"""Forgiving understanding: Vosk often hears a command a little differently from the fixed phrase.

canonical() rewrites the common variants before routing («что на флэшке» → «что на флешке»,
«открыть номер один» → «открой номер один»). closest() is the last resort for a phrase no router
took: the catalog phrase it most resembles, when the resemblance is strong and unambiguous.
"""

import difflib
import re
from typing import Iterable, Optional

from .phrase_catalog import PHRASES

# Whole-word spellings Vosk produces for the same word.
WORD_FIXES = {
    "флэшка": "флешка", "флэшки": "флешки", "флэшке": "флешке", "флэшку": "флешку", "флэшкой": "флешкой",
    "флешь": "флешка", "флэш": "флеш",
    "открыть": "открой", "откройте": "открой", "открою": "открой", "открывай": "открой", "открои": "открой",
    "отрой": "открой", "открый": "открой",
    "прочитать": "прочитай", "прочти": "прочитай", "прочитайте": "прочитай",
    "включить": "включи", "включите": "включи",
    "выбрать": "выбери", "выберите": "выбери",
    "извлечь": "извлеки", "извлеките": "извлеки",
}

# After these the rest is the person's own text (a note, a search, dictation): only the first word is fixed.
FREE_TEXT = ("напиши", "напечатай", "введи", "запиши", "напомни", "найди", "переведи", "сколько будет", "мой город", "я живу")

# Leading words that add nothing: «а открой», «ну какая погода», «пожалуйста который час».
FILLER_START = ("а ", "ну ", "так ", "пожалуйста ", "слушай ", "скажи пожалуйста ")

# Phrase-level variants, applied after the word fixes.
PHRASE_FIXES = (
    (r"^что (?:есть|лежит|находится|записано) (на|в) ", r"что \1 "),
    (r"^какие (?:у меня )?флешки(?: есть)?$", "какие флешки подключены"),
    (r"^(?:какие|что за) (?:диски|накопители) подключены$", "какие съемные диски подключены"),
    (r"^открой (?:мою |мои )?(?:флешку|флешка)$", "открой флешку"),
    (r"^(?:флешка|флешку|моя флешка)$", "что на флешке"),
    (r"^покажи (флешку|документы|загрузки|изображения|музыку|мои видео|папку .+)$", r"открой \1"),
    # Known folders in any form Vosk hears: «открой папку загрузок», «открой папки загрузки».
    (r"^(?:открой |покажи )?(?:мой|мои|мою|наш|этот) компьютер[а-я]*$", "открой мой компьютер"),
    (r"^открой (?:папк[аиуе] )?(?:загрузк[аиуе]|загрузок|закрузк[аиуе])$", "открой загрузки"),
    (r"^открой (?:папк[аиуе] )?(?:мои )?документ(?:ы|ов)$", "открой документы"),
    (r"^открой (?:папк[аиуе] )?рабоч(?:ий|его|ем) стол(?:а|е)?$", "открой рабочий стол"),
    (r"^открой (?:папк[аиуе] )?(?:изображени[яей]|картинки|фотографии)$", "открой изображения"),
    (r"^открой (?:папк[аиуе] )?музык[аиу]$", "открой музыку"),
    (r"^открой (?:папк[аиуе] )?(?:мои )?видео$", "открой мои видео"),
    (r"\bна (первой |второй |третьей )?флешк[а-я]*", r"на \1флешке"),
    (r"^погода (?:на )?завтра$", "погода на завтра"),
    (r"^(?:ещё|еще) раз$", "повтори"),
)


def canonical(command: str) -> str:
    text = command
    changed = True
    while changed:
        changed = False
        for filler in FILLER_START:
            if text.startswith(filler) and len(text) > len(filler):
                text, changed = text[len(filler):], True
    words = text.split()
    if not words:
        return text
    words[0] = WORD_FIXES.get(words[0], words[0])
    if not text.startswith(FREE_TEXT):
        words = words[:1] + [WORD_FIXES.get(word, word) for word in words[1:]]
    text = " ".join(words)
    for pattern, replacement in PHRASE_FIXES:
        text = re.sub(pattern, replacement, text)
    return text


def closest(command: str, catalog: Optional[Iterable[str]] = None, cutoff: float = 0.82) -> Optional[str]:
    """The catalog phrase the command most resembles, or None when nothing is clearly close."""
    catalog = list(_KNOWN if catalog is None else catalog)
    cut = cut_start(command, catalog)
    if cut is not None:
        return cut
    if len(command) < 6 or " " not in command:
        return None  # one short word is too little to guess from
    scored = sorted(((difflib.SequenceMatcher(None, command, phrase).ratio(), phrase) for phrase in catalog), reverse=True)
    if not scored or scored[0][0] < cutoff:
        return None
    if len(scored) > 1 and scored[1][0] > scored[0][0] - 0.03 and scored[1][1] != scored[0][1]:
        return None  # two phrases fit equally well: asking is better than guessing
    return scored[0][1]


