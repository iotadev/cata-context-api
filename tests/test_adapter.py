"""Independent release regressions; synthetic observations, never live evidence."""
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from adapter_fixture import fixture

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "RELEASE-PROFILE.json").read_text())
PACKAGE = PROFILE["package"]
BUILD = PROFILE["build"]
Queries = importlib.import_module(PACKAGE + ".queries").Queries
reader = importlib.import_module(PACKAGE + ".reader")


def observation(build=BUILD, now=10000):
    data = fixture(now)
    if build == 12340:
        data["server"].update(client_build=12340, expansion="wotlk", core="AzerothCore")
        row = data["entities"][0]
        row["player"]["origin"] = "unknown"
        row["bot"] = dict(kind="wotlk_ai_attachment_v1", ai_attached=True, control_mode="self", controller_guid="42")
    return data


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "snapshot.json"
        self.data = observation()
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def test_matching_profile_and_explicit_scope(self):
        reader.validate(self.data)
        queries = Queries(self.path, clock=lambda: 10000)
        result = queries.query("game.get_party")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["server"]["client_build"], BUILD)
        self.assertEqual(result["source"], "fixture")
        self.assertEqual(queries.query("playerbots.get_bot_state", "99")["status"], "out_of_scope")

    def test_other_expansion_is_rejected_at_all_entry_points(self):
        other = 12340 if BUILD == 15595 else 15595
        self.data = observation(other)
        self.write()
        with self.assertRaises(reader.SnapshotError):
            reader.read_snapshot(self.path)
        self.assertEqual(Queries(self.path).query("game.get_party")["status"], "unavailable")
        with self.assertRaises(reader.SnapshotError):
            reader.validate(self.data, expected_build=other)
        # Internal consumers cannot bypass the release binding either.
        core = importlib.import_module(PROFILE["core_package"] + ".queries")
        self.assertEqual(core.Queries(self.path).query("game.get_party")["status"], "unavailable")

    def test_fresh_export_cannot_refresh_old_sample(self):
        self.data["server"]["uptime_ms"] = 20000
        self.data["server"]["exported_at_ms"] = 29000
        self.write()
        result = Queries(self.path, clock=lambda: 29000).query("game.get_party")
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["data"]["members"][0]["player"])

    def test_stopped_and_missing_never_supply_live_state(self):
        self.data["server"]["status"] = "stopped"
        self.write()
        queries = Queries(self.path, clock=lambda: 10000)
        result = queries.query("game.get_party")
        self.assertEqual(result["status"], "stopped")
        self.assertIsNone(result["data"]["members"][0]["bot"])
        self.path.unlink()
        self.assertIsNone(queries.query("game.get_party")["data"])

    def test_cli_uses_this_profile(self):
        self.data = observation(now=time.time_ns() // 1000000)
        self.write()
        result = subprocess.run([sys.executable, "-m", PACKAGE, "--snapshot", str(self.path), "--json", "party"],
                                capture_output=True, text=True, cwd=ROOT, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["server"]["client_build"], BUILD)

    def test_common_source_fingerprints_match(self):
        import hashlib
        manifest = json.loads((ROOT / "SHARED-SOURCE.json").read_text())
        for name, expected in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / PROFILE["core_package"] / name).read_bytes()).hexdigest(), expected, name)

    def test_distributed_module_is_disabled(self):
        template = (ROOT / "server-module/conf/context-api.conf.dist").read_text()
        self.assertIn("ContextAPI.Enabled = 0", template)


HAS_MCP = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(HAS_MCP, "Optional MCP dependency not installed")
class AdapterMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_both_handshakes_preserve_expansion_binding(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            parameters = StdioServerParameters(command=sys.executable,
                args=["-m", PACKAGE + ".mcp_server", "--snapshot", str(path)], cwd=ROOT)
            for mode in ("auto", "legacy"):
                data = observation(now=time.time_ns() // 1000000)
                path.write_text(json.dumps(data))
                async with Client(parameters, mode=mode, read_timeout_seconds=15) as client:
                    tools = (await client.list_tools()).tools
                    self.assertEqual(len(tools), 5)
                    self.assertTrue(all(tool.annotations.read_only_hint for tool in tools))
                    capabilities = f"{PROFILE['profile']}_get_capabilities"
                    self.assertIn(capabilities, {tool.name for tool in tools})
                    result = await client.call_tool("game_get_party", {})
                    self.assertEqual(result.structured_content["server"]["client_build"], BUILD)
                    data = observation(12340 if BUILD == 15595 else 15595)
                    path.write_text(json.dumps(data))
                    rejected = await client.call_tool("game_get_party", {})
                    self.assertEqual(rejected.structured_content["status"], "unavailable")
