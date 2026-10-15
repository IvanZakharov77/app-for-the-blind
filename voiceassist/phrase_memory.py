"""What this person says, learned from Gemini: the next time Vega understands it at once and offline.

Ivan, 2026-10-15: Vega should get better at understanding her user. Every phrase she could not
do herself but Gemini turned into a command that worked is kept in learned.json next to the
settings: «поставь высоцкого про коней» → «включи песню высоцкий кони привередливые».
"""

import json
import threading
from pathlib import Path
from typing import Dict, Optional

LIMIT = 2000  # the oldest phrases are forgotten first


def key_of(phrase: str) -> str:
    from .core import normalize, strip_assistant_name
    return strip_assistant_name(normalize(phrase))


class PhraseMemory:
    def __init__(self, path: Optional[Path]):
        self.path = path
        self.lock = threading.Lock()
        self.known: Dict[str, str] = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path else {}
            self.known = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.known = {}

    def recall(self, phrase: str) -> Optional[str]:
        return self.known.get(key_of(phrase))

    def learn(self, phrase: str, command: str) -> None:
        key = key_of(phrase)
        if not key or key == key_of(command):
            return
        with self.lock:
            self.known.pop(key, None)
            self.known[key] = command
            while len(self.known) > LIMIT:
                self.known.pop(next(iter(self.known)))
            self._save()

    def forget(self, phrase: str) -> None:
        with self.lock:
            if self.known.pop(key_of(phrase), None) is not None:
                self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.known, ensure_ascii=False, indent=0), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            pass
