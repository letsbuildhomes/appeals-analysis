# Releases, the public site and the MCP server

A **release** is one finished run frozen into files that can be published.
The public site serves releases at `https://data.letsbuildhomes.org/appeals/`.
It has a landing page, a page for every appeal, a read-only JSON API, and an
MCP server at `/appeals/mcp`. Through the MCP server, an AI assistant can
analyse the data, learn what each column means, read the passages of the
decisions behind any one case's answers, and link the reader to that case's
page.

## What readers see

A release is the product, and the pipeline is how it gets made. Readers get
the pipeline's final answers, presented as what the decisions show, and
nothing about how each answer was settled:

- **Final facts only.** No scan answers or probabilities, no record of which
  step answered, no node IDs, prompts or thresholds. Those stay in the store
  and the local dashboard, for whoever runs the pipeline. A quoted passage is
  published only if it was checked against the page.
- **Method and reliability come first.** `overview` carries a few plain
  sentences on how the data was made (`METHOD`) and how far to trust it
  (`RELIABILITY`, in line with the latest answer-key score but never citing it), both in
  `appeals/codebook/conventions.py`. Update `RELIABILITY` before the
  production run whenever a pass changes the figures.
- **Appeals in scope by default.** The main tables hold only appeals in
  scope. The dockets the study set aside are reachable only through the
  `all_` tables, which an assistant is told to use only when a question is
  about them.
- **A version and a date.** Readers name a release by its version (v0.0.2)
  and the day it was built in Vermont (October 19, 2026). The 12-character
  ID is for operators and URLs; run IDs, graph hashes and commits are in
  `release.json`'s `internal` section, which nothing serves.
The site is written for the public, who will not use a terminal. It is
static HTML, CSS and JavaScript in `appeals/site/static/`, with no build step;
asset links carry a hash of the files, so browsers fetch them again after a
deploy. Its look is set once in `site.css`: the Let's Build Homes logo
(`static/brand/lbh-logo.svg`, from reports.letsbuildhomes.org) on its green in
a header bar with the same three links on every page, Source Serif 4
(self-hosted in `static/fonts/`, under the SIL Open Font License) for
headlines and figures, small-caps labels, hairline rules rather than boxes,
square controls, the LBH green as the one accent, and amber only for a quoted
passage. `case.css` adds the appeal pages in the same terms.

- **The landing page** (`index.html`, `site.js`): the current release's
  numbers (or a note that data is coming), an animated seven-step
  walkthrough of how the data is made, how to use the data with an AI
  assistant, and a plain-language guide to the data (summary, how appeals
  work, sources, method, recorded facts, limitations, definitions) written
  for readers who know nothing about the court, AI or data. The walkthrough plays only while
  on screen, stops once the reader steps through it, and never moves for
  readers who ask for reduced motion.
- **Connecting an assistant** is a dialog, opened by any link to `#connect`
  (so `/appeals/#connect` from another page lands with it open). Apps down
  the side (Claude, ChatGPT, Perplexity and any other app that adds a remote
  MCP server by address); for the chosen one, a few numbered steps that link
  straight to the app's settings page where they can, and the name and
  address to paste, each with a copy button. No app offers a link that adds a
  server by itself, so each step links to the app's own settings page.
