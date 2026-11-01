"""Books and documents read aloud with a bookmark (Ivan, 2026-11-01)."""

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from voiceassist.books import BookError, BookShelf, extract, phrases
from voiceassist.core import Assistant
from voiceassist.speech import read_book
from offwindows import setUpModule, tearDownModule  # noqa: F401

STORY = ("Глава первая\nЖил-был кот Васька. Он любил молоко и спал на тёплой печи весь день. "
         "Ночью он ловил мышей в амбаре, а утром снова спал.\n" * 6
         + "Глава вторая\nОднажды пришла зима. Снег лёг на крыши. Кот смотрел в окно и мурлыкал.\n" * 6)

FB2 = """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Кот Васька</book-title></title-info></description>
<body><section><title><p>Глава 1</p></title><p>Жил-был кот.</p><p>Он любил молоко.</p></section>
<section><title><p>Глава 2</p></title><p>Пришла зима.</p></section></body>
<body name="notes"><section><p>Примечание, его не читаем.</p></section></body>
</FictionBook>"""


class Speaker:
    """Says phrases instantly; `stop_at` makes «Ctrl» pressed while that phrase is spoken."""

    def __init__(self, stop_at=None):
        self.said, self.stop_at, self.callback = [], stop_at, None

    def connect(self, name, callback):
        self.callback = callback
        return name

    def disconnect(self, token): pass
    def startLoop(self, driver): pass
    def endLoop(self): pass
    def stop(self): pass

    def say(self, text):
        self.said.append(text)

    def iterate(self):
        if self.stop_at is None or self.stop_at not in self.said[-1]:
            self.callback("", True)


