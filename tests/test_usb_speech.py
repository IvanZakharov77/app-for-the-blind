import tempfile
import unittest
from pathlib import Path

from voiceassist.drives import UsbVolume
from voiceassist.files import copy_tree, plan_copy
from voiceassist.usb_copy import SYSTEM_FOLDERS, UsbCopyController


class UsbSpeechTests(unittest.TestCase):
    def make(self, root, destination_fs="NTFS"):
        first, second = Path(root, "first"), Path(root, "second")
        first.mkdir()
        second.mkdir()
        volumes = (UsbVolume("E", "e", "Фото", "NTFS", True), UsbVolume("F", "f", "Копия", destination_fs, True))
        paths = {"e": first, "f": second}
        controller = UsbCopyController(lambda: volumes, path_for_volume=lambda v: paths[v.guid])
        controller.list_devices()
        return first, second, controller

    def test_plan_speaks_size_in_units_and_volume_labels(self):
        with tempfile.TemporaryDirectory() as root:
            first, _second, controller = self.make(root)
            (first / "a.bin").write_bytes(b"x" * (3 * 1024 * 1024))
            message = controller.prepare_first_to_second().message
            self.assertIn("3 мегабайта", message)
            self.assertNotIn("байт.", message.replace("мегабайта", ""))
            self.assertIn("«Фото»", message)
            self.assertIn("«Копия»", message)

    def test_windows_service_folders_are_not_planned_or_copied(self):
        with tempfile.TemporaryDirectory() as root:
            first, second, controller = self.make(root)
            (first / "photo.jpg").write_bytes(b"photo")
            (first / "System Volume Information").mkdir()
            (first / "System Volume Information" / "WPSettings.dat").write_bytes(b"locked")
            (first / "$RECYCLE.BIN").mkdir()
            (first / "$RECYCLE.BIN" / "old.txt").write_bytes(b"deleted")
            plan = controller.prepare_first_to_second()
            self.assertIn("Файлов: 1", plan.message)
            controller.confirm()
            controller.worker.join(5)
            self.assertIn("завершено и проверено", " ".join(controller.poll_events()))
            copied = second / "VoiceAssist Copy 1"
            self.assertTrue((copied / "photo.jpg").exists())
            self.assertFalse((copied / "System Volume Information").exists())
            self.assertFalse((copied / "$RECYCLE.BIN").exists())

    def test_fat16_two_gigabyte_limit_is_named(self):
        class Plan:
            largest_file_bytes = 3 * 1024 ** 3
        with tempfile.TemporaryDirectory() as root:
            first, _second, controller = self.make(root, destination_fs="FAT")
            (first / "a").write_bytes(b"a")
            import voiceassist.usb_copy as module
            original = module.plan_copy
            module.plan_copy = lambda *args: Plan()
            try:
                result = controller.prepare_first_to_second()
            finally:
                module.plan_copy = original
            self.assertEqual(result.status, "error")
            self.assertIn("2 гигабайт", result.message)

    def test_exclusion_applies_only_to_top_level(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root, "s"), Path(root, "d")
            (source / "docs" / "System Volume Information").mkdir(parents=True)
            (source / "docs" / "System Volume Information" / "note.txt").write_bytes(b"user file")
            destination.mkdir()
            plan = plan_copy(source, destination, SYSTEM_FOLDERS)
            self.assertEqual(plan.file_count, 1)
            report = copy_tree(plan, confirmed=True)
            self.assertEqual(report.copied, 1)


if __name__ == "__main__":
    unittest.main()
