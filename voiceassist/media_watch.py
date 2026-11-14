"""Ctrl closes the player Vega opened for a song or a video (Ivan, 2026-11-14).

A person asked Vega to play a file from a flash drive. Windows opened it in its default player, the music
drowned «Вега, стоп», and Ctrl did nothing: the player is not Vega's. Which player it is differs from one
computer to another, so Vega does not guess by name alone. Before opening the file she notes the programs
that already have windows; afterwards the new one is the player (or a known player that took the file).
Ctrl then closes only that program. Explorer, browsers, Vega herself and Windows' own programs are never
closed, and nothing is closed when Vega did not start the playback.
"""

import os
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

MEDIA = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".wma", ".aac", ".opus", ".mid", ".midi", ".amr",
         ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".mpg", ".mpeg", ".m4v", ".3gp", ".webm", ".flv", ".vob")
# Players people have; a file handed to one already running opens no new program.
PLAYERS = ("wmplayer.exe", "vlc.exe", "aimp.exe", "aimp3.exe", "foobar2000.exe", "winamp.exe", "potplayermini.exe",
           "potplayermini64.exe", "potplayer.exe", "mpc-hc.exe", "mpc-hc64.exe", "mpc-be.exe", "mpc-be64.exe",
           "kmplayer.exe", "gom.exe", "mpv.exe", "musicbee.exe", "itunes.exe", "lightalk.exe", "daumpotplayer.exe",
           "music.ui.exe", "video.ui.exe", "microsoft.media.player.exe", "zune.exe", "smplayer.exe", "jetaudio.exe")
# Never closed, whatever opened: Windows itself, browsers (the file may be one tab of many), Vega.
NEVER = ("explorer.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "svchost.exe", "taskmgr.exe", "sihost.exe",
         "shellexperiencehost.exe", "startmenuexperiencehost.exe", "searchui.exe", "searchapp.exe", "searchhost.exe",
         "textinputhost.exe", "lockapp.exe", "systemsettings.exe", "ctfmon.exe", "rundll32.exe", "dllhost.exe",
         "conhost.exe", "cmd.exe", "powershell.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe",
         "browser.exe", "iexplore.exe", "brave.exe", "nvda.exe", "narrator.exe", "jfw.exe", "voiceassist.exe",
         "voiceassistnativehost.exe", "voiceassistsetup.exe", "piper.exe", "cscript.exe", "wscript.exe",
         "python.exe", "pythonw.exe", "applicationframehost.exe")
# Windows 10/11 players live inside ApplicationFrameHost: known by their window title instead.
FRAME_TITLES = ("медиаплеер", "media player", "groove", "музыка groove", "кино и тв", "movies & tv", "фильмы и тв")
WAIT = 8.0  # seconds a slow old laptop may need to show the player


