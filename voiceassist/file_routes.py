"""Spoken phrases for folders, files, free space, flash drives and the CD/DVD contents."""

import re
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

from .file_browser import FLASH_ORDINALS, KIND_EXTENSIONS, KNOWN_FOLDERS, FileBrowser, FileOutcome
from .numbers import format_size

TRANSFER_ALIASES = {"фотографии": "изображения", "фото": "изображения", "картинки": "изображения",
                    "видео": "мои видео", "все фотографии": "изображения", "все документы": "документы"}


def route_files(command: str, files: FileBrowser, owns_list: bool) -> Optional[FileOutcome]:
    """FileOutcome for a file phrase, or None. owns_list: the last numbered list was a file list."""
    if command in ("что в папке", "какие файлы в папке", "прочитай файлы", "какие здесь файлы", "что в этой папке"):
        return files.list_current()
    if command in ("следующие файлы", "еще файлы", "дальше файлы") or (owns_list and command in ("дальше", "еще", "следующие пять")):
        return files.more()
    if command in ("где я в папках", "какая папка открыта", "какая это папка", "в какой я папке"):
        return files.where()
    if command in ("выйди из папки", "папка выше", "на уровень выше", "наверх", "вверх по папкам", "вернись в папку выше"):
        return files.up()
    if command in ("открой мой компьютер", "мой компьютер", "открой компьютер", "открой этот компьютер", "какие диски есть"):
        return files.open_computer()
    if command.startswith("открой "):
        target = command[len("открой "):]
        target = {"папку документы": "документы", "папку загрузки": "загрузки", "мои документы": "документы"}.get(target, target)
        if target in KNOWN_FOLDERS:
            return files.open_known(target)
        flash = files.open_flash(target)
        if flash is not None:
            return flash
        if target.startswith(("файл ", "папку ", "документ ")) or (owns_list and files.pick(target) is not None):
            return files.open(target)
    match = re.fullmatch(r"создай (?:новую )?папку (.+)", command)
    if match:
        return files.create_folder(match.group(1))
    match = re.fullmatch(r"найди (?:все |мои )?(фотографии|фото|видео|музыку|песни|документы|книги|фильмы|картинки)", command)
    if match:
        return files.find_kind(match.group(1))
    match = re.fullmatch(r"найди файл (.+)|найди папку (.+)|где файл (.+)", command)
    if match:
        return files.find_name(next(group for group in match.groups() if group))
    match = re.fullmatch(r"переименуй (.+?) в (.+)", command)
    if match:
        return files.rename(match.group(1), match.group(2))
    match = re.fullmatch(r"удали (файл .+|папку .+|.+)", command)
    if match and not match.group(1).startswith(("напоминани", "будильник", "заметк", "последнюю заметку", "все заметки", "таймер")) \
            and (owns_list or match.group(1).startswith(("файл ", "папку "))):
        return files.delete(match.group(1))
    match = re.fullmatch(r"(скопируй|перемести) (.+?) ((?:в|на) .+)", command)
    if match:
        item = match.group(2)
        if files.pick(item) is None:
            item = TRANSFER_ALIASES.get(item, item)
        return files.transfer(item, match.group(3), match.group(1) == "перемести")
    return None


def _spoken_drive(letter: str, label: str = "") -> str:
    return "диск {}{}".format(letter, " «{}»".format(label) if label else "")


