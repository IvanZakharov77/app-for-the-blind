"""Vega updates herself from the project's GitHub releases (Ivan, 2026-10-27).

Once a day, in the background, Vega asks GitHub for the latest release. When its version is newer,
she quietly downloads Vega-Setup.exe (checking its size and SHA-256), and at the first quiet moment
says that she is updating, starts the installer silently and closes. The installer replaces the
programs, keeps the settings and the Gemini key, and starts the new Vega.
Without internet nothing happens; every failure goes to last-error.log only.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.request import Request

from . import __version__

LATEST = "https://api.github.com/repos/IvanZakharov77/app-for-the-blind/releases/latest"
ASSET = "Vega-Setup.exe"
DAY = 24 * 3600.0
FIRST_CHECK = 300.0  # seconds after start: the PC is busy starting up before that
IDLE = 300.0  # an update is installed only when nobody spoke to Vega for this long
INSTALL_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/vegaupdate=1")
UPDATING = "Вышла новая версия Веги. Сейчас я обновлюсь и через минуту снова буду с вами."
LATEST_ALREADY = "У вас последняя версия Веги, {}."
NO_ANSWER = "Не удалось проверить обновления: нет связи с интернетом."
DOWNLOADING = "Вышла версия {}. Скачиваю её, это займёт несколько минут. Когда скачаю, обновлюсь сама."


def version_tuple(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:4])


def newer(tag: str, current: str = __version__) -> bool:
    found = version_tuple(tag)
    return bool(found) and found > version_tuple(current)


def _get(url: str, timeout: float, accept: str):
    from .net import open_url
    return open_url(Request(url, headers={"User-Agent": "Vega/" + __version__, "Accept": accept}), timeout)


def latest_release(fetch=_get) -> Optional[dict]:
    """{"version", "url", "size", "sha256"} of the latest release's installer, or None."""
    with fetch(LATEST, 20, "application/vnd.github+json") as response:
        data = json.loads(response.read().decode("utf-8"))
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET and asset.get("browser_download_url"):
            digest = str(asset.get("digest") or "")
            return {"version": str(data.get("tag_name", "")).lstrip("v"), "url": asset["browser_download_url"],
                    "size": int(asset.get("size") or 0),
                    "sha256": digest[7:].lower() if digest.startswith("sha256:") else ""}
    return None


def download(release: dict, folder: Path, fetch=_get) -> Path:
    """The installer in folder, downloaded once; a broken or partial file is never kept."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "Vega-Setup-{}.exe".format(release["version"])
    for old in folder.glob("Vega-Setup-*"):
        if old != target:
            try:
                old.unlink()
            except OSError:
                pass
    if target.exists() and _matches(target, release):
        return target
    part = target.with_suffix(".part")
    digest = hashlib.sha256()
    with fetch(release["url"], 60, "application/octet-stream") as response, open(str(part), "wb") as out:
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            digest.update(block)
            out.write(block)
    if not _matches(part, release, digest.hexdigest()):
        part.unlink()
        raise ValueError("скачанный установщик повреждён")
    os.replace(str(part), str(target))
    return target


def _matches(path: Path, release: dict, sha256: str = "") -> bool:
    if release["size"] and path.stat().st_size != release["size"]:
        return False
    with open(str(path), "rb") as handle:
        if handle.read(2) != b"MZ":
            return False
    if release["sha256"]:
        if not sha256:
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        return sha256 == release["sha256"]
    return True


# Ivan, 2026-10-27: after «проверь обновления» the silent install failed and Vega no longer started at
# all. A file still in use makes a silent Inno Setup give up halfway. So the installer runs through this
# script: on failure it waits, stops what may hold the files and tries again; the third time it is shown
# on the screen, so a person sees what is wrong. Each run writes a log next to it for the report.
RETRY_SCRIPT = """@echo off
cd /d "%~dp0"
"%~dp0{name}" {args} /LOG="%~dp0install-1.log"
if not errorlevel 1 exit /b 0
timeout /t 20 /nobreak >nul
taskkill /F /T /IM VoiceAssist.exe >nul 2>&1
taskkill /F /T /IM VoiceAssistNativeHost.exe >nul 2>&1
taskkill /F /T /IM piper.exe >nul 2>&1
timeout /t 5 /nobreak >nul
"%~dp0{name}" {args} /LOG="%~dp0install-2.log"
if not errorlevel 1 exit /b 0
"%~dp0{name}" /SP- /vegaupdate=1 /LOG="%~dp0install-3.log"
"""
LOGS = ("install-1.log", "install-2.log", "install-3.log")


def launch(installer: Path) -> None:
    """Start the silent installer on its own; it closes this Vega and starts the new one."""
    for log in LOGS:
        try:
            (installer.parent / log).unlink()
        except OSError:
            pass
    script = installer.parent / "update.cmd"
    script.write_bytes(RETRY_SCRIPT.format(name=installer.name, args=" ".join(INSTALL_ARGS))
                       .replace("\n", "\r\n").encode("ascii"))
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    command = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
    subprocess.Popen([command, "/C", str(script)], close_fds=True, creationflags=flags,
                     cwd=str(installer.parent))


def install_log_tail(folder: Optional[Path] = None, lines: int = 25) -> str:
    """The end of the last update's installer log, for the report."""
    folder = folder or Path(tempfile.gettempdir()) / "VoiceAssist-update"
    found = [folder / log for log in LOGS if (folder / log).is_file()]
    if not found:
        return "(обновлений через Вегу не было)"
    text = found[-1].read_bytes().decode("utf-8", "replace").splitlines()
    return "{}:\n{}".format(found[-1].name, "\n".join(text[-lines:]))


