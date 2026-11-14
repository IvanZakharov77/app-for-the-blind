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
    def test_new_message_is_read_at_once_without_reply_hint(self):
        telegram, backend = logged_in()
        backend.listener(1, "Маша Петрова", "Привет, ты дома?")
        self.assertEqual(telegram.take_news(), ["Сообщение от Маша Петрова: Привет, ты дома?"])
        self.assertIsNone(telegram.waiting)
        self.assertEqual(backend.read, [1])
        self.assertEqual(telegram.handle("повтори сообщение"), "Сообщение от Маша Петрова: Привет, ты дома?")

    def test_polite_in_a_talk_and_ask_first_setting(self):
        telegram, backend = logged_in()
        telegram.polite = True
        backend.listener(1, "Маша Петрова", "Привет")
        said = telegram.take_news()[0]
        self.assertTrue(said.startswith("Прошу прощения, Игорь. Сообщение от Маша Петрова: Привет"), said)
        self.assertNotIn("ответ", said)
        telegram.polite = False
        telegram.handle("спрашивай перед чтением")
        backend.listener(1, "Маша Петрова", "Ещё")
        self.assertEqual(telegram.take_news(), ["Игорь, вам пришло сообщение в Телеграм от Маша Петрова. Прочитать или нет?"])
        self.assertTrue(telegram.answer("да").startswith("Сообщение от Маша Петрова: Ещё"))
        backend.listener(1, "Маша Петрова", "Ау")
        telegram.take_news()
        self.assertIn("Хорошо", telegram.answer("нет"))

    def test_nothing_while_a_command_is_said(self):
        telegram, backend = logged_in()
        telegram.busy = True
        backend.listener(1, "Маша Петрова", "Привет")
        self.assertEqual(telegram.take_news(), [])
        telegram.busy = False
        self.assertEqual(len(telegram.take_news()), 1)

    def test_reply_dictate_confirm_send(self):
        telegram, backend = logged_in()
        backend.listener(1, "Маша Петрова", "Привет")
        telegram.take_news()
        telegram.answer("да")
        self.assertEqual(telegram.handle("ответь"), "Хорошо, Игорь, что написать Маша Петрова?")
        backend.listener(3, "Мама", "Ты где")
        self.assertEqual(telegram.take_news(), [])  # nothing read aloud over the dictation
        self.assertEqual(telegram.answer("я дома приходи"),
                         "Вы продиктовали: Я дома приходи. Отправить Маша Петрова? Скажите: да, нет или исправить.")
        self.assertIn("Я дома приходи", telegram.answer("повтори что я продиктовал"))
        self.assertEqual(telegram.answer("исправить"), "Диктуйте сообщение заново.")
        telegram.answer("буду через час")
        self.assertEqual(backend.sent, [])  # nothing goes without «да»
        self.assertEqual(telegram.answer("да"), "Сообщение отправлено.")
        self.assertEqual(backend.sent, [(1, "Буду через час")])
        self.assertIsNone(telegram.waiting)

    def test_send_by_contact_name_choose_and_cancel(self):
        telegram, backend = logged_in()
        self.assertIn("что написать Мама", telegram.handle("отправь сообщение маме"))
        self.assertEqual(telegram.waiting["person"], 3)
        self.assertEqual(telegram.cancel(), "Отменила, сообщение не отправлено.")
        self.assertIn("Маша Петрова", telegram.handle("отправь сообщение через телеграм маше"))
        telegram.answer("отмени отправку")
        self.assertIn("Сергей Кот", telegram.handle("отправь сообщение контакту сергей кот"))
        telegram.cancel()
        self.assertIn("Нашла несколько", telegram.handle("напиши сообщение сергею"))
        self.assertIn("что написать", telegram.answer("второй"))
        telegram.cancel()
        self.assertIn("что написать Маша", telegram.handle("ответь маше"))
        telegram.cancel()
        self.assertEqual(backend.sent, [])

    def test_name_and_text_in_one_phrase(self):
        telegram, backend = logged_in()
        backend.people.append((5, "Артем Рева"))
        self.assertEqual(telegram.handle("отправь сообщение артем рева привет чувак"),
                         "Вы продиктовали: Привет чувак. Отправить Артем Рева? Скажите: да, нет или исправить.")
        self.assertEqual(backend.sent, [])
        self.assertEqual(telegram.answer("да"), "Сообщение отправлено.")
        self.assertEqual(backend.sent, [(5, "Привет чувак")])
        self.assertIn("Отправить Мама", telegram.handle("напиши сообщение маме я скоро буду через телеграм"))
        self.assertEqual(telegram.waiting["text"], "Я скоро буду")
        telegram.cancel()
        self.assertIn("Отправить Сергей Кот", telegram.handle("отправь сообщение контакту сергей кот как дела"))
        telegram.cancel()
        self.assertIn("Нашла несколько", telegram.handle("отправь сообщение сергею привет"))
        self.assertIn("Отправить", telegram.answer("второй"))
        telegram.cancel()
        self.assertIn("что написать Артем Рева", telegram.handle("отправь сообщение артему реве"))
        telegram.cancel()
        self.assertIn("Не нашла", telegram.handle("отправь сообщение гене привет"))
        self.assertEqual(backend.sent, [(5, "Привет чувак")])

    def test_send_without_the_word_message(self):
        telegram, backend = logged_in()
        backend.people.append((5, "Артем Рева"))
        self.assertIn("Отправить Артем Рева", telegram.handle("отправь артему реве привет чувак"))
        telegram.cancel()
        self.assertIn("Отправить Мама", telegram.handle("напиши маме я скоро буду"))
        telegram.cancel()
        self.assertIsNone(telegram.handle("напиши привет"))  # typing into a field
        backend.listener(1, "Маша Петрова", "Ты придёшь?")
        telegram.take_news()
        self.assertEqual(telegram.handle("ответь да приду"),
                         "Вы продиктовали: Да приду. Отправить Маша Петрова? Скажите: да, нет или исправить.")
        telegram.cancel()
        self.assertEqual(backend.sent, [])

    def test_alias(self):
        telegram, _backend = logged_in()
        self.assertEqual(telegram.handle("запомни сын это сергей кот"), "Запомнила: сын это Сергей Кот.")
        self.assertIn("что написать Сергей Кот", telegram.handle("отправь сообщение сыну"))
        telegram.cancel()
        self.assertIsNone(telegram.handle("запомни что завтра врач это важно"))  # a note, not a contact

    def test_who_wrote_and_from(self):
        telegram, backend = logged_in()
        self.assertEqual(telegram.handle("кто мне написал"),
                         "Вам написали: Маша Петрова, 2 сообщения. Скажите, например: прочитай сообщения от Маша Петрова.")
        backend.history = lambda person, count: [(False, "Привет"), (True, "Привет, как ты"), (False, "Хорошо")]
        self.assertEqual(telegram.handle("прочитай сообщения от маши"),
                         "Последние сообщения с Маша Петрова: Привет Вы: Привет, как ты Хорошо")

    def test_waiting_expires(self):
        clock = Clock()
        telegram, backend = logged_in(clock)
        telegram.handle("отправь сообщение маме")
        clock.now += 60
        self.assertEqual(telegram.expired(), "Сообщение не отправлено.")
        _backend = backend
        telegram.handle("спрашивай перед чтением")
        backend.listener(1, "Маша Петрова", "Привет")
        telegram.take_news()
        clock.now += 60
        self.assertEqual(telegram.expired(), "")  # an unanswered «Прочитать?» just waits for «прочитай сообщения»
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
            telegram.background = False
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


