import tempfile
import unittest
from pathlib import Path

from voiceassist.browser import BrowserController, SitesStore
from voiceassist.browser_state import save_active_tab


class BrowserTests(unittest.TestCase):
    def test_chrome_start_is_verified_by_process_probe(self):
        calls = []
        controller = BrowserController(lambda: Path("chrome.exe"), lambda args: calls.append(args), lambda: True, wait=lambda _: None)
        result = controller.open_browser()
        self.assertEqual(result.status, "ok")
        self.assertEqual(calls, [["chrome.exe"]])

    def test_site_launch_does_not_claim_page_loaded(self):
        calls = []
        controller = BrowserController(lambda: Path("chrome.exe"), lambda args: calls.append(args), lambda: True, wait=lambda _: None)
        result = controller.open_site("https://example.org/")
        self.assertEqual(result.status, "unverified")
        self.assertIn("не проверена", result.message)
        self.assertEqual(calls, [["chrome.exe", "https://example.org/"]])

    def test_site_is_confirmed_from_fresh_extension_report(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root, "browser_state.json")
            def launch(_args):
                save_active_tab(state, "https://example.org/", "Пример", 101.0)
            controller = BrowserController(lambda: Path("chrome.exe"), launch, lambda: True,
                                           wait=lambda _: None, page_state_path=state, clock=lambda: 100.0)
            result = controller.open_site("https://example.org/")
            self.assertEqual(result.status, "ok")
            self.assertIn("загружена", result.message)

    def test_no_chrome_and_no_default_browser_is_error(self):
        def refuse(url):
            raise OSError("no browser")
        controller = BrowserController(lambda: None, lambda args: None, lambda: False, wait=lambda _: None, default_opener=refuse)
        self.assertEqual(controller.open_browser().status, "error")

    def test_no_chrome_opens_site_in_default_browser(self):
        opened = []
        controller = BrowserController(lambda: None, lambda args: None, lambda: False, wait=lambda _: None, default_opener=opened.append)
        self.assertEqual(controller.open_site("https://www.youtube.com/").status, "unverified")
        self.assertEqual(opened, ["https://www.youtube.com/"])

    def test_saved_site_rejects_non_http_url(self):
        with tempfile.TemporaryDirectory() as root:
            store = SitesStore(Path(root, "sites.json"))
            with self.assertRaises(ValueError):
                store.set("HDRezka", "file:///secret")
            store.set("HDRezka", "https://example.org/")
            self.assertEqual(SitesStore(Path(root, "sites.json")).get("хдрезка"), "https://example.org/")


if __name__ == "__main__":
    unittest.main()
