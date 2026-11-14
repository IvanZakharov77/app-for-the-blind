"""Ctrl twice: Vega listens without «Вега» (Ivan, 2026-11-14).

Muting the laptop while she listens was tried in 0.7.27 and removed in 0.7.28 (Ivan: the sound sometimes
stayed off, so her answers were not heard). unmute_speakers() turns a muted laptop back on at start.


Two quick presses of Ctrl: Vega beeps and takes the next phrase as a command, without the word «Вега».
A single Ctrl still stops speech and media as before. Ctrl+C, Ctrl+V and other combinations never count: another key held with Ctrl spoils it.
"""

import sys
import threading
import time
from typing import Callable, Optional

VK_CONTROL = 0x11
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


def start() -> Optional[WakeKey]:
    if sys.platform != "win32":
        return None
    return WakeKey(lambda: _key(VK_CONTROL), lambda: any(_key(code) for code in OTHER_KEYS))


def unmute_speakers() -> bool:
    """The default speakers unmuted through the Windows audio API (Vista and later); True when Vega turned
    the sound back on. Nothing happens when the sound is already on or the API is missing."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import POINTER, HRESULT, c_float, c_uint, c_void_p
    from ctypes.wintypes import BOOL, DWORD
    import comtypes
    from comtypes import CLSCTX_ALL, COMMETHOD, GUID, IUnknown

    class IAudioEndpointVolume(IUnknown):
        _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
        _methods_ = [
            COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], c_void_p, "notify")),
            COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], c_void_p, "notify")),
            COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "count")),
            COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "level"), (["in"], POINTER(GUID), "context")),
            COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "level"), (["in"], POINTER(GUID), "context")),
            COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "level")),
            COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "level")),
            COMMETHOD([], HRESULT, "SetChannelVolumeLevel", (["in"], c_uint, "channel"), (["in"], c_float, "level"), (["in"], POINTER(GUID), "context")),
            COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar", (["in"], c_uint, "channel"), (["in"], c_float, "level"), (["in"], POINTER(GUID), "context")),
            COMMETHOD([], HRESULT, "GetChannelVolumeLevel", (["in"], c_uint, "channel"), (["out"], POINTER(c_float), "level")),
            COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar", (["in"], c_uint, "channel"), (["out"], POINTER(c_float), "level")),
            COMMETHOD([], HRESULT, "SetMute", (["in"], BOOL, "mute"), (["in"], POINTER(GUID), "context")),
            COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(BOOL), "mute")),
        ]

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "context"),
                      (["in"], c_void_p, "params"), (["out"], POINTER(POINTER(IUnknown)), "interface")),
        ]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [
            COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_uint, "flow"), (["in"], DWORD, "mask"),
                      (["out"], POINTER(c_void_p), "devices")),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_uint, "flow"), (["in"], c_uint, "role"),
                      (["out"], POINTER(POINTER(IMMDevice)), "device")),
        ]

    comtypes.CoInitialize()
    enumerator = comtypes.CoCreateInstance(GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), IMMDeviceEnumerator, CLSCTX_ALL)
    device = enumerator.GetDefaultAudioEndpoint(0, 1)  # render, multimedia
    endpoint = device.Activate(ctypes.byref(IAudioEndpointVolume._iid_), CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)
    if not endpoint.GetMute():
        return False
    endpoint.SetMute(False, None)
    return True
