import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from voiceassist.personal import PersonalStore, TimerBook
from voiceassist.browser import BrowserOutcome, SitesStore
from voiceassist.drives import UsbVolume
from voiceassist.usb_copy import UsbCopyController
from voiceassist.optical import OpticalProbe

from voiceassist.core import Assistant


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.assistant = Assistant(clock=lambda: datetime(2026, 10, 13, 14, 5))

    def test_time_uses_injected_system_clock(self):
        self.assertIn("14:05", self.assistant.handle("Который час?").message)

    def test_help_offers_five_or_fewer_available_commands(self):
        result = self.assistant.handle("Какие команды мне сейчас доступны?")
        self.assertEqual(result.status, "ok")
        self.assertLessEqual(len(result.options), 5)
        self.assertTrue(result.options)

    def test_unknown_command_is_not_claimed_successful(self):
        result = self.assistant.handle("Сотри всё")
        self.assertEqual(result.status, "unknown")
        self.assertNotIn("готово", result.message.lower())

    def test_repeat_reuses_last_message(self):
        previous = self.assistant.handle("Который час?")
        self.assertEqual(self.assistant.handle("Повтори").message, previous.message)

    def test_context_help_paginates(self):
        first = self.assistant.handle("Помоги")
        second = self.assistant.handle("Дальше")
        self.assertNotEqual(first.options, second.options)

    def test_cancel_without_operation_is_honest(self):
        self.assertEqual(self.assistant.handle("Отмена").status, "unavailable")

    def test_directory_command_reads_actual_files(self):
        with TemporaryDirectory() as root:
            Path(root, "заметка.txt").write_text("пример")
            assistant = Assistant(current_directory=Path(root))
            self.assertIn("заметка.txt", assistant.handle("Что в папке?").message)

    def test_removable_drives_command_names_detected_letters(self):
        assistant = Assistant(drive_provider=lambda: (
            UsbVolume("E", "guid-e", "Фильмы", "FAT32", True),
            UsbVolume("F", "guid-f", "Фото", "NTFS", True)))
        result = assistant.handle("Какие флешки подключены?")
        self.assertEqual(result.status, "ok")
        self.assertIn("E", result.message)
        self.assertIn("F", result.message)
        self.assertIn("Фильмы", result.message)

    def test_optical_disc_command_does_not_start_usb_copy(self):
        assistant = Assistant(drive_provider=lambda: (UsbVolume("E", "usb-e", "Фильмы", "FAT32", True),))
        result = assistant.handle("Запиши на диск папку Фотографии")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("CD/DVD", result.message)

    def test_optical_request_checks_writer_separately_from_usb(self):
        assistant = Assistant(optical_probe=lambda: OpticalProbe(1, 0, 0))
        result = assistant.handle("Запиши на диск папку Фото")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("записывающий привод", result.message.casefold())

    def test_optical_capability_question_reports_writer_and_media(self):
        assistant = Assistant(optical_probe=lambda: OpticalProbe(1, 1, 0))
        result = assistant.handle("Есть ли записывающий привод?")
        self.assertEqual(result.status, "ok")
        self.assertIn("носитель", result.message)

    def test_voice_copy_requires_named_plan_and_confirmation(self):
        with TemporaryDirectory() as root:
            first = Path(root, "first")
            second = Path(root, "second")
            first.mkdir()
            second.mkdir()
            (first / "photo.txt").write_text("x")
            volumes = (UsbVolume("E", "e", "Фото", "NTFS", True),
                       UsbVolume("F", "f", "Копия", "NTFS", True))
            paths = {"e": first, "f": second}
            controller = UsbCopyController(lambda: volumes, path_for_volume=lambda v: paths[v.guid])
            assistant = Assistant(drive_provider=lambda: volumes, usb_copy=controller)
            self.assertEqual(assistant.handle("Подтверждаю копирование с первой на вторую").status, "unavailable")
            self.assertEqual(assistant.handle("Какие флешки подключены?").status, "ok")
            self.assertEqual(assistant.handle("Скопируй всё с первой на вторую").status, "needs_confirmation")
            self.assertFalse(list(second.iterdir()))
            self.assertEqual(assistant.handle("Подтверждаю копирование с первой на вторую").status, "in_progress")
            controller.worker.join(5)
            self.assertTrue((second / "VoiceAssist Copy 1" / "photo.txt").exists())

    def test_external_disk_term_routes_to_usb_listing(self):
        volumes = (UsbVolume("E", "e", "DATA", "NTFS", True),)
        assistant = Assistant(drive_provider=lambda: volumes)
        result = assistant.handle("Какие внешние диски подключены?")
        self.assertEqual(result.status, "ok")
        self.assertIn("E", result.message)

    def test_copy_progress_question_uses_copy_controller(self):
        class Copy:
            def progress_status(self):
                from voiceassist.usb_copy import CopyAction
                return CopyAction("ok", "Проверено 2 из 5 файлов.")
        assistant = Assistant(usb_copy=Copy())
        result = assistant.handle("Сколько осталось копировать?")
        self.assertEqual(result.status, "ok")
        self.assertIn("2 из 5", result.message)

    def test_local_note_and_calculation_commands(self):
        with TemporaryDirectory() as root:
            assistant = Assistant(personal=PersonalStore(Path(root, "data.json")))
            # Free text is read back first (ТЗ: переспросить до сохранения).
            self.assertEqual(assistant.handle("Запиши заметку купить хлеб").status, "needs_confirmation")
            self.assertEqual(assistant.handle("Да").status, "ok")
            self.assertIn("купить хлеб", assistant.handle("Прочитай заметки").message)
            self.assertIn("19", assistant.handle("Сколько будет 12 плюс 7?").message)

    def test_timer_announces_only_after_deadline(self):
        now = [0.0]
        assistant = Assistant(timers=TimerBook(clock=lambda: now[0]))
        self.assertEqual(assistant.handle("Поставь таймер на 1 минуту").status, "ok")
        self.assertEqual(assistant.poll_due(), ())
        now[0] = 60.0
        self.assertEqual(assistant.poll_due(), ("Таймер завершён.",))

    def test_repeat_after_copy_final_uses_actual_final_result(self):
        class Copy:
            def poll_events(self): return ("Копирование завершено и проверено.",)
        assistant = Assistant(usb_copy=Copy())
        self.assertEqual(assistant.poll_due(), ("Копирование завершено и проверено.",))
        self.assertEqual(assistant.handle("Повтори").message, "Копирование завершено и проверено.")

    def test_conversion_and_network_question_are_honest(self):
        self.assertIn("2000 метров", self.assistant.handle("Переведи 2 километра в метры").message)
        weather = self.assistant.handle("Какая погода?")
        self.assertEqual(weather.status, "unavailable")

    def test_reminder_command_uses_calendar_clock(self):
        with TemporaryDirectory() as root:
            now = [datetime(2026, 10, 13, 14, 0)]
            assistant = Assistant(clock=lambda: now[0], personal=PersonalStore(Path(root, "data.json")))
            self.assertEqual(assistant.handle("Напомни через 1 минуту позвонить").status, "needs_confirmation")
            self.assertEqual(assistant.handle("Да").status, "ok")
            self.assertIn("позвонить", assistant.handle("Какие напоминания?").message)
            now[0] = datetime(2026, 10, 13, 14, 1)
            self.assertEqual(assistant.poll_due(), ("Напоминание: позвонить.",))

    def test_chrome_and_saved_site_report_distinct_outcomes(self):
        class Browser:
            def open_browser(self):
                return BrowserOutcome("ok", "Процесс Chrome запущен.")

            def open_site(self, url):
                return BrowserOutcome("unverified", "Адрес передан Chrome. Загрузка страницы пока не проверена.")

        with TemporaryDirectory() as root:
            sites = SitesStore(Path(root, "sites.json"))
            sites.set("HDRezka", "https://example.org/")
            assistant = Assistant(browser=Browser(), sites=sites)
            self.assertEqual(assistant.handle("Открой Chrome").status, "ok")
            result = assistant.handle("Открой HDRezka")
            self.assertEqual(result.status, "unverified")
            self.assertIn("не проверена", result.message)


if __name__ == "__main__":
    unittest.main()
