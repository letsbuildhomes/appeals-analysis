"""Command line: `appeals <command>`. The Makefile wraps the common ones."""
import argparse
import asyncio
from datetime import date
import json
import os
import sys

from appeals import config
from appeals.store import Store


def _settings(args):
    overrides = {
        'workers': getattr(args, 'workers', None),
        'budget_usd': getattr(args, 'budget', None),
        'reasoning.model': getattr(args, 'reasoning_model', None),
        'reasoning.key': getattr(args, 'reasoning_key', None),
        'decision.model': getattr(args, 'decision_model', None),
        'decision.key': getattr(args, 'decision_key', None),
    }
    return config.load(overrides=overrides)


def cmd_doctor(args):
    from appeals.ingest.text import tools_available
    settings = _settings(args)
    for tool, ok in tools_available().items():
        note = '' if ok else ('  (needed only to OCR new scanned pages)' if tool == 'tesseract' else '  (required)')
        print(f'{"ok " if ok else "-- "} {tool}{note}')
    for name in ('decision', 'reasoning'):
        model = getattr(settings, name).model
        print(f'{"ok " if model.key else "-- "} {name} key ({model.provider.key_env}) for {model.ref}')
        for warning in model.provider.warnings(date.today()):
            print(f'-- {model.provider.id}: {warning}')


def cmd_ingest(args):
    from appeals.ingest import dockets, listing, pdfs, text
    settings = _settings(args)
    store = Store(settings.db)
    if args.crawl:
        folder = listing.crawl(settings)
        print(f'Listing: new snapshot saved to {folder}')
    listing.reparse_all(settings, store)
    pdfs.download_new(settings, store, limit=args.limit)
    text.extract_missing(settings, store)
    dockets.assign_all(store)


def cmd_dockets(args):
    from appeals.ingest import dockets
    store = Store(_settings(args).db, read_only=True)
    if args.number:
        doc = dockets.docket_text(store, args.number)
        print(doc.text if doc else f'No docket {args.number}')
        return
    for row in dockets.list_dockets(store, search=args.search, limit=args.limit):
        print(f'{row["number"]:<18} {row["documents"]:>3} docs {row["chars"] or 0:>8} chars  {row["title"] or ""}')


def cmd_graph(args):
    from appeals.codebook import build
    settings = _settings(args)
    pipeline = build(settings.thresholds)
    description = pipeline.describe()
    out = settings.data / 'graph.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(description, indent=1))
    print(pipeline.summary())
    print(f'graph {pipeline.hash()} written to {out}')


def cmd_run(args):
    from appeals.codebook import build
    from appeals.graph import endpoints
    from appeals.graph.run import Runner
    settings = _settings(args)
    store = Store(settings.db)
    pipeline = build(settings.thresholds)
    if args.model == 'fake':
        decision, reasoning = endpoints.FakeDecisions(), endpoints.FakeReasoning()
    else:
        decision, reasoning = endpoints.decision_model(settings.decision.model), endpoints.reasoning_model(settings.reasoning)
    numbers = _pick_dockets(store, args)
    runner = Runner(pipeline, store, settings, decision, reasoning)
    run_id = asyncio.run(runner.run(numbers, workers=settings.workers, tags=args.tag or [],
                                    fresh_steps=args.fresh_steps))
    print(f'run {run_id}')


def _pick_dockets(store, args):
    from appeals.ingest import dockets
    if args.dockets:
        return [d.strip() for d in args.dockets.split(',') if d.strip()]
    rows = dockets.list_dockets(store)
    numbers = [r['number'] for r in rows if not r['number'].startswith('pdf-')]
    return numbers[:args.limit] if args.limit else numbers


def _run_line(r):
    tags = f'  [{", ".join(r["tags"])}]' if r['tags'] else ''
    model = r['endpoints'].get('reasoning', {}).get('model', '')
    started = (r['started_at'] or '')[:16].replace('T', ' ')
    return (f'{r["id"]}  {started} UTC  {r["dockets"]:>5} dockets  {r["status"]:<17} '
            f'${r["cost_usd"] or 0:>7.2f}  {model}{tags}')


def cmd_runs(args):
    store = Store(_settings(args).db, read_only=True)
    runs = store.runs(tag=args.tag)
    for r in runs:
        print(_run_line(r))
    if not runs:
        print('No runs' + (f' tagged {args.tag}' if args.tag else ''))


