import json
from pathlib import Path
import tempfile
import unittest
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
from test_context import fixture
from cata_context.cli import handler_for
from cata_context.queries import Queries
from cata_context.reader import SnapshotError, validate


def recorded():
    data = fixture()
    data["capabilities"]["history"] = True
    data["capabilities"]["query_methods"].append("playerbots.get_action_history")
    data["entities"][0]["action_history"] = {
        "available": True, "session_generation": 1, "captured_ms": 900, "captured_at_ms": 9900,
        "epoch": 1, "last_sequence": 3, "overwritten": 0, "expired": 0, "suppressed": 1,
        "retention_ms": 60000, "capacity": 64,
        "events": [{"sequence": 1, "first_sequence": 1, "first_age_ms": 100, "last_age_ms": 100, "repeats": 1,
                    "engine": "combat", "action": "attack", "kind": "rejected", "reason": "not_possible",
                    "execute_called": False, "action_return": None, "engine_result": None},
                   {"sequence": 3, "first_sequence": 3, "first_age_ms": 50, "last_age_ms": 50, "repeats": 1,
                    "engine": "combat", "action": "cast", "kind": "execution", "reason": "action_returned_false",
                    "execute_called": True, "action_return": False, "engine_result": True}]}
    return data


class ActionHistoryTests(unittest.TestCase):
    def test_http_history_pagination_and_parameter_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(recorded()), encoding="utf-8")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(Queries(path, clock=lambda: 10000)))
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/v1/bots/42/actions"
                with urlopen(url + "?after_sequence=1&limit=1") as response:
                    result = json.load(response)
                self.assertEqual([event["sequence"] for event in result["data"]["events"]], [3])
                for suffix in ("?limit=33", "?limit=1&limit=2", "?unknown=1", "?after_sequence=-1"):
                    with self.assertRaises(HTTPError) as failure:
                        urlopen(url + suffix)
                    self.assertEqual(failure.exception.code, 400)
                    failure.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_clock_mismatch_does_not_publish_unreliably_aged_history(self):
        result = self.query(recorded(), now=1000)
        self.assertEqual(result["status"], "clock_mismatch")
        self.assertIsNone(result["data"])

    def test_contradictory_return_reason_is_rejected(self):
        data = recorded()
        data["entities"][0]["action_history"]["events"][1]["reason"] = "action_returned_true"
        with self.assertRaises(SnapshotError):
            validate(data)

    def query(self, data, method="playerbots.get_action_history", now=10000, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            queries = Queries(path, clock=lambda: now)
            return queries.query(method, "42" if method != "game.get_party" else None, **kwargs)

    def test_action_return_and_engine_override_stay_distinct(self):
        result = self.query(recorded())
        events = result["data"]["events"]
        self.assertFalse(events[1]["action_return"])
        self.assertTrue(events[1]["engine_result"])
        self.assertTrue(result["data"]["historical"])
        self.assertEqual(result["data"]["suppressed"], 1)

    def test_regular_snapshots_do_not_flood_context_with_history(self):
        result = self.query(recorded(), "game.get_party")
        row = result["data"]["members"][0]
        self.assertNotIn("action_history", row)
        self.assertNotIn("events", row["action_history_summary"])

    def test_history_is_explicitly_aged_and_bounded_after_shutdown(self):
        data = recorded()
        data["server"]["status"] = "stopped"
        result = self.query(data, now=20000)
        self.assertEqual(result["status"], "stopped")
        self.assertGreater(result["data"]["events"][0]["last_age_ms"], 10000)
        self.assertEqual(self.query(data, now=80000)["data"]["events"], [])

    def test_offline_history_keeps_recorded_generation(self):
        data = recorded()
        data["entities"][0].update(state="offline", player=None, bot=None, session_generation=2)
        result = self.query(data)
        self.assertEqual(result["data"]["session_generation"], 1)
        self.assertEqual(len(result["data"]["events"]), 2)

    def test_pagination_scope_and_cursor_bounds(self):
        data = recorded()
        first = self.query(data, limit=1)
        self.assertTrue(first["data"]["more"])
        second = self.query(data, after_sequence=first["data"]["next_sequence"])
        self.assertEqual([event["sequence"] for event in second["data"]["events"]], [3])
        self.assertEqual(self.query(data, after_sequence=4)["status"], "cursor_ahead")
        with self.assertRaises(ValueError):
            self.query(data, limit=100)

    def test_legacy_or_disabled_capture_does_not_mean_no_actions(self):
        self.assertEqual(self.query(fixture())["status"], "history_unavailable")
        data = recorded()
        data["entities"][0]["action_history"].update(available=False, events=[])
        self.assertEqual(self.query(data)["status"], "history_unavailable")

    def test_malformed_or_misleading_execution_evidence_is_rejected(self):
        for mutate in (lambda e: e.update(execute_called=False), lambda e: e.update(first_age_ms=60001),
                       lambda e: e.update(sequence=0), lambda e: e.update(reason="spell_landed")):
            data = recorded()
            mutate(data["entities"][0]["action_history"]["events"][1])
            with self.assertRaises(SnapshotError):
                validate(data)
