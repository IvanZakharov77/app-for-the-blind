"""Weather (Open-Meteo, free, no key) and news (an RSS feed the user chose).

Every answer names its source and the time of the data. Network content is only read
aloud, never treated as a command. Offline answers say so plainly.
"""

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
import json
import re
import ssl
from typing import Callable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request

from .net import open_url
from .numbers import plural
import xml.etree.ElementTree as ElementTree

TIMEOUT = 8
MAX_BYTES = 2 * 1024 * 1024
WEATHER_CODES = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "изморозь и туман",
    51: "слабая морось", 53: "морось", 55: "сильная морось", 56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежные зёрна", 80: "небольшой ливень", 81: "ливень",
    82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад", 95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


@dataclass
class OnlineOutcome:
    status: str
    message: str


class Offline(Exception):
    pass


def _context() -> ssl.SSLContext:
    from .net import context
    return context()


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "VoiceAssist/1.0 (local voice assistant)"})
    try:
        with open_url(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES + 1)
    except (OSError, ValueError) as error:
        raise Offline(str(error)) from error
    if len(data) > MAX_BYTES:
        raise Offline("слишком большой ответ")
    return data


def degrees_after_do(value: float) -> str:
    """«до 21 градуса», «до 5 градусов»."""
    rounded = abs(int(round(value)))
    return "градуса" if rounded % 10 == 1 and rounded % 100 != 11 else "градусов"


def signed(value: float) -> str:
    rounded = int(round(value))
    if rounded == 0:
        return "ноль"
    return ("плюс " if rounded > 0 else "минус ") + str(abs(rounded))


def city_variants(spoken: str) -> List[str]:
    """Vosk gives «в казани», «в москве»: try the heard form, then likely nominatives."""
    word = spoken.strip()
    variants = [word]
    for ending, replacements in (("е", ("а", "", "я")), ("и", ("ь", "а", "я")), ("у", ("а",)), ("ом", ("",)), ("ах", ("и", "а"))):
        if word.endswith(ending):
            variants.extend(word[: -len(ending)] + replacement for replacement in replacements)
    return variants


GOOGLE_NEWS = "https://news.google.com/rss"
NEWS_LANGUAGE = {"hl": "ru", "gl": "RU", "ceid": "RU:ru"}


# Google News editions that have Russian-language headlines; elsewhere the Russian edition is used.
RUSSIAN_EDITIONS = ("RU", "UA")


def news_language(country: Optional[str] = None) -> dict:
    country = (country or "").upper()
    if country not in RUSSIAN_EDITIONS:
        return dict(NEWS_LANGUAGE)
    return {"hl": "ru", "gl": country, "ceid": country + ":ru"}


def top_news_feed(country: Optional[str] = None) -> dict:
    """Main Russian-language headlines of the person's country: works with no setup at all."""
    return {"name": "Google Новости", "url": GOOGLE_NEWS + "?" + urlencode(news_language(country))}


def local_news_feed(place: str, country: Optional[str] = None) -> dict:
    """Fresh articles that mention the city or region, from many local and national outlets."""
    query = dict(news_language(country), q="{} when:2d".format(place))
    return {"name": "Google Новости по запросу «{}»".format(place), "url": GOOGLE_NEWS + "/search?" + urlencode(query)}


