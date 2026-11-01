"""Books and documents read aloud by Vega herself, with a bookmark (Ivan, 2026-11-01).

The text is taken out of the file (txt, fb2, epub, Word docx, PDF, rtf) and read in short
phrases. Before each phrase is spoken its place is written to disk, so after Ctrl, «стоп», a
crash or a power cut «продолжи книгу» starts from that very phrase. Extracted text is cached,
so a big PDF is slow only the first time on a weak laptop.
"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import time
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ElementTree
import zipfile

BOOK_EXTENSIONS = (".txt", ".fb2", ".epub", ".docx", ".pdf", ".rtf")
PART = 160        # characters in one spoken phrase, about one sentence
PIECE = 900       # characters handed to the voice at once
BACK = 1000       # «назад в книге» goes back about this much
CHAPTER = re.compile(r"^\s*(?:глава|часть|раздел|chapter|книга)\s+[\wIVXLC]+", re.IGNORECASE)


class BookError(ValueError):
    """Why a file cannot be read aloud, in words for the person."""


class Book:
    def __init__(self, path: Path, text: str, chapters: List[int], title: str):
        self.path = path
        self.text = text
        self.chapters = sorted(set(position for position in chapters if 0 <= position < len(text))) or [0]
        self.title = title

    def chapter_at(self, position: int) -> int:
        """Index of the chapter that holds position."""
        index = 0
        for number, start in enumerate(self.chapters):
            if start <= position:
                index = number
        return index


# Text out of the formats

def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").replace("\u00ad", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    return re.sub(r"\n\s*\n\s*(\n\s*)+", "\n\n", text).strip()


def _join(blocks: List[Tuple[str, bool]]) -> Tuple[str, List[int]]:
    """Paragraphs (text, starts a chapter) into one text and chapter starts."""
    text, chapters = "", []
    for block, chapter in blocks:
        block = re.sub(r"\s+", " ", block).strip()
        if not block:
            continue
        if text:
            text += "\n"
        if chapter:
            chapters.append(len(text))
        text += block
    return text, chapters


def _text_chapters(text: str) -> List[int]:
    """Chapters of a plain text: lines that start like «Глава 3», «Часть вторая»."""
    chapters, offset = [], 0
    for line in text.split("\n"):
        if CHAPTER.match(line) and len(line) < 80:
            chapters.append(offset)
        offset += len(line) + 1
    return chapters


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1251", "replace")  # old Russian texts


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _fb2(data: bytes) -> Tuple[str, List[int], str]:
    root = ElementTree.fromstring(data)
    title = ""
    blocks: List[Tuple[str, bool]] = []
    for element in root.iter():
        if _local(element.tag) == "book-title" and not title:
            title = "".join(element.itertext()).strip()
    for body in (child for child in root if _local(child.tag) == "body"):
        if body.get("name") in ("notes", "comments"):
            continue

        def walk(node, chapter_next: bool) -> bool:
            for child in node:
                name = _local(child.tag)
                if name == "section":
                    chapter_next = walk(child, True)
                elif name == "title":
                    blocks.append((" ".join("".join(p.itertext()) for p in child) or "".join(child.itertext()), True))
                    chapter_next = False
                elif name in ("p", "v", "subtitle", "text-author"):
                    blocks.append(("".join(child.itertext()), chapter_next))
                    chapter_next = False
                elif name in ("poem", "stanza", "cite", "epigraph"):
                    chapter_next = walk(child, chapter_next)
            return chapter_next

        walk(body, False)
    text, chapters = _join(blocks)
    return text, chapters, title


class _HtmlText(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "section"}

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _html_text(markup: str) -> str:
    parser = _HtmlText()
    parser.feed(markup)
    return "\n".join(re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).split("\n"))


def _epub(path: Path) -> Tuple[str, List[int], str]:
    with zipfile.ZipFile(str(path)) as archive:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        opf_path = next(element.get("full-path") for element in container.iter() if _local(element.tag) == "rootfile")
        opf = ElementTree.fromstring(archive.read(opf_path))
        base = PurePosixPath(opf_path).parent
        title = next(("".join(element.itertext()).strip() for element in opf.iter() if _local(element.tag) == "title"), "")
        manifest = {item.get("id"): item.get("href") for item in opf.iter() if _local(item.tag) == "item"}
        spine = [item.get("idref") for item in opf.iter() if _local(item.tag) == "itemref"]
        blocks: List[Tuple[str, bool]] = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            name = str(base / href.split("#")[0]) if str(base) != "." else href.split("#")[0]
            try:
                markup = _decode(archive.read(name))
            except KeyError:
                continue
            lines = [line for line in _html_text(markup).split("\n") if line.strip()]
            for number, line in enumerate(lines):
                blocks.append((line, number == 0))
    text, chapters = _join(blocks)
    return text, chapters, title


WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx(path: Path) -> Tuple[str, List[int], str]:
    with zipfile.ZipFile(str(path)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    blocks: List[Tuple[str, bool]] = []
    for paragraph in root.iter(WORD + "p"):
        style = paragraph.find("./{0}pPr/{0}pStyle".format(WORD))
        heading = style is not None and re.match(r"(?i)(heading|заголовок|title)", style.get(WORD + "val", "") or "")
        pieces = []
        for node in paragraph.iter():
            if node.tag == WORD + "t":
                pieces.append(node.text or "")
            elif node.tag in (WORD + "tab", WORD + "br"):
                pieces.append(" ")
        blocks.append(("".join(pieces), bool(heading)))
    text, chapters = _join(blocks)
    return text, chapters, ""


def _rtf(data: bytes) -> str:
    """Plain text of an RTF file: enough to read it aloud, formatting is dropped."""
    source = data.decode("latin-1")
    source = re.sub(r"\{\\\*[^{}]*\}", "", source)
    for group in ("fonttbl", "colortbl", "stylesheet", "info"):
        source = re.sub(r"\{\\" + group + r"(?:[^{}]|\{[^{}]*\})*\}", "", source)
    source = re.sub(r"\\par[d]?\b ?|\\line\b ?", "\n", source)
    source = re.sub(r"\\'([0-9a-fA-F]{2})", lambda match: bytes([int(match.group(1), 16)]).decode("cp1251"), source)
    source = re.sub(r"\\u(-?\d+)\??", lambda match: chr(int(match.group(1)) % 65536), source)
    source = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", source)
    return source.replace("{", "").replace("}", "").replace("\\\\", "\\")


def _pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise BookError("PDF читать пока не умею: не хватает модуля.")
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:
        raise BookError("Не получилось открыть этот PDF.")
    text = "\n\n".join(pages)
    if len(re.sub(r"\s", "", text)) < 40 * max(1, len(pages)) / 4:
        raise BookError("В этом PDF нет текста, это отсканированные картинки. Такие я пока читать не умею.")
    return text


def extract(path: Path) -> Tuple[str, List[int], str]:
    """(text, chapter starts, title) of a book or document."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".fb2":
            text, chapters, title = _fb2(path.read_bytes())
        elif suffix == ".epub":
            text, chapters, title = _epub(path)
        elif suffix == ".docx":
            text, chapters, title = _docx(path)
        elif suffix == ".pdf":
            text = _clean(_pdf(path))
            chapters, title = _text_chapters(text), ""
        elif suffix == ".rtf":
            text = _clean(_rtf(path.read_bytes()))
            chapters, title = _text_chapters(text), ""
        elif suffix == ".txt":
            text = _clean(_decode(path.read_bytes()))
            chapters, title = _text_chapters(text), ""
        elif suffix == ".doc":
            raise BookError("Старые файлы Word с расширением doc я читать не умею. Попросите помощника сохранить его в формате docx.")
        else:
            raise BookError("Файл «{}» не книга и не документ, читать его вслух я не умею.".format(path.name))
    except BookError:
        raise
    except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile, ElementTree.ParseError):
        raise BookError("Не получилось прочитать файл «{}». Возможно, он повреждён.".format(path.name))
    if not text.strip():
        raise BookError("В файле «{}» нет текста.".format(path.name))
    return text, chapters, title or path.stem


