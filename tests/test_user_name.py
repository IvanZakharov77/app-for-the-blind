"""Vega calls one person by name: «Привет, Игорь!» (Ivan, 2026-11-01)."""

import tempfile
import unittest
from pathlib import Path

from voiceassist import user_name
from voiceassist.core import Assistant
from offwindows import setUpModule, tearDownModule  # noqa: F401


class UserNameTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.assistant = Assistant()
        self.assistant.config_dir = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_said_name_is_kept_and_used(self):
        self.assertIn("Вега, меня зовут", self.assistant.handle("как меня зовут").message)
        answer = self.assistant.handle("меня зовут игорь петрович")
        self.assertIn("Игорь Петрович", answer.message)
        self.assertEqual(user_name.load(Path(self.folder.name)), "Игорь Петрович")
        self.assertEqual(self.assistant.handle("как меня зовут").message, "Вас зовут Игорь Петрович.")
        self.assertEqual(self.assistant.handle("привет вега").message, "Привет, Игорь Петрович! Чем я могу помочь?")
        self.assistant.handle("забудь мое имя")
        self.assertEqual(user_name.load(Path(self.folder.name)), "")

    def test_installer_file_with_bom(self):
        (Path(self.folder.name) / user_name.FILE).write_bytes("﻿игорь\r\n".encode("utf-8"))
        self.assertEqual(self.assistant.user_name(), "Игорь")

    def test_other_name_words(self):
        for phrase in ("называй меня оля", "зови меня оля", "мое имя оля"):
            self.assistant.handle(phrase)
            self.assertEqual(self.assistant.user_name(), "Оля", phrase)


if __name__ == "__main__":
    unittest.main()
