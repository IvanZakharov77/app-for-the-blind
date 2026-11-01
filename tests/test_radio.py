"""Radio by genre and country without numbers or lists (Ivan, 2026-11-01)."""

import tempfile
import unittest
from pathlib import Path

from voiceassist.core import Assistant
from voiceassist.radio import Radio, RadioRequest, find_stations, parse
from offwindows import setUpModule, tearDownModule  # noqa: F401


def station(name, url, codec="MP3", hls=0, country="US"):
    return {"name": name, "url_resolved": url, "codec": codec, "hls": hls, "countrycode": country}


class Player:
    def __init__(self, dead=()):
        self.dead, self.played, self.current = set(dead), [], None

    def play(self, url):
        self.played.append(url)
        self.current = None if url in self.dead else url
        return self.current is not None

    def stop(self):
        self.current = None


class ParseTests(unittest.TestCase):
    def test_simple_phrases(self):
        self.assertEqual(parse("включи радио америки джаз"), RadioRequest("jazz", "Джаз", "US"))
        self.assertEqual(parse("радио дип хаус"), RadioRequest("deep house", "Дип хаус"))
        self.assertEqual(parse("включи джаз"), RadioRequest("jazz", "Джаз"))
        self.assertEqual(parse("включи американское радио"), RadioRequest(country="US"))
        self.assertEqual(parse("включи радио маяк").name, "маяк")
        self.assertEqual(parse("включи радио"), RadioRequest())

    def test_other_commands_are_left_alone(self):
        for phrase in ("включи музыку", "включи песню любэ", "включи звук", "включи видео", "включи блокнот"):
            self.assertIsNone(parse(phrase), phrase)


class SpellingTests(unittest.TestCase):
    def test_deep_house_in_any_spelling(self):
        for phrase in ("включи радио дип хауз", "радио дип хауз", "включи радио deep house", "включи радио дипхаус",
                       "поставь дип хауз"):
            self.assertEqual(parse(phrase).tag, "deep house", phrase)
        self.assertEqual(parse("включи джазовое радио").tag, "jazz")
        self.assertEqual(parse("включи радио маяк").name, "маяк")


class ArrowTests(unittest.TestCase):
    def test_arrows_switch_stations_once_per_press(self):
        import time
        from voiceassist.radio import LEFT, RIGHT
        pressed = set()
        player = Player()
        stations = [station("A", "a"), station("B", "b"), station("C", "c")]
        radio = Radio(player=player, find=lambda request, home: stations, key_pressed=lambda: False,
                      arrow_pressed=lambda key: key in pressed)
        radio.start(RadioRequest(tag="jazz", genre="Джаз"))
        self.assertEqual(player.current, "a")
        pressed.add(RIGHT)
        time.sleep(0.3)  # held: still one step
        pressed.clear()
        time.sleep(0.15)
        self.assertEqual(player.current, "b")
        pressed.add(LEFT)
        time.sleep(0.15)
        pressed.clear()
        time.sleep(0.15)
        self.assertEqual(player.current, "a")
        self.assertTrue(radio.previous()[0])
        self.assertEqual(player.current, "c")


class ChosenStationTests(unittest.TestCase):
    def test_deep_house_is_beat_blender_without_the_directory(self):
        def fetch(url):
            raise AssertionError("the directory is not asked")

        stations = find_stations(parse("включи радио дип хауз"), "UA", fetch)
        self.assertEqual({item["name"] for item in stations}, {"SomaFM Beat Blender"})
        self.assertTrue(stations[0]["url_resolved"].startswith("http://ice1.somafm.com/beatblender"))


class FirstLineTests(unittest.TestCase):
    def test_silent_player_does_not_hang_vega(self):
        import os, time
        from voiceassist.radio import first_line
        read, write = os.pipe()
        started = time.monotonic()
        with os.fdopen(read, "rb") as stream:
            self.assertEqual(first_line(stream, 0.3), "")
            self.assertLess(time.monotonic() - started, 2)
            os.write(write, b"PLAYING\r\n")
            os.close(write)

    def test_line_is_read(self):
        import io
        from voiceassist.radio import first_line
        self.assertEqual(first_line(io.BytesIO(b"PLAYING\r\n"), 1), "PLAYING")


