"""Opening web addresses for Vega, with a way around a provider that hides a site.

2026-10-15: on Ivan's laptop in Ukraine Chrome opened kinokrad, but Vega's own requests to the
film sites failed («Кинокрад не ответил»), while the same requests from a Windows runner abroad
worked. Providers there block sites through their DNS; Chrome asks Google's DNS over HTTPS itself.
So when a site cannot be reached, Vega asks dns.google (then Cloudflare) for its address and
connects to that address directly, with the site's own name for the certificate check.
Every failure is written to last-error.log through problem_log, so the reason is visible.
"""

import http.client
import json
import socket
import ssl
from typing import Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

problem_log: Callable[[str], None] = lambda message: None
_resolved: Dict[str, str] = {}
DOH = ("https://dns.google/resolve?name={}&type=A", "https://cloudflare-dns.com/dns-query?name={}&type=A")


def context() -> ssl.SSLContext:
    """Windows 7 and 8 often lack newer root certificates; certifi's bundle fills the gap when installed."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def resolve(host: str, timeout: float = 6) -> Optional[str]:
    """The site's address from DNS over HTTPS, past the provider's DNS."""
    if host in _resolved:
        return _resolved[host]
    for template in DOH:
        try:
            request = Request(template.format(quote(host)), headers={"Accept": "application/dns-json"})
            with urlopen(request, timeout=timeout, context=context()) as response:
                answers = json.loads(response.read().decode("utf-8")).get("Answer", [])
        except (OSError, ValueError) as error:
            problem_log("DNS через HTTPS ({}) не ответил для {}: {}".format(urlparse(template).netloc, host, error))
            continue
        addresses = [item.get("data") for item in answers if item.get("type") == 1]
        if addresses:
            _resolved[host] = addresses[0]
            return addresses[0]
    return None


class _Pinned(http.client.HTTPSConnection):
    """An HTTPS connection to a known address that still checks the certificate of the site's name."""

    def connect(self):
        address = _resolved.get(self.host)
        if address is None:
            return super().connect()
        sock = socket.create_connection((address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_Pinned, request, context=self._context)


def open_url(request: Request, timeout: float):
    """urlopen that, when a site cannot be reached, tries again through its address from DNS over HTTPS."""
    try:
        return urlopen(request, timeout=timeout, context=context())
    except HTTPError:
        raise
    except (URLError, OSError) as error:
        host = urlparse(request.full_url).hostname or ""
        problem_log("Нет связи с {}: {}".format(host, getattr(error, "reason", error)))
        if not host or request.full_url.startswith("http:") or resolve(host) is None:
            raise
    try:
        return build_opener(_PinnedHandler(context=context())).open(request, timeout=timeout)
    except HTTPError:
        raise
    except (URLError, OSError) as error:
        problem_log("И через адрес {} нет связи с {}: {}".format(_resolved.get(host), host, getattr(error, "reason", error)))
        raise


def check(urls: List[str]) -> List[str]:
    """One line per address for the help report: reachable or the exact error."""
    import time
    lines = []
    for url in urls:
        start = time.monotonic()
        try:
            with open_url(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as response:
                response.read(1024)
                lines.append("{}: ответ {} за {:.1f} с{}".format(url, response.status, time.monotonic() - start,
                             " (через DNS по HTTPS)" if urlparse(url).hostname in _resolved else ""))
        except HTTPError as error:
            lines.append("{}: ответ {} за {:.1f} с".format(url, error.code, time.monotonic() - start))
        except (OSError, ValueError) as error:
            lines.append("{}: НЕТ СВЯЗИ: {}".format(url, getattr(error, "reason", error)))
    return lines
