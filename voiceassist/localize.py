"""Vega's answers in the chosen language (Ivan, 2026-11-15).

Vega's logic builds her answers in Russian; just before she speaks, the answer is translated with the
language's catalog voiceassist/locales/<code>.json: {"Russian text with {} for each inserted part":
"the same in that language"}. A whole answer is looked up first, then each sentence. An inserted part
(a file name, a contact, a number) is kept as it is unless the catalog knows it too. Sentences the catalog
does not know are spoken as they are and written to untranslated-<code>.txt, so they can be added.
"""

import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[«\"(A-ZА-ЯЁІЇЄҐ0-9])")
PLACE = re.compile(r"\{[^{}]*\}")  # «{}», «{:02d}», «{name}»: one inserted part
LOCALES = Path(__file__).resolve().parent / "locales"
RUSSIAN_ONLY = set("ыэъё")
NATIVE = {"uk": set("іїєґ")}  # letters that show a long text (a book page, a headline) is already in the language


class Catalog:
    def __init__(self, entries: Dict[str, str], missing: Callable[[str], None] = lambda text: None, native: str = ""):
        self.native = set(native)
        self.exact: Dict[str, str] = {}
        self.templates: List[Tuple[re.Pattern, str, int]] = []
        self.missing = missing
        for source, target in entries.items():
            if source[-1:].isspace() and source.strip():  # «По часам компьютера сейчас » + the time: a beginning
                source, target = source.rstrip() + " {}", target.rstrip() + " {}"
            source, target = PLACE.sub("{}", source).strip(), PLACE.sub("{}", target).strip()
            if "{}" in source:
                pattern = "^" + "(.+?)".join(re.escape(part) for part in source.split("{}")) + "$"
                self.templates.append((re.compile(pattern, re.S), target, source.count("{}")))
            else:
                self.exact[source] = target
        # the longest fixed text first: «Открыта папка {}» wins over «{}»
        self.templates.sort(key=lambda item: -len(item[0].pattern.replace("(.+?)", "")))

    def _one(self, text: str, depth: int = 0) -> Optional[str]:
        stripped = text.strip()
        if not stripped:
            return text
        if stripped in self.exact:
            return self.exact[stripped]
        for pattern, target, count in self.templates:
            match = pattern.match(stripped)
            if match:
                parts = [self._part(value, depth) for value in match.groups()]
                return _fill(target, parts)
        return None

    def _part(self, value: str, depth: int) -> str:
        if depth >= 2:
            return value
        found = self._one(value, depth + 1)
        if found is None and "; " in value:  # «Например: Который час; Какое сегодня число»: each one
            return "; ".join(self._piece(piece, depth + 1) for piece in value.split("; "))
        return value if found is None else found

    def _piece(self, piece: str, depth: int) -> str:
        found = self._one(piece, depth)
        if found is None and piece[-1:] in "?.!":
            found = self._one(piece[:-1], depth)
            found = None if found is None else found + piece[-1]
        return piece if found is None else found

    def already_native(self, text: str) -> bool:
        """A book, a page or the news read in the language itself: spoken as it is, no lookup."""
        if not self.native or len(text) < 120:
            return False
        words = re.findall(r"\w+", text.lower())
        native = sum(1 for word in words if self.native & set(word))
        russian = sum(1 for word in words if RUSSIAN_ONLY & set(word))
        return native > 2 * russian + 2

    def translate(self, text: str) -> str:
        if self.already_native(text):
            return text
        found = self._one(text)
        if found is not None:
            return found
        sentences = SENTENCE.split(text.strip())
        if len(sentences) == 1:
            self.missing(text)
            return text
        said = []
        for sentence in sentences:
            one = self._one(sentence)
            if one is None:
                self.missing(sentence)
                one = sentence
            said.append(one)
        return " ".join(said)


def _fill(target: str, parts: List[str]) -> str:
    pieces = target.split("{}")
    said = pieces[0]
    for index, piece in enumerate(pieces[1:]):
        said += (parts[index] if index < len(parts) else "") + piece
    return said


def load(code: str, missing: Callable[[str], None] = lambda text: None, folder: Path = LOCALES) -> Optional[Catalog]:
    if code == "ru":
        return None
    path = folder / (code + ".json")
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = {}
    return Catalog(entries, missing, "".join(NATIVE.get(code, ())))


def missing_log(path: Path) -> Callable[[str], None]:
    seen = set()

    def note(text: str) -> None:
        text = text.strip()
        if not text or text in seen or len(seen) > 2000:
            return
        seen.add(text)
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError:
            pass
    return note
