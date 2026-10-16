"""The store: one SQLite file for everything except the PDFs themselves.

Ingest tables hold what came from the court; run tables hold what the
extraction graph produced. Every write goes through this class.

The file uses SQLite's write-ahead log, so the dashboard and other readers
can open it while a run writes. Dates and timestamps are ISO 8601 text
(timestamps in UTC), and lists and records are JSON text.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS listing_entries (
    snapshot   TEXT,      -- folder name of the saved listing pages
    page       INTEGER,   -- listing page number
    ordinal    INTEGER,   -- position on the page
    media_url  TEXT,
    title      TEXT,
    posted     TEXT,      -- YYYY-MM-DD
    division   TEXT,
    docket     TEXT,      -- the listing's docket text, as shown
    note       TEXT,      -- why something listed was not used, such as an implausible posting date
    PRIMARY KEY (snapshot, page, ordinal)
);
CREATE INDEX IF NOT EXISTS listing_entries_media ON listing_entries (media_url);
CREATE TABLE IF NOT EXISTS downloads (
    media_url  TEXT PRIMARY KEY,
    final_url  TEXT,
    sha256     TEXT,
    fetched_at TEXT       -- UTC
);
CREATE INDEX IF NOT EXISTS downloads_sha256 ON downloads (sha256);
CREATE TABLE IF NOT EXISTS documents (
    sha256     TEXT PRIMARY KEY,
    bytes      INTEGER,
    pages      INTEGER
);
CREATE TABLE IF NOT EXISTS pages (
    sha256     TEXT,
    page       INTEGER,
    text       TEXT,
    source     TEXT,      -- native | ocr | NULL when there is no usable text
    status     TEXT,      -- usable | blank | unresolved
    reason     TEXT,
    origin     TEXT,      -- which extraction produced it
    PRIMARY KEY (sha256, page)
);
CREATE TABLE IF NOT EXISTS document_dockets (
    sha256     TEXT,
    docket     TEXT,
    basis      TEXT,      -- heading | listing
    PRIMARY KEY (sha256, docket)
);
CREATE INDEX IF NOT EXISTS document_dockets_docket ON document_dockets (docket);
CREATE TABLE IF NOT EXISTS document_flags (
    sha256     TEXT,
    flag       TEXT,
    PRIMARY KEY (sha256, flag)
);
CREATE TABLE IF NOT EXISTS graphs (
    hash        TEXT PRIMARY KEY,
    description TEXT,                   -- JSON: the pipeline's complete description
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))   -- millisecond precision
);
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    graph_hash  TEXT,
    endpoints   TEXT,                   -- JSON: each endpoint's format, address and model, never keys
    settings    TEXT,                   -- JSON
    dockets     INTEGER,
    status      TEXT,
    cost_usd    REAL,
    started_at  TEXT,                   -- UTC
    finished_at TEXT,                   -- UTC
    tags        TEXT DEFAULT '[]'       -- JSON list of labels given at the start, such as "scratch"
);
CREATE TABLE IF NOT EXISTS node_records (
    key         TEXT PRIMARY KEY,       -- hash of the node, its inputs and the endpoint
    docket      TEXT,
    layer       TEXT,
    node        TEXT,
    value       TEXT,                   -- JSON
    exchange    TEXT,                   -- JSON: exact requests and responses, when a model was called
    cost_usd    REAL,
    seconds     REAL,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS run_records (
    run_id      TEXT,
    docket      TEXT,
    layer       TEXT,
    node        TEXT,
    key         TEXT,
    reused      INTEGER,                -- 1 when the record came from an earlier run
    PRIMARY KEY (run_id, docket, node)
);
CREATE INDEX IF NOT EXISTS run_records_key ON run_records (key);
CREATE INDEX IF NOT EXISTS run_records_docket ON run_records (docket);
CREATE TABLE IF NOT EXISTS reference_answers (
    docket      TEXT,
    field       TEXT,
    value       TEXT,                   -- JSON
    quotes      TEXT,                   -- JSON
    source      TEXT,
    PRIMARY KEY (docket, field)
);

-- One row per document: its earliest listing date and title, and the dockets its listing entries name.
CREATE VIEW IF NOT EXISTS document_info AS
SELECT d.sha256, d.pages, d.bytes,
       (SELECT min(e.posted) FROM downloads w JOIN listing_entries e ON e.media_url = w.media_url
        WHERE w.sha256 = d.sha256) AS posted,
       (SELECT e.title FROM downloads w JOIN listing_entries e ON e.media_url = w.media_url
        WHERE w.sha256 = d.sha256 ORDER BY e.posted NULLS LAST LIMIT 1) AS title,
       (SELECT json_group_array(DISTINCT e.docket) FROM downloads w JOIN listing_entries e ON e.media_url = w.media_url
        WHERE w.sha256 = d.sha256 AND e.docket IS NOT NULL) AS listing_dockets
FROM documents d;
"""


def _iso(value):
    """Dates as YYYY-MM-DD and timestamps as UTC "YYYY-MM-DDTHH:MM:SS.ffffffZ"; anything else unchanged."""
    if isinstance(value, datetime):
        utc = (value if value.tzinfo else value.astimezone()).astimezone(timezone.utc)
        return utc.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    return value.isoformat() if isinstance(value, date) else value


