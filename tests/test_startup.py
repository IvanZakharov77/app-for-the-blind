import unittest
from pathlib import Path

from voiceassist.startup import StartupManager, startup_command


class FakeRegistry:
    def __init__(self):
        self.value = None

    def read(self):
        return self.value

    def write(self, value):
        self.value = value

    def delete(self):
        self.value = None


class StartupTests(unittest.TestCase):
    def test_command_quotes_paths_and_selects_voice_mode(self):
        command = startup_command(Path(r"C:\Program Files\Voice Assist\VoiceAssist.exe"), Path(r"C:\Models\Russian Small"), frozen=True)
        self.assertIn('"C:\\Program Files\\Voice Assist\\VoiceAssist.exe"', command)
        self.assertIn('--voice', command)
        self.assertIn('"C:\\Models\\Russian Small"', command)

    def test_install_verifies_readback_and_remove(self):
        registry = FakeRegistry()
        manager = StartupManager(registry)
        self.assertTrue(manager.install('"C:\\VoiceAssist.exe" --voice'))
        self.assertEqual(registry.read(), '"C:\\VoiceAssist.exe" --voice')
        self.assertTrue(manager.remove())
        self.assertIsNone(registry.read())

    def test_run_key_limit_rejected(self):
        with self.assertRaises(ValueError):
            StartupManager(FakeRegistry()).install("x" * 261)


if __name__ == "__main__":
    unittest.main()
