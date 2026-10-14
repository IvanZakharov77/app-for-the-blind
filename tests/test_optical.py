import unittest

from voiceassist.optical import parse_probe_output


class OpticalTests(unittest.TestCase):
    def test_probe_distinguishes_read_only_drive_and_blank_recordable_media(self):
        status = parse_probe_output(b"TOTAL|2\nDRIVE|0|0|0|0|0\nDRIVE|1|-1|-1|2|300000\n")
        self.assertEqual(status.drive_count, 2)
        self.assertEqual(status.writer_count, 1)
        self.assertEqual(status.ready_writer_count, 1)

    def test_malformed_probe_output_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_probe_output(b"TOTAL|1\nDRIVE|bad\n")



if __name__ == "__main__":
    unittest.main()
