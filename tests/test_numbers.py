import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from voiceassist.browser import BrowserOutcome, SitesStore
from voiceassist.browser_state import loaded_requested_page, save_active_tab
from voiceassist.core import Assistant
from voiceassist.numbers import format_size, replace_number_words, words_to_number
from voiceassist.personal import PersonalStore, TimerBook
from offwindows import setUpModule, tearDownModule  # noqa: F401


class NumberWordsTests(unittest.TestCase):
    def test_words_become_numbers(self):
        self.assertEqual(words_to_number("пять"), 5)
        self.assertEqual(words_to_number("двадцать пять"), 25)
        self.assertEqual(words_to_number("сто двенадцать"), 112)
        self.assertEqual(words_to_number("две тысячи двадцать шесть"), 2026)
        self.assertEqual(words_to_number("одну"), 1)
        self.assertEqual(words_to_number("полторы"), 1.5)
        self.assertEqual(words_to_number("12"), 12)

    def test_non_numbers_are_rejected(self):
        self.assertIsNone(words_to_number("много"))
        self.assertIsNone(words_to_number("пять двадцать"))
        self.assertIsNone(words_to_number(""))

    def test_replacement_keeps_other_words(self):
        self.assertEqual(replace_number_words("двенадцать плюс семь"), "12 плюс 7")
        self.assertEqual(replace_number_words("сорок два разделить на шесть"), "42 разделить на 6")

    def test_sizes_are_spoken_in_human_units(self):
        self.assertEqual(format_size(15032385536), "14 гигабайт")
        self.assertEqual(format_size(1536 * 1024 ** 2), "1,5 гигабайта")
        self.assertEqual(format_size(3 * 1024 ** 2), "3 мегабайта")
        self.assertEqual(format_size(21 * 1024), "21 килобайт")
        self.assertEqual(format_size(1), "1 байт")


class VoskPhraseTests(unittest.TestCase):
    """Phrases in the form Vosk writes them: lower case, numbers as words."""

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.now = [0.0]
        self.clock = [datetime(2026, 10, 13, 14, 0)]
        self.assistant = Assistant(clock=lambda: self.clock[0],
                                   personal=PersonalStore(Path(self.root.name, "data.json")),
                                   timers=TimerBook(clock=lambda: self.now[0]),
                                   sites=SitesStore(Path(self.root.name, "sites.json")))

    def tearDown(self):
        self.root.cleanup()

    def test_timer_in_words(self):
        result = self.assistant.handle("поставь таймер на пять минут")
        self.assertEqual(result.status, "ok")
        self.assertIn("пять минут", result.message)
        self.now[0] = 299.0
        self.assertEqual(self.assistant.poll_due(), ())
        self.now[0] = 300.0
        self.assertEqual(self.assistant.poll_due(), ("Таймер завершён.",))

    def test_timer_without_number_and_half_hour(self):
        self.assertEqual(self.assistant.handle("поставь таймер на минуту").status, "ok")
        self.assertEqual(self.assistant.handle("поставь таймер на полчаса").status, "ok")
        self.assertEqual(self.assistant.handle("поставь таймер на полторы минуты").status, "ok")
        self.assertEqual(sorted(self.assistant.timers.deadlines), [60.0, 90.0, 1800.0])

    def test_unclear_timer_number_is_an_error_not_a_guess(self):
        self.assertEqual(self.assistant.handle("поставь таймер на много минут").status, "error")

    def test_reminder_in_words_keeps_reminder_text(self):
        result = self.assistant.handle("напомни через десять минут позвонить двум друзьям")
        self.assertIn("в 14:10: позвонить двум друзьям?", result.message)
        self.assertEqual(self.assistant.handle("да").status, "ok")
        self.assertIn("позвонить двум друзьям", self.assistant.handle("какие напоминания").message)
        self.clock[0] = datetime(2026, 10, 13, 14, 10)
        self.assertEqual(self.assistant.poll_due(), ("Напоминание: позвонить двум друзьям.",))

    def test_reminder_in_an_hour(self):
        self.assertEqual(self.assistant.handle("напомни через час выпить лекарство").status, "needs_confirmation")
        self.assertEqual(self.assistant.handle("да").status, "ok")

    def test_calculation_in_words(self):
        self.assertIn("19", self.assistant.handle("сколько будет двенадцать плюс семь").message)
        self.assertIn("7", self.assistant.handle("сколько будет сорок два разделить на шесть").message)
        self.assertIn("5000 метров", self.assistant.handle("переведи пять километров в метры").message)

    def test_time_synonyms(self):
        self.assertIn("14:00", self.assistant.handle("который сейчас час").message)
        self.assertIn("13.10.2026", self.assistant.handle("какое число").message)

    def test_misheard_note_can_be_refused(self):
        self.assertIn("Скажите: да или нет", self.assistant.handle("запиши заметку купить слона").message)
        self.assertEqual(self.assistant.handle("нет").status, "ok")
        self.assertIn("Заметок нет", self.assistant.handle("прочитай заметки").message)

    def test_note_text_is_not_rewritten_into_digits(self):
        self.assistant.handle("запиши заметку купить два хлеба")
        self.assistant.handle("да")
        self.assertIn("купить два хлеба", self.assistant.handle("прочитай заметки").message)


