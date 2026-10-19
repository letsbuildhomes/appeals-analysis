"""The public site: one ASGI app on one port, every route under the base path.

    {base}/                          the landing page (static/index.html)
    {base}/mcp                       the MCP server, over the current release
    {base}/healthz                   which release is current
    {base}/api/releases              every release readers can see, newest first, marking the current one
    {base}/api/releases/<id>         a release's overview; `current` is false for old data
    {base}/api/releases/<id>/describe?target=&page=
    {base}/api/releases/<id>/dockets/<number>
    {base}/<version>/                one release's appeals, to browse (such as /appeals/v0.0.2/)
    {base}/<version>/<docket>        one appeal's page: its facts, timeline, documents and quotes
    {base}/latest/...                the same, for whichever release is current
    {base}/api/versions/<version>/appeals
    {base}/api/versions/<version>/dockets/<docket>                     what a docket's page shows
    {base}/api/versions/<version>/dockets/<docket>/documents/<n>       a document's page text, to read a quote in place

The app mounts its own routes under the base path (such as /appeals), so a
reverse proxy forwards paths unchanged. Everything is read-only. Unlike the
MCP server, the API serves older releases too, so the dashboard can show them
with a banner saying they are not the current data.

With a password (`--password` or SITE_PASSWORD), everything but /mcp and
/healthz asks for it first; see auth.py, a temporary stopgap.
"""
import hashlib
import html
import json
from pathlib import Path
import re

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from appeals.release import guide, view
from appeals.release.read import QueryError
from appeals.site.auth import protect
from appeals.site.mcp import make_server

STATIC = Path(__file__).parent / 'static'


def base_path(value):
    """'' or '/name', with no trailing slash."""
    value = (value or '').strip().strip('/')
    return f'/{value}' if value else ''


def _assets_version():
    """A short hash of the static files, added to their links so browsers fetch them again after a change."""
    digest = hashlib.sha256()
    for path in sorted(STATIC.glob('*.*')):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def _template(name, base, title):
    text = (STATIC / name).read_text().replace('{{BASE}}', base).replace('{{TITLE}}', html.escape(title))
    return re.sub(r'(/static/[\w.-]+\.(?:css|js))"', rf'\1?v={_assets_version()}"', text)


def _fill(template, page_title, description, data, status=200, site_url=''):
    """A page with its title, description and data filled in. The data goes in a JSON script element, so the page
    shows without a second request."""
    data = json.dumps(data).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    body = (template.replace('{{PAGE_TITLE}}', html.escape(page_title))
            .replace('{{DESCRIPTION}}', html.escape(description, quote=True)).replace('{{DATA}}', data)
            .replace('{{SITE_URL}}', html.escape(site_url, quote=True)))
    return HTMLResponse(body, status_code=status)


