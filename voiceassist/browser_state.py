"""Last completed active Chrome tab reported by the optional extension."""

import json
from pathlib import Path
from urllib.parse import urlsplit


def _page_key(url: str) -> str:
    """Stored form without query and fragment, so tokens never reach the disk."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Недопустимый адрес вкладки.")
    return parts._replace(query="", fragment="").geturl()


def _comparable(url: str) -> str:
    """Chrome reports "https://site.ru/" for a saved "http://www.site.ru": treat them as one page."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    if port in (80, 443):
        port = None
    path = parts.path.rstrip("/") or "/"
    return "{}{}{}".format(host, ":{}".format(port) if port else "", path)


def save_active_tab(path: Path, url: str, title: str, received_at: float) -> None:
    if len(url) > 4096 or not title or len(title) > 512:
        raise ValueError("Недопустимые данные вкладки.")
    data = {"url": _page_key(url), "loaded": True, "received_at": received_at}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False)
    temporary.replace(path)


def loaded_requested_page(path: Path, requested_url: str, launched_at: float) -> bool:
    try:
        requested_parts = urlsplit(requested_url)
        if requested_parts.query or requested_parts.fragment:
            return False
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        reported = data.get("url")
        return (isinstance(reported, str) and _comparable(reported) == _comparable(_page_key(requested_url))
                and data.get("loaded") is True
                and data.get("received_at", 0) >= launched_at)
    except (OSError, ValueError, TypeError, AttributeError):
        return False
