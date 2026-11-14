"""Telegram by voice (Ivan, 2026-11-14), like Siri reads messages:

  «Игорь, вам сообщение от Маши: …» — a new private message is read aloud as soon as it comes.
  «Вега, ответь» / «Вега, отправь сообщение Маше» — «Хорошо, Игорь, диктуйте сообщение», the next phrase
  is sent as text. Ctrl (or «отмена») while Vega waits for the text drops it, and Vega waits for commands.
  «Вега, прочитай сообщения» — the unread private messages, «Вега, повтори сообщение» — the last one.

Vega logs in to the person's own account once (a helper types the phone number and the code at install,
or says them after «Вега, подключи Телеграм»); the login is kept encrypted by Windows for this user.
Groups, channels and bots are never read aloud: only people writing to the person.
"""

import difflib
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Deque, List, Optional, Tuple

SESSION_FILE = "telegram.session"
CONTACTS_FILE = "telegram-contacts.json"
WINDOW_SHOWN = "telegram-window-shown"  # the login window opened once on this computer
ONE_TIME_VERSIONS = ("0.7.23", "0.7.24", "0.7.26")  # Ivan, 2026-11-14: the window opens by itself only after these updates (once)
ONE_TIME_VERSION = ONE_TIME_VERSIONS[-1]
SETTINGS_FILE = "telegram-settings.json"  # «читать сразу» and voice aliases («сын» is Сергей Кот)
CONTACTS_EVERY = 24 * 3600  # seconds between contact list requests
WAIT_TEXT = 45.0  # seconds Vega waits for the dictated message before she drops it
MAX_SPOKEN = 900  # a longer message is cut: «Дальше длинно, скажите: повтори сообщение» reads it whole

CONNECT = ("подключи телеграм", "подключить телеграм", "войди в телеграм", "настрой телеграм", "подключи телеграмм",
           "подключи телегу", "войди в телеграмм")
DISCONNECT = ("отключи телеграм", "выйди из телеграма", "отключи телеграмм", "выйди из телеграмма")
READ = ("прочитай сообщения", "прочитай новые сообщения", "какие новые сообщения", "есть новые сообщения",
        "новые сообщения", "есть сообщения", "какие сообщения", "что пришло в телеграм", "прочитай телеграм",
        "что в телеграме", "есть что в телеграме", "прочитай непрочитанные сообщения", "непрочитанные сообщения")
REPEAT = ("повтори сообщение", "прочитай сообщение еще раз", "прочитай последнее сообщение", "последнее сообщение",
          "повтори последнее сообщение", "прочитай сообщение полностью")
REPLY = ("ответь", "ответь ему", "ответь ей", "ответить", "ответь на сообщение", "напиши ответ", "отправь ответ",
         "ответь в телеграм", "ответь в телеграме")
PROBE = ("проверь телеграм", "проверка телеграма", "проверь телеграмм", "проверь программу телеграм")
WHO = ("кто мне написал", "кто мне писал", "кто написал", "кто писал", "мне кто нибудь писал", "от кого сообщения")
AT_ONCE = ("читай сообщения сразу", "читай телеграм сразу", "читай новые сообщения сразу")
ASK_FIRST = ("спрашивай перед чтением", "спрашивай перед чтением сообщений", "не читай сообщения сразу")
REPEAT_DICTATED = ("повтори", "повтори что я продиктовал", "повтори что я сказал", "что я продиктовал", "прочитай еще раз",
                   "повтори сообщение", "что я сказал")
FIX = ("исправить", "исправь", "заново", "продиктую заново", "исправь текст", "переписать", "напишу заново")
YES = ("да", "верно", "правильно", "отправь", "отправляй", "давай", "конечно", "ага", "угу", "прочитай", "читай")
NO = ("нет", "не", "не надо", "потом", "позже")
FROM = re.compile(r"(?:прочитай|прочти|покажи|читай) (?:все |последние |новые )?сообщени\w* (?:от|с) (.+)")
ALIAS = re.compile(r"запомни (?:что )?(.+?) (?:это|зовут) (.+)")
REPLY_TO = re.compile(r"ответь (?!на |ему$|ей$|им$)(.+)")
NAME_NOISE = ("для", "к", "ко", "мне", "контакту", "контакт", "контакта", "пользователю", "в", "через", "по")
OFFER_SECONDS = 20.0  # how long «Прочитать?» waits for «да»
CANCEL = ("отмена", "отмени", "отмени отправку", "не надо", "не отправляй", "отбой", "стоп", "хватит", "стой", "передумал", "передумала")
SEND = re.compile(r"(?:отправь|отправить|отправьте|напиши|написать|напишите|пошли|послать|пошлите|скинь)"
                  r" (?:(?:мне )?сообщение |смс |сообщения )?(.+)")
TELEGRAM_WORDS = re.compile(r"\b(?:в|через|по|на) телеграм\w*|\bтелеграм\w*|\bсообщени\w*|\bсмс\b")

LATIN = {"a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "й",
         "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т",
         "u": "у", "v": "в", "w": "в", "x": "кс", "y": "и", "z": "з"}
