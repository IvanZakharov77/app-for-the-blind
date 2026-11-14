"""Telegram calls by voice through Telegram Desktop (Ivan, 2026-11-14):

  «Вега, позвони Артем Рева» opens the chat in Telegram Desktop and presses its call button.
  «Вам звонит Маша в Телеграм» when someone calls; «Вега, прими звонок» (or «ответь» while it rings)
  presses «Принять», «Вега, положи трубку» ends or declines the call.

Vega's Telegram library cannot carry a voice call, so the talk itself happens in Telegram Desktop with its
own microphone and speakers; Vega only finds the program's buttons through Windows UI Automation and
presses them. The button names below are a first guess; the «проверь Телеграм» report from the person's
laptop tells which names their Telegram Desktop really shows.
"""

import os
import re
import subprocess
import time
from typing import Callable, List, Optional, Sequence, Tuple

CALL = re.compile(r"(?:позвони|позвонить|позвоните|набери|наберите|звони|вызови|звякни|сделай звонок|соедини меня с)"
                  r"(?: (?:в|по|через) телеграм\w*)? (.+)")
ANSWER = ("прими звонок", "принять звонок", "ответь на звонок", "возьми трубку", "подними трубку", "прими вызов",
          "ответь на вызов", "бери трубку")
HANGUP = ("положи трубку", "заверши звонок", "закончи звонок", "сбрось звонок", "отклони звонок",
          "отбой звонка", "повесь трубку", "заверши вызов", "отклони вызов", "брось трубку", "не бери трубку")
RING_SECONDS = 60.0  # an incoming call rings about this long in Telegram

CALL_BUTTONS = ("позвонить", "звонок", "аудиозвонок", "голосовой звонок", "call", "voice call", "audio call")
ANSWER_BUTTONS = ("принять", "ответить", "accept", "answer")
HANGUP_BUTTONS = ("завершить", "положить трубку", "сбросить", "отклонить", "hang up", "end call", "decline", "end")
NOT_FOUND = ("Не вижу программу Телеграм на этом компьютере. Для звонков нужна установленная программа "
             "Telegram Desktop, в которой выполнен вход.")


def button_matches(name: str, wanted: Sequence[str]) -> bool:
    name = name.lower().replace("ё", "е").strip()
    return any(name == word or name.startswith(word + " ") for word in wanted)


class Desktop:
    """Telegram Desktop on this Windows: open a chat, press a button by its name."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep):
        self.sleep = sleep

    def exe(self):
        from .telegram_desktop import find_exe
        return find_exe()

    def windows(self) -> List[int]:
        from .media_watch import Windows
        return [window[0] for window in Windows().list() if window[2] == "telegram.exe"]

    def open_chat(self, person: int) -> bool:
        """The person's chat opens through the tg: link Telegram Desktop registers on install."""
        exe = self.exe()
        try:
            if exe is not None:
                subprocess.Popen([str(exe), "--", "tg://user?id={}".format(person)], close_fds=True)
            else:
                os.startfile("tg://user?id={}".format(person))  # type: ignore[attr-defined]
        except OSError:
            return False
        for _ in range(20):
            if self.windows():
                return True
            self.sleep(0.5)
        return False

    def press(self, wanted: Sequence[str], seconds: float = 8.0) -> bool:
        """Presses the first visible Telegram button whose name fits; tries again while the window draws."""
        from .window_ui import UiaBackend
        backend = UiaBackend()
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            for handle in self.windows():
                try:
                    for element in backend.elements(handle):
                        if element.role == "button" and button_matches(element.name, wanted):
                            if not backend.invoke(element):
                                click(element.ref)
                            return True
                except Exception:
                    continue
            self.sleep(0.5)
        return False


def click(element) -> None:
    """A mouse click in the middle of a UI Automation element that has no Invoke action."""
    import ctypes
    rect = element.CurrentBoundingRectangle
    ctypes.windll.user32.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up


class Calls:
    """What Vega says for call commands. find(name) gives (person, name), a list of several, or a text."""

    def __init__(self, find: Callable[[str], object], readable: Callable[[str], str],
                 desktop: Optional[Desktop] = None, clock: Callable[[], float] = time.monotonic):
        self.find = find
        self.readable = readable
        self.desktop = desktop
        self.clock = clock
        self.ringing: Optional[Tuple[int, str, float]] = None  # (person, name, since) of a call ringing now

    def _desktop(self) -> Desktop:
        if self.desktop is None:
            self.desktop = Desktop()
        return self.desktop

    def is_ringing(self) -> bool:
        return self.ringing is not None and self.clock() - self.ringing[2] < RING_SECONDS

    def incoming(self, person: int, name: str, user: str = "") -> str:
        self.ringing = (person, name, self.clock())
        to = user + ", вам" if user else "Вам"
        return "{} звонит {} в Телеграм. Чтобы ответить, скажите: Вега, прими звонок.".format(to, self.readable(name))

    def ended(self) -> None:
        self.ringing = None

    def handle(self, command: str, ready: bool) -> Optional[str]:
        if command in ANSWER or (command in ("ответь", "ответить") and self.is_ringing()):
            return self.answer()
        if command in HANGUP or (command in ("сбрось", "не отвечай", "не бери") and self.is_ringing()):
            return self.hang_up()
        match = CALL.fullmatch(command)
        if match:
            return self.call(match.group(1)) if ready else "Телеграм ещё не подключён. Скажите: Вега, подключи Телеграм."
        return None

    def call(self, spoken_name: str) -> str:
        found = self.find(spoken_name)
        if isinstance(found, str):
            return found
        if isinstance(found, list):
            names = ", ".join(self.readable(item[1]) for item in found)
            return "Нашла несколько: {}. Скажите имя и фамилию полностью.".format(names)
        person, name = found
        desktop = self._desktop()
        if desktop.exe() is None and not desktop.windows():
            return NOT_FOUND
        if not desktop.open_chat(person):
            return "Не получилось открыть чат с {} в программе Телеграм.".format(self.readable(name))
        if not desktop.press(CALL_BUTTONS):
            return ("Открыла чат с {} в программе Телеграм, но не нашла кнопку звонка. "
                    "Скажите: Вега, проверь Телеграм, и отправьте файл разработчику.").format(self.readable(name))
        return "Звоню {}. Чтобы закончить, скажите: Вега, положи трубку.".format(self.readable(name))

    def answer(self) -> str:
        desktop = self._desktop()
        if not desktop.windows():
            return "Сейчас никто не звонит."
        if not desktop.press(ANSWER_BUTTONS, seconds=4.0):
            return "Не нашла кнопку ответа в программе Телеграм. Скажите: Вега, проверь Телеграм, пока звонят."
        self.ringing = None
        return "Соединяю."

    def hang_up(self) -> str:
        desktop = self._desktop()
        if not desktop.windows() or not desktop.press(HANGUP_BUTTONS, seconds=3.0):
            return "Не нашла звонок в программе Телеграм."
        self.ringing = None
        return "Звонок завершён."