class Store:
    def __init__(self, path, read_only=False):
        self.path = path
        if read_only:
            self.db = sqlite3.connect(f'file:{path}?mode=ro', uri=True, isolation_level=None, check_same_thread=False)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            self.db.execute('PRAGMA journal_mode = WAL')
            self.db.execute('PRAGMA synchronous = NORMAL')
            self.db.executescript(SCHEMA)
            self._add_missing_columns()
        self.db.execute('PRAGMA busy_timeout = 10000')     # wait for a writer's lock instead of failing

    def _add_missing_columns(self):
        """Columns added after a table was first created: (table, column, declaration)."""
        for table, column, declaration in [('listing_entries', 'note', 'TEXT')]:
            columns = {row[1] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if column not in columns:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        self.db.execute('COMMIT')

    def rows(self, sql, params=()):
        """Query results as a list of dicts."""
        cursor = self.db.execute(sql, params)
        names = [c[0] for c in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def value(self, sql, params=()):
        row = self.db.execute(sql, params).fetchone()
        return row[0] if row else None

    # ---- ingest -----------------------------------------------------------

    def add_listing_entries(self, entries):
        self.db.executemany(
            'INSERT OR REPLACE INTO listing_entries (snapshot, page, ordinal, media_url, title, posted, division, '
            'docket, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [(e.snapshot, e.page, e.ordinal, e.media_url, e.title, _iso(e.posted), e.division, e.docket, e.note)
             for e in entries])

    def add_download(self, media_url, final_url, sha256, fetched_at):
        self.db.execute('INSERT OR REPLACE INTO downloads VALUES (?, ?, ?, ?)',
                        (media_url, final_url, sha256, _iso(fetched_at)))

    def add_document(self, sha256, size, pages):
        self.db.execute('INSERT OR REPLACE INTO documents VALUES (?, ?, ?)', (sha256, size, pages))

    def add_pages(self, rows):
        """rows: (sha256, page, text, source, status, reason, origin)"""
        self.db.executemany('INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)', rows)

    def set_document_pages(self, sha256, pages):
        self.db.execute('UPDATE documents SET pages = ? WHERE sha256 = ?', (pages, sha256))

    def set_document_dockets(self, sha256, dockets, flags):
        """dockets: [(docket, basis)]; replaces whatever the document had."""
        self.db.execute('DELETE FROM document_dockets WHERE sha256 = ?', (sha256,))
        self.db.execute('DELETE FROM document_flags WHERE sha256 = ?', (sha256,))
        if dockets:
            self.db.executemany('INSERT INTO document_dockets VALUES (?, ?, ?)', [(sha256, d, b) for d, b in dockets])
        if flags:
            self.db.executemany('INSERT INTO document_flags VALUES (?, ?)', [(sha256, f) for f in flags])

    # ---- runs -------------------------------------------------------------

    def save_graph(self, hash_, description):
        self.db.execute('INSERT OR IGNORE INTO graphs (hash, description) VALUES (?, ?)', (hash_, json.dumps(description)))

    def start_run(self, run_id, graph_hash, endpoints, settings, dockets, started_at, tags=()):
        self.db.execute('INSERT INTO runs (id, graph_hash, endpoints, settings, dockets, status, cost_usd, started_at, '
                        'finished_at, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (run_id, graph_hash, json.dumps(endpoints), json.dumps(settings), dockets, 'running', 0.0,
                         _iso(started_at), None, json.dumps(sorted(set(tags)))))

    def finish_run(self, run_id, status, cost_usd, finished_at):
        self.db.execute('UPDATE runs SET status = ?, cost_usd = ?, finished_at = ? WHERE id = ?',
                        (status, cost_usd, _iso(finished_at), run_id))

    def runs(self, tag=None):
        """Runs, newest first, with JSON columns decoded; only those carrying `tag` when given."""
        if tag is None:
            rows = self.rows('SELECT * FROM runs ORDER BY started_at DESC')
        else:
            rows = self.rows('SELECT * FROM runs WHERE EXISTS (SELECT 1 FROM json_each(runs.tags) WHERE value = ?) '
                             'ORDER BY started_at DESC', (tag,))
        for r in rows:
            for column in ('endpoints', 'settings', 'tags'):
                r[column] = json.loads(r[column]) if r[column] else ([] if column == 'tags' else {})
        return rows

    def delete_runs(self, run_ids):
        """Delete runs and the stored results no remaining run uses. Returns the number of results deleted."""
        if not run_ids:
            return 0
        ids = json.dumps(list(run_ids))
        with self.transaction():
            self.db.execute('DELETE FROM run_records WHERE run_id IN (SELECT value FROM json_each(?))', (ids,))
            self.db.execute('DELETE FROM runs WHERE id IN (SELECT value FROM json_each(?))', (ids,))
            orphans = self.db.execute(
                'DELETE FROM node_records WHERE key NOT IN (SELECT key FROM run_records)').rowcount
        return orphans

    def cached_record(self, key):
        rows = self.rows('SELECT * FROM node_records WHERE key = ?', (key,))
        if not rows:
            return None
        row = rows[0]
        row['value'] = json.loads(row['value']) if row['value'] else None
        row['exchange'] = json.loads(row['exchange']) if row['exchange'] else None
        return row

    def save_record(self, key, docket, layer, node, value, exchange=None, cost_usd=0.0, seconds=0.0):
        self.db.execute(
            'INSERT OR REPLACE INTO node_records (key, docket, layer, node, value, exchange, cost_usd, seconds) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (key, docket, layer, node, json.dumps(value), json.dumps(exchange) if exchange is not None else None,
             cost_usd, seconds))

    def link_record(self, run_id, docket, layer, node, key, reused):
        self.db.execute('INSERT OR REPLACE INTO run_records VALUES (?, ?, ?, ?, ?, ?)',
                        (run_id, docket, layer, node, key, int(bool(reused))))
