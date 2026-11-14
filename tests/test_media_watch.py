import unittest

from voiceassist.media_watch import MediaWatch


class FakeWindows:
    def __init__(self, windows):
        self.windows = list(windows)
        self.closed, self.killed = [], []
        self.after_open = []

    def list(self):
        return list(self.windows)

    def open(self, path):
        self.windows += self.after_open

    def close(self, handle):
        self.closed.append(handle)
        self.windows = [window for window in self.windows if window[0] != handle]

    def alive(self, handle):
        return any(window[0] == handle for window in self.windows)

    def kill(self, pid):
        self.killed.append(pid)


BEFORE = [(1, 10, "explorer.exe", "Флешка", "CabinetWClass"), (2, 20, "chrome.exe", "YouTube", "Chrome_WidgetWin_1")]


class MediaWatchTests(unittest.TestCase):
    def watch(self, windows):
        ticks = iter(range(10 ** 6))
        return MediaWatch(windows, clock=lambda: float(next(ticks)), sleep=lambda seconds: None)

    def launch(self, watch, windows, path):
        before = windows.list()
        windows.open(path)
        watch._find_player(before)

    def test_unknown_new_player_is_closed_and_nothing_else(self):
        windows = FakeWindows(BEFORE)
        windows.after_open = [(3, 30, "someplayer.exe", "песня.mp3", "Main")]
        watch = self.watch(windows)
        self.launch(watch, windows, "E:\\песня.mp3")
        self.assertTrue(watch.playing)
        self.assertTrue(watch.close())
        self.assertEqual(windows.closed, [3])
        self.assertTrue(windows.alive(1) and windows.alive(2))  # Explorer and the browser stay

    def test_player_already_open_takes_the_file(self):
        windows = FakeWindows(BEFORE + [(4, 40, "aimp.exe", "AIMP", "TAIMPMainForm")])
        watch = self.watch(windows)
        self.launch(watch, windows, "E:\\песня.mp3")
        self.assertTrue(watch.close())
        self.assertEqual(windows.closed, [4])

    def test_windows_10_media_player_frame(self):
        windows = FakeWindows(BEFORE)
        windows.after_open = [(5, 50, "applicationframehost.exe", "Медиаплеер", "ApplicationFrameWindow")]
        watch = self.watch(windows)
        self.launch(watch, windows, "E:\\песня.mp3")
        self.assertTrue(watch.close())
        self.assertEqual(windows.closed, [5])
        self.assertEqual(windows.killed, [])  # the frame host is never killed

    def test_browser_or_explorer_never_taken_for_a_player(self):
        windows = FakeWindows(BEFORE)
        windows.after_open = [(6, 60, "msedge.exe", "песня.mp3", "Chrome_WidgetWin_1")]
        watch = self.watch(windows)
        self.launch(watch, windows, "E:\\песня.mp3")
        self.assertFalse(watch.playing)
        self.assertFalse(watch.close())
        self.assertEqual(windows.closed, [])

    def test_documents_are_not_watched(self):
        windows = FakeWindows(BEFORE)
        opened = []
        watch = self.watch(windows)
        watch.launcher(opened.append)("E:\\письмо.docx")
        self.assertEqual(opened, ["E:\\письмо.docx"])
        self.assertFalse(watch.playing)


class MediaCommandTests(unittest.TestCase):
    def test_voice_closes_the_player_only_when_one_plays(self):
        from voiceassist.core import Assistant

        class Media:
            playing, closed = True, 0

            def close(self):
                self.closed += 1
                return True

        assistant = Assistant()
        assistant.media = Media()
        self.assertEqual(assistant.handle("выключи музыку").message, "Выключила.")
        self.assertEqual(assistant.media.closed, 1)
        assistant.media.playing = False
        assistant.handle("выключи музыку")
        self.assertEqual(assistant.media.closed, 1)
