import json
import unittest

from voiceassist.core import Result
from voiceassist.speech import GREETING, listen_forever
from offwindows import setUpModule, tearDownModule  # noqa: F401


class Conversation:
    """A scripted room: each step is (seconds passed, phrase heard or None for silence)."""

    def __init__(self, steps, results=None):
        self.steps = list(steps)
        self.now = 0.0
        self.spoken, self.handled, self.asleep = [], [], 0
        self.results = results or {}

    def run(self, greet=False):
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
            partial = ""
            def AcceptWaveform(self, audio):
                step = test.steps.pop(0)
                test.now += step[0]
                if step[1] is not None and step[1].startswith("~"):  # still talking: only a partial result
                    self.current, self.partial = None, step[1][1:]
                    return False
                self.current, self.partial = step[1], ""
                return step[1] is not None
            def Result(self): return json.dumps({"text": self.current}, ensure_ascii=False)
            def PartialResult(self): return json.dumps({"partial": self.partial}, ensure_ascii=False)
            def Reset(self): pass

        def asleep():
            test.asleep += 1
        listen_forever(Stream(), Speaker(), Assistant(), Recognizer(), lambda audio: False, [None], False,
                       should_stop=lambda: not test.steps, clock=lambda: test.now, asleep=asleep, greet=greet)
        return self


class ConversationTests(unittest.TestCase):
    def test_at_start_vega_greets_first_and_takes_a_command(self):
        room = Conversation([(1, "который час")]).run(greet=True)
        self.assertEqual(room.spoken[0], "Привет! Чем я могу помочь?")
        self.assertEqual(room.handled, ["который час"])

    def test_greeting_then_command(self):
        room = Conversation([(0, "привет вега"), (1, None), (2, "который час")]).run()
        self.assertEqual(room.spoken[0], "Привет! Чем я могу помочь?")
        self.assertEqual(GREETING, "Привет! Чем я могу помочь?")
        self.assertEqual(room.handled, ["который час"])
        self.assertIn("Ответ на «который час».", room.spoken)

    def test_command_after_a_pause_is_not_cut_by_the_greeting(self):
        # Ivan, 2026-10-15: «Привет, Вега … найди музыку» was heard as «музыку»: she greeted over the first word.
        room = Conversation([(0, "привет вега"), (0.5, "~найди"), (0.5, "найди музыку")]).run()
        self.assertNotIn(GREETING, room.spoken)
        self.assertEqual(room.handled, ["найди музыку"])

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
                             (16, None), (1, "удали всё")]).run()
        self.assertEqual(room.handled, ["открой документы", "дальше", "открой второй"])
        self.assertEqual(room.asleep, 1)

    def test_greeting_waits_for_the_command_only_a_few_seconds(self):
        room = Conversation([(0, "привет вега"), (1, None), (11, None), (0, "который час")]).run()
        self.assertEqual(room.handled, [])
        self.assertEqual(room.asleep, 1)

    def test_misheard_follow_up_is_answered_once_and_window_stays(self):
        room = Conversation([(0, "привет вега"), (1, "открой загрузки"), (1, "открыла номер адин"), (10, "открой номер один")],
                            results={"открыла номер адин": Result("unknown", "Не поняла: «открыла номер адин».")}).run()
        self.assertEqual(room.handled, ["открой загрузки", "открыла номер адин", "открой номер один"])
        self.assertIn("Не поняла: «открыла номер адин».", room.spoken)
        self.assertEqual(room.asleep, 0)

    def test_two_overheard_phrases_in_follow_up_end_the_conversation(self):
        unknown = Result("unknown", "Не понял.")
        room = Conversation([(0, "привет вега"), (1, "который час"), (1, "а что по телевизору"), (1, "ну и дела"), (1, "какая погода")],
                            results={"а что по телевизору": unknown, "ну и дела": unknown}).run()
        self.assertEqual(room.handled, ["который час", "а что по телевизору", "ну и дела"])
        self.assertEqual(room.spoken.count("Не понял."), 1)
        self.assertEqual(room.asleep, 1)

    def test_unknown_right_after_greeting_is_answered(self):
        room = Conversation([(0, "привет вега"), (1, "сделай кофе")],
                            results={"сделай кофе": Result("unknown", "Не понял. Скажите: помоги.")}).run()
        self.assertIn("Не понял. Скажите: помоги.", room.spoken)

    def test_thanks_ends_the_conversation(self):
        room = Conversation([(0, "привет вега"), (1, "который час"), (1, "спасибо"), (1, "какая погода")]).run()
        self.assertEqual(room.handled, ["который час"])
        self.assertIn("Пожалуйста.", room.spoken)


class EchoTests(unittest.TestCase):
    def test_own_words_at_the_start_are_dropped(self):
        from voiceassist.speech import strip_echo
        self.assertEqual(strip_echo("чем я могу помочь найди музыку", GREETING), "найди музыку")
        self.assertEqual(strip_echo("помочь найди музыку", GREETING), "найди музыку")
        self.assertEqual(strip_echo("найди музыку", GREETING), "найди музыку")
        self.assertEqual(strip_echo("могу помочь", GREETING), "")
        self.assertEqual(strip_echo("что в папке что в папке", "Чтобы послушать, скажите: что в папке."), "что в папке")

    def test_audio_at_the_end_of_speech_is_kept_for_the_recognizer(self):
        from voiceassist.speech import speak_interruptibly

        class Speaker:
            def __init__(self): self.left = 6
            def connect(self, event, callback): self.callback = callback; return "t"
            def disconnect(self, token): pass
            def say(self, message): pass
            def startLoop(self, driver): pass
            def iterate(self):
                self.left -= 1
                if self.left == 0:
                    self.callback("", True)
            def endLoop(self): pass
            def stop(self): pass

        class Stream:
            count = 0
            def read(self, frames):
                Stream.count += 1
                return bytes([Stream.count]), False
        tail = []
        self.assertFalse(speak_interruptibly(Stream(), Speaker(), "Привет", lambda audio: False, tail))
        self.assertEqual(tail, [bytes([2]), bytes([3]), bytes([4]), bytes([5])])


if __name__ == "__main__":
    unittest.main()
