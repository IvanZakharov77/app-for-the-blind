import sys
import unittest
from pathlib import Path

from voiceassist.understanding import canonical, closest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import make_phrase_catalog  # noqa: E402


class UnderstandingTests(unittest.TestCase):
    def test_spelling_and_verb_variants(self):
        self.assertEqual(canonical("что на флэшке"), "что на флешке")
        self.assertEqual(canonical("открыть номер один"), "открой номер один")
        self.assertEqual(canonical("а открой загрузки"), "открой загрузки")
        self.assertEqual(canonical("что есть на флешке"), "что на флешке")
        self.assertEqual(canonical("покажи флешку"), "открой флешку")
        self.assertEqual(canonical("какие флешки"), "какие флешки подключены")
        self.assertEqual(canonical("сколько места на второй флешки"), "сколько места на второй флешке")
        self.assertEqual(canonical("погода завтра"), "погода на завтра")
        for heard in ("открой папку загрузки", "открой папку загрузок", "открой папки загрузки", "открой загрузку", "открыть папку загрузки"):
            self.assertEqual(canonical(heard), "открой загрузки", heard)
        self.assertEqual(canonical("открой папку документов"), "открой документы")
        self.assertEqual(canonical("открой рабочий стол"), "открой рабочий стол")

    def test_existing_commands_and_dictation_stay(self):
        self.assertEqual(canonical("покажи рабочий стол"), "покажи рабочий стол")
        self.assertEqual(canonical("напиши открыть скобку"), "напиши открыть скобку")

    def test_closest_recovers_a_slightly_misheard_command(self):
        self.assertEqual(closest("какие флешка подключены"), "какие флешки подключены")
        self.assertEqual(closest("который чаще"), "который час")

    def test_closest_does_not_guess_from_noise(self):
        self.assertIsNone(closest("а что по телевизору"))
        self.assertIsNone(closest("да"))

    def test_catalog_matches_the_routers(self):
        from voiceassist.phrase_catalog import PHRASES
        self.assertEqual(list(PHRASES), make_phrase_catalog.harvest(),
                         "run: python tools/make_phrase_catalog.py")
        self.assertFalse([phrase for phrase in PHRASES if phrase.startswith("подтверждаю")])


if __name__ == "__main__":
    unittest.main()
