import unittest

from voiceassist.lang_uk import to_russian
from voiceassist.speech import parse_wake


class UkrainianCommandTests(unittest.TestCase):
    def check(self, heard, command):
        self.assertEqual(to_russian(heard), command)

    def test_common_commands(self):
        self.check("вего котра година", "вега который час")
        self.check("вего увімкни радіо джаз", "вега включи радио джаз")
        self.check("відкрий завантаження", "открой загрузки")
        self.check("що в теці", "что в папке")
        self.check("гучніше", "громче")
        self.check("постав таймер на п'ять хвилин", "поставь таймер на пять минут")
        self.check("вего досить", "вега хватит")

    def test_free_text_stays_ukrainian(self):
        self.check("запиши нотатку купити хліб і молоко", "запиши заметку купити хліб і молоко")
        self.check("надішли повідомлення артему привіт як справи", "отправь сообщение артему привіт як справи")
        self.check("знайди в інтернеті рецепт борщу", "найди в интернете рецепт борщу")
        self.check("відповідай на дзвінок", "ответь на звонок")

    def test_wake_word(self):
        self.assertEqual(parse_wake(to_russian("вего яка погода")), (True, "какая погода"))
        self.assertEqual(parse_wake(to_russian("привіт вего")), (True, ""))
