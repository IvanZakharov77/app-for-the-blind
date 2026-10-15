import urllib.request, urllib.parse, pathlib, http.cookiejar
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0 Safari/537.36"
q = "человек паук"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
targets = [
    ("filmix_home", "https://filmix.gg/", None, {}),
    ("filmix_ajax", "https://filmix.gg/engine/ajax/sphinx_search.php", {"scf": "fx", "story": q.encode("cp1251"), "search_start": "0", "do": "search", "subaction": "search"}, {"X-Requested-With": "XMLHttpRequest", "Referer": "https://filmix.gg/search/"}),
    ("filmix_ajax_utf", "https://filmix.gg/engine/ajax/sphinx_search.php", {"scf": "fx", "story": q, "search_start": "0", "do": "search", "subaction": "search"}, {"X-Requested-With": "XMLHttpRequest", "Referer": "https://filmix.gg/search/"}),
    ("filmix_quick", "https://filmix.gg/api/v2/suggestions?search_word=" + urllib.parse.quote(q), None, {"X-Requested-With": "XMLHttpRequest"}),
    ("filmix_search_q", "https://filmix.gg/search/" + urllib.parse.quote(q), None, {}),
    ("rezka_la_home", "https://hdrezka.la/", None, {}),
    ("rezka_ag_search", "https://hdrezka.ag/search/?do=search&subaction=search&q=" + urllib.parse.quote(q), None, {}),
    ("rezka_me_search", "https://rezka.ag/search/?do=search&subaction=search&q=" + urllib.parse.quote(q), None, {}),
    ("rezka_la_search2", "https://hdrezka.la/index.php?do=search&subaction=search&q=" + urllib.parse.quote(q), None, {}),
    ("kinokrad_search", "https://kinokrad.my/index.php?do=search&subaction=search&story=" + urllib.parse.quote(q), None, {}),
]
out = pathlib.Path("out"); out.mkdir(exist_ok=True)
for name, url, form, extra in targets:
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(url, data=data, headers=dict({"User-Agent": UA, "Accept-Language": "ru"}, **extra))
    try:
        with opener.open(req, timeout=20) as r:
            body = r.read()
            msg = "{} {} {}".format(r.status, r.geturl(), len(body))
            (out / (name + ".html")).write_bytes(body)
    except Exception as e:
        msg = "ERROR " + repr(e)[:200]
        try:
            (out / (name + ".err.html")).write_bytes(e.read())
        except Exception:
            pass
    print(name, msg)
    print("::warning title=" + name + "::" + msg)