class DriveInfo:
    """Free space, flash drive details, safe removal and the inserted CD/DVD."""

    def __init__(self, drive_provider=None, fixed_letters: Optional[Callable[[], Sequence[str]]] = None,
                 optical_letters: Optional[Callable[[], Sequence[str]]] = None,
                 eject: Optional[Callable[[str], None]] = None,
                 disk_usage: Callable = shutil.disk_usage, wait: Callable[[float], None] = time.sleep):
        self.drive_provider = drive_provider
        if sys.platform == "win32":
            from .drives import drive_letters_of_type, eject_volume
            fixed_letters = fixed_letters or (lambda: drive_letters_of_type(3))
            optical_letters = optical_letters or (lambda: drive_letters_of_type(5))
            eject = eject or eject_volume
        self.fixed_letters = fixed_letters
        self.optical_letters = optical_letters
        self.eject_function = eject
        self.disk_usage = disk_usage
        self.wait = wait

    def _volumes(self):
        if self.drive_provider is None:
            return None
        return tuple(self.drive_provider())

    def free_space(self) -> FileOutcome:
        parts = []
        try:
            letters = list(self.fixed_letters()) if self.fixed_letters else []
            for letter in letters:
                usage = self.disk_usage(letter + ":\\")
                parts.append("{}: свободно {} из {}".format(_spoken_drive(letter), format_size(usage.free), format_size(usage.total)))
            if not letters:
                usage = self.disk_usage(str(Path.home()))
                parts.append("На диске с папкой пользователя свободно {} из {}".format(format_size(usage.free), format_size(usage.total)))
            for volume in self._volumes() or ():
                usage = self.disk_usage(volume.letter + ":\\")
                parts.append("флешка {}: свободно {}".format(_spoken_drive(volume.letter, volume.label), format_size(usage.free)))
        except OSError as error:
            return FileOutcome("error", "Не удалось проверить место: {}.".format(error.strerror or error))
        return FileOutcome("ok", "; ".join(parts) + ".")

    def _flash(self, spoken: str):
        word = spoken.split()[0] if spoken else ""
        index = FLASH_ORDINALS.get(word)
        try:
            volumes = self._volumes()
        except OSError:
            return FileOutcome("error", "Не удалось проверить флешки.")
        if volumes is None:
            return FileOutcome("unavailable", "Флешки доступны только на Windows.")
        if index is None:
            if len(volumes) == 1:
                return volumes[0]
            return FileOutcome("error", "Уточните: первая или вторая флешка." if volumes else "Флешки не подключены.")
        if index >= len(volumes):
            return FileOutcome("error", "Флешки с таким номером нет. Подключено: {}.".format(len(volumes)))
        return volumes[index]

    def flash_space(self, spoken: str) -> FileOutcome:
        volume = self._flash(spoken)
        if isinstance(volume, FileOutcome):
            return volume
        try:
            usage = self.disk_usage(volume.letter + ":\\")
        except OSError as error:
            return FileOutcome("error", "Флешка не отвечает: {}.".format(error.strerror or error))
        return FileOutcome("ok", "На флешке {}: свободно {} из {}, файловая система {}.".format(
            _spoken_drive(volume.letter, volume.label), format_size(usage.free), format_size(usage.total), volume.filesystem or "неизвестна"))

    def flash_root(self, spoken: str):
        volume = self._flash(spoken)
        return volume if isinstance(volume, FileOutcome) else Path(volume.letter + ":\\")

    def eject(self, spoken: str) -> FileOutcome:
        volume = self._flash(spoken)
        if isinstance(volume, FileOutcome):
            return volume
        if self.eject_function is None:
            return FileOutcome("unavailable", "Безопасное извлечение доступно только на Windows.")
        try:
            self.eject_function(volume.letter)
        except PermissionError:
            return FileOutcome("error", "Флешку {} сейчас извлечь нельзя: на ней открыты файлы или окна. Закройте их и повторите.".format(volume.letter))
        except OSError as error:
            return FileOutcome("error", "Windows не извлекла флешку {}: {}.".format(volume.letter, error))
        for _ in range(10):
            self.wait(0.5)
            try:
                if all(item.guid != volume.guid for item in self._volumes()):
                    return FileOutcome("ok", "Флешку {} можно вынимать.".format(_spoken_drive(volume.letter, volume.label)))
            except OSError:
                break
        return FileOutcome("unverified", "Команда извлечения выполнена, но диск {} ещё виден. Подождите несколько секунд перед тем, как вынуть.".format(volume.letter))

    def optical_root(self) -> FileOutcome:
        """Root of the inserted CD/DVD with data, or why there is none."""
        if self.optical_letters is None:
            return FileOutcome("unavailable", "Привод CD/DVD доступен только на Windows.")
        try:
            letters = list(self.optical_letters())
        except OSError:
            return FileOutcome("error", "Не удалось проверить привод CD/DVD.")
        if not letters:
            return FileOutcome("unavailable", "Привод CD/DVD не найден.")
        for letter in letters:
            if Path(letter + ":\\").exists():
                return FileOutcome("ok", letter + ":\\")
        return FileOutcome("unavailable", "В приводе нет диска с данными, или диск пустой.")

    def optical_space(self, probe) -> FileOutcome:
        root = self.optical_root()
        if root.status == "ok":
            try:
                usage = self.disk_usage(root.message)
            except OSError as error:
                return FileOutcome("error", "Диск не читается: {}.".format(error.strerror or error))
            return FileOutcome("ok", "На диске в приводе записано {}. Дописывать такой диск Вега не умеет.".format(format_size(usage.used)))
        if probe is not None:
            try:
                optical = probe()
            except (OSError, ValueError):
                return FileOutcome("error", "Не удалось проверить привод через IMAPI.")
            if optical.ready_drives:
                return FileOutcome("ok", "В приводе пустой диск, на него помещается {}.".format(format_size(optical.ready_drives[0][1])))
        return root
