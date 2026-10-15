"""Spoken file manager: known folders, numbered lists, search, and confirmed changes.

Lists are read five at a time. Searches are bounded in depth, folders and time so an old
HDD is never scanned for long. Nothing is overwritten; deletion goes to the Recycle Bin,
and every change is confirmed with its own phrase naming the exact object.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import time
from typing import Callable, List, Optional, Sequence, Tuple

from .files import CopyJournal, _digest, copy_tree, plan_copy, survey_tree
from .numbers import format_size, parse_index, plural

PAGE = 5
# Spoken name → (Windows "User Shell Folders" value, folder name in the profile).
KNOWN_FOLDERS = {
    "документы": ("Personal", "Documents"), "мои документы": ("Personal", "Documents"),
    "загрузки": ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
    "рабочий стол": ("Desktop", "Desktop"),
    "изображения": ("My Pictures", "Pictures"), "картинки": ("My Pictures", "Pictures"), "мои фотографии": ("My Pictures", "Pictures"),
    "папку изображения": ("My Pictures", "Pictures"), "папку фотографии": ("My Pictures", "Pictures"),
    "музыку": ("My Music", "Music"), "папку музыка": ("My Music", "Music"),
    "папку видео": ("My Video", "Videos"), "мои видео": ("My Video", "Videos"),
    "папку пользователя": (None, ""), "домашнюю папку": (None, ""),
}
FOLDER_TITLES = {"Documents": "Документы", "Downloads": "Загрузки", "Desktop": "Рабочий стол", "Pictures": "Изображения",
                 "Music": "Музыка", "Videos": "Видео"}
KIND_EXTENSIONS = {
    "фотографии": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp"),
    "фото": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp"),
    "картинки": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp"),
    "видео": (".mp4", ".avi", ".mkv", ".mov", ".wmv", ".mpg", ".mpeg", ".m4v", ".3gp", ".webm"),
    "фильмы": (".mp4", ".avi", ".mkv", ".mov", ".wmv", ".mpg", ".mpeg", ".m4v", ".webm"),
    "музыку": (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".wma", ".aac"),
    "песни": (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".wma", ".aac"),
    "документы": (".doc", ".docx", ".pdf", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ods", ".fb2", ".epub", ".djvu"),
    "книги": (".fb2", ".epub", ".pdf", ".djvu", ".txt", ".mobi"),
}
KIND_TITLES = {".jpg": "фото", ".jpeg": "фото", ".png": "картинка", ".mp4": "видео", ".avi": "видео", ".mkv": "видео",
               ".mp3": "музыка", ".wav": "звук", ".doc": "документ Word", ".docx": "документ Word", ".pdf": "PDF",
               ".txt": "текст", ".xls": "таблица Excel", ".xlsx": "таблица Excel", ".fb2": "книга", ".epub": "книга"}
# Files that run code when opened: a misheard number must not start one.
RUNNABLE = (".exe", ".com", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".ps1", ".scr",
            ".lnk", ".reg", ".hta", ".cpl", ".jar", ".pif")
SKIP_DIRS = {"appdata", "$recycle.bin", "system volume information", "windows", "program files", "program files (x86)",
             "programdata", "node_modules", ".git", "recycler"}
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"con", "prn", "aux", "nul"} | {"com{}".format(n) for n in range(1, 10)} | {"lpt{}".format(n) for n in range(1, 10)}
FLASH_ORDINALS = {"первую": 0, "первый": 0, "вторую": 1, "второй": 1, "третью": 2, "третий": 2}
SEARCH_LIMITS = (4, 1500, 3.0, 200)  # depth, folders, seconds, matches


@dataclass
class FileOutcome:
    status: str
    message: str
    confirm_phrase: Optional[str] = None
    action: Optional[Callable[[], "FileOutcome"]] = None


def known_folder(spoken: str, home: Path) -> Optional[Path]:
    entry = KNOWN_FOLDERS.get(spoken)
    if entry is None:
        return None
    value_name, folder = entry
    if value_name and sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
            raw, _kind = winreg.QueryValueEx(key, value_name)
            path = Path(os.path.expandvars(raw))
            if path.is_dir():
                return path
        except OSError:
            pass
    return home / folder if folder else home


MY_COMPUTER = "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"  # «Компьютер» in Explorer, Windows 7 and up


def windows_drives() -> List[Path]:
    """Disks that are ready now: C: and up (A: and B: are floppy letters that can make Windows wait)."""
    if sys.platform != "win32":
        return []
    return [Path(letter + ":\\") for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(letter + ":\\")]


def spoken_folder_name(path: Path, home: Path) -> str:
    if path == home:
        return "папка пользователя"
    if path.parent == path:
        return "диск " + str(path).rstrip("\\/")
    return FOLDER_TITLES.get(path.name, path.name)


def describe_item(path: Path) -> str:
    if path.parent == path:
        return "диск " + str(path).rstrip("\\/")
    try:
        if path.is_dir():
            return path.name + " — папка"
        size = path.stat().st_size
    except OSError:
        return path.name
    kind = KIND_TITLES.get(path.suffix.lower())
    return "{}{}, {}".format(path.name, ", " + kind if kind else "", format_size(size))


def valid_name(name: str) -> bool:
    return bool(name.strip()) and not BAD_NAME.search(name) and name.strip(" .").lower() not in RESERVED and len(name) <= 200


def _same_drive(first: Path, second: Path) -> bool:
    return os.path.splitdrive(str(first))[0].lower() == os.path.splitdrive(str(second))[0].lower() and \
        (sys.platform == "win32" or first.stat().st_dev == second.stat().st_dev)


def copy_file_verified(source: Path, target: Path, should_cancel: Callable[[], bool]) -> None:
    """Copy one file without overwrite, flush to disk and compare checksums."""
    created = False
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            created = True
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                if should_cancel():
                    raise InterruptedError()
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if _digest(source) != _digest(target):
            raise OSError("копия не совпала с оригиналом")
        shutil.copystat(str(source), str(target))
    except BaseException:
        if created:
            try:
                target.unlink()
            except OSError:
                pass
        raise


def windows_recycle(path: Path) -> None:
    """Move to the Recycle Bin through SHFileOperationW (Windows 7+), silently."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    operation = SHFILEOPSTRUCTW(None, FO_DELETE, str(path) + "\0", None,
                                FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if code or operation.fAnyOperationsAborted:
        raise OSError("Windows вернула код {}".format(code))


