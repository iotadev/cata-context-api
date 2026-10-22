"""Bounded, validated reads of atomically published copied server snapshots."""
import json
import math
import os
import time
from pathlib import Path
from ._release_profile import BUILD as RELEASE_BUILD

MAX_BYTES = 1024 * 1024
MAX_CHARACTERS = 8


class SnapshotError(ValueError):
    pass


def integer(value, label, minimum=0, maximum=2**64 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise SnapshotError(f"Invalid {label}")
    return value


def guid(value, label="GUID", nullable=False):
    if value is None and nullable:
        return value
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise SnapshotError(f"Invalid {label}")
    if len(value) > 20 or value.startswith("0") or not 0 < int(value) < 2**64:
        raise SnapshotError(f"Invalid {label}")
    return value


def obj(value, label):
    if not isinstance(value, dict):
        raise SnapshotError(f"Invalid {label}")
    return value


def text(value, label, limit=256):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise SnapshotError(f"Invalid {label}")
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise SnapshotError(f"Invalid {label}")


def phase(value):
    obj(value, "native phase")
    integer(value.get("flags"), "phase flags", maximum=2**32 - 1)
    guid(value.get("personal_guid"), "personal phase GUID", nullable=True)
    total = integer(value.get("total_entries"), "phase entry count", maximum=2**32 - 1)
    boolean(value.get("complete"), "phase completeness")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) > 32 or len(entries) > total:
        raise SnapshotError("Invalid phase entries")
    if value["complete"] != (len(entries) == total):
        raise SnapshotError("Inconsistent phase completeness")
    seen = set()
    for entry in entries:
        obj(entry, "phase entry")
        identity = integer(entry.get("id"), "phase ID", 1, 2**32 - 1)
        integer(entry.get("flags"), "phase entry flags", maximum=65535)
        if identity in seen:
            raise SnapshotError("Duplicate phase ID")
        seen.add(identity)


def relation(value):
    if value is None:
        return
    obj(value, "unit relation")
    guid(value.get("guid"))
    boolean(value.get("details_available"), "unit detail availability")
    if not value["details_available"]:
        if set(value) != {"guid", "details_available"}:
            raise SnapshotError("Unavailable relation contains apparently resolved details")
        return
    text(value.get("name"), "unit name")
    for key in ("alive", "in_combat", "player_can_see_unit_phase", "unit_can_see_player_phase", "in_front_half", "within_native_melee_range"):
        boolean(value.get(key), key)
    for key in ("map_id", "instance_id"):
        integer(value.get(key), key, maximum=2**32 - 1)
    phase(value.get("phase"))
    for key in ("centre_distance_yards", "relative_angle_rad", "native_melee_range_yards"):
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number):
            raise SnapshotError(f"Invalid {key}")
    if value["centre_distance_yards"] < 0 or value["native_melee_range_yards"] < 0 or abs(value["relative_angle_rad"]) > 3.1417:
        raise SnapshotError("Invalid relation geometry bounds")


def diagnostics(value, identity, configured):
    obj(value, "native diagnostics")
    if value.get("kind") != "native_phase_engagement_v1":
        raise SnapshotError("Unsupported native diagnostics")
    phase(value.get("phase"))
    relation(value.get("selected_unit"))
    relation(value.get("attack_victim"))
    peers = value.get("configured_peer_phases")
    if not isinstance(peers, list) or len(peers) != len(configured) - 1:
        raise SnapshotError("Invalid configured phase peer count")
    seen = set()
    for peer in peers:
        obj(peer, "phase peer")
        peer_guid = guid(peer.get("guid"))
        if peer_guid == identity or peer_guid not in configured or peer_guid in seen:
            raise SnapshotError("Invalid phase peer identity")
        seen.add(peer_guid)
        boolean(peer.get("details_available"), "peer detail availability")
        if peer["details_available"]:
            for key in ("player_can_see_peer_phase", "peer_can_see_player_phase"):
                boolean(peer.get(key), key)
        elif set(peer) != {"guid", "details_available"}:
            raise SnapshotError("Unavailable phase peer contains compatibility conclusions")


