import tempfile
import unittest
from pathlib import Path

from voiceassist import telegram_link
from voiceassist.telegram_link import Telegram, match_contacts, phone_number, readable, spoken_digits


class FakeBackend:
    def __init__(self, session=""):
        self.session_text = session
        self.sent, self.read = [], []
        self.listener = None
        self.code_phone = None
        self.code_result = "ok"
        self.people = [(1, "Маша Петрова"), (2, "Sergey Ivanov"), (3, "Мама"), (4, "Сергей Кот")]

    def connect(self):
        return bool(self.session_text)

    def send_code(self, phone):
        self.code_phone = phone

    def sign_in(self, code):
        self.code = code
        if self.code_result == "ok":
            self.session_text = "logged-in"
        return self.code_result

    def session(self):
        return self.session_text

    def listen(self, on_message):
        self.listener = on_message

    def contacts(self):
        return self.people

    def send(self, person, text):
        self.sent.append((person, text))

    def unread(self):
        return [(1, "Маша Петрова", ["Привет", "Как дела?"])]

    def mark_read(self, person):
        self.read.append(person)

    def log_out(self):
        pass


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def logged_in(clock=None):
    backend = FakeBackend("saved")
    telegram = Telegram(None, lambda session: backend, user_name=lambda: "Игорь", clock=clock or Clock())
    telegram.backend = backend
    telegram._listen()
    telegram._contacts = backend.people
    return telegram, backend


class TelegramTests(unittest.TestCase):
    def test_new_message_is_read_with_the_name(self):
        telegram, backend = logged_in()
        backend.listener(1, "Маша Петрова", "Привет, ты дома?")
        news = telegram.take_news()
        self.assertEqual(len(news), 1)
        self.assertTrue(news[0].startswith("Игорь, вам сообщение от Маша Петрова: Привет, ты дома?"))
        self.assertIn("Вега, ответь", news[0])  # the hint, once
        backend.listener(1, "Маша Петрова", "Ау")
        self.assertNotIn("ответь", telegram.take_news()[0])

    def test_reply_dictate_send(self):
        telegram, backend = logged_in()
        backend.listener(1, "Маша Петрова", "Привет")
        telegram.take_news()
        self.assertEqual(telegram.handle("ответь"), "Хорошо, Игорь, диктуйте сообщение для Маша Петрова.")
        self.assertEqual(telegram.take_news(), [])  # nothing read aloud over the dictation
        self.assertEqual(telegram.answer("я дома приходи"), "Отправила Маша Петрова.")
        self.assertEqual(backend.sent, [(1, "Я дома приходи")])
        self.assertIsNone(telegram.waiting)

    def test_send_by_contact_name_and_cancel(self):
        telegram, backend = logged_in()
        self.assertIn("диктуйте", telegram.handle("отправь сообщение маме"))
        self.assertEqual(telegram.waiting["person"], 3)
        self.assertEqual(telegram.cancel(), "Отменила.")
        self.assertIsNone(telegram.waiting)
        self.assertIn("для Маша Петрова", telegram.handle("отправь сообщение через телеграм маше"))
        telegram.answer("отмена")
        self.assertIn("для Сергей Кот", telegram.handle("отправь сообщение контакту сергей кот"))
        telegram.cancel()
        self.assertIn("Нашла несколько", telegram.handle("напиши сообщение сергею"))
        self.assertEqual(backend.sent, [])

    def test_waiting_expires(self):
        clock = Clock()
        telegram, backend = logged_in(clock)
        telegram.handle("отправь сообщение маме")
        clock.now += 60
        self.assertEqual(telegram.expired(), "Сообщение не отправлено.")
        self.assertEqual(backend.sent, [])

    def test_typing_command_is_not_taken(self):
        telegram, _backend = logged_in()
        self.assertIsNone(telegram.handle("напиши привет"))
        self.assertIsNone(telegram.handle("который час"))

    def test_unread(self):
        telegram, backend = logged_in()
        answer = telegram.handle("прочитай сообщения")
        self.assertTrue(answer.startswith("От Маша Петрова: Привет Как дела?"))
        self.assertEqual(backend.read, [1])

    def test_voice_login(self):
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as folder:
            telegram = Telegram(Path(folder), lambda session: backend, user_name=lambda: "", clock=Clock())
            self.assertIn("номер телефона", telegram.handle("подключи телеграм"))
            self.assertIn("3 8 0 5 0 1 2 3 4 5 6 7", telegram.answer("ноль пятьдесят сто двадцать три сорок пять шестьдесят семь"))
            self.assertIn("код", telegram.answer("да"))
            self.assertEqual(backend.code_phone, "+380501234567")
            self.assertIn("подключён", telegram.answer("один два три четыре пять"))
            self.assertEqual(backend.code, "12345")
            self.assertTrue(telegram.ready)
            self.assertEqual(telegram.saved_session(), "logged-in")  # survives restarts and updates

    def test_not_configured(self):
        telegram = Telegram(None, None)
        self.assertEqual(telegram.handle("подключи телеграм"), "Телеграм в этой версии Веги не настроен.")
        self.assertIsNone(telegram.handle("ответь"))


class ContactsTests(unittest.TestCase):
    def test_contacts_asked_once_a_day_and_kept(self):
        calls = []
        backend = FakeBackend("saved")
        backend.contacts = lambda: calls.append(1) or [(1, "Маша")]
        with tempfile.TemporaryDirectory() as folder:
            telegram = Telegram(Path(folder), lambda session: backend, clock=Clock())
            telegram.backend, telegram.wall = backend, lambda: 1000.0
            telegram._refresh_contacts()
            telegram._refresh_contacts()
            self.assertEqual(len(calls), 1)
            again = Telegram(Path(folder), lambda session: backend, clock=Clock())  # after a restart
            again.backend, again.wall = backend, lambda: 1000.0 + 3600
            again._refresh_contacts()
            self.assertEqual(len(calls), 1)
            self.assertEqual(again._contacts, [(1, "Маша")])
            again.wall = lambda: 1000.0 + 25 * 3600
            again._refresh_contacts()
            self.assertEqual(len(calls), 2)
            again._arrived(7, "Петя", "Привет")  # a new person who wrote is added without a request
            self.assertIn((7, "Петя"), again._contacts)
            self.assertEqual(len(calls), 2)


class HelperTests(unittest.TestCase):
    def test_names_and_numbers(self):
        self.assertEqual(readable("Sergey Ivanov"), "Сергей Иванов")
        self.assertEqual(spoken_digits("плюс три восемь ноль пятьдесят"), "38050")
        self.assertEqual(phone_number("восемь девятьсот шестнадцать сто двадцать три сорок пять шестьдесят семь"), "+79161234567")
        self.assertIsNone(phone_number("сто"))
        people = [(1, "Маша Петрова"), (2, "Олег")]
        self.assertEqual(match_contacts("маше", people), [(1, "Маша Петрова")])
        self.assertEqual(match_contacts("олегу", people), [(2, "Олег")])
        self.assertEqual(match_contacts("ивану", people), [])

    def test_no_keys_no_telegram(self):
        import importlib.util
        if importlib.util.find_spec("voiceassist.telegram_keys") is None:  # the build adds the keys
            self.assertIsNone(telegram_link.api_keys())
