"use strict";

// Runs inside the web page through chrome.scripting.executeScript({func: voiceAssistPage}).
// It must stay self-contained: Chrome serializes only this function into the page.
// Page text is data for speech; nothing read here is ever treated as a command.
function voiceAssistPage(op, args) {
  args = args || {};
  var PAGE = 5;
  var state = window.__voiceAssist || (window.__voiceAssist = {lists: {}, textOffset: 0});

  function clean(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function visible(element) {
    if (!element || !element.isConnected) return false;
    var style = window.getComputedStyle(element);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (element.closest("[aria-hidden='true']")) return false;
    var box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  }

  function accessibleName(element) {
    var labelled = element.getAttribute("aria-labelledby");
    if (labelled) {
      var parts = labelled.split(/\s+/).map(function (id) {
        var node = document.getElementById(id);
        return node ? clean(node.textContent) : "";
      }).filter(Boolean);
      if (parts.length) return parts.join(" ");
    }
    var aria = clean(element.getAttribute("aria-label"));
    if (aria) return aria;
    if (element.labels && element.labels.length) {
      var label = clean(element.labels[0].textContent);
      if (label) return label;
    }
    if (element.tagName === "INPUT" && /^(button|submit|reset)$/i.test(element.type)) {
      return clean(element.value) || clean(element.type);
    }
    var text = clean(element.innerText || element.textContent);
    if (text) return text.slice(0, 120);
    var image = element.querySelector && element.querySelector("img[alt]");
    if (image && clean(image.alt)) return clean(image.alt);
    return clean(element.getAttribute("title")) || clean(element.getAttribute("placeholder")) ||
      clean(element.getAttribute("name"));
  }

  var SELECTORS = {
    headings: "h1, h2, h3, h4, h5, h6, [role='heading']",
    links: "a[href]",
    buttons: "button, [role='button'], input[type='button'], input[type='submit'], input[type='reset']",
    fields: "input:not([type='hidden']):not([type='button']):not([type='submit']):not([type='reset']), textarea, select, [contenteditable='true']",
  };

  function collect(kind) {
    var seen = [];
    var items = [];
    var nodes = document.querySelectorAll(SELECTORS[kind]);
    for (var i = 0; i < nodes.length; i++) {
      var element = nodes[i];
      if (!visible(element)) continue;
      var name = accessibleName(element);
      if (!name) continue;
      if (kind === "links" && seen.indexOf(name + "|" + element.href) >= 0) continue;
      seen.push(name + "|" + element.href);
      var entry = {element: element, name: name};
      if (kind === "headings") {
        entry.level = Number(element.getAttribute("aria-level")) || Number((element.tagName.match(/^H(\d)$/) || [])[1]) || 0;
      }
      items.push(entry);
    }
    return items;
  }

  // Film catalogues: a site adapter first, then the generic "repeated card" guess.
  var ADAPTERS = [
    {
      name: "hdrezka",
      test: function () { return !!document.querySelector(".b-content__inline_item"); },
      cards: function () {
        return Array.prototype.map.call(document.querySelectorAll(".b-content__inline_item"), function (card) {
          var link = card.querySelector(".b-content__inline_item-link a") || card.querySelector("a[href]");
          var info = card.querySelector(".b-content__inline_item-link div");
          return link && {element: link, name: clean(link.textContent), detail: info ? clean(info.textContent) : ""};
        }).filter(Boolean);
      },
      description: function () {
        var node = document.querySelector(".b-post__description_text");
        return node ? clean(node.textContent) : "";
      },
      episodes: function () {
        return Array.prototype.slice.call(document.querySelectorAll(".b-simple_episode__item"));
      },
      search: function () { return document.querySelector("#search-field"); },
    },
  ];

  function adapter() {
    for (var i = 0; i < ADAPTERS.length; i++) if (ADAPTERS[i].test()) return ADAPTERS[i];
    return null;
  }

  function genericCards() {
    // Groups of at least four siblings that each hold a link and a picture look like a catalogue.
    var groups = new Map();
    var links = document.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      if (!visible(link)) continue;
      var card = link.closest("li, article, div");
      if (!card || !card.parentElement || !card.querySelector("img")) continue;
      var key = card.parentElement;
      if (!groups.has(key)) groups.set(key, []);
      var list = groups.get(key);
      if (list.some(function (item) { return item.card === card; })) continue;
      var title = card.querySelector("h1, h2, h3, h4, [class*='title'], [class*='name']");
      var name = clean(title ? title.textContent : "") || accessibleName(link);
      if (name) list.push({card: card, element: link, name: name.slice(0, 120), detail: ""});
    }
    var best = [];
    groups.forEach(function (list) { if (list.length >= 4 && list.length > best.length) best = list; });
    return best;
  }

  function youtubeResults() {
    var renderers = document.querySelectorAll("ytd-video-renderer, ytd-playlist-renderer, ytd-radio-renderer, " +
      "ytd-compact-video-renderer, ytd-rich-item-renderer, ytd-grid-video-renderer");
    var items = [];
    for (var i = 0; i < renderers.length; i++) {
      var title = renderers[i].querySelector("#video-title");
      if (!title || !visible(renderers[i])) continue;
      var link = title.closest("a[href]") || renderers[i].querySelector("a#thumbnail[href], a[href*='watch']");
      var name = clean(title.getAttribute("title") || title.textContent);
      if (!link || !name) continue;
      var channel = renderers[i].querySelector("#channel-name #text, ytd-channel-name #text, #byline");
      var duration = renderers[i].querySelector("ytd-thumbnail-overlay-time-status-renderer, .badge-shape-wiz__text, #time-status #text");
      var detail = [channel ? clean(channel.textContent) : "", duration ? clean(duration.textContent) : ""].filter(Boolean).join(", ");
      if (renderers[i].tagName === "YTD-PLAYLIST-RENDERER" || renderers[i].tagName === "YTD-RADIO-RENDERER") detail = "плейлист" + (detail ? ", " + detail : "");
      items.push({element: link, name: name.slice(0, 160), detail: detail});
    }
    return items;
  }

  function searchResults() {
    if (/(^|\.)youtube\.com$/.test(location.hostname)) {
      var youtube = youtubeResults();
      if (youtube.length) return youtube;
    }
    // Yandex, Google and DuckDuckGo result titles; otherwise any link that wraps a heading.
    var selectors = [".serp-item .OrganicTitle-Link", ".serp-item h2 a", "#search a:has(h3)", "a[data-testid='result-title-a']", "a:has(h2), a:has(h3)"];
    for (var i = 0; i < selectors.length; i++) {
      var nodes;
      try { nodes = document.querySelectorAll(selectors[i]); } catch (error) { continue; }
      var items = [];
      for (var j = 0; j < nodes.length; j++) {
        if (!visible(nodes[j])) continue;
        var heading = nodes[j].querySelector("h2, h3");
        var name = clean(heading ? heading.textContent : nodes[j].textContent);
        var host = "";
        try { host = new URL(nodes[j].href).hostname.replace(/^www\./, ""); } catch (error) {}
        if (name) items.push({element: nodes[j], name: name.slice(0, 160), detail: host});
      }
      if (items.length) return items;
    }
    return [];
  }

  function filmCards() {
    var site = adapter();
    return site ? site.cards() : genericCards();
  }

  function page(kind, offset, build) {
    if (offset === 0 || !state.lists[kind]) {
      state.lists[kind] = {items: build(), url: location.href};
    }
    var list = state.lists[kind];
    var slice = list.items.slice(offset, offset + PAGE).map(function (item, index) {
      return {number: offset + index + 1, name: item.name, detail: item.detail || "", level: item.level || 0};
    });
    return {kind: kind, total: list.items.length, offset: offset, items: slice};
  }

  function pick(kind, number) {
    var list = state.lists[kind];
    if (!list) return {error: "no_list"};
    var item = list.items[number - 1];
    if (!item) return {error: "no_item", total: list.items.length};
    if (list.url !== location.href || !item.element.isConnected) {
      delete state.lists[kind];
      return {error: "changed"};
    }
    return {item: item};
  }

  function mainText() {
    // An article is the most specific container; a whole <main> often also holds menus and catalogues.
    var groups = ["article", "[role='article'], .b-post__description_text", "main, [role='main'], #content, .content"];
    var best = null;
    var bestLength = 0;
    for (var g = 0; g < groups.length && bestLength < 200; g++) {
      var candidates = document.querySelectorAll(groups[g]);
      for (var i = 0; i < candidates.length; i++) {
        var length = clean(candidates[i].innerText).length;
        if (length > bestLength && visible(candidates[i])) { best = candidates[i]; bestLength = length; }
      }
    }
    if (!best || bestLength < 200) {
      var blocks = document.querySelectorAll("p");
      var parents = new Map();
      for (var j = 0; j < blocks.length; j++) {
        var parent = blocks[j].parentElement;
        parents.set(parent, (parents.get(parent) || 0) + clean(blocks[j].innerText).length);
      }
      parents.forEach(function (length, parent) { if (length > bestLength) { best = parent; bestLength = length; } });
    }
    return clean((best || document.body).innerText);
  }

  function chunk(text, offset) {
    var size = 600;
    if (offset >= text.length) return {text: "", offset: offset, more: false, total: text.length};
    var end = Math.min(text.length, offset + size);
    if (end < text.length) {
      var stop = text.lastIndexOf(". ", end);
      if (stop > offset + 200) end = stop + 1;
    }
    return {text: text.slice(offset, end).trim(), offset: end, more: end < text.length, total: text.length};
  }

  function bestVideo() {
    var videos = Array.prototype.slice.call(document.querySelectorAll("video"));
    if (!videos.length) return null;
    videos.sort(function (a, b) {
      var playing = (b.paused ? 0 : 1) - (a.paused ? 0 : 1);
      if (playing) return playing;
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return rb.width * rb.height - ra.width * ra.height;
    });
    return videos[0];
  }

  function videoState(video) {
    return {
      found: true, paused: video.paused, time: Math.round(video.currentTime), duration: isFinite(video.duration) ? Math.round(video.duration) : null,
      volume: Math.round(video.volume * 100), muted: video.muted, fullscreen: !!document.fullscreenElement,
    };
  }

  function clickByText(patterns) {
    var nodes = document.querySelectorAll("a, button, [role='button']");
    for (var i = 0; i < nodes.length; i++) {
      var name = accessibleName(nodes[i]).toLowerCase();
      for (var j = 0; j < patterns.length; j++) {
        if (name.indexOf(patterns[j]) >= 0 && visible(nodes[i])) { nodes[i].click(); return name; }
      }
    }
    return null;
  }

  switch (op) {
    case "page.summary": {
      var counts = {};
      Object.keys(SELECTORS).forEach(function (kind) { counts[kind] = collect(kind).length; });
      var first = collect("headings")[0];
      return {title: document.title, url: location.href, counts: counts, heading: first ? first.name : "",
              videos: document.querySelectorAll("video").length, films: filmCards().length};
    }
    case "page.list":
      return page(args.kind, args.offset || 0, function () { return collect(args.kind); });
    case "page.activate": {
      var picked = pick(args.kind, args.number);
      if (picked.error) return picked;
      var element = picked.item.element;
      element.scrollIntoView({block: "center"});
      if (args.kind === "fields") { element.focus(); return {done: "focused", name: picked.item.name}; }
      element.click();
      return {done: "clicked", name: picked.item.name};
    }
    case "page.text": {
      if (!args.offset) state.text = mainText();
      return chunk(state.text || mainText(), args.offset || 0);
    }
    case "page.find": {
      var needle = clean(args.text).toLowerCase();
      if (!needle) return {count: 0};
      var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      var count = 0, firstNode = null;
      while (walker.nextNode()) {
        var value = walker.currentNode.nodeValue.toLowerCase();
        if (value.indexOf(needle) >= 0 && visible(walker.currentNode.parentElement)) {
          count++;
          if (!firstNode) firstNode = walker.currentNode;
        }
      }
      if (!firstNode) return {count: 0};
      firstNode.parentElement.scrollIntoView({block: "center"});
      return {count: count, context: clean(firstNode.parentElement.innerText).slice(0, 300)};
    }
    case "page.scroll": {
      var height = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
      var target = {up: window.scrollY - window.innerHeight * 0.8, down: window.scrollY + window.innerHeight * 0.8,
                    top: 0, bottom: height}[args.direction];
      window.scrollTo(0, target);
      var range = Math.max(1, height - window.innerHeight);
      return {percent: Math.round(Math.min(1, Math.max(0, window.scrollY / range)) * 100)};
    }
    case "page.search": {
      var site = adapter();
      var box = (site && site.search && site.search()) ||
        document.querySelector("input[type='search'], input[name='q'], input[name='text'], input[name='search'], input[name='s']");
      if (!box || !visible(box)) return {error: "no_search"};
      box.focus();
      box.value = args.text;
      box.dispatchEvent(new Event("input", {bubbles: true}));
      if (box.form) {
        if (box.form.requestSubmit) box.form.requestSubmit(); else box.form.submit();
      } else {
        box.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", keyCode: 13, bubbles: true}));
      }
      return {done: true};
    }
    case "results.list":
      return page("results", args.offset || 0, searchResults);
    case "results.open": {
      var result = pick("results", args.number);
      if (result.error) return result;
      result.item.element.click();
      return {done: "clicked", name: result.item.name};
    }
    case "results.find":
    case "films.find": {
      // «Воспроизведи Дюну»: the item whose name shares the most words with the phrase.
      var kind = op === "films.find" ? "films" : "results";
      state.lists[kind] = {items: kind === "films" ? filmCards() : searchResults(), url: location.href};
      var words = clean(args.text).toLowerCase().replace(/ё/g, "е").split(" ").filter(function (word) { return word.length > 1; });
      var bestItem = null, bestScore = 0;
      state.lists[kind].items.forEach(function (item, index) {
        var name = item.name.toLowerCase().replace(/ё/g, "е");
        var score = words.filter(function (word) { return name.indexOf(word.slice(0, Math.max(3, word.length - 2))) >= 0; }).length;
        if (score > bestScore) { bestScore = score; bestItem = {item: item, number: index + 1}; }
      });
      if (!bestItem || bestScore < Math.min(words.length, Math.max(1, Math.ceil(words.length / 2)))) return {error: "not_found"};
      bestItem.item.element.click();
      return {done: "clicked", name: bestItem.item.name, number: bestItem.number};
    }
    case "films.list":
      return page("films", args.offset || 0, filmCards);
    case "films.open": {
      var film = pick("films", args.number);
      if (film.error) return film;
      film.item.element.click();
      return {done: "clicked", name: film.item.name};
    }
    case "films.description": {
      var site2 = adapter();
      var text = (site2 && site2.description && site2.description()) ||
        clean((document.querySelector("meta[name='description'], meta[property='og:description']") || {}).content);
      return {title: document.title, text: text.slice(0, 1200)};
    }
    case "video.state": {
      var video = bestVideo();
      return video ? videoState(video) : {found: false};
    }
    case "video.control": {
      var player = bestVideo();
      var action = args.action;
      if (action === "next_episode" || action === "prev_episode") {
        var site3 = adapter();
        var episodes = site3 && site3.episodes ? site3.episodes() : [];
        if (episodes.length) {
          var active = episodes.findIndex(function (item) { return item.classList.contains("active"); });
          var next = episodes[active + (action === "next_episode" ? 1 : -1)];
          if (!next) return {error: "no_episode"};
          next.click();
          return {done: "episode", name: clean(next.textContent)};
        }
        var youtubeNext = action === "next_episode" && document.querySelector(".ytp-next-button");
        if (youtubeNext && visible(youtubeNext)) { youtubeNext.click(); return {done: "episode", name: "следующее видео"}; }
        var clicked = clickByText(action === "next_episode" ? ["следующая серия", "след. серия", "next episode"] :
                                                          ["предыдущая серия", "previous episode"]);
        return clicked ? {done: "episode", name: clicked} : {error: "unsupported"};
      }
      if (action === "skip_ad") {
        var skip = document.querySelector(".ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-skip-ad-button");
        if (skip && visible(skip)) { skip.click(); return {done: "skipped"}; }
        return {error: document.querySelector(".ad-showing") ? "ad_not_skippable" : "no_ad"};
      }
      if (!player) return {found: false};
      var before = videoState(player);
      if (action === "play") {
        var promise = player.play();
        if (promise && promise.catch) promise.catch(function () {});
      } else if (action === "pause") {
        player.pause();
      } else if (action === "seek") {
        player.currentTime = Math.max(0, Math.min(player.duration || Infinity, player.currentTime + Number(args.value || 0)));
      } else if (action === "start") {
        player.currentTime = 0;
      } else if (action === "volume") {
        player.muted = false;
        player.volume = Math.max(0, Math.min(1, player.volume + Number(args.value || 0) / 100));
      } else if (action === "mute") {
        player.muted = true;
      } else if (action === "unmute") {
        player.muted = false;
      } else if (action === "exit_fullscreen") {
        if (document.fullscreenElement) document.exitFullscreen();
      } else if (action === "fullscreen") {
        // Browsers allow fullscreen only from a real click or key press, which a voice command is not.
        return {error: "needs_gesture", before: before};
      } else {
        return {error: "unsupported"};
      }
      return {before: before, after: videoState(player)};
    }
  }
  return {error: "unknown_op"};
}
