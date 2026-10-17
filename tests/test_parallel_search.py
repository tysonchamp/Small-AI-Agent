"""Actual registry/agent tests with scripted model and MCP network responses."""
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import yaml

from core import agent
from tools import parallel_search
from tools import web_search as search_tools


SOURCE_URL = "https://www.python.org/downloads/"
SEARCH_TEXT = json.dumps({"results": [{
    "title": "Python releases", "url": SOURCE_URL,
    "excerpts": ["Download current Python releases."],
}]})
REAL_CLIENT = httpx.AsyncClient


class ScriptedModel:
    """No live inference: exercise the normal router and synthesis consumer."""
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if prompt.startswith("You are a tool router"):
            text = json.dumps({"tool": "web_search", "params": {
                "query": "Python release news",
            }})
        else:
            text = f"Current Python releases: {SOURCE_URL}"
        return SimpleNamespace(content=text)


class ParallelSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "config.yaml"
        self.configure({})
        self.model = ScriptedModel()
        self.requests = []
        self.result = {"content": [{"type": "text", "text": SEARCH_TEXT}],
                       "isError": False}
        self.status = 200
        self.delay = False
        self.started = None
        self.cancelled = False
        self.clients = []
        self.tool_available = True
        for p in [patch.dict(os.environ, {}, clear=True),
                  patch("config.CONFIG_FILE", str(self.config_path)),
                  patch("core.llm.get_ollama_llm", return_value=self.model),
                  patch("core.agent.get_ollama_llm", return_value=self.model),
                  patch("tools.parallel_search.httpx.AsyncClient",
                        side_effect=self.make_client)]:
            p.start()
            self.addCleanup(p.stop)

    def configure(self, settings):
        self.config_path.write_text(yaml.safe_dump(settings))

    def make_client(self, **kwargs):
        client = REAL_CLIENT(transport=httpx.MockTransport(self.respond), **kwargs)
        self.clients.append(client)
        return client

    async def respond(self, request):
        self.requests.append(request)
        if request.method != "POST":
            return httpx.Response(405)
        body = json.loads(request.content)
        method = body["method"]
        if method.startswith("notifications/"):
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            tools = [{"name": "web_search", "inputSchema": {"type": "object"}}]
            result = {"tools": tools if self.tool_available else []}
        elif method == "tools/call":
            if self.started is not None:
                self.started.set()
            if self.delay:
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled = True
            if self.status != 200:
                return httpx.Response(self.status, text="service unavailable")
            result = self.result
        else:
            raise AssertionError(f"Unexpected method: {method}")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                         "result": result})

    def run_agent(self):
        # Use the actual complete tool registry; unrelated tools aren't invoked.
        runtime = agent.create_agent()
        self.assertIn("web_search", runtime._tool_map)
        return runtime.invoke({"input": "Search web for Python release news"})["output"]

    def test_parallel_through_registry_router_and_synthesis(self):
        self.configure({"search": {"provider": "parallel"}})
        # Ambient API keys must neither select a provider nor become auth headers.
        with patch.dict(os.environ, {"PARALLEL_API_KEY": "unused-test-key"}):
            self.assertIn(SOURCE_URL, self.run_agent())
        self.assertIn(SEARCH_TEXT, self.model.prompts[-1])
        self.assertTrue(self.clients[0].is_closed)
        messages = [json.loads(r.content) for r in self.requests if r.method == "POST"]
        self.assertEqual([m["method"] for m in messages], [
            "initialize", "notifications/initialized", "tools/list", "tools/call",
        ])
        self.assertEqual(messages[-1]["params"], {
            "name": "web_search", "arguments": {
                "objective": "Python release news",
                "search_queries": ["Python release news"],
            },
        })
        for request in self.requests:
            self.assertEqual(str(request.url), parallel_search.MCP_URL)
            self.assertEqual(request.headers["user-agent"], parallel_search.USER_AGENT)
            self.assertNotIn("authorization", request.headers)

    def test_default_and_saved_duckduckgo_do_not_use_mcp(self):
        for settings in [{}, {"search": {"provider": "duckduckgo"}}]:
            with self.subTest(settings=settings):
                self.configure(settings)
                with patch("ddgs.DDGS") as ddgs, patch.dict(
                    os.environ, {"PARALLEL_API_KEY": "unused-test-key"}
                ):
                    ddgs.return_value.text.return_value = [{
                        "title": "Python", "href": SOURCE_URL, "body": "Release news",
                    }]
                    self.assertIn(SOURCE_URL, self.run_agent())
                    ddgs.return_value.text.assert_called_once_with(
                        "Python release news", max_results=5
                    )
        self.assertEqual(self.requests, [])

    def test_environment_overrides_saved_provider(self):
        self.configure({"search": {"provider": "duckduckgo"}})
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "parallel"}):
            self.assertIn(SOURCE_URL, self.run_agent())
        self.configure({"search": {"provider": "parallel"}})
        self.requests.clear()
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "duckduckgo"}), patch(
            "ddgs.DDGS"
        ) as ddgs:
            ddgs.return_value.text.return_value = []
            self.run_agent()
        self.assertEqual(self.requests, [])

    def test_disabled_search_blocks_network_and_synthesis(self):
        self.configure({"search": {"provider": "parallel", "enabled": False}})
        with patch.dict(os.environ, {"WEB_SEARCH_PROVIDER": "parallel"}):
            self.assertIn("disabled", self.run_agent())
        self.assertEqual(len(self.model.prompts), 1)  # Routing only.
        self.assertEqual(self.requests, [])

    def test_unknown_provider_is_not_silently_replaced(self):
        self.configure({"search": {"provider": "typo"}})
        self.assertIn("Unknown web search provider", self.run_agent())
        self.assertEqual(self.requests, [])
        self.assertEqual(len(self.model.prompts), 1)

    def test_tool_error_is_not_synthesized_or_retried(self):
        self.configure({"search": {"provider": "parallel"}})
        self.result = {"content": [{"type": "text", "text": "Anonymous quota reached"}],
                       "isError": True}
        with patch("ddgs.DDGS") as ddgs:
            self.assertIn("Anonymous quota reached", self.run_agent())
            ddgs.assert_not_called()
        self.assertEqual(len(self.model.prompts), 1)
        self.assertTrue(all(c.is_closed for c in self.clients))

    def test_empty_result_and_missing_tool_fail(self):
        self.configure({"search": {"provider": "parallel"}})
        self.result = {"content": [], "isError": False}
        self.assertIn("no text results", self.run_agent())
        self.tool_available = False
        self.assertIn("Search failed", self.run_agent())
        self.assertTrue(all(c.is_closed for c in self.clients))

    def test_http_error_is_not_synthesized_or_retried(self):
        self.configure({"search": {"provider": "parallel"}})
        self.status = 503
        self.assertIn("Search failed", self.run_agent())
        calls = [r for r in self.requests if b'"tools/call"' in r.content]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.model.prompts), 1)
        self.assertTrue(self.clients[0].is_closed)

    def test_timeout_closes_transport(self):
        self.configure({"search": {"provider": "parallel", "timeout_seconds": 0.05}})
        self.delay = True
        self.assertIn("timed out", self.run_agent())
        self.assertTrue(self.cancelled)
        self.assertTrue(self.clients[0].is_closed)
        self.assertEqual(len(self.model.prompts), 1)

    def test_async_cancellation_closes_transport(self):
        async def check():
            self.started = asyncio.Event()
            self.delay = True
            task = asyncio.create_task(parallel_search._search("Python releases", 5))
            await asyncio.wait_for(self.started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(check())
        self.assertTrue(self.cancelled)
        self.assertTrue(self.clients[0].is_closed)

    def test_invalid_deadlines_and_empty_query_do_not_send(self):
        for timeout in [0, -1, 121, True, "30", float("nan"), float("inf")]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                parallel_search.search("query", timeout)
        with self.assertRaises(ValueError):
            search_tools.perform_web_search("  ")
        self.assertEqual(self.requests, [])

    def test_missing_optional_dependency_has_setup_hint(self):
        self.configure({"search": {"provider": "parallel"}})
        with patch.dict("sys.modules", {"tools.parallel_search": None}):
            self.assertIn("requirements-parallel.txt", self.run_agent())
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
