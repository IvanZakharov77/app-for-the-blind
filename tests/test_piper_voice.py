import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from voiceassist.piper_voice import PiperSpeaker, find_piper, make_speaker

FAKE_PIPER = """#!{python}
import json, sys, wave
args = sys.argv
scale = args[args.index("--length_scale") + 1]
open(args[0] + ".log", "a", encoding="utf-8").write("start " + scale + "\\n")
for line in sys.stdin:
    request = json.loads(line)
    with wave.open(request["output_file"], "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(22050)
        out.writeframes(b"\\x10\\x00" * 2205)
    open(args[0] + ".log", "a", encoding="utf-8").write("text " + request["text"] + "\\n")
    print(request["output_file"], flush=True)
"""


class Player:
    def __init__(self):
        self.played, self.stopped = [], 0

    def play(self, path, wait):
        self.played.append((Path(path).read_bytes()[-4:], wait))

    def stop(self):
        self.stopped += 1


@unittest.skipIf(sys.platform == "win32", "the fake Piper is a POSIX script")
class PiperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name, "piper")
        root.mkdir()
        self.exe = root / "piper"
        self.exe.write_text(FAKE_PIPER.format(python=sys.executable), encoding="utf-8")
        self.exe.chmod(self.exe.stat().st_mode | stat.S_IEXEC)
        (root / "ru_RU-irina-medium.onnx").write_bytes(b"model")
        (root / "ru_RU-irina-medium.onnx.json").write_text("{}", encoding="utf-8")
        self.log = Path(str(self.exe) + ".log")

    def tearDown(self):
        self.temp.cleanup()

    def test_found_and_speaks_with_loaded_model(self):
        found = find_piper([self.temp.name])
        self.assertEqual(found[1].name, "ru_RU-irina-medium.onnx")
        player = Player()
        speaker = PiperSpeaker(*found, player=player)
        speaker.say("Привет.")
        speaker.runAndWait()
        self.assertEqual(len(player.played), 1)
        self.assertTrue(player.played[0][1])
        speaker.setProperty("rate", 240)  # «говори быстрее» restarts Piper once with a shorter length
        speaker.say("Быстрее.")
        speaker.runAndWait()
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("start 1.0", log)
        self.assertIn("start 0.83", log)
        self.assertIn("text Быстрее.", log)
        speaker.close()

    def test_interruptible_loop_and_volume(self):
        player = Player()
        speaker = PiperSpeaker(*find_piper([self.temp.name]), player=player)
        finished = []
        speaker.connect("finished-utterance", lambda name, done: finished.append(done))
        speaker.setProperty("volume", 0.5)
        speaker.say("Длинная фраза.")
        speaker.startLoop(False)
        for _ in range(100):
            speaker.iterate()
            if finished:
                break
        speaker.endLoop()
        self.assertEqual(finished, [True])
        self.assertFalse(player.played[-1][1])
        self.assertEqual(player.played[-1][0], b"\x08\x00\x08\x00")  # samples halved
        speaker.stop()
        self.assertEqual(player.stopped, 1)
        speaker.close()

    def test_falls_back_to_windows_voice(self):
        speaker, name = make_speaker("auto", [str(Path(self.temp.name, "nothing"))], lambda: "sapi-engine")
        self.assertEqual((speaker, name), ("sapi-engine", "sapi"))
        broken = Path(self.temp.name, "piper", "ru_RU-irina-medium.onnx.json")
        self.exe.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        messages = []
        speaker, name = make_speaker("auto", [self.temp.name], lambda: "sapi-engine", log=messages.append)
        self.assertEqual(name, "sapi")
        self.assertTrue(messages)

    def test_auto_keeps_the_light_windows_voice_on_small_memory(self):
        messages = []
        speaker, name = make_speaker("auto", [self.temp.name], lambda: "sapi-engine", log=messages.append,
                                     memory=lambda: 2 * 1024 ** 3)
        self.assertEqual((speaker, name), ("sapi-engine", "sapi"))
        self.assertIn("2.0 ГБ", messages[0])
        speaker, name = make_speaker("piper", [self.temp.name], lambda: "sapi-engine", memory=lambda: 2 * 1024 ** 3)
        self.assertEqual(name, "piper")
        speaker.close()
        # Ivan's 6 GB laptop gets the natural voice (2026-10-27).
        speaker, name = make_speaker("auto", [self.temp.name], lambda: "sapi-engine", memory=lambda: 6 * 1024 ** 3)
        self.assertEqual(name, "piper")
        speaker.close()

    def test_small_memory_without_russian_windows_voice_still_speaks_with_piper(self):
        def no_voice():
            raise RuntimeError("Не найден установленный русский голос синтеза речи.")
        messages = []
        speaker, name = make_speaker("auto", [self.temp.name], no_voice, log=messages.append, memory=lambda: 2 * 1024 ** 3)
        self.assertEqual(name, "piper")
        self.assertIn("Русского голоса Windows нет", messages[0])
        speaker.close()


if __name__ == "__main__":
    unittest.main()


class PlayerFallbackTests(unittest.TestCase):
    def test_sound_goes_through_sounddevice_when_winsound_fails(self):
        import sys
        import tempfile
        import types
        import wave
        from pathlib import Path
        from voiceassist.piper_voice import WinsoundPlayer
        written = []

        def broken(*args):
            raise RuntimeError("Failed to play sound")

        class Stream:
            def __init__(self, **options): written.append(options)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, data): written.append(len(data))
        fakes = {"winsound": types.SimpleNamespace(SND_FILENAME=1, SND_ASYNC=2, PlaySound=broken),
                 "sounddevice": types.SimpleNamespace(RawOutputStream=Stream)}
        saved = {name: sys.modules.get(name) for name in fakes}
        sys.modules.update(fakes)
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "a.wav"
                with wave.open(str(path), "wb") as sound:
                    sound.setnchannels(1); sound.setsampwidth(2); sound.setframerate(22050)
                    sound.writeframes(b"\0\0" * 22050)
                player = WinsoundPlayer()
                player.play(path, wait=True)
                self.assertTrue(player.device)
                self.assertEqual(written[0], {"samplerate": 22050, "channels": 1, "dtype": "int16"})
                self.assertEqual(sum(written[1:]), 44100)
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
