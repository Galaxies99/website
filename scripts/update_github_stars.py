#!/usr/bin/env python3
"""Refresh GitHub stars for publication repository links at build time."""

import argparse
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- github-stars:start -->"
END = "<!-- github-stars:end -->"
BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def repository_from_url(url):
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or parts[0].lower() in {"orgs", "users", "settings", "topics", "collections", "sponsors", "features", "marketplace"}:
        return None
    repo = parts[1][:-4] if parts[1].lower().endswith(".git") else parts[1]
    name = f"{parts[0]}/{repo}"
    if repo in (".", "..") or not REPOSITORY.fullmatch(name):
        return None
    return name.lower()


def strip_generated_stars(content):
    matches = list(BLOCK.finditer(content))
    if (content.count(START) != len(matches) or content.count(END) != len(matches)
            or len(matches) > 1):
        raise ValueError("Malformed or duplicate GitHub star block inside a paper link")
    return BLOCK.sub("", content)


class PaperRepositoryParser(HTMLParser):
    """Find link contents by source offsets, ignoring authors and commented HTML."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.offsets = [0]
        for line in page.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack = []
        self.current = None
        self.links = []
        self.found_publications = False

    def source_offset(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        in_publications = bool(self.stack and self.stack[-1][1])
        in_links = bool(self.stack and self.stack[-1][2])
        if attrs.get("id") == "section-publications":
            in_publications = self.found_publications = True
        if in_publications and "paper-links" in attrs.get("class", "").split():
            in_links = True
        if tag not in VOID_TAGS:
            self.stack.append((tag, in_publications, in_links))
        if tag == "a" and in_publications and in_links:
            if self.current is not None:
                raise ValueError("Nested publication links are invalid")
            self.current = {
                "repo": repository_from_url(attrs.get("href", "")),
                "start": self.source_offset() + len(self.get_starttag_text()),
            }

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.current["end"] = self.source_offset()
            strip_generated_stars(self.page[self.current["start"]:self.current["end"]])
            self.links.append(self.current)
            self.current = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def find_paper_links(page):
    parser = PaperRepositoryParser(page)
    parser.feed(page)
    if not parser.found_publications or parser.current is not None or any(item[1] for item in parser.stack):
        raise ValueError("Missing or incomplete publications section")
    return parser.links


def parse_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing GitHub update timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("GitHub update timestamp needs a timezone")
    return parsed


def validate_record(record):
    if not isinstance(record, dict) or not isinstance(record.get("full_name"), str):
        raise ValueError("Invalid GitHub repository record")
    if not REPOSITORY.fullmatch(record["full_name"]):
        raise ValueError("Invalid GitHub repository name")
    if type(record.get("stars")) is not int or record["stars"] < 0:
        raise ValueError("Invalid GitHub star count")
    parse_timestamp(record.get("updated_at"))
    return record


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or type(snapshot.get("version")) is not int or snapshot["version"] != 1:
        raise ValueError("Unsupported GitHub star snapshot")
    repositories = snapshot.get("repositories")
    if not isinstance(repositories, dict):
        raise ValueError("Missing GitHub repository records")
    for repo, record in repositories.items():
        if not isinstance(repo, str) or not REPOSITORY.fullmatch(repo) or repo != repo.lower():
            raise ValueError("Invalid normalized GitHub repository key")
        validate_record(record)
    return snapshot


class GitHubRedirectHandler(HTTPRedirectHandler):
    """Allow renamed-repository redirects, but never forward a token off api.github.com."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.netloc != "api.github.com":
            raise ValueError("Refusing a GitHub API redirect to another host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_repository(payload, requested_repo, response_url, updated_at):
    if not isinstance(payload, dict) or payload.get("private") is not False:
        raise ValueError("Expected public GitHub repository metadata")
    record = {
        "full_name": payload.get("full_name"),
        "stars": payload.get("stargazers_count"),
        "updated_at": updated_at,
    }
    validate_record(record)
    repository_id = payload.get("id")
    if type(repository_id) is not int or repository_id <= 0:
        raise ValueError("Missing GitHub repository ID")
    target = urlsplit(response_url)
    if target.scheme != "https" or target.netloc != "api.github.com":
        raise ValueError("Unexpected GitHub API response URL")
    canonical = record["full_name"].lower()
    allowed_paths = {f"/repos/{canonical}", f"/repositories/{repository_id}"}
    if target.path.lower() not in allowed_paths:
        raise ValueError("GitHub response belongs to a different repository")
    if repository_from_url(payload.get("html_url", "")) != canonical:
        raise ValueError("GitHub repository URL does not match its identity")
    # Renamed repositories return /repositories/ID or the canonical /repos/owner/name.
    if canonical != requested_repo and target.path.lower() == f"/repos/{requested_repo}":
        raise ValueError("Mismatched GitHub repository without a canonical redirect")
    return record


def fetch_repository(repo):
    if not REPOSITORY.fullmatch(repo) or repo != repo.lower():
        raise ValueError("Invalid GitHub repository request")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "PersonalWebsiteGitHubStars/1.0"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"https://api.github.com/repos/{repo}", headers=headers)
    with build_opener(GitHubRedirectHandler()).open(request, timeout=20) as response:
        raw = response.read(1_000_001)
        final_url = response.geturl()
    if len(raw) > 1_000_000:
        raise ValueError("Unexpectedly large GitHub response")
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return parse_repository(json.loads(raw.decode("utf-8")), repo, final_url, updated_at)


