# Google Scholar metrics

The Publications heading displays all-time citations and h-index from
[Hongjie Fang's Google Scholar profile](https://scholar.google.com/citations?user=Kyio_RAAAAAJ&hl=en).
The numbers link to the profile; the tooltip records the last successful fetch in UTC.

## Automatic updates

The existing **Deploy static content to Pages** workflow now runs:

- On pushes to `main`.
- Daily at 22:17 UTC (06:17 China Standard Time the following day).
- On demand through GitHub → Actions → Deploy static content to Pages → Run workflow.

`scripts/update_scholar_stats.py` fetches the profile's summary table and reads the
**All** column, never a sum of individual publications. It validates the profile,
numbers and timestamp, then replaces only the `scholar-stats` block in `index.html`
inside the deployment checkout. The rest of the existing Pages deployment stays
unchanged. No source commits, browser-side scraping, API keys or paid services are
required.

GitHub Actions restores and saves `.cache/scholar-stats.json` so a failed fetch
uses the last successful snapshot without changing its timestamp. The checked-in
`data/scholar-stats.json` contains an initial verified snapshot as a fallback if
the Actions cache is unavailable or evicted. The updater selects the newer valid
snapshot, then writes the chosen values to the cache, deployed JSON and HTML.
A verification page, HTTP error or unexpected markup produces a workflow warning
rather than zero or fabricated counts. If both snapshots are unavailable, the
existing HTML is left untouched.

Google Scholar has no official public API for these metrics and may block
requests from GitHub-hosted runners. The schedule is a daily **attempt**, not a
guarantee of fresh data. Actions caches can be evicted; in that case a failed
fetch falls back to the checked-in snapshot, which may be older. GitHub may also
disable scheduled workflows in public repositories after 60 days without
repository activity; re-enable the workflow in Actions if necessary. Scheduled
executions can be delayed by GitHub.

These updates become active only after the changes are pushed to the default
branch and the workflow is enabled. Scheduled runs update the deployed HTML and
JSON, not source commits. The repository keeps the snapshot from its last local
refresh.

## Local use and tests

From the repository root:

- Refresh the local homepage: `python3 scripts/update_scholar_stats.py`
- Run offline tests: `python3 -m unittest discover -s scripts -p 'test_scholar_stats.py'`

The updater accepts `--html PATH`, `--cache PATH` and `--snapshot PATH` for alternate
destinations. The local `.cache/` directory is ignored by Git. Test counts are
synthetic and are never used as production defaults.
