"""Offline regression tests. All numbers below are synthetic test data."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError

from update_scholar_stats import (
    END, SCHOLAR_ID, START, parse_scholar, render_stats, update_stats, validate_stats,
)

PAGE = """
<div id="gsc_prf_in">Hongjie Fang</div>
<table id="gsc_rsb_st"><thead><tr>
<th></th><th>All</th><th>Since 2021</th>
</tr></thead><tbody>
<tr><td><a>Citations</a></td><td class="gsc_rsb_std">1,234</td><td>999</td></tr>
<tr><td><a>h-index</a></td><td class="gsc_rsb_std">12</td><td>10</td></tr>
<tr><td><a>i10-index</a></td><td class="gsc_rsb_std">20</td><td>18</td></tr>
</tbody></table>
<table><tr><td>Not part of the summary</td><td>99999</td></tr></table>
"""
HTML = f"<main>{START}\n<a>Google Scholar</a>\n{END}<p>Keep me.</p></main>"
SNAPSHOT = {
    "scholar_id": SCHOLAR_ID,
    "citations": 1234,
    "h_index": 12,
    "updated_at": "2026-01-02T03:04:00+00:00",
}


class ScholarStatsTests(unittest.TestCase):
    def test_all_time_metrics_not_recent_column_or_paper_counts(self):
        stats = parse_scholar(PAGE)
        self.assertEqual(stats["citations"], 1234)
        self.assertEqual(stats["h_index"], 12)
        self.assertEqual(stats["scholar_id"], SCHOLAR_ID)
        validate_stats(stats)

    def test_all_time_column_is_identified_by_header(self):
        page = PAGE.replace("<th>All</th><th>Since 2021</th>",
                            "<th>Since 2021</th><th>All</th>")
        stats = parse_scholar(page)
        self.assertEqual(stats["citations"], 999)
        self.assertEqual(stats["h_index"], 10)

    def test_verification_page_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_scholar("<html>Sorry, unusual traffic. Verify you are human.</html>")

    def test_wrong_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_scholar(PAGE.replace("Hongjie Fang", "Someone Else"))

    def test_missing_or_changed_summary_is_rejected(self):
        for page in (PAGE.replace("gsc_rsb_st", "other"),
                     PAGE.replace("h-index", "unknown"),
                     PAGE.replace(">All<", ">Recent<")):
            with self.subTest(page=page), self.assertRaises(ValueError):
                parse_scholar(page)

    def test_missing_malformed_and_negative_numbers_are_rejected(self):
        for value in ("", "—", "-1", "1,23", "12x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_scholar(PAGE.replace("1,234", value))

    def test_zero_metrics_are_valid(self):
        stats = parse_scholar(PAGE.replace("1,234", "0").replace(">12<", ">0<"))
        self.assertEqual((stats["citations"], stats["h_index"]), (0, 0))

    def test_invalid_cache_is_rejected(self):
        for patch in ({"scholar_id": "other"}, {"citations": True},
                      {"h_index": -1}, {"h_index": 9000},
                      {"updated_at": None}, {"updated_at": "invalid"},
                      {"updated_at": "2026-01-01"}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_stats({**SNAPSHOT, **patch})
        with self.assertRaises(ValueError):
            validate_stats([])

    def test_render_formats_counts_and_preserves_page(self):
        result = render_stats(HTML, SNAPSHOT)
        self.assertIn("<strong>1,234</strong> citations", result)
        self.assertIn("h-index <strong>12</strong>", result)
        self.assertIn("Updated 2026-01-02 03:04 UTC", result)
        self.assertIn("&amp;hl=en", result)
        self.assertTrue(result.endswith("<p>Keep me.</p></main>"))
        self.assertEqual(render_stats(result, SNAPSHOT), result)

    def test_missing_duplicate_and_reversed_markers_fail(self):
        for page in ("<main></main>", HTML + START, HTML + END, END + START):
            with self.subTest(page=page), self.assertRaises(ValueError):
                render_stats(page, SNAPSHOT)

    def test_success_updates_cache_and_html(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, homepage = self.paths(folder)
            homepage.write_text(HTML, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                fresh = update_stats(cache, homepage, lambda: SNAPSHOT.copy())
            self.assertTrue(fresh)
            self.assertEqual(json.loads(cache.read_text()), SNAPSHOT)
            self.assertIn("1,234", homepage.read_text())

    def test_failure_keeps_cached_values_and_original_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, homepage = self.paths(folder)
            cache.parent.mkdir()
            original = json.dumps(SNAPSHOT)
            cache.write_text(original, encoding="utf-8")
            homepage.write_text(HTML, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                fresh = update_stats(cache, homepage, self.unavailable)
            self.assertFalse(fresh)
            self.assertEqual(json.loads(cache.read_text()), SNAPSHOT)
            self.assertIn("1,234", homepage.read_text())
            self.assertIn("2026-01-02 03:04 UTC", homepage.read_text())

    def test_first_run_failure_does_not_invent_counts_or_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, homepage = self.paths(folder)
            homepage.write_text(HTML, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(update_stats(cache, homepage, self.unavailable))
            self.assertEqual(homepage.read_text(), HTML)
            self.assertFalse(cache.exists())

    def test_corrupt_cache_is_replaced_only_by_valid_response(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, homepage = self.paths(folder)
            cache.parent.mkdir()
            cache.write_text("not json", encoding="utf-8")
            homepage.write_text(HTML, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(update_stats(cache, homepage, lambda: SNAPSHOT.copy()))
            self.assertEqual(json.loads(cache.read_text()), SNAPSHOT)

    def test_saved_snapshot_survives_cache_eviction(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, homepage = self.paths(folder)
            saved = Path(folder) / "snapshot.json"
            saved.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
            homepage.write_text(HTML, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                fresh = update_stats(cache, homepage, self.unavailable, saved)
            self.assertFalse(fresh)
            self.assertEqual(json.loads(cache.read_text()), SNAPSHOT)
            self.assertEqual(json.loads(saved.read_text()), SNAPSHOT)
            self.assertIn("1,234", homepage.read_text())

    def test_newest_valid_snapshot_wins_when_fetch_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            cache, homepage = self.paths(folder)
            cache.parent.mkdir()
            saved = Path(folder) / "snapshot.json"
            newer = {**SNAPSHOT, "citations": 1400, "updated_at": "2026-02-01T00:00:00Z"}
            for cached, checked_in in ((SNAPSHOT, newer), (newer, SNAPSHOT)):
                with self.subTest(cached=cached):
                    cache.write_text(json.dumps(cached), encoding="utf-8")
                    saved.write_text(json.dumps(checked_in), encoding="utf-8")
                    homepage.write_text(HTML, encoding="utf-8")
                    with contextlib.redirect_stdout(io.StringIO()):
                        update_stats(cache, homepage, self.unavailable, saved)
                    self.assertEqual(json.loads(saved.read_text()), newer)
                    self.assertEqual(json.loads(cache.read_text()), newer)
                    self.assertIn("1,400", homepage.read_text())

    @staticmethod
    def paths(folder):
        return Path(folder) / "cache/stats.json", Path(folder) / "index.html"

    @staticmethod
    def unavailable():
        raise URLError("Scholar temporarily unavailable")


if __name__ == "__main__":
    unittest.main()
