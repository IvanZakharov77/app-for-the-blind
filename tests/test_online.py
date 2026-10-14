import json
import unittest
from datetime import datetime

from voiceassist.core import Assistant
from voiceassist.online import Offline, OnlineInfo, city_variants
from voiceassist.personal import PersonalStore, TimerBook, calculate
from voiceassist.settings import Settings

FORECAST = {"current_weather": {"temperature": 4.6, "windspeed": 3.2, "weathercode": 3, "time": "2026-10-13T14:00"},
            "daily": {"temperature_2m_min": [1.2, -2.0], "temperature_2m_max": [7.4, 3.0],
                      "precipitation_probability_max": [40, 80], "weathercode": [3, 71]}}
RSS = """<?xml version="1.0"?><rss><channel><title>Лента</title>
<item><title>Первая новость</title><link>https://example.ru/1</link><description>&lt;p&gt;Текст первой&lt;/p&gt;</description>
<pubDate>Tue, 13 Oct 2026 10:00:00 +0000</pubDate></item>
<item><title>Вторая новость</title><link>https://example.ru/2</link></item></channel></rss>"""


class FakeNet:
    def __init__(self):
        self.online = True
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if not self.online:
            raise Offline("no network")
        if "geocoding" in url:
            found = "%D0%BA%D0%B0%D0%B7%D0%B0%D0%BD%D1%8C" in url  # «казань»
            return json.dumps({"results": [{"name": "Казань", "latitude": 55.79, "longitude": 49.12}]} if found else {}).encode()
        if "forecast" in url:
            return json.dumps(FORECAST).encode()
        return RSS.encode("utf-8")


class OnlineTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.net = FakeNet()
        self.settings = Settings(Path(self.temp.name, "settings.json"))
        self.assistant = Assistant(clock=lambda: datetime(2026, 10, 13, 12, 0), personal=PersonalStore(Path(self.temp.name, "p.json")),
                                   timers=TimerBook(), settings=self.settings, online=OnlineInfo(self.net))

    def tearDown(self):
        self.temp.cleanup()

    def say(self, phrase):
        return self.assistant.handle("помощник " + phrase)

    def test_weather_needs_city_then_works_and_names_source(self):
        self.assertEqual(self.say("какая погода").status, "unavailable")
        self.assertIn("Казань", self.say("мой город казань").message)
        self.assertEqual(self.settings.get("weather")["name"], "Казань")
        result = self.say("какая погода")
        self.assertIn("плюс 5 градусов, пасмурно", result.message)
        self.assertIn("на 14:00", result.message)
        self.assertIn("Open-Meteo", result.message)
        self.assertIn("минус 2", self.say("погода на завтра").message)

    def test_weather_in_spoken_city_form(self):
        self.assertIn("Казань", self.say("погода в казани").message)
        self.assertIn("казань", city_variants("казани"))

    def test_offline_is_honest(self):
        self.say("мой город казань")
        self.net.online = False
        result = self.say("какая погода")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("интернет", result.message)

    def test_news_from_configured_feed(self):
        result = self.say("какие новости")  # no setup: main headlines from Google News
        self.assertEqual(result.status, "ok")
        self.assertIn("news.google.com/rss?", self.net.urls[-1])
        self.settings.set("news", {"name": "Лента", "url": "https://lenta.ru/rss/news"})
        result = self.say("какие новости")
        self.assertIn("Новости Лента", result.message)
        self.assertIn("1. Первая новость", result.message)
        self.assertIn("Текст первой", self.say("прочитай новость номер один").message)

    def test_local_news_use_saved_city(self):
        self.say("мой город казань")
        result = self.say("местные новости")
        self.assertEqual(result.status, "ok")
        self.assertIn("q=%D0%9A%D0%B0%D0%B7%D0%B0%D0%BD%D1%8C", self.net.urls[-1])  # «Казань»
        self.assertIn("Казань", result.message)
        self.say("новости саратова")
        self.assertIn("search?", self.net.urls[-1])

    def test_city_is_guessed_then_confirmed(self):
        self.net_answer = None
        original = self.net.__call__

        def net(url):
            if "ipwho.is" in url:
                return json.dumps({"success": True, "city": "Казань", "region": "Татарстан", "latitude": 55.8, "longitude": 49.1}).encode()
            return original(url)
        self.assistant.online.fetch = net
        result = self.say("местные новости")
        self.assertEqual(result.status, "needs_confirmation")
        self.assertIn("Казань, Татарстан", result.message)
        self.assertIsNone(self.settings.get("weather"))
        self.assertEqual(self.say("да это мой город").status, "ok")
        self.assertEqual(self.settings.get("weather")["name"], "Казань")

    def test_speech_rate_and_volume_are_saved(self):
        self.assertIn("быстрее", self.say("говори быстрее").message)
        self.assertEqual(self.settings.get("speech_rate"), 1)
        self.say("голос тише")
        self.assertEqual(self.settings.get("speech_volume"), 80)
        self.assertEqual(Settings(self.settings.path).get("speech_volume"), 80)
        self.say("говори обычно")
        self.assertEqual(self.settings.get("speech_rate"), 0)

    def test_broken_settings_fall_back(self):
        self.settings.path.write_text('{"speech_rate": 99, "speech_volume": 60}', encoding="utf-8")
        loaded = Settings(self.settings.path)
        self.assertEqual(loaded.get("speech_rate"), 0)
        self.assertEqual(loaded.get("speech_volume"), 60)
        self.assertIn("speech_rate", loaded.problem)

    def test_conversions(self):
        self.assertEqual(calculate("3 часа в минуты"), "180 минут")
        self.assertEqual(calculate("500 граммов в килограммы"), "0,5 килограмма")
        with self.assertRaises(ValueError):
            calculate("2 метра в килограммы")


class MissedReminderTests(unittest.TestCase):
    def test_reminder_due_while_off_is_named_missed(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            store = PersonalStore(Path(folder, "p.json"))
            store.add_reminder(datetime(2026, 10, 13, 9, 0).timestamp(), "позвонить врачу")
            now = [datetime(2026, 10, 13, 12, 0)]
            assistant = Assistant(clock=lambda: now[0], personal=store, timers=TimerBook(), settings=Settings(None))
            alerts = assistant.poll_due()
            self.assertIn("Пропущено, пока Вега была выключена: позвонить врачу. Срок был 13.10 в 09:00.", alerts)
            store.add_reminder(datetime(2026, 10, 13, 12, 5).timestamp(), "чай")
            self.assertEqual(assistant.handle("удали напоминание номер один").status, "needs_confirmation")
            self.assertEqual(assistant.handle("подтверждаю удаление").status, "ok")
            self.assertEqual(store.upcoming(), [])


if __name__ == "__main__":
    unittest.main()
