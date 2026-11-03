import tempfile
import unittest
from pathlib import Path

from voiceassist.core import Assistant
from voiceassist.personal import PersonalStore


class NumberedNotesTests(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.assistant = Assistant(personal=PersonalStore(folder / "personal.json"))
        for note in ("купить хлеб", "позвонить внуку", "оплатить свет"):
            self.assistant.personal.add_note(note)

    def say(self, text):
        return self.assistant.handle(text).message

    def test_list_reads_numbers(self):
        answer = self.say("какие заметки")
        self.assertIn("Всего заметок: 3", answer)
        self.assertIn("Заметка номер 1: купить хлеб", answer)
        self.assertIn("Заметка номер 3: оплатить свет", answer)

    def test_read_one_by_number(self):
        self.assertEqual(self.say("прочитай заметку номер два"), "Заметка номер 2: позвонить внуку.")
        self.assertEqual(self.say("заметка три"), "Заметка номер 3: оплатить свет.")

    def test_delete_by_number_after_yes(self):
        self.assertIn("Удалить заметку номер 1: купить хлеб?", self.say("удали заметку номер один"))
        self.assertIn("Удалила заметку номер 1", self.say("да"))
        self.assertEqual(self.assistant.personal.notes(), ["позвонить внуку", "оплатить свет"])

    def test_delete_said_differently(self):
        self.assertIn("номер 2", self.say("удалить заметку два"))
        self.say("нет")
        self.assertIn("номер 3", self.say("удали третью заметку"))

    def test_missing_number(self):
        self.assertIn("Заметки номер 7 нет", self.say("удали заметку номер семь"))

    def test_last_note_still_works(self):
        self.assertIn("последнюю", self.say("удали последнюю заметку").lower())
