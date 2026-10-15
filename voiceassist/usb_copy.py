"""Confirmed, non-overwriting copy between two identified USB volumes."""

from dataclasses import dataclass
from pathlib import Path
import queue
import shutil
import sys
import threading
from typing import Callable, Optional, Tuple

from .drives import UsbVolume, WindowsVolumeAPI, enumerate_usb_volumes
from .files import CopyJournal, CopyPlan, copy_tree, plan_copy
from .numbers import format_size

# Windows service folders in a volume root: copying them is useless and usually fails on locked files.
SYSTEM_FOLDERS = ("System Volume Information", "$RECYCLE.BIN", "RECYCLER", "FOUND.000")
FILE_LIMITS = {"FAT32": (4 * 1024 ** 3, "4 гигабайт"), "FAT": (2 * 1024 ** 3, "2 гигабайт")}


def volume_name(volume: UsbVolume) -> str:
    return "{}{}".format(volume.letter, ", «{}»".format(volume.label) if volume.label else "")


# (genitive "с первого", accusative "на второй", prepositional "на втором")
ORDINALS = (("с первого", "первый", "первом"), ("со второго", "второй", "втором"))


@dataclass(frozen=True)
class CopyAction:
    status: str
    message: str


@dataclass(frozen=True)
class _PendingCopy:
    source: UsbVolume
    destination: UsbVolume
    plan: CopyPlan
    folder: Path


