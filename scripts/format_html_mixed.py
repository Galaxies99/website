#!/usr/bin/env python3
"""
Indent the document with 2 spaces, except keep <a> <b> <i> <strong> <sup>
(and void tags) compact (no extra line breaks inside those tags).
"""
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "index.html"

# Phrasing tags that stay on one logical line (no indent between open/close)
INLINE_COMPACT = frozenset({"a", "b", "i", "span", "strong", "sup"})

VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

# Block-ish containers that mix text + inline (use line buffering for text runs)
MIXED_BLOCK = frozenset(
    {"p", "td", "th", "div", "heading", "papertitle", "name", "li", "blockquote"}
)


def attrs_str(attrs):
    if not attrs:
        return ""
    parts = []
    for k, v in attrs.items():
        if k is None:
            continue
        if k == "class":
            val = " ".join(v) if isinstance(v, list) else v
            parts.append(f' class="{val}"')
        elif isinstance(v, list):
            parts.append(f' {k}="{" ".join(v)}"')
        elif v is None or v is True:
            parts.append(f" {k}")
        else:
            parts.append(f' {k}="{v}"')
    return "".join(parts)


def void_render(el):
    name = el.name
    a = attrs_str(el.attrs)
    if name == "br":
        return "<br/>"
    if name == "img":
        return f"<img{a}/>"
    if name == "meta":
        return f"<meta{a}/>"
    if name == "link":
        return f"<link{a}/>"
    return f"<{name}{a}/>"


def render_compact(el):
    """Single-line style for INLINE_COMPACT; nested non-compact tags collapsed to one line."""
    if isinstance(el, NavigableString):
        return str(el)
    if isinstance(el, Comment):
        return f"<!--{el}-->"
    name = el.name
    if name is None:
        return ""
    a = attrs_str(el.attrs)
    if name in VOID_TAGS:
        return void_render(el)
    if name in INLINE_COMPACT:
        inner = "".join(render_compact(c) for c in el.children)
        if name == "span":
            # collapse internal whitespace for span; keep single spaces between text/inline
            inner = re.sub(r"[\n\r\t]+", " ", inner)
            inner = re.sub(r" +", " ", inner).strip()
        return f"<{name}{a}>{inner}</{name}>"
    inner = "".join(render_compact(c) for c in el.children)
    inner = re.sub(r"\s+", " ", inner).strip()
    return f"<{name}{a}>{inner}</{name}>"


def _flush_mixed_line_parts(pad, line_parts, out_lines):
    joined = "".join(line_parts).rstrip()
    if joined.strip():
        out_lines.append(pad + "  " + joined)


def render_mixed_block(el, indent):
    pad = "  " * indent
    a = attrs_str(el.attrs)
    line_parts = []
    out_lines = []
    for c in el.children:
        if isinstance(c, NavigableString):
            s = str(c)
            # Newlines/indent in the source must not create unindented continuation lines
            s = re.sub(r"[\n\r\t]+", " ", s)
            s = re.sub(r" +", " ", s)
            if not s:
                continue
            if not s.strip():
                line_parts.append(" ")
                continue
            line_parts.append(s)
        elif isinstance(c, Comment):
            if line_parts:
                _flush_mixed_line_parts(pad, line_parts, out_lines)
                line_parts = []
            out_lines.append(pad + "  " + f"<!--{c}-->")
        elif c.name in INLINE_COMPACT:
            line_parts.append(render_compact(c))
        elif c.name in VOID_TAGS:
            line_parts.append(void_render(c))
        else:
            if line_parts:
                _flush_mixed_line_parts(pad, line_parts, out_lines)
                line_parts = []
            blk = render_block(c, indent + 1).rstrip("\n")
            if blk:
                out_lines.append(blk)
    if line_parts:
        _flush_mixed_line_parts(pad, line_parts, out_lines)
    inner = "\n".join(out_lines)
    return f"{pad}<{el.name}{a}>\n{inner}\n{pad}</{el.name}>\n"


def render_block(el, indent):
    pad = "  " * indent
    if isinstance(el, NavigableString):
        t = str(el)
        if not t.strip():
            return ""
        return pad + t.strip() + "\n"
    if isinstance(el, Comment):
        return pad + str(el) + "\n"
    if isinstance(el, Doctype):
        return ""
    name = el.name
    if name is None:
        return ""
    a = attrs_str(el.attrs)
    if name in INLINE_COMPACT:
        return pad + render_compact(el) + "\n"
    if name in VOID_TAGS:
        return pad + void_render(el) + "\n"
    children = list(el.children)
    if not children:
        return f"{pad}<{name}{a}></{name}>\n"

    if name == "script":
        inner = el.string
        if inner is None:
            inner = "".join(str(c) for c in el.children)
        return f"{pad}<script>{inner}</script>\n"

    if name in MIXED_BLOCK:
        return render_mixed_block(el, indent)

    lines = [f"{pad}<{name}{a}>"]
    for c in children:
        blk = render_block(c, indent + 1).rstrip("\n")
        if blk:
            lines.append(blk)
    lines.append(f"{pad}</{name}>")
    return "\n".join(lines) + "\n"


def render_document(soup):
    out = ["<!DOCTYPE HTML>\n"]
    for child in soup.children:
        if isinstance(child, Doctype):
            continue
        if isinstance(child, NavigableString) and not str(child).strip():
            continue
        out.append(render_block(child, 0))
    return "".join(out)


def main():
    html = PATH.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    PATH.write_text(render_document(soup), encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
