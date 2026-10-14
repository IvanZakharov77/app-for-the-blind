import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from voiceassist.core import Assistant, parse_clock_time
from voiceassist.personal import PersonalStore, TimerBook
from voiceassist.system import Battery, SystemController, VK_VOLUME_UP
from offwindows import setUpModule, tearDownModule  # noqa: F401


class FakeAPI:
    def __init__(self):
        self.keys, self.shutdowns, self.launched, self.closed = [], [], [], []
        self.open_windows = [(1, "Документ — Блокнот"), (2, "Google Chrome")]
        self.front = (1, "Документ — Блокнот")
        self.power = Battery(False, 47, True)
        self.online = True
        self.close_works = True

    def battery(self): return self.power
    def connected(self): return self.online
    def press_key(self, key): self.keys.append(key)
    def shutdown(self, args): self.shutdowns.append(args); return 0
    def windows(self): return list(self.open_windows)
    def foreground(self): return self.front
    def activate(self, handle):
        self.front = next(w for w in self.open_windows if w[0] == handle)
        return True
    def close(self, handle):
        self.closed.append(handle)
        if self.close_works:
            self.open_windows = [w for w in self.open_windows if w[0] != handle]
    def exists(self, handle): return any(w[0] == handle for w in self.open_windows)
    def launch(self, target):
        self.launched.append(target)
        if target == "winword.exe":
            raise OSError("not installed")
        self.open_windows.append((99, "Безымянный — Блокнот"))


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.api = FakeAPI()
        self.now = [datetime(2026, 10, 13, 22, 0)]
        self.ticks = [0.0]
        self.assistant = Assistant(clock=lambda: self.now[0], personal=PersonalStore(Path(self.root.name, "p.json")),
                                   timers=TimerBook(clock=lambda: self.ticks[0]),
                                   system=SystemController(self.api, wait=lambda _: None))

    def tearDown(self):
        self.root.cleanup()

    def test_battery_network_and_volume(self):
        self.assertIn("47 процентов", self.assistant.handle("какой заряд батареи").message)
        self.assertIn("от батареи", self.assistant.handle("заряд батареи").message)
        self.assertIn("есть", self.assistant.handle("есть ли интернет").message)
        self.api.online = False
        self.assertIn("нет", self.assistant.handle("есть ли интернет").message)
        self.assistant.handle("громче")
        self.assertEqual(self.api.keys, [VK_VOLUME_UP] * 5)

    def test_shutdown_needs_its_own_confirmation_and_can_be_aborted(self):
        self.assertEqual(self.assistant.handle("выключи компьютер").status, "needs_confirmation")
        self.assertEqual(self.api.shutdowns, [])
        self.assertEqual(self.assistant.handle("подтверждаю перезагрузку").status, "unknown")
        self.assertEqual(self.api.shutdowns, [])
        self.assertEqual(self.assistant.handle("подтверждаю выключение").status, "in_progress")
        self.assertEqual(self.api.shutdowns, [["/s", "/t", "30"]])
        self.assertEqual(self.assistant.handle("отмени выключение").status, "ok")
        self.assertEqual(self.api.shutdowns[-1], ["/a"])

    def test_late_confirmation_is_refused(self):
        self.assistant.handle("перезагрузи компьютер")
        self.now[0] = datetime(2026, 10, 13, 22, 2)
        self.assertEqual(self.assistant.handle("подтверждаю перезагрузку").status, "error")
        self.assertEqual(self.api.shutdowns, [])

    def test_program_window_is_verified(self):
        result = self.assistant.handle("открой блокнот")
        self.assertEqual(result.status, "ok")
        self.assertIn("Безымянный", result.message)
        self.assertEqual(self.assistant.handle("открой ворд").status, "error")

    def test_windows_list_switch_and_close(self):
        listing = self.assistant.handle("какие окна открыты").message
        self.assertIn("1: Документ — Блокнот", listing)
        self.assertIn("2: Google Chrome", listing)
        self.assertIn("Chrome", self.assistant.handle("переключись на окно два").message)
        self.assistant.handle("какие окна открыты")
        self.assertIn("Блокнот", self.assistant.handle("номер один").message)
        self.assertIn("Chrome", self.assistant.handle("переключись на окно номер два").message)
        self.assertIn("Chrome", self.assistant.handle("какое окно активно").message)
        self.assertEqual(self.assistant.handle("переключись на окно блокнот").status, "ok")
        self.assertEqual(self.assistant.handle("переключись на окно десять").status, "error")
        self.assertEqual(self.assistant.handle("закрой окно").status, "ok")
        self.api.close_works = False
        self.api.front = (2, "Google Chrome")
        self.assertEqual(self.assistant.handle("закрой окно").status, "unverified")

    def test_notes_are_deleted_only_after_confirmation(self):
        for note in ("купить хлеб", "позвонить"):
            self.assistant.handle("запиши заметку " + note)
            self.assistant.handle("да")
        self.assertEqual(self.assistant.handle("удали последнюю заметку").status, "needs_confirmation")
        self.assertIn("позвонить", self.assistant.handle("прочитай заметки").message)
        self.assistant.handle("удали последнюю заметку")
        self.assertEqual(self.assistant.handle("подтверждаю удаление").status, "ok")
        self.assertNotIn("позвонить", self.assistant.handle("прочитай заметки").message)
        self.assistant.handle("удали все заметки")
        self.assistant.handle("подтверждаю удаление")
        self.assertEqual(self.assistant.handle("прочитай заметки").message, "Заметок нет.")

    def test_timer_remaining_and_cancel(self):
        self.assistant.handle("поставь таймер на пять минут")
        self.ticks[0] = 90.0
        self.assertIn("3 минуты 30 секунд", self.assistant.handle("сколько осталось на таймере").message)
        self.assertEqual(self.assistant.handle("отмени таймер").status, "ok")
        self.ticks[0] = 400.0
        self.assertEqual(self.assistant.poll_due(), ())

    def test_alarm_tomorrow_morning(self):
        result = self.assistant.handle("поставь будильник на семь тридцать")
        self.assertIn("завтра 07:30", result.message)
        self.now[0] = datetime(2026, 10, 14, 7, 30)
        self.assertEqual(self.assistant.poll_due(), ("Напоминание: будильник на 07:30.",))

    def test_alarm_evening_today(self):
        self.now[0] = datetime(2026, 10, 13, 9, 0)
        self.assertIn("сегодня 20:00", self.assistant.handle("разбуди меня в восемь вечера").message)


class ClockParsingTests(unittest.TestCase):
    def test_spoken_times(self):
        self.assertEqual(parse_clock_time("семь тридцать"), (7, 30))
        self.assertEqual(parse_clock_time("семь утра"), (7, 0))
        self.assertEqual(parse_clock_time("девятнадцать ноль ноль"), (19, 0))
        self.assertEqual(parse_clock_time("восемь часов пятнадцать минут вечера"), (20, 15))
        self.assertIsNone(parse_clock_time("двадцать пять"))
        self.assertIsNone(parse_clock_time("рано"))


class WindowsOnlyTests(unittest.TestCase):
    def test_system_commands_are_honest_off_windows(self):
        import sys
        if sys.platform == "win32":
            self.skipTest("Windows")
        result = Assistant().handle("какой заряд батареи")
        self.assertEqual(result.status, "unavailable")


if __name__ == "__main__":
    unittest.main()
