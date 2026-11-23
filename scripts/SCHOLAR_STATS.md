# Google Scholar metrics

The Publications heading displays all-time citations and h-index from
[Hongjie Fang's Google Scholar profile](https://scholar.google.com/citations?user=Kyio_RAAAAAJ&hl=en).
Each publication also displays a citation icon and number after its venue and
honor labels, without a separate button or border. These counts link to the
corresponding Scholar article. Tooltips and
accessible labels identify Google Scholar and the last successful update in UTC.

## Automatic updates

The existing **Deploy static content to Pages** workflow runs:

- On pushes to `main`.
- Daily at 22:17 UTC (06:17 China Standard Time the following day).
- On demand through GitHub → Actions → Deploy static content to Pages → Run workflow.

`scripts/update_scholar_stats.py` fetches the profile with `pagesize=100`. The first
response supplies both the summary and the individual article rows; it does not
request each paper separately. If Scholar enables the next-page control, it fetches
additional pages, validates ownership and detects repeated pages. Requests have a
20-second timeout, a 2 MB response limit and a maximum of ten profile pages.

The heading still reads the summary table's **All** column, never a sum of paper
counts. Individual counts come from each article's citation anchor, excluding the
publication year and Scholar's trailing asterisk. An explicitly empty, unlinked
citation anchor means zero; a missing cell or malformed count is a parsing failure,
not zero. The parser validates the profile name, article ownership, IDs, counts,
complete table markup and timestamps.

Rendering happens at build time. The updater replaces only the `scholar-stats`
block and each `paper-citations:ID` block in `index.html` inside the deployment
checkout. No browser-side requests to Scholar, API keys, paid services or source
commits are required. Visitors receive the already-rendered citation links.

## Matching articles and adding publications

Each paper uses its stable Scholar article ID, not its current title. This handles
renames such as HINT, AnyDexRT and ChronoFlow without fuzzy matching or accidentally
transferring a citation count to a different paper.

To enable citations for a new paper:

1. Open the paper from the author's Scholar profile and inspect `citation_for_view`
   in the URL. For example, `Kyio_RAAAAAJ:hC7cP41nSMkC` identifies HINT; the article
   ID is the part after the colon, `hC7cP41nSMkC`.
2. Add `<!-- paper-citations:hC7cP41nSMkC:start --><!-- paper-citations:hC7cP41nSMkC:end -->`
   at the end of that paper's `.paper-venue` div after any honor labels, replacing
   the example ID with the new paper's actual ID. Use each ID only once on the homepage.
3. Run the updater, or let the next deployment populate the block. The next
   successful profile fetch automatically includes new article records.
4. Add the new title/ID binding to `expectedPapers` in `scripts/test_homepage.cjs`
   so the browser regression check covers the new row as well.

The same marker pair remains around the generated link on later runs. The renderer
also relocates older link-row markers to their paper's venue row; repeated renders
are idempotent. Title edits need no matching changes. If Scholar merges/removes an entry and assigns a different
ID, verify the replacement on Scholar and update that paper's marker pair together.
The updater warns about IDs with no verified record; it never guesses a match.

## Cache and failure behavior

GitHub Actions restores and saves `.cache/scholar-stats.json`. The checked-in
`data/scholar-stats.json` is also deployed and supplies an initial verified fallback
if the Actions cache is unavailable or evicted. The JSON retains the existing
`scholar_id`, `citations`, `h_index` and `updated_at` summary fields, plus a `papers`
object keyed by article ID. Each paper records its Scholar title, citations and its
own `updated_at`. Old summary-only snapshots remain readable.

The updater selects the newest valid summary and the newest valid record for each
paper independently. A successful fetch can legitimately lower a count if Scholar
revises it; counts are not forced to increase. Papers missing from a later response
retain their previous count **and original timestamp**. If the article table or a
later page fails, all previous paper counts remain available even if the summary
successfully refreshes. A complete fetch failure retains both kinds of metrics.
An article with no verified data displays **—** with an unavailable-data tooltip
and accessible label, never an invented zero.
If neither snapshot exists and the first fetch fails, the existing HTML is unchanged.

A verification page, HTTP error or unexpected source markup produces a workflow
warning rather than fabricated counts. Malformed or duplicate local placeholder
markers are configuration errors and fail the update before rewriting the snapshots.
Successful runs save the merged snapshot to the cache and deployed JSON, then
update the homepage. The workflow uses `scholar-stats-v2-` cache keys, with a
summary-only `v1` cache as an additional migration fallback.

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

- Refresh the local homepage and both snapshot files: `python3 scripts/update_scholar_stats.py`
- Render the saved counts without another network request: `python3 scripts/update_scholar_stats.py --cached-only`
- Run offline tests: `python3 -m unittest discover -s scripts -p 'test_*.py'`
- Run browser tests against a local server: `node scripts/test_homepage.cjs`

The updater accepts `--html PATH`, `--cache PATH` and `--snapshot PATH` for alternate
destinations. The local `.cache/` directory is ignored by Git. Offline tests cover
valid zero versus unavailable, pagination, renamed papers, malformed source markup,
partial refreshes, cache eviction, timestamps, formatting and idempotent rendering.
Test counts and article IDs are synthetic and are never production defaults.