# Phrases

SENTENCE_END = re.compile(r"(?<=[.!?…;:])[»\"')\]]*\s+|\n+")


def _phrase_end(text: str, start: int) -> int:
    """End of the phrase from start: a sentence or two, about PART characters; a new line always ends it."""
    hard = start + PART * 2
    for match in SENTENCE_END.finditer(text, start, min(len(text), hard)):
        if "\n" in match.group(0) or match.end() - start >= PART // 2:
            return match.end()
    if hard >= len(text):
        return len(text)
    cut = max(text.rfind(", ", start, hard), text.rfind(" ", start, hard))  # a sentence without full stops
    return cut + 1 if cut > start + PART // 2 else hard


def phrases(text: str, start: int, limit: int = PIECE) -> Tuple[List[Tuple[int, str]], int]:
    """([(offset, phrase)], where the next piece starts): about `limit` characters from start."""
    result: List[Tuple[int, str]] = []
    position, total = start, 0
    while position < len(text) and total < limit:
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        end = _phrase_end(text, position)
        phrase = re.sub(r"\s+", " ", text[position:end]).strip()
        if phrase:
            result.append((position, phrase))
            total += len(phrase)
        position = end
    return result, position


# The shelf: cache and bookmarks

class BookShelf:
    def __init__(self, folder: Optional[Path], clock=time.time):
        self.folder = folder
        self.clock = clock
        self.marks: Dict[str, dict] = {}
        self.current: Optional[Book] = None
        self.position = 0
        self.listed: List[Path] = []
        if folder is not None:
            try:
                self.marks = json.loads((folder / "bookmarks.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.marks = {}

    def _cache(self, path: Path) -> Optional[Path]:
        if self.folder is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        key = hashlib.sha1("{}|{}|{}".format(path, stat.st_size, stat.st_mtime_ns).encode("utf-8")).hexdigest()[:20]
        return self.folder / (key + ".json")

    def open(self, path: Path) -> Book:
        cache = self._cache(path)
        if cache is not None:
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                return Book(path, saved["text"], saved["chapters"], saved["title"])
            except (OSError, ValueError, KeyError):
                pass
        text, chapters, title = extract(path)
        if cache is not None:
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"text": text, "chapters": chapters, "title": title}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return Book(path, text, chapters, title)

    def start(self, book: Book, position: Optional[int] = None) -> None:
        self.current = book
        self.position = self.saved(book.path) if position is None else max(0, min(position, len(book.text)))
        self.save(self.position)

    def saved(self, path: Path) -> int:
        mark = self.marks.get(str(path))
        return int(mark.get("position", 0)) if mark else 0

    def save(self, position: int) -> None:
        """The bookmark: written at once, so a power cut loses at most the phrase being read."""
        if self.current is None:
            return
        self.position = position
        self.marks[str(self.current.path)] = {"position": position, "length": len(self.current.text),
                                              "title": self.current.title, "time": self.clock()}
        if self.folder is None:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            temporary = self.folder / "bookmarks.tmp"
            temporary.write_text(json.dumps(self.marks, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.folder / "bookmarks.json")
        except OSError:
            pass

    def next_piece(self) -> Tuple[List[Tuple[int, str]], int]:
        """The next phrases to read and where the piece after them starts; no phrases at the end."""
        if self.current is None:
            return [], 0
        return phrases(self.current.text, self.position)

    def percent(self) -> int:
        if self.current is None or not self.current.text:
            return 0
        return min(100, self.position * 100 // len(self.current.text))

    def recent(self) -> List[Tuple[Path, dict]]:
        marks = [(Path(path), mark) for path, mark in self.marks.items()]
        return sorted(marks, key=lambda item: -item[1].get("time", 0))

    def last_path(self) -> Optional[Path]:
        for path, _mark in self.recent():
            if path.exists():
                return path
        return None

    def back(self) -> None:
        """About a paragraph back, to the start of a phrase."""
        if self.current is None:
            return
        target = max(0, self.position - BACK)
        text = self.current.text
        newline = text.rfind("\n", 0, target)
        sentence = max(text.rfind(". ", 0, target), text.rfind("! ", 0, target), text.rfind("? ", 0, target))
        start = max(newline + 1, sentence + 2 if sentence >= 0 else 0) if target else 0
        self.save(start if start <= self.position else 0)
