#!/usr/bin/env python3
"""Render Google Scholar summary and per-paper citations, retaining verified snapshots."""

import argparse
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

SCHOLAR_ID = "Kyio_RAAAAAJ"
SCHOLAR_URL = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
ROOT = Path(__file__).resolve().parents[1]
START = "<!-- scholar-stats:start -->"
END = "<!-- scholar-stats:end -->"
ARTICLE_ID = re.compile(r"[A-Za-z0-9_-]{6,64}")
COUNT = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)")
PAPER_BLOCK = re.compile(
    r"<!-- paper-citations:(?P<id>[A-Za-z0-9_-]+):start -->"
    r".*?<!-- paper-citations:(?P=id):end -->", re.DOTALL,
)
PAGE_SIZE = 100
MAX_PAGES = 10


class ScholarParser(HTMLParser):
    """Read the profile name and summary table, not a sum of paper citations."""

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


class ScholarPapersParser(HTMLParser):
    """Read only complete, identifiable article rows from the profile table."""

    def __init__(self):
        super().__init__()
        self.in_list = False
        self.list_closed = False
        self.row = None
        self.capture = None
        self.rows = []
        self.has_more = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "button" and attrs.get("id") == "gsc_bpf_more":
            self.has_more = "disabled" not in attrs
        if tag == "tbody" and attrs.get("id") == "gsc_a_b":
            self.in_list = True
        if not self.in_list:
            return
        if tag == "tr" and "gsc_a_tr" in classes:
            if self.row is not None:
                raise ValueError("Incomplete Scholar article row")
            self.row = {"title": [], "count": [], "citation_seen": False}
        if self.row is None:
            return
        if tag == "a" and "gsc_a_at" in classes:
            if "href" in self.row:
                raise ValueError("Duplicate Scholar article title")
            self.row["href"] = attrs.get("href", "")
            self.capture = "title"
        elif tag == "a" and "gsc_a_ac" in classes:
            if self.row["citation_seen"]:
                raise ValueError("Duplicate Scholar citation count")
            self.row["citation_seen"] = True
            self.row["citation_href"] = attrs.get("href", "")
            self.capture = "count"

    def handle_data(self, data):
        if self.row is not None and self.capture:
            self.row[self.capture].append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self.capture = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == "tbody" and self.in_list:
            self.in_list = False
            self.list_closed = True