def make_app(releases, base='/appeals', title='Research data', allowed_hosts=None, password=None, public_url=None):
    """`public_url` is the site's public origin, such as https://data.letsbuildhomes.org: the address that page
    links, citations and MCP links name. Without it they use the address each request came to."""
    base = base_path(base)
    site_url = f'{public_url.rstrip("/")}{base}' if public_url else None
    server = make_server(releases, name=title, streamable_http_path=f'{base}/mcp', allowed_hosts=allowed_hosts,
                         site_url=site_url)
    mcp_app = server.streamable_http_app()
    page = _template('index.html', base, title)
    docket_template = _template('docket.html', base, title)
    browse_template = _template('browse.html', base, title)

    def site(request):
        return site_url or str(request.base_url).rstrip('/') + base

    def by_version(request):
        version = request.path_params['version']
        if version == 'latest':
            return releases.current()
        return releases.by_version(version) if version[:1] in 'vV' else None

    def release_or_404(request):
        release = releases.get(request.path_params['rid'])
        if release is None:
            return None, JSONResponse({'error': 'no such release'}, status_code=404)
        return release, None

    async def health(request):
        current = releases.current()
        return JSONResponse({'status': 'ok', 'current_release': current.id if current else None,
                             'current_version': current.version if current else None,
                             'releases': len(releases.ids())})

    async def list_releases(request):
        return JSONResponse([{k: r[k] for k in ('id', 'version', 'built', 'current', 'population')}
                             for r in releases.summaries() if r['servable']])

    async def overview(request):
        release, missing = release_or_404(request)
        if missing:
            return missing
        return JSONResponse(guide.overview(release, releases.current_id()))

    async def describe(request):
        release, missing = release_or_404(request)
        if missing:
            return missing
        try:
            page_number = int(request.query_params.get('page', 1))
        except ValueError:
            page_number = 1
        return JSONResponse(guide.describe(release, request.query_params.get('target'), page_number))

    async def docket(request):
        release, missing = release_or_404(request)
        if missing:
            return missing
        try:
            return JSONResponse(release.docket([request.path_params['number']]))
        except QueryError as error:
            return JSONResponse({'error': str(error)}, status_code=400)

    async def dashboard(request):
        return HTMLResponse(page.replace('{{SITE_URL}}', html.escape(site(request), quote=True)))

    def docket_data(request):
        """(release, view) for a docket page or its API; the view says found: false for an unknown docket."""
        release = by_version(request)
        if release is None:
            return None, {'found': False, 'docket': request.path_params['docket'],
                          'version': request.path_params['version'], 'no_release': True}
        number = release.find_docket(request.path_params['docket'])
        if number is None:
            return release, {'found': False, 'docket': request.path_params['docket'], 'version': release.version,
                             'built': release.built, 'current': release.id == releases.current_id()}
        data = view.docket_page(release, number, releases.current_id(), site(request))
        current = releases.current()
        if current is not None and current.id != release.id:
            data['current_version'] = current.version
        return release, data

    async def docket_api(request):
        _, data = docket_data(request)
        return JSONResponse(data, status_code=200 if data['found'] else 404)

    async def docket_page(request):
        if request.path_params['version'] == 'latest' and releases.current() is not None:
            return RedirectResponse(f'{base}/{releases.current().version}/{request.path_params["docket"]}')
        _, data = docket_data(request)
        if not data['found']:
            return _fill(docket_template, f'Docket not found · {title}', 'No appeal with that docket number.',
                         data, 404, site(request))
        place = next((h['value'] for h in data['headline'] if h['field'] == 'municipality' and h['known']), None)
        name = ' · '.join(filter(None, [data['docket'], place]))
        summary = '; '.join(f'{h["label"]}: {h["value"]}' for h in data['headline'] if h['known'])
        return _fill(docket_template, f'{name} · {title}', f'{data.get("title") or data["docket"]}. {summary}.',
                     data, 200, site(request))

    async def document_api(request):
        release, data = docket_data(request)
        if not data['found']:
            return JSONResponse({'error': 'no such docket'}, status_code=404)
        try:
            n = int(request.path_params['n'])
        except ValueError:
            n = 0
        document = release.document(data['docket'], n)
        if document is None:
            return JSONResponse({'error': 'no such document'}, status_code=404)
        return JSONResponse(document)

    def browse_data(request):
        release = by_version(request)
        if release is None:
            return None
        data = view.appeals_list(release)
        data['current'] = release.id == releases.current_id()
        current = releases.current()
        if current is not None and current.id != release.id:
            data['current_version'] = current.version
        return data

    async def browse_api(request):
        data = browse_data(request)
        return JSONResponse(data or {'error': 'no such version'}, status_code=200 if data else 404)

    async def browse_page(request):
        if request.path_params['version'] == 'latest' and releases.current() is not None:
            return RedirectResponse(f'{base}/{releases.current().version}/')
        data = browse_data(request)
        if data is None:
            return _fill(browse_template, f'Version not found · {title}', 'No data with that version.',
                         {'missing': request.path_params['version']}, 404, site(request))
        return _fill(browse_template, f'All appeals, {data["version"]} · {title}',
                     f'Every appeal about new housing in {data["version"]}, with its own page.', data, 200, site(request))

    api = f'{base}/api/releases'
    routes = [
        *mcp_app.routes,
        Route(f'{base}/healthz', health),
        Route(api, list_releases),
        Route(f'{api}/{{rid}}', overview),
        Route(f'{api}/{{rid}}/describe', describe),
        Route(f'{api}/{{rid}}/dockets/{{number:path}}', docket),
        Route(f'{base}/api/versions/{{version}}/appeals', browse_api),
        Route(f'{base}/api/versions/{{version}}/dockets/{{docket}}', docket_api),
        Route(f'{base}/api/versions/{{version}}/dockets/{{docket}}/documents/{{n}}', document_api),
        Mount(f'{base}/static', StaticFiles(directory=STATIC), name='static'),
        Route(f'{base}/', dashboard),
        Route(f'{base}/{{version}}/', browse_page),
        Route(f'{base}/{{version}}', lambda request: RedirectResponse(f'{base}/{request.path_params["version"]}/')),
        Route(f'{base}/{{version}}/{{docket}}', docket_page),
    ]
    if base:
        routes.append(Route(base, lambda request: RedirectResponse(f'{base}/')))
    app = Starlette(routes=routes, lifespan=mcp_app.router.lifespan_context)
    return protect(app, password, base, title)      # temporary: a shared password for the dashboard


def allowed_hosts(configured, extra, host, port):
    """The Host values the MCP endpoint accepts: the configured names, any given on the command line, and the
    address the server listens on. An empty list turns the check off."""
    hosts = [*configured, *extra]
    if host not in ('0.0.0.0', '::', '') and hosts:
        hosts.append(f'{host}:{port}')
    return list(dict.fromkeys(hosts)) or None


def serve(releases, host, port, base, title, hosts, password=None, public_url=None):
    import uvicorn
    base = base_path(base)
    print(f'Site on http://{host}:{port}{base}/  (MCP at {base}/mcp; on this network use the machine\'s address)')
    if password:
        print('The dashboard asks for the password; /mcp and /healthz stay open.')
    uvicorn.run(make_app(releases, base, title, hosts, password, public_url), host=host, port=port, proxy_headers=False,
                timeout_graceful_shutdown=10)
