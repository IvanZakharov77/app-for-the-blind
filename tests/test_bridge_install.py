import json
import tempfile
import unittest
from pathlib import Path

from voiceassist.bridge_install import register_bridge


class FakeRegistry:
    def __init__(self):
        self.path = None

    def write(self, path):
        self.path = path

    def read(self):
        return self.path


class BridgeInstallTests(unittest.TestCase):
    def test_manifest_allows_only_selected_extension(self):
        with tempfile.TemporaryDirectory() as root:
            exe = Path(root, "VoiceAssistNativeHost.exe")
            exe.write_bytes(b"exe")
            registry = FakeRegistry()
            manifest = register_bridge("a" * 32, exe, Path(root, "config"), registry)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["allowed_origins"], ["chrome-extension://" + "a" * 32 + "/"])
            self.assertEqual(registry.read(), str(manifest))

    def test_invalid_extension_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            exe = Path(root, "host.exe")
            exe.write_bytes(b"exe")
            with self.assertRaises(ValueError):
                register_bridge("../evil", exe, Path(root, "config"), FakeRegistry())


if __name__ == "__main__":
    unittest.main()
