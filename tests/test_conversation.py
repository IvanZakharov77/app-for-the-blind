import json
import unittest

from voiceassist.core import Result
from voiceassist.speech import GREETING, listen_forever


class Conversation:
    """A scripted room: each step is (seconds passed, phrase heard or None for silence)."""

    def __init__(self, steps, results=None):
        self.steps = list(steps)
        self.now = 0.0
        self.spoken, self.handled, self.asleep = [], [], 0
        self.results = results or {}

    def run(self):
        test = self

        class Speaker:
            def connect(self, event, callback): self.callback = callback; return "t"
            def disconnect(self, token): pass
            def say(self, message): test.spoken.append(message)
            def startLoop(self, driver): pass
            def iterate(self): self.callback("", True)
            def endLoop(self): pass
            def runAndWait(self): pass
            def stop(self): pass

        class Stream:
            def read(self, frames): return b"x", False
            def stop(self): pass
            def start(self): pass

        class Assistant:
            def poll_due(self): return ()
            def handle(self, phrase):
                test.handled.append(phrase)
                return test.results.get(phrase, Result("ok", "Ответ на «{}».".format(phrase)))

        class Recognizer:
            current = None
            def AcceptWaveform(self, audio):
                step = test.steps.pop(0)
                test.now += step[0]
                self.current = step[1]
                return step[1] is not None
            def Result(self): return json.dumps({"text": self.current}, ensure_ascii=False)
            def PartialResult(self): return '{"partial": ""}'
            def Reset(self): pass

        def asleep():
            test.asleep += 1
        listen_forever(Stream(), Speaker(), Assistant(), Recognizer(), lambda audio: False, [None], False,
                       should_stop=lambda: not test.steps, clock=lambda: test.now, asleep=asleep)
        return self


class ConversationTests(unittest.TestCase):
    def test_greeting_then_command(self):
        room = Conversation([(0, "привет вега"), (2, "который час")]).run()
        self.assertEqual(room.spoken[0], "Привет! Чем я могу помочь?")
        self.assertEqual(GREETING, "Привет! Чем я могу помочь?")
        self.assertEqual(room.handled, ["который час"])
        self.assertIn("Ответ на «который час».", room.spoken)

    def test_without_greeting_nothing_happens(self):
        room = Conversation([(0, "который час"), (1, "выключи компьютер")]).run()
        self.assertEqual(room.handled, [])
        self.assertEqual(room.spoken, [])

    def test_greeting_and_command_in_one_phrase(self):
        room = Conversation([(0, "привет вега какая погода")]).run()
        self.assertEqual(room.handled, ["какая погода"])
        self.assertNotIn("Привет! Чем я могу помочь?", room.spoken)

    def test_follow_up_needs_no_new_greeting_but_expires(self):
        room = Conversation([(0, "привет вега"), (1, "открой документы"), (2, "дальше"), (3, "вега открой второй"),
                             (7, None), (1, "удали всё")]).run()
        self.assertEqual(room.handled, ["открой документы", "дальше", "открой второй"])
        self.assertEqual(room.asleep, 1)

    def test_greeting_waits_for_the_command_only_a_few_seconds(self):
        room = Conversation([(0, "привет вега"), (9, None), (0, "который час")]).run()
        self.assertEqual(room.handled, [])
        self.assertEqual(room.asleep, 1)

    def test_overheard_phrase_in_follow_up_is_silent(self):
        room = Conversation([(0, "привет вега"), (1, "который час"), (1, "а что по телевизору"), (1, "какая погода")],
                            results={"а что по телевизору": Result("unknown", "Не понял.")}).run()
        self.assertEqual(room.handled, ["который час", "а что по телевизору"])
        self.assertNotIn("Не понял.", room.spoken)

    def test_unknown_right_after_greeting_is_answered(self):
        room = Conversation([(0, "привет вега"), (1, "сделай кофе")],
                            results={"сделай кофе": Result("unknown", "Не понял. Скажите: помоги.")}).run()
        self.assertIn("Не понял. Скажите: помоги.", room.spoken)

    def test_thanks_ends_the_conversation(self):
        room = Conversation([(0, "привет вега"), (1, "который час"), (1, "спасибо"), (1, "какая погода")]).run()
        self.assertEqual(room.handled, ["который час"])
        self.assertIn("Пожалуйста.", room.spoken)


if __name__ == "__main__":
    unittest.main()
