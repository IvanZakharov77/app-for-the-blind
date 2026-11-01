"""Confirmed CD/DVD data burning through IMAPI 2 with read-back verification."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from .files import survey_tree
from .numbers import format_size
from .optical import OpticalProbe

# Spoken Russian names of the usual user folders; Windows keeps them under English names.
FOLDER_ALIASES = {
    "документы": "Documents", "мои документы": "Documents", "рабочий стол": "Desktop",
    "изображения": "Pictures", "картинки": "Pictures", "фотографии": "Pictures", "фото": "Pictures",
    "музыка": "Music", "видео": "Videos", "загрузки": "Downloads",
}
FOUR_GIB = 4 * 1024 ** 3
# Room for file system structures and lead-out; burning to the last sector is not worth the risk.
RESERVE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class BurnAction:
    status: str
    message: str


@dataclass(frozen=True)
class BurnPlan:
    source: Path
    drive_index: int
    drive_root: str
    label: str
    file_count: int
    total_bytes: int
    manifest_digest: str
    udf_only: bool
    excluded: Tuple[str, ...] = ()  # a whole flash drive: Windows' own folders in its root stay off the disc


def _spoken(name: str) -> str:
    return re.sub(r"[^а-яa-z0-9]+", " ", name.lower().replace("ё", "е")).strip()


def find_folders(spoken_name: str, roots: Iterable[Path]) -> List[Path]:
    """Folders named like the phrase: an alias ("документы") or a direct child of a search root."""
    wanted = _spoken(spoken_name)
    found = []
    roots = [root for root in roots if root is not None]
    alias = FOLDER_ALIASES.get(wanted)
    for root in roots:
        if alias and (root / alias).is_dir():
            found.append(root / alias)
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                if child.is_dir() and _spoken(child.name) == wanted:
                    found.append(child)
            except OSError:
                continue
    unique = []
    for item in found:
        resolved = item.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def disc_label(name: str) -> str:
    """ISO 9660/Joliet labels are short; keep letters and digits."""
    label = re.sub(r"[^\w ]+", "", name).strip()[:16]
    return label or "VoiceAssist"


def _digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def verify_tree(source: Path, disc_root: Path, excluded: Tuple[str, ...] = ()) -> Tuple[int, List[str]]:
    """Compare every source file with the disc; return (matching count, problem paths)."""
    good = 0
    problems = []
    names = {name.casefold() for name in excluded}
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if relative.parts[0].casefold() in names or not item.is_file():
            continue
        target = disc_root / relative
        try:
            if target.is_file() and _digest(item) == _digest(target):
                good += 1
                continue
        except OSError:
            pass
        problems.append(str(relative))
    return good, problems


_BURN_SCRIPT = r'''
Option Explicit
Dim index, list, label, fsMask, master, recorder, writer, fsi, result, files, stream, line, parts
index = CInt(WScript.Arguments(0))
list = WScript.Arguments(1)
label = WScript.Arguments(2)
fsMask = CInt(WScript.Arguments(3))
On Error Resume Next
Set master = CreateObject("IMAPI2.MsftDiscMaster2")
If Err.Number <> 0 Then Fail "imapi"
Set recorder = CreateObject("IMAPI2.MsftDiscRecorder2")
recorder.InitializeDiscRecorder master.Item(index)
If Err.Number <> 0 Then Fail "recorder"
Set writer = CreateObject("IMAPI2.MsftDiscFormat2Data")
writer.Recorder = recorder
writer.ClientName = "VoiceAssist"
writer.ForceMediaToBeClosed = True
If Err.Number <> 0 Then Fail "recorder"
If Not writer.IsCurrentMediaSupported(recorder) Then Fail "media"
If (writer.CurrentMediaStatus And 2) = 0 Then Fail "media"
Set fsi = CreateObject("IMAPI2FS.MsftFileSystemImage")
fsi.ChooseImageDefaults recorder
fsi.FileSystemsToCreate = fsMask
fsi.VolumeName = label
' each line of the list (UTF-16): "1|folder" puts the folder itself on the disc, "0|folder" only its contents
Set files = CreateObject("Scripting.FileSystemObject")
Set stream = files.OpenTextFile(list, 1, False, -1)
Do Until stream.AtEndOfStream
    line = stream.ReadLine
    If Len(line) > 2 Then
        parts = Split(line, "|", 2)
        fsi.Root.AddTree parts(1), (parts(0) = "1")
        If Err.Number <> 0 Then Fail "image"
    End If
Loop
stream.Close
Set result = fsi.CreateResultImage()
If Err.Number <> 0 Then Fail "image"
WScript.ConnectObject writer, "dw_"
WScript.Echo "STAGE|write"
writer.Write result.ImageStream
If Err.Number <> 0 Then Fail "write"
WScript.DisconnectObject writer
WScript.Echo "DONE"
WScript.Quit 0

Sub Fail(stage)
    WScript.Echo "ERROR|" & stage & "|" & Hex(Err.Number)
    WScript.Quit 3
End Sub

Sub dw_Update(sender, progress)
    Dim percent
    percent = 0
    If progress.SectorCount > 0 Then percent = Int(100 * (progress.LastWrittenLba - progress.StartLba) / progress.SectorCount)
    If percent < 0 Then percent = 0
    If percent > 100 Then percent = 100
    WScript.Echo "PROGRESS|" & progress.CurrentAction & "|" & percent & "|" & progress.RemainingTime
End Sub
'''


def burn_trees(source: Path, excluded: Tuple[str, ...], staging: Path) -> List[Tuple[Path, bool]]:
    """What goes on the disc: (folder, the folder itself or only its contents).

    A plain folder is one tree. A whole flash drive cannot be one tree: Windows' own folders in its
    root (System Volume Information) cannot be read and IMAPI then refuses everything. So each user
    folder of the root is added by itself, and the loose files of the root are first copied into
    `staging`, whose contents go to the root of the disc.
    """
    if not excluded:
        return [(source, False)]
    names = {name.casefold() for name in excluded}
    trees: List[Tuple[Path, bool]] = []
    loose = False
    for item in sorted(source.iterdir()):
        if item.name.casefold() in names:
            continue
        if item.is_dir():
            trees.append((item, True))
        elif item.is_file():
            staging.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(staging / item.name))
            loose = True
    if loose:
        trees.append((staging, False))
    return trees


def run_burn_script(index: int, trees: Sequence[Tuple[Path, bool]], label: str, file_systems: int,
                    on_line: Callable[[str], None]) -> int:
    """Run the IMAPI script; every output line is handed to on_line as it arrives."""
    if sys.platform != "win32":
        raise OSError("Запись CD/DVD доступна только на Windows.")
    cscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cscript.exe"
    with TemporaryDirectory(prefix="voiceassist-burn-") as folder:
        script = Path(folder, "burn.vbs")
        script.write_text(_BURN_SCRIPT, encoding="ascii")
        listing = Path(folder, "trees.txt")
        listing.write_text("".join("{}|{}\n".format(1 if whole else 0, path) for path, whole in trees), encoding="utf-16")
        process = subprocess.Popen([str(cscript), "//B", "//Nologo", str(script), str(index), str(listing),
                                    label, str(file_systems)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for raw in process.stdout:
            on_line(raw.decode("ascii", "replace").strip())
        return process.wait()


_ERRORS = {
    "imapi": "Служба записи дисков Windows недоступна.",
    "recorder": "Не удалось подготовить записывающий привод.",
    "media": "Диск в приводе не подходит для записи или уже не пустой.",
    "image": "Не удалось подготовить файлы для записи. Возможно, какой-то файл открыт в другой программе.",
    "write": "Запись прервалась. Диск, вероятно, испорчен; вставьте новый пустой диск.",
}


class BurnController:
    def __init__(self, probe: Callable[[], OpticalProbe], runner: Callable = run_burn_script,
                 verifier: Callable[[Path, Path], Tuple[int, List[str]]] = verify_tree,
                 wait: Callable[[float], None] = time.sleep, mount_timeout: float = 120.0):
        self.probe = probe
        self.runner = runner
        self.verifier = verifier
        self.wait = wait
        self.mount_timeout = mount_timeout
        self.pending: Optional[BurnPlan] = None
        self.worker: Optional[threading.Thread] = None
        self.events = queue.Queue()
        self.percent = 0
        self.stage = ""

    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def prepare(self, folder: Path, excluded: Tuple[str, ...] = (), name: str = "", label: str = "") -> BurnAction:
        """`name` is how Vega calls the source aloud («флешка E») when it is not a folder name."""
        if self.busy():
            return BurnAction("unavailable", "Запись диска уже идёт.")
        try:
            optical = self.probe()
        except (OSError, ValueError):
            return BurnAction("error", "Не удалось проверить оптический привод.")
        if optical.writer_count == 0:
            return BurnAction("unavailable", "Записывающий привод CD/DVD не найден.")
        if not optical.ready_drives:
            return BurnAction("unavailable", "Вставьте пустой CD или DVD в записывающий привод и повторите команду.")
        index, free_bytes, root = optical.ready_drives[0]
        if not root:
            return BurnAction("error", "Не удалось узнать букву привода, поэтому записанный диск нельзя будет проверить. Запись не начата.")
        try:
            folder = folder.resolve(strict=True)
            spoken = name or "папка " + folder.name
            count, total, largest, digest = survey_tree(folder, excluded)
        except (OSError, ValueError) as error:
            return BurnAction("error", "Не удалось прочитать {}: {}".format(name or "папку " + folder.name, error))
        if count == 0:
            return BurnAction("error", "{} пуста. Записывать нечего.".format(spoken[:1].upper() + spoken[1:]))
        if total + RESERVE_BYTES > free_bytes:
            return BurnAction("error", "{} занимает {}, а на диске свободно {}. Нужен диск большей ёмкости.".format(
                spoken[:1].upper() + spoken[1:], format_size(total), format_size(free_bytes)))
        label = disc_label(label or folder.name or "DISC")
        self.pending = BurnPlan(folder, index, root, label, count, total, digest, largest >= FOUR_GIB, tuple(excluded))
        return BurnAction("needs_confirmation", "План записи: {} на чистый диск в приводе {}. Файлов: {}. Объём: {} из {}. Запись нельзя будет остановить без порчи диска. Скажите: подтверждаю запись на диск.".format(
            spoken, root.rstrip("\\"), count, format_size(total), format_size(free_bytes)))

    def confirm(self) -> BurnAction:
        pending = self.pending
        if pending is None:
            return BurnAction("unavailable", "Нет подготовленного плана записи. Скажите: запиши на диск папку и её название.")
        if self.busy():
            return BurnAction("unavailable", "Запись диска уже идёт.")
        self.pending = None
        try:
            fresh_digest = survey_tree(pending.source, pending.excluded)[3]
        except (OSError, ValueError):
            return BurnAction("error", "Папка изменилась или недоступна. Составьте план заново.")
        if fresh_digest != pending.manifest_digest:
            return BurnAction("error", "Содержимое папки изменилось после плана. Составьте план заново.")
        try:
            optical = self.probe()
        except (OSError, ValueError):
            return BurnAction("error", "Не удалось снова проверить привод. Запись не начата.")
        if not any(drive[0] == pending.drive_index for drive in optical.ready_drives):
            return BurnAction("error", "Пустой диск больше не обнаружен в приводе. Запись не начата.")
        self.percent = 0
        self.stage = "подготовка"
        self.worker = threading.Thread(target=self._burn, args=(pending,), daemon=True)
        self.worker.start()
        return BurnAction("in_progress", "Запись диска начата. Спросите: сколько осталось записывать.")

    def _on_line(self, line: str) -> None:
        parts = line.split("|")
        if parts[0] == "PROGRESS" and len(parts) >= 3:
            try:
                action, percent = int(parts[1]), int(parts[2])
            except ValueError:
                return
            self.stage = {0: "проверка диска", 2: "подготовка привода", 3: "калибровка", 4: "запись",
                          5: "завершение диска"}.get(action, self.stage)
            if action == 4:
                for milestone in (25, 50, 75):
                    if self.percent < milestone <= percent:
                        self.events.put("Запись диска: {} процентов.".format(milestone))
                self.percent = percent
        elif parts[0] == "ERROR":
            self.error_stage = parts[1] if len(parts) > 1 else "write"

    def _burn(self, plan: BurnPlan) -> None:
        self.error_stage = None
        file_systems = 4 if plan.udf_only else 7
        try:
            with TemporaryDirectory(prefix="voiceassist-root-") as staging:
                trees = burn_trees(plan.source, plan.excluded, Path(staging, "root"))
                code = self.runner(plan.drive_index, trees, plan.label, file_systems, self._on_line)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.events.put("Запись диска не выполнена: {}.".format(error))
            return
        if code != 0 or self.error_stage:
            self.events.put("Запись диска не выполнена. " + _ERRORS.get(self.error_stage or "write", _ERRORS["write"]))
            return
        self.stage = "проверка записанных файлов"
        root = Path(plan.drive_root)
        waited = 0.0
        while not root.exists() and waited < self.mount_timeout:
            self.wait(2.0)
            waited += 2.0
        try:
            good, problems = (self.verifier(plan.source, root, plan.excluded) if plan.excluded
                              else self.verifier(plan.source, root))
        except OSError as error:
            self.events.put("Диск записан, но прочитать его для проверки не удалось: {}. Не считайте запись проверенной.".format(error))
            return
        if problems:
            self.events.put("Диск записан, но проверка не прошла: совпало {} из {} файлов. Первый проблемный файл: {}.".format(
                good, plan.file_count, problems[0]))
        else:
            self.events.put("Диск записан и проверен. Файлов: {}. Можно доставать диск.".format(good))

    def cancel(self) -> BurnAction:
        if self.pending is not None:
            self.pending = None
            return BurnAction("ok", "План записи диска отменён. Диск не изменён.")
        if self.busy():
            return BurnAction("unavailable", "Запись уже идёт. Остановка сейчас испортит диск, поэтому я её не прерываю.")
        return BurnAction("unavailable", "Сейчас нет записи диска.")

    def progress_status(self) -> BurnAction:
        if not self.busy():
            return BurnAction("unavailable", "Сейчас запись диска не идёт.")
        if self.stage == "запись":
            return BurnAction("ok", "Идёт запись: {} процентов.".format(self.percent))
        return BurnAction("ok", "Идёт этап: {}.".format(self.stage))

    def poll_events(self) -> Tuple[str, ...]:
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return tuple(items)


def default_search_roots(current: Path, extra: Sequence[Path] = ()) -> List[Path]:
    home = Path.home()
    return [current, home] + list(extra)
