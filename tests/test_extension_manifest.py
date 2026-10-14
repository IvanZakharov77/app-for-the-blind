import base64
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "chrome_extension"


class ExtensionManifestTests(unittest.TestCase):
    def test_fixed_key_gives_the_documented_extension_id(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
        extension_id = "".join(chr(ord("a") + int(character, 16)) for character in digest)
        self.assertEqual(extension_id, (ROOT / "EXTENSION_ID.txt").read_text(encoding="ascii").strip())


if __name__ == "__main__":
    unittest.main()