class OnlineInfo:
    def __init__(self, fetcher: Callable[[str], bytes] = fetch, clock: Callable[[], datetime] = datetime.now):
        self.fetch = fetcher
        self.clock = clock
        self.headlines: List[dict] = []

    def detect_city(self) -> Optional[dict]:
        """Rough location by the internet address (ipwho.is, free, no key)."""
        data = json.loads(self.fetch("https://ipwho.is/?lang=ru").decode("utf-8"))
        if not data.get("success") or not data.get("city"):
            return None
        return {"name": data["city"], "latitude": float(data["latitude"]), "longitude": float(data["longitude"]),
                "region": data.get("region") or "", "country": data.get("country_code") or ""}

    def find_city(self, spoken: str) -> Optional[dict]:
        for name in city_variants(spoken):
            query = urlencode({"name": name, "count": 1, "language": "ru", "format": "json"})
            data = json.loads(self.fetch("https://geocoding-api.open-meteo.com/v1/search?" + query).decode("utf-8"))
            results = data.get("results") or []
            if results:
                place = results[0]
                return {"name": place.get("name", name), "latitude": float(place["latitude"]), "longitude": float(place["longitude"])}
        return None

    def weather(self, place: Optional[dict], spoken_city: Optional[str] = None, tomorrow: bool = False) -> OnlineOutcome:
        try:
            if spoken_city:
                place = self.find_city(spoken_city)
                if place is None:
                    return OnlineOutcome("error", "Город «{}» не найден в справочнике Open-Meteo.".format(spoken_city))
            if place is None:
                return OnlineOutcome("unavailable", "Город для погоды не настроен. Скажите: мой город, и название города.")
            query = urlencode({"latitude": place["latitude"], "longitude": place["longitude"], "current_weather": "true",
                               "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                               "timezone": "auto", "forecast_days": 2, "windspeed_unit": "ms"})
            data = json.loads(self.fetch("https://api.open-meteo.com/v1/forecast?" + query).decode("utf-8"))
        except Offline:
            return OnlineOutcome("unavailable", "Нет связи с сервисом погоды Open-Meteo. Проверьте интернет.")
        except (ValueError, KeyError, TypeError):
            return OnlineOutcome("error", "Сервис погоды ответил непонятно. Попробуйте позже.")
        try:
            daily = data["daily"]
            day = 1 if tomorrow else 0
            low, high = daily["temperature_2m_min"][day], daily["temperature_2m_max"][day]
            rain = (daily.get("precipitation_probability_max") or [None, None])[day]
            parts = []
            if tomorrow:
                parts.append("Завтра в городе {}: {}, от {} до {} {}.".format(
                    place["name"], WEATHER_CODES.get(daily["weathercode"][1], "погода без описания"), signed(low), signed(high),
                    degrees_after_do(high)))
            else:
                current = data["current_weather"]
                stamp = str(current.get("time", ""))[-5:]
                wind = int(round(current.get("windspeed", 0)))
                parts.append("Погода в городе {} на {}: {} {}, {}, ветер {} {} в секунду.".format(
                    place["name"], stamp, signed(current["temperature"]),
                    plural(abs(int(round(current["temperature"]))), ("градус", "градуса", "градусов")),
                    WEATHER_CODES.get(current.get("weathercode"), "без описания"), wind, plural(wind, ("метр", "метра", "метров"))))
                parts.append("Сегодня от {} до {}.".format(signed(low), signed(high)))
            if rain is not None:
                parts.append("Вероятность осадков {} {}.".format(int(rain), plural(int(rain), ("процент", "процента", "процентов"))))
            parts.append("Источник: Open-Meteo.")
            return OnlineOutcome("ok", " ".join(parts))
        except (KeyError, IndexError, TypeError, ValueError):
            return OnlineOutcome("error", "В ответе сервиса погоды не хватает данных.")

    def news(self, feed: Optional[dict]) -> OnlineOutcome:
        if feed is None:
            return OnlineOutcome("unavailable", "Источник новостей не настроен. Его выбирают при настройке программы.")
        try:
            root = ElementTree.fromstring(self.fetch(feed["url"]))
        except Offline:
            return OnlineOutcome("unavailable", "Нет связи с источником новостей {}. Проверьте интернет.".format(feed["name"]))
        except ElementTree.ParseError:
            return OnlineOutcome("error", "Источник новостей {} прислал повреждённую ленту.".format(feed["name"]))
        items = []
        for item in root.iter("item"):
            title = re.sub(r"\s+", " ", (item.findtext("title") or "")).strip()
            if title:
                items.append({"title": title[:300], "link": (item.findtext("link") or "").strip(),
                              "text": re.sub(r"<[^>]+>|\s+", " ", item.findtext("description") or "").strip()[:800],
                              "date": item.findtext("pubDate") or ""})
        if not items:
            return OnlineOutcome("ok", "В ленте {} новостей нет.".format(feed["name"]))
        self.headlines = items[:10]
        when = ""
        try:
            when = " на {}".format(parsedate_to_datetime(items[0]["date"]).astimezone().strftime("%H:%M %d.%m"))
        except (TypeError, ValueError, IndexError):
            pass
        spoken = "; ".join("{}. {}".format(number, item["title"]) for number, item in enumerate(items[:5], 1))
        return OnlineOutcome("ok", "Новости {}{}: {}. Скажите: прочитай новость номер.".format(feed["name"], when, spoken))

    def headline(self, number: int) -> OnlineOutcome:
        if not self.headlines:
            return OnlineOutcome("error", "Сначала скажите: какие новости.")
        if not 0 < number <= len(self.headlines):
            return OnlineOutcome("error", "Новости с номером {} нет.".format(number))
        item = self.headlines[number - 1]
        return OnlineOutcome("ok", "{}. {}".format(item["title"], item["text"] or "Подробного текста в ленте нет."))
