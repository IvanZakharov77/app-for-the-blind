"""Text as Piper should read it: units in words and «ё» put back.

Piper's dictionary (espeak-ng) skips «°» and a minus («-1» is «один», «−22» is English «mainus»),
spells «м/с» letter by letter and says «40 процент».
"""

import re

from .numbers import plural
from .yo import restore

NUMBER = r"([+\-−]?\d+(?:[.,]\d+)?)"
UNITS = (
    (r"\s*°\s*[CС]?(?![А-Яа-яЁёA-Za-z])", ("градус", "градуса", "градусов")),
    (r"\s*%", ("процент", "процента", "процентов")),
    (r"\s*м/с(?![А-Яа-яЁё])", ("метр в секунду", "метра в секунду", "метров в секунду")),
    (r"\s*км/ч(?![А-Яа-яЁё])", ("километр в час", "километра в час", "километров в час")),
)
MINUS = re.compile(r"(?:(?<=\s)|(?<=^)|(?<=\())[-−](?=\d)")
PATTERNS = tuple((re.compile(NUMBER + unit), forms) for unit, forms in UNITS)


def _units(text: str) -> str:
    for pattern, forms in PATTERNS:
        def spoken(match, forms=forms):
            number = match.group(1)
            if "." in number or "," in number:  # «2,5 процента»
                return "{} {}".format(number.replace(".", ","), forms[1])
            return "{} {}".format(number, plural(abs(int(number.lstrip("+-−"))), forms))
        text = pattern.sub(spoken, text)
    return text


def prepare(text: str) -> str:
    return restore(MINUS.sub("минус ", _units(text)))
