import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from voiceassist.native_host import process_once
from voiceassist.browser_state import loaded_requested_page


def message(payload):
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("=I", len(body)) + body


class NativeHostTests(unittest.TestCase):
    def test_authorized_extension_records_completed_page(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root, "state.json")
            incoming = io.BytesIO(message({"event": "active_tab", "url": "https://example.org/", "title": "Пример"}))
            outgoing = io.BytesIO()
            process_once(incoming, outgoing, state, "chrome-extension://abc/", "chrome-extension://abc", clock=lambda: 100.0)
            self.assertTrue(loaded_requested_page(state, "https://example.org/", 99.0))
            self.assertIn(b'"ok": true', outgoing.getvalue())

    def test_wrong_origin_cannot_write_state(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root, "state.json")
            with self.assertRaises(ValueError):
                process_once(io.BytesIO(message({"event": "active_tab", "url": "https://example.org/", "title": "Пример"})), io.BytesIO(), state, "chrome-extension://abc/", "chrome-extension://evil/", clock=lambda: 100.0)
            self.assertFalse(state.exists())

    def test_fragmented_pipe_reads_one_message(self):
        class ShortRead(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 2))

        with tempfile.TemporaryDirectory() as root:
            state = Path(root, "state.json")
            incoming = ShortRead(message({"event": "active_tab", "url": "https://example.org/", "title": "Пример"}))
            process_once(incoming, io.BytesIO(), state, "chrome-extension://abc/", "chrome-extension://abc/", clock=lambda: 100.0)
            self.assertTrue(state.exists())


if __name__ == "__main__":
    unittest.main()
