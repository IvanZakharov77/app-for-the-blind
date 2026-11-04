import unittest

from voiceassist.speech import speak_interruptibly


class Stream:
    def __init__(self):
        self.events = []

    def stop(self):
        self.events.append("stop")

    def start(self):
        self.events.append("start")

    def read(self, size):
        self.events.append("read")
        return b"\0" * size, False


class Speaker:
    def __init__(self, quiet):
        self.quiet_mic, self.checked, self.said, self.callback = None, False, [], None
        self.quiet = quiet

    def check_output(self):
        self.checked = True
        self.quiet_mic = self.quiet
        return self.quiet

    def connect(self, event, callback):
        self.callback = callback
        return event

    def disconnect(self, token):
        pass

    def say(self, text):
        self.said.append(text)

    def startLoop(self, use_driver_loop=True):
        pass

    def iterate(self):
        self.callback(None, True)

    def endLoop(self):
        pass

    def stop(self):
        pass


class QuietMicTests(unittest.TestCase):
    def test_card_that_cannot_play_while_recording_speaks_with_mic_off(self):
        stream, speaker = Stream(), Speaker(True)
        self.assertFalse(speak_interruptibly(stream, speaker, "Сейчас 13:28.", lambda audio: False, key_stop=lambda: False))
        self.assertTrue(speaker.checked)
        self.assertEqual(speaker.said, ["Сейчас 13:28."])
        self.assertEqual(stream.events, ["stop", "start"])  # no microphone reads while she spoke

    def test_normal_card_keeps_listening(self):
        stream, speaker = Stream(), Speaker(False)
        speak_interruptibly(stream, speaker, "Сейчас 13:28.", lambda audio: False, key_stop=lambda: False)
        self.assertNotIn("stop", stream.events)

    def test_ctrl_still_stops(self):
        stream, speaker = Stream(), Speaker(True)
        speaker.iterate = lambda: None
        self.assertTrue(speak_interruptibly(stream, speaker, "Длинный ответ.", lambda audio: False, key_stop=lambda: True))
        self.assertEqual(stream.events, ["stop", "start"])

    def test_checked_only_once(self):
        stream, speaker = Stream(), Speaker(False)
        speak_interruptibly(stream, speaker, "Раз.", lambda audio: False, key_stop=lambda: False)
        speaker.checked = False
        speak_interruptibly(stream, speaker, "Два.", lambda audio: False, key_stop=lambda: False)
        self.assertFalse(speaker.checked)