class Stream:
    def read(self, frames):
        return b"\0" * 10, False


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_txt_in_windows_1251_with_chapters(self):
        path = self.root / "кот.txt"
        path.write_bytes(STORY.encode("cp1251"))
        text, chapters, title = extract(path)
        self.assertIn("Жил-был кот Васька", text)
        self.assertEqual(len(chapters), 12)
        self.assertEqual(title, "кот")

    def test_fb2_skips_notes_and_marks_chapters(self):
        path = self.root / "kot.fb2"
        path.write_text(FB2, encoding="utf-8")
        text, chapters, title = extract(path)
        self.assertEqual(title, "Кот Васька")
        self.assertNotIn("Примечание", text)
        self.assertEqual([text[start:start + 7] for start in chapters], ["Глава 1", "Глава 2"])

    def test_docx_and_epub(self):
        docx = self.root / "письмо.docx"
        with zipfile.ZipFile(str(docx), "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                             '<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Счёт</w:t></w:r></w:p>'
                             '<w:p><w:r><w:t>Сумма 500 гривен.</w:t></w:r></w:p></w:body></w:document>')
        text, chapters, _title = extract(docx)
        self.assertEqual(text, "Счёт\nСумма 500 гривен.")
        self.assertEqual(chapters, [0])
        epub = self.root / "book.epub"
        with zipfile.ZipFile(str(epub), "w") as archive:
            archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>')
            archive.writestr("OEBPS/c.opf", '<package><metadata><title>Сказка</title></metadata><manifest>'
                             '<item id="a" href="one.xhtml"/><item id="b" href="two.xhtml"/></manifest>'
                             '<spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
            archive.writestr("OEBPS/one.xhtml", "<html><body><h1>Начало</h1><p>Раз.</p></body></html>")
            archive.writestr("OEBPS/two.xhtml", "<html><body><h1>Конец</h1><p>Два.</p></body></html>")
        text, chapters, title = extract(epub)
        self.assertEqual(title, "Сказка")
        self.assertEqual([text[start:start + 5] for start in chapters], ["Начал", "Конец"])

    def test_unknown_or_old_formats_are_explained(self):
        (self.root / "old.doc").write_bytes(b"\xd0\xcf")
        with self.assertRaises(BookError) as caught:
            extract(self.root / "old.doc")
        self.assertIn("docx", str(caught.exception))

    def test_phrases_cover_the_text_without_gaps(self):
        position, spoken = 0, []
        while True:
            piece, position = phrases(STORY, position)
            if not piece:
                break
            for offset, phrase in piece:
                self.assertTrue(STORY[offset:].startswith(phrase.split()[0]))
                self.assertLessEqual(len(phrase), 320)
                spoken.append(phrase)
        self.assertEqual(" ".join(spoken).split(), STORY.split())


class BookmarkTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.path = self.root / "Кот Васька.txt"
        self.path.write_text(STORY, encoding="utf-8")

    def tearDown(self):
        self.folder.cleanup()

    def test_ctrl_mid_book_keeps_the_phrase_and_survives_a_restart(self):
        shelf = BookShelf(self.root / "books")
        shelf.start(shelf.open(self.path))
        speaker = Speaker(stop_at="Однажды пришла зима")
        read_book(Stream(), speaker, shelf, lambda audio: False, key_stop=lambda: "Однажды пришла зима" in speaker.said[-1])
        self.assertIn("Однажды пришла зима", speaker.said[-1])
        later = BookShelf(self.root / "books")  # Vega restarted, or the laptop was switched off
        self.assertTrue(STORY[later.saved(self.path):].startswith("Однажды пришла зима"))
        later.start(later.open(self.path))
        again = Speaker()
        read_book(Stream(), again, later, lambda audio: False, key_stop=lambda: False)
        self.assertTrue(again.said[0].startswith("Однажды пришла зима"))
        self.assertEqual(again.said[-1], "Книга закончилась.")

    def test_extracted_text_is_cached(self):
        shelf = BookShelf(self.root / "books")
        shelf.open(self.path)
        with patch("voiceassist.books.extract", side_effect=AssertionError("read again")):
            self.assertIn("Васька", BookShelf(self.root / "books").open(self.path).text)


class AssistantBookTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "Кот Васька.txt").write_text(STORY, encoding="utf-8")
        (self.root / "Счёт за газ.txt").write_text("ООО Газ. Счёт номер 5. К оплате 812 гривен до 20 ноября. " * 3, encoding="utf-8")
        self.assistant = Assistant(current_directory=self.root)
        self.assistant.books = BookShelf(self.root / "books")
        self.search = patch.object(self.assistant.files, "_roots", return_value=[self.root])
        self.search.start()

    def tearDown(self):
        self.search.stop()
        self.folder.cleanup()

    def test_read_by_name_then_resume_and_chapters(self):
        first = self.assistant.handle("Вега, читай книгу кот васька")
        self.assertEqual(first.status, "reading")
        self.assertIn("Ctrl", first.message)
        self.assertEqual(self.assistant.handle("следующая глава").status, "reading")
        self.assertEqual(self.assistant.books.current.chapter_at(self.assistant.books.position), 1)
        self.assertTrue(STORY[self.assistant.books.position:].startswith("Глава"))
        resumed = self.assistant.handle("продолжи книгу")
        self.assertEqual(resumed.status, "reading")
        self.assertIn("Продолжаю", resumed.message)
        self.assertNotIn("Ctrl", resumed.message)
        self.assertIn("Кот Васька", self.assistant.handle("какие книги я читаю").message)
        self.assertEqual(self.assistant.handle("читай номер один").status, "reading")

    def test_summary_goes_to_gemini_and_without_it_reads_the_start(self):
        asked = []
        self.assistant.document_ai = lambda title, text, question: asked.append((title, question)) or "Это счёт за газ, 812 гривен до 20 ноября."
        answer = self.assistant.handle("о чем документ счет за газ")
        self.assertIn("812 гривен", answer.message)
        self.assertEqual(asked[0], ("Счёт за газ", ""))
        self.assistant.handle("спроси про документ до какого числа платить")
        self.assertEqual(asked[1][1], "до какого числа платить")
        self.assistant.document_ai = None
        offline = self.assistant.handle("кратко")
        self.assertIn("Начало: ООО Газ.", offline.message)

    def test_nothing_found_is_said(self):
        self.assertIn("не нашла", self.assistant.handle("читай книгу война и мир").message)


if __name__ == "__main__":
    unittest.main()