class SpokenSiteNameTests(unittest.TestCase):
    def test_spoken_name_and_help_use_cyrillic_names_only(self):
        with tempfile.TemporaryDirectory() as root:
            sites = SitesStore(Path(root, "sites.json"))
            sites.set("HDRezka", "https://example.org/")
            sites.set("ХД-Резка", "https://example.org/")

            class Browser:
                finder = staticmethod(lambda: Path("chrome.exe"))

            assistant = Assistant(browser=Browser(), sites=sites)
            self.assertEqual(sites.get("хд резка"), "https://example.org/")
            listing = assistant.handle("какие сайты сохранены").message
            self.assertIn("хд резка", listing)
            self.assertNotIn("hdrezka", listing)
            options = []
            for _ in range(4):
                options.extend(assistant.handle("дальше").options)
            self.assertIn("Открой хд резка", options)
            self.assertNotIn("Открой HDRezka", options)

    def test_old_alias_still_reaches_latin_entry(self):
        with tempfile.TemporaryDirectory() as root:
            sites = SitesStore(Path(root, "sites.json"))
            sites.set("HDRezka", "https://example.org/")
            self.assertEqual(sites.get("резка"), "https://example.org/")


class PageConfirmationTests(unittest.TestCase):
    def test_trailing_slash_www_and_https_redirect_still_confirm(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "state.json")
            save_active_tab(path, "https://rezka.ag/", "Резка", 100.0)
            self.assertTrue(loaded_requested_page(path, "https://rezka.ag", 99.0))
            self.assertTrue(loaded_requested_page(path, "http://www.rezka.ag", 99.0))
            self.assertFalse(loaded_requested_page(path, "https://rezka.ag/films", 99.0))
            self.assertFalse(loaded_requested_page(path, "https://other.ag", 99.0))


if __name__ == "__main__":
    unittest.main()


class BuiltinSiteTests(unittest.TestCase):
    def test_film_sites_open_with_no_setup(self):
        with tempfile.TemporaryDirectory() as root:
            opened = []

            class Browser:
                finder = staticmethod(lambda: Path("chrome.exe"))

                def open_site(self, url):
                    opened.append(url)
                    return BrowserOutcome("ok", "Открываю.")

            assistant = Assistant(browser=Browser(), sites=SitesStore(Path(root, "sites.json")))
            for phrase, url in (("открой сайт кинокрад", "https://kinokrad.my/s27"),
                                ("открой эйч ди резка", "https://hdrezka.la/"),
                                ("открой сайт хдрезка", "https://hdrezka.la/"),
                                ("открой филмикс", "https://filmix.gg/film/t8/pages/2/"),
                                ("открой сайт фильмикс", "https://filmix.gg/film/t8/pages/2/"),
                                ("открой ютуб", "https://www.youtube.com/"),
                                ("открыть ютуб", "https://www.youtube.com/"),
                                ("открой сайт youtube", "https://www.youtube.com/"),
                                ("открой гугл", "https://www.google.com/"),
                                ("открой почту", "https://mail.google.com/"),
                                ("открой википедию", "https://ru.wikipedia.org/")):
                self.assertEqual(assistant.handle("вега " + phrase).status, "ok", phrase)
                self.assertEqual(opened[-1], url, phrase)
            self.assertIn("кинокрад", assistant.handle("какие сайты сохранены").message)

    def test_saved_site_wins_over_builtin(self):
        with tempfile.TemporaryDirectory() as root:
            sites = SitesStore(Path(root, "sites.json"))
            sites.set("хд резка", "https://rezka.ag/")
            self.assertEqual(sites.get("хдрезка"), "https://rezka.ag/")
