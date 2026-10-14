import unittest
from voiceassist.platform import classify_windows, actual_version
from types import SimpleNamespace


class PlatformTests(unittest.TestCase):
    def test_windows_7_requires_sp1(self):
        self.assertFalse(classify_windows(6, 1, 0, 64).supported)
        self.assertTrue(classify_windows(6, 1, 1, 64).supported)

    def test_windows_10_and_11_64bit(self):
        self.assertTrue(classify_windows(10, 0, 0, 64, 19045).supported)
        self.assertTrue(classify_windows(10, 0, 0, 64, 22631).supported)
        self.assertFalse(classify_windows(10, 0, 0, 32, 19045).supported)

    def test_first_windows_10_build_is_allowed_for_testing(self):
        self.assertTrue(classify_windows(10, 0, 0, 64, 10240).supported)
        self.assertFalse(classify_windows(10, 0, 0, 64, 9600).supported)

    def test_manifest_emulation_does_not_hide_windows_11_build(self):
        version = SimpleNamespace(major=6, minor=2, build=9200, platform_version=(10, 0, 22631))
        self.assertEqual(actual_version(version), (10, 0, 22631))


if __name__ == "__main__":
    unittest.main()
