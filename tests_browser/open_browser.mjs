// Opens Chromium with the VoiceAssist extension at the given URL and waits until stdin closes.
import { createRequire } from "module";
import path from "path";
import { fileURLToPath } from "url";

const { chromium } = createRequire(import.meta.url)("playwright");
const here = path.dirname(fileURLToPath(import.meta.url));
const extension = path.join(here, "..", "chrome_extension");
const [profile, url] = process.argv.slice(2);
const context = await chromium.launchPersistentContext(profile, {
  channel: "chromium", headless: true,
  args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`, "--autoplay-policy=no-user-gesture-required"],
});
const page = context.pages()[0] || await context.newPage();
await page.goto(url);
await page.bringToFront();
console.log("ready");
process.stdin.resume();
process.stdin.on("end", async () => { await context.close(); process.exit(0); });
