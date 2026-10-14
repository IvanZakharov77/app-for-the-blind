import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.test_browser_commands import FakeBridge
from tests.test_system import FakeAPI
from voiceassist.browser_commands import BrowserCommands
from voiceassist.core import Assistant
from voiceassist.personal import PersonalStore, TimerBook
from voiceassist.system import SystemController
from voiceassist.window_ui import UiElement, clean_name


class DialogAPI(FakeAPI):
    """A Notepad «save changes?» dialog in front."""

    def __init__(self):
        super().__init__()
        self.open_windows.append((5, "Блокнот"))
        self.front = (5, "Блокнот")
        self.items = [
            UiElement("text", "Вы хотите сохранить изменения в файле Безымянный?"),
            UiElement("button", "Сохранить"), UiElement("button", "Не сохранять"), UiElement("button", "Отмена"),
            UiElement("checkbox", "Больше не спрашивать", checked=False),
        ]
        self.pressed = []
        self.shown = []

    def controls(self, handle):
        return list(self.items) if handle == 5 else []

    def invoke(self, element):
        self.pressed.append(element.name)
        if element.name in ("Не сохранять", "Отмена", "Удалить всё"):
            self.open_windows = [w for w in self.open_windows if w[0] != 5]
            self.front = self.open_windows[0]
        return True

    def show(self, handle, how): self.shown.append((handle, how))
    def is_minimized(self, handle): return ("minimize" in [h for _, h in self.shown])
    def is_maximized(self, handle): return False
    def show_desktop(self): self.shown.append((0, "desktop"))


class WindowCommandTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.api = DialogAPI()
        self.now = [datetime(2026, 10, 13, 22, 0)]
        self.bridge = FakeBridge()
        self.assistant = Assistant(clock=lambda: self.now[0], personal=PersonalStore(Path(self.root.name, "p.json")),
                                   timers=TimerBook(), system=SystemController(self.api, wait=lambda _: None),
                                   web=BrowserCommands(self.bridge))

    def tearDown(self):
        self.root.cleanup()

    def say(self, phrase):
        return self.assistant.handle("помощник " + phrase)

    def test_read_dialog(self):
        result = self.say("прочитай окно")
        self.assertIn("сохранить изменения", result.message)
        self.assertIn("Кнопки: Сохранить; Не сохранять; Отмена", result.message)

    def test_list_and_press_by_number_and_name(self):
        result = self.say("что можно нажать")
        self.assertIn("4. Больше не спрашивать, флажок, не отмечен", result.message)
        result = self.say("нажми второй")
        self.assertEqual(self.api.pressed, ["Не сохранять"])
        self.assertEqual(result.status, "ok")
        self.assertIn("Окно закрылось", result.message)

    def test_press_by_name_and_unknown(self):
        self.say("нажми кнопку отмена")
        self.assertEqual(self.api.pressed, ["Отмена"])
        self.api.front = (5, "Блокнот")
        self.api.open_windows.append((5, "Блокнот"))
        result = self.say("нажми кнопку печать")
        self.assertEqual(result.status, "error")

    def test_risky_button_needs_confirmation(self):
        self.api.items.append(UiElement("button", "Удалить всё"))
        result = self.say("нажми удалить все")
        self.assertEqual(result.status, "needs_confirmation")
        self.assertEqual(self.api.pressed, [])
        result = self.say("подтверждаю нажатие")
        self.assertEqual(self.api.pressed, ["Удалить всё"])
        self.assertEqual(result.status, "ok")

    def test_chrome_in_front_sends_buttons_to_page(self):
        self.api.front = (2, "Фильмы — Google Chrome")
        self.bridge.answers["page.list"] = {"items": [{"number": 1, "name": "Войти"}], "total": 1}
        result = self.say("какие здесь кнопки")
        self.assertIn("Войти", result.message)
        self.say("нажми кнопку один")
        self.assertEqual(self.bridge.calls[-1], ("page.activate", {"kind": "buttons", "number": 1}))
        self.assertEqual(self.api.pressed, [])

    def test_minimize_and_desktop(self):
        self.assertEqual(self.say("сверни окно").status, "ok")
        self.say("сверни все окна")
        self.assertEqual(self.api.shown[-1], (0, "desktop"))

    def test_clean_name(self):
        self.assertEqual(clean_name("&Сохранить"), "Сохранить")
        self.assertEqual(clean_name("Не со&хранять\tAlt+N"), "Не сохранять")
        self.assertEqual(clean_name("R&&D"), "R&D")


if __name__ == "__main__":
    unittest.main()