LATIN_PAIRS = (("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ch", "ч"), ("sh", "ш"), ("ts", "ц"),
               ("ya", "я"), ("yu", "ю"), ("yo", "ё"), ("ye", "е"), ("ia", "ия"), ("iy", "ий"), ("ey", "ей"),
               ("ay", "ай"), ("oy", "ой"), ("uy", "уй"))
UKRAINIAN = str.maketrans({"і": "и", "ї": "и", "є": "е", "ґ": "г", "ё": "е"})
ENDINGS = ("ами", "ями", "ою", "ею", "ей", "ой", "ом", "ем", "ам", "ям", "ах", "ях", "у", "ю", "е", "и", "а", "я", "ы", "ь")


def readable(name: str) -> str:
    """«Masha Petrova» → «Маша Петрова»: Irina reads Latin letters badly."""
    text = name
    for latin, cyrillic in LATIN_PAIRS:
        text = re.sub(latin, cyrillic, text, flags=re.I)
    result = "".join(LATIN.get(char.lower(), char) if char.isascii() and char.isalpha() else char for char in text)
    words = [word[:1].upper() + word[1:] if word[:1].isalpha() else word for word in result.split()]
    clean = " ".join(word for word in words if any(char.isalpha() for char in word))
    return clean or "без имени"


def _stem(word: str) -> str:
    word = word.lower().translate(UKRAINIAN)
    if len(word) > 3:
        for ending in ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                return word[:-len(ending)]
    return word


def _words(name: str) -> List[str]:
    return [_stem(word) for word in re.findall(r"[а-яa-z]+", readable(name).lower().translate(UKRAINIAN))]


def match_contacts(spoken: str, contacts: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """The contacts meant by «маше», «маме», «игорю петрову»: best first; one when it is clear."""
    wanted = _words(spoken)
    if not wanted:
        return []
    scored = []
    for contact_id, name in contacts:
        words = _words(name)
        if not words:
            continue
        score = sum(max((difflib.SequenceMatcher(None, want, word).ratio() if want[0] == word[0] else 0.0)
                        for word in words) for want in wanted) / len(wanted)  # «важно» is never «Иванов»
        if score >= 0.72:
            scored.append((score, contact_id, name))
    scored.sort(key=lambda item: -item[0])
    if not scored:
        return []
    best = scored[0][0]
    close = [(contact_id, name) for score, contact_id, name in scored if score >= best - 0.08]
    unique = []
    for item in close:
        if item[0] not in [seen[0] for seen in unique]:
            unique.append(item)
    return unique


def spoken_digits(text: str) -> str:
    """«плюс три восемь ноль пятьдесят один два три» → «38050123»; digits said in groups too."""
    from .numbers import words_to_number
    words = [word for word in re.findall(r"[а-я]+|\d+", text.lower().replace("ё", "е")) if word not in ("плюс", "и")]
    digits, index = [], 0
    while index < len(words):
        if words[index].isdigit():
            digits.append(words[index])
            index += 1
            continue
        for end in range(len(words), index, -1):
            value = words_to_number(" ".join(words[index:end]))
            if value is not None:
                digits.append(str(int(value)))
                index = end
                break
        else:
            index += 1
    return "".join(digits)


def phone_number(text: str) -> Optional[str]:
    digits = spoken_digits(text)
    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits  # «ноль пятьдесят …»: a Ukrainian number said without the country code
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return "+" + digits if 11 <= len(digits) <= 15 else None


def say_digits(number: str) -> str:
    return " ".join(number.lstrip("+"))


# Windows keeps the login readable only by this Windows user (DPAPI); elsewhere (tests) it is plain.
def protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    return _dpapi(data, True)


def unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    return _dpapi(data, False)


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    source, result = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), Blob()
    call = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):  # 1 = no UI
        raise OSError("Windows не смогла {} вход в Телеграм".format("зашифровать" if encrypt else "прочитать"))
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def api_keys() -> Optional[Tuple[int, str]]:
    """Vega's own Telegram app keys, put into the installer by the build from GitHub secrets."""
    try:
        from . import telegram_keys  # generated by the build, never in the repository
    except ImportError:
        return None
    if not getattr(telegram_keys, "API_ID", 0) or not getattr(telegram_keys, "API_HASH", ""):
        return None
    return int(telegram_keys.API_ID), str(telegram_keys.API_HASH)