def action_history(value, row, server):
    obj(value, "action history")
    boolean(value.get("available"), "history availability")
    for key in ("session_generation", "captured_ms", "captured_at_ms", "epoch", "last_sequence", "overwritten", "expired", "suppressed"):
        integer(value.get(key), key)
    if value["captured_ms"] > server["uptime_ms"] or value["session_generation"] > row["session_generation"]:
        raise SnapshotError("Invalid history capture identity/time")
    if value.get("retention_ms") != 60000 or value.get("capacity") != 64:
        raise SnapshotError("Unsupported history bounds")
    events = value.get("events")
    if not isinstance(events, list) or len(events) > 64 or (events and not value["available"]):
        raise SnapshotError("Invalid retained history")
    previous = 0
    for event in events:
        obj(event, "action event")
        sequence = integer(event.get("sequence"), "event sequence", 1)
        first = integer(event.get("first_sequence"), "first event sequence", 1)
        if not previous < sequence <= value["last_sequence"] or first > sequence:
            raise SnapshotError("Invalid action sequence order")
        previous = sequence
        first_age = integer(event.get("first_age_ms"), "first action age", maximum=60000)
        last_age = integer(event.get("last_age_ms"), "last action age", maximum=60000)
        if last_age > first_age:
            raise SnapshotError("Inconsistent action ages")
        integer(event.get("repeats"), "coalesced repeat count", 1, sequence - first + 1)
        text(event.get("action"), "action name", 64)
        if event.get("engine") not in ("combat", "noncombat", "dead"):
            raise SnapshotError("Unknown action engine")
        reasons = {"rejected": {"unknown_action", "not_useful", "not_possible", "relevance_not_positive"},
                   "deferred": {"prerequisite_queued"},
                   "execution": {"action_returned_true", "action_returned_false", "before_listener_veto", "execution_listener_suppressed"}}
        kind = event.get("kind")
        if kind not in reasons or event.get("reason") not in reasons[kind]:
            raise SnapshotError("Unknown action observation")
        boolean(event.get("execute_called"), "Execute call flag")
        for key in ("action_return", "engine_result"):
            if event.get(key) is not None:
                boolean(event[key], key)
        if event["execute_called"] != (event.get("action_return") is not None):
            raise SnapshotError("Inconsistent execution return")
        if kind != "execution" and (event["execute_called"] or event.get("engine_result") is not None):
            raise SnapshotError("Admission event contains execution evidence")
        if kind == "execution" and event.get("engine_result") is None:
            raise SnapshotError("Execution observation lacks final engine result")
        reason = event["reason"]
        if reason.startswith("action_returned_") and (not event["execute_called"] or
                event["action_return"] != (reason == "action_returned_true")):
            raise SnapshotError("Action return contradicts observation reason")
        if reason in ("before_listener_veto", "execution_listener_suppressed") and event["execute_called"]:
            raise SnapshotError("Listener suppression contains an action return")


def movement(value):
    obj(value, "movement")
    if value.get("kind") != "native_movement_v1" or value.get("source") != "server_native_state":
        raise SnapshotError("Unsupported movement source/kind")
    integer(value.get("flags_raw"), "movement flags", maximum=2**32 - 1)
    boolean(value.get("falling"), "falling")
    for key in ("run_speed", "swim_speed", "flight_speed"):
        speed = value.get(key)
        if type(speed) not in (float, int) or not math.isfinite(speed) or not 0 <= speed <= 10000:
            raise SnapshotError("Invalid native movement speed")


