import unittest

from voiceassist.localize import Catalog


class LocalizeTests(unittest.TestCase):
    def setUp(self):
        self.missing = []
        self.catalog = Catalog({"Открыта папка {}.": "Відкрито теку {}.", "Загрузки": "Завантаження",
                                "Не поняла.": "Не зрозуміла.", "Звоню {}. Чтобы закончить, скажите: Вега, положи трубку.":
                                "Телефоную {}. Щоб завершити, скажіть: Вего, поклади слухавку."}, self.missing.append)

    def test_exact_template_and_inner_part(self):
        self.assertEqual(self.catalog.translate("Не поняла."), "Не зрозуміла.")
        self.assertEqual(self.catalog.translate("Открыта папка Загрузки."), "Відкрито теку Завантаження.")
        self.assertEqual(self.catalog.translate("Звоню Маше. Чтобы закончить, скажите: Вега, положи трубку."),
                         "Телефоную Маше. Щоб завершити, скажіть: Вего, поклади слухавку.")

    def test_sentences_and_missing(self):
        self.assertEqual(self.catalog.translate("Не поняла. Привет мир."), "Не зрозуміла. Привет мир.")
        self.assertEqual(self.missing, ["Привет мир."])


class NativeTextTests(unittest.TestCase):
    def test_ukrainian_book_is_not_looked_up(self):
        heard = []
        catalog = Catalog({"Привет.": "Привіт."}, heard.append, native="іїєґ")
        page = "Реве та стогне Дніпр широкий, сердитий вітер завива, додолу верби гне високі, горами хвилю підійма. " * 2
        self.assertEqual(catalog.translate(page), page)
        self.assertEqual(heard, [])
        self.assertEqual(catalog.translate("Привет."), "Привіт.")


class PiecesTests(unittest.TestCase):
    def test_list_and_beginning(self):
        catalog = Catalog({"Например: {}.": "Наприклад: {}.", "Который час": "Котра година", "Повтори": "Повтори",
                           "По часам компьютера сейчас ": "За годинником комп'ютера зараз "})
        self.assertEqual(catalog.translate("Например: Который час; Повтори."), "Наприклад: Котра година; Повтори.")
        self.assertEqual(catalog.translate("По часам компьютера сейчас 10:00."), "За годинником комп'ютера зараз 10:00.")
