"""Repeating and clock-time reminders (Ivan, 2026-11-01)."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from voiceassist.core import Assistant
from voiceassist.daily import describe, next_due, parse, parse_once
from voiceassist.personal import PersonalStore
from offwindows import setUpModule, tearDownModule  # noqa: F401


class ParseTests(unittest.TestCase):
    def test_phrases(self):
        self.assertEqual(parse("напоминай каждый день в девять и в двадцать один выпить таблетки"),
                         (tuple(range(7)), [(9, 0), (21, 0)], "выпить таблетки"))
        self.assertEqual(parse("напоминай выпить таблетки по будням в 8 30"), ((0, 1, 2, 3, 4), [(8, 30)], "выпить таблетки"))
        days, times, what = parse("напоминай по понедельникам и пятницам в 10 полить цветы")
        self.assertEqual(describe(days, times), "по понедельникам и пятницам в 10:00")
        self.assertIsNone(parse("напомни через десять минут позвонить"))

    def test_once_at_a_clock_time(self):
        now = datetime(2026, 11, 1, 15, 30)
        self.assertEqual(parse_once("напомни в шестнадцать принять лекарство", now), (datetime(2026, 11, 1, 16, 0), "принять лекарство"))
        self.assertEqual(parse_once("напомни в три часа дня принять лекарство", now)[0], datetime(2026, 11, 2, 15, 0))
        self.assertEqual(parse_once("напомни завтра в девять позвонить врачу", now)[0], datetime(2026, 11, 2, 9, 0))

    def test_next_due_skips_other_days(self):
        friday_evening = datetime(2026, 11, 6, 22, 0)
        self.assertEqual(next_due((0, 1, 2, 3, 4), [(8, 30)], friday_evening), datetime(2026, 11, 9, 8, 30))


class AssistantDailyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now = [datetime(2026, 11, 1, 8, 0)]
        self.assistant = Assistant(clock=lambda: self.now[0], current_directory=Path(self.folder.name),
                                   personal=PersonalStore(Path(self.folder.name) / "personal.json"))

    def tearDown(self):
        self.folder.cleanup()

    def test_pill_reminder_repeats_until_done_and_comes_back_tomorrow(self):
        asked = self.assistant.handle("Вега, напоминай каждый день в девять утра принять лекарство")
        self.assertIn("каждый день в 09:00", asked.message)
        self.assertIn("Буду напоминать", self.assistant.handle("да").message)
        self.now[0] = datetime(2026, 11, 1, 9, 0, 5)
        self.assertIn("Пора: принять лекарство", " ".join(self.assistant.poll_due()))
        self.now[0] += timedelta(minutes=10, seconds=1)
        self.assertIn("ещё раз", " ".join(self.assistant.poll_due()))
        self.assertEqual(self.assistant.handle("приняла").message, "Отлично, отметила.")
        self.now[0] += timedelta(minutes=10, seconds=1)
        self.assertEqual(self.assistant.poll_due(), ())
        self.now[0] = datetime(2026, 11, 2, 9, 0, 1)
        self.assertIn("Пора: принять лекарство", " ".join(self.assistant.poll_due()))
        self.assertIn("Постоянные: принять лекарство, каждый день в 09:00", self.assistant.handle("какие напоминания").message)
        self.assistant.handle("удали напоминание про лекарство")
        self.assertIn("Больше не напоминаю", self.assistant.handle("да").message)

    def test_done_without_a_reminder_is_not_taken(self):
        self.assertNotEqual(self.assistant.handle("готово").message, "Отлично, отметила.")

    def test_clock_time_reminder(self):
        self.assertIn("Напомнить сегодня в 15:00: принять лекарство", self.assistant.handle("напомни в три часа дня принять лекарство").message)
        self.assistant.handle("да")
        self.now[0] = datetime(2026, 11, 1, 15, 0, 1)
        self.assertIn("принять лекарство", " ".join(self.assistant.poll_due()))


if __name__ == "__main__":
    unittest.main()
