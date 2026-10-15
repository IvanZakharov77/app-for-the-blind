"""The «with Gemini» edition: a phrase Vega did not understand is sent, as sound, to Google Gemini.

Ivan, 2026-10-15: the installer offers a standard edition and one with Gemini; for the latter the
person pastes a free key from Google AI Studio, which the installer saves to gemini.json next to the
settings. The local recognizer still does everything it can: only a phrase it could not turn into a
command goes to Gemini, so the free daily limit lasts and Vega works without the internet as before.
"""

import base64
import io
import json
import wave
from pathlib import Path
from typing import Callable, Iterable, List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .online import _context

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
# Newest cheap model first; a name Google retired answers 404 and the next one is tried.
MODELS = ("gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash")
TIMEOUT = 6  # no internet or a slow one: Vega answers on her own instead of waiting
MAX_SECONDS = 15

PROMPT = """Ты — модуль понимания команд голосового помощника «Вега» для незрячих и пожилых людей.
В записи человек по-русски (иногда неразборчиво, с ошибками, своими словами) говорит одну команду.
Слова «привет», «Вега» в начале — это обращение, их отбрось.
Местный распознаватель услышал: «{heard}».
Выбери, что человек хотел, и ответь строго JSON: {{"command": "..."}}.
command — команда в нижнем регистре, ровно в таком виде, как в списке ниже. Где в образце «…», подставь
слова человека (название фильма, песни, запрос, текст заметки, имя файла, число).
Если в записи нет команды (посторонний разговор, телевизор, тишина), ответь {{"command": ""}}.

Образцы со свободными словами:
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
    pcm = b"".join(blocks)[-rate * 2 * MAX_SECONDS:]
    out = io.BytesIO()
    with wave.open(out, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(rate)
        sound.writeframes(pcm)
    return out.getvalue()


def _post(url: str, body: dict, key: str) -> dict:
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urlopen(request, timeout=TIMEOUT, context=_context()) as response:
        return json.loads(response.read().decode("utf-8"))


class GeminiHelper:
    def __init__(self, key: str, phrases: List[str], model: str = "",
                 post: Callable[[str, dict, str], dict] = _post, log: Callable[[str], None] = lambda message: None):
        self.key = key
        self.phrases = phrases
        self.models = [model] if model else list(MODELS)
        self.post = post
        self.log = log

    def understand(self, audio: bytes, heard: str) -> Optional[str]:
        """The command the person meant, «» when the sound was not a command, None when Gemini is unreachable."""
        body = {
            "contents": [{"parts": [
                {"text": PROMPT.format(heard=heard, phrases="; ".join(self.phrases))},
                {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(audio).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 200, "responseMimeType": "application/json"},
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
                return None
            except (OSError, ValueError) as error:
                self.log("Gemini недоступен: {}".format(error))
                return None
            return _command(answer)
        return None


def _error_text(error: HTTPError) -> str:
    try:
        return json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")[:200]
    except (OSError, ValueError, AttributeError):
        return ""


def _command(answer: dict) -> str:
    try:
        text = answer["candidates"][0]["content"]["parts"][0]["text"]
        value = json.loads(text.strip().strip("`").replace("json\n", "", 1))
        command = value.get("command", "") if isinstance(value, dict) else ""
    except (KeyError, IndexError, TypeError, ValueError):
        return ""
    return " ".join(str(command).lower().replace("ё", "е").split()).strip(" .!?,")


def start_gemini(config_dir: Path, log: Callable[[str], None]) -> Optional[GeminiHelper]:
    settings = load_key(config_dir)
    if settings is None:
        return None
    from .phrase_catalog import PHRASES
    return GeminiHelper(settings["key"], list(PHRASES), settings["model"], log=log)
