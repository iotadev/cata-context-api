"""Protocol-level adapter tests; fixtures are never live realm evidence."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from test_context import fixture
from test_action_history import recorded
from cata_context.queries import Queries


HAS_MCP = importlib.util.find_spec("mcp") is not None
if HAS_MCP:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    from cata_context.mcp_server import create_server


@unittest.skipUnless(HAS_MCP, 'Install the optional ".[mcp]" dependencies to test MCP.')
class McpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "snapshot.json"
        self.now = 10000
        self.data = fixture()
        self.write()
        self.queries = Queries(self.path, clock=lambda: self.now)
        self.server = create_server(self.queries)

    def write(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    async def test_discovery_exposes_only_five_read_only_tools_and_two_resources(self):
        async with Client(self.server) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, {
                "cata_get_capabilities", "game_get_party", "playerbots_get_bot_state", "playerbots_get_action_history", "modules_get_observations"})
            for tool in tools:
                self.assertTrue(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.destructive_hint)
                self.assertFalse(tool.annotations.open_world_hint)
                self.assertNotIn("snapshot", tool.input_schema.get("properties", {}))
            resources = (await client.list_resources()).resources
            self.assertEqual({str(resource.uri) for resource in resources}, {"cata://contract", "cata://capabilities"})
            guide = (await client.read_resource("cata://contract")).contents[0].text
            self.assertIn("not evidence of client", guide)

    async def test_tools_preserve_semantic_data_and_history_limits(self):
        self.data = recorded()
        self.write()
        async with Client(self.server) as client:
            party = await client.call_tool("game_get_party", {})
            self.assertFalse(party.is_error)
            self.assertEqual(party.structured_content, self.queries.query("game.get_party"))
            self.assertNotIn("events", party.structured_content["data"]["members"][0]["action_history_summary"])
            bot = await client.call_tool("playerbots_get_bot_state", {"guid": "42"})
            self.assertEqual(bot.structured_content["data"]["player"]["name"], "Testbot")
            result = await client.call_tool("playerbots_get_action_history", {"guid": "42", "after_sequence": 1, "limit": 1})
            history = result.structured_content["data"]
            self.assertEqual([event["sequence"] for event in history["events"]], [3])
            self.assertFalse(history["events"][0]["action_return"])
            self.assertTrue(history["events"][0]["engine_result"])
            self.assertTrue(history["historical"])

    async def test_stale_stopped_and_unavailable_remain_semantic_statuses(self):
        async with Client(self.server) as client:
            fresh = await client.call_tool("game_get_party", {})
            self.assertEqual(fresh.structured_content["status"], "ok")
            self.now = 20000
            stale = await client.call_tool("game_get_party", {})
            self.assertFalse(stale.is_error)
            self.assertEqual(stale.structured_content["status"], "stale")
            self.assertIsNone(stale.structured_content["data"]["members"][0]["player"])
            self.data["server"]["status"] = "stopped"
            self.write()
            stopped = await client.call_tool("game_get_party", {})
            self.assertEqual(stopped.structured_content["status"], "stopped")
            self.assertIsNone(stopped.structured_content["data"]["members"][0]["bot"])
            self.path.write_text('{"partial":', encoding="utf-8")
            missing = await client.call_tool("game_get_party", {})
            self.assertEqual(missing.structured_content["status"], "unavailable")
            self.assertIsNone(missing.structured_content["data"])

    async def test_resources_and_capabilities_read_updated_captures(self):
        async with Client(self.server) as client:
            result = await client.call_tool("cata_get_capabilities", {})
            self.assertEqual(result.structured_content["source"], "fixture")
            self.assertFalse(result.structured_content["data"]["control"])
            self.data["server"]["status"] = "stopped"
            self.write()
            resource = await client.read_resource("cata://capabilities")
            self.assertEqual(json.loads(resource.contents[0].text)["status"], "stopped")
            self.path.unlink()
            resource = await client.read_resource("cata://capabilities", cache_mode="bypass")
            self.assertEqual(json.loads(resource.contents[0].text)["status"], "unavailable")

    async def test_invalid_arguments_and_unknown_controls_do_not_reach_gameplay(self):
        async with Client(self.server) as client:
            for arguments in ({"guid": 42}, {"guid": "../secret"}, {"guid": "18446744073709551616"},
                              {"guid": "42", "limit": 33}, {"guid": "42", "limit": True},
                              {"guid": "42", "after_sequence": -1}):
                result = await client.call_tool("playerbots_get_action_history", arguments)
                self.assertTrue(result.is_error, arguments)
            result = await client.call_tool("playerbots_set_strategy", {"guid": "42", "strategy": "tank"})
            self.assertTrue(result.is_error)
            self.assertEqual(json.loads(self.path.read_text()), self.data)

    async def test_out_of_scope_and_disabled_history_are_explicit(self):
        async with Client(self.server) as client:
            out = await client.call_tool("playerbots_get_bot_state", {"guid": "99"})
            self.assertEqual(out.structured_content["status"], "out_of_scope")
            history = await client.call_tool("playerbots_get_action_history", {"guid": "42"})
            self.assertEqual(history.structured_content["status"], "history_unavailable")

    async def test_real_stdio_subprocess_negotiates_discovers_and_reads(self):
        self.data = fixture(time.time_ns() // 1_000_000)
        self.write()
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "cata_context.mcp_server", "--snapshot", str(self.path)],
            cwd=Path(__file__).resolve().parents[1],
        )
        for mode in ("auto", "legacy"):
            with self.subTest(handshake=mode):
                self.data = fixture(time.time_ns() // 1_000_000)
                self.write()
                async with Client(parameters, read_timeout_seconds=15, mode=mode) as client:
                    self.assertEqual(client.server_info.name, "Cata Context")
                    self.assertEqual(len((await client.list_tools()).tools), 5)
                    response = await client.call_tool("game_get_party", {})
                    self.assertFalse(response.is_error)
                    self.assertEqual(response.structured_content["status"], "ok")
                    self.assertEqual(response.structured_content["source"], "fixture")
