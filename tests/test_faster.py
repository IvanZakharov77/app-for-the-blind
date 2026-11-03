import io
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError

from voiceassist.gemini import GeminiHelper
from voiceassist.speech import FIRST_PART, chat_answer, speech_parts


def answer(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class ThinkingTests(unittest.TestCase):
    def test_thinking_is_switched_off(self):
        sent = []
        helper = GeminiHelper("k", [], "m", post=lambda url, body, key: sent.append(body) or answer("Привет!"))
        self.assertEqual(helper.chat(b"", "привет"), "Привет!")
        self.assertEqual(sent[0]["generationConfig"]["thinkingConfig"], {"thinkingBudget": 0})

    def test_model_that_refuses_is_asked_again_without_it(self):
        sent = []

        def post(url, body, key):
            sent.append(body)
            if "thinkingConfig" in body["generationConfig"]:
                raise HTTPError(url, 400, "bad", {}, io.BytesIO(b'{"error": {"message": "thinking"}}'))
            return answer("Хорошо.")
        helper = GeminiHelper("k", [], "m", post=post)
        self.assertEqual(helper.chat(b"", "как дела"), "Хорошо.")
        self.assertEqual(helper.chat(b"", "ещё"), "Хорошо.")
        self.assertEqual(len(sent), 3)  # refused once, then never sent again

    def test_real_bad_request_still_reported(self):
        def post(url, body, key):
            raise HTTPError(url, 400, "bad", {}, io.BytesIO(b"{}"))
        helper = GeminiHelper("k", [], "m", post=post)
        self.assertTrue(helper.chat(b"", "привет").startswith("!"))


class FirstPartTests(unittest.TestCase):
    def test_long_answer_starts_with_a_short_part(self):
        text = "Конечно, Игорь. " + "Сегодня хорошая погода, можно пойти погулять в парк и подышать воздухом. " * 4
        parts = speech_parts(text)
        self.assertEqual(parts[0], "Конечно, Игорь.")
        self.assertEqual(" ".join(parts), text.strip())

    def test_short_answer_whole(self):
        self.assertEqual(speech_parts("Да, конечно."), ["Да, конечно."])


class ChatWaitTests(unittest.TestCase):
    def test_slow_answer_says_one_moment(self):
        said = []

        class Stream:
            def stop(self): pass
            def start(self): pass

        class Speaker:
            def say(self, text): said.append(text)
            def runAndWait(self): pass

        release = threading.Event()

        class Chat:
            def chat(self, audio, phrase):
                release.wait(2)
                return "Ответ."
        timer = threading.Timer(0.2, release.set)
        timer.start()
        self.assertEqual(chat_answer(Stream(), Speaker(), Chat(), b"", "привет", wait=0.05), "Ответ.")
        self.assertEqual(said, ["Секунду."])


class PrepareTests(unittest.TestCase):
    def test_prepared_phrase_is_not_made_twice(self):
        from voiceassist.piper_voice import PiperSpeaker
        speaker = PiperSpeaker.__new__(PiperSpeaker)
        speaker.prepared, speaker.generation, speaker.timeout = {}, 0, 5
        made = []

        def synthesize(text):
            made.append(text)
            path = Path(self.id().replace(".", "_") + ".wav")
            return path
        speaker.synthesize = synthesize
        speaker.prepare("Вторая фраза.")
        speaker.prepared["Вторая фраза."][0].join()
        Path(self.id().replace(".", "_") + ".wav").write_bytes(b"x")
        try:
            speaker._made("Вторая фраза.")
            self.assertEqual(made, ["Вторая фраза."])
        finally:
            Path(self.id().replace(".", "_") + ".wav").unlink()
