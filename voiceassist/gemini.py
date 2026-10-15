"""The «with Gemini» edition: a phrase Vega did not understand is sent, as sound, to Google Gemini.

Ivan, 2026-10-15: the installer offers a standard edition and one with Gemini; for the latter the
person pastes a free key from Google AI Studio, which the installer saves to gemini.json next to the
settings. The local recognizer still does everything it can: only a phrase it could not turn into a
command goes to Gemini, so the free daily limit lasts and Vega works without the internet as before.
"""

import base64
import io
from array import array
import json
import wave
from pathlib import Path
from typing import Callable, Iterable, List, Optional
from urllib.error import HTTPError
from urllib.request import Request

from .net import open_url

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
# Newest cheap model first; a name Google retired answers 404 and the next one is tried.
# 2026-10-15: new keys get 404 for the 2.x names («no longer available to new users»).
MODELS = ("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-2.5-flash-lite")
# 2026-10-15 on Ivan's laptop 6 s was not enough («The read operation timed out»); Vega says «Секунду» meanwhile.
TIMEOUT = 20  # Ivan: give Gemini time; Vega says «Запрос обрабатывается, подождите» meanwhile
MAX_SECONDS = 10
RATE = 8000  # speech needs no more; half the upload on a slow connection

PROMPT = """Ты — модуль понимания команд голосового помощника «Вега» для незрячих и пожилых людей.
В записи человек по-русски (иногда неразборчиво, с ошибками, своими словами) говорит одну команду.
Слова «привет», «Вега» в начале — это обращение, их отбрось.
Местный распознаватель услышал: «{heard}».
Ответь строго JSON: {{"commands": ["...", "..."], "say": "..."}}.
commands — команды Веги по порядку, каждая в нижнем регистре, ровно в таком виде, как в списке ниже. Где в
образце «…», подставь слова человека (название фильма, песни, запрос, текст заметки, имя файла, число).
Обычно команда одна. Если просьба требует нескольких шагов («открой блокнот и напиши привет»), дай все шаги.
say — пусто, если хватает команд. Если человек задаёт вопрос или просит то, чего нет в командах
(узнать факт, посоветовать, поговорить), ответь ему сам в say по-русски, коротко (до трёх предложений), тепло
и просто: он незрячий или пожилой. Не придумывай команд вне списка.
Если в записи нет обращения к Веге (посторонний разговор, телевизор, тишина), ответь {{"commands": [], "say": ""}}.

Если человек хочет сразу смотреть или слушать что-то определённое, выбирай «включи …»: Вега сама найдёт
и откроет лучшее совпадение. «Найди …» — когда он хочет услышать список. Название пиши полностью и правильно,
как оно известно (например, «человек паук нет пути домой», «высоцкий кони привередливые»).

Образцы со свободными словами:
включи песню …; включи на ютубе …; включи фильм … на кинокраде; включи фильм … на резке; включи фильм … на филмиксе;
найди музыку …; найди на ютубе …; найди фильм …; найди фильм … на кинокраде; найди фильм … на резке;
найди фильм … на филмиксе; найди в интернете …; напомни через … минут …; запиши заметку …; напиши …;
сколько будет …; открой папку …; найди файл …; открой сайт …; мой город …; поставь таймер на … минут;
поставь будильник на …; открой номер …; включи номер …; прочитай новость номер …

Готовые команды:
{phrases}"""


