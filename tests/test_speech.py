import unittest

from voiceassist.speech import extract_final_text, strip_wake_word, speak_with_mic_paused, speak_interruptibly, StopWordDetector, report_voice_failure, format_outcome, execute_spoken_command
from voiceassist.core import Result
from pathlib import Path
from tempfile import TemporaryDirectory
from offwindows import setUpModule, tearDownModule  # noqa: F401


class SpeechTests(unittest.TestCase):
    def test_started_speech_stops_when_stop_phrase_is_heard(self):
        events = []

        class Stream:
            def read(self, frames):
                events.append("listen")
                return b"stop", False

        class Speaker:
            def connect(self, event, callback):
                self.callback = callback
                return "token"
            def disconnect(self, token): events.append("disconnect")
            def say(self, message): events.append("say")
            def startLoop(self, driver): events.append("loop")
            def iterate(self): events.append("iterate")
            def stop(self): events.append("stop"); self.callback("", False)
            def endLoop(self): events.append("end")

        interrupted = speak_interruptibly(Stream(), Speaker(), "Длинный ответ", lambda audio: audio == b"stop")
        self.assertTrue(interrupted)
        self.assertLess(events.index("say"), events.index("listen"))
        self.assertLess(events.index("listen"), events.index("stop"))
        self.assertIn("end", events)

    def test_stop_word_detector_requires_wake_word_and_command(self):
        class Recognizer:
            def __init__(self): self.payload = ''
            def Reset(self): self.payload = ''
            def AcceptWaveform(self, audio): self.payload = audio.decode(); return True
            def Result(self): return '{"text": "' + self.payload + '"}'
        detector = StopWordDetector(Recognizer())
        self.assertFalse(detector("замолчи".encode()))
        self.assertTrue(detector("Вега, замолчи".encode()))
        for phrase in ("стоп", "остановись", "хватит", "Вега, стоп"):
            self.assertTrue(detector(phrase.encode()), phrase)
        self.assertFalse(detector("открой стоп лист".encode()))

    def test_stop_word_detector_uses_partial_result_during_speech(self):
        class Recognizer:
            def Reset(self): pass
            def AcceptWaveform(self, audio): return False
            def PartialResult(self): return '{"partial": "вега замолчи"}'
        self.assertTrue(StopWordDetector(Recognizer())(b"audio"))

    def test_only_final_recognition_text_is_used(self):
        self.assertEqual(extract_final_text('{"text": "помощник который час"}'), "помощник который час")
        self.assertEqual(extract_final_text('{"partial": "выключи"}'), "")

    def test_unexpected_recognition_json_is_ignored(self):
        self.assertEqual(extract_final_text('[]'), "")
        self.assertEqual(extract_final_text('null'), "")

    def test_wake_word_required(self):
        self.assertEqual(strip_wake_word("Привет, Вега, который час"), "который час")
        self.assertEqual(strip_wake_word("привет века который час"), "который час")
        self.assertEqual(strip_wake_word("привет вега"), "")
        self.assertEqual(strip_wake_word("помощник который час"), "")
        self.assertEqual(strip_wake_word("который час"), "")

    def test_speech_pauses_microphone_to_avoid_its_own_voice(self):
        events = []

        class Stream:
            def stop(self):
                events.append("stop")

            def start(self):
                events.append("start")

        class Speaker:
            def say(self, message):
                events.append(message)

            def runAndWait(self):
                events.append("spoken")

        speak_with_mic_paused(Stream(), Speaker(), "готов")
        self.assertEqual(events, ["stop", "готов", "spoken", "start"])

    def test_voice_failure_logs_and_signals_without_claiming_ready(self):
        with TemporaryDirectory() as root:
            signals = []
            path = Path(root, "error.log")
            report_voice_failure("микрофон недоступен", path, beep=lambda: signals.append(True))
            self.assertEqual(signals, [True])
            self.assertIn("микрофон недоступен", path.read_text(encoding="utf-8"))

    def test_answers_are_natural_but_honest(self):
        self.assertEqual(format_outcome("который час", Result("ok", "Сейчас 14:00.")), "Сейчас 14:00.")
        self.assertTrue(format_outcome("открой сайт", Result("error", "Chrome не найден.")).startswith("Не получилось."))
        unverified = format_outcome("открой сайт", Result("unverified", "Загрузка не проверена."))
        self.assertNotIn("Готово", unverified)
        self.assertNotIn("Команда «", format_outcome("x", Result("ok", "Да.")))

    def test_started_copy_is_not_spoken_as_completed_or_failed(self):
        message = format_outcome("подтверждаю копирование", Result("in_progress", "Копирование начато."))
        self.assertEqual(message, "Копирование начато.")

    def test_copy_plan_is_spoken_as_awaiting_confirmation(self):
        message = format_outcome("скопируй всё", Result("needs_confirmation", "План составлен. Скажите: подтверждаю копирование."))
        self.assertIn("подтверждаю", message)

    @staticmethod
    def _fakes(events, stop=False):
        class Stream:
            def read(self, frames): return b"silence", False
            def stop(self): events.append("mic off")
            def start(self): events.append("mic on")
        class Speaker:
            def connect(self, event, callback): self.callback = callback; return "token"
            def disconnect(self, token): pass
            def say(self, message): events.append(message)
            def runAndWait(self): pass
            def startLoop(self, driver): pass
            def iterate(self): self.callback("", True)
            def endLoop(self): pass
            def stop(self): pass
        class Detector:
            def reset(self): pass
            def __call__(self, audio): return stop
        return Stream(), Speaker(), Detector()

    def test_quick_command_answers_without_filler(self):
        events = []
        stream, speaker, detector = self._fakes(events)
        class Assistant:
            def handle(self, phrase):
                events.append("action")
                return Result("ok", "Время 14:00.")
        execute_spoken_command(stream, speaker, Assistant(), "который час", detector, acknowledge=lambda: events.append("tone"))
        self.assertEqual([e for e in events if not e.startswith("mic")], ["tone", "action", "Время 14:00."])

    def test_slow_command_says_one_second(self):
        import time
        import voiceassist.speech as speech
        events = []
        stream, speaker, detector = self._fakes(events)
        class Assistant:
            def handle(self, phrase):
                time.sleep(0.2)
                events.append("action")
                return Result("ok", "Готово.")
        old, speech.SLOW_SECONDS = speech.SLOW_SECONDS, 0.05
        try:
            execute_spoken_command(stream, speaker, Assistant(), "найди фотографии", detector)
        finally:
            speech.SLOW_SECONDS = old
        self.assertLess(events.index("Секунду."), events.index("action"))

    def test_voice_reports_action_exception_and_restores_microphone(self):
        events = []
        stream, speaker, detector = self._fakes(events)
        class Assistant:
            def handle(self, phrase): raise RuntimeError("secret detail")
        result = execute_spoken_command(stream, speaker, Assistant(), "пример", detector)
        self.assertEqual(result.status, "error")
        self.assertTrue(any(item.startswith("Не получилось") for item in events))
        self.assertFalse(any("secret detail" in item for item in events))
        self.assertIn("mic on", events)


