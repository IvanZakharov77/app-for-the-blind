"""Small, offline command router with explicit outcome messages."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
import re
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import user_name
from .diagnostics import DEVELOPER_EMAIL_SPOKEN, CommandLog, desktop, write_report
from .files import CopyJournal, describe_directory
from .online import OnlineInfo, local_news_feed, top_news_feed
from .settings import Settings
from .file_browser import FileBrowser, FileOutcome
from .file_routes import DriveInfo, route_files
from .meaning import variants
from .understanding import canonical, closest, closest_name, endings_of
from .help_menu import CATEGORY_PHRASE, categories_message, category_message, find_category
from .numbers import format_dictation, parse_index, plural, replace_number_words, words_to_number
from .personal import PersonalStore, TimerBook, calculate
from .browser import BUILTIN_SITES, BrowserController, SitesStore
from .browser_routes import NoBrowser, route, route_followup
from .drives import UsbVolume, enumerate_usb_volumes
from .books import BOOK_EXTENSIONS, BookError, BookShelf
from . import daily as daily_module
from . import radio as radio_module
from .usb_copy import SYSTEM_FOLDERS, UsbCopyController, volume_name
from .optical import OpticalProbe, probe_optical
from .optical_burn import BurnController, find_folders
from .system import PROGRAMS, SystemController

SHUTDOWN_PHRASES = ("выключи компьютер", "выключи компьютер полностью", "заверши работу", "выключи комп",
                    "выключи ноутбук", "выключи ноут", "выключи пк", "выключение компьютера", "выключи компьютер совсем")
RESTART_PHRASES = ("перезагрузи компьютер", "перезагрузка", "перезагрузи комп", "перезагрузи ноутбук",
                   "перезагрузи ноут", "перезагрузка компьютера", "перезагрузи пк")


def _day_and_time(timestamp: float) -> str:
    # Windows strftime cannot take Cyrillic text in the format on Python 3.8.
    moment = datetime.fromtimestamp(timestamp)
    return moment.strftime("%d.%m") + " в " + moment.strftime("%H:%M")


def _daily_when(item: dict) -> str:
    return daily_module.describe(item["days"], [tuple(int(part) for part in clock.split(":")) for clock in item["times"]])


@dataclass(frozen=True)
class Result:
    status: str
    message: str
    options: Tuple[str, ...] = ()


def normalize(phrase: str) -> str:
    return re.sub(r"[^а-яa-z0-9]+", " ", phrase.lower().replace("ё", "е")).strip()


# «привет вега», misheard: «привет века», «здравствуй в его», «привет бега». Removed before the command,
# so «привет вега что ты умеешь» heard while Vega is already listening is still «что ты умеешь».
ASSISTANT_CALL = re.compile(r"^(?:(?:привет|приветик|здравствуй|здравствуйте|здрасте|алло|эй)\s+)?"
                            r"(?:вега|века|вегу|веге|веги|вегой|бега|вег|в его|в эго|помощник)\s+")
GREETING_ONLY = re.compile(r"^(?:привет|здравствуй|здравствуйте|здрасте)\s+(?=\S+\s+\S)")


def strip_assistant_name(command: str) -> str:
    stripped = ASSISTANT_CALL.sub("", command, count=1)
    if stripped == command:
        stripped = GREETING_ONLY.sub("", command, count=1)  # «привет [unclear name] что ты умеешь»: drop the greeting
    return stripped


# «что ты умеешь» the way people really ask it.
HELP_QUESTION = re.compile(r"(?:а |ну )?(?:что|чего|чо|што|что же) (?:ты |вы |же ты )?(?:умеешь|умеет|умеете|умеш|можешь|может|можете)"
                           r"(?: делать)?(?: вега)?|(?:помощь|помогите|справка|подскажи|подскажи команды|какие команды|команды)")


def duration_seconds(amount_text: Optional[str], unit: str) -> Optional[int]:
    """"пять" + "минут" → 300; no amount means one unit; "полчаса" is 30 minutes."""
    if unit == "полчаса":
        return 1800 if amount_text is None else None
    amount = 1.0 if amount_text is None else words_to_number(amount_text)
    if amount is None:
        return None
    scale = 3600 if unit.startswith("час") else 60 if unit.startswith("минут") else 1
    return int(round(amount * scale))


def spoken_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append("{} {}".format(hours, plural(hours, ("час", "часа", "часов"))))
    if minutes:
        parts.append("{} {}".format(minutes, plural(minutes, ("минута", "минуты", "минут"))))
    if rest or not parts:
        parts.append("{} {}".format(rest, plural(rest, ("секунда", "секунды", "секунд"))))
    return " ".join(parts)


def parse_clock_time(text: str) -> Optional[Tuple[int, int]]:
    """"семь тридцать", "7 утра", "девятнадцать ноль ноль", "восемь вечера" → (hour, minute)."""
    match = re.fullmatch(r"(\d+)(?: (?:час|часа|часов))?(?: (?:0 )?(\d+)(?: (?:минута|минуты|минут))?)?(?: (утра|дня|вечера|ночи))?",
                         replace_number_words(text))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    period = match.group(3)
    if period in ("дня", "вечера") and hour < 12:
        hour += 12
    if period == "ночи" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def speakable_site_name(name: str) -> bool:
    """Vosk's Russian model writes only Cyrillic words, so Latin names cannot be spoken."""
    return bool(re.fullmatch(r"[а-яе0-9 ]+", name)) and any("а" <= character <= "я" for character in name)


class _Done:
    """Lets an already finished Result pass through _ask_phrase unchanged."""

    def __init__(self, result):
        self.status, self.message = result.status, result.message


# word forms drift in recognition and in canonical() («на флешке»), so these take any of them
FLASH_TO_DISC = re.compile(r"(?:запиши|скопируй|перепиши|перекинь|сбрось)(?: все| всю)?(?: с)? флешк[уеиа] на (?:компакт )?диск")
DISC_TO_FLASH = re.compile(r"(?:скопируй|перепиши|перекинь|сбрось|запиши)(?: все)?(?: с)? (?:компакт )?диска? на флешк[уеиа]")

# «уменьши громкость на 20 процентов», «громче на 10», «поставь громкость на 50 процентов» (Ivan, 2026-11-01)
# «Как связаться с разработчиком» (Ivan, 2026-11-01: contacts instead of sending reports automatically).
CONTACT_PHRASES = ("как связаться с разработчиком", "связаться с разработчиком", "контакты разработчика", "почта разработчика",
                   "кто тебя сделал", "кто твой разработчик", "кто тебя создал", "как написать разработчику",
                   "куда отправить отчет", "куда отправлять отчет", "как отправить отчет")
# The same guide as text, read aloud like a book with a bookmark (Ivan, 2026-11-01).
MANUAL_READ = ("прочитай инструкцию", "читай инструкцию", "почитай инструкцию", "прочитай инструкцию веги",
               "прочитай мне инструкцию", "прочитай инструкцию вслух", "читай инструкцию веги", "прочти инструкцию")
MANUAL_TEXT = "Инструкция Веги.txt"
# The PDF guide next to VoiceAssist.exe, rebuilt with every release (Ivan, 2026-11-01).
MANUAL_PHRASES = ("открой инструкцию", "покажи инструкцию", "открой инструкцию веги", "инструкция", "инструкция веги",
                  "открой руководство", "где инструкция", "открыть инструкцию", "покажи инструкцию веги")
VOLUME_PERCENT = re.compile(r"(уменьши|убавь|понизь|снизь|сделай тише|тише|потише|увеличь|прибавь|повысь|подними|"
                            r"сделай громче|громче|погромче|поставь|установи|сделай)(?: громкость| звук)?(?: на| до)? (\d{1,3})(?: процент\w*)?")
RADIO_OFF = ("выключи радио", "останови радио", "стоп радио", "радио стоп", "хватит радио", "радио хватит",
             "выключи радиостанцию", "отключи радио", "убери радио", "радио выключи", "закрой радио")
RADIO_OFF_WHILE_ON = ("стоп", "хватит", "пауза", "стой", "выключи", "тишина",
                      "замолчи", "выключи это")
RADIO_OTHER = ("другое радио", "другая станция", "другую станцию", "следующая станция", "следующее радио",
               "переключи радио", "переключи станцию", "не нравится", "другое", "поменяй радио", "смени радио",
               "смени станцию", "поменяй станцию", "включи другое радио", "включи другую станцию")
RADIO_PREVIOUS = ("предыдущая станция", "предыдущее радио", "прошлая станция", "прошлое радио", "верни прошлое радио",
                  "верни предыдущую станцию", "предыдущую станцию", "включи предыдущую станцию", "назад радио")
RADIO_WHAT = ("что играет", "что за радио", "какое радио", "что за станция", "какая станция", "какое это радио",
              "что это за радио", "что сейчас играет")
RADIO_REMEMBER = ("запомни это радио", "запомни радио", "запомни станцию", "запомни эту станцию", "сохрани радио",
                  "сохрани станцию", "запомни это")
RADIO_FAVOURITE = ("включи мое радио", "мое радио", "любимое радио", "включи любимое радио", "включи мою станцию",
                   "моя станция", "мою станцию")
BOOK_RESUME = ("продолжи книгу", "продолжи чтение книги", "продолжай книгу", "читай дальше", "продолжи читать",
               "читай книгу", "дальше читай", "читай книгу дальше", "продолжи читать книгу", "читай")
BOOK_LIST = ("какие книги я читаю", "мои книги", "какие книги читаю", "какие у меня книги", "что я читаю", "список книг")
BOOK_FROM_START = ("читай с начала", "читай сначала", "читай книгу сначала", "читай книгу с начала", "начни книгу сначала",
                   "начни сначала")
BOOK_WHERE = ("где я в книге", "сколько прочитано", "сколько осталось в книге", "какая глава")
BOOK_NEXT_CHAPTER = ("следующая глава", "дальше глава", "следующую главу", "читай следующую главу")
BOOK_PREVIOUS_CHAPTER = ("предыдущая глава", "прошлая глава", "предыдущую главу", "назад глава", "читай главу заново",
                         "повтори главу")
