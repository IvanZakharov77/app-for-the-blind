import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voiceassist.core import Assistant
from voiceassist.optical import OpticalProbe, parse_probe_output
from voiceassist.optical_burn import BurnController, disc_label, find_folders, verify_tree

BLANK = OpticalProbe(1, 1, 1, ((0, 700 * 1024 * 1024, "E:\\"),))


class FakeDisc:
    """Stands in for IMAPI: "burns" by copying the folder to a directory playing the disc."""

    def __init__(self, disc_root: Path, fail_stage=None, corrupt=False):
        self.disc_root = disc_root
        self.fail_stage = fail_stage
        self.corrupt = corrupt
        self.calls = []

    def __call__(self, index, source, label, file_systems, on_line):
        self.calls.append((index, source, label, file_systems))
        on_line("STAGE|write")
        for percent in (10, 30, 60, 90, 100):
            on_line("PROGRESS|4|{}|5".format(percent))
        if self.fail_stage:
            on_line("ERROR|{}|80004005".format(self.fail_stage))
            return 3
        shutil.copytree(str(source), str(self.disc_root))
        if self.corrupt:
            next(self.disc_root.rglob("*.txt")).write_bytes(b"broken")
        on_line("DONE")
        return 0


class BurnTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.photos = self.root / "Фото с моря"
        self.photos.mkdir()
        (self.photos / "a.txt").write_bytes(b"sea")
        (self.photos / "inner").mkdir()
        (self.photos / "inner" / "b.txt").write_bytes(b"sun")

    def tearDown(self):
        shutil.rmtree(str(self.root))

    def controller(self, disc, probe=BLANK):
        return BurnController(lambda: probe, runner=disc,
                              verifier=lambda source, _root: verify_tree(source, disc.disc_root), wait=lambda _: None)

    def finish(self, controller):
        controller.worker.join(5)
        return " ".join(controller.poll_events())

    def test_plan_confirmation_burn_and_verification(self):
        disc = FakeDisc(self.root / "disc")
        controller = self.controller(disc)
        plan = controller.prepare(self.photos)
        self.assertEqual(plan.status, "needs_confirmation")
        self.assertIn("Файлов: 2", plan.message)
        self.assertIn("подтверждаю запись на диск", plan.message)
        self.assertEqual(disc.calls, [])
        self.assertEqual(controller.confirm().status, "in_progress")
        events = self.finish(controller)
        self.assertIn("50 процентов", events)
        self.assertIn("записан и проверен", events)
        self.assertEqual(disc.calls[0][3], 7)

    def test_corrupted_disc_is_not_reported_as_verified(self):
        controller = self.controller(FakeDisc(self.root / "disc", corrupt=True))
        controller.prepare(self.photos)
        controller.confirm()
        events = self.finish(controller)
        self.assertNotIn("проверен.", events)
        self.assertIn("проверка не прошла", events)

    def test_failed_write_is_reported_honestly(self):
        controller = self.controller(FakeDisc(self.root / "disc", fail_stage="write"))
        controller.prepare(self.photos)
        controller.confirm()
        self.assertIn("не выполнена", self.finish(controller))

    def test_folder_too_large_for_disc_is_refused(self):
        small = OpticalProbe(1, 1, 1, ((0, 10 * 1024 * 1024, "E:\\"),))
        result = self.controller(FakeDisc(self.root / "disc"), small).prepare(self.photos)
        self.assertEqual(result.status, "error")
        self.assertIn("большей ёмкости", result.message)

    def test_changed_folder_requires_new_plan(self):
        disc = FakeDisc(self.root / "disc")
        controller = self.controller(disc)
        controller.prepare(self.photos)
        (self.photos / "new.txt").write_bytes(b"new")
        self.assertEqual(controller.confirm().status, "error")
        self.assertEqual(disc.calls, [])

    def test_removed_disc_blocks_confirmation(self):
        probes = [BLANK, OpticalProbe(1, 1, 0)]
        disc = FakeDisc(self.root / "disc")
        controller = BurnController(lambda: probes.pop(0), runner=disc, wait=lambda _: None)
        controller.prepare(self.photos)
        self.assertEqual(controller.confirm().status, "error")
        self.assertEqual(disc.calls, [])

    def test_cancel_before_confirmation_drops_plan(self):
        controller = self.controller(FakeDisc(self.root / "disc"))
        controller.prepare(self.photos)
        self.assertEqual(controller.cancel().status, "ok")
        self.assertIsNone(controller.pending)

    def test_running_burn_is_not_interrupted(self):
        import threading
        release = threading.Event()

        def slow(index, source, label, file_systems, on_line):
            release.wait(5)
            return 3

        controller = BurnController(lambda: BLANK, runner=slow, wait=lambda _: None)
        controller.prepare(self.photos)
        controller.confirm()
        refusal = controller.cancel()
        release.set()
        controller.worker.join(5)
        self.assertEqual(refusal.status, "unavailable")
        self.assertIn("испортит диск", refusal.message)

    def test_large_file_switches_to_udf_only(self):
        from voiceassist import optical_burn
        original = optical_burn.survey_tree
        optical_burn.survey_tree = lambda folder: (1, 1024, 5 * 1024 ** 3, "digest")
        try:
            controller = self.controller(FakeDisc(self.root / "disc"),
                                         OpticalProbe(1, 1, 1, ((0, 8 * 1024 ** 3, "E:\\"),)))
            controller.prepare(self.photos)
            self.assertTrue(controller.pending.udf_only)
        finally:
            optical_burn.survey_tree = original