def load_snapshot(path):
    try:
        return validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        print(f"GitHub star cache unavailable: {error}")
        return None


def merge_snapshots(snapshots):
    repositories = {}
    for snapshot in snapshots:
        for repo, record in validate_snapshot(snapshot)["repositories"].items():
            if repo not in repositories or parse_timestamp(record["updated_at"]) > parse_timestamp(repositories[repo]["updated_at"]):
                repositories[repo] = record
    return {"version": 1, "repositories": repositories}


def render_stars(page, snapshot, links=None):
    repositories = validate_snapshot(snapshot)["repositories"]
    links = find_paper_links(page) if links is None else links
    for link in reversed(links):
        content = strip_generated_stars(page[link["start"]:link["end"]])
        repo = link["repo"]
        if repo:
            record = repositories.get(repo)
            if record:
                count = f"{record['stars']:,}"
                updated = parse_timestamp(record["updated_at"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                title = f"GitHub · {record['full_name']} · Updated {updated}"
                label = " GitHub stars"
            else:
                count = "—"
                title = f"GitHub · {repo} · Star count not available yet"
                label = " GitHub stars unavailable"
            content += (f'{START}<span class="github-stars" data-github-repo="{repo}" '
                        f'title="{escape(title, quote=True)}"><span aria-hidden="true">★</span> '
                        f'<span class="github-stars-count">{count}</span>'
                        f'<span class="github-stars-label">{label}</span></span>{END}')
        page = page[:link["start"]] + content + page[link["end"]:]
    return page


def save_snapshot(path, snapshot):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def update_stars(cache_path, html_path, fetcher=fetch_repository, snapshot_path=None):
    page = html_path.read_text(encoding="utf-8")
    links = find_paper_links(page)
    repos = list(dict.fromkeys(link["repo"] for link in links if link["repo"]))
    paths = [cache_path] + ([snapshot_path] if snapshot_path else [])
    snapshots = [snapshot for path in paths if (snapshot := load_snapshot(path)) is not None]
    snapshot = merge_snapshots(snapshots)
    fresh = 0
    if fetcher is not None:
        for repo in repos:
            try:
                record = validate_record(fetcher(repo))
                snapshot = merge_snapshots([snapshot, {"version": 1, "repositories": {repo: record}}])
                fresh += 1
            except (OSError, ValueError) as error:
                print(f"::warning::GitHub stars unavailable for {repo}; retaining its previous count. {error}")
                if isinstance(error, HTTPError) and error.code in (401, 403, 429):
                    print("::warning::GitHub authentication/rate limit reached; remaining repositories use cached counts.")
                    break
    rendered = render_stars(page, snapshot, links)
    save_snapshot(cache_path, snapshot)
    if snapshot_path:
        save_snapshot(snapshot_path, snapshot)
    html_path.write_text(rendered, encoding="utf-8")
    available = sum(repo in snapshot["repositories"] for repo in repos)
    print(f"Rendered stars for {len(repos)} unique paper repositories: {fresh} refreshed, "
          f"{available} verified, {len(repos) - available} unavailable.")
    return fresh


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/github-stars.json")
    parser.add_argument("--html", type=Path, default=ROOT / "index.html")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/github-stars.json")
    parser.add_argument("--cached-only", action="store_true", help="Render saved data without API requests")
    args = parser.parse_args()
    update_stars(args.cache, args.html, fetcher=None if args.cached_only else fetch_repository,
                 snapshot_path=args.snapshot)


if __name__ == "__main__":
    main()