class TelethonBackend:
    """The real Telegram client in its own thread; every call waits for its answer."""

    def __init__(self, api_id: int, api_hash: str, session: str, version: str = ""):
        import asyncio
        self.asyncio = asyncio
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="vega-telegram", daemon=True).start()
        self.api_id, self.api_hash, self.version = api_id, api_hash, version
        self.client = self.run(self._make(session))
        self.phone_hash = ""
        self.phone = ""

    def run(self, coroutine, timeout: float = 40.0):
        return self.asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    async def _make(self, session: str):
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        return TelegramClient(StringSession(session or None), self.api_id, self.api_hash, device_model="Vega",
                              system_version="Windows", app_version=self.version or "1.0", lang_code="ru",
                              system_lang_code="ru")

    def connect(self) -> bool:
        async def go():
            await self.client.connect()
            return await self.client.is_user_authorized()
        return self.run(go())

    def send_code(self, phone: str) -> None:
        async def go():
            if not self.client.is_connected():
                await self.client.connect()
            sent = await self.client.send_code_request(phone)
            return sent.phone_code_hash
        self.phone, self.phone_hash = phone, self.run(go())

    def sign_in(self, code: str) -> str:
        from telethon import errors

        async def go():
            try:
                await self.client.sign_in(phone=self.phone, code=code, phone_code_hash=self.phone_hash)
                return "ok"
            except errors.SessionPasswordNeededError:
                return "password"
            except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
                return "bad_code"
            except errors.PhoneCodeExpiredError:
                return "expired"
        return self.run(go())

    def sign_in_password(self, password: str) -> str:
        from telethon import errors

        async def go():
            try:
                await self.client.sign_in(password=password)
                return "ok"
            except errors.PasswordHashInvalidError:
                return "bad_password"
        return self.run(go())

    def session(self) -> str:
        return self.client.session.save()

    def listen(self, on_message: Callable[[int, str, str], None]) -> None:
        from telethon import events

        async def handler(event):
            if not event.is_private or event.out:
                return
            sender = await event.get_sender()
            if sender is None or getattr(sender, "bot", False) or getattr(sender, "is_self", False):
                return
            on_message(sender.id, display_name(sender), describe(event.message))
        self.client.add_event_handler(handler, events.NewMessage(incoming=True))

    def contacts(self) -> List[Tuple[int, str]]:
        from telethon import functions

        async def go():
            people = {}
            async for dialog in self.client.iter_dialogs(limit=300):
                entity = dialog.entity
                if dialog.is_user and not getattr(entity, "bot", False) and not getattr(entity, "is_self", False):
                    people[entity.id] = display_name(entity)
            found = await self.client(functions.contacts.GetContactsRequest(hash=0))
            for user in getattr(found, "users", []):
                if not getattr(user, "bot", False):
                    people.setdefault(user.id, display_name(user))
            return list(people.items())
        return self.run(go(), 60.0)

    def send(self, person: int, text: str) -> None:
        self.run(self.client.send_message(person, text))

    def unread(self) -> List[Tuple[int, str, List[str]]]:
        async def go():
            found = []
            async for dialog in self.client.iter_dialogs(limit=100):
                entity = dialog.entity
                if not dialog.is_user or getattr(entity, "bot", False) or dialog.unread_count <= 0:
                    continue
                messages = await self.client.get_messages(entity, limit=min(dialog.unread_count, 5))
                texts = [describe(message) for message in reversed(messages) if not message.out]
                if texts:
                    found.append((entity.id, display_name(entity), texts))
            return found
        return self.run(go(), 60.0)

    def history(self, person: int, count: int) -> List[Tuple[bool, str]]:
        async def go():
            messages = await self.client.get_messages(person, limit=count)
            return [(bool(message.out), describe(message)) for message in reversed(messages)]
        return self.run(go())

    def mark_read(self, person: int) -> None:
        self.run(self.client.send_read_acknowledge(person))

    def log_out(self) -> None:
        self.run(self.client.log_out())


def display_name(user) -> str:
    name = " ".join(part for part in (getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or "") if part)
    return name or getattr(user, "username", "") or "без имени"


