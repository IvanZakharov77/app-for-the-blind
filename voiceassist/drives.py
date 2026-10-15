"""Read-only Windows enumeration of volumes marked removable by the OS."""

import ctypes
from dataclasses import dataclass
import struct
import sys
import time
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class UsbVolume:
    letter: str
    guid: str
    label: str
    filesystem: str
    confirmed_usb: bool
    removable: bool = False


def volume_arrival_message(volume: UsbVolume) -> str:
    name = "диск {}".format(volume.letter)
    if volume.label:
        name += " «{}»".format(volume.label)
    if volume.confirmed_usb or volume.removable:
        return "Подключена флешка или внешний диск: {}.".format(name)
    return "Подключён новый {}.".format(name)


class VolumeWatcher:
    def __init__(self, provider, clock=time.monotonic, interval: float = 10.0):
        self.provider = provider
        self.clock = clock
        self.interval = interval
        self.last_scan = None
        self.present_guids = set()

    def start(self) -> None:
        self.present_guids = {volume.guid for volume in self.provider()}
        self.last_scan = self.clock()

    def poll(self) -> Tuple[UsbVolume, ...]:
        if self.last_scan is None:
            self.start()
            return ()
        now = self.clock()
        if now - self.last_scan < self.interval:
            return ()
        volumes = self.provider()
        new = tuple(volume for volume in volumes if volume.guid not in self.present_guids)
        self.present_guids = {volume.guid for volume in volumes}
        self.last_scan = now
        return new


def bus_type_from_descriptor(payload: bytes) -> int:
    if len(payload) < 36 or struct.unpack_from("<I", payload, 4)[0] < 36:
        raise ValueError("Неполное описание устройства.")
    return struct.unpack_from("<I", payload, 28)[0]


def scan_volumes(api=None) -> Tuple[UsbVolume, ...]:
    """Snapshot local volumes, retaining bus classification without guessing."""
    api = api or WindowsVolumeAPI()
    mask = api.logical_mask()
    if mask == 0:
        raise OSError("Не удалось получить список дисков.")
    volumes = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        letter = chr(ord("A") + index)
        root = letter + ":\\"
        kind = api.drive_type(root)
        if kind not in (2, 3):
            continue
        try:
            try:
                bus = api.bus_type(letter)
            except OSError:
                bus = None
            guid = api.volume_guid(root)
            label, filesystem = api.volume_info(root)
        except OSError:
            continue
        volumes.append(UsbVolume(letter, guid, label, filesystem, bus == 7, kind == 2))
    return tuple(volumes)


def enumerate_usb_volumes(api=None) -> Tuple[UsbVolume, ...]:
    """Include USB bus volumes even when Windows marks their media fixed."""
    return tuple(volume for volume in scan_volumes(api) if volume.confirmed_usb or volume.removable)


