"use strict";

// One long-lived Native Messaging port to the local VoiceAssist host.
// The host may only ask for the operations in OPS; anything else is refused.
importScripts("page.js");

var HOST = "com.voiceassist.bridge";
var port = null;

var PAGE_OPS = ["page.summary", "page.list", "page.activate", "page.text", "page.find", "page.scroll",
                "page.search", "results.list", "results.open", "results.find", "films.find", "films.list", "films.open", "films.description"];
var FRAME_OPS = ["video.state", "video.control"];

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST);
  } catch (error) {
    port = null;
    return;
  }
  port.onMessage.addListener(onRequest);
  port.onDisconnect.addListener(function () {
    void chrome.runtime.lastError;
    port = null;
  });
  reportActive();
}

function send(message) {
  connect();
  if (port) {
    try { port.postMessage(message); } catch (error) { port = null; }
  }
}

function report(tab) {
  if (!tab || !tab.active || tab.status !== "complete" || !/^https?:\/\//.test(tab.url || "") || !tab.title) return;
  send({event: "active_tab", url: tab.url, title: tab.title});
}

function reportActive() {
  chrome.tabs.query({active: true, lastFocusedWindow: true}, function (tabs) {
    if (!chrome.runtime.lastError && tabs && tabs[0]) report(tabs[0]);
  });
}

chrome.tabs.onUpdated.addListener(function (tabId, changeInfo, tab) {
  if (changeInfo.status === "complete") report(tab);
});
chrome.tabs.onActivated.addListener(function (info) {
  chrome.tabs.get(info.tabId, function (tab) { if (!chrome.runtime.lastError) report(tab); });
});
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(function () {
  chrome.alarms.create("voiceassist-reconnect", {periodInMinutes: 1});
  connect();
});
chrome.alarms.onAlarm.addListener(function () { connect(); });
connect();

function activeTab() {
  return new Promise(function (resolve, reject) {
    chrome.tabs.query({active: true, lastFocusedWindow: true}, function (tabs) {
      if (chrome.runtime.lastError || !tabs || !tabs[0]) reject(new Error("no_tab"));
      else resolve(tabs[0]);
    });
  });
}

function call(fn) {
  var extra = Array.prototype.slice.call(arguments, 1);
  return new Promise(function (resolve, reject) {
    fn.apply(null, extra.concat([function (value) {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(value);
    }]));
  });
}

function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

function inPage(tab, op, args, allFrames) {
  if (!/^https?:\/\//.test(tab.url || "")) return Promise.reject(new Error("not_web_page"));
  return call(chrome.scripting.executeScript.bind(chrome.scripting),
              {target: {tabId: tab.id, allFrames: !!allFrames}, func: voiceAssistPage, args: [op, args || {}]})
    .then(function (results) {
      if (!allFrames) return results[0] && results[0].result;
      // Video can live in an embedded player frame: answer from the first frame that has one.
      var found = results.filter(function (item) { return item.result && item.result.found !== false && !item.result.error; });
      var chosen = found[0] || results[0];
      return chosen ? Object.assign({frameId: chosen.frameId}, chosen.result) : {found: false};
    });
}

function tabInfo(tab, index) {
  return {number: index + 1, title: tab.title || "", url: tab.url || "", active: !!tab.active};
}

function handle(op, args) {
  if (PAGE_OPS.indexOf(op) >= 0) return activeTab().then(function (tab) { return inPage(tab, op, args, false); });
  if (op === "video.state") return activeTab().then(function (tab) { return inPage(tab, op, args, true); });
  if (op === "video.control") {
    return activeTab().then(function (tab) {
      return inPage(tab, op, args, true).then(function (result) {
        if (!result || result.error || !result.before || result.frameId === undefined) return result;
        // play() is asynchronous: check the real state a moment later instead of trusting the call.
        return wait(800).then(function () {
          return call(chrome.scripting.executeScript.bind(chrome.scripting),
                      {target: {tabId: tab.id, frameIds: [result.frameId]}, func: voiceAssistPage, args: ["video.state", {}]});
        }).then(function (later) {
          result.after = later[0] && later[0].result;
          return result;
        });
      });
    });
  }
  switch (op) {
    case "tabs.list":
      return call(chrome.tabs.query.bind(chrome.tabs), {lastFocusedWindow: true}).then(function (tabs) { return {tabs: tabs.map(tabInfo)}; });
    case "tabs.new":
      return call(chrome.tabs.create.bind(chrome.tabs), {url: args.url || "chrome://newtab/"}).then(function (tab) { return {done: true, id: tab.id}; });
    case "tabs.close":
      return activeTab().then(function (tab) {
        return call(chrome.tabs.remove.bind(chrome.tabs), tab.id).then(function () { return {done: true, title: tab.title}; });
      });
    case "tabs.next":
    case "tabs.prev":
      return call(chrome.tabs.query.bind(chrome.tabs), {lastFocusedWindow: true}).then(function (tabs) {
        var current = tabs.findIndex(function (tab) { return tab.active; });
        var next = tabs[(current + (op === "tabs.next" ? 1 : tabs.length - 1)) % tabs.length];
        return call(chrome.tabs.update.bind(chrome.tabs), next.id, {active: true}).then(function (tab) { return {done: true, title: tab.title}; });
      });
    case "tabs.activate":
      return call(chrome.tabs.query.bind(chrome.tabs), {lastFocusedWindow: true}).then(function (tabs) {
        var target = args.number ? tabs[args.number - 1] : tabs.find(function (tab) {
          try { return new URL(tab.url).hostname.replace(/^www\./, "") === args.host; } catch (error) { return false; }
        });
        if (!target) return {error: "no_tab"};
        return call(chrome.tabs.update.bind(chrome.tabs), target.id, {active: true}).then(function (tab) { return {done: true, title: tab.title}; });
      });
    case "nav.back":
      return activeTab().then(function (tab) { return call(chrome.tabs.goBack.bind(chrome.tabs), tab.id); }).then(function () { return {done: true}; });
    case "nav.forward":
      return activeTab().then(function (tab) { return call(chrome.tabs.goForward.bind(chrome.tabs), tab.id); }).then(function () { return {done: true}; });
    case "nav.reload":
      return activeTab().then(function (tab) { return call(chrome.tabs.reload.bind(chrome.tabs), tab.id, {}); }).then(function () { return {done: true}; });
    case "nav.open":
      if (!/^https?:\/\//.test(args.url || "")) return Promise.reject(new Error("bad_url"));
      return activeTab().then(function (tab) {
        return call(chrome.tabs.update.bind(chrome.tabs), tab.id, {url: args.url});
      }, function () {
        return call(chrome.tabs.create.bind(chrome.tabs), {url: args.url});
      }).then(function () { return {done: true}; });
    case "open.special": {
      var pages = {history: "chrome://history/", downloads: "chrome://downloads/", bookmarks: "chrome://bookmarks/"};
      if (!pages[args.page]) return Promise.reject(new Error("bad_page"));
      return call(chrome.tabs.create.bind(chrome.tabs), {url: pages[args.page]}).then(function () { return {done: true}; });
    }
    case "bookmark.add":
      return activeTab().then(function (tab) {
        if (!/^https?:\/\//.test(tab.url || "")) return {error: "not_web_page"};
        return call(chrome.bookmarks.search.bind(chrome.bookmarks), {url: tab.url}).then(function (found) {
          if (found.length) return {done: "exists", title: tab.title};
          return call(chrome.bookmarks.create.bind(chrome.bookmarks), {title: tab.title, url: tab.url}).then(function () {
            return {done: "added", title: tab.title};
          });
        });
      });
    case "bookmark.list":
      return call(chrome.bookmarks.getRecent.bind(chrome.bookmarks), 20).then(function (items) {
        return {items: items.filter(function (item) { return item.url; }).map(function (item) { return {title: item.title, url: item.url}; })};
      });
    case "history.recent":
      if (!chrome.history) return {error: "unsupported"};
      return call(chrome.history.search.bind(chrome.history), {text: "", maxResults: 10}).then(function (items) {
        return {items: items.map(function (item) { return {title: item.title, url: item.url}; })};
      });
    case "browser.close":
      return call(chrome.windows.getAll.bind(chrome.windows), {}).then(function (windows) {
        return Promise.all(windows.map(function (item) { return call(chrome.windows.remove.bind(chrome.windows), item.id); }));
      }).then(function () { return {done: true}; });
  }
  return Promise.reject(new Error("unknown_op"));
}

function onRequest(message) {
  if (!message || typeof message.id !== "number" || typeof message.op !== "string") return;
  handle(message.op, message.args || {}).then(function (result) {
    send({id: message.id, ok: true, result: result || {}});
  }, function (error) {
    send({id: message.id, ok: false, error: String(error && error.message || error)});
  });
}