def describe(message) -> str:
    text = (getattr(message, "message", "") or "").strip()
    kind = ""
    if getattr(message, "voice", None):
        kind = "Голосовое сообщение. Слушать голосовые я пока не умею."
    elif getattr(message, "video_note", None) or getattr(message, "video", None):
        kind = "Видео."
    elif getattr(message, "photo", None):
        kind = "Фотография."
    elif getattr(message, "sticker", None):
        kind = "Стикер."
    elif getattr(message, "contact", None):
        kind = "Контакт."
    elif getattr(message, "geo", None):
        kind = "Место на карте."
    elif getattr(message, "document", None):
        kind = "Файл."
    if kind and text:
        return kind + " Подпись: " + text
    return text or kind or "Пустое сообщение."


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def problem(error: Exception, fallback: str) -> str:
    """Telegram's «wait N seconds» is said as it is: Vega never retries in a loop (an account that keeps
    hammering the servers is what Telegram blocks)."""
    seconds = getattr(error, "seconds", None)
    if type(error).__name__.startswith("FloodWait") and seconds:
        minutes = max(1, int(seconds) // 60)
        return "Телеграм просит подождать {} мин. Попробуйте позже.".format(minutes)
    return fallback


class Telegram:
    """What Vega says and does for Telegram commands; the client is behind backend (a fake in tests)."""

    def __init__(self, folder: Optional[Path], backend_factory: Optional[Callable[[str], object]] = None,
                 user_name: Callable[[], str] = lambda: "", clock: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = lambda message: None):
        self.folder = folder
        self.factory = backend_factory
        self.user_name = user_name
        self.clock = clock
        self.log = log
        self.backend = None
        self.ready = False  # logged in and listening
        self.news: Deque[str] = deque()
        self.lock = threading.Lock()
        self.last: Optional[Tuple[int, str, str]] = None  # (person, name, text) of the last message read
        self.waiting: Optional[dict] = None  # {"kind": "text"/"phone"/"confirm_phone"/"code"/"password", ...}
        self.hinted = False
        self._contacts: List[Tuple[int, str]] = []
        self._seen_session = 0.0
        self.background = True  # tests run the contact request in place
        self.busy = False  # the person is saying a command: new messages wait a moment
        self.polite = False  # in a talk with Gemini Vega excuses herself before the message (Ivan, 2026-11-14)
        self.notes: List[str] = []  # Vega's own Telegram notices (logged out, …), said when she is free
        self.settings, self.aliases = self._load_settings()
        self._code_asked = -1000.0
        self._contacts_day = 0.0
        self.wall = time.time
        self._checked = 0.0

    # Start and login

    @property
    def available(self) -> bool:
        return self.factory is not None

    def _session_path(self) -> Optional[Path]:
        return None if self.folder is None else self.folder / SESSION_FILE

    def saved_session(self) -> str:
        path = self._session_path()
        try:
            return unprotect(path.read_bytes()).decode("utf-8") if path is not None and path.exists() else ""
        except (OSError, ValueError):
            return ""

    def _save_session(self) -> None:
        path = self._session_path()
        if path is None or self.backend is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(protect(self.backend.session().encode("utf-8")))

    def start(self) -> None:
        """At Vega's start: a saved login connects in the background, Vega does not wait for it."""
        if not self.available or not self.saved_session():
            return
        try:
            self._seen_session = self._session_path().stat().st_mtime
        except OSError:
            pass
        threading.Thread(target=self._connect_saved, name="vega-telegram-start", daemon=True).start()

    def _connect_saved(self) -> None:
        for attempt in range(6):  # no internet yet right after Windows starts
            try:
                self.backend = self.factory(self.saved_session())
                if self.backend.connect():
                    self._listen()
                    return
                self.log("Телеграм: вход больше не действует, нужно подключить заново.")
                with self.lock:
                    self.notes.append("Телеграм отключился. Чтобы подключить его снова, скажите: Вега, подключи Телеграм.")
                return
            except Exception as error:
                self.log("Телеграм не подключился: {}".format(error))
                time.sleep(min(60, 10 * (attempt + 1)))

    def _listen(self) -> None:
        self.backend.listen(self._arrived)
        self.ready = True
        if self.background:
            threading.Thread(target=self._refresh_contacts, name="vega-telegram-contacts", daemon=True).start()
        else:
            self._refresh_contacts()

    def _load_settings(self):
        import json
        if self.folder is None:
            return {}, {}
        try:
            data = json.loads((self.folder / SETTINGS_FILE).read_text(encoding="utf-8"))
            return dict(data.get("settings", {})), dict(data.get("aliases", {}))
        except (OSError, ValueError, AttributeError):
            return {}, {}

    def _save_settings(self) -> None:
        import json
        if self.folder is None:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / SETTINGS_FILE).write_text(json.dumps({"settings": self.settings, "aliases": self.aliases},
                                                                ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _contacts_path(self) -> Optional[Path]:
        return None if self.folder is None else self.folder / CONTACTS_FILE

    def _refresh_contacts(self) -> None:
        """The contact list is asked from Telegram at most once a day (Ivan, 2026-11-14) and kept on disk,
        so restarts ask nothing. People who write in between are added from their messages."""
        import json
        path = self._contacts_path()
        if not self._contacts and path is not None:
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                self._contacts = [(int(person), str(name)) for person, name in saved["people"]]
                self._contacts_day = float(saved["at"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if self._contacts and self.wall() - self._contacts_day < CONTACTS_EVERY:
            return
        self._contacts_day = self.wall()
        try:
            self._contacts = self.backend.contacts()
        except Exception as error:
            self.log("Телеграм: список контактов не загрузился: {}".format(error))
            return
        self._save_contacts()

    def _save_contacts(self) -> None:
        import json
        path = self._contacts_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"at": self._contacts_day, "people": self._contacts}, ensure_ascii=False),
                            encoding="utf-8")
        except OSError:
            pass

    def _arrived(self, person: int, name: str, text: str) -> None:
        if person not in [known for known, _name in self._contacts]:
            self._contacts.append((person, name))  # «ответь» and «напиши ему» work without asking Telegram again
            self._save_contacts()
        with self.lock:
            self.news.append((person, name, text))

    def _message_text(self, person: int, name: str, text: str, hint: bool = True) -> str:
        self.last = (person, name, text)
        body = text if len(text) <= MAX_SPOKEN else text[:MAX_SPOKEN].rsplit(" ", 1)[0] + ". Дальше длинно, скажите: Вега, повтори сообщение."
        hint = ""  # Ivan, 2026-11-14: after reading Vega does not suggest a reply
        if self.backend is not None:
            try:
                self.backend.mark_read(person)
            except Exception:
                pass
        return "Сообщение от {}: {}{}".format(readable(name), body, hint)

    def _new_login(self) -> None:
        """The helper's window saved a login while Vega runs: connect without a restart."""
        now = self.clock()
        if self.ready or not self.available or now - self._checked < 5:
            return
        self._checked = now
        path = self._session_path()
        try:
            changed = path is not None and path.exists() and path.stat().st_mtime != self._seen_session
        except OSError:
            changed = False
        if changed:
            self._seen_session = path.stat().st_mtime
            if self.backend is None:
                threading.Thread(target=self._connect_saved, name="vega-telegram-login", daemon=True).start()

    def take_news(self) -> List[str]:
        """What to say about new messages now. Nothing while Vega waits for an answer, talks with the person
        or listens for a command: a message never cuts into a conversation (TZ 7)."""
        self._new_login()
        if self.waiting is not None or self.busy:
            return []
        with self.lock:
            items, self.news = list(self.news), deque()
            notes, self.notes = list(self.notes), []
        if not items:
            return notes
        user = self.user_name()
        to = user + ", вам" if user else "Вам"
        if self.polite:
            to = "Прошу прощения, " + (user + ", вам" if user else "вам")
        if self.settings.get("read_at_once", True):  # Ivan, 2026-11-14: read at once, no «Прочитать или нет?»
            said = [self._message_text(*item) for item in items]
            if self.polite:  # a talk with Gemini: «Прошу прощения, Игорь», then the talk goes on
                said[0] = "Прошу прощения{}. {}".format(", " + user if user else "", said[0])
            return notes + said
        senders = []
        for _person, name, _text in items:
            if readable(name) not in senders:
                senders.append(readable(name))
        self.waiting = {"kind": "offer", "items": items, "until": self.clock() + OFFER_SECONDS, "talk": self.polite}
        if len(items) == 1:
            return notes + ["{} пришло сообщение в Телеграм от {}. Прочитать или нет?".format(to, senders[0])]
        return notes + ["{} пришли сообщения в Телеграм от: {}. Прочитать или нет?".format(to, ", ".join(senders))]

    # Commands

    def handle(self, command: str) -> Optional[str]:
        """Vega's answer to a Telegram command, or None when the command is not about Telegram."""
        if command in PROBE:
            if sys.platform != "win32":
                return "Проверка Телеграма работает только на Windows."
            from .diagnostics import desktop
            from .telegram_desktop import probe
            return probe(desktop())
        if command in CONNECT:
            return self.connect()
        if command in DISCONNECT:
            return self.disconnect()
        if command in READ:
            return self.read_unread()
        if command in WHO:
            return self.who_wrote()
        if command in REPEAT:
            if self.last is None:
                return "Новых сообщений пока не было."
            return "Сообщение от {}: {}".format(readable(self.last[1]), self.last[2])
        if command in REPLY:
            if self.last is None:
                return None if not self.ready else "Отвечать пока некому: новых сообщений не было."
            return self._dictate(self.last[0], self.last[1])
        if command in AT_ONCE:
            return self._set("read_at_once", True, "Хорошо, буду читать новые сообщения сразу.")
        if command in ASK_FIRST:
            return self._set("read_at_once", False, "Хорошо, перед чтением буду спрашивать.")
        match = FROM.fullmatch(command)
        if match:
            return self.read_from(match.group(1))
        match = ALIAS.fullmatch(command)
        if match and self.ready and not isinstance(self._find(match.group(2)), str):
            return self.remember_alias(match.group(1), match.group(2))  # only a real contact: «запомни …» is also a note
        match = REPLY_TO.fullmatch(command)
        if match and self.ready:
            if self.last is not None and not self._split(match.group(1))[2]:
                return self._confirm(self.last[0], self.last[1], match.group(1))  # «ответь хорошо, приду»
            return self.send_to(match.group(1), with_text=True)
        match = SEND.fullmatch(command)
        if match and TELEGRAM_WORDS.search(command):
            return self.send_to(match.group(1), with_text=True)
        # «отправь Артему Реве привет», «напиши маме я скоро буду»: no word «сообщение», but it starts with a
        # contact. «напиши привет» (typing into a field) starts with no contact and stays a typing command.
        match = SEND.fullmatch(command)
        if match and self.ready and self._split(match.group(1))[2]:
            return self.send_to(match.group(1), with_text=True)
        return None

    def _set(self, key: str, value, answer: str) -> str:
        self.settings[key] = value
        self._save_settings()
        return answer

    def _not_ready(self) -> Optional[str]:
        if not self.available:
            return "Телеграм в этой версии Веги не настроен."
        if not self.ready:
            return "Телеграм ещё не подключён. Скажите: Вега, подключи Телеграм."
        return None

    def connect(self) -> str:
        if not self.available:
            return "Телеграм в этой версии Веги не настроен."
        if self.ready:
            return "Телеграм уже подключён."
        spawn = getattr(self, "spawn_window", None)
        if spawn is not None:  # Ivan, 2026-11-14: the helper types the number and the code in the window
            try:
                spawn()
                return WINDOW_OPENED
            except Exception as error:
                self.log("Окно подключения Телеграма не открылось: {}".format(error))
        self.waiting = {"kind": "phone", "until": self.clock() + 90}
        return "Скажите номер телефона, к которому привязан Телеграм, полностью, с кодом страны."

    def disconnect(self) -> str:
        if not self.ready:
            return "Телеграм и так не подключён."
        try:
            self.backend.log_out()
        except Exception as error:
            self.log("Телеграм: выход не удался: {}".format(error))
        self.ready, self.backend = False, None
        path = self._session_path()
        try:
            if path is not None and path.exists():
                path.unlink()
        except OSError:
            pass
        return "Телеграм отключён."

    def _unread(self):
        blocked = self._not_ready()
        if blocked:
            return None, blocked
        try:
            return self.backend.unread(), ""
        except Exception as error:
            self.log("Телеграм: непрочитанные не загрузились: {}".format(error))
            return None, problem(error, "Нет связи с Телеграмом. Проверьте интернет.")

    def read_unread(self) -> str:
        found, failed = self._unread()
        if found is None:
            return failed
        if not found:
            return "Новых сообщений нет."
        parts = []
        for person, name, texts in found[:5]:
            parts.append("От {}: {}".format(readable(name), " ".join(texts)))
            self.last = (person, name, texts[-1])
            try:
                self.backend.mark_read(person)
            except Exception:
                pass
        more = " Есть ещё сообщения, скажите: прочитай сообщения." if len(found) > 5 else ""
        return " ".join(parts) + more

    def who_wrote(self) -> str:
        found, failed = self._unread()
        if found is None:
            return failed
        if not found:
            return "Новых сообщений нет."
        from .numbers import plural
        names = ["{}, {} {}".format(readable(name), len(texts), plural(len(texts), ("сообщение", "сообщения", "сообщений")))
                 for _person, name, texts in found[:6]]
        return "Вам написали: {}. Скажите, например: прочитай сообщения от {}.".format("; ".join(names), readable(found[0][1]))

    def read_from(self, spoken_name: str) -> str:
        blocked = self._not_ready()
        if blocked:
            return blocked
        found = self._find(spoken_name)
        if isinstance(found, str):
            return found
        person, name = found
        try:
            texts = self.backend.history(person, 3)
        except Exception as error:
            self.log("Телеграм: переписка не загрузилась: {}".format(error))
            return problem(error, "Нет связи с Телеграмом. Проверьте интернет.")
        if not texts:
            return "От {} сообщений нет.".format(readable(name))
        self.last = (person, name, texts[-1][1])
        try:
            self.backend.mark_read(person)
        except Exception:
            pass
        said = " ".join(("Вы: " if mine else "") + text for mine, text in texts)
        return "Последние сообщения с {}: {}".format(readable(name), said)

    def _find(self, spoken_name: str):
        """(person, name) for a spoken name or alias, or what to say when it is not one clear person."""
        name = " ".join(word for word in spoken_name.split() if word not in NAME_NOISE)
        if not name:
            return "Кому? Скажите, например: Вега, отправь сообщение Маше."
        alias = self.aliases.get(" ".join(_stem(word) for word in name.split()))
        if alias is not None:
            return int(alias[0]), alias[1]
        if not self._contacts:
            self._refresh_contacts()
        found = match_contacts(name, self._contacts)
        if not found:
            return "Не нашла «{}» в контактах Телеграма.".format(name)
        if len(found) > 1:
            return found[:4]
        return found[0]

    def remember_alias(self, alias: str, spoken_name: str) -> str:
        blocked = self._not_ready()
        if blocked:
            return blocked
        alias = " ".join(word for word in alias.split() if word not in ("мой", "моя", "мое", "мои"))
        found = self._find(spoken_name)
        if isinstance(found, str):
            return found
        if isinstance(found, list):
            return "Нашла несколько: {}. Скажите имя полностью.".format(", ".join(readable(item[1]) for item in found))
        self.aliases[" ".join(_stem(word) for word in alias.split())] = [found[0], found[1]]
        self._save_settings()
        return "Запомнила: {} это {}.".format(alias, readable(found[1]))

    def _name_and_text(self, spoken: str) -> Tuple[str, str]:
        name, text, _found = self._split(spoken)
        return name, text

    def _split(self, spoken: str) -> Tuple[str, str, bool]:
        """«артем рева привет чувак» → («артем рева», «привет чувак»): the longest start that is a contact or an
        alias is the name, the rest is the message (Ivan, 2026-11-14: name and text said in one phrase)."""
        words = spoken.split()
        while words and (words[0] in NAME_NOISE or TELEGRAM_WORDS.fullmatch(words[0])):
            words = words[1:]
        if words[:2] == ["в", "телеграм"]:
            words = words[2:]
        for size in range(min(3, len(words)), 0, -1):
            name = " ".join(word for word in words[:size] if word not in NAME_NOISE and not TELEGRAM_WORDS.fullmatch(word))
            if not name:
                continue
            if self.aliases.get(" ".join(_stem(word) for word in name.split())) is not None:
                return name, " ".join(words[size:]), True
            if not self._contacts:
                self._refresh_contacts()
            found = match_contacts(name, self._contacts)
            ids = {person for person, _name in found}
            # every word must fit the same contact: «маше привет» is Маша and «привет», not «Маша Петрова»
            if found and all(ids & {person for person, _name in match_contacts(word, self._contacts)}
                             for word in name.split()):
                return name, " ".join(words[size:]), True
        return TELEGRAM_WORDS.sub(" ", " ".join(words)).strip(), "", False

    def send_to(self, spoken_name: str, with_text: bool = False) -> str:
        blocked = self._not_ready()
        if blocked:
            return blocked
        text = ""
        if with_text:
            spoken_name, text = self._name_and_text(spoken_name)
            text = re.sub(r"^(?:(?:в|через|по) )?телеграм\w*\s*|\s*(?:в|через|по) телеграм\w*$", "", text).strip()
        found = self._find(spoken_name)
        if isinstance(found, str):
            return found
        if isinstance(found, list):
            self.waiting = {"kind": "choose", "options": found, "until": self.clock() + 30, "text": text}
            names = "; ".join("{} {}".format(index, readable(item[1])) for index, item in enumerate(found, 1))
            return "Нашла несколько: {}. Скажите номер или фамилию.".format(names)
        if text:
            return self._confirm(found[0], found[1], text)
        return self._dictate(found[0], found[1])

    def _confirm(self, person: int, name: str, spoken_text: str) -> str:
        from .numbers import format_dictation
        text = format_dictation(spoken_text)
        self.waiting = {"kind": "confirm", "person": person, "name": name, "text": text, "until": self.clock() + WAIT_TEXT}
        return "Вы продиктовали: {} Отправить {}? Скажите: да, нет или исправить.".format(_sentence(text), readable(name))

    def _dictate(self, person: int, name: str) -> str:
        blocked = self._not_ready()
        if blocked:
            return blocked
        self.waiting = {"kind": "text", "person": person, "name": name, "until": self.clock() + WAIT_TEXT}
        user = self.user_name()
        return "Хорошо{}, что написать {}?".format(", " + user if user else "", readable(name))

    # The next phrase while Vega waits

    def expired(self) -> Optional[str]:
        if self.waiting is not None and self.clock() > self.waiting["until"]:
            kind, self.waiting = self.waiting["kind"], None
            if kind == "offer":
                return ""  # nobody answered «Прочитать?»: the message waits for «прочитай сообщения»
            if kind in ("text", "confirm", "choose"):
                return "Сообщение не отправлено."
            return "Подключение Телеграма отменено."
        return None

    def cancel(self) -> str:
        kind, self.waiting = (self.waiting or {}).get("kind"), None
        if kind == "offer":
            return "Хорошо."
        return "Отменила, сообщение не отправлено." if kind in ("text", "confirm", "choose") else "Подключение Телеграма отменено."

    def answer(self, phrase: str) -> str:
        """The person's phrase while Vega waits: «да» to «Прочитать?», the text, the phone number or the code."""
        waiting = self.waiting
        if waiting is None:
            return ""
        if phrase in CANCEL:
            return self.cancel()
        kind = waiting["kind"]
        if kind == "offer":
            self.waiting = None
            if phrase.split()[0] in YES or phrase in ("прочитай", "читай", "прочти"):
                said = " ".join(self._message_text(*item, hint=not waiting.get("talk")) for item in waiting["items"])
                if waiting.get("talk"):  # in a talk every phrase goes to Gemini (Ivan, 2026-11-14)
                    said += " Чтобы ответить, завершите разговор с Gemini: скажите «Вега, хватит», потом «Вега, ответь»."
                return said
            return "" if phrase.split()[0] not in NO else "Хорошо. Прочитать потом: скажите «Вега, прочитай сообщения»."
        if kind == "choose":
            from .numbers import parse_index
            options = waiting["options"]
            number = parse_index(phrase)
            chosen = options[number - 1] if number and 0 < number <= len(options) else None
            if chosen is None:
                again = match_contacts(phrase, options)
                chosen = again[0] if len(again) == 1 else None
            if chosen is None:
                waiting["until"] = self.clock() + 30
                return "Не поняла, кому. Скажите номер, например: первый."
            if waiting.get("text"):
                return self._confirm(chosen[0], chosen[1], waiting["text"])
            return self._dictate(chosen[0], chosen[1])
        if kind == "text":
            return self._confirm(waiting["person"], waiting["name"], phrase)
        if kind == "confirm":
            first = phrase.split()[0]
            if first in YES or phrase in ("отправь", "отправляй", "отправить"):
                self.waiting = None
                try:
                    self.backend.send(waiting["person"], waiting["text"])
                except Exception as error:
                    self.log("Телеграм: сообщение не ушло: {}".format(error))
                    return problem(error, "Сообщение не отправлено: нет связи с Телеграмом. Проверьте интернет.")
                return "Сообщение отправлено."
            if phrase in REPEAT_DICTATED:
                waiting["until"] = self.clock() + WAIT_TEXT
                return "Вы продиктовали: {} Отправить? Скажите: да, нет или исправить.".format(_sentence(waiting["text"]))
            if phrase in FIX or first in ("исправить", "исправь", "заново"):
                self.waiting = {"kind": "text", "person": waiting["person"], "name": waiting["name"],
                                "until": self.clock() + WAIT_TEXT}
                return "Диктуйте сообщение заново."
            if first in NO:
                return self.cancel()
            waiting["until"] = self.clock() + WAIT_TEXT
            return "Скажите: да, чтобы отправить, исправить, чтобы продиктовать заново, или нет."
        if kind == "phone":
            number = phone_number(phrase)
            if number is None:
                waiting["until"] = self.clock() + 90
                return "Не расслышала номер. Скажите его ещё раз, цифрами, с кодом страны."
            self.waiting = {"kind": "confirm_phone", "phone": number, "until": self.clock() + 90}
            return "Номер {}. Верно? Скажите: да или нет.".format(say_digits(number))
        if kind == "confirm_phone":
            if phrase.split()[0] in YES:
                return self.request_code(waiting["phone"])
            self.waiting = {"kind": "phone", "until": self.clock() + 90}
            return "Скажите номер ещё раз."
        if kind == "code":
            code = spoken_digits(phrase)
            if len(code) < 5:
                waiting["until"] = self.clock() + 180
                return "Код из пяти цифр. Скажите его ещё раз."
            return self.enter_code(code)
        return ""

    def request_code(self, phone: str) -> str:
        if self.clock() - self._code_asked < 120:
            self.waiting = {"kind": "code", "until": self.clock() + 300}
            return "Код уже отправлен, новый можно попросить через две минуты. Скажите код из сообщения по цифрам."
        self._code_asked = self.clock()
        try:
            if self.backend is None:
                self.backend = self.factory("")
            self.backend.send_code(phone)
        except Exception as error:
            self.waiting = None
            self.log("Телеграм: код не запрошен: {}".format(error))
            return problem(error, "Телеграм не прислал код. Проверьте номер и интернет и попробуйте снова.")
        self.waiting = {"kind": "code", "until": self.clock() + 300}
        return "Телеграм прислал код в сообщении. Оно в Телеграме на телефоне или на этом компьютере. Скажите код по цифрам."

    def enter_code(self, code: str) -> str:
        try:
            result = self.backend.sign_in(code)
        except Exception as error:
            self.waiting = None
            self.log("Телеграм: вход не удался: {}".format(error))
            return "Войти не получилось. Попробуйте ещё раз: Вега, подключи Телеграм."
        if result == "bad_code":
            self.waiting = {"kind": "code", "until": self.clock() + 300}
            return "Код не подошёл. Скажите его ещё раз."
        if result == "expired":
            self.waiting = None
            return "Код устарел. Скажите ещё раз: Вега, подключи Телеграм."
        if result == "password":
            self.waiting = None
            return ("На этом Телеграме стоит облачный пароль. Его нужно ввести в окне подключения: "
                    "попросите помощника открыть в меню Пуск «Подключить Телеграм».")
        return self.finish_login()

    def finish_login(self) -> str:
        self.waiting = None
        self._save_session()
        self._listen()
        return "Телеграм подключён. Я буду читать новые сообщения. Отправить: скажите «Вега, отправь сообщение» и имя."


WINDOW_OPENED = ("Открылось окно подключения Телеграма. Помощник, впишите номер телефона, "
                 "нажмите «Получить код» и впишите код из Телеграма.")


def mark_window_shown(folder: Path) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / WINDOW_SHOWN).write_text("1", encoding="utf-8")
    except OSError:
        pass


