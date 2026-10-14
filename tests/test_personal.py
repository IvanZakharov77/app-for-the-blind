import tempfile
import unittest
from pathlib import Path

from voiceassist.personal import PersonalStore, TimerBook, calculate


class PersonalTests(unittest.TestCase):
    def test_timer_uses_monotonic_clock_and_fires_once(self):
        now = [100.0]
        timers = TimerBook(clock=lambda: now[0])
        timers.add(60)
        now[0] = 159.0
        self.assertEqual(timers.pop_due(), 0)
        now[0] = 160.0
        self.assertEqual(timers.pop_due(), 1)
        self.assertEqual(timers.pop_due(), 0)

    def test_note_persists_across_store_instances(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "personal.json")
            PersonalStore(path).add_note("купить хлеб")
            self.assertEqual(PersonalStore(path).notes(), ["купить хлеб"])

    def test_reminder_persists_and_is_consumed_once(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "personal.json")
            PersonalStore(path).add_reminder(1000.0, "позвонить")
            reopened = PersonalStore(path)
            self.assertEqual(reopened.reminders(), ["позвонить"])
            self.assertEqual(reopened.pop_due_reminders(999.0), [])
            self.assertEqual(reopened.pop_due_reminders(1000.0), ["позвонить"])
            self.assertEqual(PersonalStore(path).pop_due_reminders(1001.0), [])

    def test_calculator_uses_limited_grammar(self):
        self.assertEqual(calculate("12 плюс 7"), "19")
        self.assertEqual(calculate("2 километра в метры"), "2000 метров")
        with self.assertRaises(ValueError):
            calculate("__import__ os")


if __name__ == "__main__":
    unittest.main()
