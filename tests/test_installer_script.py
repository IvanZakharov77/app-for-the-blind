import re
import unittest
from pathlib import Path

ISS = (Path(__file__).resolve().parent.parent / "installer" / "VoiceAssist.iss").read_text(encoding="utf-8-sig")


class SilentUpdateTests(unittest.TestCase):
    """Ivan, 2026-11-11: after the 0.7.19 update people met installer windows and the AI checkbox again."""

    def test_update_never_shows_the_ai_warning(self):
        skip = re.search(r"function ShouldSkipPage.*?\nend;", ISS, re.S).group(0)
        self.assertIn("WarnPage.ID) and (VegaUpdate() or (SavedKey() <> ''))", skip)

    def test_silent_install_is_never_stopped_by_a_question(self):
        click = re.search(r"function NextButtonClick.*?\nend;", ISS, re.S).group(0)
        first = click.index("if WizardSilent() or VegaUpdate() then")
        self.assertLess(first, click.index("MsgBox"))