class FolderLookupTests(unittest.TestCase):
    def test_spoken_folder_names_and_aliases(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "Фото с моря").mkdir()
            (root / "Documents").mkdir()
            self.assertEqual(find_folders("фото с моря", [root]), [(root / "Фото с моря").resolve()])
            self.assertEqual(find_folders("документы", [root]), [(root / "Documents").resolve()])
            self.assertEqual(find_folders("нет такой", [root]), [])

    def test_label_is_short_and_safe(self):
        self.assertEqual(disc_label("Фото с моря 2026!!!"), "Фото с моря 2026")
        self.assertEqual(disc_label("***"), "VoiceAssist")

    def test_probe_reports_drive_root_and_free_space(self):
        probe = parse_probe_output(b"TOTAL|1\nDRIVE|0|-1|-1|2|1000|E:\\\n")
        self.assertEqual(probe.ready_drives, ((0, 2048000, "E:\\"),))


class AssistantBurnTests(unittest.TestCase):
    def test_voice_route_plans_and_confirms_named_folder(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "Фото").mkdir()
            (root / "Фото" / "a.txt").write_bytes(b"x")
            disc = FakeDisc(root / "disc")
            burner = BurnController(lambda: BLANK, runner=disc,
                                    verifier=lambda source, _r: verify_tree(source, disc.disc_root), wait=lambda _: None)
            assistant = Assistant(current_directory=root, optical_probe=lambda: BLANK, burner=burner)
            # Keep this routing test independent of a real ~/Pictures directory.
            with patch.object(assistant, "_search_roots", return_value=[root]):
                plan = assistant.handle("запиши на диск папку фото")
            self.assertEqual(plan.status, "needs_confirmation")
            self.assertEqual(assistant.handle("подтверждаю запись на диск").status, "in_progress")
            burner.worker.join(5)
            self.assertIn("записан и проверен", " ".join(assistant.poll_due()))

    def test_unknown_folder_is_an_honest_error(self):
        with tempfile.TemporaryDirectory() as root:
            assistant = Assistant(current_directory=Path(root), optical_probe=lambda: BLANK,
                                  burner=BurnController(lambda: BLANK, runner=None))
            result = assistant.handle("запиши на диск папку несуществующая")
            self.assertEqual(result.status, "error")
            self.assertIn("не найдена", result.message)

    def test_cancel_drops_burn_plan(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "Фото").mkdir()
            (root / "Фото" / "a.txt").write_bytes(b"x")
            assistant = Assistant(current_directory=root, optical_probe=lambda: BLANK,
                                  burner=BurnController(lambda: BLANK, runner=None))
            with patch.object(assistant, "_search_roots", return_value=[root]):
                assistant.handle("запиши на диск папку фото")
            result = assistant.handle("отмена")
            self.assertIn("План записи диска отменён", result.message)


if __name__ == "__main__":
    unittest.main()
