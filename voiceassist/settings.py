"""User settings in %APPDATA%\\VoiceAssist\\settings.json: small, validated, written atomically."""

import copy
import json
from pathlib import Path
from typing import Any, Optional

DEFAULTS = {
    "speech_rate": 0,          # steps of 10 % from the voice's normal rate, −5…+5
    "speech_volume": 100,      # percent, 20…100
    "input_device": None,      # sounddevice index or None for the Windows default microphone
    "search_engine": "гугл",   # гугл, яндекс, duckduckgo; Яндекс закрыт в Украине
    "weather": None,           # {"name": "Москва", "latitude": 55.75, "longitude": 37.62}
    "news": None,              # {"name": "Лента", "url": "https://lenta.ru/rss/news"}
    "pause_for_screen_reader": True,  # silence NVDA before speaking, so the two voices do not overlap
    "voice_engine": "auto",    # auto: Piper when installed and the PC has 8 GB of RAM, else the Windows (SAPI) voice
}


def _valid(key: str, value: Any) -> bool:
    if key == "speech_rate":
        return isinstance(value, int) and -5 <= value <= 5
    if key == "speech_volume":
        return isinstance(value, int) and 20 <= value <= 100
    if key == "input_device":
        return value is None or (isinstance(value, int) and value >= 0)
    if key == "search_engine":
        return value in ("яндекс", "гугл", "duckduckgo")
    if key == "weather":
        return value is None or (isinstance(value, dict) and isinstance(value.get("name"), str)
                                 and isinstance(value.get("latitude"), (int, float)) and -90 <= value["latitude"] <= 90
                                 and isinstance(value.get("longitude"), (int, float)) and -180 <= value["longitude"] <= 180)
    if key == "news":
        return value is None or (isinstance(value, dict) and isinstance(value.get("name"), str)
                                 and isinstance(value.get("url"), str) and value["url"].startswith(("https://", "http://")))
    if key == "voice_engine":
        return value in ("auto", "piper", "sapi")
    if key == "pause_for_screen_reader":
        return isinstance(value, bool)
    return False


class Settings:
    def __init__(self, path: Optional[Path]):
        self.path = path
        self.values = copy.deepcopy(DEFAULTS)
        self.problem: Optional[str] = None
        self.load()

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            self.problem = "Файл настроек не читается, использую обычные настройки: {}.".format(error)
            return
        if not isinstance(data, dict):
            self.problem = "Файл настроек повреждён, использую обычные настройки."
            return
        bad = [key for key, value in data.items() if key in DEFAULTS and not _valid(key, value)]
        for key, value in data.items():
            if key in DEFAULTS and _valid(key, value):
                self.values[key] = value
        if bad:
            self.problem = "В настройках неверные значения: {}. Для них взяты обычные.".format(", ".join(bad))

    def get(self, key: str):
        return self.values[key]

    def set(self, key: str, value) -> None:
        if not _valid(key, value):
            raise ValueError("Недопустимое значение настройки {}.".format(key))
        self.values[key] = value
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def apply_to_speaker(speaker, settings: Settings, base_rate: int) -> None:
    """pyttsx3 rate is words per minute; volume is 0…1."""
    speaker.setProperty("rate", int(base_rate * (1 + settings.get("speech_rate") / 10)))
    speaker.setProperty("volume", settings.get("speech_volume") / 100)
