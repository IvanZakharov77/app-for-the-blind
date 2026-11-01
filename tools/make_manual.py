"""ИНСТРУКЦИЯ.md -> «Инструкция Веги.pdf» with a contents page (Ivan, 2026-11-01: the full guide as a PDF,
replaced on every update). The build runs it, so the PDF always matches the version it ships with.

    python tools/make_manual.py OUT.pdf      # needs Chrome or Edge (headless print)
    python tools/make_manual.py OUT.html     # HTML only

Only the Markdown this guide uses: headings, paragraphs, **bold**, `code`, lists and tables.
"""

import html
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm;
        @bottom-center { content: counter(page); font: 10pt Arial, sans-serif; color: #666; } }
@page :first { @bottom-center { content: none; } }
body { font: 12.5pt/1.5 "Segoe UI", Arial, sans-serif; color: #1b1b1f; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; text-align: center;
         page-break-after: always; }
.cover h1 { font-size: 44pt; margin: 0 0 6mm; color: #23305e; border: 0; }
.cover .version { font-size: 16pt; color: #555; }
.cover .lead { font-size: 14pt; margin: 14mm auto 0; max-width: 140mm; color: #333; }
.toc { page-break-after: always; }
.toc h2 { border: 0; }
.toc ol { list-style: none; padding: 0; font-size: 13.5pt; }
.toc li { margin: 2.2mm 0; }
.toc li li { font-size: 12pt; margin: 1mm 0 1mm 8mm; color: #333; }
.toc a { color: inherit; text-decoration: none; }
h2 { font-size: 20pt; color: #23305e; border-bottom: 2px solid #23305e; padding-bottom: 1.5mm;
     margin: 0 0 4mm; page-break-before: always; page-break-after: avoid; }
h3 { font-size: 15pt; color: #23305e; margin: 7mm 0 2mm; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
code { font-family: Consolas, monospace; font-size: 10.5pt; background: #f0f1f5; padding: 0 1mm; border-radius: 2px;
       word-break: break-all; }
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 11pt; }
th { background: #23305e; color: #fff; text-align: left; }
th, td { border: 1px solid #c9ccd8; padding: 1.6mm 2.2mm; vertical-align: top; }
tr { page-break-inside: avoid; }
tr:nth-child(even) td { background: #f6f7fb; }
td:first-child { width: 48%; font-weight: 600; }
"""


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)


def slug(index: int) -> str:
    return "s{}".format(index)


def convert(markdown: str, version: str):
    """(body html, [(level, id, title)]) for the guide."""
    markdown = markdown.replace("{{VERSION}}", version)
    lines = markdown.splitlines()
    body, toc, paragraph, list_tag, table = [], [], [], None, []

    def flush():
        nonlocal list_tag
        if paragraph:
            body.append("<p>{}</p>".format(inline(" ".join(paragraph))))
            paragraph.clear()
        if list_tag:
            body.append("</{}>".format(list_tag))
            list_tag = None
        if table:
            rows = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in table
                    if not re.fullmatch(r"\|?[\s:|-]+\|?", row.strip())]
            out = ["<table><thead><tr>"] + ["<th>{}</th>".format(inline(cell)) for cell in rows[0]] + ["</tr></thead><tbody>"]
            for row in rows[1:]:
                out.append("<tr>" + "".join("<td>{}</td>".format(inline(cell)) for cell in row) + "</tr>")
            body.append("".join(out) + "</tbody></table>")
            table.clear()

    for line in lines:
        stripped = line.strip()
        heading = re.match(r"(#{1,3}) (.+)", stripped)
        item = re.match(r"(?:(\d+)\.|-) (.+)", stripped)
        if not stripped:
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            if level == 1:
                continue  # the cover carries the title
            anchor = slug(len(toc))
            toc.append((level, anchor, heading.group(2)))
            body.append('<h{0} id="{1}">{2}</h{0}>'.format(level, anchor, inline(heading.group(2))))
        elif stripped.startswith("|"):
            if paragraph or list_tag:
                flush()
            table.append(stripped)
        elif item:
            tag = "ol" if item.group(1) else "ul"
            if paragraph or table or (list_tag and list_tag != tag):
                flush()
            if not list_tag:
                body.append("<{}>".format(tag))
                list_tag = tag
            body.append("<li>{}</li>".format(inline(item.group(2))))
        else:
            if list_tag or table:
                flush()
            paragraph.append(stripped)
    flush()
    return "\n".join(body), toc


def page(markdown: str, version: str) -> str:
    title = re.search(r"^# (.+)$", markdown, re.M).group(1)
    # The cover takes the text up to the first section; the rest is the guide.
    first = markdown.index("\n## ")
    intro, rest = markdown[:first], markdown[first:]
    intro_body, _ = convert(re.sub(r"^# .+$|^Версия .+$", "", intro, flags=re.M), version)
    body, toc = convert(rest, version)
    items, open_sub = [], False
    for level, anchor, text in toc:
        link = '<a href="#{}">{}</a>'.format(anchor, inline(text))
        if level == 2:
            if open_sub:
                items.append("</ol></li>")
                open_sub = False
            elif items:
                items.append("</li>")
            items.append("<li>" + link)
        else:
            if not open_sub:
                items.append("<ol>")
                open_sub = True
            items.append("<li>{}</li>".format(link))
    items.append("</ol></li>" if open_sub else "</li>")
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{title}</title><style>{css}</style></head>
<body><section class="cover"><h1>Вега</h1><div class="version">Полная инструкция · версия {version}</div>
<div class="lead">{intro}</div></section>
<section class="toc"><h2>Содержание</h2><ol>{toc}</ol></section>
{body}</body></html>""".format(title=html.escape(title), css=CSS, version=html.escape(version), intro=intro_body,
                               toc="".join(items), body=body)


def find_browser():
    names = [os.environ.get("VEGA_CHROME", "")]
    for root in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("LOCALAPPDATA", "")):
        if root:
            names += [os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
                      os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe")]
    names += ["/usr/bin/google-chrome", "/usr/bin/chromium", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"]
    return next((name for name in names if name and os.path.isfile(name)), None)


def print_pdf(html_path: str, pdf_path: str) -> None:
    browser = find_browser()
    if browser is None:
        raise SystemExit("Chrome or Edge not found: set VEGA_CHROME")
    profile = tempfile.mkdtemp(prefix="vega-manual-")
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
                    "--user-data-dir=" + profile, "--no-pdf-header-footer", "--print-to-pdf=" + os.path.abspath(pdf_path),
                    "file:///" + os.path.abspath(html_path).replace("\\", "/")], check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) < 20000:
        raise SystemExit("the PDF was not printed")


def main(argv) -> int:
    out = argv[1] if len(argv) > 1 else os.path.join(HERE, "build", "manual", "Инструкция Веги.pdf")
    sys.path.insert(0, HERE)
    import voiceassist
    with open(os.path.join(HERE, "ИНСТРУКЦИЯ.md"), encoding="utf-8") as source:
        document = page(source.read(), voiceassist.__version__)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    html_path = out if out.endswith(".html") else os.path.splitext(out)[0] + ".html"
    with open(html_path, "w", encoding="utf-8") as target:
        target.write(document)
    if out.endswith(".pdf"):
        print_pdf(html_path, out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
