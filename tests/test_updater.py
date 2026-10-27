import hashlib
import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from voiceassist.updater import (DOWNLOADING, LATEST_ALREADY, NO_ANSWER, Updater, download, latest_release, newer)

SETUP = b"MZ" + b"vega" * 1000


def release(version="0.7.0", data=SETUP, digest=True):
    return {"version": version, "url": "https://example/Vega-Setup.exe", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest() if digest else ""}


def fetcher(data):
    @contextmanager
    def fetch(url, timeout, accept):
        yield io.BytesIO(data)
    return fetch


class VersionTests(unittest.TestCase):
    def test_newer(self):
        self.assertTrue(newer("v0.6.10", "0.6.9"))
        self.assertTrue(newer("0.7.0", "0.6.3"))
        self.assertFalse(newer("v0.6.3", "0.6.3"))
        self.assertFalse(newer("v0.5.9", "0.6.3"))
        self.assertFalse(newer("latest", "0.6.3"))

    def test_latest_release_reads_the_installer_asset(self):
        body = {"tag_name": "v0.7.0", "assets": [
            {"name": "other.zip", "browser_download_url": "https://x/other.zip", "size": 1},
            {"name": "Vega-Setup.exe", "browser_download_url": "https://x/Vega-Setup.exe", "size": 5, "digest": "sha256:ABC"}]}
        found = latest_release(fetcher(json.dumps(body).encode("utf-8")))
        self.assertEqual(found, {"version": "0.7.0", "url": "https://x/Vega-Setup.exe", "size": 5, "sha256": "abc"})


class DownloadTests(unittest.TestCase):
    def test_good_download_is_kept_and_old_ones_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "Vega-Setup-0.6.0.exe"
            old.write_bytes(b"old")
            path = download(release(), Path(folder), fetcher(SETUP))
            self.assertEqual(path.read_bytes(), SETUP)
            self.assertFalse(old.exists())

    def test_broken_download_is_thrown_away(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                download(release(), Path(folder), fetcher(SETUP[:-5] + b"xxxxx"))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_not_a_program_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                download(release(data=b"<html>", digest=False), Path(folder), fetcher(b"<html>"))


class UpdaterTests(unittest.TestCase):
    def make(self, folder, found=None, fail=False, now=[100000.0]):
        started = []

        def latest():
            if fail:
                raise OSError("нет сети")
            return found
        updater = Updater(Path(folder) / "update.json", Path(folder) / "dl", latest=latest,
                          fetch=lambda rel, where: Path(where) / "setup.exe", start=started.append,
                          quit=lambda: started.append("quit"), clock=lambda: now[0], current="0.6.3")
        return updater, started

    def test_checks_once_a_day(self):
        with tempfile.TemporaryDirectory() as folder:
            updater, _ = self.make(folder, found=release("0.6.3"))
            self.assertEqual(updater.check(), "")
            calls = []
            updater.latest = lambda: calls.append(1)
            self.assertEqual(updater.check(), "")
            self.assertEqual(calls, [])

    def test_newer_version_is_installed_only_when_quiet(self):
        with tempfile.TemporaryDirectory() as folder:
            updater, started = self.make(folder, found=release("0.7.0"))
            self.assertEqual(updater.check(), "0.7.0")
            self.assertFalse(updater.ready(10))
            self.assertTrue(updater.ready(600))
            updater.install()
            self.assertEqual(started, [Path(folder) / "dl" / "setup.exe", "quit"])

    def test_no_internet_is_quiet(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = []
            updater, _ = self.make(folder, fail=True)
            updater.log = logs.append
            self.assertIsNone(updater.check())
            self.assertFalse(updater.ready(1000))
            self.assertEqual(updater.ask(), NO_ANSWER)
            self.assertTrue(logs)

    def test_asking_by_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            updater, _ = self.make(folder, found=release("0.6.3"))
            self.assertEqual(updater.ask(), LATEST_ALREADY.format("0.6.3"))
            updater.latest = lambda: release("0.7.0")
            self.assertEqual(updater.ask(), DOWNLOADING.format("0.7.0"))
            updater.worker.join(5)
            self.assertTrue(updater.ready(0))  # asked by voice: no need to wait for quiet


if __name__ == "__main__":
    unittest.main()


class LaunchTests(unittest.TestCase):
    def test_installer_runs_through_a_retrying_script_and_its_log_reaches_the_report(self):
        from unittest import mock
        from voiceassist import updater
        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder, "Vega-Setup-9.9.9.exe")
            installer.write_bytes(b"MZ")
            Path(folder, "install-2.log").write_text("old", encoding="utf-8")
            with mock.patch.object(updater.subprocess, "Popen") as popen:
                updater.launch(installer)
            command = popen.call_args[0][0]
            self.assertEqual(command[1:], ["/C", str(Path(folder, "update.cmd"))])
            script = Path(folder, "update.cmd").read_bytes()
            self.assertIn(b"\r\n", script)
            self.assertEqual(script.count(b"Vega-Setup-9.9.9.exe"), 3)
            self.assertIn(b"/VERYSILENT", script)
            self.assertFalse(Path(folder, "install-2.log").exists())
            self.assertIn("не было", updater.install_log_tail(Path(folder)))
            Path(folder, "install-1.log").write_text("Log opened\nInstallation process succeeded.", encoding="utf-8")
            self.assertIn("succeeded", updater.install_log_tail(Path(folder)))
