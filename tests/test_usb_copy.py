import tempfile
import threading
import time
import unittest
from pathlib import Path

from voiceassist.drives import UsbVolume
from voiceassist.usb_copy import UsbCopyController
from voiceassist.files import CopyJournal, CopyReport
from voiceassist.file_browser import FileBrowser


class UsbCopyTests(unittest.TestCase):
    def test_finished_job_does_not_read_stale_progress_messages(self):
        controller = UsbCopyController(lambda: ())
        controller.events.put("Копирование: проверено 1 из 4 файлов.")
        controller.events.put("Копирование завершено и проверено.")
        self.assertEqual(controller.poll_events(), ("Копирование завершено и проверено.",))

    def test_progress_question_does_not_invent_remaining_time(self):
        controller = UsbCopyController(lambda: ())
        controller.worker = threading.Thread(target=lambda: None)
        controller.worker.start()
        controller.worker.join()
        self.assertEqual(controller.progress_status().status, "unavailable")

    def test_plan_requires_confirmation_then_copies_to_new_folder(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root, "first")
            second = Path(root, "second")
            first.mkdir()
            second.mkdir()
            (first / "photo.txt").write_text("memory")
            volumes = (UsbVolume("E", "guid-e", "Фото", "NTFS", True),
                       UsbVolume("F", "guid-f", "Копия", "NTFS", True))
            paths = {"guid-e": first, "guid-f": second}
            controller = UsbCopyController(lambda: volumes, path_for_volume=lambda v: paths[v.guid])
            listed = controller.list_devices().message
            self.assertIn("первый", listed)
            self.assertIn("скопируй всё с первой на вторую", listed)
            plan = controller.prepare_first_to_second()
            self.assertEqual(plan.status, "needs_confirmation")
            self.assertIn("Файлов: 1", plan.message)
            self.assertFalse(list(second.iterdir()))
            started = controller.confirm()
            self.assertEqual(started.status, "in_progress")
            controller.worker.join(5)
            self.assertFalse(controller.worker.is_alive())
            self.assertEqual((second / "VoiceAssist Copy 1" / "photo.txt").read_text(), "memory")
            self.assertEqual((first / "photo.txt").read_text(), "memory")
            self.assertIn("завершено и проверено", " ".join(controller.poll_events()))

    def test_pulled_drive_leaves_a_journal_that_finishes_the_copy(self):
        with tempfile.TemporaryDirectory() as root:
            first, second = Path(root, "first"), Path(root, "second")
            first.mkdir()
            second.mkdir()
            (first / "a.txt").write_text("один")
            (first / "b.txt").write_text("два")
            volumes = (UsbVolume("E", "guid-e", "A", "NTFS", True), UsbVolume("F", "guid-f", "B", "NTFS", True))
            paths = {"guid-e": first, "guid-f": second}
            journal = CopyJournal(Path(root, "journal.json"))

            def pulled(plan, **options):
                (plan.destination / "a.txt").write_text("од")  # cut off mid-file
                return CopyReport(0, 0, 0, device_changed=True)
            controller = UsbCopyController(lambda: volumes, path_for_volume=lambda v: paths[v.guid],
                                           copy_function=pulled, journal=journal)
            controller.list_devices()
            controller.prepare_first_to_second()
            controller.confirm()
            controller.worker.join(5)
            self.assertIn("продолжи копирование", " ".join(controller.poll_events()))
            self.assertIn("с диска E на диск F", journal.load()["label"])
            files = FileBrowser(home=Path(root), journal=journal)
            outcome = files.resume()
            self.assertEqual(outcome.status, "needs_confirmation")
            self.assertEqual(outcome.action().status, "in_progress")
            files.worker.join(5)
            self.assertEqual((second / "VoiceAssist Copy 1" / "a.txt").read_text(), "один")
            self.assertEqual((second / "VoiceAssist Copy 1" / "b.txt").read_text(), "два")
            self.assertIsNone(journal.load())

    def test_changed_volume_identity_blocks_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root, "first")
            second = Path(root, "second")
            first.mkdir()
            second.mkdir()
            (first / "a").write_text("x")
            initial = (UsbVolume("E", "guid-e", "A", "NTFS", True),
                       UsbVolume("F", "guid-f", "B", "NTFS", True))
            changed = (initial[0], UsbVolume("F", "different-guid", "B", "NTFS", True))
            present = [initial]
            controller = UsbCopyController(lambda: present[0], path_for_volume=lambda v: first if v.letter == "E" else second)
            controller.list_devices()
            self.assertEqual(controller.prepare_first_to_second().status, "needs_confirmation")
            present[0] = changed
            self.assertEqual(controller.confirm().status, "error")
            self.assertFalse(list(second.iterdir()))

    def test_confirmation_rechecks_usb_bus_even_when_guids_match(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root, "first")
            second = Path(root, "second")
            first.mkdir()
            second.mkdir()
            (first / "a").write_text("x")
            initial = (UsbVolume("E", "guid-e", "A", "NTFS", True),
                       UsbVolume("F", "guid-f", "B", "NTFS", True))
            present = [initial]
            paths = {"guid-e": first, "guid-f": second}
            controller = UsbCopyController(lambda: present[0], path_for_volume=lambda v: paths[v.guid],
                                           guid_lookup=lambda root: "guid-e" if root.startswith("E") else "guid-f")
            controller.list_devices()
            self.assertEqual(controller.prepare_first_to_second().status, "needs_confirmation")
            present[0] = (initial[0], UsbVolume("F", "guid-f", "B", "NTFS", False))
            self.assertEqual(controller.confirm().status, "error")
            self.assertFalse(list(second.iterdir()))

    def test_fat32_rejects_file_that_cannot_fit_before_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root, "first")
            second = Path(root, "second")
            first.mkdir()
            second.mkdir()
            with (first / "large.bin").open("wb") as stream:
                stream.truncate(4 * 1024 ** 3)
            volumes = (UsbVolume("E", "e", "A", "NTFS", True),
                       UsbVolume("F", "f", "B", "FAT32", True))
            paths = {"e": first, "f": second}
            controller = UsbCopyController(lambda: volumes, path_for_volume=lambda v: paths[v.guid])
            controller.list_devices()
            result = controller.prepare_first_to_second()
            self.assertEqual(result.status, "error")
            self.assertIn("FAT32", result.message)
            self.assertFalse(list(second.iterdir()))

    def test_cancel_discards_pending_plan_without_writing(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root, "first")
            second = Path(root, "second")
            first.mkdir()
            second.mkdir()
            (first / "a.txt").write_text("x")
            volumes = (UsbVolume("E", "e", "A", "NTFS", True),
                       UsbVolume("F", "f", "B", "NTFS", True))
            paths = {"e": first, "f": second}
            controller = UsbCopyController(lambda: volumes, path_for_volume=lambda v: paths[v.guid])
            controller.list_devices()
            controller.prepare_first_to_second()
            self.assertEqual(controller.cancel().status, "ok")
            self.assertEqual(controller.confirm().status, "unavailable")
            self.assertFalse(list(second.iterdir()))

    def test_cancel_active_copy_reports_partial_outcome(self):
        with tempfile.TemporaryDirectory() as root:
            first = Path(root, "first")
            second = Path(root, "second")
            first.mkdir()
            second.mkdir()
            (first / "a.txt").write_text("x")
            volumes = (UsbVolume("E", "e", "A", "NTFS", True),
                       UsbVolume("F", "f", "B", "NTFS", True))
            paths = {"e": first, "f": second}
            entered = threading.Event()
            def controlled_copy(plan, confirmed, should_cancel, on_progress, devices_match):
                entered.set()
                self.assertTrue(entered.wait(1))
                while not should_cancel():
                    time.sleep(0.001)
                return CopyReport(0, 0, 0, cancelled=True)
            controller = UsbCopyController(lambda: volumes, path_for_volume=lambda v: paths[v.guid],
                                           copy_function=controlled_copy)
            controller.list_devices()
            controller.prepare_first_to_second()
            self.assertEqual(controller.confirm().status, "in_progress")
            self.assertTrue(entered.wait(2))
            self.assertIn("0 из 1", controller.progress_status().message)
            self.assertEqual(controller.cancel().status, "ok")
            controller.worker.join(5)
            self.assertIn("остановлено", " ".join(controller.poll_events()))


if __name__ == "__main__":
    unittest.main()
