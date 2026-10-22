"""Semantic contract regressions; synthetic data is not native gameplay proof."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from test_context import fixture
from cata_context.queries import Queries
from cata_context.reader import SnapshotError, validate


def phase():
    return {"flags": 8, "personal_guid": None, "entries": [{"id": 169, "flags": 0}], "total_entries": 1, "complete": True}


def relation(identity):
    return {"guid": identity, "details_available": True, "name": "Enemy", "alive": True, "in_combat": True,
            "map_id": 1, "instance_id": 0, "phase": phase(), "player_can_see_unit_phase": True,
            "unit_can_see_player_phase": True, "in_front_half": False, "within_native_melee_range": True,
            "centre_distance_yards": 3.0, "relative_angle_rad": 2.0, "native_melee_range_yards": 5.0}


def diagnostic_fixture():
    data = fixture()
    data["entities"][0]["player"]["diagnostics"] = {
        "kind": "native_phase_engagement_v1", "phase": phase(),
        "selected_unit": relation("700"), "attack_victim": relation("701"), "configured_peer_phases": []}
    return data


class NativeDiagnosticsTests(unittest.TestCase):
    def query(self, data, now=10000):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return Queries(path, clock=lambda: now).query("game.get_party")

    def test_selection_and_actual_victim_remain_distinct(self):
        result = self.query(diagnostic_fixture())
        player = result["data"]["members"][0]["player"]
        self.assertEqual(player["selected_target_guid"], "700")
        self.assertEqual(player["diagnostics"]["attack_victim"]["guid"], "701")
        self.assertFalse(player["diagnostics"]["attack_victim"]["in_front_half"])
        self.assertEqual(player["diagnostics_availability"], "available")

    def test_known_no_victim_is_not_unsupported_diagnostics(self):
        data = diagnostic_fixture()
        data["entities"][0]["player"]["diagnostics"]["attack_victim"] = None
        self.assertIsNone(self.query(data)["data"]["members"][0]["player"]["diagnostics"]["attack_victim"])
        old = self.query(fixture())["data"]["members"][0]["player"]
        self.assertEqual(old["diagnostics_availability"], "unsupported")
        disabled = fixture()
        disabled["capabilities"]["diagnostic_fields"] = []
        self.assertEqual(self.query(disabled)["data"]["members"][0]["player"]["diagnostics_availability"], "disabled")

    def test_stale_diagnostics_are_not_returned_as_live_geometry(self):
        result = self.query(diagnostic_fixture(), now=17000)
        self.assertIsNone(result["data"]["members"][0]["player"])

    def test_unresolved_unit_does_not_claim_phase_or_facing(self):
        data = diagnostic_fixture()
        unit = data["entities"][0]["player"]["diagnostics"]["attack_victim"]
        data["entities"][0]["player"]["diagnostics"]["attack_victim"] = {"guid": unit["guid"], "details_available": False}
        self.assertEqual(self.query(data)["status"], "ok")
        data["entities"][0]["player"]["diagnostics"]["attack_victim"]["in_front_half"] = False
        with self.assertRaises(SnapshotError):
            validate(data)

    def test_phase_data_is_bounded_and_not_a_mask_equality_assertion(self):
        data = diagnostic_fixture()
        diagnostic = data["entities"][0]["player"]["diagnostics"]
        diagnostic["phase"].update(total_entries=2, complete=False)
        diagnostic["selected_unit"]["player_can_see_unit_phase"] = False
        self.assertEqual(self.query(data)["status"], "ok")
        for mutate in (lambda d: d["phase"].update(complete=True),
                       lambda d: d["attack_victim"].update(relative_angle_rad=7.0),
                       lambda d: d["selected_unit"].update(guid="999"),
                       lambda d: d["configured_peer_phases"].append({"guid": "42", "details_available": False})):
            candidate = copy.deepcopy(data)
            mutate(candidate["entities"][0]["player"]["diagnostics"])
            with self.assertRaises(SnapshotError):
                validate(candidate)