def validate(data, expected_build=None):
    if RELEASE_BUILD is not None:
        if expected_build not in (None, RELEASE_BUILD):
            raise SnapshotError("Requested build does not match this adapter release")
        expected_build = RELEASE_BUILD
    obj(data, "snapshot")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise SnapshotError("Unsupported snapshot schema; expected version 1")
    if data.get("source") not in ("server", "fixture"):
        raise SnapshotError("Unknown snapshot source")
    server = obj(data.get("server"), "server")
    text(server.get("boot_id"), "boot identity")
    if not server["boot_id"] or server.get("status") not in ("running", "stopped"):
        raise SnapshotError("Invalid server identity/status")
    build = server.get("client_build")
    profiles = {15595: ("cata", "TrinityCore"), 12340: ("wotlk", "AzerothCore")}
    if type(build) is not int or build not in profiles or (expected_build is not None and build != expected_build):
        raise SnapshotError("Unsupported or unexpected client build")
    expansion, core = profiles[build]
    # Old Cata v1 exports have no profile labels. New adapters must identify both.
    if build == 12340 or "expansion" in server or "core" in server:
        if server.get("expansion") != expansion or server.get("core") != core:
            raise SnapshotError("Expansion/core/build profile mismatch")
    for key in ("realm_id", "started_at_ms", "exported_at_ms", "uptime_ms", "sequence"):
        integer(server.get(key), key)
    integer(server.get("sample_interval_ms"), "sample interval", 250, 10000)
    for key in ("core_revision", "adapter_version"):
        text(server.get(key), key)
    scope = obj(data.get("scope"), "scope")
    boolean(scope.get("roster_complete"), "roster completeness")
    configured = scope.get("characters")
    if not isinstance(configured, list) or not 1 <= len(configured) <= MAX_CHARACTERS:
        raise SnapshotError("Invalid character scope")
    for value in configured:
        guid(value)
    if len(set(configured)) != len(configured):
        raise SnapshotError("Duplicate scoped identity")
    capabilities = obj(data.get("capabilities"), "capabilities")
    if capabilities.get("control") is not False:
        raise SnapshotError("Unexpected control capability in read-only schema v1")
    boolean(capabilities.get("history"), "history capability")
    if "movement" in capabilities:
        boolean(capabilities["movement"], "movement capability")
    supported = capabilities.get("module_observations", [])
    if supported not in ([], ["skate_pilot_v1"]):
        raise SnapshotError("Unsupported module observation capability")
    methods = capabilities.get("query_methods")
    expected = ["context.get_capabilities", "game.get_party", "playerbots.get_bot_state"]
    if capabilities["history"]:
        expected.append("playerbots.get_action_history")
    if supported:
        expected.append("modules.get_observations")
    if methods != expected:
        raise SnapshotError("Unexpected query methods")
    rows = data.get("entities")
    if not isinstance(rows, list) or len(rows) != len(configured):
        raise SnapshotError("Entity count does not match configured scope")
    seen = set()
    for row in rows:
        obj(row, "entity")
        identity = guid(row.get("guid"))
        if identity in seen or identity not in configured:
            raise SnapshotError("Duplicate or out-of-scope identity")
        seen.add(identity)
        for key in ("session_generation", "sampled_ms", "sampled_at_ms"):
            integer(row.get(key), key)
        if "module_observations" in row:
            from .module_observations import validate_modules
            validate_modules(row["module_observations"], row, server, supported)
        elif supported:
            raise SnapshotError("Enabled module observations lack scoped payload")
        if "action_history" in row:
            action_history(row["action_history"], row, server)
        if row["sampled_ms"] > server["uptime_ms"]:
            raise SnapshotError("Entity sample is newer than its export")
        state = row.get("state")
        if state not in ("unobserved", "awaiting_sample", "offline", "online", "transferring"):
            raise SnapshotError("Unknown entity state")
        player, bot = row.get("player"), row.get("bot")
        if state != "online":
            if player is not None or bot is not None:
                raise SnapshotError("Unavailable entity contains apparently live state")
            continue
        if not row["session_generation"] or not row["sampled_at_ms"]:
            raise SnapshotError("Online entity lacks lifecycle/sample identity")
        obj(player, "player")
        if "diagnostics" in player:
            if build != 15595:
                raise SnapshotError("Cata phase diagnostics require the Cata adapter")
            diagnostics(player["diagnostics"], identity, configured)
        text(player.get("name"), "player name", 64)
        if player.get("origin") not in (("client", "server") if build == 15595 else ("unknown",)):
            raise SnapshotError("Invalid session origin")
        for key in ("group_guid", "selected_target_guid"):
            guid(player.get(key), key, nullable=True)
        if "diagnostics" in player:
            selected = player["diagnostics"]["selected_unit"]
            selected_guid = selected["guid"] if selected else None
            if selected_guid != player["selected_target_guid"]:
                raise SnapshotError("Selected-unit diagnostic identity mismatch")
        for key in ("alive", "in_combat"):
            boolean(player.get(key), key)
        for key in ("map_id", "instance_id"):
            integer(player.get(key), key, maximum=2**32 - 1)
        for key in ("health", "power"):
            values = obj(player.get(key), key)
            integer(values.get("current"), key, maximum=2**32 - 1)
            integer(values.get("max"), key, maximum=2**32 - 1)
            if values["current"] > values["max"]:
                raise SnapshotError(f"Invalid {key} range")
        integer(player["power"].get("type"), "power type", maximum=255)
        position = obj(player.get("position"), "position")
        for key in ("x", "y", "z", "orientation"):
            value = position.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise SnapshotError("Invalid position")
        if "movement" in player:
            if capabilities.get("movement") is not True:
                raise SnapshotError("Movement data lacks an enabled capability")
            movement(player["movement"])
        elif capabilities.get("movement") is True:
            raise SnapshotError("Enabled movement capture lacks an online sample")
        if build == 12340:
            # Client connection origin is not inferred from AI attachment/master.
            if bot is not None:
                obj(bot, "WOTLK bot")
                if bot.get("kind") != "wotlk_ai_attachment_v1" or bot.get("ai_attached") is not True:
                    raise SnapshotError("Invalid WOTLK bot observation")
                guid(bot.get("controller_guid"), nullable=True)
                mode = bot.get("control_mode")
                if mode not in ("self", "other_master", "other_master_unresolved", "no_master"):
                    raise SnapshotError("Invalid observed control mode")
                controller = bot["controller_guid"]
                if ((mode == "self" and controller != identity) or
                    (mode == "other_master" and (controller is None or controller == identity)) or
                    (mode in ("no_master", "other_master_unresolved") and controller is not None)):
                    raise SnapshotError("Inconsistent master observation")
            continue
        if player["origin"] == "client":
            if bot is not None:
                raise SnapshotError("Client-origin entity contains bot state")
            continue
        obj(bot, "bot")
        boolean(bot.get("available"), "bot availability")
        boolean(bot.get("attack_requested"), "attack request")
        for key in ("controller_guid", "follow_target_guid"):
            guid(bot.get(key), key, nullable=True)
        integer(bot.get("role_mask"), "role mask", maximum=2**32 - 1)
        if bot["available"]:
            boolean(bot.get("staying"), "staying")
            if bot.get("engine_state") not in ("combat", "noncombat", "dead"):
                raise SnapshotError("Invalid bot engine state")
            action = bot.get("last_executed_action")
            if action is not None:
                text(action, "last executed action")
            integer(bot.get("queued_count"), "queue count", maximum=2**32 - 1)
            for key in ("combat_strategies", "noncombat_strategies"):
                strategies = bot.get(key)
                if not isinstance(strategies, list) or len(strategies) > 64:
                    raise SnapshotError("Invalid strategy list")
                for value in strategies:
                    text(value, "strategy")
    return data


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError("Duplicate JSON key")
        result[key] = value
    return result


