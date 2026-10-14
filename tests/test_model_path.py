import tempfile
import unittest
from pathlib import Path

from unittest import mock

from voiceassist.model_path import DONE_MARK, latin_model_path, latin_temp_folder


class LatinModelPathTests(unittest.TestCase):
    def test_voice_temp_folder_avoids_cyrillic_profile(self):
        with tempfile.TemporaryDirectory() as root:
            profile_temp = Path(root, "Пользователь", "Temp")
            profile_temp.mkdir(parents=True)
            with mock.patch("tempfile.gettempdir", return_value=str(profile_temp)), \
                    mock.patch("voiceassist.model_path.shared_folder", return_value=Path(root, "shared")):
                folder = latin_temp_folder(short=lambda text: None)
            self.assertTrue(str(folder.relative_to(root)).isascii())
            self.assertTrue(folder.is_dir())

    def test_latin_path_is_kept(self):
        self.assertEqual(latin_model_path(Path("C:/Users/Ivan/model"), short=lambda text: None), Path("C:/Users/Ivan/model"))

    def test_short_name_replaces_cyrillic_folder(self):
        path = latin_model_path(Path("C:/Users/Пользователь/model"), short=lambda text: "C:/Users/5D3B~1/model")
        self.assertEqual(path, Path("C:/Users/5D3B~1/model"))

    def test_copy_once_when_there_is_no_short_name(self):
        with tempfile.TemporaryDirectory() as root:
            model = Path(root, "Пользователь", "model")
            (model / "am").mkdir(parents=True)
            (model / "am" / "final.mdl").write_text("weights", encoding="ascii")
            shared = Path(root, "shared")
            copies = []

            def copy(source, target):
                copies.append(target)
                import shutil
                shutil.copytree(source, target)
            first = latin_model_path(model, short=lambda text: None, fallback=shared, copy=copy)
            second = latin_model_path(model, short=lambda text: None, fallback=shared, copy=copy)
            self.assertEqual(first, shared / "model")
            self.assertEqual(second, first)
            self.assertEqual(len(copies), 1)
            self.assertTrue((first / DONE_MARK).exists())
            self.assertEqual((first / "am" / "final.mdl").read_text(encoding="ascii"), "weights")


if __name__ == "__main__":
    unittest.main()