if __name__ == "__main__":
    unittest.main()


class StartSpeakerTests(unittest.TestCase):
    def test_broken_voice_falls_back_then_retries(self):
        from voiceassist.speech import start_speaker
        said, logged, waits = [], [], []

        class Voice:
            def __init__(self, works):
                self.works = works

            def say(self, text):
                said.append(text)

            def runAndWait(self):
                if not self.works:
                    raise RuntimeError("Failed to play sound")
        tries = iter([False, False, False, True])
        speaker = start_speaker(lambda: Voice(next(tries)), lambda: Voice(next(tries)), logged.append, wait=waits.append)
        self.assertTrue(speaker.works)
        self.assertEqual(len(logged), 3)
        self.assertEqual(len(waits), 1)

    def test_gives_up_with_a_reason(self):
        from voiceassist.speech import start_speaker

        def broken():
            raise OSError("no sound device")
        with self.assertRaises(RuntimeError) as caught:
            start_speaker(broken, broken, lambda message: None, attempts=2, wait=lambda seconds: None)
        self.assertIn("no sound device", str(caught.exception))


class LongSpeechTests(unittest.TestCase):
    def test_long_answer_is_read_in_parts_and_stopped_in_a_pause(self):
        # Ivan, 2026-10-27: during a long folder list «хватит» was not heard.
        from voiceassist.speech import speak_interruptibly, speech_parts
        text = " ".join("{}. Папка номер {};".format(index, index) for index in range(1, 40))
        parts = speech_parts(text)
        self.assertGreater(len(parts), 2)
        self.assertTrue(all(len(part) <= 200 for part in parts))
        self.assertEqual(speech_parts("Коротко."), ["Коротко."])
        said = []

        class Speaker:
            def connect(self, event, callback): self.callback = callback; return "t"
            def disconnect(self, token): pass
            def say(self, message): said.append(message)
            def startLoop(self, driver): pass
            def iterate(self): self.callback("", True)  # each part ends at once
            def endLoop(self): pass
            def stop(self): pass

        reads = []

        class Stream:
            def read(self, frames):
                reads.append(1)
                return (b"stop" if len(reads) == 2 else b"x"), False
        self.assertTrue(speak_interruptibly(Stream(), Speaker(), text, lambda audio: audio == b"stop"))
        self.assertEqual(said, parts[:1])  # stopped in the pause after the first part
