"""Command line: `appeals <command>`. The Makefile wraps the common ones."""
import argparse
import asyncio
from datetime import date
import json
import sys

from appeals import config
from appeals.store import Store


def _settings(args):
    overrides = {
        'workers': getattr(args, 'workers', None),
        'budget_usd': getattr(args, 'budget', None),
        'reasoning.format': getattr(args, 'reasoning_format', None),
        'reasoning.base_url': getattr(args, 'reasoning_base_url', None),
        'reasoning.model': getattr(args, 'reasoning_model', None),
        'reasoning.key': getattr(args, 'reasoning_key', None),
        'decision.base_url': getattr(args, 'decision_base_url', None),
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
        endpoint = getattr(settings, name)
        print(f'{"ok " if endpoint.key else "-- "} {name} key ({endpoint.key_env}) for {endpoint.format} {endpoint.model}')
        year = date.today().year
        if not endpoint.holidays_cover(year):
            print(f'-- {name} off-peak calendar lists no holidays for {year}; those days are priced as peak')


def cmd_ingest(args):
    from appeals.ingest import dockets, listing, pdfs, text
    settings = _settings(args)
    store = Store(settings.db)
    if args.crawl:
        folder = listing.crawl(settings)
        entries = listing.read_snapshot(folder)
        store.add_listing_entries(entries)
        print(f'Listing: {len(entries)} entries saved to {folder}')
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
        decision, reasoning = endpoints.decision_model(settings.decision), endpoints.reasoning_model(settings.reasoning)
    numbers = _pick_dockets(store, args)
    runner = Runner(pipeline, store, settings, decision, reasoning)
    run_id = asyncio.run(runner.run(numbers, workers=settings.workers, tags=args.tag or []))
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
    model = (json.loads(r['endpoints']) if r['endpoints'] else {}).get('reasoning', {}).get('model', '')
    return (f'{r["id"]}  {r["started_at"]:%Y-%m-%d %H:%M}  {r["dockets"]:>5} dockets  {r["status"]:<17} '
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
    from appeals.web.server import serve
    serve(_settings(args), host=args.host, port=args.port)


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
    for name in ('reasoning', 'decision'):
        for key in ('format', 'base-url', 'model', 'key'):
            if name == 'decision' and key == 'format':
                continue
            p.add_argument(f'--{name}-{key}')
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

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    sys.exit(main())
