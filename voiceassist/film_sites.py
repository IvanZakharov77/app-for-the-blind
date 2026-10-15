"""Film sites without the Chrome extension: Vega reads their pages and searches them herself.

Ivan, 2026-10-15: after «открой кинокрад» he wants «какие фильмы здесь», «найди фильм Человек-паук»
on the open site, and «найди фильм Человек-паук на кинокраде». The extension is not needed: the
film lists are in the HTML of the pages (checked on a Windows runner, 2026-10-15).
"""

import gzip
import json
import re
from html import unescape
from typing import Callable, List, Optional
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .online import Offline, _context

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0 Safari/537.36"
MAX_BYTES = 4 * 1024 * 1024


def fetch_text(url: str) -> str:
    headers = {"User-Agent": UA, "Accept-Language": "ru", "Accept-Encoding": "gzip"}
    if "/api/" in url:
        headers["X-Requested-With"] = "XMLHttpRequest"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=12, context=_context()) as response:
            data = response.read(MAX_BYTES + 1)[:MAX_BYTES]
            declared = response.headers.get_content_charset()
            packed = response.headers.get("Content-Encoding", "") == "gzip"
    except (OSError, ValueError) as error:
        raise Offline(str(error)) from error
    if packed or data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError):
            pass
    charset = declared
    if not charset:
        match = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", data[:4096], re.I)
        charset = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return data.decode(charset, "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", text))).strip()


def _unique(items: List[dict]) -> List[dict]:
    seen, result = set(), []
    for item in items:
        if item["url"] not in seen and item["name"]:
            seen.add(item["url"])
            result.append(item)
    return result


def parse_kinokrad(page: str) -> List[dict]:
    # <a class="kino-poster" itemprop="url" href="https://kinokrad.my/3475-soljaris.html" title="Солярис (2003)">
    found = re.findall(r'<a class="kino-poster"[^>]*href="([^"]+)"[^>]*title="([^"]+)"', page)
    return _unique([{"name": _clean(title), "detail": "", "url": url} for url, title in found])


def parse_rezka(page: str) -> List[dict]:
    # <div class="b-content__inline_item-link"> <a href="…">Человек-паук</a> <div>2002, США, Боевики</div>
    found = re.findall(r'b-content__inline_item-link">\s*<a href="([^"]+)">(.*?)</a>\s*(?:<div>(.*?)</div>)?', page, re.S)
    return _unique([{"name": _clean(name), "detail": _clean(detail or ""), "url": url} for url, name, detail in found])


def parse_filmix(page: str) -> List[dict]:
    stripped = page.lstrip()
    if stripped.startswith("{"):  # the suggestions API
        try:
            posts = json.loads(stripped).get("posts", [])
        except ValueError:
            return []
        return _unique([{"name": _clean(str(post.get("title", ""))), "detail": str(post.get("year") or ""),
                         "url": str(post.get("link", ""))} for post in posts if isinstance(post, dict)])
    found = re.findall(r'<h2 class="name" itemprop="name" content="([^"]+)"><a itemprop="url" href="([^"]+)"', page)
    return _unique([{"name": _clean(name), "detail": "", "url": url} for name, url in found])


class FilmSite:
    def __init__(self, title: str, hosts, search_page: str, search_data: str, parse: Callable[[str], List[dict]]):
        self.title = title
        self.hosts = hosts
        self.search_page = search_page  # what the browser shows
        self.search_data = search_data  # what Vega reads
        self.parse = parse


SITES = {
    "kinokrad": FilmSite("Кинокрад", ("kinokrad",), "https://kinokrad.my/index.php?do=search&subaction=search&story={}",
                         "https://kinokrad.my/index.php?do=search&subaction=search&story={}", parse_kinokrad),
    # hdrezka.la asks for a login; rezka.ag shows the same films to everyone.
    "rezka": FilmSite("Резка", ("rezka", "hdrezka"), "https://rezka.ag/search/?do=search&subaction=search&q={}",
                      "https://rezka.ag/search/?do=search&subaction=search&q={}", parse_rezka),
    "filmix": FilmSite("Филмикс", ("filmix",), "https://filmix.gg/search/{}",
                       "https://filmix.gg/api/v2/suggestions?search_word={}", parse_filmix),
}
SPOKEN_SITES = {"кинокраде": "kinokrad", "кинокрад": "kinokrad", "кино краде": "kinokrad", "резке": "rezka", "хд резке": "rezka",
                "хдрезке": "rezka", "резка": "rezka", "филмиксе": "filmix", "фильмиксе": "filmix", "филмикс": "filmix",
                "фильмикс": "filmix"}


def site_of(url: Optional[str]) -> Optional[str]:
    host = urlparse(url or "").netloc.lower()
    for key, site in SITES.items():
        if any(name in host for name in site.hosts):
            return key
    return None


def search(key: str, query: str, fetch: Callable[[str], str] = fetch_text) -> Optional[List[dict]]:
    site = SITES[key]
    try:
        return site.parse(fetch(site.search_data.format(quote(query))))
    except Offline:
        return None


def films_on(url: str, fetch: Callable[[str], str] = fetch_text) -> Optional[List[dict]]:
    key = site_of(url)
    if key is None:
        return None
    if key == "rezka":
        # Some Rezka mirrors (hdrezka.la) show a login page to programs; rezka.ag has the same paths.
        parts = urlparse(url)
        url = parts._replace(netloc="rezka.ag").geturl()
    try:
        films = SITES[key].parse(fetch(url))
        if not films and key == "rezka" and urlparse(url).path in ("", "/"):
            films = SITES[key].parse(fetch("https://rezka.ag/new/"))  # the main page lists films in a slider
        return films
    except Offline:
        return None
