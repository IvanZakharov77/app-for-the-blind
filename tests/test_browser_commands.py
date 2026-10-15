import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from voiceassist.browser_bridge import BridgeError
from voiceassist.browser_commands import BrowserCommands
from voiceassist.core import Assistant
from voiceassist.personal import PersonalStore, TimerBook
from offwindows import setUpModule, tearDownModule  # noqa: F401

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
        for phrase in ("включи номер три", "номер три", "третий", "открыть номер три"):
            self.bridge.calls.clear()
            self.say("что нашлось")
            self.say(phrase)
            self.assertEqual(self.bridge.calls[-1], ("results.open", {"number": 3}), phrase)

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


class PlainBrowserTests(unittest.TestCase):
    def test_search_without_extension_opens_the_browser(self):
        from voiceassist.browser import BrowserOutcome
        bridge = FakeBridge()
        bridge.connected = False
        opened = []

        class Browser:
            def open_site(self, url):
                opened.append(url)
                return BrowserOutcome("unverified", "Адрес передан Chrome.")
        with tempfile.TemporaryDirectory() as folder:
            web = BrowserCommands(bridge)
            web.video_finder = lambda query: None  # YouTube unreachable: the page is only opened
            assistant = Assistant(personal=PersonalStore(Path(folder) / "p.json"), browser=Browser(), web=web)
            result = assistant.handle("вега найди в интернете погода харьков")
            self.assertIn("Открыла поиск", result.message)
            self.assertIn("погода+харьков", unquote(opened[-1]))
            assistant.handle("вега найди на ютубе кино группа крови")
            self.assertIn("youtube.com/results", opened[-1])

    def test_youtube_results_are_read_and_played_without_extension(self):
        # Ivan, 2026-10-15: without the extension Vega only said she could not read the results.
        from voiceassist.browser import BrowserOutcome
        bridge = FakeBridge()
        bridge.connected = False
        opened = []

        class Browser:
            def open_site(self, url):
                opened.append(url)
                return BrowserOutcome("unverified", "Адрес передан Chrome.")
        videos = [{"name": "Песня номер {}".format(number), "detail": "Канал, 3:0{}".format(number),
                   "url": "https://www.youtube.com/watch?v=v{}".format(number)} for number in range(1, 8)]
        with tempfile.TemporaryDirectory() as folder:
            web = BrowserCommands(bridge)
            web.video_finder = lambda query: videos
            assistant = Assistant(personal=PersonalStore(Path(folder) / "p.json"), browser=Browser(), web=web)
            result = assistant.handle("найди на ютубе песни высоцкого")
            self.assertIn("На YouTube нашла: 1. Песня номер 1, Канал, 3:01", result.message)
            self.assertIn("5. Песня номер 5", result.message)
            self.assertNotIn("расширение", result.message)
            self.assertIn("6. Песня номер 6", assistant.handle("дальше").message)
            self.assertIn("1. Песня номер 1", assistant.handle("что нашлось").message)
            played = assistant.handle("включи номер два")
            self.assertIn("Песня номер 2", played.message)
            self.assertEqual(opened[-1], "https://www.youtube.com/watch?v=v2")
            self.assertIn("Номера 9 нет", assistant.handle("включи номер девять").message)
            searched = []
            web.video_finder = lambda query: searched.append(query) or videos
            self.assertIn("На YouTube нашла", assistant.handle("привет вега найди музыку").message)
            self.assertIn("На YouTube нашла", assistant.handle("включи музыку").message)
            self.assertEqual(searched, ["музыка", "музыка"])

    def test_youtube_page_parsing(self):
        import json
        from voiceassist.youtube_search import parse_results
        data = {"contents": {"list": [
            {"videoRenderer": {"videoId": "abc", "title": {"runs": [{"text": "Высоцкий — Кони привередливые"}]},
                               "ownerText": {"runs": [{"text": "Архив"}]}, "lengthText": {"simpleText": "4:12"}}},
            {"adSlotRenderer": {}},
            {"videoRenderer": {"videoId": "abc", "title": {"runs": [{"text": "повтор"}]}}},
            {"videoRenderer": {"videoId": "def", "title": {"simpleText": "Песня о друге"}}}]}}
        page = "<script>var ytInitialData = " + json.dumps(data, ensure_ascii=False) + ";</script>"
        self.assertEqual(parse_results(page), [
            {"name": "Высоцкий — Кони привередливые", "detail": "Архив, 4:12", "url": "https://www.youtube.com/watch?v=abc"},
            {"name": "Песня о друге", "detail": "", "url": "https://www.youtube.com/watch?v=def"}])
        self.assertEqual(parse_results("<html>consent</html>"), [])

    def test_any_page_without_extension(self):
        # Ivan, 2026-10-15: with a site open, Vega must tell what is on it even without the extension.
        from voiceassist.page_reader import parse_page, chunk
        html = ("<html><head><title>Солярис — Википедия</title><script>x()</script></head><body><nav><p>Меню сайта</p></nav>"
                "<h1>Солярис</h1><p>Войти</p><p>«Солярис» — фантастический роман Станислава Лема, написанный в 1961 году.</p>"
                "<h2>Сюжет</h2><p>Психолог Крис Кельвин прилетает на станцию над планетой Солярис.</p></body></html>")
        page = parse_page(html)
        self.assertEqual(page.title, "Солярис — Википедия")
        self.assertEqual(page.headings, ["Солярис", "Сюжет"])
        self.assertIn("роман Станислава Лема", page.text)
        self.assertNotIn("Меню", page.text)
        self.assertNotIn("Войти", page.text)
        piece, end = chunk("Раз. " * 400, 0)
        self.assertTrue(piece.endswith("Раз.") and 0 < end < 2000)

        bridge = FakeBridge()
        bridge.connected = False
        web = BrowserCommands(bridge)
        web.page_reader = lambda url: parse_page(html)
        with tempfile.TemporaryDirectory() as folder:
            assistant = Assistant(personal=PersonalStore(Path(folder) / "p.json"), web=web)
            self.assertIn("расширением", assistant.handle("вега что на странице").message)  # nothing opened yet
            web.note_opened("https://ru.wikipedia.org/wiki/Солярис")
            result = assistant.handle("вега что на странице")
            self.assertIn("Страница «Солярис — Википедия». Заголовки: Солярис; Сюжет.", result.message)
            self.assertIn("Крис Кельвин", assistant.handle("вега прочитай страницу").message)

    def test_open_site_and_search_in_one_phrase(self):
        # Ivan, 2026-10-15: «привет вега открой сайт кинокрад найди фильм человек паук» got «Не поняла».
        from voiceassist.browser_routes import route

        class Web:
            def __getattr__(self, name):
                return lambda *args: (name,) + args
        self.assertEqual(route("открой сайт кинокрад найди фильм человек паук", Web(), None),
                         ("film_search_on", "kinokrad", "человек паук"))
        self.assertEqual(route("открой резку и найди солярис", Web(), None), ("film_search_on", "rezka", "солярис"))
        self.assertEqual(route("открой ютуб найди высоцкого", Web(), None), ("youtube_search", "высоцкого"))

    def test_film_sites_without_extension(self):
        # Ivan, 2026-10-15: «открой кинокрад», then «какие фильмы здесь», «найди фильм …» on that site,
        # and «найди фильм … на кинокраде / резке / филмиксе», all without the extension.
        from voiceassist.browser import BrowserOutcome
        bridge = FakeBridge()
        bridge.connected = False
        opened, searched, read = [], [], []

        class Browser:
            def open_site(self, url):
                opened.append(url)
                return BrowserOutcome("unverified", "Открываю сайт.")
        films = [{"name": "Фильм {}".format(number), "detail": "", "url": "https://kinokrad.my/{}.html".format(number)}
                 for number in range(1, 8)]
        with tempfile.TemporaryDirectory() as folder:
            web = BrowserCommands(bridge)
            web.film_search = lambda key, query: searched.append((key, query)) or films[:2]
            web.page_films = lambda url: read.append(url) or films
            assistant = Assistant(personal=PersonalStore(Path(folder) / "p.json"), browser=Browser(), web=web)
            self.assertEqual(assistant.handle("вега какие фильмы здесь").status, "unavailable")  # no film site open yet
            assistant.handle("привет вега открой кинокрад")
            self.assertIn("kinokrad", opened[-1])
            listed = assistant.handle("вега какие фильмы здесь")
            self.assertIn("1. Фильм 1", listed.message)
            self.assertIn("5. Фильм 5", listed.message)
            self.assertIn("kinokrad", read[-1])
            self.assertIn("6. Фильм 6", assistant.handle("вега дальше").message)
            result = assistant.handle("вега открой номер два")
            self.assertIn("Фильм 2", result.message)
            self.assertEqual(opened[-1], "https://kinokrad.my/2.html")
            # On the open site
            found = assistant.handle("вега найди фильм человек паук")
            self.assertEqual(searched[-1], ("kinokrad", "человек паук"))
            self.assertIn("Кинокрад, «человек паук»: 1. Фильм 1", found.message)
            self.assertIn("kinokrad.my/index.php?do=search", opened[-1])
            # On a named site
            assistant.handle("привет вега найди фильм человек паук на резке")
            self.assertEqual(searched[-1], ("rezka", "человек паук"))
            assistant.handle("вега найди на филмиксе солярис")
            self.assertEqual(searched[-1], ("filmix", "солярис"))
            self.assertIn("filmix.gg/search/", opened[-1])
            self.assertIn("Фильм 1", assistant.handle("вега что на странице").message)

    def test_film_site_pages_are_parsed(self):
        from voiceassist.film_sites import parse_filmix, parse_kinokrad, parse_rezka, site_of
        kinokrad = ('<a class="kino-poster" itemprop="url" href="https://kinokrad.my/3475-soljaris.html" title="Солярис (2003)">'
                    '<a class="kino-poster" itemprop="url" href="https://kinokrad.my/7690-soljaris.html" title="Солярис (1972)">')
        self.assertEqual([film["name"] for film in parse_kinokrad(kinokrad)], ["Солярис (2003)", "Солярис (1972)"])
        rezka = ('<div class="b-content__inline_item-link"> <a href="https://rezka.ag/films/action/1481-chelovek-pauk-2002.html">'
                 'Человек-паук</a> <div>2002, США, Боевики</div> </div>')
        self.assertEqual(parse_rezka(rezka), [{"name": "Человек-паук", "detail": "2002, США, Боевики",
                                               "url": "https://rezka.ag/films/action/1481-chelovek-pauk-2002.html"}])
        api = '{"posts":[{"title":"Человек-паук","year":2002,"link":"https:\\/\\/filmix.gg\\/film\\/3987.html"}]}'
        self.assertEqual(parse_filmix(api), [{"name": "Человек-паук", "detail": "2002", "url": "https://filmix.gg/film/3987.html"}])
        page = '<h2 class="name" itemprop="name" content="Высокогорье"><a itemprop="url" href="https://filmix.gg/s/1.html" title="x">'
        self.assertEqual(parse_filmix(page)[0]["name"], "Высокогорье")
        self.assertEqual([site_of(url) for url in ("https://kinokrad.my/s27", "https://hdrezka.la/", "https://filmix.gg/", "https://ya.ru")],
                         ["kinokrad", "rezka", "filmix", None])


class NoBrowserTests(unittest.TestCase):
    def test_browser_phrases_are_unavailable_without_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            assistant = Assistant(personal=PersonalStore(Path(folder) / "p.json"))
            result = assistant.handle("помощник найди на ютубе кино")
            self.assertEqual(result.status, "unavailable")
            self.assertEqual(assistant.handle("помощник пауза").status, "unavailable")


if __name__ == "__main__":
    unittest.main()
