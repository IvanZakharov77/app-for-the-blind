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


class CommandRecognizerTests(unittest.TestCase):
    def test_command_grammar_rescues_unclear_speech(self):
        from voiceassist.speech import choose_heard
        self.assertEqual(choose_heard("привет вега откроют номер адин", "открой номер один"), "привет вега открой номер один")
        self.assertEqual(choose_heard("какие флешь подключены", "какие флешки подключены"), "какие флешки подключены")

    def test_free_words_and_clear_commands_are_kept(self):
        from voiceassist.speech import choose_heard
        self.assertEqual(choose_heard("открой номер один", "открой номер два"), "открой номер один")
        self.assertEqual(choose_heard("найди на ютубе группа крови", "найди фильм"), "найди на ютубе группа крови")
        self.assertEqual(choose_heard("а ты кто такой", "открой гугл"), "а ты кто такой")
        self.assertEqual(choose_heard("вот это да", "[unk] [unk]"), "вот это да")

    def test_recognizer_pair_reads_both_and_resets(self):
        import json
        from voiceassist.speech import CommandBiasedRecognizer

        class Fake:
            def __init__(self, text, endpoint):
                self.text, self.endpoint, self.resets = text, endpoint, 0
            def AcceptWaveform(self, audio): return self.endpoint
            def Result(self): return json.dumps({"text": self.text}, ensure_ascii=False)
            def FinalResult(self): return json.dumps({"text": ""})
            def PartialResult(self): return json.dumps({"partial": ""})
            def Reset(self): self.resets += 1

        commands = Fake("открой загрузки", True)
        pair = CommandBiasedRecognizer(Fake("открой загрузок папка", True), commands)
        self.assertTrue(pair.AcceptWaveform(b"x"))
        self.assertEqual(json.loads(pair.Result())["text"], "открой загрузки")
        self.assertEqual(commands.resets, 1)

    def test_grammar_covers_lists_folders_and_sites(self):
        from voiceassist.understanding import grammar_phrases
        phrases = grammar_phrases(["кинокрад"])
        for phrase in ("открой номер один", "третий", "открой загрузки", "открой сайт кинокрад", "привет вега", "какие флешки подключены"):
            self.assertIn(phrase, phrases)

    def test_help_question_with_greeting_and_mishearing(self):
        # Ivan, 2026-10-15: «привет вега что ты умеешь» said while Vega was already listening got «Не поняла».
        from voiceassist.core import Assistant
        for heard in ("привет вега что ты умеешь", "привет века что ты умеешь", "здравствуй в его что ты умеешь",
                      "привет что ты умеешь", "а что ты можешь", "что ты умеешь делать", "чего ты умеешь", "помощь"):
            result = Assistant().handle(heard)
            self.assertIn("Я умею вот что", result.message, heard)
        self.assertEqual(Assistant().handle("привет вега").message, "Привет! Чем я могу помочь?")
        self.assertIn("сейчас", Assistant().handle("привет вега который час").message)

    def test_only_the_end_was_heard(self):
        from voiceassist.core import Assistant
        message = Assistant().handle("музыку").message
        self.assertIn("«найди музыку»", message)
        self.assertIn("«включи музыку»", message)
        self.assertIn("«открой загрузки»", Assistant().handle("загрузки").message)
        self.assertIn("Скажите: помоги", Assistant().handle("кофе").message)


if __name__ == "__main__":
    unittest.main()
