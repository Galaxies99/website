#!/usr/bin/env python3
"""
Normalize HTML whitespace: collapse runs of spaces/newlines inside phrasing-heavy
regions so <a>/<b>/<i> etc. flow with surrounding text (no strict one-line rule).

Preserves <br/> as explicit breaks. Does not force every tag onto its own line.
"""
import re
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "index.html"


def collapse_whitespace_preserving_br(fragment: str) -> str:
    """Turn internal newlines/tabs into single spaces; keep <br/> boundaries."""
    parts = re.split(r"(<br\s*/?>)", fragment, flags=re.I)
    out = []
    for part in parts:
        if re.match(r"^<br\s*/?>$", part, re.I):
            out.append("<br/>")
        else:
            out.append(re.sub(r"\s+", " ", part).strip())
    merged = "".join(out)
    # Join adjacent tags onto one run (no requirement for one line per tag)
    merged = re.sub(r">\s+<", "><", merged)
    return merged


def replace_inner(el, new_inner: str) -> None:
    frag = BeautifulSoup(f'<div id="_w">{new_inner}</div>', "html.parser")
    node = frag.find("div", id="_w")
    el.clear()
    for c in list(node.children):
        el.append(c)


html = path.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")

# Paragraphs, titles, section headings
for el in soup.find_all(["p", "papertitle", "heading", "title"]):
    inner = el.decode_contents()
    replace_inner(el, collapse_whitespace_preserving_br(inner))

# Publication list: meta block before first <p> in each text cell (venue + links line)
for td in soup.select("table.publications-table td"):
    if td.get("colspan"):
        continue
    inner = td.decode_contents()
    m = re.search(r"<p\b", inner, re.I)
    if not m:
        replace_inner(td, collapse_whitespace_preserving_br(inner))
        continue
    head = inner[: m.start()]
    tail = inner[m.start() :]
    head = collapse_whitespace_preserving_br(head)
    replace_inner(td, head + tail)

# Do not prettify(): it breaks every <a>/<b> onto separate lines. str(soup) keeps
# phrasing tags inline with surrounding text after whitespace collapse.
out = str(soup)
if not out.lstrip().upper().startswith("<!DOCTYPE"):
    out = "<!DOCTYPE HTML>\n\n" + out.lstrip()
path.write_text(out, encoding="utf-8")
print("ok")