def cmd_delete_runs(args):
    if bool(args.run) == bool(args.tag):
        sys.exit('Give either a run ID or --tag, not both.')
    store = Store(_settings(args).db)
    runs = [r for r in store.runs() if r['id'] == args.run] if args.run else store.runs(tag=args.tag)
    if not runs:
        sys.exit(f'No run {args.run}' if args.run else f'No runs tagged {args.tag}')
    print(f'Deleting {len(runs)} run{"s" if len(runs) != 1 else ""}:')
    for r in runs:
        print('  ' + _run_line(r))
    spent = sum(r['cost_usd'] or 0 for r in runs)
    if spent:
        print(f'Their model calls cost ${spent:.2f}; results no other run uses are lost and would be paid for again.')
    if not args.yes and input('Delete? [y/N] ').strip().lower() not in ('y', 'yes'):
        sys.exit('Nothing deleted.')
    results = store.delete_runs([r['id'] for r in runs])
    print(f'Deleted {len(runs)} run{"s" if len(runs) != 1 else ""} and {results} stored results no other run used.')


def cmd_score(args):
    from appeals.codebook import build
    from appeals.graph.score import score_run
    settings = _settings(args)
    store = Store(settings.db, read_only=True)
    print(json.dumps(score_run(build(settings.thresholds), store, args.run), indent=1))


def cmd_serve(args):
    if args.reload:
        from appeals.web import reload
        return reload.run(['serve', '--host', args.host, '--port', str(args.port), '--no-reload'])
    from appeals.web.server import serve
    serve(_settings(args), host=args.host, port=args.port)


def cmd_release(args):
    from appeals.release.build import BuildError, build
    from appeals.release.read import Releases
    settings = _settings(args)
    store = Store(settings.db, read_only=True)
    try:
        meta = build(store, args.run, settings.releases, test=args.test, tags=args.tag or [])
    except BuildError as error:
        sys.exit(f'No release built: {error}')
    p = meta['population']
    print(f'{p["dockets"]} dockets: {p["in_scope"]} in scope, {p["out_of_scope"]} out of scope, '
          f'{p["failed"]} failed, {p["not_run"]} not run')
    if args.publish:
        Releases(settings.releases).publish(meta['id'])
        print(f'release {meta["id"]} is now current')
    else:
        print(f'publish it with: make publish RELEASE={meta["id"]}')


def cmd_releases(args):
    from appeals.release.read import Releases
    summaries = Releases(_settings(args).releases).summaries(tag=args.tag)
    for r in summaries:
        print(_release_line(r))
    if not summaries:
        print('No releases' + (f' tagged {args.tag}' if args.tag else ''))


def _release_line(r):
    p = r['population']
    tags = f'  [{", ".join(r["tags"])}]' if r['tags'] else ''
    return (f'{r["id"]}  {r["created_at"][:16].replace("T", " ")} UTC  run {r["run"]}  graph {r["graph_hash"]}  '
            f'{p["dockets"]:>5} dockets  {p["in_scope"]:>5} in scope{"  current" if r["current"] else ""}{tags}')


def cmd_delete_releases(args):
    from appeals.release.read import Releases
    if bool(args.release) == bool(args.tag):
        sys.exit('Give either a release ID or --tag, not both.')
    releases = Releases(_settings(args).releases)
    chosen = [r for r in releases.summaries() if r['id'] == args.release] if args.release \
        else releases.summaries(tag=args.tag)
    if not chosen:
        sys.exit(f'No release {args.release}' if args.release else f'No releases tagged {args.tag}')
    current = [r for r in chosen if r['current']]
    if current:
        sys.exit(f'Release {current[0]["id"]} is current; publish another before deleting it.')
    print(f'Deleting {len(chosen)} release{"s" if len(chosen) != 1 else ""}:')
    for r in chosen:
        print('  ' + _release_line(r))
    if not args.yes and input('Delete? [y/N] ').strip().lower() not in ('y', 'yes'):
        sys.exit('Nothing deleted.')
    releases.delete([r['id'] for r in chosen])
    print(f'Deleted {len(chosen)} release{"s" if len(chosen) != 1 else ""}. Their runs are still in the store.')


def cmd_publish(args):
    from appeals.release.read import Releases
    try:
        Releases(_settings(args).releases).publish(args.release)
    except ValueError as error:
        sys.exit(str(error))
    print(f'release {args.release} is now current; running servers serve it from their next request')


def _site_options(args, settings):
    site = settings.site
    host = args.host or site.get('host', '0.0.0.0')
    port = args.port or int(site.get('port', 8000))
    base = site.get('base_path', '/appeals') if args.base_path is None else args.base_path
    return host, port, base


def cmd_site(args):
    from appeals.release.read import Releases
    from appeals.site.app import allowed_hosts, serve
    settings = _settings(args)
    host, port, base = _site_options(args, settings)
    hosts = allowed_hosts(settings.site.get('allowed_hosts', []), args.allowed_host or [], host, port)
    password = args.password if args.password is not None else os.environ.get('SITE_PASSWORD', '')
    serve(Releases(settings.releases), host, port, base, settings.site.get('title', 'Research data'), hosts, password)


