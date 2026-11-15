"""The language Vega speaks (Ivan, 2026-11-15): Russian, Ukrainian, US English, UK English, German, Italian.

The installer writes the chosen language to %APPDATA%\\VoiceAssist\\language.txt. Russian is inside the
installer; another language's voice (Piper) and speech recognizer (Vosk) come as one zip from the
«lang-assets» pre-release of Vega's own GitHub repository, downloaded once and checked by its SHA-256.
"""

import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

LANGUAGE_FILE = "language.txt"
PACKS = "https://github.com/IvanZakharov77/app-for-the-blind/releases/download/lang-assets-1/"


@dataclass(frozen=True)
class Language:
    code: str
    name: str            # the language in itself, as the installer list shows it
    voice: str           # Piper model file name without .onnx
    speaker: str = ""    # speaker inside a multi-speaker Piper model
    wake: tuple = ("вега",)
    check: str = "Проверка."  # Piper's first test phrase
    celsius: bool = True
    clock_12: bool = False


LANGUAGES: Dict[str, Language] = {
    "ru": Language("ru", "Русский", "ru_RU-irina-medium"),
    "uk": Language("uk", "Українська", "uk_UA-ukrainian_tts-medium", speaker="lada", wake=("вега", "вего"),
                   check="Перевірка."),
    "en_us": Language("en_us", "English (United States)", "en_US-lessac-medium", wake=("vega",), celsius=False, clock_12=True,
                      check="Testing."),
    "en_gb": Language("en_gb", "English (United Kingdom)", "en_GB-cori-medium", wake=("vega",), check="Testing."),
    "de": Language("de", "Deutsch", "de_DE-thorsten-medium", wake=("vega",), check="Test."),
    "it": Language("it", "Italiano", "it_IT-paola-medium", wake=("vega",), check="Prova."),
}


def current(config_dir: Optional[Path]) -> Language:
    """The language from the installer, Russian when there is none or it is unknown."""
    try:
        code = (Path(config_dir) / LANGUAGE_FILE).read_text(encoding="utf-8-sig").strip().lower()
    except (OSError, TypeError):
        code = "ru"
    return LANGUAGES.get(code, LANGUAGES["ru"])


def pack_folder(app_dir: Path, language: Language) -> Path:
    return Path(app_dir) / "lang" / language.code


def pack_ready(app_dir: Path, language: Language) -> bool:
    if language.code == "ru":
        return True
    folder = pack_folder(app_dir, language)
    return (folder / "model").is_dir() and (folder / "piper" / (language.voice + ".onnx.json")).is_file()


def speaker_id(model_json: Path, name: str) -> Optional[int]:
    """Lada is one of several voices inside the Ukrainian model: her number from the model's .json."""
    if not name:
        return None
    try:
        data = json.loads(Path(model_json).read_text(encoding="utf-8"))
        return int(data.get("speaker_id_map", {})[name])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _sums(opener) -> Dict[str, str]:
    text = opener(PACKS + "SHA256SUMS").decode("utf-8")
    return {line.split()[1].lstrip("*"): line.split()[0] for line in text.splitlines() if len(line.split()) == 2}


def _get(url: str) -> bytes:
    from .net import open_url
    with open_url(urllib.request.Request(url, headers={"User-Agent": "Vega"}), timeout=120) as response:
        return response.read()


def download_pack(app_dir: Path, language: Language, opener: Callable[[str], bytes] = None,
                  progress: Callable[[str], None] = lambda text: None) -> bool:
    """Downloads and unpacks the language's voice and recognizer; True when they are ready."""
    if pack_ready(app_dir, language):
        return True
    opener = opener or _get
    name = "vega-lang-{}.zip".format(language.code)
    folder = pack_folder(app_dir, language)
    temp = folder.with_name(folder.name + ".part")
    try:
        expected = _sums(opener).get(name)
        progress(name)
        data = opener(PACKS + name)
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            return False
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(parents=True)
        archive = temp / name
        archive.write_bytes(data)
        with zipfile.ZipFile(archive) as packed:
            for member in packed.namelist():
                if member.startswith("/") or ".." in Path(member).parts:
                    return False  # a path outside the folder: never unpack such a zip
            packed.extractall(temp)
        archive.unlink()
        shutil.rmtree(folder, ignore_errors=True)
        os.replace(temp, folder)
        return pack_ready(app_dir, language)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        return False
