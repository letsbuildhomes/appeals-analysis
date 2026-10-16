"""The store: one DuckDB file for everything except the PDFs themselves.

Ingest tables hold what came from the court; run tables hold what the
extraction graph produced. Every write goes through this class.
"""
from contextlib import contextmanager
import json

import duckdb

SCHEMA = """
CREATE TABLE IF NOT EXISTS listing_entries (
    snapshot   TEXT,      -- folder name of the saved listing pages
    page       INTEGER,   -- listing page number
    ordinal    INTEGER,   -- position on the page
    media_url  TEXT,
    title      TEXT,
    posted     DATE,
    division   TEXT,
    docket     TEXT,      -- the listing's docket text, as shown
    PRIMARY KEY (snapshot, page, ordinal)
);
CREATE TABLE IF NOT EXISTS downloads (
    media_url  TEXT PRIMARY KEY,
    final_url  TEXT,
    sha256     TEXT,
    fetched_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    sha256     TEXT PRIMARY KEY,
    bytes      BIGINT,
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
CREATE TABLE IF NOT EXISTS document_flags (
    sha256     TEXT,
    flag       TEXT,
    PRIMARY KEY (sha256, flag)
);
CREATE TABLE IF NOT EXISTS graphs (
    hash        TEXT PRIMARY KEY,
    description JSON,
    created_at  TIMESTAMP DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    graph_hash  TEXT,
    endpoints   JSON,
    settings    JSON,
    dockets     INTEGER,
    status      TEXT,
    cost_usd    DOUBLE,
    started_at  TIMESTAMP,
    finished_at TIMESTAMP,
    tags        VARCHAR[] DEFAULT []   -- labels given at the start, such as "scratch"
);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS tags VARCHAR[] DEFAULT [];
CREATE TABLE IF NOT EXISTS node_records (
    key         TEXT PRIMARY KEY,   -- hash of the node, its inputs and the endpoint
    docket      TEXT,
    layer       TEXT,
    node        TEXT,
    value       JSON,
    exchange    JSON,               -- exact requests and responses, when a model was called
    cost_usd    DOUBLE,
    seconds     DOUBLE,
    created_at  TIMESTAMP DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS run_records (
    run_id      TEXT,
    docket      TEXT,
    layer       TEXT,
    node        TEXT,
    key         TEXT,
    reused      BOOLEAN,
    PRIMARY KEY (run_id, docket, node)
);
CREATE TABLE IF NOT EXISTS reference_answers (
    docket      TEXT,
    field       TEXT,
    value       JSON,
    quotes      JSON,
    source      TEXT,
    PRIMARY KEY (docket, field)
);

CREATE OR REPLACE VIEW document_info AS
SELECT d.sha256, d.pages, d.bytes,
       min(e.posted) AS posted,
       arg_min(e.title, e.posted) AS title,
       list(DISTINCT e.docket) FILTER (WHERE e.docket IS NOT NULL) AS listing_dockets
FROM documents d
LEFT JOIN downloads w ON w.sha256 = d.sha256
LEFT JOIN listing_entries e ON e.media_url = w.media_url
GROUP BY d.sha256, d.pages, d.bytes;
"""


class Store:
    def __init__(self, path, read_only=False):
        self.path = path
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(path), read_only=read_only)
        if not read_only:
            self.db.execute(SCHEMA)

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
            'INSERT OR REPLACE INTO listing_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [(e.snapshot, e.page, e.ordinal, e.media_url, e.title, e.posted, e.division, e.docket) for e in entries])

    def add_download(self, media_url, final_url, sha256, fetched_at):
        self.db.execute('INSERT OR REPLACE INTO downloads VALUES (?, ?, ?, ?)', (media_url, final_url, sha256, fetched_at))

    def add_document(self, sha256, size, pages):
        self.db.execute('INSERT OR REPLACE INTO documents VALUES (?, ?, ?)', (sha256, size, pages))

    def add_pages(self, rows):
        """rows: (sha256, page, text, source, status, reason, origin)"""
        self.db.executemany('INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?, ?)', rows)

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
                         started_at, None, sorted(set(tags))))

    def finish_run(self, run_id, status, cost_usd, finished_at):
        self.db.execute('UPDATE runs SET status = ?, cost_usd = ?, finished_at = ? WHERE id = ?',
                        (status, cost_usd, finished_at, run_id))

    def runs(self, tag=None):
        """Runs, newest first; only those carrying `tag` when given."""
        if tag is None:
            return self.rows('SELECT * FROM runs ORDER BY started_at DESC')
        return self.rows('SELECT * FROM runs WHERE list_contains(tags, ?) ORDER BY started_at DESC', (tag,))

    def delete_runs(self, run_ids):
        """Delete runs and the stored results no remaining run uses. Returns the number of results deleted."""
        if not run_ids:
            return 0
        ids = list(run_ids)
        with self.transaction():
            self.db.execute('DELETE FROM run_records WHERE list_contains(?, run_id)', (ids,))
            self.db.execute('DELETE FROM runs WHERE list_contains(?, id)', (ids,))
            orphans = self.value('SELECT count(*) FROM node_records WHERE key NOT IN (SELECT key FROM run_records)')
            self.db.execute('DELETE FROM node_records WHERE key NOT IN (SELECT key FROM run_records)')
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
                        (run_id, docket, layer, node, key, reused))