- **A page per appeal** at `/appeals/<version>/<docket>` (`docket.html`,
  `case.js`, `case.css`), such as `/appeals/v0.0.2/134-7-04-vtec`: the docket
  number in lower case with spaces as hyphens, though the plain number works
  too. It shows the case at a glance (the town's decision, the appeal, the
  court's result, how long it took, new homes), every fact grouped by topic
  with its meaning, a timeline, the documents and linked cases. Each fact's
  quotes open beside the page in a reader that shows the document's text at
  the quote's page with the passage highlighted, and links to the court's PDF
  at that page. `appeals/release/view.py` builds the page from the release's
  data dictionary, so new fields appear by themselves; the server puts it in
  the page, so it shows without a second request. A version names the current
  release if it has that version, else the newest with it; `latest` redirects
  to the current version, and an older version shows an "old data" banner.
- **The list of appeals** at `/appeals/<version>/` (`browse.html`,
  `browse.js`), to search by docket, town or case name and filter by outcome.

Addresses that leave the site (the MCP address the pages show, citations,
and the MCP tools' page links) use `[site] public_url` in `config.toml`, or
the address each request came to when it is empty. For a preview on the
LAN, run `make site PUBLIC_URL=http://192.168.88.3:8000`.

```text
store ──make release──▶ data/releases/<id>/ ──make publish──▶ current ──▶ site: dashboard · API · MCP
```

## What a release holds

`data/releases/<id>/` is never changed once written:

| File | What |
|---|---|
| `data.duckdb` | The research tables, the only data `query` can read |
| `evidence.duckdb` | The checked passages behind the answers (`quotes`), and the page text of every appeal's documents (`pages`), so a reader can see a quote where it stands. Both are read only a docket at a time, through `docket` and the docket pages, so they never come back from bulk queries. A release built before `pages` existed still serves; its quotes link only to the PDFs |
| `release.json` | The version, build date and file hashes; what the data is, its conventions, method and reliability; the data dictionary with a profile and query tips for every column; and what changed since the previous version. An `internal` section keeps the provenance (run, models, git commit) and the run's full graph description for operators; nothing serves it |

The tables:

| Table | Grain |
|---|---|
| `appeals` | One row per appeal in scope: document count and dates, then one column per fact and derived value. Every question starts here |
| long tables | One per yes/no or choice set (`permission_kinds`, `judgment_grounds`), list (`appellants`, …) or count by option (`appellant_mix_roles`, …), for appeals in scope |
| `documents` | Each appeal's documents, numbered as quotes cite them, with the court's PDF link |
| `docket_links` | Appeals that share a decision, which often means the same project |
| `all_dockets` | Every docket the run covered, in scope or not: `in_scope` (NULL when it couldn't be determined), document count and dates, and the scope columns |
| `all_documents`, `all_docket_links` | `documents` and `docket_links` for every docket |

A docket whose run failed is in `all_dockets` with `in_scope` NULL, and
`overview` counts it as not determined.

## The codebook drives everything

The release code names no field. It lays out tables from the value types in
the run's stored graph description, with one rule per type. The rules are
listed at the top of `appeals/release/schema.py`. For example, a date becomes
the date plus a `_precision` column, a list becomes a long table plus a
`_count` column, and "not stated" becomes NULL everywhere except as an
option's value.

So changing the codebook changes the next release with no other edits:

- **A new field or derived value** gets its columns, its dictionary entry,
  its profile and its tips automatically.
- **Labels, codes, option meanings, notes and conventions** come from the
  codebook (`conventions.py`, and `notes` on fields and derived values).
- **Example queries** for the research questions are in
  [RESEARCH-QUESTIONS.md](RESEARCH-QUESTIONS.md). Releases don't carry or
  check them: the release is for any question, not a fixed set.
- **A value that doesn't match its declared type** stops the build, listing
  the problems, because the tables depend on the types.
- **A value type with no rule** stops the build until a rule is added to
  `schema.py`, written once for every field of that type.

A release always describes the graph its run used, not today's codebook. The
`changes` section tells readers which columns were added or removed since the
previous version; `internal.changes` lists the nodes and thresholds that
changed, for operators. A release in an older format can't be served (the
reader refuses it), so rebuild it from its run.

## Commands

```sh
make release RUN_ID=<id> [VERSION=v0.0.2] [TAG=preview]   # build; refuses scratch, fake-model and unfinished runs
                               # VERSION defaults to the version in pyproject.toml
                               # (appeals release <id> --test overrides that and tags the release "test")
make releases [TAG=test]       # list them, marking the current one
make publish RELEASE=<id>      # make it current; running servers switch on their next request
make delete-releases TAG=test  # or RELEASE=<id>; asks first, and never deletes the current release
make site                      # serve on SITE_HOST:SITE_PORT (default 0.0.0.0:8000)
make site SITE_HOST=10.8.0.2   # bind to one address only, such as a VPN address
make mcp-check URL=http://192.168.88.3:8000/appeals/mcp   # end-to-end check of a running server
uv run appeals mcp             # the same tools over stdio, for a local client
```

Releases are kept until you delete them. Tags work like run tags: a release
built with `--test` from a scratch, fake-model or unfinished run is tagged
`test` automatically, so `make delete-releases TAG=test` clears them.
Deleting a release leaves its run in the store. The MCP server serves only
the current one,
because an assistant can't reliably show that data is old. The site's API
serves every release, and the dashboard puts an "old data" banner on any
release that isn't current.

## The MCP tools

| Tool | What it returns |
|---|---|
| `overview` | Start here. The version and build date, what the data is, what it covers, how it was made, how reliable it is, the topics, the tables (with the `all_` tables listed apart), the conventions, how to work with the data, the limits, what changed, and `web_pages`: where each appeal's page is |
| `describe` | Full descriptions of a table, a topic ("Units added"), a field name (`duration`) or named columns. Each has its meaning, options, notes, a profile (counts and how many are known) and tips. With no target, a compact index. Fields and topics match the main tables only; name an `all_` table to see its columns |
| `query` | One read-only DuckDB SELECT: at most 1,000 rows, 256 KB and 5 seconds |
| `docket` | Up to 10 dockets in full: answers, lists, the passages behind them, document links, linked dockets and `page_url`, the docket's page. A docket out of scope has only its scope answers and a note saying so |

**Links to pages.** The server's instructions tell assistants to link each
case they discuss to its page, so a reader can check the answers. The address
comes from `[site] public_url`, also over stdio (`uv run appeals mcp`); with
neither a public address nor a request to take one from, there are no links.

**Query bounds.** Each query is a single SELECT on a DuckDB connection that
is read-only and has file access, extensions and configuration changes
locked out, so it can read the release's tables and nothing else. The tests
try the known ways out.

## Deploying

**The service.** `deploy/appeals-site.service` runs `make site` as a systemd
user service. It reads the address and port from `.site-env`, which git
ignores. Copy `.site-env.example` to `.site-env`, then set `SITE_HOST` to
this machine's VPN address.

Install it as the unit file's header describes. If the VPN interface isn't up
yet at boot, binding fails and systemd retries every five seconds.

**The proxy.** The app mounts every route under `/appeals`, so the proxy
forwards paths unchanged:

```caddy
data.letsbuildhomes.org {
    handle /appeals* {
        reverse_proxy 10.8.0.2:8000
    }
}
```

**Allowed hosts.** The MCP endpoint accepts only the Host headers listed in
`[site] allowed_hosts` in `config.toml`, plus the address it listens on.
Caddy passes the public name through by default, and the list already
includes `data.letsbuildhomes.org`. A 421 response means a Host is missing.
Add another with `appeals site --allowed-host name`, or an empty list turns
the check off. The base path and title are also set in `[site]`.
`/appeals/healthz` names the current release.

**A temporary password.** Until the site goes fully public, the dashboard can
ask for one shared password, with no usernames. Set `SITE_PASSWORD` in
`.site-env` (or pass `appeals site --password …`) and restart the service.
Without the cookie, every page, API call and static file redirects to
`/appeals/login`. The right password sets a cookie for 30 days, renewed
whenever the dashboard loads. Changing the password signs everyone out.
`/appeals/mcp` and `/appeals/healthz` stay open, because MCP clients can't
log in. An empty password turns the check off. The whole feature is
`appeals/site/auth.py` plus one `protect` call in `app.py`; delete both to
remove it.
