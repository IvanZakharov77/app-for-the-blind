"""YouTube search results without the Chrome extension: the results page itself carries them as JSON.

Ivan, 2026-10-15: without the extension Vega opened the search but could not read what was found.
Now she reads the titles herself and «включи номер два» opens that video in the browser.
"""

import json
import re
from typing import Callable, List, Optional
from urllib.parse import quote_plus
from urllib.request import Request

from .net import open_url
from .online import Offline

SEARCH_URL = "https://www.youtube.com/results?search_query={}&hl=ru&gl=UA"
MAX_BYTES = 6 * 1024 * 1024
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0 Safari/537.36",
    "Accept-Language": "ru,uk;q=0.8,en;q=0.5",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",  # skip the cookie consent page some regions get
}


def fetch_page(url: str) -> str:
    try:
        with open_url(Request(url, headers=HEADERS), timeout=10) as response:
            data = response.read(MAX_BYTES + 1)
    except (OSError, ValueError) as error:
        raise Offline(str(error)) from error
    return data[:MAX_BYTES].decode("utf-8", "replace")


def _text(value) -> str:
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    return "".join(run.get("text", "") for run in value.get("runs", []) if isinstance(run, dict))


def _videos(node, found: List[dict]) -> None:
    if isinstance(node, dict):
        video = node.get("videoRenderer")
        if isinstance(video, dict) and video.get("videoId"):
            title = _text(video.get("title")).strip()
            if title:
                details = [part for part in (_text(video.get("ownerText")).strip(), _text(video.get("lengthText")).strip()) if part]
                found.append({"name": title, "detail": ", ".join(details),
                              "url": "https://www.youtube.com/watch?v=" + video["videoId"]})
            return
        for value in node.values():
            _videos(value, found)
    elif isinstance(node, list):
        for value in node:
            _videos(value, found)


def parse_results(page: str) -> List[dict]:
    match = re.search(r"(?:var ytInitialData|window\[\"ytInitialData\"\])\s*=\s*", page)
    if not match:
        return []
    try:
        data, _end = json.JSONDecoder().raw_decode(page, match.end())
    except ValueError:
        return []
    found: List[dict] = []
    _videos(data, found)
    unique, seen = [], set()
    for item in found:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


def search(query: str, fetch: Callable[[str], str] = fetch_page) -> Optional[List[dict]]:
    """Videos found for the query, best first; None when YouTube could not be reached."""
    try:
        return parse_results(fetch(SEARCH_URL.format(quote_plus(query))))
    except Offline:
        return None
