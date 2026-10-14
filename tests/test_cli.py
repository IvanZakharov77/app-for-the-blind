import io
import unittest
from unittest.mock import patch

from voiceassist.cli import run


class CLITests(unittest.TestCase):
    def test_text_mode_starts_and_answers_until_exit(self):
        output = io.StringIO()
        with patch("builtins.input", side_effect=["Который час?", "выход"]):
            run(output=output, check_platform=False)
        self.assertIn("Вега готова", output.getvalue())
        self.assertIn("По часам компьютера", output.getvalue())


if __name__ == "__main__":
    unittest.main()
