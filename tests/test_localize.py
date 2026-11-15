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
