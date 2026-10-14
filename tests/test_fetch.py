"""The release downloader must not unpack files outside its target folder."""

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from tools.fetch import extract_archive


class FetchTests(unittest.TestCase):
    def test_extracts_normal_archive(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            archive = root / "model.zip"
            with ZipFile(str(archive), "w") as z:
                z.writestr("model/data.txt", "sample")
            extract_archive(archive, root / "components")
            self.assertEqual((root / "components/model/data.txt").read_text(), "sample")

    def test_rejects_parent_traversal_before_extracting_anything(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            archive = root / "bad.zip"
            with ZipFile(str(archive), "w") as z:
                z.writestr("safe.txt", "safe")
                z.writestr("../outside.txt", "bad")
            with self.assertRaises(ValueError):
                extract_archive(archive, root / "components")
            self.assertFalse((root / "components/safe.txt").exists())
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_windows_style_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            archive = root / "bad.zip"
            with ZipFile(str(archive), "w") as z:
                z.writestr("..\\outside.txt", "bad")
            with self.assertRaises(ValueError):
                extract_archive(archive, root / "components")


if __name__ == "__main__":
    unittest.main()
