import tempfile
import unittest
from pathlib import Path

from voiceassist.browser_state import save_active_tab, loaded_requested_page


class BrowserStateTests(unittest.TestCase):
    def test_active_page_is_confirmed_only_after_request(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "state.json")
            save_active_tab(path, "https://example.org/", "Пример", 100.0)
            self.assertFalse(loaded_requested_page(path, "https://example.org/", 101.0))
            self.assertTrue(loaded_requested_page(path, "https://example.org/", 99.0))
            self.assertFalse(loaded_requested_page(path, "https://other.org/", 99.0))

    def test_invalid_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "state.json")
            with self.assertRaises(ValueError):
                save_active_tab(path, "file:///secret", "Private", 100.0)
            self.assertFalse(path.exists())

    def test_page_state_does_not_store_query_tokens(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "state.json")
            save_active_tab(path, "https://example.org/watch?token=secret", "Видео", 100.0)
            self.assertNotIn("secret", path.read_text())
            self.assertFalse(loaded_requested_page(path, "https://example.org/watch?token=secret", 99.0))


if __name__ == "__main__":
    unittest.main()
