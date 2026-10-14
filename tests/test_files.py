import tempfile
import unittest
from pathlib import Path

from voiceassist.files import describe_directory, plan_copy, copy_tree


class FileTests(unittest.TestCase):
    def test_directory_reads_real_entries(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "пример.txt").write_text("x", encoding="utf-8")
            result = describe_directory(Path(root))
            self.assertIn("пример.txt", result)

    def test_copy_plan_rejects_same_location(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            source.mkdir()
            with self.assertRaises(ValueError):
                plan_copy(source, source)

    def test_copy_plan_rejects_unannounced_symbolic_link(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            (source / "link").symlink_to(destination, target_is_directory=True)
            with self.assertRaises(ValueError):
                plan_copy(source, destination)

    def test_copy_plan_reports_size_without_modifying_files(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            Path(source, "a.txt").write_bytes(b"abc")
            plan = plan_copy(source, destination)
            self.assertEqual((plan.file_count, plan.total_bytes), (1, 3))
            self.assertFalse((destination / "a.txt").exists())

    def test_copy_plan_reports_largest_file_for_fat32_check(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            (source / "small").write_bytes(b"a")
            (source / "large").write_bytes(b"abc")
            self.assertEqual(plan_copy(source, destination).largest_file_bytes, 3)

    def test_same_size_source_change_requires_new_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            item = source / "a.txt"
            item.write_bytes(b"old")
            plan = plan_copy(source, destination)
            item.write_bytes(b"new")
            with self.assertRaises(ValueError):
                copy_tree(plan, confirmed=True)
            self.assertFalse((destination / "a.txt").exists())

    def test_copy_requires_explicit_confirmation_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            Path(source, "a.txt").write_bytes(b"abc")
            plan = plan_copy(source, destination)
            with self.assertRaises(ValueError):
                copy_tree(plan, confirmed=False)
            report = copy_tree(plan, confirmed=True)
            self.assertEqual(report.copied, 1)
            self.assertEqual((destination / "a.txt").read_bytes(), b"abc")
            self.assertEqual((source / "a.txt").read_bytes(), b"abc")

    def test_copy_preserves_empty_subfolders(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            (source / "empty").mkdir(parents=True)
            destination.mkdir()
            copy_tree(plan_copy(source, destination), confirmed=True)
            self.assertTrue((destination / "empty").is_dir())

    def test_copy_never_overwrites_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            Path(source, "a.txt").write_bytes(b"new")
            Path(destination, "a.txt").write_bytes(b"old")
            report = copy_tree(plan_copy(source, destination), confirmed=True)
            self.assertEqual(report.skipped, 1)
            self.assertEqual((destination / "a.txt").read_bytes(), b"old")

    def test_copy_does_not_follow_destination_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            outside = Path(root, "outside")
            (source / "nested").mkdir(parents=True)
            destination.mkdir()
            outside.mkdir()
            Path(source, "nested", "a.txt").write_bytes(b"secret")
            (destination / "nested").symlink_to(outside, target_is_directory=True)
            report = copy_tree(plan_copy(source, destination), confirmed=True)
            self.assertEqual(report.failed, 1)
            self.assertFalse((outside / "a.txt").exists())

    def test_destination_replaced_by_symlink_after_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            outside = Path(root, "outside")
            source.mkdir()
            destination.mkdir()
            outside.mkdir()
            (source / "a.txt").write_bytes(b"secret")
            plan = plan_copy(source, destination)
            destination.rmdir()
            destination.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                copy_tree(plan, confirmed=True)
            self.assertFalse((outside / "a.txt").exists())

    def test_cancel_removes_partial_file_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            payload = b"x" * (2 * 1024 * 1024)
            (source / "large.bin").write_bytes(payload)
            calls = [0]
            def cancel():
                calls[0] += 1
                return calls[0] >= 2
            report = copy_tree(plan_copy(source, destination), confirmed=True, should_cancel=cancel)
            self.assertTrue(report.cancelled)
            self.assertFalse((destination / "large.bin").exists())
            self.assertEqual((source / "large.bin").read_bytes(), payload)

    def test_progress_counts_only_verified_files(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            (source / "one.txt").write_bytes(b"abc")
            progress = []
            report = copy_tree(plan_copy(source, destination), confirmed=True,
                               on_progress=lambda copied, total: progress.append((copied, total)))
            self.assertEqual(progress, [(1, 1)])
            self.assertEqual(report.copied, 1)

    def test_copy_stops_if_device_identity_changes_between_files(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "from")
            destination = Path(root, "to")
            source.mkdir()
            destination.mkdir()
            (source / "a.txt").write_bytes(b"first")
            (source / "b.txt").write_bytes(b"second")
            checks = [0]
            def same_devices():
                checks[0] += 1
                return checks[0] == 1
            report = copy_tree(plan_copy(source, destination), confirmed=True, devices_match=same_devices)
            self.assertTrue(report.device_changed)
            self.assertTrue((destination / "a.txt").exists())
            self.assertFalse((destination / "b.txt").exists())


if __name__ == "__main__":
    unittest.main()
