"""One voice assistant per Windows session: a second copy would run every command twice."""

import sys

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\VoiceAssist.Voice"


class WindowsMutexAPI:
    def __init__(self):
        import ctypes
        self.ctypes = ctypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel32.CreateMutexW.restype = ctypes.c_void_p
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def create(self, name: str):
        handle = self.kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return handle, self.ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def close(self, handle) -> None:
        self.kernel32.CloseHandle(handle)


class SingleInstance:
    def __init__(self, api=None, name: str = MUTEX_NAME):
        self.api = api
        self.name = name
        self.handle = None

    def acquire(self) -> bool:
        """True when this is the only copy; the mutex lives until the process exits."""
        if self.api is None:
            if sys.platform != "win32":
                return True
            self.api = WindowsMutexAPI()
        handle, existed = self.api.create(self.name)
        if existed:
            self.api.close(handle)
            return False
        self.handle = handle
        return True


def suppress_error_dialogs() -> None:
    """Keep Windows from showing "Insert a disk" boxes the user cannot see when a card reader is empty."""
    if sys.platform != "win32":
        return
    import ctypes
    SEM_FAILCRITICALERRORS = 0x0001
    SEM_NOOPENFILEERRORBOX = 0x8000
    ctypes.windll.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX)
