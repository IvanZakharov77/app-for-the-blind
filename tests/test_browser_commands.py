import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from voiceassist.browser_bridge import BridgeError
from voiceassist.browser_commands import BrowserCommands
from voiceassist.core import Assistant
from voiceassist.personal import PersonalStore, TimerBook

RESULTS = [{"number": 1, "name": "Кино — Группа крови", "detail": "Кино, 4:45"},
           {"number": 2, "name": "Кино — Звезда по имени Солнце", "detail": "Кино, 3:46"},
           {"number": 3, "name": "Кино — Кукушка", "detail": "Кино, 6:38"}]


class FakeBridge:
    """Answers like the extension would; records every request."""

    def __init__(self):
        self.calls = []
        self.connected = True
        self.answers = {}

    def request(self, op, args=None, timeout=10.0):
        self.calls.append((op, dict(args or {})))
        if not self.connected:
            raise BridgeError("not_connected")
        if op in self.answers:
            answer = self.answers[op]
            return answer(args) if callable(answer) else answer
        if op == "results.list":
            offset = args.get("offset", 0)
            return {"items": RESULTS[offset:offset + 5], "total": len(RESULTS)}
        if op == "results.open":
            number = args["number"]
            if number > len(RESULTS):
                return {"error": "no_item", "total": len(RESULTS)}
            return {"done": True, "name": RESULTS[number - 1]["name"]}
        if op == "results.find":
            for item in RESULTS:
                if args["text"].split()[0][:4] in item["name"].lower():
                    return {"done": True, "number": item["number"], "name": item["name"]}
            return {"error": "not_found"}
        if op == "video.control":
            playing = args["action"] != "pause"
            return {"done": True, "before": {"paused": True, "time": 10, "duration": 285, "volume": 50},
                    "after": {"paused": not playing, "time": max(0, 10 + (args.get("value") or 0)), "duration": 285, "volume": 50}}
        return {"done": True}


class BrowserVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.bridge = FakeBridge()
        self.assistant = Assistant(clock=lambda: datetime(2026, 10, 13, 12, 0),
                                   personal=PersonalStore(root / "personal.json"), timers=TimerBook(),
                                   sites=None, web=BrowserCommands(self.bridge))
        self.assistant.sites.path = root / "sites.json"

    def tearDown(self):
        self.temp.cleanup()

    def say(self, phrase):
        return self.assistant.handle("помощник " + phrase)

    def test_youtube_search_then_read_and_play_by_number(self):
        result = self.say("найди на ютубе кино группа крови")
        self.assertEqual(result.status, "unverified")
        self.assertIn("youtube.com/results?search_query=", self.bridge.calls[-1][1]["url"])
        self.assertIn("кино+группа+крови", unquote(self.bridge.calls[-1][1]["url"]))
        result = self.say("что нашлось")
        self.assertEqual(result.status, "ok")
        self.assertIn("1. Кино — Группа крови", result.message)
        self.assertIn("3. Кино — Кукушка", result.message)
        result = self.say("воспроизведи второй номер по списку")
        self.assertEqual(self.bridge.calls[-1], ("results.open", {"number": 2}))
        self.assertIn("Звезда по имени Солнце", result.message)

    def test_play_by_name_after_list(self):
        self.say("найди музыку кино")
        self.say("что нашлось")
        result = self.say("воспроизведи кукушку")
        self.assertEqual(self.bridge.calls[-1], ("results.find", {"text": "кукушку"}))
        self.assertIn("Кукушка", result.message)

    def test_play_without_list_searches_youtube(self):
        result = self.say("воспроизведи кино группа крови")
        self.assertEqual(self.bridge.calls[-1][0], "nav.open")
        self.assertIn("YouTube", result.message)

    def test_missing_number_is_reported(self):
        self.say("что нашлось")
        result = self.say("включи пятый")
        self.assertEqual(result.status, "error")
        self.assertIn("Номера 5 нет", result.message)

    def test_next_page_of_results_and_help_still_works(self):
        self.say("что нашлось")
        self.say("дальше")
        self.assertEqual(self.bridge.calls[-1], ("results.list", {"offset": 5}))
        self.say("который час")
        self.say("дальше")
        self.assertEqual(self.bridge.calls[-1], ("results.list", {"offset": 5}))

    def test_programs_win_over_stale_list(self):
        self.say("что нашлось")
        count = len(self.bridge.calls)
        self.say("открой блокнот")
        self.assertEqual(len(self.bridge.calls), count)

    def test_video_controls_check_state(self):
        result = self.say("пауза")
        self.assertEqual(result.status, "ok")
        self.assertIn("Пауза", result.message)
        result = self.say("вперед на тридцать секунд")
        self.assertEqual(self.bridge.calls[-1], ("video.control", {"action": "seek", "value": 30.0}))
        self.assertEqual(result.status, "ok")
        self.assertEqual(self.say("назад на минуту").status, "ok")
        self.assertEqual(self.bridge.calls[-1][1]["value"], -60.0)

    def test_play_that_did_not_start_is_an_error(self):
        self.bridge.answers["video.control"] = {"done": True, "before": {"paused": True}, "after": {"paused": True}}
        result = self.say("продолжи")
        self.assertEqual(result.status, "error")

    def test_bridge_down_is_unavailable(self):
        self.bridge.connected = False
        result = self.say("что на странице")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("расширением", result.message)

    def test_system_volume_keeps_priority(self):
        result = self.say("включи звук")
        self.assertNotIn(("video.control", {"action": "unmute"}), self.bridge.calls)
        self.assertIn(result.status, ("unavailable", "ok", "unverified", "error"))

    def test_open_film_by_number_and_page_lists(self):
        self.bridge.answers["page.list"] = lambda args: {"items": [{"number": 1, "name": "Войти"}], "total": 1}
        result = self.say("прочитай кнопки")
        self.assertIn("1. Войти", result.message)
        self.say("нажми первую кнопку")
        self.assertEqual(self.bridge.calls[-1], ("page.activate", {"kind": "buttons", "number": 1}))
        self.say("открой второй фильм")
        self.assertEqual(self.bridge.calls[-1], ("films.open", {"number": 2}))

    def test_film_search_falls_back_to_youtube(self):
        self.bridge.answers["page.search"] = {"error": "no_field"}
        self.say("найди фильм брат")
        self.assertEqual(self.bridge.calls[-1][0], "nav.open")
        self.assertIn("youtube.com", self.bridge.calls[-1][1]["url"])


class NoBrowserTests(unittest.TestCase):
    def test_browser_phrases_are_unavailable_without_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            assistant = Assistant(personal=PersonalStore(Path(folder) / "p.json"))
            result = assistant.handle("помощник найди на ютубе кино")
            self.assertEqual(result.status, "unavailable")
            self.assertEqual(assistant.handle("помощник пауза").status, "unavailable")


if __name__ == "__main__":
    unittest.main()
