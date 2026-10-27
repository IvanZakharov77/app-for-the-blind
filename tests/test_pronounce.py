import unittest

from voiceassist.pronounce import prepare
from voiceassist.yo import restore


class YoTests(unittest.TestCase):
    def test_puts_yo_back(self):
        self.assertEqual(restore("Еще черный кот нашел зеленый мяч, а ее тетя принесла елку."),
                         "Ещё чёрный кот нашёл зелёный мяч, а её тётя принесла ёлку.")

    def test_keeps_case(self):
        self.assertEqual(restore("ЕЩЕ Подключен"), "ЕЩЁ Подключён")

    def test_leaves_words_that_may_be_either(self):
        self.assertEqual(restore("Все звезды, все небо"), "Все звезды, все небо")

    def test_leaves_written_yo_and_other_text(self):
        self.assertEqual(restore("Всё идёт. Vega 0.7"), "Всё идёт. Vega 0.7")


class UnitTests(unittest.TestCase):
    def test_degrees_and_minus(self):
        self.assertEqual(prepare("-1°, +5 °C и −22°С"), "минус 1 градус, +5 градусов и минус 22 градуса")

    def test_percent_wind(self):
        self.assertEqual(prepare("40%, 2,5 %, ветер 3 м/с, 11 км/ч"),
                         "40 процентов, 2,5 процента, ветер 3 метра в секунду, 11 километров в час")

    def test_ranges_keep_hyphen(self):
        self.assertEqual(prepare("1-2 дня, 2021-2022"), "1-2 дня, 2021-2022")


if __name__ == "__main__":
    unittest.main()
