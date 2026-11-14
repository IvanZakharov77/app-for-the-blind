import unittest

from voiceassist.wake_key import DoubleTap, unmute_speakers


def run(events):
    detector = DoubleTap()
    return [detector.feed(ctrl, other, now) for ctrl, other, now in events]


class DoubleTapTests(unittest.TestCase):
    def test_two_quick_taps(self):
        hits = run([(True, False, 0.0), (False, False, 0.1), (True, False, 0.3), (False, False, 0.4)])
        self.assertEqual(hits, [False, False, False, True])

    def test_one_tap_or_slow_taps(self):
        self.assertFalse(any(run([(True, False, 0.0), (False, False, 0.1)])))
        self.assertFalse(any(run([(True, False, 0.0), (False, False, 0.1), (True, False, 1.5), (False, False, 1.6)])))

    def test_ctrl_c_ctrl_v_never_counts(self):
        hits = run([(True, False, 0.0), (True, True, 0.05), (False, False, 0.1),
                    (True, False, 0.3), (True, True, 0.35), (False, False, 0.4)])
        self.assertFalse(any(hits))

    def test_long_hold_is_not_a_tap(self):
        self.assertFalse(any(run([(True, False, 0.0), (False, False, 1.0), (True, False, 1.2), (False, False, 1.3)])))

    def test_third_tap_starts_over(self):
        hits = run([(True, False, 0.0), (False, False, 0.1), (True, False, 0.2), (False, False, 0.3),
                    (True, False, 0.4), (False, False, 0.5)])
        self.assertEqual(hits.count(True), 1)


class UnmuteTests(unittest.TestCase):
    def test_nothing_happens_off_windows(self):
        self.assertFalse(unmute_speakers())


if __name__ == "__main__":
    unittest.main()