def windows_is_removable(path: Path) -> bool:
    """Removable drives have no Recycle Bin: deletion there is final."""
    import ctypes
    DRIVE_REMOVABLE = 2
    root = os.path.splitdrive(str(path))[0] + "\\"
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_REMOVABLE


class FileBrowser:
    def __init__(self, home: Optional[Path] = None, drive_provider=None,
                 launcher: Optional[Callable[[str], None]] = None,
                 recycler: Optional[Callable[[Path], None]] = None,
                 is_removable: Optional[Callable[[Path], bool]] = None,
                 folder_lookup: Callable[[str, Path], Optional[Path]] = known_folder,
                 volume_root: Callable = lambda volume: Path(volume.letter + ":\\"),
                 journal: Optional[CopyJournal] = None,
                 shower: Optional[Callable[[str], None]] = None,
                 drive_lister: Optional[Callable[[], List[Path]]] = None):
        self.home = home or Path.home()
        # «Открой загрузки» also shows the folder in Explorer: a helper sees it, and Ivan asked for it.
        self.shower = shower or (os.startfile if sys.platform == "win32" else None)
        self.drive_lister = drive_lister or windows_drives
        self.journal = journal or CopyJournal(None)
        self.volume_root = volume_root
        self.drive_provider = drive_provider
        self.launcher = launcher or (os.startfile if sys.platform == "win32" else None)
        self.recycler = recycler or (windows_recycle if sys.platform == "win32" else None)
        self.is_removable = is_removable or (windows_is_removable if sys.platform == "win32" else (lambda path: False))
        self.folder_lookup = folder_lookup
        self.current = self.home
        self.items: List[Path] = []
        self.offset = 0
        self.list_title = ""
        self.worker: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.events: "queue.Queue[str]" = queue.Queue()
        self.progress = (0, 0)

    # Lists

    def _read_folder(self, folder: Path) -> List[Path]:
        entries = [item for item in folder.iterdir() if not item.name.startswith(("~$", ".")) and
                   item.name.lower() not in ("desktop.ini", "thumbs.db") and item.name.lower() not in SKIP_DIRS]
        return sorted(entries, key=lambda item: (not item.is_dir(), item.name.casefold()))

    def _page(self, offset: int) -> FileOutcome:
        self.offset = offset
        chunk = self.items[offset:offset + PAGE]
        if not self.items:
            return FileOutcome("ok", "{}: пусто.".format(self.list_title))
        if not chunk:
            return FileOutcome("ok", "Больше нет.")
        spoken = ["{}. {}".format(offset + index + 1, describe_item(item)) for index, item in enumerate(chunk)]
        tail = " Скажите: следующие файлы." if offset + PAGE < len(self.items) else ""
        head = self.list_title + "." if offset == 0 else ""  # no item count: Ivan wants the names at once
        return FileOutcome("ok", "{} {}.{} Чтобы открыть, скажите: открой номер.".format(head, "; ".join(spoken), tail).strip())

    def go(self, folder: Path) -> FileOutcome:
        try:
            items = self._read_folder(folder)
        except OSError as error:
            return FileOutcome("error", "Папку «{}» прочитать нельзя: {}.".format(folder.name or folder, error.strerror or "нет доступа"))
        self.current = folder
        self.items = items
        self.list_title = "Папка «{}»".format(spoken_folder_name(folder, self.home))
        return self._page(0)

    def open_computer(self) -> FileOutcome:
        """«Открой мой компьютер»: the window «Компьютер» and its disks read as a numbered list."""
        drives = self.drive_lister()
        if not drives:
            return FileOutcome("unavailable", "Список дисков доступен только на Windows.")
        self.items = drives
        self.list_title = "Мой компьютер"
        outcome = self._page(0)
        if self.shower is not None:
            try:
                self.shower(MY_COMPUTER)
            except OSError:
                pass
        return outcome

    def show(self, folder: Path) -> FileOutcome:
        """Open the folder in an Explorer window. The list is read only on «что в папке» (Ivan, 2026-10-14):
        a big folder read aloud on every open is too long; its items can still be opened by number."""
        outcome = self.go(folder)
        if outcome.status != "ok":
            return outcome
        if self.shower is not None:
            try:
                self.shower(str(folder))
            except OSError:
                pass  # the folder is open for Vega anyway; a missing window is not worth an error
        name = spoken_folder_name(folder, self.home)
        if not self.items:
            return FileOutcome("ok", "Открыта папка «{}», она пустая.".format(name))
        return FileOutcome("ok", "Открыта папка «{}». Чтобы послушать, что в ней, скажите: что в папке.".format(name))

    def open_known(self, spoken: str) -> Optional[FileOutcome]:
        folder = self.folder_lookup(spoken, self.home)
        if folder is None:
            return None
        if not folder.is_dir():
            return FileOutcome("unavailable", "Папки «{}» на этом компьютере нет.".format(spoken))
        return self.show(folder)

    def open_flash(self, spoken: str) -> Optional[FileOutcome]:
        volume = self._flash(spoken)
        if volume is None:
            return None
        if isinstance(volume, FileOutcome):
            return volume
        return self.show(self.volume_root(volume))

    def list_current(self) -> FileOutcome:
        return self.go(self.current)

    def more(self) -> FileOutcome:
        return self._page(self.offset + PAGE)

    def where(self) -> FileOutcome:
        return FileOutcome("ok", "Сейчас открыта папка «{}», путь {}.".format(spoken_folder_name(self.current, self.home), self.current))

    def up(self) -> FileOutcome:
        parent = self.current.parent
        if parent == self.current:
            return self.open_computer()  # above a disk is «Мой компьютер», as in Explorer
        return self.show(parent)

    def pick(self, spoken: str) -> Optional[Path]:
        number = parse_index(spoken)
        if number is not None:
            return self.items[number - 1] if 0 < number <= len(self.items) else None
        wanted = spoken.lower().replace("ё", "е")
        for prefix in ("файл ", "папку ", "документ "):
            if wanted.startswith(prefix):
                wanted = wanted[len(prefix):]
        pool = self.items or []
        exact = [item for item in pool if item.stem.lower().replace("ё", "е") == wanted or item.name.lower() == wanted]
        partial = [item for item in pool if wanted in item.name.lower().replace("ё", "е")]
        return (exact or partial or [None])[0]

    def open(self, spoken: str) -> FileOutcome:
        item = self.pick(spoken)
        if item is None:
            return FileOutcome("error", "В списке нет «{}». Скажите: что в папке.".format(spoken))
        if item.is_dir():
            return self.show(item)
        if self.launcher is None:
            return FileOutcome("unavailable", "Открытие файлов программой по умолчанию доступно только на Windows.")

        def launch() -> FileOutcome:
            try:
                self.launcher(str(item))
            except OSError as error:
                return FileOutcome("error", "Windows не открыла файл: {}.".format(error.strerror or error))
            return FileOutcome("unverified", "Файл «{}» передан программе по умолчанию. Скажите: какое окно активно, чтобы проверить.".format(item.name))

        if item.suffix.lower() in RUNNABLE:
            return FileOutcome("needs_confirmation", "«{}» — программа или сценарий. Чтобы запустить, скажите: подтверждаю запуск.".format(item.name),
                               "подтверждаю запуск", launch)
        return launch()

    # Search

    def _roots(self) -> List[Path]:
        roots = [self.current]
        for spoken in ("рабочий стол", "документы", "загрузки", "изображения", "музыку", "мои видео"):
            folder = self.folder_lookup(spoken, self.home)
            if folder is not None and folder.is_dir():
                roots.append(folder)
        if self.drive_provider is not None:
            try:
                roots.extend(self.volume_root(volume) for volume in self.drive_provider())
            except OSError:
                pass
        unique = []
        for root in roots:
            if not any(root == seen or seen in root.parents for seen in unique):
                unique = [seen for seen in unique if root not in seen.parents] + [root]
        return unique

    def _search(self, matches: Callable[[Path], bool]) -> Tuple[List[Path], bool]:
        depth_limit, folder_limit, seconds, match_limit = SEARCH_LIMITS
        started = time.monotonic()
        found: List[Path] = []
        visited = 0
        complete = True
        queue_ = [(root, 0) for root in self._roots()]
        while queue_:
            folder, depth = queue_.pop(0)
            visited += 1
            if visited > folder_limit or time.monotonic() - started > seconds or len(found) >= match_limit:
                complete = False
                break
            try:
                entries = list(os.scandir(str(folder)))
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith((".", "~$")) or entry.name.lower() in SKIP_DIRS:
                    continue
                path = Path(entry.path)
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if matches(path) and path not in found:
                    found.append(path)
                if is_dir and depth + 1 < depth_limit:
                    queue_.append((path, depth + 1))

        def newest(path: Path) -> float:
            try:
                return -path.stat().st_mtime
            except OSError:
                return 0.0
        return sorted(found, key=newest), complete

    def find_kind(self, kind: str) -> Optional[FileOutcome]:
        extensions = KIND_EXTENSIONS.get(kind)
        if extensions is None:
            return None
        found, complete = self._search(lambda path: path.suffix.lower() in extensions and path.is_file())
        return self._found(found, complete, kind)

    def play_music(self) -> FileOutcome:
        """«Включи музыку»: the newest song found starts in the default player."""
        found, _complete = self._search(lambda path: path.suffix.lower() in KIND_EXTENSIONS["музыку"] and path.is_file())
        if not found:
            return FileOutcome("ok", "Музыки на компьютере не нашла. Искала на рабочем столе, в документах, загрузках, в папке Музыка и на флешках.")
        if self.launcher is None:
            return FileOutcome("unavailable", "Включать музыку можно только на Windows.")
        self.items = found
        self.list_title = "Найдено музыку"
        try:
            self.launcher(str(found[0]))
        except OSError as error:
            return FileOutcome("error", "Windows не включила песню: {}.".format(error.strerror or error))
        other = " Другую песню: скажите «найди музыку» и выберите номер." if len(found) > 1 else ""
        return FileOutcome("ok", "Включаю «{}».{}".format(found[0].stem, other))

    def find_name(self, text: str) -> FileOutcome:
        wanted = text.lower().replace("ё", "е")
        found, complete = self._search(lambda path: wanted in path.name.lower().replace("ё", "е"))
        return self._found(found, complete, "«{}»".format(text))

    def _found(self, found: List[Path], complete: bool, what: str) -> FileOutcome:
        note = "" if complete else " Поиск остановлен на части папок, чтобы не нагружать диск."
        if not found:
            return FileOutcome("ok", "Не найдено: {}. Искал на рабочем столе, в документах, загрузках, медиапапках и на флешках.{}".format(what, note))
        self.items = found
        self.list_title = "Найдено {}".format(what)
        outcome = self._page(0)
        outcome.message += note + " Новые файлы — первыми."
        return outcome

    # Changes

    def create_folder(self, name: str) -> FileOutcome:
        name = name.strip()
        if not valid_name(name):
            return FileOutcome("error", "Имя «{}» нельзя использовать для папки.".format(name))
        target = self.current / name
        if target.exists():
            return FileOutcome("error", "Папка «{}» уже есть здесь.".format(name))
        try:
            target.mkdir()
        except OSError as error:
            return FileOutcome("error", "Папку создать не удалось: {}.".format(error.strerror or error))
        return FileOutcome("ok" if target.is_dir() else "error",
                           "Папка «{}» создана в папке «{}».".format(name, spoken_folder_name(self.current, self.home)))

    def rename(self, spoken: str, new_name: str) -> FileOutcome:
        item = self.pick(spoken)
        if item is None:
            return FileOutcome("error", "В списке нет «{}».".format(spoken))
        new_name = new_name.strip()
        if item.is_file() and not Path(new_name).suffix:
            new_name += item.suffix
        if not valid_name(new_name):
            return FileOutcome("error", "Имя «{}» использовать нельзя.".format(new_name))
        target = item.with_name(new_name)
        if target.exists():
            return FileOutcome("error", "«{}» уже существует. Переименование не выполнено.".format(new_name))

        def run() -> FileOutcome:
            if target.exists():
                return FileOutcome("error", "«{}» уже существует. Переименование не выполнено.".format(new_name))
            try:
                item.rename(target)
            except OSError as error:
                return FileOutcome("error", "Переименовать не удалось: {}.".format(error.strerror or error))
            self._replace(item, target)
            return FileOutcome("ok", "Переименовано: «{}» теперь «{}».".format(item.name, new_name))

        return FileOutcome("needs_confirmation", "Переименовать «{}» в «{}»? Скажите: подтверждаю переименование.".format(item.name, new_name),
                           "подтверждаю переименование", run)

    def delete(self, spoken: str) -> FileOutcome:
        item = self.pick(spoken)
        if item is None:
            return FileOutcome("error", "В списке нет «{}».".format(spoken))
        if self.recycler is None:
            return FileOutcome("unavailable", "Удаление в корзину доступно только на Windows.")
        try:
            final = self.is_removable(item)
        except OSError:
            final = True
        what = "папку «{}»".format(item.name) if item.is_dir() else "файл «{}»".format(item.name)

        def run() -> FileOutcome:
            try:
                self.recycler(item)
            except OSError as error:
                return FileOutcome("error", "Удалить не удалось: {}.".format(error))
            if item.exists():
                return FileOutcome("error", "Windows не удалила {}.".format(what))
            self._replace(item, None)
            return FileOutcome("ok", "Удалено: «{}». {}".format(item.name, "Восстановить нельзя." if final else "Его можно вернуть из корзины."))

        warning = "На съёмном диске корзины нет, удаление будет окончательным. " if final else "Объект попадёт в корзину. "
        return FileOutcome("needs_confirmation", "Удалить {}? {}Скажите: подтверждаю удаление.".format(what, warning),
                           "подтверждаю удаление", run)

    def _replace(self, old: Path, new: Optional[Path]) -> None:
        self.items = [new if item == old else item for item in self.items if new is not None or item != old]

    def _flash(self, spoken: str):
        index = FLASH_ORDINALS.get(spoken.split()[0]) if spoken else None
        if not re.search(r"флеш|накопител", spoken) and not (index is not None and "диск" in spoken):
            return None
        if self.drive_provider is None:
            return FileOutcome("unavailable", "Флешки доступны только на Windows.")
        try:
            volumes = self.drive_provider()
        except OSError:
            return FileOutcome("error", "Не удалось проверить флешки.")
        if index is None:
            if len(volumes) == 1:
                return volumes[0]
            return FileOutcome("error", "Уточните: на первую или на вторую флешку." if volumes else "Флешки не подключены.")
        if index >= len(volumes):
            return FileOutcome("error", "Флешки с таким номером нет. Скажите: какие флешки подключены.")
        return volumes[index]

    def target(self, spoken: str):
        """«в документы», «на рабочий стол», «на вторую флешку», «в папку Фото» → folder or FileOutcome."""
        spoken = re.sub(r"^(?:в|на) ", "", spoken)
        volume = self._flash(spoken)
        if isinstance(volume, FileOutcome):
            return volume
        if volume is not None:
            return self.volume_root(volume)
        known = self.folder_lookup(spoken, self.home) or self.folder_lookup({"документах": "документы"}.get(spoken, spoken), self.home)
        if known is not None:
            return known
        name = re.sub(r"^папку ", "", spoken)
        candidate = next((item for item in self.items if item.is_dir() and item.name.lower().replace("ё", "е") == name), None)
        return candidate or FileOutcome("error", "Не знаю папку «{}». Назовите: документы, рабочий стол, загрузки или первую флешку.".format(spoken))

    def transfer(self, spoken_item: str, spoken_target: str, move: bool) -> FileOutcome:
        if self.busy():
            return FileOutcome("unavailable", "Уже идёт копирование. Скажите: сколько осталось копировать.")
        item = self.pick(spoken_item)
        if item is None and spoken_item in ("эту папку", "текущую папку", "всю папку"):
            item = self.current
        if item is None:
            known = self.folder_lookup(re.sub(r"^(?:все |всю )", "", spoken_item), self.home)
            item = known if known is not None and known.is_dir() else None
        if item is None:
            return FileOutcome("error", "Не нашёл «{}». Скажите: что в папке, и назовите номер.".format(spoken_item))
        destination = self.target(spoken_target)
        if isinstance(destination, FileOutcome):
            return destination
        try:
            if not destination.is_dir():
                return FileOutcome("unavailable", "Папки назначения нет.")
            final = destination / item.name
            if final.exists():
                return FileOutcome("error", "В «{}» уже есть «{}». Ничего не перезаписываю; переименуйте один из них.".format(
                    spoken_folder_name(destination, self.home), item.name))
            if item == destination or item in destination.parents:
                return FileOutcome("error", "Нельзя переносить папку в саму себя.")
            if item.is_dir():
                count, total, largest, _digest_ = survey_tree(item)
            else:
                count, total, largest = 1, item.stat().st_size, item.stat().st_size
            quick_move = move and _same_drive(item, destination)
            if not quick_move and shutil.disk_usage(str(destination)).free < total:
                return FileOutcome("error", "Не хватает места: нужно {}, свободно {}.".format(
                    format_size(total), format_size(shutil.disk_usage(str(destination)).free)))
            if largest >= 4 * 1024 ** 3 and self._fat32(destination):
                return FileOutcome("error", "Там файл от 4 гигабайт, а диск назначения в FAT32 его не примет.")
        except (OSError, ValueError) as error:
            return FileOutcome("error", "Не удалось составить план: {}.".format(error))
        verb = "Переместить" if move else "Скопировать"
        plan = "{} «{}» ({} {}, {}) в «{}»?{}".format(
            verb, item.name, count, plural(count, ("файл", "файла", "файлов")), format_size(total),
            spoken_folder_name(destination, self.home),
            " Оригинал будет удалён только после проверки копии." if move and not quick_move else "")
        phrase = "подтверждаю перемещение" if move else "подтверждаю копирование"

        def run() -> FileOutcome:
            if final.exists():
                return FileOutcome("error", "«{}» уже появился в папке назначения. Ничего не перезаписано.".format(item.name))
            if quick_move:
                try:
                    item.rename(final)
                except OSError as error:
                    return FileOutcome("error", "Переместить не удалось: {}.".format(error.strerror or error))
                self._replace(item, None)
                return FileOutcome("ok", "Перемещено: «{}» в «{}».".format(item.name, spoken_folder_name(destination, self.home)))
            self.cancel_event.clear()
            self.progress = (0, count)
            self.journal.save(item, final, "«{}» в «{}»".format(item.name, spoken_folder_name(destination, self.home)), move)
            self.worker = threading.Thread(target=self._copy, args=(item, final, move), daemon=True)
            self.worker.start()
            return FileOutcome("in_progress", "{} начато. Скажите: сколько осталось копировать, или: останови копирование.".format(
                "Перемещение" if move else "Копирование"))

        return FileOutcome("needs_confirmation", plan + " Скажите: {}.".format(phrase), phrase, run)

    @staticmethod
    def _fat32(folder: Path) -> bool:
        if sys.platform != "win32":
            return False
        import ctypes
        name = ctypes.create_unicode_buffer(32)
        root = os.path.splitdrive(str(folder))[0] + "\\"
        if not ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0, None, None, None, name, 32):
            return False
        return name.value.upper().startswith("FAT")

    RESUME_HINT = " Чтобы докопировать, скажите: продолжи копирование."

    def _copy(self, item: Path, final: Path, move: bool, resume: bool = False, excluded: Tuple[str, ...] = ()) -> None:
        try:
            if item.is_dir():
                final.mkdir(exist_ok=resume)
                plan = plan_copy(item, final, excluded)
                report = copy_tree(plan, confirmed=True, should_cancel=self.cancel_event.is_set,
                                   on_progress=lambda done, total: setattr(self, "progress", (done, total)), resume=resume)
                copied, problems, cancelled = report.copied, report.failed + report.skipped, report.cancelled
            else:
                if resume and final.is_file():
                    if final.stat().st_size == item.stat().st_size and _digest(final) == _digest(item):
                        copied, problems, cancelled = 1, 0, False
                        self.progress = (1, 1)
                        return self._copied(item, move, 1)
                    final.unlink()
                copy_file_verified(item, final, self.cancel_event.is_set)
                copied, problems, cancelled = 1, 0, False
                self.progress = (1, 1)
        except InterruptedError:
            copied, problems, cancelled = 0, 0, True
        except (OSError, ValueError) as error:
            self.events.put("Копирование «{}» прервано: {}.{}".format(item.name, error, self.RESUME_HINT))
            return
        if cancelled:
            self.events.put("Копирование остановлено. Готово файлов: {}. Оригинал не тронут.{}".format(copied, self.RESUME_HINT))
            return
        if problems:
            self.events.put("Скопировано файлов: {}, с ошибками: {}. Оригинал не тронут.{}".format(copied, problems, self.RESUME_HINT))
            return
        self._copied(item, move, copied)

    def _copied(self, item: Path, move: bool, copied: int) -> None:
        self.journal.clear()
        if move:
            try:
                shutil.rmtree(str(item)) if item.is_dir() else item.unlink()
            except OSError as error:
                self.events.put("Копия проверена, но оригинал удалить не удалось: {}.".format(error))
                return
            self.events.put("Перемещение «{}» завершено, копия проверена.".format(item.name))
            return
        self.events.put("Копирование «{}» завершено и проверено. Файлов: {}.".format(item.name, copied))

    def unfinished(self) -> Optional[dict]:
        return None if self.busy() else self.journal.load()

    def resume(self) -> FileOutcome:
        """«продолжи копирование»: finish the copy from the journal; matching files are not copied again."""
        if self.busy():
            return FileOutcome("unavailable", "Копирование уже идёт. Скажите: сколько осталось копировать.")
        entry = self.journal.load()
        if entry is None:
            return FileOutcome("unavailable", "Незаконченного копирования нет.")
        source, final = Path(entry["source"]), Path(entry["target"])
        try:
            if not source.exists():
                return FileOutcome("unavailable", "Не вижу, откуда копировать: {}. Подключите флешку или диск и повторите.".format(source))
            if not final.parent.is_dir():
                return FileOutcome("unavailable", "Не вижу, куда копировать: {}. Подключите флешку или диск и повторите.".format(final.parent))
            count = survey_tree(source, tuple(entry.get("excluded") or ()))[0] if source.is_dir() else 1
        except OSError as error:
            return FileOutcome("error", "Диск не читается: {}.".format(error.strerror or error))
        move = bool(entry.get("move"))

        def run() -> FileOutcome:
            if self.busy():
                return FileOutcome("unavailable", "Копирование уже идёт.")
            self.cancel_event.clear()
            self.progress = (0, count)
            self.worker = threading.Thread(target=self._copy, args=(source, final, move, True, tuple(entry.get("excluded") or ())), daemon=True)
            self.worker.start()
            return FileOutcome("in_progress", "Докопирую. Уже готовые файлы проверяю и не копирую заново. Скажите: сколько осталось копировать.")

        return FileOutcome("needs_confirmation", "Продолжить {} {}? Файлов всего: {}. Скажите: да.".format(
            "перемещение" if move else "копирование", entry["label"], count), ("да", "продолжай"), run)

    def forget_unfinished(self) -> FileOutcome:
        if self.journal.load() is None:
            return FileOutcome("ok", "Незаконченного копирования нет.")
        self.journal.clear()
        return FileOutcome("ok", "Хорошо, докопировать не предлагаю. Уже скопированные файлы остались на месте.")

    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def cancel(self) -> FileOutcome:
        if not self.busy():
            return FileOutcome("unavailable", "Сейчас копирования файлов нет.")
        self.cancel_event.set()
        return FileOutcome("ok", "Остановка копирования запрошена.")

    def progress_status(self) -> FileOutcome:
        if not self.busy():
            return FileOutcome("unavailable", "Сейчас копирование файлов не идёт.")
        done, total = self.progress
        return FileOutcome("ok", "Проверено {} из {} файлов.".format(done, total))

    def poll_events(self) -> Tuple[str, ...]:
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return tuple(items)
