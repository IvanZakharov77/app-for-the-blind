"""«VoiceAssist --setup»: a short text wizard for the person who installs the assistant.

Asks only what the blind user cannot easily set by voice: microphone, voice, city,
news feed, favourite sites and autostart. Every question has a default (Enter keeps it).
"""

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .settings import Settings

NEWS_FEEDS = (
    ("РИА Новости", "https://ria.ru/export/rss2/archive/index.xml"),
    ("Лента.ру", "https://lenta.ru/rss/news"),
    ("ТАСС", "https://tass.ru/rss/v2.xml"),
)


class Wizard:
    def __init__(self, settings: Settings, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
                 microphones: Callable[[], Sequence[Tuple[int, str]]] = lambda: (),
                 voices: Callable[[], Sequence[str]] = lambda: (),
                 save_voice: Callable[[str], None] = lambda name: None,
                 find_city: Optional[Callable[[str], Optional[dict]]] = None,
                 save_site: Callable[[str, str], None] = lambda name, url: None,
                 autostart: Optional[Callable[[], bool]] = None, piper_available: bool = False):
        self.settings = settings
        self.ask = ask
        self.say = say
        self.microphones = microphones
        self.voices = voices
        self.save_voice = save_voice
        self.find_city = find_city
        self.save_site = save_site
        self.autostart = autostart
        self.piper_available = piper_available

    def _choose(self, title: str, options: List[str], current: int) -> Optional[int]:
        self.say(title)
        for number, option in enumerate(options, 1):
            self.say("  {}. {}{}".format(number, option, " (сейчас)" if number - 1 == current else ""))
        while True:
            answer = self.ask("Номер, Enter — оставить: ").strip()
            if not answer:
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            self.say("Введите номер от 1 до {}.".format(len(options)))

    def run(self) -> None:
        self.say("Настройка Веги. Нажимайте Enter, чтобы оставить как есть.")
        microphones = list(self.microphones())
        if microphones:
            current = next((index for index, (device, _name) in enumerate(microphones) if device == self.settings.get("input_device")), -1)
            choice = self._choose("Микрофон:", ["Микрофон Windows по умолчанию"] + [name for _device, name in microphones], current + 1)
            if choice is not None:
                self.settings.set("input_device", None if choice == 0 else microphones[choice - 1][0])
        if self.piper_available:
            engines = ["auto", "piper", "sapi"]
            choice = self._choose("Голос Веги:", ["Автоматически: Piper при 8 ГБ памяти и больше, иначе голос Windows",
                                                         "Всегда нейросетевой голос Piper (ещё около 150 МБ памяти)",
                                                         "Голос Windows, RHVoice (самый лёгкий)"],
                                  engines.index(self.settings.get("voice_engine")))
            if choice is not None:
                self.settings.set("voice_engine", engines[choice])
        voices = list(self.voices()) if self.settings.get("voice_engine") == "sapi" or not self.piper_available else []
        if voices:
            choice = self._choose("Голос (лучше русский, например RHVoice):", ["Автовыбор русского голоса"] + voices, -1)
            if choice is not None:
                self.save_voice("" if choice == 0 else voices[choice - 1])
        engines = ["яндекс", "гугл", "duckduckgo"]
        choice = self._choose("Поисковая система:", ["Яндекс", "Google", "DuckDuckGo"], engines.index(self.settings.get("search_engine")))
        if choice is not None:
            self.settings.set("search_engine", engines[choice])
        if self.find_city is not None:
            current = self.settings.get("weather")
            city = self.ask("Город для погоды{}: ".format(" (сейчас {})".format(current["name"]) if current else "")).strip()
            if city:
                try:
                    place = self.find_city(city)
                except Exception as error:
                    self.say("Нет связи с Open-Meteo ({}). Город можно назвать позже голосом: «Привет, Вега», затем «мой город …».".format(error))
                else:
                    if place:
                        self.settings.set("weather", place)
                        self.say("Город сохранён: {}.".format(place["name"]))
                    else:
                        self.say("Город не найден. Его можно назвать позже голосом.")
        current_news = self.settings.get("news")
        options = [name for name, _url in NEWS_FEEDS] + ["Свой адрес RSS", "Без новостей"]
        choice = self._choose("Новости:", options, next((i for i, (name, _u) in enumerate(NEWS_FEEDS) if current_news and current_news["name"] == name), -1))
        if choice is not None:
            if choice < len(NEWS_FEEDS):
                self.settings.set("news", {"name": NEWS_FEEDS[choice][0], "url": NEWS_FEEDS[choice][1]})
            elif choice == len(NEWS_FEEDS):
                url = self.ask("Адрес RSS (https://…): ").strip()
                name = self.ask("Как называть источник вслух: ").strip() or "новости"
                try:
                    self.settings.set("news", {"name": name, "url": url})
                except ValueError:
                    self.say("Адрес должен начинаться с https:// или http://. Новости не изменены.")
            else:
                self.settings.set("news", None)
        self.say("Сайты, которые человек будет открывать голосом (например: хд резка). Пустое название — закончить.")
        while True:
            name = self.ask("Название вслух: ").strip().lower()
            if not name:
                break
            url = self.ask("Адрес сайта: ").strip()
            try:
                self.save_site(name, url)
                self.say("Сохранено: «{}».".format(name))
            except (OSError, ValueError) as error:
                self.say("Не сохранено: {}.".format(error))
        if self.autostart is not None and self.ask("Запускать Вегу при входе в Windows? (Д/н): ").strip().lower() in ("", "д", "да", "y", "yes"):
            self.say("Автозапуск включён." if self.autostart() else "Автозапуск включить не удалось.")
        self.say("Готово. Настройки: {}".format(self.settings.path or "не сохраняются"))


def input_devices() -> List[Tuple[int, str]]:
    try:
        import sounddevice
        return [(index, device["name"]) for index, device in enumerate(sounddevice.query_devices())
                if device.get("max_input_channels", 0) > 0 and device.get("hostapi") == 0]
    except Exception:
        return []


def tts_voices() -> List[str]:
    try:
        import pyttsx3
        return [voice.name for voice in pyttsx3.init().getProperty("voices")]
    except Exception:
        return []
