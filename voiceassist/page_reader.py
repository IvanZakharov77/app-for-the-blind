"""Any page Vega opened, read without the Chrome extension: its title, headings and main text.

Ivan, 2026-10-15: with a site open, «что на странице» and «прочитай страницу» must work even
when the extension is not installed. Vega downloads the page she opened herself and reads its HTML.
"""

import re
from html import unescape
from typing import Callable, List, Optional

from .film_sites import fetch_text
from .online import Offline

DROP = re.compile(r"<(script|style|noscript|svg|template|head|nav|footer|form|select|button)\b.*?</\1\s*>", re.S | re.I)
BLOCK = re.compile(r"<(h[1-6]|p|li|td|dd|blockquote|article)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
CHUNK = 900  # about a minute of speech, then «дальше»


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text))).strip()


class Page:
    def __init__(self, title: str, headings: List[str], text: str):
        self.title = title
        self.headings = headings
        self.text = text


def parse_page(html: str) -> Page:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = _clean(match.group(1)) if match else ""
    body = DROP.sub(" ", html)
    headings, parts, seen = [], [], set()
    for tag, inner in BLOCK.findall(body):
        text = _clean(inner)
        if not text or text in seen:
            continue
        seen.add(text)
        if tag.lower().startswith("h"):
            if len(text) < 150:
                headings.append(text)
            parts.append(text + ".")
        elif len(text) >= 40 or text.endswith((".", "!", "?")):
            parts.append(text)  # short menu items and buttons are not the page's text
    return Page(title, headings, " ".join(parts))


def read_page(url: str, fetch: Callable[[str], str] = fetch_text) -> Optional[Page]:
    try:
        return parse_page(fetch(url))
    except Offline:
        return None


def chunk(text: str, offset: int) -> tuple:
    """The text from offset up to a sentence end near CHUNK characters, and where the next piece starts."""
    rest = text[offset:]
    if len(rest) <= CHUNK:
        return rest.strip(), len(text)
    cut = max(rest.rfind(". ", 0, CHUNK), rest.rfind("! ", 0, CHUNK), rest.rfind("? ", 0, CHUNK))
    cut = cut + 1 if cut > CHUNK // 3 else rest.rfind(" ", 0, CHUNK)
    return rest[:cut].strip(), offset + cut
