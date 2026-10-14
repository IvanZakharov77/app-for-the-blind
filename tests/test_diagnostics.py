import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from voiceassist.core import Assistant
from voiceassist.diagnostics import CommandLog, write_report
from voiceassist.personal import PersonalStore
from offwindows import setUpModule, tearDownModule  # noqa: F401


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name, "VoiceAssist")
        self.config.mkdir()
        self.clock = lambda: datetime(2026, 10, 13, 18, 5)

    def tearDown(self):
        self.temp.cleanup()

    def test_log_keeps_commands_but_not_personal_text(self):
        log = CommandLog(self.config / "commands.log", self.clock)
        log.add("какая погода", "unavailable", "Нет связи с сервисом погоды.")
        log.add("напиши пароль от почты", "ok", "Напечатано: пароль от почты")
        log.add("запиши заметку купить лекарство", "needs_confirmation", "Записать заметку: купить лекарство?")
        text = (self.config / "commands.log").read_text(encoding="utf-8")
        self.assertIn("«какая погода» → unavailable", text)
        self.assertNotIn("пароль", text)
        self.assertNotIn("лекарство", text)
        self.assertIn("«напиши …»", text)

    def test_report_collects_errors_commands_and_settings_without_the_bridge_token(self):
        (self.config / "settings.json").write_text('{"speech_rate": 1}', encoding="utf-8")
        (self.config / "last-error.log").write_text("Микрофон недоступен\n", encoding="utf-8")
        (self.config / "bridge.json").write_text('{"token": "секрет"}', encoding="utf-8")
        CommandLog(self.config / "commands.log", self.clock).add("открой ютуб", "ok", "Открыт YouTube.")
        path = write_report(self.config, Path(self.temp.name), self.clock)
        self.assertEqual(path.name, "Vega-отчёт-20261013-1805.txt")
        text = path.read_text(encoding="utf-8-sig")
        for expected in ("Отчёт Vega", "Микрофон недоступен", "открой ютуб", '"speech_rate": 1'):
            self.assertIn(expected, text)
        self.assertNotIn("секрет", text)
        self.assertNotIn("bridge.json", text)

    def test_voice_command_saves_the_report(self):
        saved = []
        assistant = Assistant(clock=self.clock, personal=PersonalStore(Path(self.temp.name, "p.json")),
                              report=lambda: saved.append(1) or Path(self.temp.name, "Vega-отчёт-20261013-1805.txt"))
        result = assistant.handle("помощник сохрани отчёт для помощи")
        self.assertEqual(result.status, "ok")
        self.assertIn("рабочем столе", result.message)
        self.assertEqual(saved, [1])


if __name__ == "__main__":
    unittest.main()
