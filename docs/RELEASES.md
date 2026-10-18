# Releases, the public site and the MCP server

A **release** is one finished run frozen into files that can be published.
The public site serves releases at `https://data.letsbuildhomes.org/appeals/`.
It has a dashboard, which is a placeholder for now, a read-only JSON API, and
an MCP server at `/appeals/mcp`. Through the MCP server, an AI assistant can
analyse the data, learn what each column means, and trace any value back
through the pipeline.

```text
store ──make release──▶ data/releases/<id>/ ──make publish──▶ current ──▶ site: dashboard · API · MCP
```

## What a release holds

`data/releases/<id>/` is never changed once written:

| File | What |
|---|---|
| `data.duckdb` | The research tables, the only data `query` can read |
| `evidence.duckdb` | The quotes behind the answers. They are read only through `docket`, a few dockets at a time, so quotes never come back from bulk queries |
| `release.json` | The release's identity and provenance (run, graph hash, models, git commit, file hashes). It also holds the run's full graph description, the data dictionary with a profile and query tips for every column, and what changed since the previous release |

The tables:

| Table | Grain |
|---|---|
| `dockets` | One row per docket the run covered: status, whether it's in scope, document count and dates, then one column per fact and derived value. Only the scope columns are filled for out-of-scope dockets |
| `appeals` | A view of `dockets WHERE in_scope`. Questions about appeals start here |
| long tables | One per yes/no or choice set (`permission_kinds`, `judgment_grounds`), list (`appellants`, …) or count by option (`appellant_mix_roles`, …) |
| `documents` | Each docket's documents, numbered as quotes cite them, with the court's PDF link |
| `docket_links` | Dockets that share a decision, which often means the same project |
| `confidence` | Where each settled answer came from: a quoted step, the scan with its probability, a rule, or nothing |

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
`changes` section compares it with the previous release: columns, nodes,
thresholds and conventions added, removed or changed.

## Commands

```sh
make release RUN_ID=<id> [TAG=preview]   # build; refuses scratch, fake-model and unfinished runs
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
| `overview` | Start here. What the data is, the release and its provenance, the population, the tables, the conventions, how to work with the data, the limits and what changed |
| `describe` | Full descriptions of a table, a code (`A4`, `X4`), a node or named columns. Each has its meaning, options, notes, how it's settled, a profile (counts, share known, sources) and tips. With no target, a compact index |
| `explain` | `pipeline` describes the whole flow: layers, gates, steps in order, thresholds and what the run did. A column, node or code returns that node and everything upstream of it: questions, gates, prompts, the field's rule and derived-value code |
| `query` | One read-only DuckDB SELECT: at most 1,000 rows, 256 KB and 5 seconds |
| `docket` | Up to 10 dockets in full, with confidence, quotes, document links and linked dockets |

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
