"""Ctrl twice: Vega listens even when the laptop is loud (Ivan, 2026-11-14).

The microphone hears the laptop's own speakers (a video, music, a ringing call) louder than the person, so
«Вега» is lost. Two quick presses of Ctrl mute the laptop's sound, Vega beeps and takes the next phrase as a
command, without the word «Вега»; the sound comes back before she answers. A single Ctrl still stops speech
and media as before. Ctrl+C, Ctrl+V and other combinations never count: another key held with Ctrl spoils it.
"""

import sys
import threading
import time
from typing import Callable, Optional

VK_CONTROL = 0x11
VK_VOLUME_MUTE = 0xAD
DOUBLE_SECONDS = 0.5   # the second press starts within this time after the first one ends
TAP_SECONDS = 0.4      # a press held longer is not a tap
POLL_SECONDS = 0.03
OTHER_KEYS = tuple(code for code in range(0x08, 0xFF)
                   if code not in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5) and not 0x01 <= code <= 0x06)


class DoubleTap:
    """Pure detector: feed it (Ctrl down, another key down, time) and it says when a double tap happened."""

    def __init__(self):
        self.down_at: Optional[float] = None
        self.spoiled = False
        self.last_tap: Optional[float] = None

    def feed(self, ctrl: bool, other: bool, now: float) -> bool:
        if ctrl:
            if self.down_at is None:
                self.down_at, self.spoiled = now, False
            if other:
                self.spoiled = True
            return False
        if self.down_at is None:
            return False
        held, self.down_at = now - self.down_at, None
        if self.spoiled or held > TAP_SECONDS:
            self.last_tap = None
            return False
        if self.last_tap is not None and now - self.last_tap - held <= DOUBLE_SECONDS:
            self.last_tap = None
            return True
        self.last_tap = now
        return False


def _key(code: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)


class WakeKey:
    """A small thread that watches Ctrl; take() is True once after each double tap."""

    def __init__(self, ctrl: Callable[[], bool], other: Callable[[], bool]):
        self.ctrl, self.other = ctrl, other
        self.detector = DoubleTap()
        self._hit = threading.Event()
        threading.Thread(target=self._watch, name="vega-wake-key", daemon=True).start()

    def _watch(self) -> None:
        while True:
            try:
                ctrl = self.ctrl()
                if self.detector.feed(ctrl, ctrl and self.other(), time.monotonic()):
                    self._hit.set()
            except Exception:
                return
            time.sleep(POLL_SECONDS)

    def take(self) -> bool:
        if self._hit.is_set():
            self._hit.clear()
            return True
        return False


class Mute:
    """The laptop's sound off while Vega listens and back on before she speaks. The mute key toggles,
    so Vega presses it once to mute and once to restore, and only when she was the one who muted."""

    def __init__(self, press: Callable[[int], None]):
        self.press = press
        self.active = False

    def on(self) -> None:
        if not self.active:
            self.press(VK_VOLUME_MUTE)
            self.active = True

    def off(self) -> None:
        if self.active:
            self.press(VK_VOLUME_MUTE)
            self.active = False


def _press(code: int) -> None:
    import ctypes
    ctypes.windll.user32.keybd_event(code, 0, 0, None)
    ctypes.windll.user32.keybd_event(code, 0, 2, None)


def start() -> Optional[WakeKey]:
    if sys.platform != "win32":
        return None
    return WakeKey(lambda: _key(VK_CONTROL), lambda: any(_key(code) for code in OTHER_KEYS))


def mute() -> Mute:
    return Mute(_press if sys.platform == "win32" else (lambda code: None))