def load_key(config_dir: Path) -> Optional[dict]:
    """{"key": …, "model": optional} from gemini.json, or None for the standard edition."""
    try:
        data = json.loads((config_dir / "gemini.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    key = str(data.get("key", "")).strip() if isinstance(data, dict) else ""
    return {"key": key, "model": str(data.get("model", "")).strip()} if key else None


def wav_bytes(blocks: Iterable[bytes], rate: int = 16000) -> bytes:
    """The phrase as a small WAV: silence around it cut off, 8 kHz, at most MAX_SECONDS."""
    samples = array("h")
    samples.frombytes(b"".join(blocks))
    samples = _speech_only(samples, rate)
    if rate == 2 * RATE:
        samples = array("h", ((samples[i] + samples[i + 1]) >> 1 for i in range(0, len(samples) - 1, 2)))
        rate = RATE
    samples = samples[-rate * MAX_SECONDS:]
    out = io.BytesIO()
    with wave.open(out, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(rate)
        sound.writeframes(samples.tobytes())
    return out.getvalue()


def _speech_only(samples: "array", rate: int) -> "array":
    """Drop the quiet before and after the words, keeping 0.3 s around them."""
    step = rate // 10
    loudness = [max(map(abs, samples[i:i + step]), default=0) for i in range(0, len(samples), step)]
    if not loudness or max(loudness) < 500:
        return samples
    limit = max(500, max(loudness) // 8)
    loud = [index for index, level in enumerate(loudness) if level >= limit]
    start, end = max(0, loud[0] - 3), min(len(loudness), loud[-1] + 4)
    return samples[start * step:end * step]


def _post(url: str, body: dict, key: str) -> dict:
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with open_url(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


class GeminiHelper:
    def __init__(self, key: str, phrases: List[str], model: str = "",
                 post: Callable[[str, dict, str], dict] = _post, log: Callable[[str], None] = lambda message: None):
        self.key = key
        self.phrases = phrases
        self.models = [model] if model else list(MODELS)
        self.post = post
        self.log = log
        self.warned = set()  # problems already said aloud this session

    def understand(self, audio: bytes, heard: str) -> Optional[str]:
        """The command the person meant, «» when the sound was not a command, None when Gemini is unreachable.

        A key Google refused or a used-up daily limit gives, once per session, «!» and a sentence for
        the person, so a broken key is heard instead of hiding in last-error.log.
        """
        body = {
            "contents": [{"parts": [
                {"text": PROMPT.format(heard=heard, phrases="; ".join(self.phrases))},
                {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(audio).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 500, "responseMimeType": "application/json"},
        }
        while self.models:
            model = self.models[0]
            try:
                answer = self.post(ENDPOINT.format(model), body, self.key)
            except HTTPError as error:
                if error.code == 404 and len(self.models) > 1:
                    self.models.pop(0)  # this model name is gone: the next one stays for the next phrases too
                    continue
                self.log("Gemini ответил ошибкой {}: {}".format(error.code, _error_text(error)))
                problem = PROBLEMS.get(error.code)
                if problem and problem not in self.warned:
                    self.warned.add(problem)
                    return "!" + problem
                return None
            except (OSError, ValueError) as error:
                self.log("Gemini недоступен: {}".format(error))
                return None
            command = _command(answer)
            if not command:
                self.log("Gemini не нашёл команды в «{}»".format(heard))
            return command
        return None


KEY_PROBLEM = "Ключ Gemini не подходит. Запустите установщик Веги ещё раз и вставьте новый ключ."
PROBLEMS = {400: KEY_PROBLEM, 401: KEY_PROBLEM, 403: KEY_PROBLEM,
            429: "Бесплатный лимит Gemini на сегодня закончился. До завтра понимаю сама."}


def _error_text(error: HTTPError) -> str:
    try:
        return json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")[:200]
    except (OSError, ValueError, AttributeError):
        return ""


def _command(answer: dict) -> str:
    """The commands one per line, and «say:» with Gemini's own spoken answer; «» when there is nothing."""
    try:
        text = answer["candidates"][0]["content"]["parts"][0]["text"]
        value = json.loads(text.strip().strip("`").replace("json\n", "", 1))
    except (KeyError, IndexError, TypeError, ValueError):
        return ""
    if not isinstance(value, dict):
        return ""
    commands = value.get("commands")
    if not isinstance(commands, list):
        commands = [value.get("command", "")]
    lines = [" ".join(str(command).lower().replace("ё", "е").split()).strip(" .!?,") for command in commands[:6]]
    lines = [line for line in lines if line]
    say = " ".join(str(value.get("say") or "").split())
    if say:
        lines.append("say:" + say[:600])
    return "\n".join(lines)


def start_gemini(config_dir: Path, log: Callable[[str], None]) -> Optional[GeminiHelper]:
    settings = load_key(config_dir)
    if settings is None:
        return None
    from .phrase_catalog import PHRASES
    return GeminiHelper(settings["key"], list(PHRASES), settings["model"], log=log)
