"""Read-only file inspection and copy preflight."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import shutil
from typing import Callable, Iterable, List, Optional, Tuple


SMALL_FILE_BYTES = 64 * 1024


@dataclass(frozen=True)
class CopyPlan:
    source: Path
    destination: Path
    file_count: int
    total_bytes: int
    largest_file_bytes: int
    manifest_digest: str
    excluded: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CopyReport:
    copied: int
    skipped: int
    failed: int
    cancelled: bool = False
    device_changed: bool = False


def describe_directory(path: Path, limit: int = 5) -> str:
    entries = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
    if not entries:
        return "Папка пуста."
    names = [item.name + (" — папка" if item.is_dir() else "") for item in entries[:limit]]
    suffix = " Есть ещё файлы." if len(entries) > limit else ""
    return "В папке: " + "; ".join(names) + "." + suffix


def _is_link_like(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _without_excluded(items: Iterable[Path], source: Path, excluded: Tuple[str, ...]) -> List[Path]:
    """Drop top-level folders such as "System Volume Information" that belong to Windows, not the user."""
    names = {name.casefold() for name in excluded}
    return [item for item in items if item.relative_to(source).parts[0].casefold() not in names]


def plan_copy(source: Path, destination: Path, excluded: Tuple[str, ...] = ()) -> CopyPlan:
    excluded = tuple(excluded)
    source = source.resolve(strict=True)
    destination = destination.resolve(strict=True)
    if not source.is_dir() or not destination.is_dir():
        raise ValueError("Источник и назначение должны быть папками.")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Нельзя копировать папку в себя или в её вложенную папку.")
    count, total, largest, digest = survey_tree(source, excluded)
    return CopyPlan(source, destination, count, total, largest, digest, excluded)


def survey_tree(source: Path, excluded: Tuple[str, ...] = ()) -> Tuple[int, int, int, str]:
    """(file count, total bytes, largest file, manifest digest); refuses links and junctions."""
    entries = _without_excluded(source.rglob("*"), source, excluded)
    if any(_is_link_like(item) for item in entries):
        raise ValueError("Источник содержит ссылку или точку подключения. Копирование не начато.")
    files: List[Path] = [item for item in entries if item.is_file()]
    digest = hashlib.sha256()
    sizes = []
    for item in sorted(files):
        metadata = item.stat()
        sizes.append(metadata.st_size)
        fingerprint = "{}\0{}\0{}\0{}\n".format(item.relative_to(source), metadata.st_size,
                                                   metadata.st_mtime_ns, metadata.st_ctime_ns)
        digest.update(fingerprint.encode("utf-8"))
        # File times tick coarsely (about 15 ms on NTFS, 2 s on FAT32), so a quick same-size edit
        # keeps them. Small files are cheap to read, so their content joins the fingerprint.
        if metadata.st_size <= SMALL_FILE_BYTES:
            digest.update(item.read_bytes())
    return len(files), sum(sizes), max(sizes, default=0), digest.hexdigest()


def _digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def _destination_has_link(path: Path, root: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current == root:
            return False
        current = current.parent


class _CopyCancelled(Exception):
    pass


class CopyJournal:
    """The one unfinished copy, kept on disk so it can be finished after a restart or a pulled flash drive."""

    def __init__(self, path: Optional[Path]):
        self.path = path

    def load(self) -> Optional[dict]:
        if self.path is None:
            return None
        try:
            entry = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) for key in ("source", "target", "label")):
            return None
        return entry

    def save(self, source: Path, target: Path, label: str, move: bool = False, excluded: Tuple[str, ...] = ()) -> None:
        if self.path is None:
            return
        entry = {"source": str(source), "target": str(target), "label": label, "move": move, "excluded": list(excluded)}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def clear(self) -> None:
        if self.path is not None:
            try:
                self.path.unlink()
            except OSError:
                pass


def copy_tree(plan: CopyPlan, confirmed: bool,
              should_cancel: Optional[Callable[[], bool]] = None,
              on_progress: Optional[Callable[[int, int], None]] = None,
              devices_match: Optional[Callable[[], bool]] = None,
              resume: bool = False) -> CopyReport:
    """Copy without overwrite; failures remain visible in the returned counts.

    resume: the destination is our own unfinished copy. Files that already match are counted as
    copied; a file that differs (cut off by a pulled drive or a power loss) is copied again."""
    if not confirmed:
        raise ValueError("Для копирования нужно явное подтверждение.")
    fresh = plan_copy(plan.source, plan.destination, plan.excluded)
    if fresh.destination != plan.destination or plan.destination.is_symlink():
        raise ValueError("Папка назначения изменилась. Составьте план заново.")
    if fresh.manifest_digest != plan.manifest_digest:
        raise ValueError("Содержимое источника изменилось. Составьте план заново.")
    if not resume and shutil.disk_usage(plan.destination).free < plan.total_bytes:
        raise ValueError("Недостаточно свободного места.")
    copied = skipped = failed = 0
    current_items = _without_excluded(plan.source.rglob("*"), plan.source, plan.excluded)
    blocked_dirs = []
    for source_dir in sorted((item for item in current_items if item.is_dir()),
                             key=lambda item: (len(item.parts), str(item))):
        if any(blocked == source_dir or blocked in source_dir.parents for blocked in blocked_dirs):
            continue
        if devices_match is not None and not devices_match():
            return CopyReport(copied, skipped, failed, device_changed=True)
        if should_cancel is not None and should_cancel():
            return CopyReport(copied, skipped, failed, cancelled=True)
        target_dir = plan.destination / source_dir.relative_to(plan.source)
        try:
            if _destination_has_link(target_dir, plan.destination):
                raise OSError("Назначение содержит символическую ссылку")
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            blocked_dirs.append(source_dir)
    for source_file in sorted(current_items):
        if not source_file.is_file() or _is_link_like(source_file):
            continue
        if any(blocked in source_file.parents for blocked in blocked_dirs):
            failed += 1
            continue
        if devices_match is not None and not devices_match():
            return CopyReport(copied, skipped, failed, device_changed=True)
        target = plan.destination / source_file.relative_to(plan.source)
        created = False
        if resume and target.is_file() and not target.is_symlink():
            try:
                if target.stat().st_size == source_file.stat().st_size and _digest(target) == _digest(source_file):
                    copied += 1
                    if on_progress is not None:
                        on_progress(copied, plan.file_count)
                    continue
                target.unlink()
            except OSError:
                failed += 1
                continue
        try:
            if _destination_has_link(target.parent, plan.destination):
                raise OSError("Назначение содержит символическую ссылку")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source_file.open("rb") as source_stream, target.open("xb") as target_stream:
                created = True
                while True:
                    if should_cancel is not None and should_cancel():
                        raise _CopyCancelled()
                    chunk = source_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    target_stream.write(chunk)
                # The user hears "проверено" and may pull the flash drive out right away.
                target_stream.flush()
                os.fsync(target_stream.fileno())
            if _digest(source_file) != _digest(target):
                target.unlink()
                failed += 1
            else:
                copied += 1
                if on_progress is not None:
                    on_progress(copied, plan.file_count)
        except FileExistsError:
            skipped += 1
        except _CopyCancelled:
            if created:
                try:
                    target.unlink()
                except OSError:
                    pass
            return CopyReport(copied, skipped, failed, cancelled=True)
        except OSError:
            if created:
                try:
                    target.unlink()
                except OSError:
                    pass
            failed += 1
    failed += sum(1 for blocked in blocked_dirs
                  if not any(blocked in item.parents for item in current_items if item.is_file()))
    return CopyReport(copied, skipped, failed)
