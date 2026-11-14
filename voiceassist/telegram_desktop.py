"""«Вега, проверь Телеграм»: what Vega can see in Telegram Desktop, before calls are built (TZ, 2026-11-14).

Calls are not in the Telegram client library Vega uses; they can only go through Telegram Desktop by
pressing its buttons. Whether its buttons are visible to Windows UI Automation differs by version and by
Windows (new Telegram Desktop no longer supports Windows 7 and 8). This check writes everything Vega sees
into a file on the desktop; the developer reads it and only then calls are built. Nothing is pressed.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

REPORT = "Vega-проверка-телеграма.txt"
MAX_ITEMS = 600


def find_exe() -> Optional[Path]:
    for base in (os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""),
                 os.environ.get("ProgramFiles(x86)", "")):
        if not base:
            continue
        for folder in ("Telegram Desktop", "Programs\\Telegram Desktop", "Telegram"):
            exe = Path(base) / folder / "Telegram.exe"
            if exe.exists():
                return exe
    return None


def file_version(path: Path) -> str:
    try:
        import ctypes
        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, data)
        pointer, length = ctypes.c_void_p(), ctypes.c_uint()
        ctypes.windll.version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length))
        words = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
        ms, ls = words[4], words[5]
        return "{}.{}.{}.{}".format(ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except Exception:
        return ""


def telegram_windows(windows) -> List[Tuple[int, int, str, str, str]]:
    return [window for window in windows.list() if window[2] == "telegram.exe"]


def dump(handle: int) -> List[str]:
    """Every UI Automation element under the window: type, name, automation id, class, size."""
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as uia
    automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
    root = automation.ElementFromHandle(handle)
    found = root.FindAll(4, automation.CreateTrueCondition())  # 4 = all descendants
    lines = ["Элементов всего: {}".format(found.Length)]
    for index in range(min(found.Length, MAX_ITEMS)):
        try:
            element = found.GetElement(index)
            rect = element.CurrentBoundingRectangle
            lines.append("{} | {} | id={} | class={} | {}x{} at {},{} | enabled={}".format(
                element.CurrentControlType, (element.CurrentName or "")[:80], element.CurrentAutomationId or "",
                element.CurrentClassName or "", rect.right - rect.left, rect.bottom - rect.top, rect.left, rect.top,
                bool(element.CurrentIsEnabled)))
        except Exception as error:
            lines.append("? ошибка чтения элемента: {}".format(error))
    return lines


def probe(desktop: Path) -> str:
    import platform
    from .media_watch import Windows
    exe = find_exe()
    lines = ["Проверка Telegram Desktop для звонков через Вегу", "Windows: {} {}".format(platform.platform(), platform.machine())]
    lines.append("Telegram.exe: {} {}".format(exe or "не найден в обычных папках", file_version(exe) if exe else ""))
    windows = Windows()
    found = telegram_windows(windows)
    if not found and exe is not None:
        subprocess.Popen([str(exe)], close_fds=True)
        for _ in range(20):
            time.sleep(1)
            found = telegram_windows(windows)
            if found:
                break
        time.sleep(3)  # the chat list draws after the window shows
    if not found:
        answer = ("Telegram Desktop на этом компьютере не найден или не открылся. "
                  "Для звонков через Вегу нужна установленная программа Телеграм.")
        lines.append(answer)
    else:
        for handle, pid, exe_name, title, kind in found:
            lines.append("")
            lines.append("Окно: «{}» class={} pid={}".format(title, kind, pid))
            try:
                lines.extend(dump(handle))
            except Exception as error:
                lines.append("UI Automation не прочитала окно: {}".format(error))
        answer = "Проверка Телеграма готова. Файл «{}» лежит на рабочем столе, отправьте его разработчику.".format(REPORT)
    try:
        desktop.mkdir(parents=True, exist_ok=True)
        (desktop / REPORT).write_text("\n".join(lines), encoding="utf-8-sig")
    except OSError as error:
        return "Не удалось записать файл проверки: {}.".format(error)
    return answer
