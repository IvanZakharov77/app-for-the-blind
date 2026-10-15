"""Chrome without the extension: its windows, its keyboard shortcuts and its address bar.

Ivan, 2026-10-15: Vega must manage Chrome by herself, without the extension («закрой хром»,
«следующая вкладка», «пауза», «что на странице» on a page opened with the mouse).
"""

import time
from typing import List, Optional, Sequence, Tuple

SUFFIXES = (" - Google Chrome", " – Google Chrome", " - Chromium")
ADDRESS_NAMES = ("адресная строка", "address and search bar", "address bar")


class ChromeWindows:
    def __init__(self, api, wait=time.sleep):
        self.api = api  # WindowsSystemAPI
        self.wait = wait

    def _windows(self) -> List[Tuple[int, str]]:
        found = []
        for handle, title in self.api.windows():
            for suffix in SUFFIXES:
                if title.endswith(suffix) or title in ("Google Chrome", "Chromium"):
                    found.append((handle, title[:-len(suffix)] if title.endswith(suffix) else ""))
                    break
        return found

    def titles(self) -> List[str]:
        """Page titles of the open Chrome windows, the most recently used first."""
        return [title or "новая вкладка" for _handle, title in self._windows()]

    def press(self, keys: Sequence[Tuple[str, tuple]]) -> bool:
        windows = self._windows()
        if not windows:
            return False
        handle = windows[0][0]
        if not self.api.activate(handle):
            self.wait(0.3)
            self.api.activate(handle)
        self.wait(0.25)
        for key, modifiers in keys:
            if not self.api.press(key, modifiers):
                return False
            self.wait(0.08)
        return True

    def close(self) -> int:
        windows = self._windows()
        for handle, _title in windows:
            self.api.close(handle)
        return len(windows)

    def address(self) -> Optional[str]:
        """The address in the front Chrome window's address bar, read through UI Automation."""
        windows = self._windows()
        if not windows:
            return None
        try:
            elements = self.api.controls(windows[0][0])
        except Exception:
            return None
        for element in elements:
            if element.role == "field" and element.value and any(name in element.name.lower() for name in ADDRESS_NAMES):
                value = element.value.strip()
                if " " in value or "." not in value:
                    return None  # typed search text, not an address
                return value if "://" in value else "https://" + value
        return None


class LazyChrome:
    """ChromeWindows made on first use, so startup does not load the Windows libraries for it."""

    def __init__(self, system_of):
        self.system_of = system_of
        self._chrome = None

    def __getattr__(self, name):
        if self._chrome is None:
            system = self.system_of()
            if system is None:
                return lambda *args: None  # no Windows libraries: every answer is «Chrome is not open»
            self._chrome = ChromeWindows(system.api, system.wait)
        return getattr(self._chrome, name)