class UsbCopyController:
    def __init__(self, provider: Callable[[], Tuple[UsbVolume, ...]] = enumerate_usb_volumes,
                 path_for_volume: Optional[Callable[[UsbVolume], Path]] = None,
                 guid_lookup: Optional[Callable[[str], str]] = None,
                 copy_function: Callable = copy_tree, journal: Optional[CopyJournal] = None):
        self.provider = provider
        self.journal = journal or CopyJournal(None)
        self.path_for_volume = path_for_volume or (lambda volume: Path(volume.letter + ":\\"))
        if guid_lookup is None and sys.platform == "win32" and path_for_volume is None:
            guid_lookup = WindowsVolumeAPI().volume_guid
        self.guid_lookup = guid_lookup
        self.copy_function = copy_function
        self.listed: Tuple[UsbVolume, ...] = ()
        self.pending: Optional[_PendingCopy] = None
        self.worker: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.progress_copied = 0
        self.progress_total = 0

    def _same_ids(self, source: UsbVolume, destination: UsbVolume) -> bool:
        try:
            if self.guid_lookup is not None:
                return (self.guid_lookup(source.letter + ":\\") == source.guid
                        and self.guid_lookup(destination.letter + ":\\") == destination.guid)
            current = {volume.guid: volume for volume in self.provider()}
            return (current.get(source.guid) == source and current.get(destination.guid) == destination)
        except OSError:
            return False

    def _same_devices(self, source: UsbVolume, destination: UsbVolume) -> bool:
        try:
            current = {volume.guid: volume for volume in self.provider()}
            return (current.get(source.guid) == source and current.get(destination.guid) == destination
                    and current[source.guid].confirmed_usb and current[destination.guid].confirmed_usb
                    and self._same_ids(source, destination))
        except OSError:
            return False

    def list_devices(self) -> CopyAction:
        try:
            self.listed = self.provider()
        except OSError:
            self.listed = ()
            return CopyAction("error", "Не удалось проверить USB-накопители.")
        self.pending = None
        if not self.listed:
            return CopyAction("ok", "USB-накопители не обнаружены. Подключите их после запуска Веги и повторите запрос.")
        names = []
        for index, volume in enumerate(self.listed):
            number = ("первый", "второй", "третий", "четвёртый", "пятый")[index] if index < 5 else str(index + 1)
            kind = "USB" if volume.confirmed_usb else "съёмный, USB-шина не подтверждена"
            names.append("{} диск: {}, {}, {}".format(number, volume.letter, volume.label or "без имени", kind))
        hint = " Скажите: скопируй всё с первой на вторую, или со второй на первую." if len(self.listed) >= 2 and all(volume.confirmed_usb for volume in self.listed[:2]) else ""
        return CopyAction("ok", "Доступные накопители: " + "; ".join(names) + "." + hint)

    def prepare_first_to_second(self) -> CopyAction:
        return self.prepare(0, 1)

    def prepare_second_to_first(self) -> CopyAction:
        return self.prepare(1, 0)

    def prepare(self, source_index: int, destination_index: int) -> CopyAction:
        if self.worker is not None and self.worker.is_alive():
            return CopyAction("unavailable", "Копирование уже идёт.")
        if len(self.listed) < 2:
            try:
                self.listed = self.provider()
            except OSError:
                self.listed = ()
        if len(self.listed) < 2:
            return CopyAction("unavailable", "Нужны две подключённые флешки. Скажите: какие флешки подключены.")
        source, destination = self.listed[source_index], self.listed[destination_index]
        source_word, destination_word = ORDINALS[source_index], ORDINALS[destination_index]
        if not source.confirmed_usb or not destination.confirmed_usb:
            return CopyAction("unavailable", "USB-шина одного из двух дисков не подтверждена. Копирование не запускаю.")
        if not self._same_devices(source, destination):
            self.pending = None
            return CopyAction("error", "Состав или буквы дисков изменились. Снова запросите список накопителей.")
        source_root = self.path_for_volume(source)
        destination_root = self.path_for_volume(destination)
        try:
            plan = plan_copy(source_root, destination_root, SYSTEM_FOLDERS)
            limit = FILE_LIMITS.get(destination.filesystem.upper())
            if limit and plan.largest_file_bytes >= limit[0]:
                return CopyAction("error", "На источнике есть файл от {}. {} на {} диске его не примет.".format(limit[1], destination.filesystem.upper(), destination_word[2]))
            if shutil.disk_usage(destination_root).free < plan.total_bytes:
                return CopyAction("error", "На {} диске недостаточно места для копирования.".format(destination_word[2]))
            folder = next(destination_root / ("VoiceAssist Copy " + str(index)) for index in range(1, 1000)
                          if not (destination_root / ("VoiceAssist Copy " + str(index))).exists())
        except (OSError, ValueError, StopIteration):
            return CopyAction("error", "Не удалось составить план. Проверьте оба диска и свободное место.")
        self.pending = _PendingCopy(source, destination, plan, folder)
        return CopyAction("needs_confirmation", "План копирования {} диска {} на {} диск {} в новую папку {}. Файлов: {}. Объём: {}. Исходные файлы останутся. Скажите: подтверждаю копирование.".format(
            source_word[0], volume_name(source), destination_word[1], volume_name(destination), folder.name, plan.file_count, format_size(plan.total_bytes)))

    def confirm(self) -> CopyAction:
        pending = self.pending
        if pending is None:
            return CopyAction("unavailable", "Нет подготовленного плана копирования.")
        if self.worker is not None and self.worker.is_alive():
            return CopyAction("unavailable", "Копирование уже идёт.")
        if not self._same_devices(pending.source, pending.destination):
            self.pending = None
            return CopyAction("error", "Диски изменились. Снова запросите список и составьте план.")
        try:
            pending.folder.mkdir(exist_ok=False)
        except OSError:
            self.pending = None
            return CopyAction("error", "Не удалось создать отдельную папку на диске {}.".format(pending.destination.letter))
        self.pending = None
        self.cancel_event.clear()
        self.progress_copied = 0
        self.progress_total = pending.plan.file_count
        self.journal.save(pending.plan.source, pending.folder, "с диска {} на диск {} в папку {}".format(
            pending.source.letter, pending.destination.letter, pending.folder.name), False, pending.plan.excluded)
        self.worker = threading.Thread(target=self._copy, args=(pending,), daemon=True)
        self.worker.start()
        return CopyAction("in_progress", "Копирование начато. Скажите «останови копирование» для отмены.")

    def _copy(self, pending: _PendingCopy) -> None:
        try:
            fresh = plan_copy(pending.plan.source, pending.folder, pending.plan.excluded)
            if fresh.manifest_digest != pending.plan.manifest_digest:
                raise ValueError("Содержимое источника изменилось после подтверждения.")
            next_milestone = [25]
            def progress(copied, total):
                self.progress_copied = copied
                if total and copied < total and copied * 100 // total >= next_milestone[0]:
                    self.events.put("Копирование: проверено {} из {} файлов.".format(copied, total))
                    next_milestone[0] += 25
            report = self.copy_function(fresh, confirmed=True, should_cancel=self.cancel_event.is_set,
                                        on_progress=progress,
                                        devices_match=lambda: self._same_ids(pending.source, pending.destination))
            if report.cancelled:
                outcome = "Копирование остановлено по запросу. Скопировано {}, пропущено {}, ошибок {}. Уже скопированные файлы сохранены. Чтобы докопировать, скажите: продолжи копирование.".format(report.copied, report.skipped, report.failed)
            elif report.device_changed:
                outcome = "Копирование остановлено: диск отключён или изменился. Скопировано {}, пропущено {}, ошибок {}. Подключите его снова. Чтобы докопировать, скажите: продолжи копирование.".format(report.copied, report.skipped, report.failed)
            elif report.failed or report.skipped:
                outcome = "Копирование завершилось не полностью. Скопировано {}, пропущено {}, ошибок {}. Чтобы докопировать, скажите: продолжи копирование.".format(report.copied, report.skipped, report.failed)
            else:
                self.journal.clear()
                outcome = "Копирование завершено и проверено. Скопировано файлов: {}. Папка: {}.".format(report.copied, pending.folder.name)
        except (OSError, ValueError) as error:
            outcome = "Копирование не завершено: {}. Проверьте оба диска. Чтобы докопировать, скажите: продолжи копирование.".format(error)
        self.events.put(outcome)

    def cancel(self) -> CopyAction:
        if self.pending is not None:
            self.pending = None
            return CopyAction("ok", "План копирования отменён.")
        if self.worker is not None and self.worker.is_alive():
            self.cancel_event.set()
            return CopyAction("ok", "Остановка копирования запрошена.")
        return CopyAction("unavailable", "Сейчас нет копирования для отмены.")

    def progress_status(self) -> CopyAction:
        if self.worker is None or not self.worker.is_alive():
            return CopyAction("unavailable", "Сейчас копирование не идёт.")
        return CopyAction("ok", "Проверено {} из {} файлов. Время окончания пока не известно.".format(self.progress_copied, self.progress_total))

    def poll_events(self) -> Tuple[str, ...]:
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return (items[-1],) if items else ()