BOOK_BACK = ("назад в книге", "назад на абзац", "повтори абзац", "вернись назад в книге", "прочитай еще раз абзац")
BOOK_SUMMARY = ("о чем документ", "о чем книга", "кратко", "расскажи кратко", "кратко о документе", "краткое содержание",
                "о чем этот документ", "перескажи документ", "суть документа", "что в документе", "перескажи кратко",
                "о чем там", "что это за документ", "перескажи", "кратко документ", "в двух словах")
BOOK_SUMMARY_OF = re.compile(r"(?:о чем|кратко|перескажи|что в)(?: кратко)? (?:документ[еау]?|книг[аеиу]|файл[еау]?) (.+)")
BOOK_ASK = re.compile(r"(?:спроси|узнай|скажи)(?: у)? (?:про|о|по|в|из) (?:документ\w*|книг\w*|файл\w*|сч[её]т\w*) (.+)")
BOOK_BY_NAME = re.compile(r"(?:прочитай|читай|почитай|прочти|прочитать)(?: мне)? (?:книгу|документ|книжку|рассказ|текст) (.+)")
BOOK_BY_NUMBER = re.compile(r"(?:прочитай|читай|почитай|прочти)(?: мне)?(?: файл| книгу| документ)? (.+)")


class Assistant:
    def __init__(self, clock: Callable[[], datetime] = datetime.now, current_directory: Optional[Path] = None, personal: Optional[PersonalStore] = None, timers: Optional[TimerBook] = None, browser=None, sites: Optional[SitesStore] = None, drive_provider: Optional[Callable[[], Tuple[UsbVolume, ...]]] = None, usb_copy: Optional[UsbCopyController] = None, optical_probe: Optional[Callable[[], OpticalProbe]] = None, burner=None, system=None, web=None, settings=None, online=None, journal=None, report=None):
        self.clock = clock
        self.current_directory = current_directory or Path.home()
        self.personal = personal or PersonalStore(Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist" / "personal.json")
        self.timers = timers or TimerBook()
        self.browser = browser if browser is not None else (BrowserController() if sys.platform == "win32" else None)
        self.sites = sites or SitesStore(Path(os.environ.get("APPDATA", str(Path.home()))) / "VoiceAssist" / "sites.json")
        self.drive_provider = drive_provider if drive_provider is not None else (enumerate_usb_volumes if sys.platform == "win32" else None)
        # One unfinished copy (folders or flash to flash) survives a restart or a pulled drive.
        self.journal = journal if journal is not None else CopyJournal(
            Path(os.environ["APPDATA"]) / "VoiceAssist" / "copy-journal.json" if sys.platform == "win32" and os.environ.get("APPDATA") else None)
        self.usb_copy = usb_copy if usb_copy is not None else (UsbCopyController(self.drive_provider, journal=self.journal) if self.drive_provider is not None else None)
        self.optical_probe = optical_probe if optical_probe is not None else (probe_optical if sys.platform == "win32" else None)
        self.burner = burner if burner is not None else (BurnController(self.optical_probe) if self.optical_probe is not None else None)
        self._system = system
        # Page, YouTube and video commands over the Chrome extension; NoBrowser answers honestly without it.
        self.web = web if web is not None else NoBrowser()
        if hasattr(self.browser, "open_site") and hasattr(self.web, "plain_opener"):
            self.web.plain_opener = self.browser.open_site
        if sys.platform == "win32" and getattr(self.web, "chrome", 0) is None:
            from .chrome_windows import LazyChrome
            self.web.chrome = LazyChrome(lambda: self.system)
        self.last_topic: Optional[str] = None
        self.list_owner: Optional[str] = None  # "web", "files", "news" or "windows": who numbered the last list
        self.settings = settings if settings is not None else Settings(
            Path(os.environ["APPDATA"]) / "VoiceAssist" / "settings.json" if sys.platform == "win32" and os.environ.get("APPDATA") else None)
        self.online = online or OnlineInfo()
        self.city_checked = False
        # Reminders that fell due before this start were missed while the assistant was off.
        self.started_at = self.clock().timestamp()
        self._ip_country: Optional[str] = None
        self.config_dir = Path(os.environ["APPDATA"]) / "VoiceAssist" if sys.platform == "win32" and os.environ.get("APPDATA") else None
        self.command_log = CommandLog(self.config_dir / "commands.log" if self.config_dir else None, clock)
        self.books = BookShelf(self.config_dir / "books" if self.config_dir else None)
        self.radio = None  # radio.Radio on Windows (Ivan, 2026-11-01)
        self.document_ai = None  # Gemini's summarize(title, text, question) in the «with Gemini» edition
        self.report = report or (lambda: write_report(self.config_dir, desktop()) if self.config_dir else None)
        self.files = FileBrowser(home=Path.home(), drive_provider=self.drive_provider, journal=self.journal)
        self.unfinished_announced = False
        self.files.current = self.current_directory
        self.drives = DriveInfo(self.drive_provider)
        self.pending_confirmation: Optional[Tuple[str, float]] = None
        self.pending_action: Optional[Callable[[], Result]] = None
        self.pending_phrase: Optional[str] = None
        self.last_message: Optional[str] = None
        self.last_command = ""  # the last command that worked, for «ещё раз» and «наоборот»
        self.help_index = 0
        self.categories_offered = False
        self.help_items = (
            # «Повтори», «Замолчи», «Отмена» are named after every help page, so they take no slot here.
            "Который час?", "Какое сегодня число?", "Все категории", "Что в папке?",
            "Поставь таймер на пять минут", "Запиши заметку …", "Прочитай заметки",
            "Сколько будет двенадцать плюс семь?", "Напомни через десять минут …", "Какие напоминания?",
            "Поставь будильник на семь тридцать", "Сколько осталось на таймере?", "Удали последнюю заметку",
            "Какая погода?", "Какие новости?", "Местные новости", "Открой документы", "Найди фотографии",
            "Сколько свободного места?", "Говори медленнее", "Голос громче",
            "Напиши …", "Прочитай поле", "Следующий пункт", "Следующий элемент", "Открой меню", "Продолжи копирование",
            "Сохрани отчёт для помощи",
        )

    def _finish(self, status: str, message: str, options: Tuple[str, ...] = ()) -> Result:
        if message:
            self.last_message = message
        return Result(status, message, options)

    CONFIRMATIONS = {
        "delete_last_note": ("подтверждаю удаление", "Удалить последнюю заметку «{}»? Скажите: подтверждаю удаление."),
        "clear_notes": ("подтверждаю удаление", "Удалить все заметки, их {}? Скажите: подтверждаю удаление."),
        "press": ("подтверждаю нажатие", "Кнопка «{}» может удалить данные. Чтобы нажать, скажите: подтверждаю нажатие."),
    }
    RISKY_BUTTON = re.compile(r"удал|формат|стер|очист|delete|format|erase")

    @property
    def system(self):
        """Created on first use so the text mode and tests never load Windows libraries."""
        if self._system is None and sys.platform == "win32":
            from .system import WindowsSystemAPI
            try:
                self._system = SystemController(WindowsSystemAPI())
            except OSError:
                return None
        return self._system

    def _web(self, outcome) -> Result:
        self.last_topic = "web"
        if self.web.last_list:
            self.list_owner = "web"
        return self._finish(outcome.status, outcome.message)

    def _file(self, outcome) -> Result:
        self.last_topic = "files"
        if outcome.status == "ok" and self.files.items:
            self.list_owner = "files"
        if outcome.status == "needs_confirmation" and outcome.action is not None:
            return self._ask_phrase(outcome.confirm_phrase, outcome.message, outcome.action)
        return self._finish(outcome.status, outcome.message)

    def _read_back(self, question: str, save: Callable[[], Result]) -> Result:
        """Free text heard by Vosk is repeated before saving: «да» saves, «нет» drops it (ТЗ, раздел 3)."""
        self.pending_confirmation = ("custom", self.clock().timestamp() + 60)
        self.pending_action = save
        self.pending_phrase = ("да", "верно", "да верно", "сохрани", "да сохрани")
        return self._finish("needs_confirmation", question + " Скажите: да или нет.")

    def _ask_phrase(self, phrase: str, message: str, action) -> Result:
        """Confirmation for a planned file action: «подтверждаю удаление» runs exactly that plan."""
        def run() -> Result:
            done = action()
            return self._finish(done.status, done.message)
        self.pending_confirmation = ("custom", self.clock().timestamp() + 60)
        self.pending_action = run
        self.pending_phrase = phrase
        return self._finish("needs_confirmation", message)

    def _ask_confirmation(self, kind: str, *details, action: Optional[Callable[[], Result]] = None) -> Result:
        self.pending_confirmation = (kind, self.clock().timestamp() + 60)
        self.pending_action = action
        return self._finish("needs_confirmation", self.CONFIRMATIONS[kind][1].format(*details))

    def _confirm(self, command: str) -> Optional[Result]:
        """Run the pending dangerous action when its own phrase is said within a minute."""
        if self.pending_confirmation is None:
            return None
        kind, deadline = self.pending_confirmation
        expected = self.pending_phrase if kind == "custom" else self.CONFIRMATIONS[kind][0]
        accepted = expected if isinstance(expected, tuple) else (expected,)
        if kind == "custom" and "да" in accepted and command in ("нет", "не надо", "неправильно"):
            self.pending_confirmation = self.pending_action = self.pending_phrase = None
            saving = "сохрани" in accepted
            return self._finish("ok", "Не сохраняю. Повторите команду, если нужно." if saving else "Хорошо, не трогаю.")
        if command not in accepted:
            return None
        self.pending_confirmation = None
        if self.clock().timestamp() > deadline:
            return self._finish("error", "Подтверждение пришло позже минуты. Повторите команду заново.")
        action, self.pending_action = self.pending_action, None
        if action is not None:
            return action()
        try:
            if kind == "delete_last_note":
                removed = self.personal.delete_last_note()
                return self._finish("ok", "Удалена заметка: {}.".format(removed) if removed else "Заметок нет.")
            count = self.personal.clear_notes()
            return self._finish("ok", "Удалено заметок: {}.".format(count))
        except (OSError, ValueError) as error:
            return self._finish("error", "Не удалось удалить: {}.".format(error))

    def _power(self, kind: str) -> Result:
        if self.system is None:
            return self._finish("unavailable", "Выключение доступно только на Windows.")
        outcome = self.system.schedule_power(kind)
        return self._finish(outcome.status, outcome.message)

    def _system_command(self, command: str) -> Optional[Result]:
        volume = {"громче": "up", "сделай громче": "up", "прибавь громкость": "up", "прибавь звук": "up",
                  "тише": "down", "сделай тише": "down", "убавь громкость": "down", "убавь звук": "down",
                  "увеличь громкость": "up", "звук громче": "up", "громкость больше": "up", "погромче": "up",
                  "уменьши громкость": "down", "звук тише": "down", "громкость меньше": "down", "потише": "down",
                  "выключи звук": "mute", "включи звук": "mute"}
        simple = {"какой заряд батареи": "battery", "заряд батареи": "battery", "сколько заряда": "battery",
                  "есть ли интернет": "network", "есть ли сеть": "network", "проверь интернет": "network",
                  "подключен ли интернет": "network", "работает ли интернет": "network", "что открыто": "windows",
                  "какие окна открыты": "windows", "какие окна": "windows", "список окон": "windows",
                  "какое окно активно": "active", "где я": "active", "какое сейчас окно": "active",
                  "закрой окно": "close", "отмени выключение": "abort"}
        switch = re.fullmatch(r"(?:переключись на|перейди в|перейди на|покажи) окно (.+)", command)
        if command in MANUAL_PHRASES:
            if self.system is None:
                return self._finish("unavailable", "Инструкция открывается только на Windows.")
            outcome = self.system.open_manual()
            return self._finish(outcome.status, outcome.message)
        percent = VOLUME_PERCENT.fullmatch(replace_number_words(command))
        if percent:
            if self.system is None:
                return self._finish("unavailable", "Эта команда доступна только на Windows.")
            verb = percent.group(1)
            kind = "set" if verb in ("поставь", "установи", "сделай") else "down" if re.match(r"(?:умень|убав|пониз|сниз|тише|сделай тише|потише)", verb) else "up"
            outcome = self.system.volume_percent(kind, int(percent.group(2)))
            return self._finish(outcome.status, outcome.message)
        if command not in volume and command not in simple and not switch:
            return None
        system = self.system
        if system is None:
            return self._finish("unavailable", "Эта команда доступна только на Windows.")
        try:
            if command in volume:
                outcome = system.volume(volume[command])
            elif switch:
                outcome = system.switch_to(switch.group(1))
            else:
                outcome = {"battery": system.battery, "network": system.network, "windows": system.list_windows,
                           "active": system.active_window, "close": system.close_active,
                           "abort": system.abort_power}[simple[command]]()
                if simple[command] == "windows" and outcome.status == "ok":
                    self.list_owner = "windows"  # «номер два», «переключись на второе» now mean a window
        except (OSError, ValueError) as error:
            return self._finish("error", "Windows не ответила: {}.".format(error))
        return self._finish(outcome.status, outcome.message)

    WINDOW_LISTS = {
        "какие здесь кнопки": "button", "какие кнопки в окне": "button", "прочитай кнопки в окне": "button", "какие кнопки": "button",
        "какие здесь поля": "field", "какие поля в окне": "field",
        "какие здесь флажки": "checkbox", "какие флажки": "checkbox",
        "что можно нажать": None, "какие элементы в окне": None, "что есть в окне": None, "какие здесь элементы": None,
    }
    WINDOW_ARRANGE = {
        "сверни окно": "minimize", "разверни окно": "maximize", "разверни на весь экран": "maximize",
        "восстанови окно": "restore", "сверни все окна": "desktop", "покажи рабочий стол": "desktop",
    }

    def _chrome_active(self) -> bool:
        if isinstance(self.web, NoBrowser) or self.system is None:
            return False
        try:
            window = self.system.api.foreground()
        except OSError:
            return False
        return bool(window and window[1] and window[1].endswith("Google Chrome"))

    def _window_command(self, command: str) -> Optional[Result]:
        """Texts and buttons of the active program; on a Chrome page these phrases go to the page instead."""
        reading = command in ("прочитай окно", "прочитай сообщение", "что в окне", "что написано в окне", "что написано", "прочитай диалог")
        role_known = command in self.WINDOW_LISTS
        arrange = self.WINDOW_ARRANGE.get(command)
        press = re.fullmatch(r"нажми (?:на )?(?:кнопку )?(.+)", command)
        if not (reading or role_known or arrange or press):
            return None
        if (role_known or press) and self._chrome_active():
            if role_known and self.WINDOW_LISTS[command] in ("button", "field"):
                kind = {"button": "buttons", "field": "fields"}[self.WINDOW_LISTS[command]]
                return self._web(self.web.page_list(kind, 0))
            return None
        system = self.system
        if system is None:
            return None if press else self._finish("unavailable", "Чтение и нажатие элементов окон доступно только на Windows.")
        try:
            if reading:
                outcome = system.read_window()
            elif role_known:
                outcome = system.list_controls(self.WINDOW_LISTS[command])
            elif arrange:
                outcome = system.arrange(arrange)
            else:
                element = system.find_control(press.group(1))
                if element is None:
                    return self._finish("error", "В активном окне нет элемента «{}». Скажите: что можно нажать.".format(press.group(1)))
                if self.RISKY_BUTTON.search(element.name.lower()):
                    def run(element=element):
                        done = system.press(element)
                        return self._finish(done.status, done.message)
                    return self._ask_confirmation("press", element.name, action=run)
                outcome = system.press(element)
        except (OSError, ValueError) as error:
            return self._finish("error", "Windows не ответила: {}.".format(error))
        return self._finish(outcome.status, outcome.message)

    KEYBOARD = {
        "следующий пункт": ("down", ()), "вниз": ("down", ()), "ниже": ("down", ()),
        "предыдущий пункт": ("up", ()), "вверх": ("up", ()), "выше": ("up", ()),
        "следующий элемент": ("tab", ()), "следующее поле": ("tab", ()),
        "предыдущий элемент": ("tab", ("shift",)), "предыдущее поле": ("tab", ("shift",)),
        "выбери": ("enter", ()), "нажми ввод": ("enter", ()), "нажми энтер": ("enter", ()), "отправь": ("enter", ()),
        "нажми escape": ("escape", ()), "нажми эскейп": ("escape", ()), "закрой меню": ("escape", ()),
        "открой меню": ("f10", ()), "контекстное меню": ("applications", ()),
        "нажми пробел": ("space", ()), "отметь": ("space", ()),
        "сотри слово": ("backspace", ("control",)), "сотри букву": ("backspace", ()),
        "в начало списка": ("home", ()), "в конец списка": ("end", ()),
    }
    FOCUS = ("прочитай поле", "где фокус", "что выбрано", "что под фокусом", "что в поле")

    def _keyboard_command(self, command: str) -> Optional[Result]:
        """Lists, menus, dialogs and dictation in any program: the keys a sighted user would press."""
        dictation = re.fullmatch(r"(?:напиши|напечатай|введи|набери) (?:текст )?(.+)", command)
        menu = re.fullmatch(r"открой меню (.+)", command)
        clear = command in ("очисти поле", "сотри все в поле")
        if not (dictation or menu or clear or command in self.KEYBOARD or command in self.FOCUS):
            return None
        system = self.system
        if system is None:
            return self._finish("unavailable", "Клавиши и диктовка работают только на Windows.")
        try:
            if dictation:
                outcome = system.type_text(format_dictation(dictation.group(1)))
            elif menu:
                outcome = system.open_menu(menu.group(1))
            elif clear:
                def run():
                    system.key("a", ("control",), announce=False)
                    done = system.key("delete", (), announce=False)
                    return self._finish(done.status, "Поле очищено." if done.status == "ok" else done.message)
                return self._ask_phrase(("да", "стирай"), "Стереть весь текст в поле? Скажите: да.", run)
            elif command in self.FOCUS:
                outcome = system.focus_report()
            else:
                key, modifiers = self.KEYBOARD[command]
                outcome = system.key(key, modifiers, announce=key not in ("enter", "backspace"))
        except (OSError, ValueError) as error:
            return self._finish("error", "Windows не ответила: {}.".format(error))
        return self._finish(outcome.status, outcome.message)

    SPEECH = {
        "говори медленнее": ("speech_rate", -1), "помедленнее": ("speech_rate", -1), "говори помедленнее": ("speech_rate", -1),
        "говори быстрее": ("speech_rate", 1), "побыстрее": ("speech_rate", 1), "говори побыстрее": ("speech_rate", 1),
        "говори обычно": ("speech_rate", None), "обычная скорость": ("speech_rate", None),
        "голос громче": ("speech_volume", 20), "сделай голос громче": ("speech_volume", 20), "говори громче": ("speech_volume", 20),
        "голос тише": ("speech_volume", -20), "сделай голос тише": ("speech_volume", -20), "говори тише": ("speech_volume", -20),
    }

    def _speech_command(self, command: str) -> Optional[Result]:
        entry = self.SPEECH.get(command)
        if entry is None:
            return None
        key, change = entry
        current = self.settings.get(key)
        if key == "speech_rate":
            value = 0 if change is None else max(-5, min(5, current + change))
            if value == current and change is not None:
                return self._finish("ok", "Это уже {} скорость.".format("самая высокая" if change > 0 else "самая низкая"))
            message = "Скорость речи обычная." if value == 0 else "Скорость речи: на {} {} {} обычной.".format(
                abs(value), plural(abs(value), ("шаг", "шага", "шагов")), "быстрее" if value > 0 else "медленнее")
        else:
            value = max(20, min(100, current + change))
            if value == current:
                return self._finish("ok", "Это уже {} громкость голоса.".format("самая высокая" if change > 0 else "самая низкая"))
            message = "Громкость голоса {} процентов. Громкость компьютера не менялась.".format(value)
        try:
            self.settings.set(key, value)
        except (OSError, ValueError) as error:
            return self._finish("error", "Настройку сохранить не удалось: {}.".format(error))
        return self._finish("ok", message)

    def _info_command(self, command: str) -> Optional[Result]:
        if command in ("какая погода", "какая сейчас погода", "погода", "что с погодой", "какая погода сегодня"):
            outcome = self.online.weather(self._home())
        elif command in ("какая погода завтра", "погода на завтра", "что с погодой завтра"):
            outcome = self.online.weather(self._home(), tomorrow=True)
        elif re.fullmatch(r"(?:какая )?погода (?:в|во) (.+?)( завтра)?", command):
            match = re.fullmatch(r"(?:какая )?погода (?:в|во) (.+?)( завтра)?", command)
            outcome = self.online.weather(None, match.group(1), tomorrow=bool(match.group(2)))
        elif re.fullmatch(r"(?:мой город|запомни город|я живу в) (.+)", command):
            spoken = re.fullmatch(r"(?:мой город|запомни город|я живу в) (.+)", command).group(1)
            try:
                place = self.online.find_city(spoken)
            except Exception:
                return self._finish("unavailable", "Нет связи с Open-Meteo, город не проверен и не сохранён.")
            if place is None:
                return self._finish("error", "Город «{}» не найден. Попробуйте сказать иначе.".format(spoken))
            try:
                self.settings.set("weather", place)
            except (OSError, ValueError) as error:
                return self._finish("error", "Не удалось сохранить город: {}.".format(error))
            return self._finish("ok", "Город для погоды: {}.".format(place["name"]))
        elif command in ("какие новости", "расскажи новости", "новости", "прочитай новости", "что нового", "главные новости"):
            outcome = self.online.news(self.settings.get("news") or top_news_feed(self._country()))
        elif command in ("местные новости", "новости моего города", "новости города", "новости региона", "новости моего региона",
                         "что нового в городе", "что нового у нас", "региональные новости"):
            place = self._home()
            if place is None:
                return self._finish("unavailable", "Не удалось определить ваш город по интернету. Скажите: мой город, и название города.")
            outcome = self.online.news(local_news_feed(place["name"], place.get("country")))
        elif re.fullmatch(r"новости (?:в |во |города |из )?(.+)", command) and not command.startswith("новости номер"):
            outcome = self.online.news(local_news_feed(re.fullmatch(r"новости (?:в |во |города |из )?(.+)", command).group(1), self._country()))
        elif command in ("где я нахожусь", "определи мой город", "в каком я городе", "какой мой город"):
            place = self._home()
            if place is None:
                return self._finish("unavailable", "Не удалось определить ваш город по интернету. Скажите: мой город, и название города.")
            how = "По интернет-подключению вы в городе {}." if place.get("auto") else "Сохранён город {}."
            return self._finish("ok", (how + " Чтобы сменить, скажите: мой город, и название.").format(place["name"]))
        elif re.fullmatch(r"(?:прочитай|открой) новость (?:номер )?(.+)", command):
            number = parse_index(re.fullmatch(r"(?:прочитай|открой) новость (?:номер )?(.+)", command).group(1))
            if number is None:
                return self._finish("error", "Назовите номер новости.")
            outcome = self.online.headline(number)
        else:
            return None
        if outcome.status == "ok" and "новост" in command and not re.match(r"(?:прочитай|открой) новость", command):
            self.list_owner = "news"  # «номер два», «прочитай вторую» now mean a headline
        return self._finish(outcome.status, outcome.message)

    def _home(self) -> Optional[dict]:
        """The city the person named, or else the one found by the internet address: no question asked.
        The found city is saved as automatic and looked up again once per run, so a moved laptop follows."""
        saved = self.settings.get("weather")
        if saved is not None and not saved.get("auto"):
            return saved
        if not self.city_checked:
            self.city_checked = True
            try:
                place = self.online.detect_city()
            except Exception:
                place = None
            if place is not None:
                saved = dict(place, auto=True)
                try:
                    self.settings.set("weather", saved)
                except (OSError, ValueError):
                    pass
        return saved

    def _country(self) -> Optional[str]:
        """The person's country, for a bare «включи радио». A city saved before 0.7.13 has no country:
        then the internet address tells it (Ivan, 2026-11-01: Kharkiv got foreign radio)."""
        place = self._home()
        if place and place.get("country"):
            return place["country"]
        if self._ip_country is None:
            self._ip_country = ""
            try:
                found = self.online.detect_city() if self.online is not None else None
                self._ip_country = (found or {}).get("country", "") or ""
            except Exception:
                pass
        return self._ip_country or None

    def _drive_command(self, command: str) -> Optional[Result]:
        if command in ("сколько свободного места", "сколько места свободно", "сколько места на компьютере", "сколько места на дисках"):
            return self._file(self.drives.free_space())
        match = re.fullmatch(r"сколько (?:свободного )?места на (первой|второй|третьей)?(?: ?флешке| ?флеш накопителе)?", command)
        if match and command != "сколько места на":
            return self._file(self.drives.flash_space((match.group(1) or "").replace("ой", "ую").replace("ьей", "ью")))
        match = re.fullmatch(r"что на (первой|второй|третьей)(?: флешке)?|что на флешке", command)
        if match:
            return self._file(self.files.open_flash(((match.group(1) or "") + " флешку").strip().replace("ой ", "ую ").replace("ьей ", "ью ")))
        match = re.fullmatch(r"(?:безопасно )?извлеки (первую|вторую|третью)?(?: ?флешку)?", command)
        if match and command not in ("извлеки", "безопасно извлеки"):
            return self._file(self.drives.eject(match.group(1) or ""))
        if command in ("что на диске", "что на компакт диске", "что на диске в приводе", "прочитай диск"):
            root = self.drives.optical_root()
            return self._file(self.files.go(Path(root.message)) if root.status == "ok" else root)
        if command in ("сколько места на диске", "сколько места на компакт диске", "сколько места на диске в приводе"):
            return self._file(self.drives.optical_space(self.optical_probe))
        return None

    def _daily_command(self, command: str) -> Optional[Result]:
        """Repeating and clock-time reminders, «Вега, готово» (Ivan, 2026-11-01)."""
        if command in daily_module.DONE_WORDS:
            try:
                nags = self.personal.nags()
            except (OSError, ValueError):
                return None
            if not nags:
                return None
            self.personal.save_daily(self.personal.daily(), [])
            return self._finish("ok", "Отлично, {}, отметила.".format(self.user_name()) if self.user_name() else "Отлично, отметила.")
        parsed = daily_module.parse(command)
        if parsed is not None:
            days, times, what = parsed
            when = daily_module.describe(days, times)

            def save() -> Result:
                try:
                    items = self.personal.daily()
                    due = daily_module.next_due(days, times, self.clock())
                    items.append({"text": what, "days": list(days), "times": ["{:02d}:{:02d}".format(*clock) for clock in times],
                                  "next": due.timestamp()})
                    self.personal.save_daily(items)
                except (OSError, ValueError) as error:
                    return self._finish("error", "Не удалось сохранить напоминание: {}.".format(error))
                return self._finish("ok", "Буду напоминать {}: {}.".format(when, what))
            return self._read_back("Напоминать {}: {}?".format(when, what), save)
        once = daily_module.parse_once(command, self.clock())
        if once is not None:
            due, what = once
            day = "сегодня" if due.date() == self.clock().date() else "завтра" if (due.date() - self.clock().date()).days == 1 else due.strftime("%d.%m")

            def save_once() -> Result:
                try:
                    self.personal.add_reminder(due.timestamp(), what)
                except (OSError, ValueError) as error:
                    return self._finish("error", "Не удалось сохранить напоминание: {}.".format(error))
                return self._finish("ok", "Напомню {} в {}: {}.".format(day, due.strftime("%H:%M"), what))
            return self._read_back("Напомнить {} в {}: {}?".format(day, due.strftime("%H:%M"), what), save_once)
        match = re.fullmatch(r"(?:удали|отмени|убери|выключи) (?:ежедневное |каждодневное )?напоминани[ея] (?:про |о |об |на )?(.+)", command)
        if match and parse_index(match.group(1)) is None:
            wanted = match.group(1)
            try:
                items = self.personal.daily()
            except (OSError, ValueError):
                return None
            found = [item for item in items if wanted in item["text"] or item["text"] in wanted]
            if not found:
                return None  # maybe a one-time reminder: the older handler looks
            chosen = found[0]

            def remove() -> Result:
                self.personal.save_daily([item for item in self.personal.daily() if item != chosen])
                return self._finish("ok", "Больше не напоминаю: {}.".format(chosen["text"]))
            return self._read_back("Удалить напоминание {}: {}?".format(_daily_when(chosen), chosen["text"]), remove)
        return None

    def _daily_alerts(self, now: float) -> List[str]:
        alerts: List[str] = []
        items, nags = self.personal.daily(), self.personal.nags()
        changed = False
        for item in items:
            if item["next"] > now:
                continue
            changed = True
            if item["next"] < self.started_at - 60:
                if now - item["next"] < 24 * 3600:
                    alerts.append("Пропущено, пока Вега была выключена: {}. Было в {}.".format(
                        item["text"], datetime.fromtimestamp(item["next"]).strftime("%H:%M")))
            else:
                alerts.append("Пора: {}. Когда сделаете, скажите: Вега, готово.".format(item["text"]))
                nags = [nag for nag in nags if nag["text"] != item["text"]]
                nags.append({"text": item["text"], "due": now + daily_module.NAG_SECONDS, "left": daily_module.NAG_TIMES})
            times = [tuple(int(part) for part in clock.split(":")) for clock in item["times"]]
            item["next"] = daily_module.next_due(item["days"], times, datetime.fromtimestamp(max(now, item["next"]))).timestamp()
        kept = []
        for nag in nags:
            if nag["due"] <= now:
                changed = True
                alerts.append("Напоминаю ещё раз: {}. Скажите: Вега, готово.".format(nag["text"]))
                nag["left"] -= 1
                nag["due"] = now + daily_module.NAG_SECONDS
                if nag["left"] <= 0:
                    continue
            kept.append(nag)
        if changed:
            self.personal.save_daily(items, kept)
        return alerts

    def _radio_command(self, command: str) -> Optional[Result]:
        """Radio by genre and country, no numbers and no lists (Ivan, 2026-11-01)."""
        playing = self.radio is not None and self.radio.on
        if command in RADIO_OFF or (playing and command in RADIO_OFF_WHILE_ON):
            if self.radio is None or not self.radio.on:
                return self._finish("ok", "Радио и так не играет.")
            return self._finish("ok", self.radio.stop())
        if command in RADIO_OTHER or command in RADIO_PREVIOUS:
            if self.radio is None:
                return self._finish("unavailable", "Радио работает только на Windows.")
            done, message = self.radio.other() if command in RADIO_OTHER else self.radio.previous()
            if done:
                self.radio.hush()  # plays again once Vega has said it
            return self._finish("ok" if done else "error", message)
        if command in RADIO_WHAT:
            return self._finish("ok", self.radio.what() if self.radio else "Радио сейчас не играет.")
        if command in RADIO_REMEMBER:
            return self._finish("ok", self.radio.remember() if self.radio else "Радио работает только на Windows.")
        if command in RADIO_FAVOURITE:
            if self.radio is None:
                return self._finish("unavailable", "Радио работает только на Windows.")
            done, message = self.radio.favourite()
            if done:
                self.radio.hush()
            return self._finish("ok" if done else "error", message)
        request = radio_module.parse(command)
        if request is None:
            return None
        if self.radio is None:
            return self._finish("unavailable", "Радио работает только на Windows.")
        done, message = self.radio.start(request, (self._country() or "").upper())
        if done:
            self.radio.hush()
        return self._finish("ok" if done else "error", message)

    def _book_command(self, command: str) -> Optional[Result]:
        """Books and documents read aloud with a bookmark (Ivan, 2026-11-01)."""
        if command in MANUAL_READ:
            manual = Path(sys.executable).parent / MANUAL_TEXT
            if not manual.is_file():
                return self._finish("unavailable", "Инструкции для чтения нет в папке Веги. Она появится после обновления.")
            return self._read_book(manual)
        if command in BOOK_RESUME:
            path = self.books.current.path if self.books.current is not None else self.books.last_path()
            if path is None:
                return self._finish("unavailable", "Вы ещё не читали книг. Скажите: читай книгу и её название.")
            return self._read_book(path)
        if command in BOOK_LIST:
            return self._book_list()
        if command in BOOK_FROM_START:
            if self.books.current is None and self.books.last_path() is None:
                return self._finish("unavailable", "Сейчас нет открытой книги.")
            return self._read_book(self.books.current.path if self.books.current else self.books.last_path(), 0)
        if command in BOOK_WHERE:
            book = self.books.current
            if book is None:
                return self._finish("unavailable", "Сейчас нет открытой книги.")
            chapter = "Глава {} из {}. ".format(book.chapter_at(self.books.position) + 1, len(book.chapters)) if len(book.chapters) > 1 else ""
            return self._finish("ok", "«{}». {}Прочитано {} процентов.".format(book.title, chapter, self.books.percent()))
        if command in BOOK_NEXT_CHAPTER or command in BOOK_PREVIOUS_CHAPTER or command in BOOK_BACK:
            book = self.books.current
            if book is None:
                return self._finish("unavailable", "Сейчас нет открытой книги. Скажите: продолжи книгу.")
            if command in BOOK_BACK:
                self.books.back()
                return self._read_book(book.path, self.books.position, intro="Назад.")
            index = book.chapter_at(self.books.position)
            if command in BOOK_NEXT_CHAPTER:
                if index + 1 >= len(book.chapters):
                    return self._finish("ok", "Это последняя глава. Скажите: продолжи книгу.")
                return self._read_book(book.path, book.chapters[index + 1], intro="Глава {}.".format(index + 2))
            target = index - 1 if self.books.position - book.chapters[index] < 300 and index > 0 else index
            return self._read_book(book.path, book.chapters[target], intro="Глава {}.".format(target + 1))
        match = BOOK_ASK.fullmatch(command)
        if match:
            return self._summary(match.group(1))
        if command in BOOK_SUMMARY or BOOK_SUMMARY_OF.fullmatch(command):
            named = BOOK_SUMMARY_OF.fullmatch(command)
            return self._summary("", named.group(1) if named else "")
        match = BOOK_BY_NAME.fullmatch(command)
        if match:
            spoken = match.group(1)
            if self.list_owner in ("files", "books") and parse_index(spoken) is not None:
                return self._book_by_number(spoken)
            name = spoken.lower().replace("ё", "е")
            found, _complete = self.files._search(lambda path: path.suffix.lower() in BOOK_EXTENSIONS
                                                  and name in path.stem.lower().replace("ё", "е") and path.is_file())
            if not found:
                return self._finish("ok", "Книгу «{}» не нашла. Искала на рабочем столе, в документах, загрузках и на флешках. Скажите: найди книги.".format(spoken))
            if len(found) > 1 and not any(path.stem.lower().replace("ё", "е") == name for path in found):
                self.files.items = found
                self.files.list_title = "Найдено «{}»".format(spoken)
                self.list_owner = "files"
                names = "; ".join("{}. {}".format(number, path.stem) for number, path in enumerate(found[:5], 1))
                return self._finish("ok", "Нашла несколько: {}. Скажите: читай номер один.".format(names))
            exact = [path for path in found if path.stem.lower().replace("ё", "е") == name]
            return self._read_book((exact or found)[0])
        match = BOOK_BY_NUMBER.fullmatch(command)
        if match and self.list_owner in ("files", "books") and parse_index(match.group(1)) is not None:
            return self._book_by_number(match.group(1))
        match = re.fullmatch(r"(?:открой|включи)(?: файл| книгу)? (.+)", command)
        if match and self.list_owner == "files":
            item = self.files.pick(match.group(1))
            if item is not None and item.is_file() and item.suffix.lower() in (".fb2", ".epub"):
                return self._read_book(item)  # Windows has no program for these: Vega reads them herself
        return None

    def _find_book(self, spoken: str) -> Optional[Path]:
        if self.list_owner == "books" and parse_index(spoken) and parse_index(spoken) <= len(self.books.listed):
            return self.books.listed[parse_index(spoken) - 1]
        if self.list_owner == "files" and parse_index(spoken) is not None:
            item = self.files.pick(spoken)
            return item if item is not None and item.is_file() else None
        name = re.sub(r"^(?:документ|книгу|книга|файл) ", "", spoken).lower().replace("ё", "е")
        found, _complete = self.files._search(lambda path: path.suffix.lower() in BOOK_EXTENSIONS
                                              and name in path.stem.lower().replace("ё", "е") and path.is_file())
        exact = [path for path in found if path.stem.lower().replace("ё", "е") == name]
        return (exact or found or [None])[0]

    def _summary(self, question: str, spoken: str = "") -> Result:
        """«О чём документ», «спроси про документ …»: Gemini tells the gist; without it the start is read."""
        if spoken:
            path = self._find_book(spoken)
            if path is None:
                return self._finish("ok", "Документ «{}» не нашла. Скажите: найди документы.".format(spoken))
        elif self.books.current is not None:
            path = self.books.current.path
        else:
            path = self.books.last_path()
            if path is None:
                return self._finish("unavailable", "Какой документ? Скажите, например: о чём документ счёт, или: о чём документ номер два.")
        try:
            book = self.books.open(path)
        except BookError as error:
            return self._finish("error", str(error))
        if self.books.current is None or self.books.current.path != path:
            self.books.start(book)
        if self.document_ai is not None:
            answer = self.document_ai(book.title, book.text, question)
            if answer and answer.startswith("!"):
                return self._finish("error", answer[1:])
            if answer:
                return self._finish("ok", answer + ("" if question else " Прочитать целиком: скажите «продолжи книгу»."))
        pages = max(1, len(book.text) // 1800)
        from .books import phrases
        start = " ".join(phrase for _offset, phrase in phrases(book.text, 0, 300)[0])
        note = "Кратко пересказывать умеет версия с Gemini и с интернетом. " if question or self.document_ai is None else "Gemini сейчас недоступен. "
        return self._finish("ok", "{}«{}», примерно {} {}. Начало: {} Прочитать целиком: скажите «продолжи книгу».".format(
            note, book.title, pages, plural(pages, ("страница", "страницы", "страниц")), start))

    def _book_by_number(self, spoken: str) -> Result:
        number = parse_index(spoken)
        if self.list_owner == "books":
            if not number or number > len(self.books.listed):
                return self._finish("error", "В списке книг нет номера {}.".format(number))
            return self._read_book(self.books.listed[number - 1])
        item = self.files.pick(spoken)
        if item is None or not item.is_file():
            return self._finish("error", "В списке нет файла номер {}.".format(number))
        return self._read_book(item)

    def _book_list(self) -> Result:
        recent = [(path, mark) for path, mark in self.books.recent() if path.exists()][:5]
        if not recent:
            return self._finish("ok", "Вы ещё не читали книг. Скажите: найди книги, или: читай книгу и её название.")
        self.books.listed = [path for path, _mark in recent]
        self.list_owner = "books"
        names = []
        for number, (path, mark) in enumerate(recent, 1):
            percent = min(100, int(mark.get("position", 0)) * 100 // max(1, int(mark.get("length", 1))))
            names.append("{}. {}, прочитано {} процентов".format(number, mark.get("title") or path.stem, percent))
        return self._finish("ok", "Ваши книги: {}. Скажите: читай номер один.".format("; ".join(names)))

    def _read_book(self, path: Path, position: Optional[int] = None, intro: str = "") -> Result:
        first_time = not self.books.marks
        try:
            book = self.books.open(path)
        except BookError as error:
            return self._finish("error", str(error))
        resumed = position is None and self.books.saved(path) > 0
        self.books.start(book, position)
        if position is None and self.books.position >= len(book.text.rstrip()) - 1:
            self.books.start(book, 0)
            intro = "Эту книгу вы дочитали, читаю сначала."
        if not intro:
            intro = "Продолжаю «{}», прочитано {} процентов.".format(book.title, self.books.percent()) if resumed \
                else "Читаю «{}».".format(book.title)
        if first_time:
            intro += " Остановить чтение: клавиша Ctrl или слово «стоп». Потом скажите: продолжи книгу."
        self.last_topic = "book"
        return self._finish("reading", intro)

    def _burn_flash(self) -> Result:
        """The whole first flash drive onto a blank CD/DVD (Ivan, 2026-11-01)."""
        if self.optical_probe is None or self.burner is None:
            return self._finish("unavailable", "Запись CD и DVD доступна только на Windows.")
        try:
            flashes = self.drive_provider() if self.drive_provider is not None else ()
        except OSError:
            flashes = ()
        if not flashes:
            return self._finish("unavailable", "Флешка не найдена. Вставьте флешку и повторите.")
        flash = flashes[0]
        root = self.usb_copy.path_for_volume(flash) if self.usb_copy is not None else Path(flash.letter + ":\\")
        outcome = self.burner.prepare(root, SYSTEM_FOLDERS, "вся флешка " + volume_name(flash),
                                      flash.label or "Flash " + flash.letter)
        return self._finish(outcome.status, outcome.message)

    def _copy_disc(self) -> Result:
        """Everything from the CD/DVD in the drive onto the flash drive (Ivan, 2026-11-01)."""
        if self.usb_copy is None:
            return self._finish("unavailable", "Копирование с диска на флешку доступно только на Windows.")
        root = self.drives.optical_root()
        if root.status != "ok":
            return self._finish(root.status, root.message)
        outcome = self.usb_copy.prepare_disc(Path(root.message))
        return self._finish(outcome.status, outcome.message)

    def _alarm(self, text: str) -> Result:
        parsed = parse_clock_time(text)
        if parsed is None:
            return self._finish("error", "Не понял время будильника. Скажите, например: поставь будильник на семь тридцать.")
        now = self.clock()
        due = now.replace(hour=parsed[0], minute=parsed[1], second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        try:
            self.personal.add_reminder(due.timestamp(), "будильник на {:02d}:{:02d}".format(*parsed))
        except (OSError, ValueError) as error:
            return self._finish("error", "Не удалось сохранить будильник: {}.".format(error))
        day = "сегодня" if due.date() == now.date() else "завтра"
        return self._finish("ok", "Будильник поставлен на {} {:02d}:{:02d}. Помощник должен быть запущен.".format(day, *parsed))

    def _search_roots(self):
        roots = [self.current_directory, Path.home()]
        if self.drive_provider is not None:
            try:
                roots.extend(Path(volume.letter + ":\\") for volume in self.drive_provider())
            except OSError:
                pass
        return roots

    def _categories(self) -> Result:
        context = ()
        if self.list_owner == "files":
            context = ("что в папке", "открой номер один", "выйди из папки")
        elif self.list_owner == "web" or self.last_topic == "web":
            context = ("дальше", "открой номер один")
        message, names = categories_message(context)
        self.categories_offered = True  # «три», «номер три», «флешки» now name a category
        return self._finish("ok", message, names)

    def _category(self, spoken: str) -> Result:
        index = find_category(spoken)
        if index is None:
            message, names = categories_message()
            self.categories_offered = True
            return self._finish("ok", "Не нашла такую категорию. " + message, names)
        message, commands = category_message(index)
        return self._finish("ok", message, commands)

    def _help(self) -> Result:
        items = []
        if self.browser is not None and (not hasattr(self.browser, "finder") or self.browser.finder() is not None):
            items.append("Открой хром")
            try:
                spoken = [name for name in self.sites.names() if speakable_site_name(name)]
            except (OSError, ValueError):
                spoken = []
            if spoken:
                items.append("Открой " + spoken[0])
                items.append("Какие сайты сохранены?")
        web_items = ()
        if not isinstance(self.web, NoBrowser):
            web_items = (("Найди на ютубе …", "Что нашлось?", "Воспроизведи второй", "Что на странице?",
                          "Прочитай текст", "Пауза", "Вперёд на тридцать секунд", "Какие фильмы здесь есть?"))
            items.extend(web_items)
        if self.system is not None:
            items.extend(("Какой заряд батареи?", "Громче", "Тише", "Какие окна открыты?", "Открой блокнот",
                          "Прочитай окно", "Что можно нажать?", "Нажми кнопку …", "Сверни окно", "Выключи компьютер"))
        if self.drive_provider is not None:
            items.append("Какие съёмные диски подключены?")
        if self.burner is not None:
            items.append("Запиши на диск папку …")
        # Context first (ТЗ, раздел 3): what fits the current situation, then the everyday commands.
        base = list(self.help_items)
        if self.last_topic == "web" or self.list_owner == "web":
            items = list(web_items) + [item for item in items if item not in web_items] + base
        elif self.list_owner == "files":
            files_items = ["Что в папке", "Открой номер один", "Следующие файлы", "Найди фотографии", "Создай папку …", "Выйди из папки"]
            items = files_items + base + items
        else:
            items = base[:4] + items + base[4:]
        options = tuple(items[self.help_index:self.help_index + 5])
        self.help_index = (self.help_index + 5) % len(items)
        return self._finish("ok", "Сейчас доступны: " + "; ".join(options) + ". Общие команды: Повтори, Замолчи, Отмена.", options)

    def _usb_busy(self) -> bool:
        worker = getattr(self.usb_copy, "worker", None)
        return worker is not None and worker.is_alive()

    def poll_due(self) -> Tuple[str, ...]:
        alerts = ["Таймер завершён." for _ in range(self.timers.pop_due())]
        try:
            for item in self.personal.pop_due_items(self.clock().timestamp()):
                if item["due"] < self.started_at - 60:
                    alerts.append("Пропущено, пока Вега была выключена: {}. Срок был {}.".format(
                        item["text"], _day_and_time(item["due"])))
                else:
                    alerts.append("Напоминание: {}.".format(item["text"]))
        except (OSError, ValueError, KeyError, TypeError):
            alerts.append("Не удалось прочитать напоминания. Проверьте файл данных.")
        try:
            alerts.extend(self._daily_alerts(self.clock().timestamp()))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if self.usb_copy is not None:
            alerts.extend(self.usb_copy.poll_events())
        if self.burner is not None:
            alerts.extend(self.burner.poll_events())
        alerts.extend(self.files.poll_events())
        if not self.unfinished_announced:
            self.unfinished_announced = True
            entry = None if self._usb_busy() else self.files.unfinished()
            if entry is not None:
                alerts.append("Прошлое копирование {} не закончено. Чтобы докопировать, скажите: продолжи копирование.".format(entry["label"]))
        if alerts:
            self.last_message = alerts[-1]
        return tuple(alerts)

    def handle(self, phrase: str) -> Result:
        offered, self.categories_offered = self.categories_offered, False
        understood = canonical(strip_assistant_name(normalize(phrase)))
        result = self._handle(phrase)
        if result.status == "unknown" and offered:
            heard = re.sub(r"^(?:открой|выбери|давай|прочитай|категория) ", "", canonical(strip_assistant_name(normalize(phrase))))
            if find_category(heard) is not None:
                result = self._category(heard)
        if result.status == "unknown":
            retry = self._second_chance(phrase)
            if retry is not None:
                second = self._handle(retry)
                if second.status != "unknown":
                    result = second
        if result.status == "unknown":
            # Free wording, offline: «можешь открыть блокнот», «блокнот открой», «а теперь наоборот».
            for other in variants(canonical(strip_assistant_name(normalize(phrase))), self.last_command)[:6]:
                again = self._handle(other)
                if again.status == "unknown":
                    retry = self._second_chance(other)
                    again = self._handle(retry) if retry is not None else again
                if again.status != "unknown":
                    result, understood = again, other
                    break
        if result.status not in ("unknown", "error", "unavailable"):
            self.last_command = understood
        self.command_log.add(phrase, result.status, result.message)
        return result

    def _second_chance(self, phrase: str) -> Optional[str]:
        """A phrase no router took: a bare list number («номер один», «первый») opens that item of the
        list just read; otherwise the closest known command, when it is clearly the one meant."""
        command = canonical(strip_assistant_name(normalize(phrase)))
        choice = re.sub(r"^(?:открой|прочитай|включи|выбери|давай|переключись на|перейди на|перейди в) ", "", command)
        if parse_index(choice) is None and self.list_owner and len(command.split()) in (2, 3) \
                and parse_index(command.split(" ", 1)[1]) is not None:
            choice = command.split(" ", 1)[1]  # «бронь первый»: the verb was misheard, the number was not
        if parse_index(choice) is not None:
            if self.list_owner in ("files", "web") and choice != command and command.startswith("открой "):
                return None  # «открой второй» was already tried as it is
            if self.list_owner in ("files", "web"):
                return "открой " + choice
            if self.list_owner == "news":
                return "прочитай новость {}".format(parse_index(choice))
            if self.list_owner == "windows":
                return "переключись на окно {}".format(parse_index(choice))
        site = self._closest_site(command)
        if site is not None:
            return "открой " + site
        return closest(command)

    def _closest_site(self, command: str) -> Optional[str]:
        """«открой кино крот», «эйч ди резко», a bare «ютуб»: the site whose name was heard almost right."""
        name = re.sub(r"^(?:открой |зайди на |перейди на )?(?:сайт |страницу )?", "", command)
        aliases = {alias: url for names, url in BUILTIN_SITES for alias in names}
        try:
            aliases.update({saved: "saved:" + saved for saved in self.sites.names() if saved not in aliases})
        except (OSError, ValueError, AttributeError):
            pass
        if name in aliases:
            return name
        if not command.startswith(("открой ", "зайди на ", "перейди на ", "сайт ")):
            return None  # a bare word is taken only when it is exactly a site name
        return closest_name(name, aliases)

    def user_name(self) -> str:
        return user_name.load(self.config_dir)

    def _name_command(self, command: str) -> Optional[Result]:
        """«Вега, меня зовут Игорь», «как меня зовут», «забудь моё имя» (Ivan, 2026-11-01)."""
        if command in user_name.ASK:
            name = self.user_name()
            return self._finish("ok", "Вас зовут {}.".format(name) if name else
                                "Я пока не знаю вашего имени. Скажите: Вега, меня зовут, и ваше имя.")
        if command in user_name.FORGET:
            user_name.forget(self.config_dir)
            return self._finish("ok", "Хорошо, больше не буду называть вас по имени.")
        match = user_name.SET.fullmatch(command)
        if match is None:
            return None
        name = user_name.tidy(match.group(1))
        if not name:
            return None
        try:
            user_name.save(self.config_dir, name)
        except OSError:
            return self._finish("unavailable", "Имя сохраняется только в установленной Веге.")
        return self._finish("ok", "Приятно познакомиться, {}! Теперь буду звать вас по имени.".format(name))

    def _handle(self, phrase: str) -> Result:
        if ASSISTANT_CALL.fullmatch(normalize(phrase) + " "):
            return self._finish("ok", user_name.greeting(self.user_name()))  # the greeting again while she is listening
        command = canonical(strip_assistant_name(normalize(phrase)))
        named = self._name_command(command)
        if named is not None:
            return named
        if command in ("помоги", "какие команды доступны", "какие команды мне сейчас доступны", "что я могу сделать сейчас",
                       "что ты умеешь", "все категории", "какие категории", "какие категории есть", "что ты можешь",
                       "что умеешь", "список команд", "какие есть команды") or HELP_QUESTION.fullmatch(command):
            self.help_index = 0
            self.last_topic = "help"
            return self._categories()
        category = CATEGORY_PHRASE.fullmatch(command)
        if category:
            return self._category(category.group(1))
        if command == "следующие команды":
            return self._help()
        if command in ("дальше", "еще", "следующие пять", "еще пять", "продолжай"):
            if self.last_topic == "web" and self.web.last_list:
                return self._web(self.web.more())
            if self.last_topic == "files" and self.files.items:
                return self._file(self.files.more())
            if command in ("дальше", "еще"):
                self.last_topic = "help"
                return self._help()
        self.last_topic = None
        confirmed = self._confirm(command)
        if confirmed is not None:
            return confirmed
        daily_result = self._daily_command(command)
        if daily_result is not None:
            return daily_result
        radio_result = self._radio_command(command)
        if radio_result is not None:
            return radio_result
        book_result = self._book_command(command)
        if book_result is not None:
            return book_result
        # before the file router: «скопируй диск на флешку» is not a file called «диск»
        if command in ("запиши флешку на диск", "запиши на диск флешку", "запиши всю флешку на диск", "запиши все с флешки на диск",
                       "запиши с флешки на диск", "запиши флешку на компакт диск", "скопируй флешку на диск",
                       "скопируй все с флешки на диск", "скопируй с флешки на диск", "перепиши флешку на диск",
                       "перепиши все с флешки на диск", "перепиши с флешки на диск") or FLASH_TO_DISC.fullmatch(command):
            return self._burn_flash()
        if command in ("скопируй диск на флешку", "скопируй все с диска на флешку", "скопируй с диска на флешку",
                       "скопируй компакт диск на флешку", "скопируй все с компакт диска на флешку", "перепиши диск на флешку",
                       "перепиши все с диска на флешку", "перепиши с диска на флешку", "запиши диск на флешку",
                       "запиши все с диска на флешку", "запиши с диска на флешку") or DISC_TO_FLASH.fullmatch(command):
            return self._copy_disc()
        speech_result = self._speech_command(command)
        if speech_result is not None:
            return speech_result
        system_result = self._system_command(command)
        if system_result is not None:
            return system_result
        keyboard_result = self._keyboard_command(command)
        if keyboard_result is not None:
            return keyboard_result
        window_result = self._window_command(command)
        if window_result is not None:
            return window_result
        # Ivan, 2026-10-27: no confirmation; Vega says when, and the computer turns off by itself.
        if command in SHUTDOWN_PHRASES:
            return self._power("shutdown")
        if command in RESTART_PHRASES:
            return self._power("restart")
        if command == "удали последнюю заметку":
            try:
                notes = self.personal.notes()
            except (OSError, ValueError) as error:
                return self._finish("error", "Не удалось прочитать заметки: {}.".format(error))
            if not notes:
                return self._finish("ok", "Заметок нет.")
            return self._ask_confirmation("delete_last_note", notes[-1])
        if command in ("удали все заметки", "очисти заметки"):
            try:
                count = len(self.personal.notes())
            except (OSError, ValueError) as error:
                return self._finish("error", "Не удалось прочитать заметки: {}.".format(error))
            if not count:
                return self._finish("ok", "Заметок нет.")
            return self._ask_confirmation("clear_notes", count)
        if command in ("сколько осталось на таймере", "проверь таймер", "сколько осталось до таймера"):
            left = self.timers.remaining()
            if not left:
                return self._finish("ok", "Таймеров нет.")
            return self._finish("ok", "До ближайшего таймера {}.".format(spoken_duration(left[0])) +
                                (" Всего таймеров: {}.".format(len(left)) if len(left) > 1 else ""))
        if command in ("отмени таймер", "отмени таймеры", "удали таймер"):
            count = self.timers.cancel_all()
            return self._finish("ok" if count else "unavailable", "Таймеры отменены: {}.".format(count) if count else "Таймеров нет.")
        alarm = re.fullmatch(r"(?:поставь будильник на|разбуди меня в|разбуди меня на|будильник на) (.+)", command)
        if alarm:
            return self._alarm(alarm.group(1))
        if command == "повтори":
            return Result("ok", self.last_message or "Пока нечего повторить.")
        if command == "замолчи":
            return Result("ok", "")
        if command in ("продолжи копирование", "докопируй", "продолжи перемещение", "доделай копирование"):
            if self._usb_busy():
                return self._finish("unavailable", "Копирование уже идёт. Скажите: сколько осталось копировать.")
            return self._file(self.files.resume())
        if command in ("сохрани отчет для помощи", "сохрани отчет", "отчет для помощи", "сделай отчет для помощи",
                       "отчет", "сделай отчет", "создай отчет", "сохрани отчет об ошибках",
                       "отправь отчет", "отправить отчет", "отправь отчет разработчику"):
            try:
                path = self.report()
            except OSError as error:
                return self._finish("error", "Отчёт сохранить не удалось: {}.".format(error.strerror or error))
            if path is None:
                return self._finish("unavailable", "Отчёт для помощи сохраняется только на Windows.")
            return self._finish("ok", "Отчёт сохранён на рабочем столе: файл {}. Его можно отправить разработчику на почту: {}.".format(
                path.name, DEVELOPER_EMAIL_SPOKEN))
        if command in CONTACT_PHRASES:
            return self._finish("ok", "Почта разработчика Веги: {}. Если что-то не работает, скажите: Вега, сохрани отчёт, "
                                      "и отправьте файл с рабочего стола на эту почту.".format(DEVELOPER_EMAIL_SPOKEN))
        if command in ("забудь копирование", "не надо докопировать", "не докопировать"):
            return self._file(self.files.forget_unfinished())
        if command in ("отмена", "останови копирование", "отмени копирование") and self.files.busy():
            return self._file(self.files.cancel())
        if command in ("сколько осталось копировать", "сколько осталось", "ход копирования") and self.files.busy():
            return self._file(self.files.progress_status())
        if command == "отмена":
            if self.pending_confirmation is not None:
                self.pending_confirmation = self.pending_action = self.pending_phrase = None
                return self._finish("ok", "Отменено. Ничего не изменено.")
            if self.burner is not None and (self.burner.pending is not None or self.burner.busy()):
                outcome = self.burner.cancel()
                return self._finish(outcome.status, outcome.message)
            if self.usb_copy is not None:
                outcome = self.usb_copy.cancel()
                return self._finish(outcome.status, outcome.message)
            return self._finish("unavailable", "Сейчас нет операции для отмены.")
        if command in ("который час", "который сейчас час", "сколько времени", "сколько сейчас времени", "скажи время", "какое сейчас время"):
            return self._finish("ok", "По часам компьютера сейчас " + self.clock().strftime("%H:%M") + ".")
        if command in ("какое сегодня число", "какое число", "какое число сегодня", "какая сегодня дата", "какая дата"):
            return self._finish("ok", "По календарю компьютера сегодня " + self.clock().strftime("%d.%m.%Y") + ".")
        if command in ("есть ли записывающий привод", "есть ли привод для записи диска"):
            if self.optical_probe is None:
                return self._finish("unavailable", "Проверка привода CD/DVD доступна только на Windows.")
            try:
                optical = self.optical_probe()
            except (OSError, ValueError):
                return self._finish("error", "Не удалось проверить оптический привод через IMAPI.")
            if optical.writer_count == 0:
                return self._finish("ok", "Записывающий привод CD/DVD не найден.")
            if optical.ready_writer_count == 0:
                return self._finish("ok", "Записывающий привод найден, но подходящий пустой носитель не подтверждён.")
            return self._finish("ok", "Записывающий привод и подходящий пустой носитель обнаружены.")
        if command.startswith("запиши на диск "):
            if self.optical_probe is None:
                return self._finish("unavailable", "Запись на оптический CD/DVD-диск пока не реализована. USB-копирование этой командой не запускается.")
            try:
                optical = self.optical_probe()
            except (OSError, ValueError):
                return self._finish("error", "Не удалось проверить оптический привод через IMAPI.")
            if optical.writer_count == 0:
                return self._finish("unavailable", "Записывающий привод CD/DVD не найден. USB-копирование этой командой не запускается.")
            if optical.ready_writer_count == 0:
                return self._finish("unavailable", "Записывающий привод CD/DVD найден, но подходящий пустой носитель не подтверждён. Запись не начата.")
            if self.burner is None:
                return self._finish("unavailable", "Записывающий привод и пустой CD/DVD обнаружены, но запись здесь недоступна. Носитель не изменён.")
            name = command[len("запиши на диск "):]
            if name.startswith("папку "):
                name = name[len("папку "):]
            folders = find_folders(name, self._search_roots())
            if not folders:
                return self._finish("error", "Папка «{}» не найдена в текущей папке, в папке пользователя и на флешках. Диск не изменён.".format(name))
            if len(folders) > 1:
                return self._finish("unavailable", "Нашлось несколько папок «{}»: {}. Перейдите в нужную папку или переименуйте одну из них. Диск не изменён.".format(
                    name, "; ".join(str(folder) for folder in folders[:3])))
            outcome = self.burner.prepare(folders[0])
            return self._finish(outcome.status, outcome.message)
        if command in ("подтверждаю запись на диск", "подтверждаю запись диска", "подтверждаю запись"):
            if self.burner is None:
                return self._finish("unavailable", "Нет подготовленного плана записи.")
            outcome = self.burner.confirm()
            return self._finish(outcome.status, outcome.message)
        if command in ("сколько осталось записывать", "ход записи", "как идет запись"):
            if self.burner is None:
                return self._finish("unavailable", "Сейчас запись диска не идёт.")
            outcome = self.burner.progress_status()
            return self._finish(outcome.status, outcome.message)
        if command in ("отмени запись", "отмени запись диска"):
            if self.burner is None:
                return self._finish("unavailable", "Сейчас нет записи диска.")
            outcome = self.burner.cancel()
            return self._finish(outcome.status, outcome.message)
        if command in ("скопируй все с первой на вторую", "скопируй все с первой флешки на вторую", "скопируй все с первого диска на второй"):
            if self.usb_copy is None:
                return self._finish("unavailable", "USB-копирование доступно только на Windows.")
            outcome = self.usb_copy.prepare_first_to_second()
            return self._finish(outcome.status, outcome.message)
        if command in ("скопируй все со второй на первую", "скопируй все со второй флешки на первую", "скопируй все со второго диска на первый"):
            if self.usb_copy is None:
                return self._finish("unavailable", "USB-копирование доступно только на Windows.")
            outcome = self.usb_copy.prepare_second_to_first()
            return self._finish(outcome.status, outcome.message)
        if command in ("подтверждаю копирование", "подтверждаю копирование с первой на вторую", "подтверждаю копирование со второй на первую"):
            if self.usb_copy is None:
                return self._finish("unavailable", "Нет подготовленного плана копирования.")
            outcome = self.usb_copy.confirm()
            return self._finish(outcome.status, outcome.message)
        if command in ("останови копирование", "отмени копирование"):
            if self.usb_copy is None:
                return self._finish("unavailable", "Сейчас нет копирования для отмены.")
            outcome = self.usb_copy.cancel()
            return self._finish(outcome.status, outcome.message)
        if command in ("сколько осталось копировать", "сколько осталось", "ход копирования"):
            if self.usb_copy is None:
                return self._finish("unavailable", "Сейчас копирование не идёт.")
            outcome = self.usb_copy.progress_status()
            return self._finish(outcome.status, outcome.message)
        if command in ("какие флешки подключены", "какие флеш накопители подключены", "какие внешние диски подключены", "какие съемные диски подключены", "покажи съемные диски"):
            if self.usb_copy is None:
                return self._finish("unavailable", "Список съёмных дисков доступен только на Windows.")
            outcome = self.usb_copy.list_devices()
            return self._finish(outcome.status, outcome.message)
        if command == "открой загрузки" and self._chrome_active():
            return self._web(self.web.open_special("downloads"))
        drive_result = self._drive_command(command)
        if drive_result is not None:
            return drive_result
        web_outcome = route(command, self.web, self.web.last_list if self.list_owner == "web" else None)
        if web_outcome is not None:
            return self._web(web_outcome)
        if command in ("открой chrome", "открой хром", "открой браузер", "запусти браузер"):
            if self.browser is None:
                return self._finish("unavailable", "Управление Chrome доступно только на Windows.")
            outcome = self.browser.open_browser()
            return self._finish(outcome.status, outcome.message)
        if command in ("какие сайты сохранены", "какие сайты есть", "список сайтов"):
            try:
                names = [name for name in self.sites.names() if speakable_site_name(name)]
            except (OSError, ValueError):
                return self._finish("error", "Не удалось прочитать сохранённые сайты.")
            if not names:
                return self._finish("ok", "Сохранённых сайтов с русским названием нет.")
            return self._finish("ok", "Сохранённые сайты: " + "; ".join(names[:5]) + ".")
        if command.startswith("открой ") or command.startswith("запусти "):
            site_name = re.sub(r"^(?:сайт|страницу) ", "", command.split(" ", 1)[1])
            try:
                url = self.sites.get(site_name)
            except (OSError, ValueError):
                return self._finish("error", "Не удалось прочитать сохранённые сайты.")
            if url:
                if self.browser is None:
                    return self._finish("unavailable", "Управление сайтами доступно только на Windows.")
                outcome = self.browser.open_site(url)
                if outcome.status in ("ok", "unverified") and hasattr(self.web, "note_opened"):
                    self.web.note_opened(url)
                    self.list_owner = "web"
                return self._finish(outcome.status, outcome.message)
            if site_name in PROGRAMS:
                if self.system is None:
                    return self._finish("unavailable", "Запуск программ доступен только на Windows.")
                outcome = self.system.open_program(site_name)
                return self._finish(outcome.status, outcome.message)
        file_outcome = route_files(command, self.files, self.list_owner == "files")
        if file_outcome is not None:
            return self._file(file_outcome)
        web_outcome = route_followup(command, self.web, self.web.last_list if self.list_owner == "web" else None)
        if web_outcome is not None:
            return self._web(web_outcome)
        timer = re.fullmatch(r"(?:поставь|установи|заведи) таймер на (?:(.+?) )?(секунду|секунд|секунды|минуту|минуты|минут|час|часа|часов|полчаса)", command)
        if timer:
            seconds = duration_seconds(timer.group(1), timer.group(2))
            if seconds is None:
                return self._finish("error", "Не понял число в таймере. Скажите, например: поставь таймер на пять минут.")
            try:
                self.timers.add(seconds)
            except ValueError as error:
                return self._finish("error", str(error))
            return self._finish("ok", "Таймер установлен на {}.".format(" ".join(part for part in timer.group(1, 2) if part)))
        reminder = re.fullmatch(r"напомни через (?:(.+?) )?(минуту|минуты|минут|час|часа|часов|полчаса) (.+)", command)
        if reminder:
            seconds = duration_seconds(reminder.group(1), reminder.group(2))
            if seconds is None:
                return self._finish("error", "Не понял срок напоминания. Скажите, например: напомни через десять минут позвонить.")
            if not 1 <= seconds <= 365 * 24 * 3600:
                return self._finish("error", "Срок напоминания должен быть от минуты до года.")
            due, text = self.clock().timestamp() + seconds, reminder.group(3)

            def save_reminder() -> Result:
                try:
                    self.personal.add_reminder(due, text)
                except (OSError, ValueError) as error:
                    return self._finish("error", "Не удалось сохранить напоминание: {}.".format(error))
                return self._finish("ok", "Напоминание сохранено: {}.".format(text))
            return self._read_back("Напомнить в {}: {}?".format(datetime.fromtimestamp(due).strftime("%H:%M"), text), save_reminder)
        if command in ("какие напоминания", "какие будильники", "прочитай напоминания"):
            try:
                reminders = self.personal.upcoming()
            except (OSError, ValueError, KeyError, TypeError) as error:
                return self._finish("error", "Не удалось прочитать напоминания: {}.".format(error))
            try:
                repeating = self.personal.daily()
            except (OSError, ValueError):
                repeating = []
            if not reminders and not repeating:
                return self._finish("ok", "Напоминаний нет.")
            parts = []
            if repeating:
                parts.append("Постоянные: " + "; ".join("{}, {}".format(item["text"], _daily_when(item)) for item in repeating)
                             + ". Удалить: скажите «удали напоминание про» и о чём оно.")
            if reminders:
                parts.append("Разовые: " + "; ".join("{}. {}, {}".format(
                    number, item["text"], _day_and_time(item["due"]))
                    for number, item in enumerate(reminders[:5], 1)) + ". Чтобы удалить, скажите: удали напоминание и номер.")
            return self._finish("ok", " ".join(parts))
        match = re.fullmatch(r"(?:удали|отмени) (?:напоминание|будильник)(?: номер)?(?: (.+))?", command)
        if match:
            try:
                reminders = self.personal.upcoming()
            except (OSError, ValueError, KeyError, TypeError) as error:
                return self._finish("error", "Не удалось прочитать напоминания: {}.".format(error))
            alarms = [item for item in reminders if item["text"].startswith("будильник")] if "будильник" in command else reminders
            number = parse_index(match.group(1)) if match.group(1) else (1 if len(alarms) == 1 else None)
            if not alarms:
                return self._finish("ok", "Удалять нечего.")
            if number is None or not 0 < number <= len(alarms):
                return self._finish("error", "Назовите номер. Скажите: какие напоминания.")
            chosen = alarms[number - 1]

            def remove() -> Result:
                try:
                    done = self.personal.delete_reminder(chosen["due"], chosen["text"])
                except (OSError, ValueError) as error:
                    return self._finish("error", "Не удалось удалить: {}.".format(error))
                return self._finish("ok" if done else "error", "Удалено: {}.".format(chosen["text"]) if done else "Его уже нет.")
            return self._ask_phrase("подтверждаю удаление", "Удалить «{}» на {}? Скажите: подтверждаю удаление.".format(
                chosen["text"], datetime.fromtimestamp(chosen["due"]).strftime("%d.%m %H:%M")), lambda: _Done(remove()))
        if command.startswith("запиши заметку "):
            note = command[len("запиши заметку "):]

            def save_note() -> Result:
                try:
                    self.personal.add_note(note)
                except (OSError, ValueError) as error:
                    return self._finish("error", "Не удалось сохранить заметку: {}.".format(error))
                return self._finish("ok", "Заметка сохранена: {}.".format(note))
            return self._read_back("Записать заметку: {}?".format(note), save_note)
        if command == "прочитай заметки":
            try:
                notes = self.personal.notes()
            except (OSError, ValueError) as error:
                return self._finish("error", "Не удалось прочитать заметки: {}.".format(error))
            return self._finish("ok", "Заметок нет." if not notes else "Заметки: " + "; ".join(notes[:5]) + ".")
        if command.startswith("сколько будет "):
            try:
                answer = calculate(replace_number_words(command[len("сколько будет "):]))
            except ValueError as error:
                return self._finish("error", str(error))
            return self._finish("ok", "Ответ: {}.".format(answer))
        if command.startswith("переведи "):
            try:
                answer = calculate(replace_number_words(command[len("переведи "):]))
            except ValueError as error:
                return self._finish("error", str(error))
            return self._finish("ok", "Ответ: {}.".format(answer))
        info = self._info_command(command)
        if info is not None:
            return info
        # What was heard is said back: the person learns whether Vega misheard or the phrase is unknown.
        guesses = endings_of(command)
        if guesses:
            # Only the end of the phrase was heard («музыку»): offer the commands it can be the end of.
            quoted = ["«{}»".format(guess) for guess in guesses]
            offer = quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " или " + quoted[-1]
            return self._finish("unknown", "Не поняла: «{}». Может быть, {}?".format(command, offer))
        return self._finish("unknown", "Не поняла: «{}». Скажите: помоги.".format(command))