def cmd_mcp(args):
    from appeals.release.read import Releases
    from appeals.site.mcp import make_server
    settings = _settings(args)
    make_server(Releases(settings.releases), name=settings.site.get('title', 'Research data')).run('stdio')


def cmd_mcp_check(args):
    from appeals.site.check import check
    try:
        result = check(args.url)
    except Exception as error:
        sys.exit(f'MCP check failed: {type(error).__name__}: {error}')
    print(json.dumps(result, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='appeals', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    def add(name, func, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(func=func)
        return p

    add('doctor', cmd_doctor, 'check tools and keys')
    p = add('ingest', cmd_ingest, 'download new PDFs, extract text, assign dockets')
    p.add_argument('--crawl', action='store_true', help='crawl the live listing first')
    p.add_argument('--limit', type=int, help='download at most this many PDFs')
    p = add('dockets', cmd_dockets, 'list dockets, or print one docket\'s text')
    p.add_argument('number', nargs='?')
    p.add_argument('--search')
    p.add_argument('--limit', type=int, default=50)
    add('graph', cmd_graph, 'build and validate the extraction graph; write graph.json')
    p = add('run', cmd_run, 'run the extraction graph over dockets')
    p.add_argument('--dockets', help='comma-separated docket numbers')
    p.add_argument('--limit', type=int, help='take the first N dockets (most recent first)')
    p.add_argument('--model', choices=['fake', 'live'], default='fake')
    p.add_argument('--workers', type=int)
    p.add_argument('--budget', type=float)
    p.add_argument('--tag', action='append', help='label the run, such as "scratch"; may be repeated')
    p.add_argument('--fresh-steps', action='store_true',
                   help='ask the reasoning model again instead of reusing stored step results (the scan is reused)')
    for name in ('reasoning', 'decision'):
        p.add_argument(f'--{name}-model', help='"provider/model", from a file in providers/')
        p.add_argument(f'--{name}-key', help='the API key, instead of the provider\'s environment variable')
    p = add('runs', cmd_runs, 'list runs, newest first')
    p.add_argument('--tag', help='only runs with this tag')
    p = add('delete-runs', cmd_delete_runs, 'delete one run, or every run with a tag')
    p.add_argument('run', nargs='?', help='the run ID')
    p.add_argument('--tag', help='delete every run with this tag')
    p.add_argument('--yes', action='store_true', help='don\'t ask for confirmation')
    p = add('score', cmd_score, 'compare a run with the reference answers')
    p.add_argument('run')
    p = add('serve', cmd_serve, 'serve the dashboard')
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8800)
    p.add_argument('--no-reload', dest='reload', action='store_false',
                   help='don\'t restart when the code changes (it does by default)')
    p = add('release', cmd_release, 'build a release from a finished run')
    p.add_argument('run', help='the run ID')
    p.add_argument('--test', action='store_true', help='allow a scratch, fake-model or unfinished run')
    p.add_argument('--publish', action='store_true', help='make it the current release')
    p.add_argument('--tag', action='append', help='label the release, such as "preview"; may be repeated')
    p = add('releases', cmd_releases, 'list releases, newest first')
    p.add_argument('--tag', help='only releases with this tag')
    p = add('delete-releases', cmd_delete_releases, 'delete one release, or every release with a tag')
    p.add_argument('release', nargs='?', help='the release ID')
    p.add_argument('--tag', help='delete every release with this tag')
    p.add_argument('--yes', action='store_true', help='don\'t ask for confirmation')
    p = add('publish', cmd_publish, 'make a release the current one')
    p.add_argument('release', help='the release ID')
    p = add('site', cmd_site, 'serve the public site: dashboard, API and MCP server ([site] in config.toml)')
    p.add_argument('--host', help='address to listen on, such as a VPN address')
    p.add_argument('--port', type=int)
    p.add_argument('--base-path', help='path prefix for every route, such as /appeals; "" for none')
    p.add_argument('--allowed-host', action='append', help='another Host header the MCP endpoint accepts; may repeat')
    p.add_argument('--password', help='ask for this password before the dashboard (default: SITE_PASSWORD; '
                                      'empty for none). /mcp and /healthz stay open')
    add('mcp', cmd_mcp, 'serve the MCP server on stdin and stdout, for a local client')
    p = add('mcp-check', cmd_mcp_check, 'check a running MCP endpoint end to end')
    p.add_argument('url', help='such as http://192.168.88.3:8000/appeals/mcp')

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    sys.exit(main())