# Commands that carry the person's own words: the command-only recognizer must not replace those words.
OPEN_ENDED = FREE_TEXT + ("найди на", "поищи", "ищи", "включи песню", "воспроизведи", "запомни сайт", "сохрани сайт",
                          "переименуй", "создай папку", "найди фильм", "найди файл", "найди папку")

NUMBER_WORDS = ("один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять")
ORDINAL_WORDS = ("первый", "второй", "третий", "четвертый", "пятый", "шестой", "седьмой", "восьмой", "девятый", "десятый")


def grammar_phrases(extra: Iterable[str] = ()) -> list:
    """Everything Vega can be told without free words, for the command-only recognizer: the catalog,
    list choices («открой номер два», «третий»), folders, sites and the wake phrase."""
    phrases = set(PHRASES)
    phrases.update(("привет вега", "здравствуй вега", "здравствуйте вега", "вега", "да", "нет", "дальше", "еще",
                    "повтори", "отмена", "помоги", "спасибо", "стоп", "остановись", "хватит", "что в папке",
                    "открой мой компьютер", "мой компьютер", "что на флешке", "открой флешку", "какие флешки подключены"))
    for number, ordinal in zip(NUMBER_WORDS, ORDINAL_WORDS):
        phrases.update(("открой номер " + number, "номер " + number, ordinal, "открой " + ordinal,
                        "прочитай новость номер " + number, "переключись на окно " + number, "включи номер " + number))
    from .help_menu import CATEGORIES
    for index, (name, _stems, _commands) in enumerate(CATEGORIES):
        phrases.update(("категория " + name, "категория " + name.split()[0], "категория " + NUMBER_WORDS[index], name.split()[0]))
    phrases.update(("включи мою музыку", "найди музыку на компьютере", "включи музыку", "найди музыку", "найди фотографии", "найди видео", "найди документы", "найди книги"))
    phrases.update(("хочу поговорить", "давай поговорим", "поговори со мной", "давай поболтаем", "закончим разговор"))
    phrases.update(("что ты умеешь", "что ты можешь", "что умеешь", "что ты умеешь делать", "помощь", "все категории"))
    for folder in ("документы", "загрузки", "рабочий стол", "изображения", "музыку", "мои видео"):
        phrases.update(("открой " + folder, "открой папку " + folder))
    for name in extra:
        phrases.update(("открой " + name, "открой сайт " + name))
    return sorted(phrases)


def cut_start(command: str, catalog: Iterable[str]) -> Optional[str]:
    """The person often starts speaking while Vega is still finishing her answer, and the recognizer
    gets the phrase without its beginning: «ой номер один», «и флешки подключены» (commands.log,
    2026-10-14). A known phrase that ends with what was heard, and is not much longer, is the one meant."""
    if len(command) < 8:
        return None
    found = {phrase for phrase in catalog
             if phrase != command and phrase.endswith(command) and len(command) >= 0.55 * len(phrase)}
    return found.pop() if len(found) == 1 else None


def closest_name(heard: str, names: dict, cutoff: float = 0.75) -> Optional[str]:
    """«кино крот» → «кино крад»: the site name Vosk heard almost right. names maps each spelling to
    what it opens; spellings of the same site never make the choice ambiguous."""
    scored = sorted(((difflib.SequenceMatcher(None, heard, name).ratio(), name) for name in names if name), reverse=True)
    if not scored or scored[0][0] < cutoff:
        return None
    best = scored[0]
    rivals = [name for score, name in scored[1:] if score > best[0] - 0.05 and names[name] != names[best[1]]]
    return None if rivals else best[1]


COMMAND_VERBS = ("найди", "включи", "открой", "прочитай", "покажи", "закрой", "выключи", "поставь", "скопируй", "извлеки")


def endings_of(heard: str, limit: int = 3) -> list:
    """Commands that end with what was heard, when the beginning was lost: «музыку» → «найди музыку»,
    «включи музыку», «открой музыку». Empty when there are none or too many to offer."""
    if not heard or len(heard) < 4:
        return []
    found = sorted({phrase for phrase in _KNOWN if phrase != heard and phrase.endswith(" " + heard)
                    and len(phrase.split()) == len(heard.split()) + 1 and phrase.split()[0] in COMMAND_VERBS}, key=len)
    return found if 0 < len(found) <= limit else []


def is_known_command(command: str) -> bool:
    return command in _KNOWN or command.startswith(OPEN_ENDED)


_KNOWN = frozenset(grammar_phrases())
