# GitHub stars on publication links

`scripts/update_github_stars.py` uses GitHub's official repository API to add a
compact star icon and count inside each GitHub repository link in the homepage's
publication list. Existing link labels, URLs and attributes are preserved. For
example, AirExo-2's data-collection and policy repositories each get their own count.
Tooltips identify the repository and last successful update in UTC; screen readers
also receive a text label for the star count.

## Daily updates

The existing Pages workflow refreshes stars alongside Scholar citations on pushes,
manual runs and the daily 22:17 UTC schedule (06:17 China Standard Time). GitHub may
delay scheduled runs. The GitHub step uses the workflow's built-in `GITHUB_TOKEN`;
no personal token or extra secret configuration is required, and existing read-only
repository permissions are sufficient for public metadata.

The script reads repository URLs directly from links inside
`#section-publications .paper-links`. It ignores author/profile links, non-GitHub
resources, commented-out projects, and links elsewhere on the page. Adding a new
repository link automatically includes it in the next refresh: there is no separate
mapping file. GitHub URL casing, `.git`, trailing slashes and subpaths are normalized,
and each unique repository is fetched only once per run. The script follows official
API redirects for renamed repositories while retaining the original webpage link.
Authorization is never forwarded outside the HTTPS `api.github.com` host.

Only public repositories with validated numeric star counts are accepted. Each
request has a 20-second timeout and 1 MB response limit. HTTP 401/403/429 stops further
requests for that run to avoid repeatedly hitting an authentication or rate limit.
Other repository-specific errors retain that repository's last verified count while
the remaining repositories continue updating.

## Storage and failure behavior

- `.cache/github-stars.json` is restored/saved by Actions under `github-stars-v1-` keys.
- `data/github-stars.json` is a checked-in fallback and is included in the deployed site.
- Each repository record stores its canonical name, stars and individual successful
  update timestamp. The newest valid record wins independently for each repository.
- Failed requests never overwrite a known count or advance its timestamp. Genuine
  decreases are allowed. A first-time unknown count displays **★ —**, not zero.
- The initial checked-in snapshot remains available if Actions evicts the cache.
- Counts are rendered into HTML before deployment. Browsers make no GitHub API
  requests and receive no tokens. No automatic source commits are created.

The generated badge is delimited by `<!-- github-stars:start -->` and
`<!-- github-stars:end -->` inside its existing anchor. Reruns replace the badge
without duplicating it or altering the original label. Changing a link to another
repository selects that new repository's data; changing it to a non-GitHub resource
removes the previously generated badge. Malformed local marker blocks fail the
update before requests or file rewrites.

## Local commands

- Refresh: `python3 scripts/update_github_stars.py`
- Render cached data only: `python3 scripts/update_github_stars.py --cached-only`
- Offline tests: `python3 -m unittest discover -s scripts -p 'test_*.py'`
- Browser checks against a local preview: `node scripts/test_homepage.cjs`

Local refreshes can run anonymously within GitHub's unauthenticated API quota. An
optional `GITHUB_TOKEN` environment variable increases the available quota; the
script never writes or logs the token. Alternate paths are supported via `--html`,
`--cache` and `--snapshot`. The automatic workflow changes take effect after they
are pushed to the default branch and the Pages workflow is enabled.
