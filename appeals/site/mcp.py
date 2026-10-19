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
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from appeals.release import guide
from appeals.release.read import LIMITS

INSTRUCTIONS = """\
This server publishes a dataset of facts about appeals of Vermont town decisions about new housing, drawn from the \
published decisions of the Vermont Environmental Division: one row per appeal, for any question you want to ask \
of them. Call overview first: it says what the data is, what it covers, how it was made and how reliable it is, \
its tables, and the conventions every answer follows. Then describe the tables, topics or columns you need and \
query them with read-only DuckDB SQL. docket reads a few cases in full, with the passages of the decisions behind \
each answer. Questions are about the appeals in scope unless the user asks about other cases. Present the answers \
as what the decisions show; keep "not stated" separate from "no", say how many appeals you counted, and cite the \
version (such as v0.0.1) with any figure."""

QUERY = (f"Run one read-only DuckDB SELECT over the data's tables (see overview and describe). Returns columns, "
         f"rows and whether the result was truncated. Limits: {LIMITS['rows']} rows, {LIMITS['response_bytes']} "
         f"bytes, {LIMITS['seconds']:g} seconds. Aggregate in SQL rather than fetching rows to count them.")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def make_server(releases, name='Research data', streamable_http_path='/mcp', allowed_hosts=None):
    """The FastMCP server. `allowed_hosts`: Host header values accepted over HTTP (None: any)."""
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

    @server.tool(annotations=READ_ONLY)
    def overview() -> dict[str, Any]:
        """Start here. What the data is and which version, what it covers, how it was made and how reliable it is,
        the tables, the conventions every answer follows, how to work with the data, query limits, and what
        changed since the previous version."""
        return guide.overview(current())

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
    async def docket(dockets: list[str], fields: list[str] | None = None) -> dict[str, Any]:
        """Read up to 10 dockets in full: every answer, the lists (appellants, conditions and so on), the passages
        of the decisions behind the answers with document and page, the court's PDF links, and linked dockets.
        `fields` (field names such as court_result or duration) narrows it. A docket out of scope has only its
        scope answers. For individual cases only; use query for analysis."""
        release = current()
        return await anyio.to_thread.run_sync(partial(release.docket, dockets, fields), limiter=slots)

    return server
