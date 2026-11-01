"""Internet radio by genre and country, as simply as possible (Ivan, 2026-11-01).

«Вега, включи радио», «включи джаз», «радио Америки джаз», «радио дип хаус», «другое радио»,
«выключи радио» or the Ctrl key, «запомни это радио» and «включи моё радио». No numbers and no
lists: Vega picks a popular working station herself and names it briefly («Джаз, США»).

Stations come from the free Radio Browser directory (radio-browser.info, no key). Windows Media
Player, which every Windows from 7 on has, plays the stream from a small script, so no browser
opens. While Vega listens and answers, the radio is silent: the microphone must hear the person.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import gettempdir
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request

SERVERS = ("de1.api.radio-browser.info", "nl1.api.radio-browser.info", "at1.api.radio-browser.info",
           "fi1.api.radio-browser.info", "de2.api.radio-browser.info")
PLAYABLE = ("MP3", "AAC", "AAC+", "WMA")  # what Windows Media Player on Windows 7 plays without extra codecs
START_SECONDS = 12  # a station that does not start playing in this time is skipped

# spoken genre -> (directory tag, how Vega names it)
GENRES: Dict[str, Tuple[str, str]] = {
    "джаз": ("jazz", "Джаз"), "джаза": ("jazz", "Джаз"), "классика": ("classical", "Классика"),
    "классику": ("classical", "Классика"), "классическая": ("classical", "Классика"),
    "классическую": ("classical", "Классика"), "классической": ("classical", "Классика"),
    "рок": ("rock", "Рок"), "поп": ("pop", "Поп"), "попса": ("pop", "Поп"), "попсу": ("pop", "Поп"),
    "шансон": ("chanson", "Шансон"), "ретро": ("retro", "Ретро"), "хиты": ("hits", "Хиты"),
    "блюз": ("blues", "Блюз"), "кантри": ("country", "Кантри"), "электронная": ("electronic", "Электронная музыка"),
    "электронную": ("electronic", "Электронная музыка"), "электроника": ("electronic", "Электронная музыка"),
    "электронику": ("electronic", "Электронная музыка"), "танцевальная": ("dance", "Танцевальная музыка"),
    "танцевальную": ("dance", "Танцевальная музыка"), "спокойная": ("chillout", "Спокойная музыка"),
    "спокойную": ("chillout", "Спокойная музыка"), "релакс": ("chillout", "Спокойная музыка"),
    "расслабляющая": ("chillout", "Спокойная музыка"), "расслабляющую": ("chillout", "Спокойная музыка"),
    "народная": ("folk", "Народная музыка"), "народную": ("folk", "Народная музыка"),
    "новости": ("news", "Новости"), "детское": ("kids", "Детское радио"), "детская": ("kids", "Детское радио"),
    "детскую": ("kids", "Детское радио"), "православное": ("orthodox", "Православное радио"),
    "христианское": ("christian", "Христианское радио"), "дип хаус": ("deep house", "Дип хаус"),
    "хаус": ("house", "Хаус"), "лаунж": ("lounge", "Лаунж"), "диско": ("disco", "Диско"),
    "регги": ("reggae", "Регги"), "метал": ("metal", "Метал"), "хип хоп": ("hip hop", "Хип-хоп"),
    "рэп": ("rap", "Рэп"), "опера": ("opera", "Опера"), "оперу": ("opera", "Опера"),
    "латино": ("latin", "Латино"), "саундтреки": ("soundtrack", "Музыка из фильмов"),
    "восьмидесятые": ("80s", "Восьмидесятые"), "девяностые": ("90s", "Девяностые"),
    "80": ("80s", "Восьмидесятые"), "90": ("90s", "Девяностые"),
}

# spoken country -> (ISO code, how Vega names it)
_COUNTRIES = (
    ("US", "США", "америки америка американское американский американская американскую сша штатов"),
    ("UA", "Украина", "украины украина украинское украинский украинская украинскую"),
    ("RU", "Россия", "россии россия российское российский"),
    ("DE", "Германия", "германии германия немецкое немецкий немецкая немецкую"),
    ("FR", "Франция", "франции франция французское французский французская французскую"),
    ("IT", "Италия", "италии италия итальянское итальянский итальянская итальянскую"),
    ("GB", "Англия", "англии англия английское английский британии британское британский великобритании лондона"),
    ("PL", "Польша", "польши польша польское польский"),
    ("ES", "Испания", "испании испания испанское испанский"),
    ("CA", "Канада", "канады канада канадское канадский"),
    ("BY", "Беларусь", "беларуси белоруссии беларусь белорусское белорусский"),
    ("KZ", "Казахстан", "казахстана казахстан казахское казахский"),
    ("IL", "Израиль", "израиля израиль израильское израильский"),
    ("TR", "Турция", "турции турция турецкое турецкий"),
    ("GR", "Греция", "греции греция греческое греческий"),
    ("BR", "Бразилия", "бразилии бразилия бразильское бразильский"),
    ("JP", "Япония", "японии япония японское японский"),
    ("GE", "Грузия", "грузии грузия грузинское грузинский"),
    ("MD", "Молдова", "молдовы молдавии молдова молдавское молдавский"),
    ("CZ", "Чехия", "чехии чехия чешское чешский"),
    ("AT", "Австрия", "австрии австрия австрийское австрийский"),
    ("CH", "Швейцария", "швейцарии швейцария швейцарское швейцарский"),
    ("NL", "Нидерланды", "нидерландов голландии голландия голландское голландский"),
    ("CU", "Куба", "кубы куба кубинское кубинский"),
    ("MX", "Мексика", "мексики мексика мексиканское мексиканский"),
    ("IN", "Индия", "индии индия индийское индийский"),
    ("CN", "Китай", "китая китай китайское китайский"),
    ("IE", "Ирландия", "ирландии ирландия ирландское ирландский"),
    ("SE", "Швеция", "швеции швеция шведское шведский"),
    ("FI", "Финляндия", "финляндии финляндия финское финский"),
    ("LV", "Латвия", "латвии латвия латышское латвийское"),
    ("LT", "Литва", "литвы литва литовское литовский"),
    ("EE", "Эстония", "эстонии эстония эстонское эстонский"),
    ("AM", "Армения", "армении армения армянское армянский"),
    ("AZ", "Азербайджан", "азербайджана азербайджан азербайджанское азербайджанский"),
    ("UZ", "Узбекистан", "узбекистана узбекистан узбекское узбекский"),
    ("PT", "Португалия", "португалии португалия португальское португальский"),
    ("AU", "Австралия", "австралии австралия австралийское австралийский"),
)
COUNTRIES: Dict[str, Tuple[str, str]] = {word: (code, name) for code, name, words in _COUNTRIES for word in words.split()}
COUNTRY_NAMES = {code: name for code, name, _words in _COUNTRIES}

FILLER = {"радио", "радиостанцию", "радиостанция", "станцию", "музыку", "музыка", "мне", "пожалуйста", "какое", "нибудь",
          "из", "с", "со", "в", "на", "про", "немного", "послушать", "хорошее", "хорошую", "волну", "песни", "станции"}
START = re.compile(r"^(?:включи|включить|поставь|поставить|вруби|давай|запусти|хочу послушать|хочу|сыграй|играй)\b ?")


class RadioRequest:
    def __init__(self, tag: str = "", genre: str = "", country: str = "", name: str = ""):
        self.tag, self.genre, self.country, self.name = tag, genre, country, name

    def spoken(self) -> str:
        """«Джаз, США»: short, never a long station name."""
        parts = [part for part in (self.genre, COUNTRY_NAMES.get(self.country, "")) if part]
        return ", ".join(parts) or "Радио"

    def __eq__(self, other):
        return isinstance(other, RadioRequest) and vars(self) == vars(other)

    def __repr__(self):
        return "RadioRequest({})".format(vars(self))


def parse(command: str) -> Optional[RadioRequest]:
    """«включи радио америки джаз» -> jazz from the US; None when the phrase is not about radio.

    A phrase without the word «радио» counts only when every word is a genre or a country
    («включи джаз», «поставь дип хаус»); «включи песню …» stays with YouTube."""
    text = START.sub("", command.strip())
    has_radio = bool(re.search(r"\bрадио", text))
    if not has_radio and not START.match(command.strip()):
        return None
    words = text.split()
    request = RadioRequest()
    rest: List[str] = []
    index = 0
    while index < len(words):
        pair = " ".join(words[index:index + 2])
        if pair in GENRES:
            request.tag, request.genre = GENRES[pair]
            index += 2
            continue
        word = words[index]
        if word in GENRES:
            request.tag, request.genre = GENRES[word]
        elif word in COUNTRIES:
            request.country = COUNTRIES[word][0]
        elif word not in FILLER:
            rest.append(word)
        index += 1
    if rest:
        if not has_radio:
            return None
        request.name = " ".join(rest)  # «включи радио маяк»: a station by its name
    elif not has_radio and not (request.tag or request.country):
        return None
    return request


# The directory

def _fetch_json(url: str, timeout: float = 8):
    from .net import open_url
    request = Request(url, headers={"User-Agent": "Vega/1.0 (voice assistant for the blind)"})
    with open_url(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def find_stations(request: RadioRequest, home_country: str = "", fetch: Callable[[str], list] = _fetch_json) -> List[dict]:
    """Popular working stations for the request, best first; the person's own country when none is named."""
    query = {"order": "clickcount", "reverse": "true", "hidebroken": "true", "limit": "40"}
    if request.name:
        query["name"] = request.name
    if request.tag:
        query["tag"] = request.tag
    if request.country:
        query["countrycode"] = request.country
    elif not request.tag and not request.name and home_country:
        query["countrycode"] = home_country  # a bare «включи радио»: your own country
    last_error: Optional[Exception] = None
    for server in SERVERS:
        try:
            stations = fetch("https://{}/json/stations/search?{}".format(server, urlencode(query)))
            break
        except (OSError, ValueError) as error:
            last_error = error
    else:
        raise OSError("каталог радиостанций недоступен: {}".format(last_error))
    good = [station for station in stations
            if station.get("url_resolved") and not station.get("hls") and (station.get("codec") or "").upper() in PLAYABLE]
    seen, result = set(), []
    for station in good:
        key = re.sub(r"\W+", "", (station.get("name") or "").lower())
        if key and key not in seen:
            seen.add(key)
            result.append(station)
    return result


