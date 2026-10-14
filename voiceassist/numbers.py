"""Russian number words as Vosk writes them ("двадцать пять") to numbers."""

import re
from typing import Optional

_UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "одну": 1, "одно": 1, "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
_THOUSAND = ("тысяча", "тысячи", "тысяч", "тысячу")
_HALVES = {"полтора": 1.5, "полторы": 1.5}


def is_number_word(word: str) -> bool:
    return word in _UNITS or word in _TENS or word in _HUNDREDS or word in _THOUSAND


def words_to_number(text: str) -> Optional[float]:
    """Parse "125", "сто двадцать пять", "полторы"; None when it is not a number."""
    text = text.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return float(text.replace(",", "."))
    if text in _HALVES:
        return _HALVES[text]
    words = text.split()
    if not words or not all(is_number_word(word) for word in words):
        return None
    total = 0
    current = 0
    last_rank = None
    for word in words:
        if word in _THOUSAND:
            if total:
                return None
            total = (current or 1) * 1000
            current = 0
            last_rank = None
            continue
        if word in _HUNDREDS:
            rank, value = 3, _HUNDREDS[word]
        elif word in _TENS:
            rank, value = 2, _TENS[word]
        else:
            rank, value = (1 if _UNITS[word] < 10 else 2), _UNITS[word]
        if last_rank is not None and rank >= last_rank:
            return None
        current += value
        last_rank = rank
    return float(total + current)


def replace_number_words(text: str) -> str:
    """Replace each run of number words with digits: "двенадцать плюс семь" → "12 плюс 7"."""
    result = []
    run = []

    def flush():
        # "семь тридцать" is two numbers: take the longest prefix that parses, then continue.
        start = 0
        while start < len(run):
            for end in range(len(run), start, -1):
                value = words_to_number(" ".join(run[start:end]))
                if value is not None:
                    result.append("{:g}".format(value))
                    start = end
                    break
            else:
                result.append(run[start])
                start += 1
        run.clear()

    for word in text.split():
        if is_number_word(word):
            run.append(word)
        else:
            flush()
            result.append(word)
    flush()
    return " ".join(result)


def format_size(byte_count: int) -> str:
    """Size for speech: "14,2 гигабайта", not "15032385536 байт"."""
    for limit, forms in ((1024 ** 3, ("гигабайт", "гигабайта", "гигабайт")),
                         (1024 ** 2, ("мегабайт", "мегабайта", "мегабайт")),
                         (1024, ("килобайт", "килобайта", "килобайт"))):
        if byte_count >= limit:
            value = byte_count / limit
            if value < 10:
                rounded = round(value, 1)
                if rounded != int(rounded):
                    return "{} {}".format(str(rounded).replace(".", ","), forms[1])
                return "{} {}".format(int(rounded), plural(int(rounded), forms))
            whole = int(round(value))
            return "{} {}".format(whole, plural(whole, forms))
    return "{} {}".format(byte_count, plural(byte_count, ("байт", "байта", "байт")))


def plural(count: int, forms) -> str:
    """forms: (1 файл, 2 файла, 5 файлов)."""
    if count % 10 == 1 and count % 100 != 11:
        return forms[0]
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return forms[1]
    return forms[2]


_ORDINAL_STEMS = (
    ("одиннадцат", 11), ("двенадцат", 12), ("тринадцат", 13), ("четырнадцат", 14), ("пятнадцат", 15),
    ("шестнадцат", 16), ("семнадцат", 17), ("восемнадцат", 18), ("девятнадцат", 19), ("двадцат", 20),
    ("перв", 1), ("втор", 2), ("трет", 3), ("четверт", 4), ("пят", 5), ("шест", 6),
    ("седьм", 7), ("восьм", 8), ("девят", 9), ("десят", 10))
# Words that may follow a position without making it a title: «второй номер по списку», «третье видео».
_INDEX_FILLER = frozenset((
    "номер", "под", "номером", "по", "списку", "из", "списка", "в", "списке", "пункт", "вариант", "результат",
    "видео", "ролик", "фильм", "трек", "песню", "песня", "ссылку", "кнопку", "поле", "вкладку", "файл", "папку",
    "заголовок", "серию", "пожалуйста",
))


def parse_index(text: str) -> Optional[int]:
    """"второй", "номер два", "3", "пятую по списку" → list position; None for titles like «первый мститель»."""
    words = [word for word in text.split() if word not in _INDEX_FILLER]
    if not words or len(words) > 3:
        return None
    if len(words) == 1:
        for stem, value in _ORDINAL_STEMS:
            if words[0].startswith(stem) and not is_number_word(words[0]):
                return value
    value = words_to_number(" ".join(words))
    if value is not None and value == int(value) and value >= 1:
        return int(value)
    return None


PUNCTUATION = (
    ("вопросительный знак", "?"), ("восклицательный знак", "!"), ("с новой строки", "\n"), ("новая строка", "\n"),
    ("новый абзац", "\n"), ("двоеточие", ":"), ("точка с запятой", ";"), ("многоточие", "..."), ("запятая", ","),
    ("точка", "."), ("тире", " —"), ("открыть скобку", " ("), ("закрыть скобку", ")"), ("кавычки", "\""),
)


def format_dictation(spoken: str) -> str:
    """Vosk text → typed text: spoken punctuation, capital letters after a sentence end."""
    text = " " + spoken.strip() + " "
    for words, mark in PUNCTUATION:
        text = text.replace(" " + words + " ", mark + " ")
    text = text.replace(" \n ", "\n").replace("\n ", "\n").strip(" ")
    result = []
    capital = True
    for char in text:
        if capital and char.isalpha():
            result.append(char.upper())
            capital = False
        else:
            result.append(char)
        if char in ".?!\n":
            capital = True
    return "".join(result).rstrip(" ")