class Updater:
    """Background checks once a day; listen_forever asks ready() at quiet moments and calls install()."""

    def __init__(self, state: Path, folder: Path, log: Callable[[str], None] = lambda message: None,
                 latest=latest_release, fetch=download, start=launch, quit=lambda: os._exit(0),
                 clock=time.time, current: str = __version__):
        self.state, self.folder, self.log = state, folder, log
        self.latest, self.fetch, self.start, self.quit = latest, fetch, start, quit
        self.clock, self.current = clock, current
        self.installer: Optional[Path] = None
        self.asked = False
        self.lock = threading.Lock()

    def _checked(self) -> float:
        try:
            return float(json.loads(self.state.read_text(encoding="utf-8")).get("checked", 0))
        except (OSError, ValueError, AttributeError):
            return 0.0

    def _mark(self) -> None:
        try:
            self.state.parent.mkdir(parents=True, exist_ok=True)
            self.state.write_text(json.dumps({"checked": self.clock()}), encoding="utf-8")
        except OSError:
            pass

    def check(self, force: bool = False) -> Optional[str]:
        """The newer version found ("" when this one is the latest); None when GitHub did not answer."""
        if not force and self.clock() - self._checked() < DAY:
            return ""
        with self.lock:
            try:
                release = self.latest()
            except Exception as error:
                self.log("Проверка обновлений не удалась: {}".format(error))
                return None
            self._mark()
            if not release or not newer(release["version"], self.current):
                return ""
            try:
                self.installer = self.fetch(release, self.folder)
            except Exception as error:
                self.log("Обновление {} не скачалось: {}".format(release["version"], error))
                return None
            return release["version"]

    def ask(self) -> str:
        """«Вега, проверь обновления»: the answer to say now; a newer version downloads in the background."""
        self.asked = True
        if self.installer is not None:
            return UPDATING
        try:
            release = self.latest()
        except Exception as error:
            self.log("Проверка обновлений не удалась: {}".format(error))
            return NO_ANSWER
        if not release or not newer(release["version"], self.current):
            return LATEST_ALREADY.format(self.current)
        self.worker = threading.Thread(target=self.check, args=(True,), name="vega-update-download", daemon=True)
        self.worker.start()
        return DOWNLOADING.format(release["version"])

    def ready(self, idle_for: float) -> bool:
        """An update is waiting and nobody spoke to Vega for IDLE seconds (or the person asked for it)."""
        return self.installer is not None and (self.asked or idle_for >= IDLE)

    def install(self) -> None:
        try:
            self.start(self.installer)
        except OSError as error:
            self.log("Установщик обновления не запустился: {}".format(error))
            self.installer = None
            return
        self.quit()

    def run_forever(self, sleep=time.sleep) -> None:
        sleep(FIRST_CHECK)
        while self.installer is None:
            self.check()
            sleep(3600)

    def begin(self) -> None:
        threading.Thread(target=self.run_forever, name="vega-updates", daemon=True).start()


def start_updater(config_dir: Path, log: Callable[[str], None]) -> Optional[Updater]:
    """Only the installed Vega updates herself, never a copy run from the source code."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return None
    updater = Updater(config_dir / "update.json", Path(tempfile.gettempdir()) / "VoiceAssist-update", log)
    updater.begin()
    return updater
