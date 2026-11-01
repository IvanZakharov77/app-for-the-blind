import unittest

from voiceassist.orb import KEY, NoOrb, Orb, frame_rows, palette


class OrbTests(unittest.TestCase):
    def test_frame_is_a_circle_on_the_transparent_colour(self):
        rows = frame_rows(0, 84, size=32)
        self.assertEqual(len(rows), 32)
        self.assertEqual(rows[0][0], KEY)
        self.assertNotEqual(rows[16][16], KEY)

    def test_palette_closes_on_itself(self):
        colors = palette()
        self.assertEqual(len(colors), 360)
        self.assertLess(sum(abs(a - b) for a, b in zip(colors[0], colors[-1])), 30)

    def test_keep_and_fade(self):
        now = [100.0]
        orb = Orb.__new__(Orb)  # without its window thread
        orb.clock, orb.visible_until = (lambda: now[0]), 0.0
        orb.keep(10)
        self.assertEqual(orb.visible_until, 110.0)
        orb.fade_soon(1.5)
        self.assertEqual(orb.visible_until, 101.5)
        orb.hide()
        self.assertEqual(orb.visible_until, 0.0)

    def test_no_orb_does_nothing(self):
        NoOrb().keep(1)
        NoOrb().fade_soon(1)
        NoOrb().hide()


if __name__ == "__main__":
    unittest.main()