class DirectoryTests(unittest.TestCase):
    def test_only_playable_unique_stations_and_home_country_for_bare_radio(self):
        asked = []

        def fetch(url):
            asked.append(url)
            return [station("Jazz FM", "http://a"), station("Jazz  FM!", "http://b"), station("HLS", "http://c", hls=1),
                    station("Opus", "http://d", codec="OGG"), station("Smooth", "http://e", codec="AAC")]

        found = find_stations(RadioRequest(), "UA", fetch)
        self.assertIn("countrycode=UA", asked[0])
        self.assertEqual([item["url_resolved"] for item in found], ["http://a", "http://e"])
        find_stations(RadioRequest("jazz", "Джаз"), "UA", fetch)
        self.assertNotIn("countrycode", asked[1])  # jazz from the whole world, not only Ukrainian

    def test_a_dead_server_is_skipped(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if len(calls) == 1:
                raise OSError("down")
            return [station("A", "http://a")]

        self.assertEqual(len(find_stations(RadioRequest("jazz"), "", fetch)), 1)
        self.assertEqual(len(calls), 2)


class RadioTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.player = Player(dead={"http://dead"})
        stations = [station("Dead Jazz", "http://dead"), station("Jazz 24 Very Long Station Name", "http://one"),
                    station("Smooth Jazz", "http://two")]
        self.radio = Radio(self.player, find=lambda request, home: stations, store=Path(self.folder.name) / "radio.json")
        self.assistant = Assistant(current_directory=Path(self.folder.name))
        self.assistant.radio = self.radio

    def tearDown(self):
        self.folder.cleanup()

    def test_play_skip_dead_hush_resume_other_and_off(self):
        result = self.assistant.handle("Вега, включи радио америки джаз")
        self.assertEqual(result.message, "Включаю: Джаз, США.")
        self.assertEqual(self.player.played, ["http://dead", "http://one"])
        self.assertTrue(self.radio.hushed)  # quiet while Vega says it
        self.radio.resume()
        self.assertEqual(self.player.current, "http://one")
        self.radio.hush()
        self.assertIsNone(self.player.current)
        self.assertEqual(self.assistant.handle("другое радио").message, "Другое радио.")
        self.radio.resume()
        self.assertEqual(self.player.current, "http://two")
        self.assertIn("Smooth Jazz", self.assistant.handle("что играет").message)
        self.assertEqual(self.assistant.handle("стоп").message, "Радио выключено.")
        self.radio.resume()
        self.assertIsNone(self.player.current)  # switched off stays off

    def test_favourite_is_remembered(self):
        self.assistant.handle("включи джаз")
        self.radio.resume()
        self.assertIn("Запомнила", self.assistant.handle("запомни это радио").message)
        self.assistant.handle("выключи радио")
        self.assertEqual(self.assistant.handle("включи мое радио").message, "Включаю ваше радио.")
        self.radio.resume()
        self.assertEqual(self.player.current, "http://one")

    def test_ctrl_switches_it_off(self):
        pressed = [False]
        radio = Radio(Player(), find=lambda request, home: [station("A", "http://a")], key_pressed=lambda: pressed[0])
        radio.start(RadioRequest("jazz", "Джаз"))
        pressed[0] = True
        import time
        for _ in range(30):
            if not radio.on:
                break
            time.sleep(0.05)
        self.assertFalse(radio.on)


if __name__ == "__main__":
    unittest.main()


class VolumePercentTests(unittest.TestCase):
    def test_percent_and_level(self):
        from voiceassist.system import SystemOutcome
        calls = []

        class System:
            def volume_percent(self, kind, percent):
                calls.append((kind, percent))
                return SystemOutcome("ok", "")

        assistant = Assistant(system=System())
        for phrase in ("уменьши громкость на двадцать процентов", "увеличь громкость на 30 процентов",
                       "громче на 10", "поставь громкость на пятьдесят процентов"):
            assistant.handle(phrase)
        self.assertEqual(calls, [("down", 20), ("up", 30), ("up", 10), ("set", 50)])

    def test_key_presses_are_two_percent(self):
        from voiceassist.system import SystemController

        class Api:
            def __init__(self): self.keys = []
            def press_key(self, key): self.keys.append(key)

        api = Api()
        controller = SystemController.__new__(SystemController)
        controller.api = api
        controller.volume_percent("down", 20)
        self.assertEqual(len(api.keys), 10)
