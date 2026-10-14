"""Small local personal-assistant functions, independent of audio."""

import json
import copy
import re
import time
from pathlib import Path
from typing import Callable, List, Optional


class TimerBook:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.deadlines: List[float] = []

    def add(self, seconds: int) -> None:
        if not 1 <= seconds <= 24 * 3600:
            raise ValueError("Таймер должен быть от 1 секунды до 24 часов.")
        self.deadlines.append(self.clock() + seconds)

    def remaining(self) -> List[float]:
        now = self.clock()
        return sorted(deadline - now for deadline in self.deadlines if deadline > now)

    def cancel_all(self) -> int:
        count = len(self.deadlines)
        self.deadlines = []
        return count

    def pop_due(self) -> int:
        now = self.clock()
        due = sum(deadline <= now for deadline in self.deadlines)
        self.deadlines = [deadline for deadline in self.deadlines if deadline > now]
        return due


class PersonalStore:
    def __init__(self, path: Path):
        self.path = path
        self._cache = None

    def _read(self) -> dict:
        if self._cache is not None:
            return copy.deepcopy(self._cache)
        if not self.path.exists():
            self._cache = {"notes": [], "reminders": []}
            return copy.deepcopy(self._cache)
        with self.path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
            raise ValueError("Файл заметок повреждён.")
        if not isinstance(data.get("reminders", []), list):
            raise ValueError("Файл напоминаний повреждён.")
        data.setdefault("reminders", [])
        self._cache = data
        return copy.deepcopy(data)

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        temporary.replace(self.path)
        self._cache = copy.deepcopy(data)

    def notes(self) -> List[str]:
        return list(self._read()["notes"])

    def add_note(self, note: str) -> None:
        note = note.strip()
        if not note or len(note) > 500:
            raise ValueError("Заметка должна содержать от 1 до 500 символов.")
        data = self._read()
        data["notes"].append(note)
        self._write(data)

    def delete_last_note(self) -> Optional[str]:
        data = self._read()
        if not data["notes"]:
            return None
        removed = data["notes"].pop()
        self._write(data)
        return removed

    def clear_notes(self) -> int:
        data = self._read()
        count = len(data["notes"])
        if count:
            data["notes"] = []
            self._write(data)
        return count

    def add_reminder(self, due_epoch: float, text: str) -> None:
        text = text.strip()
        if not text or len(text) > 500:
            raise ValueError("Текст напоминания должен содержать от 1 до 500 символов.")
        data = self._read()
        data["reminders"].append({"due": due_epoch, "text": text})
        self._write(data)

    def reminders(self) -> List[str]:
        return [item["text"] for item in self._read()["reminders"]]

    def pop_due_reminders(self, now_epoch: float) -> List[str]:
        return [item["text"] for item in self.pop_due_items(now_epoch)]

    def pop_due_items(self, now_epoch: float) -> List[dict]:
        """Due reminders with their times, so ones missed while switched off can be named as missed."""
        data = self._read()
        due = [item for item in data["reminders"] if item["due"] <= now_epoch]
        if due:
            data["reminders"] = [item for item in data["reminders"] if item["due"] > now_epoch]
            self._write(data)
        return due

    def upcoming(self) -> List[dict]:
        return sorted(self._read()["reminders"], key=lambda item: item["due"])

    def delete_reminder(self, due_epoch: float, text: str) -> bool:
        data = self._read()
        kept = [item for item in data["reminders"] if not (item["due"] == due_epoch and item["text"] == text)]
        if len(kept) == len(data["reminders"]):
            return False
        data["reminders"] = kept
        self._write(data)
        return True


# stem → (quantity, factor to the base unit, spoken forms for 1 / 2 / 5)
UNITS = (
    ("миллиметр", "length", 0.001, ("миллиметр", "миллиметра", "миллиметров")),
    ("сантиметр", "length", 0.01, ("сантиметр", "сантиметра", "сантиметров")),
    ("километр", "length", 1000.0, ("километр", "километра", "километров")),
    ("метр", "length", 1.0, ("метр", "метра", "метров")),
    ("миллиграмм", "mass", 0.000001, ("миллиграмм", "миллиграмма", "миллиграммов")),
    ("килограмм", "mass", 1.0, ("килограмм", "килограмма", "килограммов")),
    ("грамм", "mass", 0.001, ("грамм", "грамма", "граммов")),
    ("центнер", "mass", 100.0, ("центнер", "центнера", "центнеров")),
    ("тонн", "mass", 1000.0, ("тонна", "тонны", "тонн")),
    ("секунд", "time", 1.0, ("секунда", "секунды", "секунд")),
    ("минут", "time", 60.0, ("минута", "минуты", "минут")),
    ("час", "time", 3600.0, ("час", "часа", "часов")),
    ("сут", "time", 86400.0, ("сутки", "суток", "суток")),
    ("дн", "time", 86400.0, ("день", "дня", "дней")),
    ("день", "time", 86400.0, ("день", "дня", "дней")),
    ("недел", "time", 604800.0, ("неделя", "недели", "недель")),
    ("литр", "volume", 1.0, ("литр", "литра", "литров")),
    ("миллилитр", "volume", 0.001, ("миллилитр", "миллилитра", "миллилитров")),
)


def _unit(word: str):
    for entry in sorted(UNITS, key=lambda item: -len(item[0])):
        if word.startswith(entry[0]):
            return entry
    return None


def convert(phrase: str) -> Optional[str]:
    """«2 километра в метры», «3 часа в минуты»; None when the phrase is not a conversion."""
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?) (\S+) в (\S+)", phrase)
    if not match:
        return None
    source, target = _unit(match.group(2)), _unit(match.group(3))
    if source is None or target is None:
        return None
    if source[1] != target[1]:
        raise ValueError("Эти величины нельзя перевести друг в друга.")
    value = float(match.group(1).replace(",", ".")) * source[2] / target[2]
    text = "{:.6g}".format(value)
    forms = target[3]
    if value != int(value):
        word = forms[1]
    else:
        number = int(value) % 100
        word = forms[2] if 11 <= number <= 14 else forms[0] if number % 10 == 1 else forms[1] if 2 <= number % 10 <= 4 else forms[2]
    return "{} {}".format(text.replace(".", ","), word)


def calculate(expression: str) -> str:
    phrase = expression.strip().lower().replace("ё", "е")
    converted = convert(phrase)
    if converted is not None:
        return converted
    match = re.fullmatch(r"(-?\d+(?:[.,]\d+)?) (плюс|минус|умножить на|умножь на|разделить на|раздели на|поделить на|подели на) (-?\d+(?:[.,]\d+)?)", phrase)
    if not match:
        raise ValueError("Поддерживаются простые числа и четыре арифметические операции.")
    left = float(match.group(1).replace(",", "."))
    right = float(match.group(3).replace(",", "."))
    operation = match.group(2)
    if operation == "плюс":
        result = left + right
    elif operation == "минус":
        result = left - right
    elif operation in ("умножить на", "умножь на"):
        result = left * right
    else:
        if right == 0:
            raise ValueError("На ноль делить нельзя.")
        result = left / right
    return "{:g}".format(result)
