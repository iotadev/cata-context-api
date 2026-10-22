"""Semantic queries shared by the CLI, local HTTP, and optional MCP adapter."""
import copy
import json
import time
from .reader import SnapshotError, guid, read_snapshot


class Queries:
    def __init__(self, path, max_age_ms=5000, clock=None, expected_build=None):
        if type(max_age_ms) is not int or not 250 <= max_age_ms <= 60000:
            raise ValueError("max_age_ms must be 250-60000")
        self.expected_build = expected_build
        self.path = path
        self.max_age_ms = max_age_ms
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)

    def query(self, method, character=None, *, after_sequence=0, limit=16):
        if method not in ("context.get_capabilities", "game.get_party", "playerbots.get_bot_state", "playerbots.get_action_history", "modules.get_observations"):
            raise ValueError("Unsupported query")
        if method in ("playerbots.get_bot_state", "playerbots.get_action_history", "modules.get_observations"):
            guid(character)
        elif character is not None:
            raise ValueError("This query takes no character")
        if type(after_sequence) is not int or not 0 <= after_sequence < 2**64 or type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError("History sequence/limit is out of bounds")
        try:
            data = read_snapshot(self.path, self.expected_build)
        except SnapshotError as error:
            return {"status": "unavailable", "reason": str(error), "data": None}
        now = self.clock()
        server = data["server"]
        age = now - server["exported_at_ms"]
        if age < -2000:
            status = "clock_mismatch"
        elif server["status"] == "stopped":
            status = "stopped"
        elif age > self.max_age_ms:
            status = "stale"
        else:
            status = "ok"
        result = {"status": status, "source": data["source"], "server": copy.deepcopy(server),
                  "export_age_ms": max(0, age), "max_age_ms": self.max_age_ms}
        if method == "context.get_capabilities":
            result["data"] = {**data["capabilities"], "scope": data["scope"]}
            return self._bounded(result)
        if method == "modules.get_observations":
            from .module_observations import query_modules
            row = next((item for item in data["entities"] if item["guid"] == character), None)
            if row is None:
                result.update(status="out_of_scope", data=None)
            elif not data["capabilities"].get("module_observations"):
                result.update(status="module_unavailable", data=None, reason="No native module provider")
            else:
                result["data"] = query_modules(row, server, now, status, data["source"], self.max_age_ms)
                if result["data"] is None:
                    result.update(status="module_unavailable", reason="Native module capture unavailable")
            return self._bounded(result)
        if method == "playerbots.get_action_history":
            if status == "clock_mismatch":
                result.update(data=None, reason="Cannot age history reliably with a clock mismatch")
                return result
            row = next((row for row in data["entities"] if row["guid"] == character), None)
            if row is None:
                result.update(status="out_of_scope", data=None)
                return result
            history = row.get("action_history")
            if not data["capabilities"]["history"] or history is None or not history["available"]:
                result.update(status="history_unavailable", data=None,
                              reason="History export or native engine collection is disabled/unsupported")
                return result
            if after_sequence > history["last_sequence"]:
                result.update(status="cursor_ahead", data=None,
                              reason="Cursor exceeds this history; reset after boot/session/epoch changes")
                return result
            capture_age = max(0, now - history["captured_at_ms"],
                              server["uptime_ms"] - history["captured_ms"] + max(0, age))
            events = []
            for original in history["events"]:
                event = copy.deepcopy(original)
                event["first_age_ms"] += capture_age
                event["last_age_ms"] += capture_age
                if event["first_age_ms"] <= history["retention_ms"] and event["sequence"] > after_sequence:
                    events.append(event)
            page = events[:limit]
            result["data"] = {key: value for key, value in history.items() if key != "events"}
            result["data"].update(guid=character, boot_id=server["boot_id"], events=page,
                next_sequence=page[-1]["sequence"] if page else after_sequence,
                more=len(events) > limit, capture_age_ms=capture_age,
                historical=True, coverage="engine admission and action-method returns only",
                note="Coalesced records can reappear when their sequence advances. Returns are not spell landing or damage/healing evidence.")
            return self._bounded(result)
        rows = [self._entity(row, server, now, status, data["capabilities"].get("diagnostic_fields")) for row in data["entities"]]
        if method == "playerbots.get_bot_state":
            row = next((row for row in rows if row["guid"] == character), None)
            if row is None:
                result.update(status="out_of_scope", data=None)
            elif row["player"] is not None and row["bot"] is None:
                result.update(status="not_a_bot", data=row)
            else:
                result["data"] = row
            return self._bounded(result)
        online = [row for row in rows if row["availability"] == "current"]
        groups = {}
        for row in online:
            group = row["player"]["group_guid"]
            if group:
                groups.setdefault(group, []).append(row["guid"])
        sampled = [row["sampled_ms"] for row in online]
        result["data"] = {"scope": data["scope"], "members": rows, "observed_groups": groups,
                          "snapshot_skew_ms": max(sampled) - min(sampled) if sampled else None,
                          "note": "Configured characters only; not an authoritative complete party roster."}
        return self._bounded(result)

    @staticmethod
    def _bounded(result):
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 65536:
            return {"status": "too_large", "source": result.get("source"),
                    "reason": "Query exceeds the 64 KiB response limit; no partial result returned", "data": None}
        return result

    def _entity(self, row, server, now, status, diagnostic_fields=None):
        result = copy.deepcopy(row)
        result.pop("module_observations", None)
        history = result.pop("action_history", None)
        if history is not None:
            result["action_history_summary"] = {key: value for key, value in history.items() if key != "events"}
        age = now - row["sampled_at_ms"] if row["sampled_at_ms"] else None
        # Monotonic age catches old samples even when wall clock moves backward.
        monotonic_age = server["uptime_ms"] - row["sampled_ms"] + max(0, now - server["exported_at_ms"])
        if status != "ok":
            availability = "server_" + status
        elif row["state"] != "online":
            availability = row["state"]
        elif age is None or age < -2000:
            availability = "clock_mismatch"
        elif max(age, monotonic_age) > self.max_age_ms:
            availability = "stale"
        else:
            availability = "current"
        result.update(availability=availability, sample_age_ms=max(0, age) if age is not None else None)
        if availability != "current":
            result["player"] = None
            result["bot"] = None
        if result["player"] is not None:
            result["player"]["diagnostics_availability"] = ("available" if "diagnostics" in result["player"] else
                "disabled" if diagnostic_fields == [] else "unsupported")
        if result["bot"] is not None and server["client_build"] == 12340:
            result["bot"]["observed_roles"] = None
            result["bot"]["unavailable_fields"] = ["engine_state", "strategies", "follow_target", "action_history", "role_assignment"]
        elif result["bot"] is not None and not result["bot"]["available"]:
            result["bot"]["unavailable_reason"] = "No initialized engine read model"
            result["bot"]["observed_roles"] = None
        elif result["bot"] is not None:
            # Matching Cata Playerbots Strategy.h: tank=4, dps=8, heal=16.
            # Other strategy bits (e.g. melee=64) do not change these roles.
            mask = result["bot"]["role_mask"]
            result["bot"]["observed_roles"] = [name for name, bit in (("tank", 4), ("damage", 8), ("healer", 16)) if mask & bit]
            result["bot"]["role_source"] = "playerbots_strategy_flags"
        return result
