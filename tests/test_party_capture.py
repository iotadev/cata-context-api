"""Synthetic accumulator regressions; none constitute native realm evidence."""
import unittest

from cata_context.party_capture import PartyCapture


def query(status="ok", availability="current", count=5):
    # Synthetic semantic-query shape, including its source discriminator.
    return {"source": "server", "status": status, "export_age_ms": 100,
            "server": {"boot_id": "synthetic-boot", "sequence": 2,
                       "exported_at_ms": 10000, "uptime_ms": 2000},
            "data": {"snapshot_skew_ms": 0, "members": [
                {"guid": str(index), "state": "online", "availability": availability,
                 "sample_age_ms": 100, "sampled_ms": 1900, "session_generation": 1,
                 "player": {"origin": "client" if index == 1 else "server",
                            "in_combat": True, "group_guid": "900",
                            "map_id": 389, "instance_id": 1}} for index in range(1, count + 1)]}}


class PartyCaptureTests(unittest.TestCase):
    def test_fresh_party_and_partial_scope_are_distinct(self):
        capture = PartyCapture()
        capture.observe(query(count=4), 1)
        capture.observe(query(), 2)
        report = capture.report()
        self.assertEqual(report["fresh_party_samples"], 1)
        self.assertEqual(report["same_group_instance_samples"], 1)
        self.assertTrue(report["combat_seen"])

    def test_sample_and_export_gaps_retain_their_causes(self):
        capture = PartyCapture()
        capture.observe(query(availability="stale", count=1), 1)
        capture.observe(query(status="stale", availability="server_stale", count=1), 1)
        report = capture.report()
        self.assertEqual(report["stale_online_samples"], 2)
        self.assertEqual([event["query_status"] for event in report["recent_anomalies"]], ["ok", "stale"])
        self.assertEqual(report["members"]["1"]["first_stale_exported_at_ms"], 10000)

    def test_anomaly_storage_is_bounded_without_losing_totals(self):
        capture = PartyCapture()
        for _ in range(100):
            capture.observe(query(availability="stale", count=1), 1)
        report = capture.report()
        self.assertEqual(len(report["recent_anomalies"]), 64)
        self.assertEqual(report["omitted_anomaly_observations"], 36)
        self.assertEqual(report["members"]["1"]["stale_samples"], 100)

    def test_stopped_and_offline_are_not_stale_online(self):
        capture = PartyCapture()
        result = query(status="stopped", availability="server_stopped", count=1)
        result["data"]["members"][0]["state"] = "offline"
        capture.observe(result, 1)
        report = capture.report()
        self.assertTrue(report["server_stopped"])
        self.assertTrue(report["members"]["1"]["offline_seen"])
        self.assertEqual(report["stale_online_samples"], 0)

    def test_replacement_boot_is_rejected(self):
        capture = PartyCapture()
        capture.observe(query(), 1)
        result = query()
        result["server"]["boot_id"] = "replacement"
        with self.assertRaises(ValueError):
            capture.observe(result, 1)

    def test_unavailable_and_fixture_inputs_do_not_become_native_evidence(self):
        capture = PartyCapture()
        capture.observe({"status": "unavailable", "data": None}, 1)
        result = query()
        result["source"] = "fixture"
        capture.observe(result, 1)
        report = capture.report()
        self.assertEqual(report["samples"], 0)
        self.assertEqual(report["query_status_counts"], {"unavailable": 1, "ok": 1})

    def test_frozen_export_uses_observer_time_and_one_publication(self):
        capture = PartyCapture()
        for elapsed in (1000, 1500, 2000):
            capture.observe(query(status="stale", availability="server_stale", count=1), 1,
                            observed_at_ms=20000 + elapsed, elapsed_ms=elapsed)
        fresh = query(count=1)
        fresh["server"]["sequence"] = 3
        capture.observe(fresh, 1, observed_at_ms=22500, elapsed_ms=2500)
        report = capture.report()
        gap = report["recent_entity_gaps"][0]
        self.assertEqual(report["distinct_publications_observed"], 2)
        self.assertEqual(gap["cause"], "export_stale")
        self.assertEqual(gap["distinct_bad_publications"], 1)
        self.assertEqual(gap["observed_bad_span_ms"], 1000)
        self.assertEqual(gap["first_bad_to_resolution_ms"], 1500)
        self.assertEqual(gap["resolution"], "recovered")

    def test_entity_gap_carries_last_fresh_context_and_ends_on_logout(self):
        capture = PartyCapture()
        capture.observe(query(count=1), 1, observed_at_ms=10000, elapsed_ms=0)
        capture.observe(query(availability="stale", count=1), 1, observed_at_ms=11000, elapsed_ms=1000)
        offline = query(availability="offline", count=1)
        offline["data"]["members"][0]["state"] = "offline"
        capture.observe(offline, 1, observed_at_ms=12000, elapsed_ms=2000)
        gap = capture.report()["recent_entity_gaps"][0]
        self.assertEqual(gap["cause"], "entity_sample_stale")
        self.assertEqual(gap["before"]["map_id"], 389)
        self.assertEqual(gap["resolution"], "offline")
        self.assertIsNone(gap["after"])

    def test_generation_change_does_not_attach_old_session_context(self):
        capture = PartyCapture()
        capture.observe(query(count=1), 1)
        capture.observe(query(availability="stale", count=1), 1)
        new = query(availability="stale", count=1)
        new["data"]["members"][0]["session_generation"] = 3
        capture.observe(new, 1)
        report = capture.report()
        self.assertEqual(report["recent_entity_gaps"][0]["resolution"], "session_changed")
        self.assertIsNone(report["open_entity_gaps"][0]["before"])

    def test_completed_gap_storage_is_bounded_and_totals_are_retained(self):
        capture = PartyCapture()
        for _ in range(100):
            capture.observe(query(availability="stale", count=1), 1)
            capture.observe(query(count=1), 1)
        report = capture.report()
        self.assertEqual(report["entity_gap_episodes"], 100)
        self.assertEqual(len(report["recent_entity_gaps"]), 64)
        self.assertEqual(report["omitted_closed_entity_gaps"], 36)

    def test_query_unavailability_does_not_invent_entity_staleness(self):
        capture = PartyCapture()
        capture.observe({"status": "unavailable", "data": None}, 1, observed_at_ms=10000, elapsed_ms=0)
        capture.observe(query(count=1), 1, observed_at_ms=11000, elapsed_ms=1000)
        report = capture.report()
        self.assertEqual(report["entity_gap_episodes"], 0)
        self.assertEqual(report["recent_query_gaps"][0]["cause"], "unavailable")
        self.assertEqual(report["recent_query_gaps"][0]["first_bad_to_resolution_ms"], 1000)
