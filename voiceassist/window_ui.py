"""Controls inside the active window: texts, buttons, fields, check boxes.

UI Automation (through comtypes, which pyttsx3 already installs on Windows) sees modern
and classic programs; when it cannot load, plain Win32 child windows still cover message
boxes, «Сохранить изменения?» dialogs and most old programs. Both run only on demand.
"""

from dataclasses import dataclass
import re
import time
from typing import Any, List, Optional

ROLE_NAMES = {
    "button": ("кнопка", "Кнопки"), "text": ("текст", "Тексты"), "field": ("поле", "Поля"),
    "checkbox": ("флажок", "Флажки"), "radio": ("переключатель", "Переключатели"), "link": ("ссылка", "Ссылки"),
    "menu": ("пункт меню", "Пункты меню"), "item": ("элемент списка", "Элементы списка"), "tab": ("вкладка", "Вкладки"),
}
MAX_ELEMENTS = 300
SEARCH_SECONDS = 3.0


@dataclass
class UiElement:
    role: str
    name: str
    value: str = ""
    checked: Optional[bool] = None
    ref: Any = None
    backend: Any = None


def clean_name(text: str) -> str:
    """«&Сохранить», «Не сохранять\tAlt+N» → spoken form."""
    text = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    return re.sub(r"\s+", " ", text.split("\t")[0]).strip()


# UI Automation identifiers (UIAutomationClient.h); fixed since Windows 7.
UIA_CONTROL_TYPES = {
    50000: "button", 50020: "text", 50004: "field", 50002: "checkbox", 50013: "radio", 50005: "link",
    50011: "menu", 50007: "item", 50019: "tab", 50031: "button",  # 50031 split button
}
UIA_ControlTypePropertyId = 30003
UIA_IsOffscreenPropertyId = 30022
UIA_InvokePatternId = 10000
UIA_ValuePatternId = 10002
UIA_SelectionItemPatternId = 10010
UIA_TogglePatternId = 10015
TreeScope_Descendants = 4


class UiaBackend:
    def __init__(self):
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia
        self.uia = uia
        self.automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)
        condition = None
        for control_type in UIA_CONTROL_TYPES:
            single = self.automation.CreatePropertyCondition(UIA_ControlTypePropertyId, control_type)
            condition = single if condition is None else self.automation.CreateOrCondition(condition, single)
        visible = self.automation.CreatePropertyCondition(UIA_IsOffscreenPropertyId, False)
        self.condition = self.automation.CreateAndCondition(condition, visible)

    def elements(self, handle) -> List[UiElement]:
        root = self.automation.ElementFromHandle(handle)
        found = root.FindAll(TreeScope_Descendants, self.condition)
        result = []
        started = time.monotonic()
        for index in range(min(found.Length, MAX_ELEMENTS)):
            if time.monotonic() - started > SEARCH_SECONDS:
                break
            element = found.GetElement(index)
            try:
                role = UIA_CONTROL_TYPES.get(element.CurrentControlType)
                name = clean_name(element.CurrentName or "")
                if role is None or not element.CurrentIsEnabled and role != "text":
                    continue
                value, checked = "", None
                if role == "field":
                    pattern = element.GetCurrentPattern(UIA_ValuePatternId)
                    if pattern:
                        value = pattern.QueryInterface(self.uia.IUIAutomationValuePattern).CurrentValue or ""
                if role in ("checkbox",):
                    pattern = element.GetCurrentPattern(UIA_TogglePatternId)
                    if pattern:
                        checked = pattern.QueryInterface(self.uia.IUIAutomationTogglePattern).CurrentToggleState == 1
                if name or value:
                    result.append(UiElement(role, name, value.strip()[:300], checked, element, self))
            except Exception:
                continue
        return result

    def invoke(self, element: UiElement) -> bool:
        item = element.ref
        if element.role == "field":
            item.SetFocus()
            return True
        for pattern_id, interface, method in (
                (UIA_InvokePatternId, self.uia.IUIAutomationInvokePattern, "Invoke"),
                (UIA_TogglePatternId, self.uia.IUIAutomationTogglePattern, "Toggle"),
                (UIA_SelectionItemPatternId, self.uia.IUIAutomationSelectionItemPattern, "Select")):
            pattern = item.GetCurrentPattern(pattern_id)
            if pattern:
                getattr(pattern.QueryInterface(interface), method)()
                return True
        item.SetFocus()
        return False