def is_media(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in MEDIA


class Windows:
    """Top-level visible windows: [(handle, pid, exe name lower-case, title, class)]. Windows only."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

    def list(self) -> List[Tuple[int, int, str, str, str]]:
        ctypes, wintypes = self.ctypes, self.wintypes
        found = []
        names: Dict[int, str] = {}

        def visit(handle, _param):
            if not self.user32.IsWindowVisible(handle) or self.user32.GetWindow(handle, 4):  # 4 = GW_OWNER
                return True
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            if pid.value not in names:
                names[pid.value] = self._exe(pid.value)
            title = ctypes.create_unicode_buffer(256)
            self.user32.GetWindowTextW(handle, title, 256)
            kind = ctypes.create_unicode_buffer(128)
            self.user32.GetClassNameW(handle, kind, 128)
            if title.value:
                found.append((int(handle), pid.value, names[pid.value], title.value, kind.value))
            return True

        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
        self.user32.EnumWindows(callback, 0)
        return found

    def _exe(self, pid: int) -> str:
        ctypes, wintypes = self.ctypes, self.wintypes
        process = self.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION, Vista and up
        if not process:
            return ""
        try:
            size = wintypes.DWORD(520)
            buffer = ctypes.create_unicode_buffer(520)
            if self.kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return os.path.basename(buffer.value).lower()
            return ""
        finally:
            self.kernel32.CloseHandle(process)

    def close(self, handle: int) -> None:
        self.user32.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE: the player closes itself, as by its ×

    def alive(self, handle: int) -> bool:
        return bool(self.user32.IsWindow(handle))

    def kill(self, pid: int) -> None:
        process = self.kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if process:
            self.kernel32.TerminateProcess(process, 1)
            self.kernel32.CloseHandle(process)


def is_player(window: Tuple[int, int, str, str, str]) -> bool:
    _handle, _pid, exe, title, kind = window
    if exe in PLAYERS:
        return True
    return kind == "ApplicationFrameWindow" and any(name in title.lower() for name in FRAME_TITLES)


def closable(window: Tuple[int, int, str, str, str]) -> bool:
    exe = window[2]
    return is_player(window) or (bool(exe) and exe not in NEVER)


class MediaWatch:
    """Remembers the player Vega opened; Ctrl (or «выключи музыку») closes it."""

    def __init__(self, windows=None, key_pressed: Optional[Callable[[], bool]] = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.windows = windows
        self.clock, self.sleep = clock, sleep
        self.player: List[Tuple[int, int, str, str, str]] = []  # the player's windows
        self.lock = threading.Lock()
        if key_pressed is not None and windows is not None:
            threading.Thread(target=self._watch_key, args=(key_pressed,), name="vega-media-ctrl", daemon=True).start()

    def launcher(self, open_file: Callable[[str], None]) -> Callable[[str], None]:
        """open_file wrapped: for a song or a video, the player that shows up is remembered."""
        def launch(path: str) -> None:
            if self.windows is None or not is_media(path):
                open_file(path)
                return
            try:
                before = self.windows.list()
            except Exception:
                before = None
            open_file(path)
            if before is not None:
                threading.Thread(target=self._find_player, args=(before,), name="vega-media-find", daemon=True).start()
        return launch

    def _find_player(self, before) -> None:
        old_pids: Set[int] = {window[1] for window in before}
        old_handles: Set[int] = {window[0] for window in before}
        deadline = self.clock() + WAIT
        while self.clock() < deadline:
            self.sleep(0.5)
            try:
                now = self.windows.list()
            except Exception:
                return
            new = [window for window in now if window[1] not in old_pids and closable(window)]
            if not new:  # a player that was already open took the file, or a new Windows 10 player frame
                new = [window for window in now if is_player(window)
                       and (window[0] not in old_handles or window[2] in PLAYERS)]
            if new:
                with self.lock:
                    self.player = new
                return

    @property
    def playing(self) -> bool:
        with self.lock:
            player = list(self.player)
        if not player or self.windows is None:
            return False
        alive = [window for window in player if self.windows.alive(window[0])]
        with self.lock:
            self.player = alive
        return bool(alive)

    def close(self) -> bool:
        """Closes the remembered player; True when there was one."""
        with self.lock:
            player, self.player = list(self.player), []
        if not player or self.windows is None:
            return False
        for window in player:
            if self.windows.alive(window[0]):
                self.windows.close(window[0])
        self.sleep(2.0)
        for window in player:  # a player that asks «save?» or hangs: its own process only, never a frame host
            if self.windows.alive(window[0]) and window[2] not in NEVER and window[2]:
                self.windows.kill(window[1])
        return True

    def _watch_key(self, key_pressed: Callable[[], bool]) -> None:
        while True:
            self.sleep(0.1)
            with self.lock:
                armed = bool(self.player)
            if armed and key_pressed() and self.playing:
                self.close()


def start(key_pressed: Callable[[], bool]) -> MediaWatch:
    if sys.platform != "win32":
        return MediaWatch()
    try:
        return MediaWatch(Windows(), key_pressed)
    except Exception:
        return MediaWatch()
