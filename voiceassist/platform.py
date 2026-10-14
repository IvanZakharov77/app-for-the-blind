"""Conservative host classification; runtime acceptance still needs testing."""

from dataclasses import dataclass
import platform
import struct
import sys


@dataclass(frozen=True)
class Compatibility:
    supported: bool
    message: str


def actual_version(version):
    """Prefer the un-emulated tuple exposed by CPython 3.8+."""
    return getattr(version, "platform_version", (version.major, version.minor, version.build))


def classify_windows(major: int, minor: int, service_pack: int, bits: int, build: int = 0) -> Compatibility:
    if bits != 64:
        return Compatibility(False, "Нужна 64-разрядная Windows.")
    if (major, minor) == (6, 1):
        if service_pack < 1:
            return Compatibility(False, "Для Windows 7 требуется Service Pack 1.")
        return Compatibility(True, "Windows 7 SP1 x64: требуется проверка компонентов речи и Chrome на этом ПК.")
    if (major, minor) < (6, 1):
        return Compatibility(False, "Нужна Windows 7 SP1 или новее.")
    return Compatibility(True, "Windows {}.{} x64.".format(major, minor))


def current_host() -> Compatibility:
    if sys.platform != "win32":
        return Compatibility(False, "VoiceAssist работает только на Windows x64.")
    version = sys.getwindowsversion()
    bits = struct.calcsize("P") * 8
    service_pack = getattr(version, "service_pack_major", 0)
    major, minor, build = actual_version(version)
    return classify_windows(major, minor, service_pack, bits, build)
