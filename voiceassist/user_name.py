"""The person's name, so Vega greets them by it: «Привет, Игорь!» (Ivan, 2026-11-01).

One computer, one person: the name lives in %APPDATA%\\VoiceAssist\\username.txt. The installer's
«Имя пользователя» field writes it, and so does «Вега, меня зовут Игорь». Updates keep it.
"""

from pathlib import Path
import re
from typing import Optional

FILE = "username.txt"
SET = re.compile(r"(?:меня зовут|мое имя|моё имя|называй меня|зови меня|обращайся ко мне|мое имя это|меня звать) (.+)")
ASK = ("как меня зовут", "ты знаешь как меня зовут", "как мое имя", "кто я", "ты помнишь как меня зовут")
FORGET = ("забудь мое имя", "забудь моё имя", "не называй меня по имени", "не называй меня")


def tidy(spoken: str) -> str:
    """«игорь петрович» -> «Игорь Петрович»; at most three words, letters and hyphens only."""
    words = [re.sub(r"[^\w\-]", "", word) for word in spoken.split()][:3]
    return " ".join(word[:1].upper() + word[1:] for word in words if word and not word.isdigit())


def load(config_dir: Optional[Path]) -> str:
    if config_dir is None:
        return ""
    try:
        return tidy((config_dir / FILE).read_text(encoding="utf-8-sig").strip())
    except (OSError, ValueError):
        return ""


def save(config_dir: Optional[Path], name: str) -> None:
    if config_dir is None:
        raise OSError("нет папки настроек")
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / FILE).write_text(name, encoding="utf-8-sig")


def forget(config_dir: Optional[Path]) -> None:
    if config_dir is not None:
        try:
            (config_dir / FILE).unlink()
        except OSError:
            pass


def greeting(name: str) -> str:
    return "Привет, {}! Чем я могу помочь?".format(name) if name else "Привет! Чем я могу помочь?"
