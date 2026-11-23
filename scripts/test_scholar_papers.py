"""Offline per-paper citation tests; all counts and article IDs are synthetic."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from test_scholar_stats import HTML, PAGE, SNAPSHOT
from update_scholar_stats import (
    SCHOLAR_ID, fetch_papers, fetch_stats, merge_snapshots, parse_papers,
    render_paper_citations, update_stats, validate_stats,
)

STAMP = SNAPSHOT["updated_at"]
NEW_STAMP = "2026-02-01T00:00:00+00:00"
ID = "paper0000001"
OTHER_ID = "paper0000002"


def article(article_id=ID, count="1,234", title="A Test Paper", cited=True):
    href = ' href="/scholar?cites=123456"' if cited else ""
    return f'''<tr class="gsc_a_tr"><td class="gsc_a_t">
      <a class="gsc_a_at" href="/citations?view_op=view_citation&amp;user={SCHOLAR_ID}&amp;citation_for_view={SCHOLAR_ID}:{article_id}">{title}</a>
      <div class="gs_gray">A Author, B Author</div><div class="gs_gray">Conference 2026</div>
      </td><td class="gsc_a_c"><a class="gsc_a_ac gs_ibl"{href}>{count}</a><span>*</span></td>
      <td class="gsc_a_y"><span>2026</span></td></tr>'''


def profile(rows=None, more=False):
    rows = article() if rows is None else rows
    disabled = "" if more else ' disabled=""'
    return PAGE + f'<table id="gsc_a_t"><tbody id="gsc_a_b">{rows}</tbody></table><button id="gsc_bpf_more"{disabled}>Show more</button>'


def paper(count=1234, updated_at=STAMP, title="A Test Paper"):
    return {"title": title, "citations": count, "updated_at": updated_at}


def snapshot(papers=None, **kwargs):
    return {**SNAPSHOT, "papers": {ID: paper()} if papers is None else papers, **kwargs}


def block(article_id=ID, contents=""):
    return f"<!-- paper-citations:{article_id}:start -->{contents}<!-- paper-citations:{article_id}:end -->"


class PaperParsingTests(unittest.TestCase):
    def test_counts_are_from_article_anchors_not_years_authors_or_summary(self):
        result, more = parse_papers(profile(), STAMP)
        self.assertEqual(result, {ID: paper()})
        self.assertFalse(more)

    def test_zero_and_scholars_explicit_empty_unlinked_count_are_valid(self):
        for value in ("0", ""):
            with self.subTest(value=value):
                result, _ = parse_papers(profile(article(count=value, cited=False)), STAMP)
                self.assertEqual(result[ID]["citations"], 0)

    def test_missing_cell_or_linked_empty_count_is_not_zero(self):
        pages = [profile(article(count="")),
                 profile().replace('class="gsc_a_ac gs_ibl"', 'class="unknown"')]
        for page in pages:
            with self.subTest(page=page), self.assertRaises(ValueError):
                parse_papers(page, STAMP)

    def test_malformed_counts_are_rejected(self):
        for value in ("—", "-1", "1,23", "12x", "1.2k", "1 234"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_papers(profile(article(count=value)), STAMP)

    def test_titles_decode_entities_and_nested_markup(self):
        result, _ = parse_papers(profile(article(title="A &amp; B: <b>New</b> Title")), STAMP)
        self.assertEqual(result[ID]["title"], "A & B: New Title")

    def test_wrong_profile_verification_page_and_article_ownership_are_rejected(self):
        pages = ["<html>Verify you are human</html>",
                 profile().replace("Hongjie Fang", "Another Author"),
                 profile().replace(f"user={SCHOLAR_ID}", "user=SomeoneElse"),
                 profile().replace(f"citation_for_view={SCHOLAR_ID}:", "citation_for_view=Other:"),
                 profile().replace('href="/citations?', 'href="https://example.com/citations?')]
        for page in pages:
            with self.subTest(page=page), self.assertRaises(ValueError):
                parse_papers(page, STAMP)

    def test_changed_empty_and_incomplete_table_is_rejected(self):
        pages = [PAGE, profile(""), profile().replace("gsc_a_b", "changed"),
                 profile().replace("</tbody></table><button", "</table><button"),
                 profile().replace("</td></tr></tbody>", "</td></tbody>"),
                 profile().replace("gsc_bpf_more", "changed")]
        for page in pages:
            with self.subTest(page=page), self.assertRaises(ValueError):
                parse_papers(page, STAMP)

    def test_invalid_or_duplicate_article_ids_are_rejected(self):
        for rows in (article("bad!"), article() + article(), article(title="")):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_papers(profile(rows), STAMP)

    def test_pagination_fetches_remaining_rows_not_each_article(self):
        calls = []

        def next_page(start):
            calls.append(start)
            return profile(article(OTHER_ID, "7"))

        papers = fetch_papers(profile(more=True), STAMP, next_page)
        self.assertEqual(calls, [1])
        self.assertEqual(papers[ID]["citations"], 1234)
        self.assertEqual(papers[OTHER_ID]["citations"], 7)

    def test_complete_profile_needs_no_extra_request(self):
        def unexpected_request(start):
            self.fail(f"Unexpected pagination request: {start}")
        self.assertEqual(len(fetch_papers(profile(), STAMP, unexpected_request)), 1)

    def test_repeated_pagination_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            fetch_papers(profile(more=True), STAMP, lambda start: profile())

    def test_pagination_failure_does_not_return_partial_counts(self):
        def unavailable(start):
            raise URLError("Temporarily unavailable")
        with self.assertRaises(URLError):
            fetch_papers(profile(more=True), STAMP, unavailable)

    def test_pagination_limit_does_not_make_an_extra_request(self):
        with patch("update_scholar_stats.MAX_PAGES", 1):
            with patch("update_scholar_stats.fetch_profile_page") as fetch:
                with self.assertRaisesRegex(ValueError, "safety limit"):
                    fetch_papers(profile(more=True), STAMP, fetch)
                fetch.assert_not_called()

    def test_fetch_shares_first_page_between_summary_and_papers(self):
        with patch("update_scholar_stats.fetch_profile_page", return_value=profile()) as fetch:
            result = fetch_stats()
        fetch.assert_called_once_with()
        self.assertEqual(result["papers"][ID]["citations"], 1234)
        self.assertEqual(result["updated_at"], result["papers"][ID]["updated_at"])

    def test_summary_refresh_does_not_publish_partial_pagination(self):
        with patch("update_scholar_stats.fetch_profile_page", side_effect=[
            profile(more=True), URLError("Second page unavailable"),
        ]) as fetch:
            with contextlib.redirect_stdout(io.StringIO()):
                result = fetch_stats()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["citations"], 1234)
        self.assertNotIn("papers", result)

    def test_valid_summary_survives_article_markup_failure(self):
        with patch("update_scholar_stats.fetch_profile_page", return_value=PAGE):
            with contextlib.redirect_stdout(io.StringIO()):
                result = fetch_stats()
        self.assertEqual(result["citations"], 1234)
        self.assertNotIn("papers", result)


class PaperSnapshotTests(unittest.TestCase):
    def test_legacy_summary_snapshot_remains_valid(self):
        self.assertEqual(validate_stats(SNAPSHOT.copy()), SNAPSHOT)

    def test_invalid_paper_snapshots_are_rejected(self):
        bad_records = [None, {}, paper(True), paper(-1), paper("123"),
                       paper(updated_at="2026-01-01"), paper(title="")]
        for record in bad_records:
            with self.subTest(record=record), self.assertRaises(ValueError):
                validate_stats(snapshot({ID: record}))
        for papers in ([], {"bad!": paper()}):
            with self.subTest(papers=papers), self.assertRaises(ValueError):
                validate_stats(snapshot(papers))

    def test_merge_preserves_missing_papers_and_each_success_timestamp(self):
        old = snapshot({ID: paper(), OTHER_ID: paper(10)})
        fresh = snapshot({ID: paper(1200, NEW_STAMP)}, citations=1400, updated_at=NEW_STAMP)
        result = merge_snapshots([old, fresh])
        self.assertEqual(result["citations"], 1400)
        # A genuine downward revision is allowed; never take max(count).
        self.assertEqual(result["papers"][ID], paper(1200, NEW_STAMP))
        self.assertEqual(result["papers"][OTHER_ID], paper(10))
        self.assertEqual(old["papers"][ID]["citations"], 1234)

    def test_newest_per_paper_record_can_come_from_older_summary(self):
        older_summary = snapshot({ID: paper(1500, NEW_STAMP)})
        newer_summary = snapshot(updated_at=NEW_STAMP)
        result = merge_snapshots([older_summary, newer_summary])
        self.assertEqual(result["papers"][ID]["citations"], 1500)

    def test_success_persists_and_renders_all_snapshot_destinations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            homepage, cache, saved = root / "index.html", root / "cache.json", root / "snapshot.json"
            homepage.write_text(HTML + block(), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                fresh = update_stats(cache, homepage, lambda: snapshot(), saved)
            self.assertTrue(fresh)
            self.assertEqual(json.loads(saved.read_text()), snapshot())
            self.assertEqual(json.loads(cache.read_text()), snapshot())
            self.assertIn('class="paper-citations"', homepage.read_text())

    def test_failure_preserves_counts_and_timestamps_after_cache_eviction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            homepage, cache, saved = root / "index.html", root / "cache.json", root / "snapshot.json"
            homepage.write_text(HTML + block(), encoding="utf-8")
            saved.write_text(json.dumps(snapshot()), encoding="utf-8")

            def unavailable():
                raise URLError("Blocked")

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(update_stats(cache, homepage, unavailable, saved))
            self.assertEqual(json.loads(cache.read_text())["papers"], snapshot()["papers"])
            self.assertIn("2026-01-02 03:04 UTC", homepage.read_text())
            self.assertIn("1,234 citations", homepage.read_text())

    def test_summary_only_refresh_keeps_last_known_paper_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            homepage, cache = root / "index.html", root / "cache.json"
            homepage.write_text(HTML + block(), encoding="utf-8")
            cache.write_text(json.dumps(snapshot()), encoding="utf-8")
            fresh = {**SNAPSHOT, "updated_at": NEW_STAMP, "citations": 1400}
            with contextlib.redirect_stdout(io.StringIO()):
                update_stats(cache, homepage, lambda: fresh)
            result = json.loads(cache.read_text())
            self.assertEqual(result["updated_at"], NEW_STAMP)
            self.assertEqual(result["papers"][ID]["updated_at"], STAMP)

    def test_bad_placeholders_do_not_overwrite_cache_or_html(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            homepage, cache = root / "index.html", root / "cache.json"
            original = HTML + block() + block()
            homepage.write_text(original, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                update_stats(cache, homepage, lambda: snapshot())
            self.assertFalse(cache.exists())
            self.assertEqual(homepage.read_text(), original)


class PaperRenderingTests(unittest.TestCase):
    def test_render_is_idempotent_and_does_not_modify_surrounding_content(self):
        original = "Before <a>paper</a> " + block() + " After"
        result = render_paper_citations(original, {ID: paper()})
        self.assertTrue(result.startswith("Before <a>paper</a> "))
        self.assertTrue(result.endswith(" After"))
        self.assertIn("1,234 citations", result)
        self.assertIn(f"{SCHOLAR_ID}%3A{ID}", result)
        self.assertIn("&amp;", result)
        self.assertEqual(render_paper_citations(result, {ID: paper()}), result)

    def test_renamed_paper_still_matches_fixed_id_not_title(self):
        result = render_paper_citations("<papertitle>New Title</papertitle>" + block(), {
            ID: paper(title="Old Title"),
        })
        self.assertIn("1,234 citations", result)
        self.assertIn("<papertitle>New Title</papertitle>", result)
        self.assertNotIn("Old Title", result)

    def test_zero_one_and_many_counts_render_correctly(self):
        for count, text in ((0, "0 citations"), (1, "1 citation"), (1234, "1,234 citations")):
            with self.subTest(count=count):
                result = render_paper_citations(block(), {ID: paper(count)})
                self.assertIn(f'>{count:,}</a>', result)
                self.assertIn(f'aria-label="{text}. Google Scholar', result)

    def test_unknown_paper_is_unavailable_not_zero(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = render_paper_citations(block(), {})
        self.assertIn('>—</a>', result)
        self.assertIn('Citations unavailable', result)
        self.assertNotIn("0 citations", result)
        self.assertNotIn("Updated", result)

    def test_malformed_duplicate_or_reversed_markers_fail(self):
        for value in (block() + block(), block().replace(":end", ":oops"),
                      block().replace(f"{ID}:end", f"{OTHER_ID}:end"),
                      f"<!-- paper-citations:{ID}:end --><!-- paper-citations:{ID}:start -->"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                render_paper_citations(value, {})

    def test_old_link_row_badge_moves_after_venue_honors_only_once(self):
        original = ('<table><tr><td><div class="paper-venue"><em>ICRA 2024</em>'
                    '<span class="paper-honor">Best Paper</span></div>'
                    '<papertitle>Keep this title</papertitle><div class="paper-links">'
                    '<a href="https://example.com">paper</a>' + block() + '</div></td></tr></table>')
        result = render_paper_citations(original, {ID: paper()})
        venue, links = result.split('<div class="paper-links">')
        self.assertIn('data-scholar-id', venue)
        self.assertGreater(venue.index('data-scholar-id'), venue.index('Best Paper'))
        self.assertNotIn('paper-citations', links)
        self.assertIn('<papertitle>Keep this title</papertitle>', result)
        self.assertEqual(render_paper_citations(result, {ID: paper()}), result)

    def test_migration_preserves_nested_rows_and_removes_indented_empty_line(self):
        original = ('<table><tr><td><table><tr><td><div class="paper-venue">\n'
                    '  <em>Venue</em>\n</div><div class="paper-links">\n  '
                    + block() + '\n</div></td></tr></table></td></tr></table>')
        result = render_paper_citations(original, {ID: paper()})
        self.assertIn('<div class="paper-links">\n</div>', result)
        self.assertEqual(render_paper_citations(result, {ID: paper()}), result)

    def test_cited_paper_with_ambiguous_venue_is_rejected(self):
        for venues in ('', '<div class="paper-venue"></div><div class="paper-venue"></div>'):
            with self.subTest(venues=venues), self.assertRaises(ValueError):
                render_paper_citations('<tr><td>' + venues + block() + '</td></tr>', {ID: paper()})

    def test_legacy_page_without_paper_placeholders_is_unchanged(self):
        self.assertEqual(render_paper_citations(HTML, {}), HTML)


if __name__ == "__main__":
    unittest.main()