class PaperVenueParser(HTMLParser):
    """Locate citation markers and venue boundaries without reserializing the page."""

    def __init__(self, page):
        super().__init__()
        self.offsets = [0]
        for line in page.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.rows = []
        self.locations = {}

    def source_offset(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append({"ids": [], "venues": [], "depth": 0})
        if not self.rows or tag != "div":
            return
        row = self.rows[-1]
        if row["depth"]:
            row["depth"] += 1
        elif "paper-venue" in dict(attrs).get("class", "").split():
            row["depth"] = 1
            row["venue_start"] = self.source_offset() + len(self.get_starttag_text())

    def handle_comment(self, data):
        match = re.fullmatch(r" paper-citations:([A-Za-z0-9_-]+):start ", data)
        if match and self.rows:
            self.rows[-1]["ids"].append(match[1])

    def handle_endtag(self, tag):
        if not self.rows:
            return
        row = self.rows[-1]
        if tag == "div" and row["depth"]:
            row["depth"] -= 1
            if row["depth"] == 0:
                row["venues"].append((row["venue_start"], self.source_offset()))
        elif tag == "tr":
            self.rows.pop()
            if row["ids"]:
                if len(row["ids"]) != 1 or len(row["venues"]) != 1:
                    raise ValueError("Each cited paper must have exactly one venue and citation marker")
                self.locations[row["ids"][0]] = row["venues"][0]


def position_paper_citations(page, blocks):
    """Keep citations after venue/honor labels, migrating old link-row placeholders."""
    parser = PaperVenueParser(page)
    parser.feed(page)
    edits = []
    for block in blocks:
        location = parser.locations.get(block["id"])
        if not location:
            continue
        venue_start, venue_end = location
        if venue_start <= block.start() < block.end() <= venue_end:
            continue
        start, end = block.span()
        line_start = page.rfind("\n", 0, start) + 1
        line_end = page.find("\n", end)
        if line_end >= 0 and not page[line_start:start].strip() and not page[end:line_end].strip():
            start, end = line_start, line_end + 1
        edits.append((start, end, ""))
        indent = page[page.rfind("\n", 0, venue_end) + 1:venue_end]
        insertion = ("  " + block.group() + "\n" + indent) if not indent.strip() else " " + block.group()
        edits.append((venue_end, venue_end, insertion))
    for start, end, replacement in sorted(edits, reverse=True):
        page = page[:start] + replacement + page[end:]
    return page


def timestamp_value(value):
    if not isinstance(value, str):
        raise ValueError("Missing update timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Update timestamp must include a timezone")
    return parsed


def validate_papers(papers):
    if not isinstance(papers, dict):
        raise ValueError("Invalid Scholar papers snapshot")
    for article_id, paper in papers.items():
        if not isinstance(article_id, str) or not ARTICLE_ID.fullmatch(article_id):
            raise ValueError("Invalid Scholar article ID")
        if not isinstance(paper, dict):
            raise ValueError("Invalid Scholar paper record")
        if not isinstance(paper.get("title"), str) or not paper["title"].strip():
            raise ValueError("Missing Scholar paper title")
        if type(paper.get("citations")) is not int or paper["citations"] < 0:
            raise ValueError("Invalid paper citation count")
        timestamp_value(paper.get("updated_at"))
    return papers


def validate_stats(stats):
    if not isinstance(stats, dict) or stats.get("scholar_id") != SCHOLAR_ID:
        raise ValueError("Scholar profile ID is missing or incorrect")
    for field in ("citations", "h_index"):
        value = stats.get(field)
        if type(value) is not int or value < 0:
            raise ValueError(f"Invalid {field}")
    if stats["h_index"] > stats["citations"]:
        raise ValueError("h-index exceeds citations")
    timestamp_value(stats.get("updated_at"))
    if "papers" in stats:
        validate_papers(stats["papers"])
    return stats


def verified_profile(page):
    parser = ScholarParser()
    parser.feed(page)
    if " ".join("".join(parser.name).split()) != "Hongjie Fang":
        raise ValueError("Expected Scholar profile not found (possibly a verification page)")
    return parser


def parse_scholar(page):
    parser = verified_profile(page)
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
        if not COUNT.fullmatch(value):
            raise ValueError(f"Invalid Scholar {label}: {value!r}")
        metrics[field] = int(value.replace(",", ""))
    return validate_stats({
        "scholar_id": SCHOLAR_ID,
        **metrics,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def parse_papers(page, updated_at):
    verified_profile(page)
    timestamp_value(updated_at)
    parser = ScholarPapersParser()
    parser.feed(page)
    if not parser.list_closed or parser.row is not None or not parser.rows:
        raise ValueError("Missing or incomplete Scholar publications table")
    if parser.has_more is None:
        raise ValueError("Scholar pagination control not found")
    papers = {}
    for row in parser.rows:
        url = urlsplit(urljoin(SCHOLAR_URL, row.get("href", "")))
        query = parse_qs(url.query)
        article = query.get("citation_for_view", [""])
        prefix = SCHOLAR_ID + ":"
        if (url.scheme != "https" or url.netloc != "scholar.google.com"
                or url.path != "/citations" or query.get("user") != [SCHOLAR_ID]
                or len(article) != 1 or not article[0].startswith(prefix)):
            raise ValueError("Scholar article does not belong to the expected profile")
        article_id = article[0][len(prefix):]
        if article_id in papers:
            raise ValueError("Duplicate Scholar article ID")
        if not row["citation_seen"]:
            raise ValueError("Missing Scholar citation cell; not treating it as zero")
        value = "".join(row["count"]).strip()
        if not value and not row["citation_href"]:
            # Scholar explicitly renders an empty, unlinked gsc_a_ac for zero citations.
            citations = 0
        elif COUNT.fullmatch(value):
            citations = int(value.replace(",", ""))
        else:
            raise ValueError(f"Invalid Scholar paper citations: {value!r}")
        papers[article_id] = {
            "title": " ".join("".join(row["title"]).split()),
            "citations": citations,
            "updated_at": updated_at,
        }
    return validate_papers(papers), parser.has_more


def fetch_profile_page(start=0):
    request = Request(f"{SCHOLAR_URL}&cstart={start}&pagesize={PAGE_SIZE}", headers={
        "User-Agent": "Mozilla/5.0 (compatible; PersonalWebsiteScholarStats/1.0)",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(request, timeout=20) as response:
        page = response.read(2_000_001)
    if len(page) > 2_000_000:
        raise ValueError("Unexpectedly large Scholar response")
    return page.decode("utf-8")


def fetch_papers(first_page, updated_at, fetch_page=fetch_profile_page):
    page = first_page
    papers = {}
    for page_number in range(MAX_PAGES):
        batch, has_more = parse_papers(page, updated_at)
        if papers.keys() & batch.keys():
            raise ValueError("Scholar pagination returned duplicate articles")
        papers.update(batch)
        if not has_more:
            return papers
        if page_number + 1 == MAX_PAGES:
            break
        page = fetch_page(len(papers))
    raise ValueError("Scholar pagination exceeded the safety limit")


def fetch_stats():
    page = fetch_profile_page()
    stats = parse_scholar(page)
    try:
        stats["papers"] = fetch_papers(page, stats["updated_at"], fetch_profile_page)
    except (OSError, ValueError) as error:
        # A valid summary can still refresh if the separate article table fails.
        print(f"::warning::Scholar paper refresh failed; retaining previous paper counts. {error}")
    return stats


def load_cached_stats(path):
    try:
        return validate_stats(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        print(f"Scholar cache unavailable: {error}")
        return None


def format_updated(value):
    return timestamp_value(value).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_stats(page, stats):
    validate_stats(stats)
    if page.count(START) != 1 or page.count(END) != 1 or page.index(START) > page.index(END):
        raise ValueError("Expected one Scholar metrics placeholder in the homepage")
    title = escape(f"Google Scholar · All-time metrics · Updated {format_updated(stats['updated_at'])}", quote=True)
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


def render_paper_citations(page, papers):
    validate_papers(papers)
    blocks = list(PAPER_BLOCK.finditer(page))
    if page.count("<!-- paper-citations:") != 2 * len(blocks):
        raise ValueError("Malformed paper citation placeholders")
    ids = [block["id"] for block in blocks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate paper citation placeholders")
    page = position_paper_citations(page, blocks)

    def replace(match):
        article_id = match["id"]
        if not ARTICLE_ID.fullmatch(article_id):
            raise ValueError("Invalid Scholar article placeholder")
        url = "https://scholar.google.com/citations?" + urlencode({
            "view_op": "view_citation", "hl": "en", "user": SCHOLAR_ID,
            "citation_for_view": f"{SCHOLAR_ID}:{article_id}",
        })
        paper = papers.get(article_id)
        if paper is None:
            text = "—"
            label = "Citations unavailable"
            title = "Google Scholar · Citation count not available yet"
            print(f"::warning::No verified citations for Scholar article {article_id}; displaying unavailable.")
        else:
            count = paper["citations"]
            text = f"{count:,}"
            label = f"{text} {'citation' if count == 1 else 'citations'}"
            title = f"Google Scholar · Updated {format_updated(paper['updated_at'])}"
        link = (f'<a class="paper-citations" data-scholar-id="{article_id}" '
                f'href="{escape(url, quote=True)}" title="{escape(title, quote=True)}" '
                f'aria-label="{escape(label + ". " + title, quote=True)}">{text}</a>')
        return (f"<!-- paper-citations:{article_id}:start -->{link}"
                f"<!-- paper-citations:{article_id}:end -->")

    return PAPER_BLOCK.sub(replace, page)


def merge_snapshots(snapshots):
    if not snapshots:
        return None
    summary = max(snapshots, key=lambda item: timestamp_value(item["updated_at"]))
    result = dict(summary)
    papers = {}
    for snapshot in snapshots:
        for article_id, paper in snapshot.get("papers", {}).items():
            if (article_id not in papers
                    or timestamp_value(paper["updated_at"]) > timestamp_value(papers[article_id]["updated_at"])):
                papers[article_id] = paper
    if papers:
        result["papers"] = papers
    return validate_stats(result)


def save_stats(path, stats):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def update_stats(cache_path, html_path, fetcher=fetch_stats, snapshot_path=None):
    page = html_path.read_text(encoding="utf-8")
    paths = [cache_path] + ([snapshot_path] if snapshot_path else [])
    snapshots = [stats for path in paths if (stats := load_cached_stats(path)) is not None]
    fresh = False
    if fetcher is not None:
        try:
            snapshots.append(validate_stats(fetcher()))
            fresh = True
        except (OSError, ValueError) as error:
            print(f"::warning::Google Scholar refresh failed; retaining cached metrics. {error}")
    stats = merge_snapshots(snapshots)
    if stats is None:
        print("No verified metrics available; leaving the existing homepage unchanged.")
        return False
    rendered = render_paper_citations(render_stats(page, stats), stats.get("papers", {}))
    save_stats(cache_path, stats)
    if snapshot_path:
        save_stats(snapshot_path, stats)
    html_path.write_text(rendered, encoding="utf-8")
    print(f"Rendered {stats['citations']:,} citations · h-index {stats['h_index']} "
          f"({'fresh' if fresh else 'cached'}, {stats['updated_at']}); "
          f"{len(stats.get('papers', {}))} verified paper counts retained.")
    return fresh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/scholar-stats.json")
    parser.add_argument("--html", type=Path, default=ROOT / "index.html")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/scholar-stats.json")
    parser.add_argument("--cached-only", action="store_true", help="Render saved data without a network request")
    args = parser.parse_args()
    update_stats(args.cache, args.html, fetcher=None if args.cached_only else fetch_stats,
                 snapshot_path=args.snapshot)


if __name__ == "__main__":
    main()
