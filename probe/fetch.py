import sys, urllib.request, urllib.parse, ssl, pathlib
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0 Safari/537.36"
q = "солярис"
targets = {
    "kinokrad_home": ("https://kinokrad.my/s27", None),
    "kinokrad_get": ("https://kinokrad.my/index.php?do=search&subaction=search&story=" + urllib.parse.quote(q), None),
    "kinokrad_post": ("https://kinokrad.my/index.php?do=search", {"do": "search", "subaction": "search", "story": q}),
    "rezka_get": ("https://hdrezka.la/search/?do=search&subaction=search&q=" + urllib.parse.quote(q), None),
    "filmix_home": ("https://filmix.gg/", None),
    "filmix_search": ("https://filmix.gg/search/" + urllib.parse.quote(q), None),
}
out = pathlib.Path("out"); out.mkdir(exist_ok=True)
for name, (url, form) in targets.items():
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "ru"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            print(name, r.status, r.geturl(), len(body))
            (out / (name + ".html")).write_bytes(body)
    except Exception as e:
        print(name, "ERROR", repr(e)[:200])
