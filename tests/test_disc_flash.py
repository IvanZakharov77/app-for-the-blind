"""«Скопируй диск на флешку» and «запиши флешку на диск» (Ivan, 2026-11-01)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voiceassist.core import Assistant
from voiceassist.drives import UsbVolume
from voiceassist.file_browser import FileOutcome
from voiceassist.optical_burn import BurnController, burn_trees, verify_tree
from voiceassist.usb_copy import SYSTEM_FOLDERS, UsbCopyController
from offwindows import setUpModule, tearDownModule  # noqa: F401
from test_optical_burn import BLANK, FakeDisc

FLASH = UsbVolume("F", "guid-f", "Фото", "FAT32", True, True)


class DiscFlashTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.flash = self.root / "flash"
        (self.flash / "Море").mkdir(parents=True)
        (self.flash / "Море" / "a.jpg").write_bytes(b"sea")
        (self.flash / "письмо.txt").write_bytes(b"hello")
        (self.flash / "System Volume Information").mkdir()
        (self.flash / "System Volume Information" / "locked").write_bytes(b"windows")
        self.copier = UsbCopyController(lambda: (FLASH,), path_for_volume=lambda volume: self.flash,
                                        guid_lookup=lambda root: "guid-f")

    def tearDown(self):
        self.folder.cleanup()

    def test_whole_flash_goes_to_disc_without_windows_folders(self):
        disc = FakeDisc(self.root / "disc")
        burner = BurnController(lambda: BLANK, runner=disc, wait=lambda _: None,
                                verifier=lambda source, _r, excluded=(): verify_tree(source, disc.disc_root, excluded))
        assistant = Assistant(current_directory=self.root, optical_probe=lambda: BLANK, burner=burner,
                              usb_copy=self.copier, drive_provider=lambda: (FLASH,))
        plan = assistant.handle("запиши флешку на диск")
        self.assertEqual(plan.status, "needs_confirmation")
        self.assertIn("Файлов: 2", plan.message)
        self.assertIn("флешка F", plan.message)
        self.assertEqual(assistant.handle("подтверждаю запись на диск").status, "in_progress")
        burner.worker.join(5)
        self.assertIn("записан и проверен", " ".join(assistant.poll_due()))
        self.assertEqual((disc.disc_root / "Море" / "a.jpg").read_bytes(), b"sea")
        self.assertEqual((disc.disc_root / "письмо.txt").read_bytes(), b"hello")
        self.assertFalse((disc.disc_root / "System Volume Information").exists())

    def test_a_plain_folder_is_still_one_tree(self):
        self.assertEqual(burn_trees(self.flash / "Море", (), self.root / "staging"), [(self.flash / "Море", False)])

    def test_flash_trees_skip_windows_folders(self):
        trees = burn_trees(self.flash, SYSTEM_FOLDERS, self.root / "staging")
        self.assertEqual(trees, [(self.flash / "Море", True), (self.root / "staging", False)])
        self.assertEqual((self.root / "staging" / "письмо.txt").read_bytes(), b"hello")

    def test_no_flash_is_said_aloud(self):
        assistant = Assistant(current_directory=self.root, optical_probe=lambda: BLANK,
                              burner=BurnController(lambda: BLANK, runner=None), drive_provider=lambda: ())
        result = assistant.handle("запиши флешку на диск")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("Вставьте флешку", result.message)

    def test_disc_is_copied_to_a_new_folder_on_the_flash(self):
        disc = self.root / "cd"
        (disc / "Песни").mkdir(parents=True)
        (disc / "Песни" / "1.mp3").write_bytes(b"la")
        assistant = Assistant(current_directory=self.root, usb_copy=self.copier)
        with patch.object(assistant.drives, "optical_root", return_value=FileOutcome("ok", str(disc))):
            plan = assistant.handle("скопируй диск на флешку")
        self.assertEqual(plan.status, "needs_confirmation")
        self.assertIn("Копия диска 1", plan.message)
        self.assertEqual(assistant.handle("подтверждаю копирование").status, "in_progress")
        self.copier.worker.join(5)
        self.assertEqual((self.flash / "Копия диска 1" / "Песни" / "1.mp3").read_bytes(), b"la")

    def test_no_disc_is_said_aloud(self):
        assistant = Assistant(current_directory=self.root, usb_copy=self.copier)
        empty = FileOutcome("unavailable", "В приводе нет диска с данными, или диск пустой.")
        with patch.object(assistant.drives, "optical_root", return_value=empty):
            result = assistant.handle("перепиши диск на флешку")
        self.assertEqual(result.status, "unavailable")
        self.assertIn("нет диска", result.message)


if __name__ == "__main__":
    unittest.main()
