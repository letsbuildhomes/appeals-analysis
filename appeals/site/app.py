"""The public site: one ASGI app on one port, every route under the base path.

    {base}/                          the landing page (static/index.html)
    {base}/mcp                       the MCP server, over the current release
    {base}/healthz                   which release is current
    {base}/api/releases              every release, newest first, marking the current one
    {base}/api/releases/<id>         a release's overview; `current` is false for old data
    {base}/api/releases/<id>/describe?target=&page=
    {base}/api/releases/<id>/explain?target=
    {base}/api/releases/<id>/dockets/<number>

The app mounts its own routes under the base path (such as /appeals), so a
reverse proxy forwards paths unchanged. Everything is read-only. Unlike the
MCP server, the API serves older releases too, so the dashboard can show them
with a banner saying they are not the current data.

With a password (`--password` or SITE_PASSWORD), everything but /mcp and
/healthz asks for it first; see auth.py, a temporary stopgap.
"""
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from appeals.release import guide
from appeals.release.read import QueryError
from appeals.site.auth import protect
from appeals.site.mcp import make_server

STATIC = Path(__file__).parent / 'static'


def base_path(value):
    """'' or '/name', with no trailing slash."""
    value = (value or '').strip().strip('/')
    return f'/{value}' if value else ''


def make_app(releases, base='/appeals', title='Research data', allowed_hosts=None, password=None):
    base = base_path(base)
    server = make_server(releases, name=title, streamable_http_path=f'{base}/mcp', allowed_hosts=allowed_hosts)
    mcp_app = server.streamable_http_app()
    page = (STATIC / 'index.html').read_text().replace('{{BASE}}', base).replace('{{TITLE}}', title)

    def release_or_404(request):
        release = releases.get(request.path_params['rid'])
        if release is None:
            return None, JSONResponse({'error': 'no such release'}, status_code=404)
        return release, None

    async def health(request):
        return JSONResponse({'status': 'ok', 'current_release': releases.current_id(),
                             'releases': len(releases.ids())})

    async def list_releases(request):
        return JSONResponse(releases.summaries())

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

    async def explain(request):
        release, missing = release_or_404(request)
        if missing:
            return missing
        return JSONResponse(guide.explain(release, request.query_params.get('target', 'pipeline')))

    async def docket(request):
        release, missing = release_or_404(request)
        if missing:
            return missing
        try:
            return JSONResponse(release.docket([request.path_params['number']]))
        except QueryError as error:
            return JSONResponse({'error': str(error)}, status_code=400)

    async def dashboard(request):
        return HTMLResponse(page)

    api = f'{base}/api/releases'
    routes = [
        *mcp_app.routes,
        Route(f'{base}/healthz', health),
        Route(api, list_releases),
        Route(f'{api}/{{rid}}', overview),
        Route(f'{api}/{{rid}}/describe', describe),
        Route(f'{api}/{{rid}}/explain', explain),
        Route(f'{api}/{{rid}}/dockets/{{number:path}}', docket),
        Mount(f'{base}/static', StaticFiles(directory=STATIC), name='static'),
        Route(f'{base}/', dashboard),
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


def serve(releases, host, port, base, title, hosts, password=None):
    import uvicorn
    base = base_path(base)
    print(f'Site on http://{host}:{port}{base}/  (MCP at {base}/mcp; on this network use the machine\'s address)')
    if password:
        print('The dashboard asks for the password; /mcp and /healthz stay open.')
    uvicorn.run(make_app(releases, base, title, hosts, password), host=host, port=port, proxy_headers=False,
                timeout_graceful_shutdown=10)
