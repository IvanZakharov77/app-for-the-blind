"""Windows system commands through ctypes only: no extra packages, little memory."""

from dataclasses import dataclass
import os
import subprocess
import sys
import time
from typing import Callable, List, Optional, Tuple

# Spoken name → what to start. Plain executables live in System32 on every supported Windows.
PROGRAMS = {
    "блокнот": ("notepad.exe", "Блокнот"),
    "калькулятор": ("calc.exe", "Калькулятор"),
    "проводник": ("explorer.exe", "Проводник"),
    "паинт": ("mspaint.exe", "Paint"),
    "пэйнт": ("mspaint.exe", "Paint"),
    "ворд": ("winword.exe", "Word"),
    "эксель": ("excel.exe", "Excel"),
    "диспетчер задач": ("taskmgr.exe", "Диспетчер задач"),
    "панель управления": ("control.exe", "Панель управления"),
    "экранный диктор": ("narrator.exe", "Экранный диктор"),
    "нвда": ("nvda.exe", "NVDA"),
    "настройки": ("ms-settings:", "Параметры"),
    "параметры": ("ms-settings:", "Параметры"),
}
ORDINALS = ("первое", "второе", "третье", "четвертое", "пятое", "шестое", "седьмое", "восьмое", "девятое", "десятое")


@dataclass(frozen=True)
class SystemOutcome:
    status: str
    message: str


@dataclass(frozen=True)
class Battery:
    on_power: Optional[bool]
    percent: Optional[int]
    has_battery: bool


