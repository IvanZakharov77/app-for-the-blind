"""Conservative Chrome launch and user-configured site storage."""

import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable, Optional
from urllib.parse import urlsplit

from .browser_state import loaded_requested_page


@dataclass(frozen=True)
class BrowserOutcome:
    status: str
    message: str


def valid_url(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.scheme in ("http", "https") and bool(parts.hostname)
            and not parts.username and not parts.password
            and not any(character.isspace() for character in url))


def site_key(name: str) -> str:
    """Same normalization as spoken commands: "ХД-Резка" and "хд резка" are one name."""
    return re.sub(r"[^а-яa-z0-9]+", " ", name.lower().replace("ё", "е")).strip()


class SitesStore:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("Файл сайтов повреждён.")
        return data

    def set(self, name: str, url: str) -> None:
        if not site_key(name) or len(name) > 80 or not valid_url(url):
            raise ValueError("Нужны название и адрес http/https без логина и пароля.")
        data = self._read()
        data[site_key(name)] = url
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        temporary.replace(self.path)

    def get(self, name: str) -> Optional[str]:
        data = self._read()
        key = site_key(name)
        if key in data:
            return data[key]
        if key in ("хдрезка", "хд резка", "эйч ди резка", "резка"):
            return data.get("hdrezka")
        return data.get(name.strip().lower())

    def names(self):
        return tuple(sorted(self._read()))


def find_chrome() -> Optional[Path]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
            candidate = Path(winreg.QueryValueEx(key, "")[0])
            if candidate.is_file():
                return candidate
    except (ImportError, FileNotFoundError, OSError):
        pass
    for variable, suffix in (("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
                             ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
                             ("PROGRAMFILES(X86)", "Google/Chrome/Application/chrome.exe")):
        root = os.environ.get(variable)
        if root:
            candidate = Path(root) / suffix
            if candidate.is_file():
                return candidate
    return None


def chrome_running() -> bool:
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    return any(row and row[0].lower() == "chrome.exe" for row in csv.reader(result.stdout.splitlines()))


def launch_chrome(arguments) -> None:
    subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class BrowserController:
    def __init__(self, finder: Callable[[], Optional[Path]] = find_chrome,
                 launcher: Callable = launch_chrome,
                 process_probe: Callable[[], bool] = chrome_running,
                 wait: Callable[[float], None] = time.sleep,
                 page_state_path: Optional[Path] = None,
                 clock: Callable[[], float] = time.time):
        self.finder = finder
        self.launcher = launcher
        self.process_probe = process_probe
        self.wait = wait
        self.page_state_path = page_state_path or (Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist" / "browser_state.json" if sys.platform == "win32" else None)
        self.clock = clock

    def _launch(self, url: Optional[str] = None) -> BrowserOutcome:
        chrome = self.finder()
        if chrome is None:
            return BrowserOutcome("error", "Google Chrome не найден на компьютере.")
        try:
            launched_at = self.clock()
            self.launcher([str(chrome)] + ([url] if url else []))
            for _ in range(10):
                if self.process_probe():
                    if url:
                        if self.page_state_path is not None:
                            for _ in range(40):
                                if loaded_requested_page(self.page_state_path, url, launched_at):
                                    return BrowserOutcome("ok", "Страница загружена в Chrome.")
                                self.wait(0.25)
                        return BrowserOutcome("unverified", "Адрес передан Chrome. Загрузка страницы пока не проверена.")
                    return BrowserOutcome("ok", "Процесс Chrome запущен.")
                self.wait(0.25)
        except (OSError, subprocess.SubprocessError) as error:
            return BrowserOutcome("error", "Не удалось запустить Chrome: {}.".format(error))
        return BrowserOutcome("unverified", "Chrome получил команду запуска, но его работу не удалось подтвердить.")

    def open_browser(self) -> BrowserOutcome:
        return self._launch()

    def open_site(self, url: str) -> BrowserOutcome:
        if not valid_url(url):
            return BrowserOutcome("error", "Адрес сайта должен начинаться с http или https.")
        return self._launch(url)
