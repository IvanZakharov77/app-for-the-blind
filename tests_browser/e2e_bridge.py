"""End-to-end: VoiceAssist bridge ⇄ native host ⇄ real extension in Chromium (Linux dev check).

Run: python3 tests_browser/e2e_bridge.py   (needs node, the playwright package and Chromium)
"""

import functools
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voiceassist.browser_bridge import BridgeServer  # noqa: E402
from voiceassist.browser_commands import BrowserCommands  # noqa: E402

EXTENSION_ID = (ROOT / "chrome_extension" / "EXTENSION_ID.txt").read_text().strip()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="va-e2e-"))
    config, profile = work / "config", work / "profile"
    config.mkdir()
    host = work / "host.sh"
    script = work / "host.py"
    script.write_text("import sys\nsys.path.insert(0, {!r})\nfrom pathlib import Path\n"
                      "from voiceassist.native_host import HostRelay\n"
                      "HostRelay(sys.stdin.buffer, sys.stdout.buffer, Path({!r})).run()\n".format(str(ROOT), str(config)))
    host.write_text("#!/bin/sh\nexec 2>>'{}/host.log'\nexec '{}' -B '{}'\n".format(work, sys.executable, script))
    host.chmod(0o755)
    manifest = {"name": "com.voiceassist.bridge", "description": "test", "path": str(host), "type": "stdio",
                "allowed_origins": ["chrome-extension://{}/".format(EXTENSION_ID)]}
    # The user-level location depends on the Chromium build Playwright ships.
    folders = [profile / "NativeMessagingHosts"] + [Path.home() / ".config" / name / "NativeMessagingHosts"
               for name in ("chromium", "google-chrome-for-testing", "google-chrome")]
    folders += [Path("/etc/chromium/native-messaging-hosts"), Path("/etc/opt/chrome/native-messaging-hosts")]
    for folder in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "com.voiceassist.bridge.json").write_text(json.dumps(manifest))
        except OSError:
            pass

    class RangeHandler(http.server.SimpleHTTPRequestHandler):
        """Media seeking needs byte ranges, which the standard handler lacks."""

        def log_message(self, *args):
            pass

        def do_GET(self):
            path = Path(self.translate_path(self.path))
            header = self.headers.get("Range")
            if not header or not path.is_file():
                return super().do_GET()
            data = path.read_bytes()
            start, _, end = header.replace("bytes=", "").partition("-")
            start = int(start or 0)
            end = int(end) if end else len(data) - 1
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(str(path)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, len(data)))
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(data[start:end + 1])

    handler = functools.partial(RangeHandler, directory=str(ROOT / "tests_browser"))
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:{}/fixture.html".format(web.server_address[1])

    events = []
    bridge = BridgeServer(config / "bridge.json", on_event=events.append)
    bridge.start()
    env = dict(os.environ, NODE_PATH=os.environ.get("NODE_PATH", "/opt/node22/lib/node_modules"))
    browser = subprocess.Popen(["node", str(ROOT / "tests_browser" / "open_browser.mjs"), str(profile), url],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    failures = 0
    try:
        browser.stdout.readline()
        deadline = time.monotonic() + 30
        while not bridge.connected and time.monotonic() < deadline:
            time.sleep(0.2)
        assert bridge.connected, "extension did not connect through the native host"
        print("ok - extension connected through native host")
        commands = BrowserCommands(bridge)

        def check(name, condition):
            nonlocal failures
            print(("ok - " if condition else "FAIL - ") + name)
            failures += 0 if condition else 1

        summary = commands.page_summary()
        check("page summary: " + summary.message, summary.status == "ok" and "Каталог фильмов" in summary.message)
        films = commands.films(0)
        check("films: " + films.message, "Дюна" in films.message and "Солярис" in films.message)
        buttons = commands.page_list("buttons", 0)
        check("buttons: " + buttons.message, "Войти" in buttons.message)
        text = commands.read_text(True)
        check("text: " + text.message[:60], "абзац" in text.message)
        found = commands.find("ключевое")
        check("find: " + found.message[:60], found.status == "ok")
        play = commands.video("play")
        check("video play: " + play.message, play.status == "ok")
        seek = commands.video("seek", 60)
        check("video seek: " + seek.message, seek.status == "ok")
        pause = commands.video("pause")
        check("video pause: " + pause.message, pause.status == "ok")
        new_tab = commands.tab("new")
        check("new tab: " + new_tab.message, new_tab.status == "ok")
        tabs = commands.tabs()
        check("tabs: " + tabs.message, tabs.status == "ok" and "2" in tabs.message)
        closed = commands.tab("close")
        check("close tab: " + closed.message, closed.status == "ok")
        commands.open_url(url + "?second")
        deadline = time.monotonic() + 10
        while not events and time.monotonic() < deadline:
            time.sleep(0.2)
        check("active tab events arrive", any(event.get("event") == "active_tab" for event in events))
        check("browser state file written by host", (config / "browser_state.json").exists())
    finally:
        browser.stdin.close()
        browser.wait(20)
        bridge.stop()
        web.shutdown()
    print("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
