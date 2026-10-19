"""The MCP server: four read-only tools over the current release.

Every call reads the `current` pointer, so publishing a new release changes
what the tools serve without a restart. Older releases are deliberately not
reachable here: the public site shows them with a banner saying they are old.
The tools speak about the data, not the pipeline: facts, their meanings and
the passages behind them, named by version and date.
"""
from functools import partial
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from appeals.release import guide
from appeals.release.read import LIMITS
from appeals.release.view import page_address

INSTRUCTIONS = """\
This server publishes a dataset of facts about appeals of Vermont town decisions about new housing, drawn from the \
published decisions of the Vermont Environmental Division: one row per appeal, for any question you want to ask \
of them. Call overview first: it says what the data is, what it covers, how it was made and how reliable it is, \
its tables, and the conventions every answer follows. Then describe the tables, topics or columns you need and \
query them with read-only DuckDB SQL. docket reads a few cases in full, with the passages of the decisions behind \
each answer. Questions are about the appeals in scope unless the user asks about other cases. Present the answers \
as what the decisions show; keep "not stated" separate from "no", say how many appeals you counted, and cite the \
version (such as v0.0.1) with any figure. Every appeal has its own web page showing all of its facts with the \
quoted passages, each linked to its page of the decision: docket returns its address as page_url, and overview \
gives the pattern. Whenever you discuss particular cases, link each to its page so the user can read and check it."""

QUERY = (f"Run one read-only DuckDB SELECT over the data's tables (see overview and describe). Returns columns, "
         f"rows and whether the result was truncated. Limits: {LIMITS['rows']} rows, {LIMITS['response_bytes']} "
         f"bytes, {LIMITS['seconds']:g} seconds. Aggregate in SQL rather than fetching rows to count them.")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def make_server(releases, name='Research data', streamable_http_path='/mcp', allowed_hosts=None, site_url=None):
    """The FastMCP server. `allowed_hosts`: Host header values accepted over HTTP (None: any). `site_url` is the
    public site's address with its base path, such as https://data.letsbuildhomes.org/appeals, for links to
    docket pages; without it, links use the address the request came to, and over stdio there are none."""
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if allowed_hosts:
        names = [h.split(':')[0] for h in allowed_hosts]
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=list(allowed_hosts),
            allowed_origins=[f'{scheme}://{h}' for h in {*allowed_hosts, *names} for scheme in ('http', 'https')])
    server = FastMCP(name, instructions=INSTRUCTIONS, streamable_http_path=streamable_http_path,
                     json_response=True, stateless_http=True, transport_security=security)
    slots = anyio.CapacityLimiter(4)

    def current():
        release = releases.current()
        if release is None:
            raise ValueError('No data is published yet.')
        return release

    def site(ctx):
        if site_url:
            return site_url.rstrip('/')
        request = getattr(ctx.request_context, 'request', None) if ctx else None
        if request is None:
            return None
        return str(request.base_url).rstrip('/') + streamable_http_path.removesuffix('/mcp')

    def with_pages(out, ctx):
        """Adds each docket's page address, so the assistant can link the user to the case."""
        base = site(ctx)
        if base:
            for entry in out.get('dockets', []):
                if entry.get('found'):
                    entry['page_url'] = page_address(base, out['version'], entry['docket'])
        return out

    @server.tool(annotations=READ_ONLY)
    def overview(ctx: Context) -> dict[str, Any]:
        """Start here. What the data is and which version, what it covers, how it was made and how reliable it is,
        the tables, the conventions every answer follows, how to work with the data, query limits, what changed
        since the previous version, and where each appeal's web page is."""
        release = current()
        out = guide.overview(release)
        base = site(ctx)
        if base:
            out['web_pages'] = guide.web_pages(release, base)
        return out

    @server.tool(annotations=READ_ONLY)
    def describe(target: str | None = None, page: int = 1) -> dict[str, Any]:
        """Describe columns: meaning, options, notes, a profile of what the data holds (counts and how many are
        known), and query tips. `target` is a table name, a topic such as "Units added", a field name such as
        duration, or comma-separated column names. Without a target, returns a compact index of every table and
        column. Long results are paged."""
        return guide.describe(current(), target, page)

    @server.tool(annotations=READ_ONLY, description=QUERY)
    async def query(sql: str, max_rows: int = LIMITS['default_rows']) -> dict[str, Any]:
        release = current()
        return await anyio.to_thread.run_sync(partial(release.query, sql, max_rows), limiter=slots)

    @server.tool(annotations=READ_ONLY)
    async def docket(dockets: list[str], ctx: Context, fields: list[str] | None = None) -> dict[str, Any]:
        """Read up to 10 dockets in full: every answer, the lists (appellants, conditions and so on), the passages
        of the decisions behind the answers with document and page, the court's PDF links, linked dockets, and
        page_url, the docket's web page, which shows all of this with each quote linked to its page of the
        decision: give it to the user. `fields` (field names such as court_result or duration) narrows it. A
        docket out of scope has only its scope answers. For individual cases only; use query for analysis."""
        release = current()
        out = await anyio.to_thread.run_sync(partial(release.docket, dockets, fields), limiter=slots)
        return with_pages(out, ctx)

    return server
