"""Offline GitHub-star tests. All repository names and counts are synthetic."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from update_github_stars import (
    END, START, GitHubRedirectHandler, fetch_repository, find_paper_links,
    merge_snapshots, parse_repository, render_stars, repository_from_url,
    update_stars, validate_snapshot,
)

STAMP = "2026-01-01T01:02:03+00:00"
NEW_STAMP = "2026-02-01T00:00:00+00:00"


def record(stars=1234, updated_at=STAMP, full_name="Owner/Repo"):
    return {"full_name": full_name, "stars": stars, "updated_at": updated_at}


def snapshot(repositories=None):
    return {"version": 1, "repositories": {"owner/repo": record()} if repositories is None else repositories}


def page(links='<a class="paper-link-code" href="https://github.com/Owner/Repo">code </a>'):
    return ('<a href="https://github.com/Profile">Profile</a>'
            '<table id="section-publications"><tbody><tr><td>'
            '<div class="paper-authors"><a href="https://github.com/Author/Other">Author</a></div>'
            '<div class="paper-venue"><a class="paper-citations">123</a></div>'
            '<div class="paper-links">' + links + '</div></td></tr></tbody></table>'
            '<!-- <div class="paper-links"><a href="https://github.com/Hidden/Project">project</a></div> -->')


def payload(stars=1234, full_name="Owner/Repo"):
    return {"id": 42, "private": False, "full_name": full_name,
            "stargazers_count": stars, "html_url": "https://github.com/" + full_name}


class RepositoryDiscoveryTests(unittest.TestCase):
    def test_url_normalization(self):
        for url in ('https://github.com/Owner/Repo', 'http://github.com/OWNER/REPO/',
                    'https://www.github.com/Owner/Repo.git?x=1#readme',
                    'https://github.com/Owner/Repo/tree/main'):
            with self.subTest(url=url):
                self.assertEqual(repository_from_url(url), "owner/repo")

    def test_profile_non_repository_and_unsafe_urls_are_ignored(self):
        for url in ('https://github.com/Author', 'https://owner.github.io/repo',
                    'https://github.com.evil.test/Owner/Repo', 'https://github.com@evil.test/Owner/Repo',
                    'https://github.com/orgs/Owner', 'https://github.com/Owner/..',
                    'javascript:alert(1)', 'https://github.com/Owner/%22bad', None, 123):
            with self.subTest(url=url):
                self.assertIsNone(repository_from_url(url))

    def test_only_publication_resource_links_are_discovered(self):
        links = find_paper_links(page())
        self.assertEqual([link["repo"] for link in links], ["owner/repo"])
        self.assertEqual(page()[links[0]["start"]:links[0]["end"]], "code ")

    def test_multiple_repositories_keep_distinct_links(self):
        html = page('<a href="https://github.com/Owner/First">data collection code</a>'
                    '<a href="https://github.com/Owner/Second/">policy code</a>')
        self.assertEqual([link["repo"] for link in find_paper_links(html)], ["owner/first", "owner/second"])

    def test_missing_or_incomplete_publications_is_rejected(self):
        for html in ('<main></main>', page().replace('</table>', ''),
                     '<div id="section-publications"><div class="paper-links"><a href="https://github.com/Owner/Repo">'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                find_paper_links(html)

    def test_malformed_and_duplicate_generated_blocks_fail(self):
        for content in (START, END + START, START + END + START + END):
            with self.subTest(content=content), self.assertRaises(ValueError):
                find_paper_links(page(f'<a href="https://github.com/Owner/Repo">code{content}</a>'))


class GitHubApiTests(unittest.TestCase):
    def test_public_repository_counts_include_zero(self):
        for stars in (0, 1, 1234):
            self.assertEqual(parse_repository(payload(stars), 'owner/repo',
                'https://api.github.com/repos/owner/repo', STAMP), record(stars))

    def test_malformed_counts_and_private_repositories_are_rejected(self):
        for patch_data in ({'stargazers_count': True}, {'stargazers_count': -1},
                           {'stargazers_count': '123'}, {'private': True}, {'private': None},
                           {'id': None}, {'html_url': 'https://example.com/Owner/Repo'}):
            with self.subTest(patch_data=patch_data), self.assertRaises(ValueError):
                parse_repository({**payload(), **patch_data}, 'owner/repo',
                    'https://api.github.com/repos/owner/repo', STAMP)

    def test_wrong_repository_and_foreign_response_host_are_rejected(self):
        for response in ('https://api.github.com/repos/other/repo',
                         'http://api.github.com/repos/owner/repo',
                         'https://evil.test/repos/owner/repo', 'https://api.github.com/repositories/999'):
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_repository(payload(), 'owner/repo', response, STAMP)

    def test_canonical_redirect_after_repository_rename_is_supported(self):
        for url in ('https://api.github.com/repositories/42', 'https://api.github.com/repos/new/name'):
            self.assertEqual(parse_repository(payload(full_name='New/Name'), 'old/name', url, STAMP),
                             record(full_name='New/Name'))
        with self.assertRaises(ValueError):
            parse_repository(payload(full_name='New/Name'), 'old/name',
                             'https://api.github.com/repos/old/name', STAMP)

    def test_authorization_is_only_forwarded_to_same_https_api_host(self):
        request = Request('https://api.github.com/repos/owner/repo', headers={'Authorization': 'Bearer TEST_TOKEN'})
        handler = GitHubRedirectHandler()
        safe = handler.redirect_request(request, None, 301, 'Moved', {}, 'https://api.github.com/repositories/42')
        self.assertEqual(safe.get_header('Authorization'), 'Bearer TEST_TOKEN')
        for url in ('https://evil.test/42', 'http://api.github.com/repositories/42',
                    'https://api.github.com@evil.test/repositories/42'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 301, 'Moved', {}, url)

    def test_fetch_uses_github_token_and_public_metadata_api(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return json.dumps(payload()).encode()
            def geturl(self): return 'https://api.github.com/repos/owner/repo'
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'TEST_TOKEN'}):
            with patch('update_github_stars.build_opener') as build:
                build.return_value.open.return_value = Response()
                result = fetch_repository('owner/repo')
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/owner/repo')
        self.assertEqual(request.get_header('Authorization'), 'Bearer TEST_TOKEN')
        self.assertEqual(result['stars'], 1234)


class GitHubSnapshotRenderingTests(unittest.TestCase):
    def test_invalid_snapshots_fail(self):
        for value in ([], {'version': True, 'repositories': {}}, snapshot({'Owner/Repo': record()}),
                      snapshot({'owner/repo': record(True)}), snapshot({'owner/repo': record(-1)}),
                      snapshot({'owner/repo': record(updated_at='2026-01-01')})):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_snapshot(value)

    def test_merge_uses_per_repo_timestamp_and_allows_revised_lower_counts(self):
        old = snapshot({'owner/repo': record(), 'other/repo': record(3, full_name='Other/Repo')})
        fresh = snapshot({'owner/repo': record(1000, NEW_STAMP)})
        merged = merge_snapshots([old, fresh])
        self.assertEqual(merged['repositories']['owner/repo'], record(1000, NEW_STAMP))
        self.assertEqual(merged['repositories']['other/repo']['updated_at'], STAMP)
        self.assertEqual(old['repositories']['owner/repo']['stars'], 1234)

    def test_render_preserves_anchor_label_attributes_and_surrounding_content(self):
        html = page('<a class="paper-link-code" href="https://github.com/Owner/Repo" title="Keep me">code </a>')
        result = render_stars(html, snapshot())
        self.assertIn('title="Keep me">code ' + START, result)
        self.assertIn('>1,234</span>', result)
        self.assertIn('GitHub · Owner/Repo · Updated 2026-01-01 01:02 UTC', result)
        self.assertIn('<span class="github-stars-label"> GitHub stars</span>', result)
        self.assertEqual(result.count('data-github-repo='), 1)
        self.assertEqual(render_stars(result, snapshot()), result)
        generated_start, rest = result.split(START)
        _, generated_end = rest.split(END)
        self.assertEqual(generated_start + generated_end, html)

    def test_zero_and_unknown_are_distinct(self):
        self.assertIn('>0</span>', render_stars(page(), snapshot({'owner/repo': record(0)})))
        unknown = render_stars(page(), snapshot({}))
        self.assertIn('>—</span>', unknown)
        self.assertIn('GitHub stars unavailable', unknown)
        self.assertNotIn('>0</span>', unknown)
        self.assertNotIn('Updated', unknown)

    def test_changed_href_never_keeps_previous_repository_count(self):
        rendered = render_stars(page(), snapshot())
        changed = rendered.replace('href="https://github.com/Owner/Repo"', 'href="https://github.com/New/Repo"')
        result = render_stars(changed, snapshot())
        self.assertIn('data-github-repo="new/repo"', result)
        self.assertNotIn('1,234', result)
        removed = rendered.replace('href="https://github.com/Owner/Repo"', 'href="https://example.com/code"')
        self.assertNotIn('github-stars', render_stars(removed, snapshot()))

    def test_update_fetches_each_unique_repo_once_and_persists_both_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            html, cache, saved = root / 'index.html', root / 'cache.json', root / 'snapshot.json'
            html.write_text(page('<a href="https://github.com/Owner/Repo">code</a>'
                                 '<a href="http://github.com/OWNER/REPO.git">SDK</a>'))
            calls = []
            def fetch(repo):
                calls.append(repo)
                return record()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(update_stars(cache, html, fetch, saved), 1)
            self.assertEqual(calls, ['owner/repo'])
            self.assertEqual(json.loads(cache.read_text()), snapshot())
            self.assertEqual(json.loads(saved.read_text()), snapshot())
            self.assertEqual(html.read_text().count('data-github-repo='), 2)

    def test_partial_failure_and_cache_eviction_preserve_original_date(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            html, cache, saved = root / 'index.html', root / 'missing/cache.json', root / 'snapshot.json'
            html.write_text(page('<a href="https://github.com/Owner/Repo">code</a>'
                                 '<a href="https://github.com/Other/Repo">policy code</a>'))
            saved.write_text(json.dumps(snapshot()))
            def fetch(repo):
                if repo == 'owner/repo': raise URLError('Unavailable')
                return record(4, NEW_STAMP, 'Other/Repo')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(update_stars(cache, html, fetch, saved), 1)
            repositories = json.loads(saved.read_text())['repositories']
            self.assertEqual(repositories['owner/repo'], record())
            self.assertEqual(repositories['other/repo'], record(4, NEW_STAMP, 'Other/Repo'))

    def test_rate_limit_stops_requests_and_does_not_invent_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            html, cache = root / 'index.html', root / 'cache.json'
            html.write_text(page('<a href="https://github.com/Owner/Repo">code</a>'
                                 '<a href="https://github.com/Other/Repo">policy code</a>'))
            calls = []
            def fetch(repo):
                calls.append(repo)
                raise HTTPError('https://api.github.com', 403, 'Rate limited', {}, None)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(update_stars(cache, html, fetch), 0)
            self.assertEqual(calls, ['owner/repo'])
            self.assertEqual(html.read_text().count('>—</span>'), 2)
            self.assertEqual(json.loads(cache.read_text()), snapshot({}))

    def test_cached_only_mode_does_not_change_update_date(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            html, cache = root / 'index.html', root / 'cache.json'
            html.write_text(page())
            cache.write_text(json.dumps(snapshot()))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(update_stars(cache, html, fetcher=None), 0)
            self.assertIn('2026-01-01 01:02 UTC', html.read_text())


if __name__ == '__main__':
    unittest.main()
