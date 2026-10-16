"""The dashboard server: static pages plus a small read-only JSON API over the store.

    /api/graph                      the current pipeline, built from the codebook
    /api/graphs/<hash>              a stored pipeline description (what a run used)
    /api/runs                       runs, newest first
    /api/runs/<id>/dockets          per-docket summary of a run
    /api/runs/<id>/dockets/<n>      every record of one docket in a run
    /api/dockets?search=&limit=     dockets
    /api/dockets/<n>                one docket's documents and pages
    /api/stats                      counts for the header

The server never writes. It opens the store read-only, which works while a
run is writing, since the store uses SQLite's write-ahead log.
"""
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, unquote, urlparse

from appeals.codebook import build
from appeals.ingest import dockets
from appeals.store import Store

STATIC = Path(__file__).parent / 'static'


def _json_default(value):
    return str(value)


class Api:
    def __init__(self, settings):
        self.settings = settings

    def store(self):
        return Store(self.settings.db, read_only=True)

    def graph(self):
        return build(self.settings.thresholds).describe()

    def stored_graph(self, store, hash_):
        value = store.value('SELECT description FROM graphs WHERE hash = ?', (hash_,))
        return json.loads(value) if value else None

    def stats(self, store):
        return {
            'documents': store.value('SELECT count(*) FROM documents'),
            'pages': store.value('SELECT count(*) FROM pages'),
            'dockets': store.value("SELECT count(DISTINCT docket) FROM document_dockets WHERE docket NOT LIKE 'pdf-%'"),
            'runs': store.value('SELECT count(*) FROM runs'),
        }

    def runs(self, store):
        return store.runs()

    def run_dockets(self, store, run_id):
        rows = store.rows("""
            SELECT r.docket, r.node, n.value, n.cost_usd
            FROM run_records r JOIN node_records n ON n.key = r.key
            WHERE r.run_id = ? AND r.node IN ('plan', 'derive', 'error')""", (run_id,))
        cost = {r['docket']: r['cost'] for r in store.rows(
            'SELECT r.docket, sum(CASE WHEN r.reused THEN 0 ELSE n.cost_usd END) AS cost '
            'FROM run_records r JOIN node_records n ON n.key = r.key WHERE r.run_id = ? GROUP BY 1', (run_id,))}
        scope = store.value('SELECT json_extract(g.description, \'$.in_scope\') FROM runs r JOIN graphs g ON g.hash = r.graph_hash '
                            'WHERE r.id = ?', (run_id,))
        out = {}
        for r in rows:
            d = out.setdefault(r['docket'], {'docket': r['docket'], 'cost_usd': round(cost.get(r['docket']) or 0, 4)})
            value = json.loads(r['value'])
            if r['node'] == 'plan':
                d['proceeds'], d['calls'] = value['proceeds'], value['calls']
            elif r['node'] == 'derive':
                d['in_scope'] = value.get(scope) if scope else None
            else:
                d['error'] = value.get('error')
        return sorted(out.values(), key=lambda d: (not d.get('proceeds', False), d['docket']))

    def run_docket(self, store, run_id, number):
        rows = store.rows("""
            SELECT r.layer, r.node, r.reused, n.value, n.exchange, n.cost_usd, n.seconds
            FROM run_records r JOIN node_records n ON n.key = r.key
            WHERE r.run_id = ? AND r.docket = ?""", (run_id, number))
        records = {}
        for r in rows:
            records[r['node']] = {'layer': r['layer'], 'reused': r['reused'], 'cost_usd': r['cost_usd'],
                                  'seconds': r['seconds'], 'value': json.loads(r['value']) if r['value'] else None,
                                  'exchange': json.loads(r['exchange']) if r['exchange'] else None}
        return {'run': run_id, 'docket': number, 'records': records}

    def dockets(self, store, search, limit):
        return dockets.list_dockets(store, search=search or None, limit=limit)

    def docket(self, store, number):
        text = dockets.docket_text(store, number)
        if text is None:
            return None
        flags = store.rows("""SELECT f.sha256, f.flag FROM document_flags f
                              JOIN document_dockets d ON d.sha256 = f.sha256 WHERE d.docket = ?""", (number,))
        reference = store.rows('SELECT field, value, quotes FROM reference_answers WHERE docket = ?', (number,))
        runs = store.rows("""SELECT DISTINCT r.run_id, u.tags FROM run_records r JOIN runs u ON u.id = r.run_id
                             WHERE r.docket = ? AND r.node = 'facts' ORDER BY r.run_id DESC""", (number,))
        return {
            'number': number, 'chars': text.chars,
            'documents': [{'n': d.n, 'sha256': d.sha256, 'title': d.title, 'posted': d.posted, 'dockets': d.dockets,
                           'flags': [f['flag'] for f in flags if f['sha256'] == d.sha256], 'pages': d.pages}
                          for d in text.documents],
            'reference': {r['field']: json.loads(r['value']) for r in reference},
            'runs': [r['run_id'] for r in runs],
            'run_tags': {r['run_id']: json.loads(r['tags'] or '[]') for r in runs},
        }


def make_handler(api):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            url = urlparse(self.path)
            if not url.path.startswith('/api/'):
                if url.path in ('/', '/graph'):
                    self.path = '/index.html'
                elif url.path == '/case':
                    self.path = '/case.html'
                return super().do_GET()
            try:
                self._api(url)
            except sqlite3.OperationalError as error:          # e.g. still locked after the busy timeout
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, {'error': f'The store is busy ({error}). Try again.'})
            except Exception as error:                       # report, don't crash the server
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': f'{type(error).__name__}: {error}'})

        def _api(self, url):
            parts = [unquote(p) for p in url.path.split('/')[2:] if p]
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if parts == ['graph']:
                return self._send(HTTPStatus.OK, api.graph())
            store = api.store()
            try:
                if parts == ['stats']:
                    result = api.stats(store)
                elif len(parts) == 2 and parts[0] == 'graphs':
                    result = api.stored_graph(store, parts[1])
                elif parts == ['runs']:
                    result = api.runs(store)
                elif len(parts) == 3 and parts[0] == 'runs' and parts[2] == 'dockets':
                    result = api.run_dockets(store, parts[1])
                elif len(parts) == 4 and parts[0] == 'runs' and parts[2] == 'dockets':
                    result = api.run_docket(store, parts[1], parts[3])
                elif parts == ['dockets']:
                    result = api.dockets(store, query.get('search'), int(query.get('limit', 200)))
                elif len(parts) == 2 and parts[0] == 'dockets':
                    result = api.docket(store, parts[1])
                else:
                    return self._send(HTTPStatus.NOT_FOUND, {'error': 'unknown API path'})
            finally:
                store.close()
            if result is None:
                return self._send(HTTPStatus.NOT_FOUND, {'error': 'not found'})
            self._send(HTTPStatus.OK, result)

        def _send(self, status, body):
            data = json.dumps(body, default=_json_default).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

    return Handler


def serve(settings, host='0.0.0.0', port=8800):
    server = ThreadingHTTPServer((host, port), make_handler(Api(settings)))
    print(f'Dashboard on http://{host}:{port}/  (on this network: use the machine\'s LAN address)')
    server.serve_forever()