class WindowsVolumeAPI:
    """Small WinAPI adapter; queried only on a user command or copy check."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Список USB-дисков доступен только на Windows.")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.GetLogicalDrives.restype = ctypes.c_uint32
        self.kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        self.kernel32.GetDriveTypeW.restype = ctypes.c_uint32
        self.kernel32.GetVolumeNameForVolumeMountPointW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
        self.kernel32.GetVolumeNameForVolumeMountPointW.restype = ctypes.c_int
        self.kernel32.GetVolumeInformationW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32,
                                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                                          ctypes.c_void_p, ctypes.c_uint32]
        self.kernel32.GetVolumeInformationW.restype = ctypes.c_int
        self.kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                               ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        self.kernel32.CreateFileW.restype = ctypes.c_void_p
        self.kernel32.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                                    ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                                    ctypes.c_void_p, ctypes.c_void_p]
        self.kernel32.DeviceIoControl.restype = ctypes.c_int
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def logical_mask(self) -> int:
        return self.kernel32.GetLogicalDrives()

    def drive_type(self, root: str) -> int:
        return self.kernel32.GetDriveTypeW(root)

    def volume_guid(self, root: str) -> str:
        buffer = ctypes.create_unicode_buffer(64)
        if not self.kernel32.GetVolumeNameForVolumeMountPointW(root, buffer, len(buffer)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.value

    def volume_info(self, root: str) -> Tuple[str, str]:
        label = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        if not self.kernel32.GetVolumeInformationW(root, label, len(label), None, None, None,
                                                     filesystem, len(filesystem)):
            raise ctypes.WinError(ctypes.get_last_error())
        return label.value, filesystem.value

    def bus_type(self, letter: str) -> int:
        handle = self.kernel32.CreateFileW("\\\\.\\" + letter + ":", 0, 3, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            query = ctypes.create_string_buffer(12)
            header = ctypes.create_string_buffer(8)
            returned = ctypes.c_uint32()
            ioctl = 0x002D1400
            if not self.kernel32.DeviceIoControl(handle, ioctl, query, len(query), header, len(header),
                                                  ctypes.byref(returned), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if returned.value < 8:
                raise OSError("Неполное описание USB-диска.")
            size = struct.unpack_from("<I", header.raw, 4)[0]
            if not 36 <= size <= 65536:
                raise OSError("Недопустимый размер описания USB-диска.")
            output = ctypes.create_string_buffer(size)
            if not self.kernel32.DeviceIoControl(handle, ioctl, query, len(query), output, len(output),
                                                  ctypes.byref(returned), None):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                return bus_type_from_descriptor(output.raw[:returned.value])
            except ValueError as error:
                raise OSError(str(error)) from error
        finally:
            self.kernel32.CloseHandle(handle)


def _windows_drive_functions():
    if sys.platform != "win32":
        raise OSError("Список съёмных дисков доступен только на Windows.")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    logical_drives = kernel32.GetLogicalDrives
    logical_drives.argtypes = []
    logical_drives.restype = ctypes.c_ulong
    drive_type = kernel32.GetDriveTypeW
    drive_type.argtypes = [ctypes.c_wchar_p]
    drive_type.restype = ctypes.c_uint
    return logical_drives, drive_type


def removable_drive_letters(logical_drives: Optional[Callable[[], int]] = None,
                            drive_type: Optional[Callable[[str], int]] = None) -> Tuple[str, ...]:
    if logical_drives is None or drive_type is None:
        logical_drives, drive_type = _windows_drive_functions()
    mask = logical_drives()
    if mask == 0:
        raise OSError("Не удалось получить список дисков.")
    letters = []
    for index in range(26):
        if mask & (1 << index):
            letter = chr(ord("A") + index)
            if drive_type(letter + ":\\") == 2:
                letters.append(letter)
    return tuple(letters)


def drive_letters_of_type(kind: int, logical_drives: Optional[Callable[[], int]] = None,
                          drive_type: Optional[Callable[[str], int]] = None) -> Tuple[str, ...]:
    """3 = fixed disk, 5 = CD/DVD (GetDriveTypeW)."""
    if logical_drives is None or drive_type is None:
        logical_drives, drive_type = _windows_drive_functions()
    mask = logical_drives()
    return tuple(chr(ord("A") + index) for index in range(26)
                 if mask & (1 << index) and drive_type(chr(ord("A") + index) + ":\\") == kind)


def eject_volume(letter: str) -> None:
    """Flush, lock, dismount and eject like «Безопасное извлечение»; fails while files are open."""
    if sys.platform != "win32":
        raise OSError("Извлечение доступно только на Windows.")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                     ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.FlushFileBuffers.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    GENERIC_READ, GENERIC_WRITE, SHARE_RW, OPEN_EXISTING = 0x80000000, 0x40000000, 3, 3
    FSCTL_LOCK_VOLUME, FSCTL_DISMOUNT_VOLUME = 0x00090018, 0x00090020
    IOCTL_STORAGE_MEDIA_REMOVAL, IOCTL_STORAGE_EJECT_MEDIA = 0x002D4804, 0x002D4808
    handle = kernel32.CreateFileW("\\\\.\\" + letter + ":", GENERIC_READ | GENERIC_WRITE, SHARE_RW, None, OPEN_EXISTING, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    returned = ctypes.c_uint32()

    def control(code, payload=None, size=0):
        return kernel32.DeviceIoControl(handle, code, payload, size, None, 0, ctypes.byref(returned), None)

    try:
        kernel32.FlushFileBuffers(handle)
        for _ in range(10):
            if control(FSCTL_LOCK_VOLUME):
                break
            time.sleep(0.5)
        else:
            raise PermissionError("на флешке открыты файлы или окна")
        if not control(FSCTL_DISMOUNT_VOLUME):
            raise ctypes.WinError(ctypes.get_last_error())
        allow = ctypes.c_ubyte(0)
        control(IOCTL_STORAGE_MEDIA_REMOVAL, ctypes.byref(allow), 1)
        if not control(IOCTL_STORAGE_EJECT_MEDIA):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)
