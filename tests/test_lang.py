import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from voiceassist import lang


def make_zip(voice):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as packed:
        packed.writestr("model/am/final.mdl", "x")
        packed.writestr("piper/{}.onnx".format(voice), "x")
        packed.writestr("piper/{}.onnx.json".format(voice), json.dumps({"speaker_id_map": {"lada": 1}}))
    return buffer.getvalue()


class LangTests(unittest.TestCase):
    def test_current_reads_installer_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(lang.current(Path(folder)).code, "ru")
            (Path(folder) / "language.txt").write_text("uk", encoding="utf-8")
            self.assertEqual(lang.current(Path(folder)).code, "uk")
            (Path(folder) / "language.txt").write_text("xx", encoding="utf-8")
            self.assertEqual(lang.current(Path(folder)).code, "ru")

    def test_download_checks_hash_and_unpacks(self):
        language = lang.LANGUAGES["uk"]
        data = make_zip(language.voice)
        sums = "{}  vega-lang-uk.zip\n".format(hashlib.sha256(data).hexdigest()).encode()
        files = {lang.PACKS + "SHA256SUMS": sums, lang.PACKS + "vega-lang-uk.zip": data}
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(lang.download_pack(Path(folder), language, opener=files.__getitem__))
            model_json = lang.pack_folder(Path(folder), language) / "piper" / (language.voice + ".onnx.json")
            self.assertEqual(lang.speaker_id(model_json, "lada"), 1)

    def test_bad_hash_is_refused(self):
        language = lang.LANGUAGES["de"]
        files = {lang.PACKS + "SHA256SUMS": b"00  vega-lang-de.zip\n", lang.PACKS + "vega-lang-de.zip": make_zip(language.voice)}
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(lang.download_pack(Path(folder), language, opener=files.__getitem__))
            self.assertFalse(lang.pack_ready(Path(folder), language))
