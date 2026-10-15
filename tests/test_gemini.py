import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from urllib.error import HTTPError

from voiceassist.core import Result
from voiceassist.gemini import GeminiHelper, load_key, wav_bytes
from voiceassist.speech import execute_spoken_command


def answer(command):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"command": command}, ensure_ascii=False)}]}}]}


class GeminiTests(unittest.TestCase):
    def test_key_file(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(load_key(Path(folder)))
            (Path(folder) / "gemini.json").write_text('﻿{"key": " AIza123 "}', encoding="utf-8")
            self.assertEqual(load_key(Path(folder)), {"key": "AIza123", "model": ""})
            (Path(folder) / "gemini.json").write_text('{"key": ""}', encoding="utf-8")
            self.assertIsNone(load_key(Path(folder)))

    def test_sound_is_a_wav(self):
        with wave.open(io.BytesIO(wav_bytes([b"\x01\x00" * 100, b"\x02\x00" * 100])), "rb") as sound:
            self.assertEqual((sound.getframerate(), sound.getnchannels(), sound.getnframes()), (8000, 1, 100))

    def test_understand_sends_sound_and_reads_the_command(self):
        sent = []

        def post(url, body, key):
            sent.append((url, body, key))
            return answer("Найди музыку Высоцкого.")
        helper = GeminiHelper("KEY", ["который час", "громче"], post=post)
        self.assertEqual(helper.understand(b"RIFF", "музыку высоцкого"), "найди музыку высоцкого")
        url, body, key = sent[0]
        self.assertIn("gemini-flash-lite-latest:generateContent", url)
        self.assertEqual(key, "KEY")
        parts = body["contents"][0]["parts"]
        self.assertIn("который час; громче", parts[0]["text"])
        self.assertIn("«музыку высоцкого»", parts[0]["text"])
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "audio/wav")

    def test_retired_model_and_errors(self):
        calls, logged = [], []

        def post(url, body, key):
            calls.append(url)
            if "flash-lite-latest" in url:
                raise HTTPError(url, 404, "gone", {}, io.BytesIO(b"{}"))
            if len(calls) == 2:
                return answer("")
            raise HTTPError(url, 429, "limit", {}, io.BytesIO(b'{"error": {"message": "quota"}}'))
        helper = GeminiHelper("KEY", [], post=post, log=logged.append)
        self.assertEqual(helper.understand(b"", ""), "")  # not a command
        self.assertIn("gemini-3.5-flash-lite", calls[1])
        self.assertTrue(helper.understand(b"", "").startswith("!Бесплатный лимит"))  # said aloud once
        self.assertIn("gemini-3.5-flash-lite", calls[2])  # the retired name is not tried again
        self.assertIn("429", logged[-1])
        self.assertIn("quota", logged[-1])
        self.assertIsNone(helper.understand(b"", ""))  # and not again

    def test_refused_key_is_said(self):
        def post(url, body, key):
            raise HTTPError(url, 400, "bad", {}, io.BytesIO(b'{"error": {"message": "API key not valid"}}'))
        helper = GeminiHelper("KEY", [], post=post)
        self.assertIn("Ключ Gemini не подходит", helper.understand(b"", ""))
        self.assertIsNone(helper.understand(b"", ""))

    def test_unknown_phrase_is_rescued(self):
        class Assistant:
            handled = []

            def handle(self, phrase):
                self.handled.append(phrase)
                return Result("ok", "Ищу.") if phrase == "найди музыку" else Result("unknown", "Не поняла.")

        class Speaker:
            def connect(self, event, callback): self.callback = callback; return "t"
            def disconnect(self, token): pass
            def say(self, message): self.said = message
            def startLoop(self, driver): pass
            def iterate(self): self.callback("", True)
            def endLoop(self): pass
            def runAndWait(self): pass

        class Stream:
            def read(self, frames): return b"", False
            def stop(self): pass
            def start(self): pass
        assistant, speaker = Assistant(), Speaker()
        result = execute_spoken_command(Stream(), speaker, assistant, "музыку", lambda audio: False, rescue=lambda: "найди музыку")
        self.assertEqual(result.message, "Ищу.")
        self.assertEqual(assistant.handled, ["музыку", "найди музыку"])
        result = execute_spoken_command(Stream(), speaker, assistant, "кофе", lambda audio: False, rescue=lambda: None)
        self.assertEqual(result.status, "unknown")
        # Ivan, 2026-10-15: Vega learns her user; a phrase Gemini explained works next time at once and offline.
        import tempfile
        from pathlib import Path
        from voiceassist.phrase_memory import PhraseMemory
        with tempfile.TemporaryDirectory() as folder:
            memory = PhraseMemory(Path(folder) / "learned.json")
            assistant.handled.clear()
            execute_spoken_command(Stream(), speaker, assistant, "поставь музычку", lambda audio: False,
                                   rescue=lambda: "найди музыку", memory=memory)
            asked = []
            again = PhraseMemory(Path(folder) / "learned.json")  # after a restart
            result = execute_spoken_command(Stream(), speaker, assistant, "вега поставь музычку", lambda audio: False,
                                            rescue=lambda: asked.append(1), memory=again)
            self.assertEqual(result.message, "Ищу.")
            self.assertEqual(asked, [])  # Gemini was not needed
            self.assertEqual(assistant.handled[-1], "найди музыку")
        # Gemini's plan: several steps in a row, and its own answer to a question.
        from voiceassist.speech import run_plan
        steps = []
        assistant.handle = lambda phrase: steps.append(phrase) or Result("ok", "Готово: " + phrase + ".")
        stopped = execute_spoken_command(Stream(), speaker, Assistant(), "открой блокнот и напиши привет", lambda audio: False,
                                         rescue=lambda: "найди музыку\nоткрой блокнот\nнапиши привет")
        self.assertEqual(stopped.message, "Ищу. Не поняла.")  # stops at the step that did not work
        planned = run_plan(assistant, "открой блокнот\nнапиши привет", Result("unknown", ""))
        self.assertEqual(steps, ["открой блокнот", "напиши привет"])
        self.assertEqual(planned.message, "Готово: открой блокнот. Готово: напиши привет.")
        self.assertEqual(run_plan(assistant, "say:Кошки живут лет пятнадцать.", Result("unknown", "")).message,
                         "Кошки живут лет пятнадцать.")
        # Ivan: any command that was not done goes to Gemini, not only «Не поняла».
        assistant.handle = lambda phrase: (Result("ok", "Ищу.") if phrase == "найди музыку"
                                           else Result("unavailable", "Нет такой папки."))
        self.assertEqual(execute_spoken_command(Stream(), speaker, assistant, "открой папку музыку", lambda audio: False,
                                                rescue=lambda: "найди музыку").message, "Ищу.")
        self.assertEqual(execute_spoken_command(Stream(), speaker, assistant, "открой папку", lambda audio: False,
                                                rescue=lambda: "открой папку").message, "Нет такой папки.")
        self.assertIn("Не расслышала", execute_spoken_command(Stream(), speaker, Assistant(), "", lambda audio: False,
                                                               rescue=lambda: "").message)


if __name__ == "__main__":
    unittest.main()