def offer_window_once(telegram: "Telegram", version: str, spawn: Optional[Callable[[], None]] = None,
                      delay: float = 20.0) -> bool:
    """Ivan, 2026-11-14: Vega is already installed for one person; after the 0.7.23 update the helper says
    «Вега, проверь обновления» and the Telegram login window must open by itself, once, only in this version.
    The wait lets the installer's own «Подключить Телеграм» window (a fresh install) mark itself first."""
    folder = telegram.folder
    if version not in ONE_TIME_VERSIONS or folder is None or not telegram.available:
        return False

    def go():
        if delay:
            time.sleep(delay)
        if telegram.saved_session() or (folder / WINDOW_SHOWN).exists():
            return
        mark_window_shown(folder)
        try:
            (spawn or _spawn_login_window)()
        except Exception as error:
            telegram.log("Окно подключения Телеграма не открылось: {}".format(error))
            return
        with telegram.lock:
            telegram.notes.append(WINDOW_OPENED)
    if delay:
        threading.Thread(target=go, name="vega-telegram-window", daemon=True).start()
    else:
        go()
    return True


def shortcut_window(folder: Path, spawn: Optional[Callable[[], None]] = None) -> bool:
    """The «Vega» shortcut: the login window when Telegram is set up in this build but not connected yet."""
    if api_keys() is None or (folder / SESSION_FILE).exists():
        return False
    mark_window_shown(folder)
    (spawn or _spawn_login_window)()
    return True


def _spawn_login_window() -> None:
    import subprocess
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--telegram-login"]
    else:
        command = [sys.executable, "-m", "voiceassist", "--telegram-login"]
    subprocess.Popen(command, close_fds=True)


def start(folder: Optional[Path], user_name: Callable[[], str], log: Callable[[str], None], version: str = "") -> Telegram:
    keys = api_keys()
    factory = None
    if keys is not None:
        def factory(session: str):
            return TelethonBackend(keys[0], keys[1], session, version)
    telegram = Telegram(folder, factory, user_name, log=log)
    if sys.platform == "win32":
        telegram.spawn_window = _spawn_login_window  # «Вега, подключи Телеграм» opens the window
    telegram.start()
    offer_window_once(telegram, version)
    return telegram
