"""Bounded diagnostics for ordinary read-only party replays, not a test oracle."""
from collections import Counter, deque
import copy
import time


class PartyCapture:
    def __init__(self):
        self.boot = None
        self.statuses = Counter()
        self.events = deque(maxlen=64)
        self.anomaly_count = 0
        self.gaps = deque(maxlen=64)
        self.query_gaps = deque(maxlen=64)
        self.open_gaps = {}
        self.open_query_gap = None
        self.gap_count = 0
        self.query_gap_count = 0
        self.last_fresh = {}
        self.last_generation = {}
        self.last_publication = None
        self.publications = 0
        self.origin_monotonic_ms = time.monotonic_ns() // 1_000_000
        self.last_elapsed_ms = None
        self.summary = {"source": "server", "samples": 0, "fresh_party_samples": 0,
                        "same_group_instance_samples": 0, "stale_online_samples": 0,
                        "combat_seen": False, "server_stopped": False, "members": {},
                        "max_sample_skew_ms": 0, "max_query_ms": 0,
                        "max_export_age_ms": 0}

    def observe(self, result, query_ms, *, observed_at_ms=None, elapsed_ms=None):
        wall = time.time_ns() // 1_000_000 if observed_at_ms is None else observed_at_ms
        elapsed = time.monotonic_ns() // 1_000_000 - self.origin_monotonic_ms if elapsed_ms is None else elapsed_ms
        if self.last_elapsed_ms is not None and elapsed < self.last_elapsed_ms:
            raise ValueError("Capture observation clock moved backward")
        if self.last_elapsed_ms is not None:
            self.summary["max_poll_gap_ms"] = max(self.summary.get("max_poll_gap_ms", 0), elapsed - self.last_elapsed_ms)
        self.last_elapsed_ms = elapsed
        self.summary.setdefault("started_observed_at_ms", wall)
        self.summary["last_observed_at_ms"] = wall
        self.statuses[result.get("status", "unknown")] += 1
        if result.get("source") == "fixture":
            return
        status = result.get("status", "unknown")
        if status not in ("ok", "stopped"):
            if self.open_query_gap is None or self.open_query_gap["cause"] != status:
                self._close_query_gap("cause_changed", wall, elapsed)
                self.query_gap_count += 1
                self.open_query_gap = self._new_gap(status, wall, elapsed)
            self._extend_gap(self.open_query_gap, result, None, wall, elapsed)
        else:
            self._close_query_gap("server_stopped" if status == "stopped" else "recovered", wall, elapsed)
        if result.get("source") != "server" or "server" not in result:
            return
        server = result["server"]
        if self.boot is not None and server["boot_id"] != self.boot:
            raise ValueError("Capture boot changed during the party replay")
        self.boot = server["boot_id"]
        publication = (server["boot_id"], server["sequence"])
        if publication != self.last_publication:
            self.publications += 1
            self.last_publication = publication
        if not isinstance(result.get("data"), dict) or not isinstance(result["data"].get("members"), list):
            return
        summary = self.summary
        summary["boot_id"] = self.boot
        summary["samples"] += 1
        summary["max_query_ms"] = round(max(summary["max_query_ms"], query_ms), 3)
        summary["max_export_age_ms"] = max(summary["max_export_age_ms"], result["export_age_ms"])
        rows = result["data"]["members"]
        skew = result["data"].get("snapshot_skew_ms")
        if skew is not None:
            summary["max_sample_skew_ms"] = max(summary["max_sample_skew_ms"], skew)
        fresh = []
        for row in rows:
            identity = row["guid"]
            generation = row["session_generation"]
            if self.last_generation.get(identity, generation) != generation:
                self._close_entity_gap(identity, "session_changed", wall, elapsed)
                self.last_fresh.pop(identity, None)
            self.last_generation[identity] = generation
            facts = summary["members"].setdefault(row["guid"], {
                "current_samples": 0, "offline_seen": False, "combat_seen": False,
                "origin": None, "stale_samples": 0, "max_sample_age_ms": 0,
                "first_stale_exported_at_ms": None, "last_stale_exported_at_ms": None})
            facts["offline_seen"] |= row["state"] == "offline"
            facts["max_sample_age_ms"] = max(facts["max_sample_age_ms"], row.get("sample_age_ms") or 0)
            if result["status"] != "stopped" and row["state"] == "online" and row["availability"] != "current":
                summary["stale_online_samples"] += 1
                facts["stale_samples"] += 1
                timestamp = server["exported_at_ms"]
                if facts["first_stale_exported_at_ms"] is None:
                    facts["first_stale_exported_at_ms"] = timestamp
                facts["last_stale_exported_at_ms"] = timestamp
                self.anomaly_count += 1
                self.events.append({"guid": row["guid"], "availability": row["availability"],
                                    "query_status": result["status"], "sequence": server["sequence"],
                                    "exported_at_ms": timestamp, "uptime_ms": server["uptime_ms"],
                                    "sampled_ms": row["sampled_ms"],
                                    "session_generation": row["session_generation"],
                                    "sample_age_ms": row.get("sample_age_ms"),
                                    "export_age_ms": result["export_age_ms"],
                                    "observed_at_ms": wall, "elapsed_ms": elapsed})
                cause = ("entity_sample_stale" if row["availability"] == "stale" else
                         "export_stale" if row["availability"] == "server_stale" else row["availability"])
                current = self.open_gaps.get(identity)
                if current is None or current["cause"] != cause:
                    self._close_entity_gap(identity, "cause_changed", wall, elapsed)
                    self.gap_count += 1
                    current = self._new_gap(cause, wall, elapsed)
                    current.update(guid=identity, session_generation=generation,
                                   before=copy.deepcopy(self.last_fresh.get(identity)))
                    self.open_gaps[identity] = current
                self._extend_gap(current, result, row, wall, elapsed)
            elif row["availability"] == "current":
                self._close_entity_gap(identity, "recovered", wall, elapsed, self._context(row, wall, elapsed))
            elif status == "stopped" or row["state"] in ("offline", "transferring", "awaiting_sample", "unobserved"):
                self._close_entity_gap(identity, "server_stopped" if status == "stopped" else row["state"], wall, elapsed)
            if row["availability"] == "current":
                self.last_fresh[identity] = self._context(row, wall, elapsed)
                facts["current_samples"] += 1
                facts["origin"] = row["player"]["origin"]
                facts["combat_seen"] |= row["player"]["in_combat"]
                summary["combat_seen"] |= row["player"]["in_combat"]
                fresh.append(row)
        if len(rows) == 5 and len(fresh) == 5:
            summary["fresh_party_samples"] += 1
            locations = {(row["player"]["group_guid"], row["player"]["map_id"],
                          row["player"]["instance_id"]) for row in fresh}
            if len(locations) == 1 and next(iter(locations))[0] is not None:
                summary["same_group_instance_samples"] += 1
        summary["server_stopped"] |= result["status"] == "stopped"

    @staticmethod
    def _context(row, wall, elapsed):
        player = row.get("player") or {}
        return {"observed_at_ms": wall, "elapsed_ms": elapsed,
                "sampled_ms": row["sampled_ms"], "session_generation": row["session_generation"],
                "map_id": player.get("map_id"), "instance_id": player.get("instance_id"),
                "in_combat": player.get("in_combat"), "diagnostics": copy.deepcopy(player.get("diagnostics"))}

    @staticmethod
    def _new_gap(cause, wall, elapsed):
        return {"cause": cause, "first_bad_observed_at_ms": wall, "first_bad_elapsed_ms": elapsed,
                "last_bad_observed_at_ms": wall, "last_bad_elapsed_ms": elapsed,
                "observations": 0, "distinct_bad_publications": 0,
                "max_sample_age_ms": 0, "max_export_age_ms": 0, "last_publication": None}

    @staticmethod
    def _extend_gap(gap, result, row, wall, elapsed):
        server = result.get("server") or {}
        publication = (server.get("boot_id"), server.get("sequence"))
        if gap["last_publication"] != publication:
            gap["distinct_bad_publications"] += 1
            gap["last_publication"] = publication
        gap["observations"] += 1
        gap["last_bad_observed_at_ms"] = wall
        gap["last_bad_elapsed_ms"] = elapsed
        gap["max_export_age_ms"] = max(gap["max_export_age_ms"], result.get("export_age_ms") or 0)
        gap["max_sample_age_ms"] = max(gap["max_sample_age_ms"], (row or {}).get("sample_age_ms") or 0)
        gap["last_exported_at_ms"] = server.get("exported_at_ms")
        gap["last_sequence"] = server.get("sequence")

    def _close_entity_gap(self, identity, resolution, wall, elapsed, after=None):
        gap = self.open_gaps.pop(identity, None)
        if gap is not None:
            gap.update(resolution=resolution, resolved_observed_at_ms=wall, resolved_elapsed_ms=elapsed, after=after)
            self.gaps.append(gap)

    def _close_query_gap(self, resolution, wall, elapsed):
        if self.open_query_gap is not None:
            self.open_query_gap.update(resolution=resolution, resolved_observed_at_ms=wall, resolved_elapsed_ms=elapsed)
            self.query_gaps.append(self.open_query_gap)
            self.open_query_gap = None

    @staticmethod
    def _gap_report(gap):
        result = {key: copy.deepcopy(value) for key, value in gap.items() if key != "last_publication"}
        result["observed_bad_span_ms"] = gap["last_bad_elapsed_ms"] - gap["first_bad_elapsed_ms"]
        end = gap.get("resolved_elapsed_ms")
        result["first_bad_to_resolution_ms"] = end - gap["first_bad_elapsed_ms"] if end is not None else None
        result["open"] = end is None
        return result

    def report(self):
        return {**self.summary, "query_status_counts": dict(self.statuses),
                "recent_anomalies": list(self.events),
                "omitted_anomaly_observations": self.anomaly_count - len(self.events),
                "distinct_publications_observed": self.publications,
                "entity_gap_episodes": self.gap_count,
                "recent_entity_gaps": [self._gap_report(gap) for gap in self.gaps],
                "open_entity_gaps": [self._gap_report(gap) for gap in self.open_gaps.values()],
                "omitted_closed_entity_gaps": self.gap_count - len(self.gaps) - len(self.open_gaps),
                "query_gap_episodes": self.query_gap_count,
                "recent_query_gaps": [self._gap_report(gap) for gap in self.query_gaps],
                "open_query_gap": self._gap_report(self.open_query_gap) if self.open_query_gap else None,
                "evidence": "server_snapshots_observed" if self.boot else "no_server_snapshots_observed",
                "note": "Counts are polling observations, not unique exports or gap durations. "
                        "Gap windows use the observer's monotonic elapsed clock, not a frozen export timestamp; "
                        "they do not prove continuous staleness between polls or a gameplay stall. "
                        "Each closed-gap buffer and the anomaly buffer retain at most 64 records. Human comparison and "
                        "native sampling overhead require separate evidence."}
