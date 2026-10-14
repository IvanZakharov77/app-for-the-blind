import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from voiceassist.instance import SingleInstance
from voiceassist.speech import choose_russian_voice, keep_listening, listen_forever, report_voice_failure


def voice(identifier, name, languages=()):
    return SimpleNamespace(id=identifier, name=name, languages=list(languages))


class VoiceChoiceTests(unittest.TestCase):
    def test_rhvoice_is_found_by_sapi_language_not_by_name(self):
        voices = [voice("TTS_MS_EN-US_ANNA", "Microsoft Anna - English (United States)"),
                  voice("RHVoice-Aleksandr", "Aleksandr")]
        chosen = choose_russian_voice(voices, russian_ids=["rhvoice-aleksandr"])
        self.assertEqual(chosen.name, "Aleksandr")

    def test_configured_name_wins(self):
        voices = [voice("a", "Microsoft Irina Desktop - Russian"), voice("b", "Elena")]
        self.assertEqual(choose_russian_voice(voices, "elena").id, "b")
        with self.assertRaises(RuntimeError):
            choose_russian_voice(voices, "Pavel")

    def test_name_fallback_and_honest_failure(self):
        self.assertEqual(choose_russian_voice([voice("x", "Microsoft Irina Desktop - Russian")]).id, "x")
        with self.assertRaises(RuntimeError):
            choose_russian_voice([voice("en", "Microsoft Anna - English")])


class RecoveryTests(unittest.TestCase):
    def test_microphone_is_reopened_after_failure_and_recovery_is_reported(self):
        calls, failures, sleeps = [], [], []

        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): return False

        def open_stream():
            calls.append("open")
            if len(calls) == 1:
                raise RuntimeError("PortAudio: device unavailable")
            return Stream()

        sessions = []
        keep_listening(open_stream, lambda stream, recovered: sessions.append(recovered),
                       lambda error, attempt: failures.append((str(error), attempt)),
                       sleep=sleeps.append, clock=lambda: 0.0)
        self.assertEqual(calls, ["open", "open"])
        self.assertEqual(failures, [("PortAudio: device unavailable", 1)])
        self.assertEqual(sessions, [True])
        self.assertEqual(len(sleeps), 1)

    def test_failure_inside_session_is_retried_and_limit_stops_with_error(self):
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): return False

        def broken(stream, recovered):
            raise OSError("sleep/resume broke the stream")

        attempts = []
        with self.assertRaises(RuntimeError):
            keep_listening(Stream, broken, lambda error, attempt: attempts.append(attempt),
                           sleep=lambda _: None, clock=lambda: 0.0, max_failures=3)
        self.assertEqual(attempts, [1, 2, 3])

    def test_recovered_session_says_microphone_works_again(self):
        spoken = []

        class Speaker:
            def connect(self, event, callback): self.callback = callback; return "t"
            def disconnect(self, token): pass
            def say(self, message): spoken.append(message)
            def startLoop(self, driver): pass
            def iterate(self): self.callback("", True)
            def endLoop(self): pass

        class Stream:
            def read(self, frames): return b"", False

        class Assistant:
            def poll_due(self): return ()

        class Recognizer:
            def AcceptWaveform(self, audio): return False

        stops = iter([False, True])
        listen_forever(Stream(), Speaker(), Assistant(), Recognizer(), lambda audio: False, [None], True,
                       should_stop=lambda: next(stops))
        self.assertIn("Микрофон снова работает. Вега готова.", spoken)

    def test_log_keeps_previous_entries(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "last-error.log")
            report_voice_failure("первая", path, beep=lambda: None)
            report_voice_failure("вторая", path, beep=lambda: None)
            text = path.read_text(encoding="utf-8")
            self.assertIn("первая", text)
            self.assertIn("вторая", text)


class SingleInstanceTests(unittest.TestCase):
    def test_second_copy_is_refused(self):
        class API:
            def __init__(self): self.names, self.closed = set(), []
            def create(self, name):
                existed = name in self.names
                self.names.add(name)
                return object(), existed
            def close(self, handle): self.closed.append(handle)

        api = API()
        self.assertTrue(SingleInstance(api).acquire())
        self.assertFalse(SingleInstance(api).acquire())
        self.assertEqual(len(api.closed), 1)


if __name__ == "__main__":
    unittest.main()
