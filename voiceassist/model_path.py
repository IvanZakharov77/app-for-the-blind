"""Vosk (Kaldi) cannot open a model whose path has non-Latin letters, and on Windows the program sits under
the user's profile: C:\\Users\\Пользователь\\... Give Vosk a path made of Latin letters only."""

import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional

DONE_MARK = "copied.ok"


def windows_short_path(path: str) -> Optional[str]:
    """The 8.3 short name (C:\\Users\\5D3B~1\\...), when the disk keeps them."""
    if sys.platform != "win32":
        return None
    import ctypes
    size = ctypes.windll.kernel32.GetShortPathNameW(path, None, 0)
    if not size:
        return None
    buffer = ctypes.create_unicode_buffer(size)
    if not ctypes.windll.kernel32.GetShortPathNameW(path, buffer, size):
        return None
    return buffer.value


def shared_folder() -> Path:
    return Path(os.environ.get("ProgramData") or os.environ.get("PUBLIC") or r"C:\ProgramData") / "VoiceAssist"


def latin_model_path(model: Path, short: Callable[[str], Optional[str]] = windows_short_path,
                     fallback: Optional[Path] = None, copy=shutil.copytree, name: str = "model") -> Path:
    """The folder path itself, its short name, or a one-time copy in a Latin-letter folder.
    Piper (C++) has the same trouble as Vosk, so its folder goes through here too (name="piper")."""
    text = str(model)
    if text.isascii():
        return model
    short_name = short(text)
    if short_name and short_name.isascii():
        return Path(short_name)
    target = (fallback or shared_folder()) / name
    if not str(target).isascii():
        return model
    if not (target / DONE_MARK).exists():
        if target.exists():
            shutil.rmtree(str(target), ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        copy(str(model), str(target))
        (target / DONE_MARK).write_text("ok", encoding="ascii")
    return target


def latin_temp_folder(short: Callable[[str], Optional[str]] = windows_short_path) -> Path:
    """A temporary folder whose path has Latin letters only: Piper writes its sound files there."""
    import tempfile
    base = tempfile.gettempdir()
    if not base.isascii():
        short_name = short(base)
        if short_name and short_name.isascii():
            base = short_name
        else:
            folder = shared_folder() / "voice"
            folder.mkdir(parents=True, exist_ok=True)
            base = str(folder)
    return Path(tempfile.mkdtemp(prefix="voiceassist-voice-", dir=base))