class Win32Backend:
    """Child windows of classic dialogs: Button, Static, Edit."""

    def __init__(self, api):
        self.api = api
        user32 = api.user32
        wintypes = api.wintypes
        ctypes = api.ctypes
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, ctypes.c_void_p,
                                               ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
        user32.SetFocus.argtypes = [wintypes.HWND]

    def _class(self, handle) -> str:
        buffer = self.api.ctypes.create_unicode_buffer(64)
        self.api.user32.GetClassNameW(handle, buffer, 64)
        return buffer.value

    def _send(self, handle, message, wparam=0, lparam=None) -> int:
        ctypes = self.api.ctypes
        answer = ctypes.c_size_t()
        SMTO_ABORTIFHUNG = 2
        if not self.api.user32.SendMessageTimeoutW(handle, message, wparam, lparam, SMTO_ABORTIFHUNG, 1000, ctypes.byref(answer)):
            return 0
        return answer.value

    def _text(self, handle) -> str:
        WM_GETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000E
        length = min(self._send(handle, WM_GETTEXTLENGTH), 4000)
        buffer = self.api.ctypes.create_unicode_buffer(length + 1)
        self._send(handle, WM_GETTEXT, length + 1, self.api.ctypes.cast(buffer, self.api.ctypes.c_void_p))
        return buffer.value

    def elements(self, handle) -> List[UiElement]:
        ctypes = self.api.ctypes
        user32 = self.api.user32
        found = []
        GWL_STYLE = -16
        BM_GETCHECK = 0x00F0
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, self.api.wintypes.HWND, self.api.wintypes.LPARAM)

        def collect(child, _param):
            if len(found) >= MAX_ELEMENTS:
                return False
            if not user32.IsWindowVisible(child):
                return True
            kind = self._class(child).lower()
            style = user32.GetWindowLongW(child, GWL_STYLE) & 0xF
            text = clean_name(self._text(child))
            if kind == "button":
                if style == 7:  # group box: only a caption
                    role = "text"
                elif style in (2, 3, 5, 6):
                    role = "checkbox"
                elif style in (4, 9):
                    role = "radio"
                else:
                    role = "button"
                if role != "text" and not user32.IsWindowEnabled(child):
                    return True
                checked = self._send(child, BM_GETCHECK) == 1 if role in ("checkbox", "radio") else None
                if text:
                    found.append(UiElement(role, text, "", checked, child, self))
            elif kind == "static" and text:
                found.append(UiElement("text", text, "", None, child, self))
            elif kind == "edit" or kind.startswith("richedit"):
                found.append(UiElement("field", "", text[:300], None, child, self))
            return True

        user32.EnumChildWindows(handle, callback_type(collect), 0)
        return found

    def invoke(self, element: UiElement) -> bool:
        BM_CLICK = 0x00F5
        if element.role == "field":
            self.api.user32.SetFocus(element.ref)
            return True
        # Posted, not sent: a button that opens a modal dialog must not block the assistant.
        self.api.user32.PostMessageW(element.ref, BM_CLICK, 0, 0)
        return True


class WindowUi:
    """Chooses UI Automation once, falls back to Win32 for the rest of the run."""

    def __init__(self, api):
        self.api = api
        self.backend = None

    def _backend(self):
        if self.backend is None:
            try:
                self.backend = UiaBackend()
            except Exception:
                self.backend = Win32Backend(self.api)
        return self.backend

    def elements(self, handle) -> List[UiElement]:
        backend = self._backend()
        try:
            items = backend.elements(handle)
        except Exception:
            items = []
        if not items and not isinstance(backend, Win32Backend):
            items = Win32Backend(self.api).elements(handle)
        return items

    def invoke(self, element: UiElement) -> bool:
        return (element.backend or self._backend()).invoke(element)


# Focus: what a keyboard user would hear from a screen reader.

UIA_ExpandCollapsePatternId = 10005
ALL_ROLES = dict(UIA_CONTROL_TYPES)
ALL_ROLES.update({50003: "combo", 50008: "list", 50009: "menu", 50010: "menubar", 50024: "tree item",
                  50023: "tree", 50018: "tab", 50030: "document", 50032: "window"})
