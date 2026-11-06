"""What Vega remembers about the person between conversations with Gemini (Ivan, 2026-11-06:
«чтобы он помнил человека и прошлые разговоры, и каждый раз не начинать сначала»).

No extra requests to Gemini: it adds «ЗАПОМНИ: …» lines to its ordinary answers, Vega keeps them in
%APPDATA%\\VoiceAssist\\chat-memory.json together with the end of the last conversation, and gives a short
digest of both at the start of the next one. Nothing leaves the computer except inside the usual requests.
"""

import json
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

FILE = "chat-memory.json"
MAX_FACTS = 30        # the digest stays small: requests do not grow and the free limit counts requests anyway
MAX_FACT = 160
LAST_TURNS = 6        # exchanges of the previous conversation Gemini sees again
MARK = re.compile(r"^\s*(?:ЗАПОМНИ|ЗАПОМНИТЬ|Запомни|запомни)\s*[:：-]\s*(.+?)\s*$", re.M)

ASK = ("что ты обо мне помнишь", "что ты помнишь обо мне", "что ты обо мне знаешь", "что ты знаешь обо мне",
       "что ты про меня помнишь", "что ты про меня знаешь")
FORGET = ("забудь всё обо мне", "забудь все обо мне", "забудь всё про меня", "забудь все про меня",
          "забудь наши разговоры", "сотри память", "очисти память")

PROMPT = """
Если в разговоре человек сообщил о себе что-то важное и надолго (имя, родные, здоровье, привычки, интересы,
о чём вы договорились, что его тревожит), в самом конце ответа отдельной строкой напиши: «ЗАПОМНИ: …» —
коротко, от третьего лица, одним предложением. Эту строку человек не услышит. Не повторяй то, что уже есть
в памяти ниже, и не пиши такую строку, если нового ничего нет."""


def split_answer(text: str) -> Tuple[str, List[str]]:
    """Gemini's answer without the «ЗАПОМНИ:» lines, and those lines."""
    facts = [match.group(1).strip(" «»\"").rstrip(".") for match in MARK.finditer(text)]
    spoken = MARK.sub("", text)
    return " ".join(spoken.split()), [fact[:MAX_FACT] for fact in facts if fact]


class ChatMemory:
    def __init__(self, folder: Optional[Path], clock=time.time):
        self.path = folder / FILE if folder is not None else None
        self.clock = clock

    def _read(self) -> dict:
        if self.path is None:
            return {"facts": [], "last": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        facts = [fact for fact in data.get("facts", []) if isinstance(fact, str)]
        last = data.get("last") if isinstance(data.get("last"), dict) else {}
        return {"facts": facts, "last": last}

    def _write(self, data: dict) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self.path)

    def facts(self) -> List[str]:
        return self._read()["facts"]

    def add(self, facts: List[str]) -> None:
        if not facts:
            return
        data = self._read()
        known = {fact.lower() for fact in data["facts"]}
        for fact in facts:
            if fact.lower() not in known:
                data["facts"].append(fact)
                known.add(fact.lower())
        data["facts"] = data["facts"][-MAX_FACTS:]  # the oldest go first
        self._write(data)

    def keep_talk(self, turns: List[Tuple[str, str]]) -> None:
        """The end of the conversation, saved after every answer, so a closed Vega loses nothing."""
        if not turns:
            return
        data = self._read()
        data["last"] = {"time": self.clock(), "turns": [[person[:300], answer[:400]] for person, answer in turns[-LAST_TURNS:]]}
        self._write(data)

    def forget(self) -> None:
        if self.path is not None:
            try:
                self.path.unlink()
            except OSError:
                pass

    def digest(self) -> str:
        """For the system prompt: what is known about the person and how the last conversation went."""
        data = self._read()
        parts = []
        if data["facts"]:
            parts.append("Что ты помнишь о собеседнике по прошлым разговорам:\n- " + "\n- ".join(data["facts"]))
        turns = data["last"].get("turns") or []
        if turns:
            when = data["last"].get("time")
            ago = ""
            if isinstance(when, (int, float)):
                days = int((self.clock() - when) // 86400)
                ago = " (сегодня)" if days <= 0 else " (вчера)" if days == 1 else " ({} дн. назад)".format(days)
            lines = ["Человек: {}\nТы: {}".format(person, answer) for person, answer in turns]
            parts.append("Конец вашего прошлого разговора{}:\n{}".format(ago, "\n".join(lines)))
        if not parts:
            return ""
        return ("\n\n" + "\n\n".join(parts) + "\n\nПродолжай общение как давний знакомый: можешь вспомнить прошлое "
                "к месту, но не пересказывай его и не перечисляй, что помнишь, если не спросят.")

    def spoken(self) -> str:
        facts = self.facts()
        if not facts:
            return "Пока я ничего о вас не запомнила. Скажите: Вега, хочу поговорить, и расскажите о себе."
        return "Вот что я помню о вас: " + " ".join(fact.rstrip(".") + "." for fact in facts[-10:])
