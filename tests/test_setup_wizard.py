import tempfile
import unittest
from pathlib import Path

from voiceassist.settings import Settings
from voiceassist.setup_wizard import Wizard


class WizardTests(unittest.TestCase):
    def test_full_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(Path(folder, "settings.json"))
            answers = iter(["2", "2", "", "казань", "2", "хд резка", "https://rezka.ag", "", "д"])
            said, sites, voices = [], {}, []
            Wizard(settings, ask=lambda prompt: next(answers), say=said.append,
                   microphones=lambda: [(3, "Микрофон USB")], voices=lambda: ["Aleksandr"], save_voice=voices.append,
                   find_city=lambda name: {"name": "Казань", "latitude": 55.8, "longitude": 49.1},
                   save_site=lambda name, url: sites.__setitem__(name, url), autostart=lambda: True).run()
            reloaded = Settings(Path(folder, "settings.json"))
            self.assertEqual(reloaded.get("input_device"), 3)
            self.assertEqual(voices, ["Aleksandr"])
            self.assertEqual(reloaded.get("search_engine"), "гугл")
            self.assertEqual(reloaded.get("weather")["name"], "Казань")
            self.assertEqual(reloaded.get("news")["name"], "Лента.ру")
            self.assertEqual(sites, {"хд резка": "https://rezka.ag"})
            self.assertIn("Автозапуск включён.", said)

    def test_offline_city_does_not_stop_setup(self):
        settings = Settings(None)
        answers = iter(["", "москва", "5", ""])

        def offline(name):
            raise OSError("нет сети")
        said = []
        Wizard(settings, ask=lambda prompt: next(answers), say=said.append, find_city=offline).run()
        self.assertIsNone(settings.get("weather"))
        self.assertTrue(any("Нет связи" in line for line in said))


if __name__ == "__main__":
    unittest.main()