SPOKEN_ROLE = {"button": "кнопка", "field": "поле", "checkbox": "флажок", "radio": "переключатель", "link": "ссылка",
               "menu": "пункт меню", "item": "элемент списка", "tab": "вкладка", "combo": "раскрывающийся список",
               "list": "список", "menubar": "строка меню", "tree item": "элемент дерева", "document": "документ",
               "window": "окно", "text": "текст", "tree": "дерево"}


def focused_uia(backend: UiaBackend) -> Optional[UiElement]:
    element = backend.automation.GetFocusedElement()
    if element is None:
        return None
    role = ALL_ROLES.get(element.CurrentControlType, "text")
    value = ""
    pattern = element.GetCurrentPattern(UIA_ValuePatternId)
    if pattern:
        try:
            value = pattern.QueryInterface(backend.uia.IUIAutomationValuePattern).CurrentValue or ""
        except Exception:
            value = ""
    checked = None
    toggle = element.GetCurrentPattern(UIA_TogglePatternId)
    if toggle and role in ("checkbox", "menu", "item"):
        try:
            checked = toggle.QueryInterface(backend.uia.IUIAutomationTogglePattern).CurrentToggleState == 1
        except Exception:
            checked = None
    return UiElement(role, clean_name(element.CurrentName or ""), value.strip()[:500], checked, element, backend)


def describe_focus(element: Optional[UiElement]) -> str:
    if element is None:
        return "Фокус не определён."
    parts = [element.name or "без названия", SPOKEN_ROLE.get(element.role, element.role)]
    if element.checked is not None:
        parts.append("отмечен" if element.checked else "не отмечен")
    if element.value and element.value != element.name:
        parts.append("содержит: " + element.value[:200])
    elif element.role == "field":
        parts.append("пусто")
    return ", ".join(parts) + "."


def expand_menu(backend: UiaBackend, element: UiElement) -> bool:
    pattern = element.ref.GetCurrentPattern(UIA_ExpandCollapsePatternId)
    if pattern:
        pattern.QueryInterface(backend.uia.IUIAutomationExpandCollapsePattern).Expand()
        return True
    return backend.invoke(element)


# Keyboard: SendInput, the same path a physical keyboard takes, so every program accepts it.

KEYS = {"enter": 0x0D, "escape": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
        "page up": 0x21, "page down": 0x22, "alt": 0x12, "f10": 0x79, "shift": 0x10, "control": 0x11, "a": 0x41,
        "applications": 0x5D}
EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2E, 0x5D}


class Keyboard:
    def __init__(self, api):
        ctypes = api.ctypes
        wintypes = api.wintypes
        self.ctypes = ctypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):  # only to give the union its real size
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class _UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

        self.KEYBDINPUT, self.INPUT = KEYBDINPUT, INPUT
        self.send_input = api.user32.SendInput
        self.send_input.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.send_input.restype = wintypes.UINT

    def _event(self, vk=0, scan=0, flags=0):
        item = self.INPUT()
        item.type = 1  # INPUT_KEYBOARD
        item.u.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        return item

    def _send(self, events) -> bool:
        array = (self.INPUT * len(events))(*events)
        return self.send_input(len(events), array, self.ctypes.sizeof(self.INPUT)) == len(events)

    def press(self, key: str, modifiers=()) -> bool:
        KEYUP, EXTENDEDKEY = 0x2, 0x1
        vk = KEYS[key]
        flags = EXTENDEDKEY if vk in EXTENDED else 0
        events = [self._event(KEYS[mod]) for mod in modifiers]
        events += [self._event(vk, 0, flags), self._event(vk, 0, flags | KEYUP)]
        events += [self._event(KEYS[mod], 0, KEYUP) for mod in reversed(modifiers)]
        return self._send(events)

    def type_text(self, text: str) -> bool:
        """KEYEVENTF_UNICODE: any Russian letter regardless of the keyboard layout."""
        UNICODE, KEYUP = 0x4, 0x2
        events = []
        for char in text:
            if char == "\n":
                events += [self._event(KEYS["enter"]), self._event(KEYS["enter"], 0, KEYUP)]
                continue
            data = char.encode("utf-16-le")
            for index in range(0, len(data), 2):
                unit = int.from_bytes(data[index:index + 2], "little")
                events += [self._event(0, unit, UNICODE), self._event(0, unit, UNICODE | KEYUP)]
        ok = True
        for start in range(0, len(events), 200):
            ok = self._send(events[start:start + 200]) and ok
        return ok
