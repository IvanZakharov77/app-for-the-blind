// Checks chrome_extension/page.js in a real Chromium page.
// Run: NODE_PATH=<global node_modules> node tests_browser/test_page.mjs (needs the playwright package).
import { createRequire } from "module";
import { readFileSync } from "fs";
import { createServer } from "http";
import { fileURLToPath } from "url";
import path from "path";
import assert from "assert/strict";

const { chromium } = createRequire(import.meta.url)("playwright");
const here = path.dirname(fileURLToPath(import.meta.url));
const pageScript = readFileSync(path.join(here, "..", "chrome_extension", "page.js"), "utf8");
const server = createServer((request, response) => {
  const name = request.url === "/" ? "fixture.html" : request.url.slice(1).split("?")[0];
  try {
    const body = readFileSync(path.join(here, name));
    response.writeHead(200, {"Content-Type": name.endsWith(".wav") ? "audio/wav" : "text/html; charset=utf-8", "Accept-Ranges": "bytes"});
    response.end(body);
  } catch (error) { response.writeHead(404); response.end(); }
}).listen(0);
const url = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({executablePath: process.env.CHROMIUM || undefined, args: ["--autoplay-policy=no-user-gesture-required"]});
const page = await browser.newPage();
await page.goto(url);
await page.addScriptTag({content: pageScript});
const run = (op, args) => page.evaluate(([op, args]) => voiceAssistPage(op, args), [op, args]);
let passed = 0;
async function check(name, fn) { await fn(); passed++; console.log("ok -", name); }

await check("summary counts visible elements", async () => {
  const s = await run("page.summary");
  assert.equal(s.title, "Каталог фильмов");
  assert.equal(s.heading, "Фильмы онлайн");
  assert.equal(s.films, 3);
  assert.equal(s.videos, 1);
});
await check("links use accessible names and skip hidden", async () => {
  const links = await run("page.list", {kind: "links", offset: 0});
  const names = links.items.map(i => i.name);
  assert.ok(names.includes("Новинки кино"));
  assert.ok(!names.includes("Скрытая"));
  assert.equal(links.items[0].number, 1);
});
await check("buttons include role=button and paging", async () => {
  const buttons = await run("page.list", {kind: "buttons", offset: 0});
  const names = buttons.items.map(i => i.name);
  assert.ok(names.includes("Войти") && names.includes("Меню"));
});
await check("activate clicks the numbered button", async () => {
  const buttons = await run("page.list", {kind: "buttons", offset: 0});
  const number = buttons.items.find(i => i.name === "Войти").number;
  const result = await run("page.activate", {kind: "buttons", number});
  assert.equal(result.done, "clicked");
  assert.equal(await page.textContent("#b1"), "Нажато");
});
await check("changed page invalidates numbers", async () => {
  await run("page.list", {kind: "buttons", offset: 0});
  await page.evaluate(() => document.querySelector("#b1").remove());
  const buttons = await page.evaluate(() => window.__voiceAssist.lists.buttons.items.map(i => i.name));
  const number = buttons.indexOf("Нажато") + 1;
  const result = await run("page.activate", {kind: "buttons", number});
  assert.equal(result.error, "changed");
});
await check("main text comes from the article in chunks", async () => {
  const first = await run("page.text", {offset: 0});
  assert.ok(first.text.startsWith("Статья") || first.text.includes("Первый абзац"));
  assert.ok(!first.text.includes("Войти"));
});
await check("find scrolls to text and counts matches", async () => {
  const found = await run("page.find", {text: "ключевое"});
  assert.equal(found.count, 1);
  assert.ok(found.context.includes("ключевое"));
  assert.equal((await run("page.find", {text: "нет такого"})).count, 0);
});
await check("scroll reports position", async () => {
  assert.equal((await run("page.scroll", {direction: "bottom"})).percent, 100);
  assert.equal((await run("page.scroll", {direction: "top"})).percent, 0);
});
await check("site search fills and submits the form", async () => {
  await run("page.search", {text: "дюна"});
  assert.equal(await page.title(), "поиск: дюна");
});
await check("film adapter lists cards with details and opens one", async () => {
  const films = await run("films.list", {offset: 0});
  assert.equal(films.total, 3);
  assert.deepEqual(films.items.map(i => i.name), ["Дюна", "Интерстеллар", "Солярис"]);
  assert.equal(films.items[0].detail, "2021, США, Фантастика");
  await run("films.open", {number: 2});
  assert.ok(page.url().endsWith("#film-2"));
  assert.equal((await run("films.description")).text, "Фильм о пустынной планете и борьбе за пряность.");
});
await check("video play, seek, volume and pause change real state", async () => {
  await page.waitForFunction(() => document.querySelector("#v").readyState >= 1);
  let r = await run("video.control", {action: "play"});
  await page.waitForTimeout(500);
  assert.equal((await run("video.state")).paused, false);
  r = await run("video.control", {action: "seek", value: 60});
  assert.ok(r.after.time >= 59);
  r = await run("video.control", {action: "seek", value: -30});
  assert.ok(r.after.time >= 29 && r.after.time <= 32);
  r = await run("video.control", {action: "volume", value: -30});
  assert.equal(r.after.volume, 70);
  r = await run("video.control", {action: "pause"});
  assert.equal(r.after.paused, true);
  assert.equal((await run("video.control", {action: "fullscreen"})).error, "needs_gesture");
});
await check("next episode uses the site adapter", async () => {
  const r = await run("video.control", {action: "next_episode"});
  assert.equal(r.name, "Серия 2");
  assert.equal(await page.evaluate(() => document.querySelector(".b-simple_episodes__list").dataset.ep), "2");
});
await check("generic catalogue without adapter", async () => {
  await page.setContent(`<ul>${["Один","Два","Три","Четыре","Пять","Шесть"].map(n => `<li><a href="#${n}"><img src="data:," alt="" width="10" height="10"><span class="title">${n}</span></a></li>`).join("")}</ul>`);
  await page.addScriptTag({content: pageScript});
  const films = await run("films.list", {offset: 0});
  assert.equal(films.total, 6);
  assert.equal(films.items.length, 5);
  const more = await run("films.list", {offset: 5});
  assert.deepEqual(more.items.map(i => i.name), ["Шесть"]);
});

