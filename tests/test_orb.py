import random
import unittest

from voiceassist.orb import BARS, HEIGHT, LISTEN, LOW, WIDTH, NoOrb, Orb, bar_box, next_heights


class EqualizerTests(unittest.TestCase):
    def test_bars_fit_the_window(self):
        for index in range(BARS):
            for height in (0.0, LOW, 1.0):
                x0, y0, x1, y1 = bar_box(index, height)
                self.assertGreaterEqual(x0, 0)
                self.assertLessEqual(x1, WIDTH)
                self.assertGreaterEqual(y0, 0)
                self.assertLessEqual(y1, HEIGHT)

    def test_listening_bars_stay_low(self):
        heights = [LOW] * BARS
        for frame in range(200):
            heights = next_heights(heights, False, frame / 20)
        self.assertTrue(all(LOW - 0.01 <= h <= LISTEN + 0.01 for h in heights))

    def test_talking_bars_jump(self):
        rng = random.Random(1)
        heights = [LOW] * BARS
        tallest = 0.0
        for frame in range(100):
            heights = next_heights(heights, True, frame / 20, rng)
            tallest = max(tallest, max(heights))
            self.assertTrue(all(0 <= h <= 1 for h in heights))
        self.assertGreater(tallest, 0.6)

    def test_keep_talk_and_fade(self):
        now = [100.0]
        orb = Orb.__new__(Orb)  # without its window thread
        orb.clock, orb.visible_until, orb.talking_until = (lambda: now[0]), 0.0, 0.0
        orb.keep(10)
        self.assertEqual(orb.visible_until, 110.0)
        orb.talk(1.5)
        self.assertGreater(orb.talking_until, 100.0)
        orb.fade_soon(1.5)
        self.assertEqual(orb.visible_until, 101.5)
        orb.hide()
        self.assertEqual((orb.visible_until, orb.talking_until), (0.0, 0.0))

    def test_no_orb_does_nothing(self):
        NoOrb().keep(1)
        NoOrb().talk(1)
        NoOrb().fade_soon(1)
        NoOrb().hide()


if __name__ == "__main__":
    unittest.main()
