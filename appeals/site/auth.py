"""A temporary shared password for the dashboard, until the site goes fully public.

One password, no usernames. Without the cookie, every dashboard, API and
static request redirects to {base}/login. The right password sets a cookie
that lasts 30 days and is renewed whenever the dashboard page loads. The
cookie holds a hash of the password, so nothing is stored on the server and
changing the password signs everyone out. The MCP endpoint and /healthz stay
open: MCP clients can't log in, and the MCP server has its own Host check.

To remove this later, delete this file and the `protect` call in app.py.
"""
import asyncio
import hashlib
import hmac
import html

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

COOKIE = 'appeals_site'
MAX_AGE = 30 * 24 * 3600
WRONG_PASSWORD_DELAY = 1.0                         # seconds; slows guessing

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="{base}/static/site.css"></head>
<body><header><h1>{title}</h1></header><main>
<form method="post" action="{base}/login" class="question" style="max-width: 24rem">
  <p><label for="password">Password</label></p>
  <p><input id="password" name="password" type="password" autofocus required style="width: 100%; padding: .4rem"></p>
  {error}
  <p><button type="submit">Enter</button></p>
</form></main></body></html>"""


def _token(password):
    return hashlib.sha256(f'appeals-site:{password}'.encode()).hexdigest()


def protect(app, password, base, title):
    """`app` behind the password; `app` itself when there is no password."""
    if not password:
        return app
    token = _token(password)
    login, open_paths = f'{base}/login', {f'{base}/mcp', f'{base}/healthz', f'{base}/static/site.css'}

    def page(error=''):
        message = f'<p style="color: #9b2c1f">{html.escape(error)}</p>' if error else ''
        return HTMLResponse(PAGE.format(title=html.escape(title), base=base, error=message))

    def grant(response):
        response.set_cookie(COOKIE, token, max_age=MAX_AGE, path=base or '/', httponly=True, samesite='lax')
        return response

    async def guarded(scope, receive, send):
        if scope['type'] != 'http' or scope['path'] in open_paths:
            return await app(scope, receive, send)
        request = Request(scope, receive)
        if scope['path'] == login:
            if request.method == 'POST':
                form = await request.form()
                if hmac.compare_digest(_token(str(form.get('password', ''))), token):
                    return await grant(RedirectResponse(f'{base}/', status_code=303))(scope, receive, send)
                await asyncio.sleep(WRONG_PASSWORD_DELAY)
                return await page('Wrong password.')(scope, receive, send)
            return await page()(scope, receive, send)
        if not hmac.compare_digest(request.cookies.get(COOKIE, ''), token):
            return await RedirectResponse(login, status_code=303)(scope, receive, send)
        if scope['path'] == f'{base}/':                    # renew the 30 days on each visit
            async def renewing(message):
                if message['type'] == 'http.response.start':
                    cookie = f'{COOKIE}={token}; Max-Age={MAX_AGE}; Path={base or "/"}; HttpOnly; SameSite=lax'
                    message = {**message, 'headers': [*message['headers'], (b'set-cookie', cookie.encode())]}
                await send(message)
            return await app(scope, receive, renewing)
        return await app(scope, receive, send)

    return guarded
