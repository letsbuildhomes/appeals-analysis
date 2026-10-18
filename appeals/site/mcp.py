"""The MCP server: five read-only tools over the current release.

Every call reads the `current` pointer, so publishing a new release changes
what the tools serve without a restart. Older releases are deliberately not
reachable here: the public site shows them with a banner saying they are old.
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
This server publishes the current release of a research dataset that an extraction pipeline built from published \
court decisions: one row of facts per docket, for any question you want to ask of them. Call overview first: it \
says what the data is, its population, its tables, the conventions every answer follows, and what changed since \
the previous release. Then describe the tables, topics or columns you need (meaning, options, notes, a profile of what the \
data actually holds, and query tips) and query them with read-only DuckDB SQL. explain traces any column back through the \
pipeline: the questions asked, gates and thresholds, prompts and the code that combines answers. docket reads a \
few dockets in full, with their quotes: use it for individual cases, never for bulk analysis. Keep "not stated" \
separate from "no", state the population you counted, and cite the release ID with any figure."""

QUERY = (f"Run one read-only DuckDB SELECT over the release's tables (see overview and describe). Returns columns, "
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
            raise ValueError('No release is published yet.')
        return release

    @server.tool(annotations=READ_ONLY)
    def overview() -> dict[str, Any]:
        """Start here. What the data is, the release and its provenance, the population, the tables, the
        conventions every answer follows, how to work with the data, query limits, and what changed since the
        previous release."""
        return guide.overview(current(), releases.current_id())

    @server.tool(annotations=READ_ONLY)
    def describe(target: str | None = None, page: int = 1) -> dict[str, Any]:
        """Describe columns: meaning, options, notes, how each answer is settled, a profile of what the data holds
        (counts, share known, sources), and query tips. `target` is a table name, a topic such as "Units added", a field
        name such as duration, or comma-separated column names. Without a target,
        returns a compact index of every table and column. Long results are paged."""
        return guide.describe(current(), target, page)

    @server.tool(annotations=READ_ONLY)
    def explain(target: str = 'pipeline') -> dict[str, Any]:
        """How values are produced. "pipeline" describes the whole flow: layers, gates, the reasoning steps in
        order, thresholds and what the run did. A column, table or node ID (such as duration, L5a or the scan question C4)
        returns that node and everything upstream of it: scan questions and options, gates, step prompts and
        return types, the rule that settles each field, and the code of derived values."""
        return guide.explain(current(), target)

    @server.tool(annotations=READ_ONLY, description=QUERY)
    async def query(sql: str, max_rows: int = LIMITS['default_rows']) -> dict[str, Any]:
        release = current()
        return await anyio.to_thread.run_sync(partial(release.query, sql, max_rows), limiter=slots)

    @server.tool(annotations=READ_ONLY)
    async def docket(dockets: list[str], fields: list[str] | None = None) -> dict[str, Any]:
        """Read up to 10 dockets in full: every answer, list rows, where each answer came from (confidence), the
        verified quotes behind them with document and page, the court's PDF links, and linked dockets. `fields`
        (node IDs such as court_result or duration) narrows it. For individual cases only; use query for analysis."""
        release = current()
        return await anyio.to_thread.run_sync(partial(release.docket, dockets, fields), limiter=slots)

    return server
