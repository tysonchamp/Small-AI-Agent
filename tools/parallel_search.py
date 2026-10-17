"""Anonymous Parallel Search MCP transport for the existing web-search tool."""
import asyncio
import logging
import math
from datetime import timedelta

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


MCP_URL = "https://search.parallel.ai/mcp"
USER_AGENT = "Small-AI-Agent/1.0 (+https://github.com/tysonchamp/Small-AI-Agent)"


async def _search(query, timeout):
    # The deadline covers discovery, execution and transport cleanup together.
    with anyio.fail_after(timeout):
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with streamable_http_client(MCP_URL, http_client=client) as streams:
                async with ClientSession(
                    streams[0], streams[1],
                    read_timeout_seconds=timedelta(seconds=timeout),
                ) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    if not any(t.name == "web_search" for t in tools.tools):
                        raise RuntimeError("Parallel MCP does not offer web_search.")
                    result = await session.call_tool(
                        "web_search",
                        {"objective": query, "search_queries": [query]},
                    )

    text = "\n".join(
        block.text for block in result.content if block.type == "text"
    )
    if result.isError:
        raise RuntimeError(f"Parallel search failed: {text or 'MCP tool error'}")
    if not text.strip():
        raise RuntimeError("Parallel search returned no text results.")
    return text


def search(query, timeout=30):
    """Run in the assistant's existing executor, with a bounded MCP deadline."""
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 0 < timeout <= 120):
        raise ValueError("search.timeout_seconds must be a number above 0 and at most 120.")
    try:
        return asyncio.run(_search(query, timeout))
    except TimeoutError as exc:
        raise RuntimeError(f"Parallel search timed out after {timeout:g} seconds.") from exc
    except RuntimeError:
        raise
    except Exception as exc:
        logging.exception("Parallel Search MCP transport failed")
        raise RuntimeError(
            "Parallel search could not connect or complete the request. Please try again later."
        ) from exc