await check("search results are numbered with their site", async () => {
  await page.setContent(`<div id="search"><div><a href="https://ru.wikipedia.org/wiki/Дюна"><h3>Дюна — Википедия</h3></a></div><div><a href="https://www.kinopoisk.ru/film/1"><h3>Дюна (2021) — Кинопоиск</h3></a></div></div>`);
  await page.addScriptTag({content: pageScript});
  const results = await run("results.list", {offset: 0});
  assert.deepEqual(results.items.map(i => i.name), ["Дюна — Википедия", "Дюна (2021) — Кинопоиск"]);
  assert.equal(results.items[1].detail, "kinopoisk.ru");
});

await check("youtube results with channel and duration, play by name", async () => {
  const html = `<!doctype html><meta charset="utf-8"><title>YouTube</title>
    <ytd-video-renderer style="display:block"><a id="thumbnail" href="/watch?v=1"><ytd-thumbnail-overlay-time-status-renderer>3:45</ytd-thumbnail-overlay-time-status-renderer></a>
    <a id="video-title" href="/watch?v=1" title="Кино — Группа крови">Кино — Группа крови</a><ytd-channel-name><span id="text">Кино</span></ytd-channel-name></ytd-video-renderer>
    <ytd-video-renderer style="display:block"><a id="thumbnail" href="/watch?v=2"></a><a id="video-title" href="/watch?v=2" title="Ария — Беспечный ангел">Ария — Беспечный ангел</a></ytd-video-renderer>
    <ytd-playlist-renderer style="display:block"><a href="/playlist?list=3"><span id="video-title" title="Русский рок">Русский рок</span></a></ytd-playlist-renderer>`;
  await page.route("https://www.youtube.com/**", route => route.fulfill({contentType: "text/html; charset=utf-8", body: html}));
  await page.goto("https://www.youtube.com/results?search_query=rock");
  await page.addScriptTag({content: pageScript});
  const results = await run("results.list", {offset: 0});
  assert.deepEqual(results.items.map(i => i.name), ["Кино — Группа крови", "Ария — Беспечный ангел", "Русский рок"]);
  assert.equal(results.items[0].detail, "Кино, 3:45");
  assert.equal(results.items[2].detail, "плейлист");
  await page.addScriptTag({content: pageScript});
  const played = await run("results.find", {text: "беспечного ангела"});
  assert.equal(played.name, "Ария — Беспечный ангел");
  assert.equal(played.number, 2);
  await page.waitForURL(/v=2/);
  await page.addScriptTag({content: pageScript});
  assert.equal((await run("results.find", {text: "металлика"})).error, "not_found");
});

console.log(`${passed} browser checks passed`);
await browser.close();
server.close();
