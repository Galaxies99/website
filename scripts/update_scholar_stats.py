#!/usr/bin/env python3
"""Render Google Scholar metrics at build time, retaining the last valid snapshot."""

import argparse
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

SCHOLAR_ID = "Kyio_RAAAAAJ"
SCHOLAR_URL = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
ROOT = Path(__file__).resolve().parents[1]
START = "<!-- scholar-stats:start -->"
END = "<!-- scholar-stats:end -->"


class ScholarParser(HTMLParser):
    """Read the profile name and summary table, not individual paper citations."""

    def __init__(self):
        super().__init__()
        self.name = []
        self.in_name = False
        self.table_depth = 0
        self.rows = []
        self.row = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "gsc_prf_in":
            self.in_name = True
        if tag == "table":
            if self.table_depth or attrs.get("id") == "gsc_rsb_st":
                self.table_depth += 1
        if self.table_depth:
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th"):
                self.cell = []

    def handle_data(self, data):
        if self.in_name:
            self.name.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "div":
            self.in_name = False
        if not self.table_depth:
            return
        if tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr":
            self.rows.append(self.row)
        elif tag == "table":
            self.table_depth -= 1


def validate_stats(stats):
    if not isinstance(stats, dict) or stats.get("scholar_id") != SCHOLAR_ID:
        raise ValueError("Scholar profile ID is missing or incorrect")
    for field in ("citations", "h_index"):
        value = stats.get(field)
        if type(value) is not int or value < 0:
            raise ValueError(f"Invalid {field}")
    if stats["h_index"] > stats["citations"]:
        raise ValueError("h-index exceeds citations")
    timestamp = stats.get("updated_at")
    if not isinstance(timestamp, str):
        raise ValueError("Missing update timestamp")
    if datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("Update timestamp must include a timezone")
    return stats


def parse_scholar(page):
    parser = ScholarParser()
    parser.feed(page)
    if " ".join("".join(parser.name).split()) != "Hongjie Fang":
        raise ValueError("Expected Scholar profile not found (possibly a verification page)")
    if not parser.rows or "All" not in parser.rows[0]:
        raise ValueError("All-time Scholar summary column not found")
    column = parser.rows[0].index("All")
    rows = {row[0].casefold(): row for row in parser.rows[1:] if row}
    metrics = {}
    for label, field in (("citations", "citations"), ("h-index", "h_index")):
        row = rows.get(label, [])
        if len(row) <= column:
            raise ValueError(f"Missing Scholar {label}")
        value = row[column]
        if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", value):
            raise ValueError(f"Invalid Scholar {label}: {value!r}")
        metrics[field] = int(value.replace(",", ""))
    return validate_stats({
        "scholar_id": SCHOLAR_ID,
        **metrics,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def fetch_stats():
    request = Request(SCHOLAR_URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PersonalWebsiteScholarStats/1.0)",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(request, timeout=20) as response:
        page = response.read(2_000_001)
    if len(page) > 2_000_000:
        raise ValueError("Unexpectedly large Scholar response")
    return parse_scholar(page.decode("utf-8"))


def load_cached_stats(path):
    try:
        return validate_stats(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        print(f"Scholar cache unavailable: {error}")
        return None


def render_stats(page, stats):
    validate_stats(stats)
    if page.count(START) != 1 or page.count(END) != 1 or page.index(START) > page.index(END):
        raise ValueError("Expected one Scholar metrics placeholder in the homepage")
    updated = datetime.fromisoformat(stats["updated_at"].replace("Z", "+00:00"))
    updated = updated.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = escape(f"Google Scholar · All-time metrics · Updated {updated}", quote=True)
    link = (
        f'<a class="scholar-stats" href="{escape(SCHOLAR_URL, quote=True)}" '
        f'title="{title}"><span class="scholar-stat">'
        f'<strong>{stats["citations"]:,}</strong> citations</span>'
        ' <span class="scholar-stats-separator" aria-hidden="true">·</span> '
        f'<span class="scholar-stat">h-index <strong>{stats["h_index"]}</strong></span></a>'
    )
    before, rest = page.split(START, 1)
    _, after = rest.split(END, 1)
    return f"{before}{START}\n                      {link}\n                      {END}{after}"


def save_stats(path, stats):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def update_stats(cache_path, html_path, fetcher=fetch_stats, snapshot_path=None):
    page = html_path.read_text(encoding="utf-8")
    paths = [cache_path] + ([snapshot_path] if snapshot_path else [])
    snapshots = [stats for path in paths if (stats := load_cached_stats(path)) is not None]
    stats = max(snapshots, key=lambda item: datetime.fromisoformat(
        item["updated_at"].replace("Z", "+00:00")), default=None)
    fresh = False
    try:
        stats = validate_stats(fetcher())
        fresh = True
    except (OSError, ValueError) as error:
        print(f"::warning::Google Scholar refresh failed; retaining cached metrics. {error}")
    if stats is None:
        print("No verified metrics available; leaving the existing homepage unchanged.")
        return False
    rendered = render_stats(page, stats)
    save_stats(cache_path, stats)
    if snapshot_path:
        save_stats(snapshot_path, stats)
    html_path.write_text(rendered, encoding="utf-8")
    print(f"Rendered {stats['citations']:,} citations · h-index {stats['h_index']} "
          f"({'fresh' if fresh else 'cached'}, {stats['updated_at']})")
    return fresh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/scholar-stats.json")
    parser.add_argument("--html", type=Path, default=ROOT / "index.html")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/scholar-stats.json")
    args = parser.parse_args()
    update_stats(args.cache, args.html, snapshot_path=args.snapshot)


if __name__ == "__main__":
    main()
