import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from voiceassist.core import Assistant
from voiceassist.drives import UsbVolume
from voiceassist.file_browser import FileBrowser, KNOWN_FOLDERS, valid_name
from voiceassist.file_routes import DriveInfo
from voiceassist.files import CopyJournal
from voiceassist.personal import PersonalStore, TimerBook
from offwindows import setUpModule, tearDownModule  # noqa: F401


class FileVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name, "home")
        self.flash = Path(self.temp.name, "flash")
        for folder in ("Documents", "Downloads", "Desktop", "Pictures", "Music", "Videos"):
            (self.home / folder).mkdir(parents=True)
        self.flash.mkdir()
        documents = self.home / "Documents"
        for name in ("письмо.docx", "список.txt", "отчёт.pdf", "фото.jpg", "запуск.bat", "старое.txt"):
            (documents / name).write_text("данные " + name, encoding="utf-8")
        (documents / "Архив").mkdir()
        (documents / "Архив" / "внутри.txt").write_text("x", encoding="utf-8")
        (self.home / "Pictures" / "море.jpg").write_bytes(b"jpeg" * 10)
        (self.home / "Pictures" / "Лето").mkdir()
        (self.home / "Pictures" / "Лето" / "пляж.png").write_bytes(b"png")
        self.volume = UsbVolume("E", "guid-e", "ФЛЕШКА", "FAT32", True)
        self.launched, self.recycled, self.shown = [], [], []

        def lookup(spoken, home):
            entry = KNOWN_FOLDERS.get(spoken)
            return None if entry is None else (home / entry[1] if entry[1] else home)

        def recycle(path):
            self.recycled.append(path.name)
            path.unlink() if path.is_file() else path.rmdir()

        browser = FileBrowser(home=self.home, drive_provider=lambda: (self.volume,), launcher=self.launched.append,
                              recycler=recycle, is_removable=lambda path: self.flash in path.parents,
                              folder_lookup=lookup, volume_root=lambda volume: self.flash, shower=self.shown.append,
                              drive_lister=lambda: [self.flash])
        self.assistant = Assistant(clock=lambda: datetime(2026, 10, 13, 12, 0), current_directory=self.home,
                                   personal=PersonalStore(Path(self.temp.name, "p.json")), timers=TimerBook(),
                                   drive_provider=lambda: (self.volume,))
        self.assistant.files = browser
        browser.current = self.home
        self.assistant.drives = DriveInfo(lambda: (self.volume,), fixed_letters=lambda: (), optical_letters=lambda: ("D",),
                                          eject=lambda letter: None, wait=lambda _: None,
                                          disk_usage=lambda root: shutil.disk_usage(str(self.flash)))

    def tearDown(self):
        self.temp.cleanup()

    def say(self, phrase):
        return self.assistant.handle("помощник " + phrase)

    def wait_events(self):
        for _ in range(100):
            if not self.assistant.files.busy():
                break
            time.sleep(0.02)
        return self.assistant.poll_due()

    def test_open_documents_pages_and_open_by_number(self):
        result = self.say("открой документы")
        self.assertEqual(result.message, "Открыта папка «Документы». Чтобы послушать, что в ней, скажите: что в папке.")
        result = self.say("что в папке")
        self.assertTrue(result.message.startswith("Папка «Документы». 1. Архив"), result.message)
        self.assertNotIn("элемент", result.message)
        self.assertIn("1. Архив — папка", result.message)
        self.assertIn("следующие файлы", result.message)
        result = self.say("дальше")
        self.assertIn("7. фото.jpg", result.message)
        self.assertEqual(self.say("открой второй").status, "needs_confirmation")  # запуск.bat
        self.say("открой третий")
        self.assertTrue(self.launched[-1].endswith("отчёт.pdf"))

    def test_open_folder_shows_it_and_any_way_of_saying_the_number_works(self):
        self.say("открой документы")
        self.assertEqual(self.shown, [str(self.home / "Documents")])
        for phrase in ("открой номер 1", "открой номер один", "открыть номер один", "номер один", "первый", "открой под номером один"):
            self.say("открой документы")
            result = self.say(phrase)
            self.assertIn("Открыта папка «Архив»", result.message, phrase)
        self.assertEqual(self.shown[-1], str(self.home / "Documents" / "Архив"))

    def test_my_computer_lists_disks_and_opens_one_by_number(self):
        from voiceassist.file_browser import MY_COMPUTER
        for phrase in ("открой мой компьютер", "мой компьютер", "покажи мой компьютер", "открой мои компьютер"):
            result = self.say(phrase)
            self.assertTrue(result.message.startswith("Мой компьютер. 1. flash"), phrase)
            self.assertEqual(self.shown[-1], MY_COMPUTER)
        result = self.say("открой номер один")
        self.assertIn("Открыта папка «flash»", result.message)
        self.assertEqual(self.shown[-1], str(self.flash))

    def test_flash_phrases_as_vosk_hears_them(self):
        for phrase in ("что на флешке", "что на флэшке", "покажи флешку", "открыть флешку", "что есть на флешке", "флешка"):
            self.assertEqual(self.say(phrase).status, "ok", phrase)
        self.assertIn("ФЛЕШКА", self.say("какие флешки").message)
        self.assertIn("свободно", self.say("сколько места на флешки").message)

    def test_phrases_from_the_laptop_log(self):
        # commands.log, Windows 8, 2026-10-14: the start of a phrase is lost while Vega finishes speaking.
        for heard in ("ой номер один", "крой номер один", "бронь первый"):
            self.say("открой документы")
            self.assertIn("Открыта папка «Архив»", self.say(heard).message, heard)
        for heard in ("и флэшки подключены", "флэшки подключены", "номер флэшки подключены", "какие плюшки подключены"):
            self.assertIn("ФЛЕШКА", self.say(heard).message, heard)
        self.assertEqual(self.say("кто ты умеешь").status, "ok")

    def test_misheard_site_names_open_the_site(self):
        from voiceassist.browser import BrowserOutcome
        opened = []

        class Browser:
            def open_site(self, url):
                opened.append(url)
                return BrowserOutcome("ok", "Открываю.")
        self.assistant.browser = Browser()
        for heard, url in (("открой кино крот", "https://kinokrad.my/s27"), ("открой эйч ди резко", "https://hdrezka.la/"),
                           ("ютуб", "https://www.youtube.com/")):
            self.assertEqual(self.say(heard).status, "ok", heard)
            self.assertEqual(opened[-1], url, heard)
        self.assertEqual(self.say("открой кино").status, "unknown")

    def test_unknown_phrase_is_said_back(self):
        self.assertEqual(self.say("сделай кофе").message, "Не поняла: «сделай кофе». Скажите: помоги.")

    def test_runnable_file_needs_confirmation(self):
        self.say("открой документы")
        result = self.say("открой файл запуск")
        self.assertEqual(result.status, "needs_confirmation")
        self.assertEqual(self.launched, [])
        self.say("подтверждаю запуск")
        self.assertTrue(self.launched[-1].endswith("запуск.bat"))

    def test_enter_folder_up_and_where(self):
        self.say("открой документы")
        result = self.say("открой первый")
        self.assertIn("Открыта папка «Архив»", result.message)
        self.assertIn("внутри.txt", self.say("что в папке").message)
        result = self.say("выйди из папки")
        self.assertIn("Документы", result.message)
        self.assertIn("Документы", self.say("какая папка открыта").message)

    def test_create_folder(self):
        self.say("открой документы")
        self.assertEqual(self.say("создай папку Рецепты").status, "ok")
        self.assertTrue((self.home / "Documents" / "рецепты").is_dir())
        self.assertEqual(self.say("создай папку рецепты").status, "error")

    def test_bad_names(self):
        self.assertFalse(valid_name("con"))
        self.assertFalse(valid_name("a/b"))
        self.assertTrue(valid_name("Отпуск 2026"))

    def test_find_photos_includes_flash_and_subfolders(self):
        (self.flash / "семья.jpg").write_bytes(b"1")
        result = self.say("найди фотографии")
        self.assertIn("Найдено фотографии", result.message)
        for name in ("море.jpg", "пляж.png", "фото.jpg", "семья.jpg"):
            self.assertIn(name, result.message + " ".join(p.name for p in self.assistant.files.items))

    def test_rename_requires_confirmation_and_keeps_extension(self):
        self.say("открой документы")
        result = self.say("переименуй список в покупки")
        self.assertEqual(result.status, "needs_confirmation")
        self.assertIn("«покупки.txt»", result.message)
        self.assertTrue((self.home / "Documents" / "список.txt").exists())
        self.assertEqual(self.say("подтверждаю переименование").status, "ok")
        self.assertTrue((self.home / "Documents" / "покупки.txt").exists())

    def test_delete_goes_to_recycle_bin_after_confirmation(self):
        self.say("открой документы")
        result = self.say("удали файл старое")
        self.assertIn("корзину", result.message)
        self.assertEqual(self.recycled, [])
        self.assertEqual(self.say("подтверждаю выключение").status, "unknown")
        result = self.say("подтверждаю удаление")
        self.assertEqual(self.recycled, ["старое.txt"])
        self.assertIn("корзины", result.message)

    def test_cancel_drops_pending_change(self):
        self.say("открой документы")
        self.say("удали файл старое")
        self.assertEqual(self.say("отмена").status, "ok")
        self.say("подтверждаю удаление")
        self.assertEqual(self.recycled, [])

    def test_delete_on_flash_warns_it_is_final(self):
        (self.flash / "черновик.txt").write_text("x", encoding="utf-8")
        self.say("что на первой флешке")
        result = self.say("удали файл черновик")
        self.assertIn("окончательным", result.message)

    def test_copy_photo_to_flash_is_verified(self):
        self.say("открой документы")
        result = self.say("скопируй фото на первую флешку")
        self.assertEqual(result.status, "needs_confirmation")
        self.assertIn("1 файл", result.message)
        self.assertEqual(self.say("подтверждаю копирование").status, "in_progress")
        events = self.wait_events()
        self.assertTrue(any("завершено и проверено" in event for event in events), events)
        self.assertEqual((self.flash / "фото.jpg").read_text(encoding="utf-8"), "данные фото.jpg")
        self.assertTrue((self.home / "Documents" / "фото.jpg").exists())

    def test_copy_pictures_folder_to_flash_and_conflict(self):
        self.say("скопируй фотографии на флешку")
        self.say("подтверждаю копирование")
        self.wait_events()
        self.assertTrue((self.flash / "Pictures" / "Лето" / "пляж.png").exists())
        result = self.say("скопируй фотографии на флешку")
        self.assertEqual(result.status, "error")
        self.assertIn("ничего не перезаписываю", result.message.lower())

    def test_interrupted_copy_resumes_after_restart(self):
        journal = CopyJournal(Path(self.temp.name, "copy-journal.json"))
        self.assistant.files.journal = journal
        target = self.flash / "Pictures"
        (target / "Лето").mkdir(parents=True)
        (target / "Лето" / "пляж.png").write_bytes(b"png")       # finished before the drive was pulled
        (target / "море.jpg").write_bytes(b"jpeg")                 # cut off in the middle
        journal.save(self.home / "Pictures", target, "«Pictures» в «флешка»")
        alerts = self.assistant.poll_due()
        self.assertTrue(any("не закончено" in alert for alert in alerts), alerts)
        self.assertFalse(any("не закончено" in alert for alert in self.assistant.poll_due()))
        result = self.say("продолжи копирование")
        self.assertEqual(result.status, "needs_confirmation")
        self.assertIn("Файлов всего: 2", result.message)
        self.assertEqual(self.say("да").status, "in_progress")
        events = self.wait_events()
        self.assertTrue(any("завершено и проверено" in event for event in events), events)
        self.assertEqual((target / "море.jpg").read_bytes(), b"jpeg" * 10)
        self.assertIsNone(journal.load())
        self.assertIn("нет", self.say("продолжи копирование").message)

    def test_resume_waits_for_the_drive_and_can_be_forgotten(self):
        journal = CopyJournal(Path(self.temp.name, "copy-journal.json"))
        self.assistant.files.journal = journal
        journal.save(self.home / "Pictures", Path(self.temp.name, "нет-флешки", "Pictures"), "«Pictures» на флешку")
        result = self.say("продолжи копирование")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("Подключите", result.message)
        self.say("забудь копирование")
        self.assertIsNone(journal.load())

    def test_move_within_drive_is_a_rename(self):
        self.say("открой документы")
        result = self.say("перемести письмо на рабочий стол")
        self.assertEqual(result.status, "needs_confirmation")
        self.assertEqual(self.say("подтверждаю перемещение").status, "ok")
        self.assertTrue((self.home / "Desktop" / "письмо.docx").exists())
        self.assertFalse((self.home / "Documents" / "письмо.docx").exists())

    def test_flash_space_eject_and_free_space(self):
        self.assertIn("ФЛЕШКА", self.say("сколько места на первой флешке").message)
        self.assertIn("свободно", self.say("сколько свободного места").message)
        result = self.say("безопасно извлеки первую флешку")
        self.assertEqual(result.status, "unverified")  # the fake volume stays listed
        self.volume = UsbVolume("F", "other", "", "NTFS", True)
        self.assertEqual(self.say("извлеки флешку").status, "unverified")

    def test_web_list_and_file_list_do_not_mix(self):
        self.say("открой документы")
        self.say("открой блокнот")  # a program, not a file from the list
        self.assertEqual(self.launched, [])


if __name__ == "__main__":
    unittest.main()
