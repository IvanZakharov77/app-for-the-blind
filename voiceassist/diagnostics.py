"""«Сохрани отчёт для помощи»: one text file on the desktop that a helper can read or send on.

The command log keeps what was heard and how the assistant answered, so a helper can see why a
command failed without asking the blind user to remember. No tokens, no file contents.
"""

from datetime import datetime
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import __version__

LOG_LIMIT = 256 * 1024
SECRET_FILES = ("bridge.json",)  # the Chrome bridge token stays out of the report


# Dictated text, notes and reminders are personal: the log keeps only the command word.
PRIVATE = re.compile(r"^((?:помощник )?(?:напиши|напечатай|введи|набери|запиши(?: заметку)?|заметка|напомни(?: через [^ ]+ [^ ]+| в [^ ]+(?: [^ ]+)?)?))\b.*", re.I)


class CommandLog:
    def __init__(self, path: Optional[Path], clock: Callable[[], datetime] = datetime.now):
        self.path = path
        self.clock = clock

    def add(self, heard: str, status: str, answer: str) -> None:
        if self.path is None:
            return
        private = PRIVATE.match(heard.strip())
        if private:
            heard, answer = private.group(1) + " …", "(текст не записывается)"
        line = "{} «{}» → {}: {}\n".format(self.clock().strftime("%d.%m %H:%M:%S"), heard, status, answer[:160].replace("\n", " "))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > LOG_LIMIT:
                keep = self.path.read_text(encoding="utf-8", errors="replace")[-LOG_LIMIT // 2:]
                self.path.write_text(keep[keep.find("\n") + 1:], encoding="utf-8")
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line)
        except OSError:
            pass


def _tail(path: Path, lines: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(нет файла)"
    return "\n".join(text.splitlines()[-lines:]) or "(пусто)"


def desktop() -> Path:
    if sys.platform == "win32":
        from .file_browser import known_folder
        found = known_folder("рабочий стол", Path.home())
        if found is not None and found.is_dir():
            return found
    return Path.home() / "Desktop" if (Path.home() / "Desktop").is_dir() else Path.home()


def write_report(config_dir: Path, target_dir: Path, clock: Callable[[], datetime] = datetime.now,
                 extra: Iterable[str] = ()) -> Path:
    from .piper_voice import find_piper, total_memory
    now = clock()
    parts = ["Отчёт Vega {} от {}".format(__version__, now.strftime("%d.%m.%Y %H:%M")), ""]
    parts.append("Windows: {} ({})".format(platform.platform(), platform.machine()))
    parts.append("Программа: {}".format(sys.executable))
    memory = total_memory()
    parts.append("Память: {}".format("{:.1f} ГБ".format(memory / 1024 ** 3) if memory else "неизвестно"))
    try:
        usage = shutil.disk_usage(str(Path.home()))
        parts.append("Свободно на системном диске: {:.1f} ГБ из {:.1f} ГБ".format(usage.free / 1024 ** 3, usage.total / 1024 ** 3))
    except OSError:
        pass
    piper = find_piper((Path(sys.executable).parent, config_dir))
    parts.append("Голос Piper: {}".format(piper[1].name if piper else "не установлен"))
    parts.extend(extra)
    parts += ["", "Настройки (settings.json):"]
    try:
        settings = json.loads((config_dir / "settings.json").read_text(encoding="utf-8"))
        parts.append(json.dumps(settings, ensure_ascii=False, indent=1))
    except (OSError, ValueError):
        parts.append("(по умолчанию)")
    parts.append("Файлы в папке настроек: {}".format(", ".join(sorted(
        item.name for item in config_dir.iterdir() if item.name not in SECRET_FILES) if config_dir.is_dir() else [])))
    parts += ["", "Последние ошибки (last-error.log):", _tail(config_dir / "last-error.log", 60)]
    parts += ["", "Последние команды (commands.log):", _tail(config_dir / "commands.log", 200)]
    target = Path(target_dir) / "Vega-отчёт-{}.txt".format(now.strftime("%Y%m%d-%H%M"))
    # Notepad on Windows 7 reads UTF-8 reliably only with the BOM.
    target.write_text("\n".join(parts) + "\n", encoding="utf-8-sig")
    return target
