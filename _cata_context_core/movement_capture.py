"""Bounded historical movement observations. No controller, physics or velocity inference."""
import copy
from collections import deque
from .reader import guid


class MovementCapture:
    def __init__(self, character):
        guid(character)
        self.character = character
        self.records = deque(maxlen=256)
        self.overwritten = 0
        self.last_sample = None

    def observe(self, result):
        server = result.get("server", {})
        record = {"source": result.get("source"), "status": result.get("status"),
                  "server": copy.deepcopy(server), "guid": self.character}
        rows = (result.get("data") or {}).get("members", [])
        row = next((row for row in rows if row["guid"] == self.character), None)
        if result.get("status") != "ok" or row is None or row.get("availability") != "current":
            record["availability"] = row.get("availability") if row else "unavailable_or_out_of_scope"
            self.last_sample = None  # Preserve a fresh observation after a gap.
        else:
            player = row["player"]
            key = (server.get("expansion"), server.get("core"), server.get("client_build"),
                   server["boot_id"], row["session_generation"], row["sampled_ms"])
            if key == self.last_sample:
                return
            self.last_sample = key
            record.update(availability="historical", session_generation=row["session_generation"],
                          sampled_ms=row["sampled_ms"], sampled_at_ms=row["sampled_at_ms"],
                          map_id=player["map_id"], instance_id=player["instance_id"],
                          position=copy.deepcopy(player["position"]),
                          movement=copy.deepcopy(player.get("movement")),
                          movement_availability="available" if "movement" in player else "unsupported_or_disabled")
        if len(self.records) == self.records.maxlen:
            self.overwritten += 1
        self.records.append(record)

    def result(self):
        return {"kind": "movement_capture_v1", "historical": True, "guid": self.character,
                "capacity": 256, "overwritten": self.overwritten, "records": list(self.records),
                "coverage": "Polled server samples, not packet-complete client motion, collision or actual velocity. Native speed values are configured unit speeds."}
