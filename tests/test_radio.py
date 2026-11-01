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
