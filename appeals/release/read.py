"""Read releases: the folder of them, the current pointer, and bounded read-only queries.

Anything that serves releases (the MCP server, the public site) goes through
here. A release's DuckDB files are opened read-only with file access,
extensions and configuration changes locked out, so a query can read the
release's tables and nothing else. Quotes live in a separate file that no
SQL from outside ever reaches; `Release.docket` reads them for a few dockets
at a time.
"""
from datetime import date, datetime, time as time_of_day
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading

import duckdb

LIMITS = {'sql_characters': 16_000, 'rows': 1_000, 'default_rows': 200, 'response_bytes': 256_000, 'seconds': 5.0,
          'dockets_per_call': 10}
LOCKDOWN = {'enable_external_access': False, 'autoinstall_known_extensions': False,
            'autoload_known_extensions': False, 'memory_limit': '512MB', 'threads': 2, 'lock_configuration': True}
RELEASE_ID = re.compile(r'^[0-9a-f]{12}$')


class QueryError(ValueError):
    """A query that was refused or failed; the message is safe to show to whoever sent it."""


def connect(path):
    return duckdb.connect(str(path), read_only=True, config=LOCKDOWN)


def plain(value):
    """A DuckDB value as plain JSON."""
    if isinstance(value, (datetime, date, time_of_day)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise QueryError('binary values are not supported')
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def run_query(con, sql, max_rows=None):
    """One SELECT statement, bounded in time, rows and size. Returns {columns, rows, row_count, truncated, ...}."""
    max_rows = LIMITS['default_rows'] if max_rows is None else max_rows
    if not isinstance(sql, str) or not sql.strip():
        raise QueryError('give one SQL SELECT statement')
    if len(sql) > LIMITS['sql_characters']:
        raise QueryError(f'SQL is limited to {LIMITS["sql_characters"]} characters')
    if not isinstance(max_rows, int) or not 1 <= max_rows <= LIMITS['rows']:
        raise QueryError(f'max_rows must be between 1 and {LIMITS["rows"]}')
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as error:
        raise QueryError(_message(error)) from None
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise QueryError('only a single SELECT statement (WITH, FROM, SUMMARIZE and DESCRIBE included) is allowed')
    cursor = con.cursor()
    timer = threading.Timer(LIMITS['seconds'], cursor.interrupt)
    timer.start()
    try:
        cursor.execute(sql)
        columns = [c[0] for c in cursor.description]
        rows, size, reason = [], len(json.dumps(columns)), None
        while True:
            batch = cursor.fetchmany(100)
            if not batch:
                break
            for row in batch:
                if len(rows) >= max_rows:
                    reason = 'row limit'
                    break
                row = [plain(v) for v in row]
                size += len(json.dumps(row)) + 1
                if size > LIMITS['response_bytes']:
                    reason = 'size limit'
                    break
                rows.append(row)
            if reason:
                break
        return {'columns': columns, 'rows': rows, 'row_count': len(rows), 'truncated': reason is not None,
                'truncation_reason': reason}
    except duckdb.InterruptException:
        raise QueryError(f'the query took longer than {LIMITS["seconds"]:g} seconds') from None
    except duckdb.Error as error:
        raise QueryError(_message(error)) from None
    finally:
        timer.cancel()
        cursor.close()


def _message(error):
    """DuckDB's own explanation, which helps fix a query, but never a file path."""
    if isinstance(error, duckdb.PermissionException):
        return 'reading files, loading extensions and changing settings are not allowed'
    return str(error).split('\n\nLINE')[0].strip()[:600]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Release:
    """One release folder, checked against its release.json and opened read-only."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.meta = json.loads((self.folder / 'release.json').read_text())
        self.id = self.meta['id']
        for name, expected in self.meta['files'].items():
            if _sha256(self.folder / name) != expected:
                raise ValueError(f'release {self.id}: {name} does not match its recorded hash')
        self.data = connect(self.folder / 'data.duckdb')
        self.evidence = connect(self.folder / 'evidence.duckdb')

    def close(self):
        self.data.close()
        self.evidence.close()

    def query(self, sql, max_rows=None):
        return {'release': self.id, **run_query(self.data, sql, max_rows)}

    def _rows(self, con, sql, params):
        cursor = con.cursor()
        try:
            cursor.execute(sql, params)
            names = [c[0] for c in cursor.description]
            return [dict(zip(names, (plain(v) for v in row))) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def docket(self, numbers, fields=None):
        """Everything about a few dockets: answers, long-table rows, confidence, quotes and documents.
        `fields` (node IDs) narrows it to those fields and derived values."""
        numbers = [numbers] if isinstance(numbers, str) else list(numbers or [])
        if not numbers or len(numbers) > LIMITS['dockets_per_call']:
            raise QueryError(f'give between 1 and {LIMITS["dockets_per_call"]} docket numbers')
        wanted = set(fields or [])
        keep = {c['name'] for t in self.meta['tables'] if t['name'] == 'dockets'
                for c in t['columns'] if c.get('node') in wanted or 'node' not in c}
        out = []
        for number in numbers:
            found = self._rows(self.data, 'SELECT * FROM dockets WHERE docket = ?', [number])
            if not found:
                out.append({'docket': number, 'found': False})
                continue
            answers = found[0]
            if wanted:
                answers = {k: v for k, v in answers.items() if k in keep}
            entry = {'docket': number, 'found': True, 'answers': answers, 'lists': {}}
            for table in self.meta['tables']:
                if table['form'] in ('set', 'list', 'counts') and (not wanted or table['node'] in wanted):
                    rows = self._rows(self.data, f'SELECT * EXCLUDE (docket) FROM "{table["name"]}" WHERE docket = ?',
                                      [number])
                    entry['lists'][table['name']] = rows
            confidence = self._rows(self.data, 'SELECT * EXCLUDE (docket) FROM confidence WHERE docket = ? '
                                               'ORDER BY field, item', [number])
            quotes = self._rows(self.evidence, 'SELECT * EXCLUDE (docket) FROM evidence WHERE docket = ? '
                                               'ORDER BY field, document, page', [number])
            if wanted:
                confidence = [c for c in confidence if c['field'] in wanted]
                quotes = [q for q in quotes if q['field'] in wanted]
            entry['confidence'] = confidence
            entry['evidence'] = quotes
            entry['documents'] = self._rows(self.data, 'SELECT document, title, posted, pages, url FROM documents '
                                                       'WHERE docket = ? ORDER BY document', [number])
            entry['linked_dockets'] = self._rows(self.data, 'SELECT linked_docket, shared_documents FROM docket_links '
                                                            'WHERE docket = ? ORDER BY 1', [number])
            out.append(entry)
        return {'release': self.id, 'dockets': out}


class Releases:
    """The releases folder: every release ever built, and a `current` file naming the one served."""

    def __init__(self, root):
        self.root = Path(root)
        self._open = {}
        self._lock = threading.Lock()

    def ids(self):
        if not self.root.is_dir():
            return []
        return [p.name for p in self.root.iterdir() if RELEASE_ID.match(p.name) and (p / 'release.json').exists()]

    def summaries(self, tag=None):
        """Every release, newest first, with what a list needs to show; only those tagged `tag` when given."""
        current = self.current_id()
        out = []
        for rid in self.ids():
            meta = json.loads((self.root / rid / 'release.json').read_text())
            tags = meta.get('tags', [])
            if tag is None or tag in tags:
                out.append({'id': rid, 'created_at': meta['created_at'], 'current': rid == current, 'tags': tags,
                            'run': meta['run']['id'], 'graph_hash': meta['run']['graph_hash'],
                            'population': meta['population']})
        return sorted(out, key=lambda r: r['created_at'], reverse=True)

    def delete(self, ids):
        """Delete releases for good. The current release can't be deleted: publish another one first."""
        ids = list(ids)
        if self.current_id() in ids:
            raise ValueError(f'release {self.current_id()} is current; publish another before deleting it')
        for rid in ids:
            if not RELEASE_ID.match(rid) or not (self.root / rid / 'release.json').exists():
                raise ValueError(f'no release {rid}')
        for rid in ids:
            with self._lock:
                release = self._open.pop(rid, None)
            if release is not None:
                release.close()
            shutil.rmtree(self.root / rid)

    def current_id(self):
        pointer = self.root / 'current'
        rid = pointer.read_text().strip() if pointer.exists() else ''
        return rid if RELEASE_ID.match(rid) else None

    def get(self, rid):
        """An open release by ID, or None. Releases are immutable, so each is opened once per process."""
        if not isinstance(rid, str) or not RELEASE_ID.match(rid) or not (self.root / rid / 'release.json').exists():
            return None
        with self._lock:
            if rid not in self._open:
                self._open[rid] = Release(self.root / rid)
            return self._open[rid]

    def current(self):
        rid = self.current_id()
        return self.get(rid) if rid else None

    def publish(self, rid):
        """Make `rid` the current release. Servers pick it up on their next request."""
        if self.get(rid) is None:
            raise ValueError(f'no release {rid}')
        tmp = self.root / '.current.tmp'
        tmp.write_text(rid + '\n')
        os.replace(tmp, self.root / 'current')