class OneTimeWindowTests(unittest.TestCase):
    def make(self, folder):
        telegram = Telegram(Path(folder), lambda session: FakeBackend(), lambda: "", log=lambda message: None)
        telegram.background = False
        return telegram

    def test_window_opens_once_after_this_update_only(self):
        with tempfile.TemporaryDirectory() as folder:
            opened = []
            telegram = self.make(folder)
            self.assertTrue(telegram_link.offer_window_once(telegram, telegram_link.ONE_TIME_VERSION, lambda: opened.append(1), delay=0))
            self.assertEqual(opened, [1])
            self.assertIn("окно подключения", " ".join(telegram.take_news()))
            telegram_link.offer_window_once(self.make(folder), telegram_link.ONE_TIME_VERSION, lambda: opened.append(1), delay=0)
            self.assertEqual(opened, [1])  # a restart does not open it again

    def test_no_window_in_other_versions_or_when_connected(self):
        with tempfile.TemporaryDirectory() as folder:
            opened = []
            self.assertFalse(telegram_link.offer_window_once(self.make(folder), "0.7.28", lambda: opened.append(1), delay=0))
            (Path(folder) / telegram_link.SESSION_FILE).write_bytes(telegram_link.protect(b"saved"))
            telegram_link.offer_window_once(self.make(folder), telegram_link.ONE_TIME_VERSION, lambda: opened.append(1), delay=0)
            self.assertEqual(opened, [])

    def test_connect_command_opens_the_window(self):
        with tempfile.TemporaryDirectory() as folder:
            opened = []
            telegram = self.make(folder)
            telegram.spawn_window = lambda: opened.append(1)
            self.assertIn("окно подключения", telegram.handle("подключи телеграм"))
            self.assertEqual(opened, [1])
            self.assertIsNone(telegram.waiting)

    def test_shortcut_opens_the_window_until_connected(self):
        with tempfile.TemporaryDirectory() as folder:
            opened = []
            original = telegram_link.api_keys
            telegram_link.api_keys = lambda: (1, "hash")
            try:
                self.assertTrue(telegram_link.shortcut_window(Path(folder), lambda: opened.append(1)))
                self.assertTrue(telegram_link.shortcut_window(Path(folder), lambda: opened.append(1)))  # again and again
                (Path(folder) / telegram_link.SESSION_FILE).write_bytes(b"x")
                self.assertFalse(telegram_link.shortcut_window(Path(folder), lambda: opened.append(1)))
            finally:
                telegram_link.api_keys = original
            self.assertEqual(opened, [1, 1])

    def test_installer_window_marks_itself(self):
        with tempfile.TemporaryDirectory() as folder:
            opened = []
            telegram_link.mark_window_shown(Path(folder))
            telegram_link.offer_window_once(self.make(folder), telegram_link.ONE_TIME_VERSION, lambda: opened.append(1), delay=0)
            self.assertEqual(opened, [])
