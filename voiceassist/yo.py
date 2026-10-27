"""Puts the letter «ё» back into text before Piper reads it.

Web pages, news and Gemini answers mostly write «е» for «ё». Piper's pronunciation dictionary
(espeak-ng) knows almost no «е» spellings of «ё» words, so «черный», «еще», «нашел» came out
as «че́рный», «еще́», «наше́л» (Ivan, 2026-10-27: «не знает как ставить ударения»).
«ё» is always stressed, so restoring it also fixes the stress of those words.

Only words where «е» in place of «ё» cannot be another word are changed («все»/«всё» stay).
The word list is eyo's «safe» dictionary (MIT, Denis Seleznev, data/yo-LICENSE.txt).
"""

import gzip
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

DICTIONARY = Path(__file__).parent / "data" / "yo.txt.gz"
WORD = re.compile(r"[А-Яа-яЁё]+")

_stems: Optional[Dict[str, List[Tuple[str, frozenset, bool]]]] = None


def _plain(text: str) -> str:
    return text.replace("ё", "е").replace("Ё", "Е")


def _load() -> Dict[str, List[Tuple[str, frozenset, bool]]]:
    """«stem with е» -> [(stem with ё, endings, is a name)]; kept compact instead of every word form."""
    stems: Dict[str, List[Tuple[str, frozenset, bool]]] = {}
    shared: Dict[str, frozenset] = {}  # most words share a few sets of endings
    try:
        lines = gzip.decompress(DICTIONARY.read_bytes()).decode("utf-8").splitlines()
    except (OSError, EOFError, ValueError):
        return stems
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        stem, _, rest = line.partition("(")
        endings = shared.setdefault(rest, frozenset(rest.rstrip(")").split("|")))
        stems.setdefault(_plain(stem.lower()), []).append((stem.lower(), endings, stem[:1].isupper()))
    return stems


def _restore_word(word: str) -> str:
    if "ё" in word or "Ё" in word or ("е" not in word and "Е" not in word):
        return word
    lower = word.lower()
    capital = word[:1].isupper()
    for cut in range(len(lower), 0, -1):
        for stem, endings, name in _stems.get(lower[:cut], ()):
            if lower[cut:] in endings and (capital or not name):
                found = stem + lower[cut:]
                # keep the original letters' case, only «е» -> «ё» changes
                return "".join(("Ё" if old == "Е" else "ё") if new == "ё" else old
                               for old, new in zip(word, found))
    return word


def restore(text: str) -> str:
    global _stems
    if _stems is None:
        _stems = _load()
    return WORD.sub(lambda match: _restore_word(match.group(0)), text)
