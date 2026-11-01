"""The full guide as a PDF with contents, opened by «Вега, открой инструкцию» (Ivan, 2026-11-01)."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from voiceassist.core import Assistant
from voiceassist.system import MANUAL_NAME, SystemController, SystemOutcome
from offwindows import setUpModule, tearDownModule  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def load_tool():
    spec = importlib.util.spec_from_file_location("make_manual", str(ROOT / "tools" / "make_manual.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManualPageTests(unittest.TestCase):
    def test_guide_has_cover_contents_and_tables(self):
        tool = load_tool()
        text = (ROOT / "ИНСТРУКЦИЯ.md").read_text(encoding="utf-8")
        page = tool.page(text, "9.9.9")
        self.assertIn("версия 9.9.9", page)
        self.assertNotIn("{{VERSION}}", page)
        self.assertIn('<section class="toc">', page)
        self.assertIn("<table>", page)
        self.assertIn("открой инструкцию", page)
        self.assertNotIn("**", page)
        self.assertNotIn("| ", page.split("</style>")[1])  # every table row was converted

    def test_inline_and_lists(self):
        tool = load_tool()
        body, toc = tool.convert("## Раз\n\n- **жирно** и `код`\n- два\n\n1. первый\n\n| А | Б |\n|---|---|\n| x | y |\n", "1")
        self.assertEqual(toc, [(2, "s0", "Раз")])
        self.assertIn("<ul><li><b>жирно</b> и <code>код</code></li>", body.replace("\n", ""))
        self.assertIn("<ol>", body)
        self.assertIn("<td>x</td><td>y</td>", body)


class OpenManualTests(unittest.TestCase):
    def test_voice_command_opens_the_pdf(self):
        calls = []

        class System:
            def open_manual(self):
                calls.append(True)
                return SystemOutcome("ok", "Открываю инструкцию.")

        assistant = Assistant(system=System())
        for phrase in ("открой инструкцию", "покажи инструкцию", "инструкция веги"):
            self.assertEqual(assistant.handle(phrase).status, "ok", phrase)
        self.assertEqual(len(calls), 3)

    def test_controller_launches_file_next_to_program(self):
        launched = []

        class Api:
            def launch(self, target): launched.append(target)

        controller = SystemController.__new__(SystemController)
        controller.api = Api()
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(controller.open_manual(Path(folder)).status, "missing")
            (Path(folder) / MANUAL_NAME).write_bytes(b"%PDF")
            self.assertEqual(controller.open_manual(Path(folder)).status, "ok")
        self.assertEqual(len(launched), 1)


class ContactTests(unittest.TestCase):
    def test_contact_and_report_name_the_email(self):
        assistant = Assistant()
        answer = assistant.handle("как связаться с разработчиком")
        self.assertEqual(answer.status, "ok")
        self.assertIn("джимейл", answer.message)
        assistant.report = lambda: Path("Vega-отчёт-1.txt")
        answer = assistant.handle("отправь отчет")
        self.assertIn("Vega-отчёт-1.txt", answer.message)
        self.assertIn("крафтио", answer.message)


class NewVersionNoteTests(unittest.TestCase):
    def test_said_once_per_version(self):
        import os
        from voiceassist.speech import NEW_VERSION_NOTE, new_version_note
        os.environ["VEGA_TEST_FROZEN"] = "1"
        try:
            with tempfile.TemporaryDirectory() as folder:
                self.assertEqual(new_version_note(Path(folder), "1.0"), NEW_VERSION_NOTE)
                self.assertEqual(new_version_note(Path(folder), "1.0"), "")
                self.assertEqual(new_version_note(Path(folder), "1.1"), NEW_VERSION_NOTE)
        finally:
            del os.environ["VEGA_TEST_FROZEN"]


if __name__ == "__main__":
    unittest.main()
