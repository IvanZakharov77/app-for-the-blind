import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from voiceassist.core import Assistant
from voiceassist.personal import PersonalStore, TimerBook
from voiceassist.system import SystemController
from voiceassist.window_ui import UiElement
from offwindows import setUpModule, tearDownModule  # noqa: F401


class KeyboardAPI:
    """Fake Windows: a focused element, a key log and a text field that receives typing."""

    def __init__(self):
        self.pressed, self.typed = [], []
        self.focus = UiElement("field", "Сообщение", "")
        self.menus = [UiElement("menu", "Файл"), UiElement("menu", "Правка")]
        self.opened = []

    def foreground(self): return (1, "Документ — Блокнот")
    def focused(self): return self.focus
    def controls(self, handle): return list(self.menus)
    def open_menu(self, element):
        self.opened.append(element.name)
        self.focus = UiElement("item", "Создать")
        return True

    def press(self, key, modifiers=()):
        self.pressed.append((key, tuple(modifiers)))
        if key == "down":
            self.focus = UiElement("item", "Второй пункт")
        if key == "delete" and modifiers == ():
            self.focus = UiElement(self.focus.role, self.focus.name, "")
        return True

    def type_text(self, text):
        self.typed.append(text)
        self.focus = UiElement(self.focus.role, self.focus.name, self.focus.value + text)
        return True


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.api = KeyboardAPI()
        self.assistant = Assistant(clock=lambda: datetime(2026, 10, 13, 12, 0), personal=PersonalStore(Path(self.root.name, "p.json")),
                                   timers=TimerBook(clock=lambda: 0.0), system=SystemController(self.api, wait=lambda _: None))

    def tearDown(self):
        self.root.cleanup()

    def test_dictation_types_punctuated_text_and_checks_the_field(self):
        result = self.assistant.handle("помощник напиши привет запятая как дела вопросительный знак")
        self.assertEqual(self.api.typed, ["Привет, как дела?"])
        self.assertEqual(result.status, "ok")
        self.assertIn("Привет, как дела?", result.message)

    def test_dictation_refuses_a_button_in_focus(self):
        self.api.focus = UiElement("button", "Отправить")
        result = self.assistant.handle("напиши привет")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("кнопка «Отправить»", result.message)
        self.assertEqual(self.api.typed, [])

    def test_list_navigation_reads_the_new_focus(self):
        result = self.assistant.handle("следующий пункт")
        self.assertEqual(self.api.pressed, [("down", ())])
        self.assertIn("Второй пункт", result.message)
        self.assistant.handle("предыдущий элемент")
        self.assertEqual(self.api.pressed[-1], ("tab", ("shift",)))

    def test_enter_and_focus_report(self):
        self.assertEqual(self.assistant.handle("нажми ввод").status, "ok")
        self.assertEqual(self.api.pressed, [("enter", ())])
        self.assertIn("Сообщение", self.assistant.handle("прочитай поле").message)

    def test_named_menu_opens_and_unknown_menu_lists_existing(self):
        result = self.assistant.handle("открой меню файл")
        self.assertEqual(self.api.opened, ["Файл"])
        self.assertIn("Создать", result.message)
        result = self.assistant.handle("открой меню вид")
        self.assertEqual(result.status, "error")
        self.assertIn("Файл, Правка", result.message)
        self.assistant.handle("открой меню")
        self.assertEqual(self.api.pressed[-1], ("f10", ()))

    def test_clearing_a_field_needs_yes(self):
        self.api.focus = UiElement("field", "Сообщение", "черновик")
        self.assertEqual(self.assistant.handle("очисти поле").status, "needs_confirmation")
        self.assertEqual(self.api.pressed, [])
        self.assertEqual(self.assistant.handle("нет").message, "Хорошо, не трогаю.")
        self.assistant.handle("очисти поле")
        result = self.assistant.handle("да")
        self.assertEqual(result.message, "Поле очищено.")
        self.assertEqual(self.api.pressed, [("a", ("control",)), ("delete", ())])

    def test_without_windows_keys_are_unavailable(self):
        assistant = Assistant(personal=PersonalStore(Path(self.root.name, "q.json")))
        if assistant.system is None:
            self.assertEqual(assistant.handle("следующий пункт").status, "unavailable")


if __name__ == "__main__":
    unittest.main()