# Playing

_PLAYER_SCRIPT = r'''
Dim player, waited
Set player = CreateObject("WMPlayer.OCX")
player.settings.autoStart = True
player.settings.volume = 100
player.URL = WScript.Arguments(0)
player.controls.play
waited = 0
Do While player.playState <> 3 And waited < CInt(WScript.Arguments(1)) * 10
    WScript.Sleep 100
    waited = waited + 1
Loop
If player.playState <> 3 Then
    WScript.Echo "FAIL"
    WScript.Quit 2
End If
WScript.Echo "PLAYING"
Do
    WScript.Sleep 1000
    If player.playState = 1 Or player.playState = 8 Or player.playState = 10 Then
        player.controls.play
    End If
Loop
'''


class WindowsPlayer:
    """One stream at a time through Windows Media Player in a hidden script; stopping ends the script."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None

    def play(self, url: str) -> bool:
        self.stop()
        if sys.platform != "win32":
            return False
        script = Path(gettempdir()) / "vega-radio.vbs"
        try:
            script.write_text(_PLAYER_SCRIPT, encoding="ascii")
            cscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cscript.exe"
            self.process = subprocess.Popen([str(cscript), "//B", "//Nologo", str(script), url, str(START_SECONDS)],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            line = self.process.stdout.readline().decode("ascii", "replace").strip()
        except OSError:
            self.stop()
            return False
        if line != "PLAYING":
            self.stop()
            return False
        return True

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def playing(self) -> bool:
        return self.process is not None and self.process.poll() is None


class Radio:
    def __init__(self, player=None, find: Callable[..., List[dict]] = find_stations, store: Optional[Path] = None,
                 key_pressed: Optional[Callable[[], bool]] = None):
        self.player = player or WindowsPlayer()
        self.find = find
        self.store = store
        self.request: Optional[RadioRequest] = None
        self.stations: List[dict] = []
        self.index = -1
        self.on = False       # the person wants the radio playing
        self.hushed = False   # silent while Vega listens and answers
        self.lock = threading.Lock()
        if key_pressed is not None:
            threading.Thread(target=self._watch_key, args=(key_pressed,), name="vega-radio-ctrl", daemon=True).start()

    @property
    def station(self) -> Optional[dict]:
        return self.stations[self.index] if 0 <= self.index < len(self.stations) else None

    def start(self, request: RadioRequest, home_country: str = "") -> Tuple[bool, str]:
        try:
            stations = self.find(request, home_country)
        except OSError:
            return False, "Не получилось открыть каталог радиостанций. Проверьте интернет."
        if not stations and request.name and (request.tag or request.country):
            stations = self.find(RadioRequest(request.tag, request.genre, request.country), home_country)
        if not stations:
            return False, "Такого радио не нашла. Скажите, например: включи радио джаз, или: включи радио Америки."
        self.request, self.stations, self.index = request, stations, -1
        name = self._short_name(stations[0]) if request.name else request.spoken()
        return self._next("Включаю радио." if name == "Радио" else "Включаю: {}.".format(name))

    def other(self) -> Tuple[bool, str]:
        if self.request is None:
            return False, "Радио сейчас не играет. Скажите: включи радио."
        return self._next("Другое радио.")

    def _next(self, said: str) -> Tuple[bool, str]:
        with self.lock:
            for _ in range(min(len(self.stations), 6)):  # a few dead streams are skipped silently
                self.index = (self.index + 1) % len(self.stations)
                if self.player.play(self.station["url_resolved"]):
                    self.on, self.hushed = True, False
                    return True, said
            self.on = False
        return False, "Радиостанции сейчас не отвечают. Попробуйте другое радио позже."

    def stop(self) -> str:
        with self.lock:
            self.on = self.hushed = False
            self.player.stop()
        return "Радио выключено."

    def hush(self) -> None:
        """«Привет, Вега» heard: the radio waits, so the microphone hears the person."""
        with self.lock:
            if self.on and not self.hushed:
                self.hushed = True
                self.player.stop()

    def resume(self) -> None:
        with self.lock:
            if self.on and self.hushed and self.station is not None:
                self.hushed = False
                if not self.player.play(self.station["url_resolved"]):
                    self.on = False

    def what(self) -> str:
        station = self.station
        if not self.on or station is None:
            return "Радио сейчас не играет."
        country = COUNTRY_NAMES.get((station.get("countrycode") or "").upper(), station.get("country") or "")
        return "Играет {}{}.".format(station.get("name", "").strip(), ", " + country if country else "")

    def remember(self) -> str:
        station = self.station
        if not self.on or station is None or self.store is None:
            return "Сначала включите радио, которое нравится, потом скажите: запомни это радио."
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            self.store.write_text(json.dumps(station, ensure_ascii=False), encoding="utf-8")
        except OSError:
            return "Не получилось запомнить радио."
        return "Запомнила. Потом скажите: включи моё радио."

    def favourite(self) -> Tuple[bool, str]:
        try:
            station = json.loads(self.store.read_text(encoding="utf-8")) if self.store else None
        except (OSError, ValueError):
            station = None
        if not station:
            return False, "Любимое радио ещё не запомнено. Включите радио и скажите: запомни это радио."
        self.request, self.stations, self.index = RadioRequest(name=station.get("name", "")), [station], -1
        return self._next("Включаю ваше радио.")

    @staticmethod
    def _short_name(station: dict) -> str:
        words = re.sub(r"[^\w\s\-]", " ", station.get("name") or "").split()
        return " ".join(words[:3]) or "радио"

    def _watch_key(self, key_pressed: Callable[[], bool]) -> None:
        """Ctrl switches the radio off, like it stops Vega's speech (Ivan, 2026-11-01)."""
        while True:
            time.sleep(0.15)
            if self.on and not self.hushed and key_pressed():
                self.stop()
