import unittest

from tests.test_telegram import Clock, logged_in
from voiceassist.telegram_call import button_matches


class FakeDesktop:
    def __init__(self, installed=True, open_windows=True, buttons=("Позвонить", "Принять", "Завершить")):
        self.installed, self.open_windows, self.buttons = installed, open_windows, buttons
        self.opened, self.pressed = [], []

    def exe(self):
        return "Telegram.exe" if self.installed else None

    def windows(self):
        return [1] if self.open_windows or self.opened else []

    def open_chat(self, person):
        self.opened.append(person)
        return self.installed

    def press(self, wanted, seconds=8.0):
        for name in self.buttons:
            if button_matches(name, wanted):
                self.pressed.append(name)
                return True
        return False


def with_desktop(**kwargs):
    clock = Clock()
    telegram, backend = logged_in(clock)
    desktop = FakeDesktop(**kwargs)
    telegram.calls.desktop = desktop
    return telegram, desktop, clock


class CallTests(unittest.TestCase):
    def test_call_by_name_opens_chat_and_presses_call(self):
        telegram, desktop, _ = with_desktop(open_windows=False)
        answer = telegram.handle("позвони маше петровой")
        self.assertEqual(desktop.opened, [1])
        self.assertEqual(desktop.pressed, ["Позвонить"])
        self.assertIn("Звоню Маша Петрова", answer)

    def test_call_in_telegram_words(self):
        telegram, desktop, _ = with_desktop()
        telegram.handle("позвони в телеграм сергею коту")
        self.assertEqual(desktop.opened, [4])

    def test_no_telegram_desktop(self):
        telegram, desktop, _ = with_desktop(installed=False, open_windows=False)
        self.assertIn("Telegram Desktop", telegram.handle("позвони маме"))

    def test_unknown_contact(self):
        telegram, desktop, _ = with_desktop()
        self.assertIn("Не нашла", telegram.handle("позвони виктору"))
        self.assertEqual(desktop.opened, [])

    def test_no_call_button_asks_for_check(self):
        telegram, desktop, _ = with_desktop(buttons=())
        self.assertIn("проверь Телеграм", telegram.handle("позвони маме"))

    def test_incoming_call_is_announced_and_answered(self):
        telegram, desktop, clock = with_desktop()
        telegram._call_rings(3, "")
        self.assertEqual(telegram.take_news(), ["Игорь, вам звонит Мама в Телеграм. Чтобы ответить, скажите: Вега, прими звонок."])
        self.assertEqual(telegram.handle("ответь"), "Соединяю.")
        self.assertEqual(desktop.pressed, ["Принять"])

    def test_reply_after_ring_is_message_again(self):
        telegram, desktop, clock = with_desktop()
        telegram._call_rings(3, "Мама")
        clock.now = 120
        telegram.last = (1, "Маша Петрова", "Привет")
        self.assertIn("что написать", telegram.handle("ответь"))
        self.assertEqual(desktop.pressed, [])

    def test_hang_up(self):
        telegram, desktop, _ = with_desktop()
        self.assertEqual(telegram.handle("положи трубку"), "Звонок завершён.")
        self.assertEqual(desktop.pressed, ["Завершить"])

    def test_answer_without_telegram_open(self):
        telegram, desktop, _ = with_desktop(open_windows=False)
        self.assertEqual(telegram.handle("прими звонок"), "Сейчас никто не звонит.")

    def test_reminder_to_call_is_not_a_call(self):
        telegram, desktop, _ = with_desktop()
        self.assertIsNone(telegram.handle("напомни завтра позвонить врачу"))

    def test_button_names(self):
        self.assertTrue(button_matches("Позвонить", ("позвонить",)))
        self.assertTrue(button_matches("Call", ("call",)))
        self.assertFalse(button_matches("Позвонить позже", ("принять",)))
