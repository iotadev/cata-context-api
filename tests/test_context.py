import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cata_context.cli import handler_for
from cata_context.queries import Queries
from cata_context.reader import SnapshotError, read_snapshot


def fixture(now=10_000):
    # Deliberately marked fixture: these are reader tests, not realm evidence.
    player = {"name": "Testbot", "origin": "server", "group_guid": "900", "selected_target_guid": "700",
              "alive": True, "in_combat": False, "map_id": 1, "instance_id": 0,
              "health": {"current": 100, "max": 100}, "power": {"type": 0, "current": 40, "max": 100},
              "position": {"x": 1.0, "y": 2.0, "z": 3.0, "orientation": 0.0}}
    return {"schema_version": 1, "source": "fixture",
            "server": {"boot_id": "test-boot", "status": "running", "realm_id": 1, "client_build": 15595,
                       "core_revision": "fixture", "adapter_version": "0.1.0", "started_at_ms": now - 1000,
                       "exported_at_ms": now, "uptime_ms": 1000, "sequence": 1, "sample_interval_ms": 1000},
            "scope": {"characters": ["42"], "roster_complete": False},
            "capabilities": {"query_methods": ["context.get_capabilities", "game.get_party", "playerbots.get_bot_state"],
                             "control": False, "history": False},
            "entities": [{"guid": "42", "session_generation": 1, "state": "online", "sampled_ms": 900,
                          "sampled_at_ms": now - 100, "player": player,
                          "bot": {"available": True, "controller_guid": "43", "follow_target_guid": "43",
                                  "attack_requested": False, "role_mask": 0, "staying": False,
                                  "engine_state": "noncombat", "last_executed_action": "follow", "queued_count": 0,
                                  "combat_strategies": ["tank"], "noncombat_strategies": ["food"]}}]}


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "snapshot.json"
        self.data = fixture()
        self.write()
        self.queries = Queries(self.path, clock=lambda: 10_000)

    def write(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def member(self):
        return self.queries.query("game.get_party")["data"]["members"][0]

    def test_party_is_scoped_and_not_claimed_complete(self):
        result = self.queries.query("game.get_party")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "fixture")
        self.assertFalse(result["data"]["scope"]["roster_complete"])
        self.assertEqual(result["data"]["observed_groups"], {"900": ["42"]})
        self.assertEqual(self.member()["availability"], "current")

    def test_fresh_export_does_not_make_an_old_entity_current(self):
        self.data["server"]["uptime_ms"] = 20_000
        self.write()
        row = self.member()
        self.assertEqual(row["availability"], "stale")
        self.assertIsNone(row["player"])
        self.assertIsNone(row["bot"])

    def test_stopped_server_never_returns_live_fields(self):
        self.data["server"]["status"] = "stopped"
        self.write()
        result = self.queries.query("playerbots.get_bot_state", "42")
        self.assertEqual(result["status"], "stopped")
        self.assertIsNone(result["data"]["bot"])

    def test_crashed_exporter_becomes_stale(self):
        self.queries.clock = lambda: 16_000
        result = self.queries.query("game.get_party")
        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["data"]["members"][0]["player"])

    def test_logout_and_relogin_do_not_reuse_old_fields(self):
        row = self.data["entities"][0]
        row.update(state="offline", session_generation=2, player=None, bot=None)
        self.write()
        self.assertEqual(self.member()["availability"], "offline")
        row.update(state="awaiting_sample", session_generation=3)
        self.write()
        self.assertEqual(self.member()["availability"], "awaiting_sample")
        self.assertIsNone(self.member()["player"])

    def test_unobserved_is_not_offline(self):
        row = self.data["entities"][0]
        row.update(state="unobserved", session_generation=0, sampled_ms=0, sampled_at_ms=0, player=None, bot=None)
        self.write()
        self.assertEqual(self.member()["availability"], "unobserved")

    def test_scope_and_client_origin_are_enforced(self):
        self.assertEqual(self.queries.query("playerbots.get_bot_state", "99")["status"], "out_of_scope")
        row = self.data["entities"][0]
        row["player"]["origin"] = "client"
        row["bot"] = None
        self.write()
        self.assertEqual(self.queries.query("playerbots.get_bot_state", "42")["status"], "not_a_bot")

    def test_strategy_role_flags_exclude_other_strategy_bits(self):
        self.data["entities"][0]["bot"]["role_mask"] = 68
        self.write()
        row = self.queries.query("playerbots.get_bot_state", "42")["data"]
        self.assertEqual(row["bot"]["observed_roles"], ["tank"])
        self.data["entities"][0]["bot"] = {"available": False, "role_mask": 0,
                                           "controller_guid": None, "follow_target_guid": None, "attack_requested": False}
        self.write()
        row = self.queries.query("playerbots.get_bot_state", "42")["data"]
        self.assertIsNone(row["bot"]["observed_roles"])

    def test_future_clock_is_explicit(self):
        self.queries.clock = lambda: 1000
        result = self.queries.query("game.get_party")
        self.assertEqual(result["status"], "clock_mismatch")
        self.assertIsNone(result["data"]["members"][0]["player"])

    def test_corrupted_file_is_not_hidden_by_cached_success(self):
        self.assertEqual(self.queries.query("game.get_party")["status"], "ok")
        self.path.write_text('{"schema_version":1,', encoding="utf-8")
        self.assertEqual(self.queries.query("game.get_party")["status"], "unavailable")
        self.path.unlink()
        self.assertEqual(self.queries.query("game.get_party")["status"], "unavailable")

    def test_identity_schema_and_scope_errors_are_rejected(self):
        for mutate in (lambda d: d.update(schema_version=2),
                       lambda d: d["server"].update(client_build=12340),
                       lambda d: d["entities"][0].update(guid="43"),
                       lambda d: d["entities"][0].update(guid="042"),
                       lambda d: d["entities"][0]["player"]["position"].update(x=float("nan")),
                       lambda d: d["entities"][0].update(state="offline"),
                       lambda d: d["scope"]["characters"].append("42")):
            with self.subTest(mutation=mutate):
                self.data = fixture()
                mutate(self.data)
                self.write()
                with self.assertRaises(SnapshotError):
                    read_snapshot(self.path)

    def test_duplicate_keys_and_oversize_input_are_rejected(self):
        self.path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(SnapshotError):
            read_snapshot(self.path)
        self.path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(SnapshotError):
            read_snapshot(self.path)

    def test_oversized_query_is_explicit_and_not_silently_truncated(self):
        self.data["entities"][0]["diagnostic_extension"] = "x" * 70000
        self.write()
        result = self.queries.query("game.get_party")
        self.assertEqual(result["status"], "too_large")
        self.assertIsNone(result["data"])

    def test_invalid_unicode_is_rejected_before_presentation(self):
        self.data["entities"][0]["player"]["name"] = "\ud800"
        self.write()
        self.assertEqual(self.queries.query("game.get_party")["status"], "unavailable")

    def test_atomic_replacement_survives_concurrent_reads(self):
        errors = []
        def write_versions():
            try:
                for sequence in range(2, 102):
                    data = fixture()
                    data["server"]["sequence"] = sequence
                    temporary = self.path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(data), encoding="utf-8")
                    if os.name == "nt":
                        # Exercise the same native replacement as the C++ exporter.
                        import ctypes
                        from ctypes import wintypes
                        replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
                        replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                            wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
                        replace.restype = wintypes.BOOL
                        if not replace(str(self.path), str(temporary), None, 0, None, None):
                            raise ctypes.WinError(ctypes.get_last_error())
                    else:
                        os.replace(temporary, self.path)
            except Exception as error:
                errors.append(traceback.format_exc())
        writer = threading.Thread(target=write_versions)
        writer.start()
        try:
            for _ in range(100):
                result = self.queries.query("game.get_party")
                # An artificial 100-swap burst can exceed the Windows bounded
                # retry budget. Complete success or explicit unavailability is
                # acceptable; a partial record or cached success is not.
                self.assertIn(result["status"], ("ok", "unavailable"), result)
                if result["status"] == "unavailable":
                    self.assertIsNone(result["data"])
                else:
                    self.assertEqual(result["data"]["members"][0]["availability"], "current")
        finally:
            writer.join()
        self.assertFalse(errors)
        self.assertEqual(self.queries.query("game.get_party")["status"], "ok")

    def test_http_reads_and_rejects_mutation(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.queries))
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            with urlopen(url + "/v1/bots/42") as response:
                self.assertEqual(json.load(response)["data"]["bot"]["last_executed_action"], "follow")
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(url + "/v1/party", data=b"{}", method="POST"))
            self.assertEqual(failure.exception.code, 501)
            self.data["entities"][0]["player"]["name"] = "<script>alert(1)</script>"
            self.write()
            with urlopen(url) as response:
                page = response.read().decode()
            self.assertIn("&lt;script&gt;", page)
            self.assertNotIn("<script>", page)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_cli_uses_the_same_query_contract(self):
        self.data = fixture(time.time_ns() // 1_000_000)
        self.write()
        result = subprocess.run([sys.executable, "-m", "cata_context", "--snapshot", str(self.path), "--json", "party"],
                                capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["data"]["members"][0]["availability"], "current")


if __name__ == "__main__":
    unittest.main()