class WindowsSystemAPI:
    """Thin ctypes adapter; every call is small and on demand."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Системные команды доступны только на Windows.")
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        self.user32.GetWindow.restype = wintypes.HWND
        self.user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]

    def battery(self) -> Battery:
        ctypes = self.ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

        status = SYSTEM_POWER_STATUS()
        if not self.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        on_power = {0: False, 1: True}.get(status.ACLineStatus)
        has_battery = status.BatteryFlag != 255 and not status.BatteryFlag & 128
        percent = status.BatteryLifePercent if status.BatteryLifePercent <= 100 else None
        return Battery(on_power, percent, has_battery)

    def connected(self) -> bool:
        flags = self.wintypes.DWORD()
        wininet = self.ctypes.WinDLL("wininet")
        return bool(wininet.InternetGetConnectedState(self.ctypes.byref(flags), 0))

    def press_key(self, virtual_key: int) -> None:
        KEYEVENTF_KEYUP = 2
        self.user32.keybd_event(virtual_key, 0, 0, None)
        self.user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, None)

    def shutdown(self, arguments: List[str]) -> int:
        """shutdown.exe first; when it is missing or refuses (Ivan's Windows 7 and 8, 2026-10-27), the same
        through the Windows API with the shutdown privilege switched on. 0 means Windows took the command."""
        windows = os.environ.get("SystemRoot", r"C:\Windows")
        code = -1
        for folder in ("Sysnative", "System32"):
            executable = os.path.join(windows, folder, "shutdown.exe")
            if not os.path.isfile(executable):
                continue
            try:
                code = subprocess.run([executable] + arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      timeout=15, check=False,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode
            except (OSError, subprocess.SubprocessError):
                continue
            if code == 0:
                return 0
            break
        try:
            return 0 if self._shutdown_api(arguments) else code or -1
        except (OSError, AttributeError):
            return code or -1

    def _shutdown_api(self, arguments: List[str]) -> bool:
        ctypes, wintypes = self.ctypes, self.wintypes
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        token = wintypes.HANDLE()
        TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY, SE_PRIVILEGE_ENABLED = 0x20, 0x8, 0x2

        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

        class PRIVILEGES(ctypes.Structure):
            _fields_ = [("Count", wintypes.DWORD), ("Luid", LUID), ("Attributes", wintypes.DWORD)]

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        if advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
            privileges = PRIVILEGES(1, LUID(), SE_PRIVILEGE_ENABLED)
            if advapi32.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(privileges.Luid)):
                advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
            kernel32.CloseHandle(token)
        if "/a" in arguments:
            return bool(advapi32.AbortSystemShutdownW(None))
        seconds = int(arguments[arguments.index("/t") + 1]) if "/t" in arguments else 0
        reboot = "/r" in arguments
        SHTDN_REASON_FLAG_PLANNED = 0x80000000
        if advapi32.InitiateSystemShutdownExW(None, None, seconds, True, reboot, SHTDN_REASON_FLAG_PLANNED):
            return True
        # The last resort, no countdown: Windows closes the programs and turns off at once.
        EWX_SHUTDOWN, EWX_REBOOT, EWX_FORCEIFHUNG, EWX_POWEROFF = 0x1, 0x2, 0x10, 0x8
        flags = (EWX_REBOOT if reboot else EWX_SHUTDOWN | EWX_POWEROFF) | EWX_FORCEIFHUNG
        return bool(self.user32.ExitWindowsEx(flags, SHTDN_REASON_FLAG_PLANNED))

    def title(self, handle) -> str:
        length = self.user32.GetWindowTextLengthW(handle)
        buffer = self.ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(handle, buffer, length + 1)
        return buffer.value

    def windows(self) -> List[Tuple[int, str]]:
        """Visible top-level application windows with a title, in Alt+Tab order."""
        ctypes = self.ctypes
        found = []
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x80
        GW_OWNER = 4
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, self.wintypes.HWND, self.wintypes.LPARAM)

        def collect(handle, _param):
            if (self.user32.IsWindowVisible(handle) and not self.user32.GetWindow(handle, GW_OWNER)
                    and not self.user32.GetWindowLongW(handle, GWL_EXSTYLE) & WS_EX_TOOLWINDOW):
                text = self.title(handle)
                if text and text != "Program Manager":
                    found.append((handle, text))
            return True

        self.user32.EnumWindows(callback_type(collect), 0)
        return found

    def foreground(self) -> Optional[Tuple[int, str]]:
        handle = self.user32.GetForegroundWindow()
        return (handle, self.title(handle)) if handle else None

    def activate(self, handle) -> bool:
        SW_RESTORE = 9
        VK_MENU = 0x12
        if self.user32.IsIconic(handle):
            self.user32.ShowWindow(handle, SW_RESTORE)
        # Windows only lets the foreground process change focus; a synthetic Alt press lifts that lock.
        self.press_key(VK_MENU)
        self.user32.SetForegroundWindow(handle)
        return self.user32.GetForegroundWindow() == handle

    def close(self, handle) -> None:
        WM_CLOSE = 0x0010
        self.user32.PostMessageW(handle, WM_CLOSE, 0, 0)

    def exists(self, handle) -> bool:
        return bool(self.user32.IsWindow(handle))

    def launch(self, target: str) -> None:
        os.startfile(target)

    # Inside windows: loaded on first use, so startup on a slow disk stays short.

    def controls(self, handle):
        if getattr(self, "_ui", None) is None:
            from .window_ui import WindowUi
            self._ui = WindowUi(self)
        return self._ui.elements(handle)

    def invoke(self, element) -> bool:
        return self._ui.invoke(element)

    def show(self, handle, how: str) -> None:
        SW = {"minimize": 6, "maximize": 3, "restore": 9}
        self.user32.ShowWindow(handle, SW[how])

    def is_minimized(self, handle) -> bool:
        return bool(self.user32.IsIconic(handle))

    def is_maximized(self, handle) -> bool:
        self.user32.IsZoomed.argtypes = [self.wintypes.HWND]
        return bool(self.user32.IsZoomed(handle))

    def _keyboard(self):
        if getattr(self, "_keys", None) is None:
            from .window_ui import Keyboard
            self._keys = Keyboard(self)
        return self._keys

    def press(self, key: str, modifiers=()) -> bool:
        return self._keyboard().press(key, tuple(modifiers))

    def type_text(self, text: str) -> bool:
        return self._keyboard().type_text(text)

    def focused(self):
        """UI Automation's focused element; None when it is unavailable."""
        if getattr(self, "_ui", None) is None:
            from .window_ui import WindowUi
            self._ui = WindowUi(self)
        backend = self._ui._backend()
        from .window_ui import UiaBackend, focused_uia
        if not isinstance(backend, UiaBackend):
            return None
        try:
            return focused_uia(backend)
        except Exception:
            return None

    def open_menu(self, element) -> bool:
        from .window_ui import UiaBackend, expand_menu
        backend = element.backend
        if isinstance(backend, UiaBackend):
            return expand_menu(backend, element)
        return self.invoke(element)

    def show_desktop(self) -> None:
        VK_LWIN, VK_D, KEYEVENTF_KEYUP = 0x5B, 0x44, 2
        self.user32.keybd_event(VK_LWIN, 0, 0, None)
        self.user32.keybd_event(VK_D, 0, 0, None)
        self.user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, None)
        self.user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, None)


VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF


class SystemController:
    def __init__(self, api, wait: Callable[[float], None] = time.sleep):
        self.api = api
        self.wait = wait
        self.shutdown_planned = False

    def battery(self) -> SystemOutcome:
        state = self.api.battery()
        if not state.has_battery:
            return SystemOutcome("ok", "Батарея не обнаружена, компьютер работает от сети.")
        charge = "Заряд {} процентов.".format(state.percent) if state.percent is not None else "Заряд неизвестен."
        source = {True: " Подключено питание.", False: " Работа от батареи.", None: ""}[state.on_power]
        return SystemOutcome("ok", charge + source)

    def network(self) -> SystemOutcome:
        if self.api.connected():
            return SystemOutcome("ok", "Сетевое подключение есть. Доступность конкретных сайтов не проверялась.")
        return SystemOutcome("ok", "Подключения к сети нет.")

    def volume(self, kind: str, steps: int = 5) -> SystemOutcome:
        if kind == "mute":
            self.api.press_key(VK_VOLUME_MUTE)
            return SystemOutcome("ok", "Нажата клавиша выключения звука. Повторная команда снова включит звук.")
        key = VK_VOLUME_UP if kind == "up" else VK_VOLUME_DOWN
        for _ in range(steps):
            self.api.press_key(key)
        return SystemOutcome("ok", "Громкость {} на {} шагов.".format("прибавлена" if kind == "up" else "убавлена", steps))

    def schedule_power(self, kind: str, seconds: int = 15) -> SystemOutcome:
        flag = "/s" if kind == "shutdown" else "/r"
        code = self.api.shutdown([flag, "/t", str(seconds)])
        if code != 0:
            return SystemOutcome("error", "Windows не приняла команду. Код {}.".format(code))
        self.shutdown_planned = True
        action = "выключится" if kind == "shutdown" else "перезагрузится"
        return SystemOutcome("in_progress", "Компьютер {} через {} секунд. Чтобы отменить, скажите: Вега, отмени выключение.".format(action, seconds))

    def abort_power(self) -> SystemOutcome:
        code = self.api.shutdown(["/a"])
        self.shutdown_planned = False
        if code != 0:
            return SystemOutcome("unavailable", "Запланированного выключения нет или отменить его не удалось.")
        return SystemOutcome("ok", "Выключение отменено.")

    def open_program(self, spoken: str) -> SystemOutcome:
        entry = PROGRAMS.get(spoken)
        if entry is None:
            return SystemOutcome("unknown", "Не знаю программу «{}». Знаю: {}.".format(spoken, ", ".join(sorted(PROGRAMS))))
        target, title = entry
        before = {handle for handle, _ in self.api.windows()}
        try:
            try:
                self.api.launch(target)
            except OSError:
                if target != "ms-settings:":
                    raise
                # Windows 7 has no «Параметры»: the Control Panel plays that role there.
                self.api.launch("control.exe")
        except OSError:
            return SystemOutcome("error", "Программа {} не найдена на этом компьютере.".format(title))
        for _ in range(20):
            self.wait(0.25)
            new = [text for handle, text in self.api.windows() if handle not in before]
            if new:
                return SystemOutcome("ok", "Открыто окно «{}».".format(new[0]))
        return SystemOutcome("unverified", "Запуск {} передан Windows, но новое окно не появилось.".format(title))

    def list_windows(self) -> SystemOutcome:
        windows = self.api.windows()
        if not windows:
            return SystemOutcome("ok", "Открытых окон нет.")
        names = ["{}: {}".format(index + 1, text) for index, (_, text) in enumerate(windows[:5])]
        more = " Всего окон: {}.".format(len(windows)) if len(windows) > 5 else ""
        return SystemOutcome("ok", "Открытые окна. " + "; ".join(names) + "." + more + " Скажите: переключись на окно и номер.")

    def _find_window(self, spoken: str) -> Optional[Tuple[int, str]]:
        windows = self.api.windows()
        from .numbers import parse_index, words_to_number
        number = parse_index(spoken)  # «номер два», «второе», «2»
        if number is None:
            number = words_to_number(spoken)
        if number is None and spoken in ORDINALS:
            number = ORDINALS.index(spoken) + 1
        if number is not None:
            index = int(number) - 1
            return windows[index] if 0 <= index < len(windows) else None
        return next(((handle, text) for handle, text in windows if spoken in text.lower().replace("ё", "е")), None)

    def switch_to(self, spoken: str) -> SystemOutcome:
        window = self._find_window(spoken)
        if window is None:
            return SystemOutcome("error", "Окно «{}» не найдено. Скажите: какие окна открыты.".format(spoken))
        if self.api.activate(window[0]):
            return SystemOutcome("ok", "Активно окно «{}».".format(window[1]))
        return SystemOutcome("unverified", "Попросил Windows показать окно «{}», но оно не стало активным.".format(window[1]))

    def active_window(self) -> SystemOutcome:
        window = self.api.foreground()
        if not window or not window[1]:
            return SystemOutcome("ok", "Активное окно без названия.")
        return SystemOutcome("ok", "Активно окно «{}».".format(window[1]))

    def close_active(self) -> SystemOutcome:
        window = self.api.foreground()
        if not window:
            return SystemOutcome("unavailable", "Активного окна нет.")
        handle, title = window
        self.api.close(handle)
        for _ in range(8):
            self.wait(0.25)
            if not self.api.exists(handle):
                return SystemOutcome("ok", "Окно «{}» закрыто.".format(title))
        return SystemOutcome("unverified", "Окно «{}» не закрылось. Возможно, программа спрашивает о сохранении.".format(title))

    # Controls inside the active window

    def _controls(self):
        window = self.api.foreground()
        if not window:
            return None, []
        return window, self.api.controls(window[0])

    def read_window(self) -> SystemOutcome:
        """Title, texts and buttons: enough to answer a message box or «Сохранить изменения?»."""
        window, items = self._controls()
        if window is None:
            return SystemOutcome("unavailable", "Активного окна нет.")
        texts = [item.name for item in items if item.role == "text"][:6]
        fields = [item for item in items if item.role == "field"]
        buttons = [item.name for item in items if item.role == "button"][:6]
        parts = ["Окно «{}».".format(window[1] or "без названия")]
        if texts:
            parts.append(" ".join(text.rstrip(".") + "." for text in texts))
        if fields and fields[0].value:
            parts.append("В поле: {}.".format(fields[0].value[:200]))
        if buttons:
            parts.append("Кнопки: {}.".format("; ".join(buttons)))
        if not texts and not buttons and not fields:
            parts.append("Элементы окна не читаются. Возможно, программа не поддерживает специальные возможности.")
        self.last_controls = [item for item in items if item.role == "button"]
        return SystemOutcome("ok", " ".join(parts))

    def list_controls(self, role: Optional[str] = None) -> SystemOutcome:
        from .window_ui import ROLE_NAMES
        window, items = self._controls()
        if window is None:
            return SystemOutcome("unavailable", "Активного окна нет.")
        chosen = [item for item in items if item.role != "text" and (role is None or item.role == role)]
        self.last_controls = chosen
        if not chosen:
            what = ROLE_NAMES[role][1].lower() if role else "элементы управления"
            return SystemOutcome("ok", "В окне «{}» {} не найдены.".format(window[1], what))
        spoken = []
        for number, item in enumerate(chosen[:8], 1):
            text = "{}. {}".format(number, item.name or "без названия")
            if role is None:
                text += ", " + ROLE_NAMES[item.role][0]
            if item.checked is not None:
                text += ", отмечен" if item.checked else ", не отмечен"
            if item.value:
                text += ", содержит: " + item.value[:60]
            spoken.append(text)
        more = " Всего {}.".format(len(chosen)) if len(chosen) > 8 else ""
        return SystemOutcome("ok", "; ".join(spoken) + "." + more + " Скажите: нажми и номер или название.")

    def find_control(self, spoken: str):
        """By number from the last list, or by name in the active window."""
        from .numbers import parse_index
        number = parse_index(spoken)
        if number is not None and getattr(self, "last_controls", None):
            return self.last_controls[number - 1] if number <= len(self.last_controls) else None
        _window, items = self._controls()
        wanted = spoken.lower().replace("ё", "е")
        candidates = [item for item in items if item.role != "text" and item.name]
        exact = [item for item in candidates if item.name.lower().replace("ё", "е").rstrip(".") == wanted]
        return (exact or [item for item in candidates if wanted in item.name.lower().replace("ё", "е")] or [None])[0]

    def press(self, element) -> SystemOutcome:
        window = self.api.foreground()
        if not self.api.invoke(element):
            return SystemOutcome("unverified", "Элемент «{}» выбран, но нажать его не удалось.".format(element.name))
        if element.role == "field":
            return SystemOutcome("ok", "Курсор в поле{}. Можно печатать.".format(" «{}»".format(element.name) if element.name else ""))
        self.wait(0.4)
        after = self.api.foreground()
        now = " Активно окно «{}».".format(after[1] or "без названия") if after else ""
        if window and not self.api.exists(window[0]):
            return SystemOutcome("ok", "Нажато «{}». Окно закрылось.{}".format(element.name, now))
        if window and after and after[0] != window[0]:
            return SystemOutcome("ok", "Нажато «{}». Открылось другое окно.{}".format(element.name, now))
        return SystemOutcome("unverified", "Нажато «{}». Окно осталось прежним; скажите: прочитай окно, чтобы проверить.".format(element.name))

    def arrange(self, how: str) -> SystemOutcome:
        if how == "desktop":
            self.api.show_desktop()
            return SystemOutcome("unverified", "Все окна свёрнуты, показан рабочий стол.")
        window = self.api.foreground()
        if not window:
            return SystemOutcome("unavailable", "Активного окна нет.")
        self.api.show(window[0], how)
        self.wait(0.3)
        check = {"minimize": self.api.is_minimized, "maximize": self.api.is_maximized}.get(how)
        names = {"minimize": "свёрнуто", "maximize": "развёрнуто на весь экран", "restore": "восстановлено"}
        if check is not None and not check(window[0]):
            return SystemOutcome("error", "Окно «{}» не изменилось.".format(window[1]))
        return SystemOutcome("ok", "Окно «{}» {}.".format(window[1], names[how]))

    # Keyboard and focus: lists, menus, dictation

    def focus_report(self) -> SystemOutcome:
        from .window_ui import describe_focus
        element = self.api.focused()
        if element is None:
            window = self.api.foreground()
            return SystemOutcome("unavailable", "Не могу определить элемент под фокусом. Активно окно «{}».".format(window[1] if window else "неизвестно"))
        return SystemOutcome("ok", describe_focus(element))

    def key(self, key: str, modifiers=(), announce: bool = True) -> SystemOutcome:
        if not self.api.press(key, modifiers):
            return SystemOutcome("error", "Windows не приняла нажатие клавиши.")
        if not announce:
            return SystemOutcome("ok", "Нажато.")
        self.wait(0.15)
        report = self.focus_report()
        return SystemOutcome("ok" if report.status == "ok" else "unverified", report.message)

    def type_text(self, text: str) -> SystemOutcome:
        window = self.api.foreground()
        if not window:
            return SystemOutcome("unavailable", "Нет активного окна, печатать некуда.")
        before = self.api.focused()
        if before is not None and before.role not in ("field", "document", "combo", "item", "text"):
            return SystemOutcome("unavailable", "Сейчас под фокусом {} «{}», а не поле для текста. Скажите: следующий элемент, чтобы перейти к полю.".format(
                {"button": "кнопка", "link": "ссылка", "checkbox": "флажок"}.get(before.role, "элемент"), before.name))
        if not self.api.type_text(text):
            return SystemOutcome("error", "Windows не приняла ввод текста.")
        self.wait(0.2)
        after = self.api.focused()
        if after is not None and after.value and text.strip()[-20:].lower() in after.value.lower():
            return SystemOutcome("ok", "Напечатано: {}".format(text))
        return SystemOutcome("unverified", "Напечатал: {}. Проверить поле не удалось; скажите: прочитай поле.".format(text))

    def open_menu(self, spoken: str) -> SystemOutcome:
        window, items = self._controls()
        if window is None:
            return SystemOutcome("unavailable", "Активного окна нет.")
        wanted = spoken.lower().replace("ё", "е")
        menus = [item for item in items if item.role == "menu" and item.name.lower().replace("ё", "е") == wanted]
        if not menus:
            names = [item.name for item in items if item.role == "menu"][:8]
            return SystemOutcome("error", "Меню «{}» нет.{}".format(spoken, " Есть: " + ", ".join(names) + "." if names else
                                                                   " Скажите: открой меню, чтобы перейти в строку меню."))
        if not self.api.open_menu(menus[0]):
            return SystemOutcome("error", "Меню «{}» не открылось.".format(menus[0].name))
        self.wait(0.3)
        report = self.focus_report()
        return SystemOutcome("ok", "Открыто меню «{}». {} Дальше: следующий пункт, выбери.".format(menus[0].name, report.message))
