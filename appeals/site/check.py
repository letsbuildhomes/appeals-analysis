"""Check a running MCP endpoint end to end with the official client: no model calls, nothing written."""
import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

TOOLS = {'overview', 'describe', 'query', 'docket'}


def _data(result):
    if result.isError:
        raise RuntimeError(f'tool error: {result.content[0].text if result.content else "no message"}')
    return result.structuredContent


async def _check(url):
    async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                if tools != TOOLS:
                    raise RuntimeError(f'unexpected tools: {sorted(tools)}')
                overview = _data(await session.call_tool('overview', {}))
                version = overview['data']['version']
                counted = _data(await session.call_tool('query', {'sql': 'SELECT count(*) FROM appeals'}))
                if counted['rows'][0][0] != overview['coverage']['appeals_in_scope'] or counted['version'] != version:
                    raise RuntimeError('the query result does not match the overview')
                refused = await session.call_tool('query', {'sql': "SELECT * FROM read_csv('/etc/passwd')"})
                if not refused.isError:
                    raise RuntimeError('a query reading a file was not refused')
                _data(await session.call_tool('describe', {'target': 'appeals'}))
                return {'server': init.serverInfo.name, 'protocol': init.protocolVersion, 'version': version,
                        'built': overview['data']['built'], 'coverage': overview['coverage'],
                        'checks': ['initialize', 'tools', 'overview', 'query', 'file access refused', 'describe']}


def check(url):
    return asyncio.run(asyncio.wait_for(_check(url), timeout=90))