def _open_snapshot(path):
    if os.name != "nt":
        return Path(path).open("rb")
    # Windows' normal Python file open denies replacement while a reader holds
    # the file. Share deletion so the exporter can atomically swap snapshots;
    # the open reader retains its original complete file.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # abspath does not open a temporary non-share-delete handle, unlike resolve.
    handle = create(os.path.abspath(os.fspath(path)), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(handle)
        raise
    return os.fdopen(descriptor, "rb")


def read_snapshot(path, expected_build=None):
    try:
        for attempt in range(4):
            try:
                with _open_snapshot(path) as stream:
                    raw = stream.read(MAX_BYTES + 1)
                break
            except OSError as error:
                # ReplaceFile can briefly remove the old directory entry or
                # encounter another handle. Retry I/O only, bounded to 30 ms;
                # never reuse a cached successful response or malformed JSON.
                if os.name != "nt" or getattr(error, "winerror", None) not in (2, 3, 5, 32) or attempt == 3:
                    raise
                time.sleep(0.01)
        if len(raw) > MAX_BYTES:
            raise SnapshotError("Snapshot exceeds the 1 MiB limit")
        data = json.loads(raw, object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(SnapshotError("Non-finite JSON value")))
        return validate(data, expected_build)
    except SnapshotError:
        raise
    except (OSError, ValueError, TypeError, RecursionError, OverflowError) as error:
        raise SnapshotError(f"Snapshot unavailable or malformed ({type(error).__name__})") from error
