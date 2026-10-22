"""Human-readable CLI and an optional loopback-only read service."""
import argparse
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from .queries import Queries


def summary(result):
    lines = [f"Realm context: {result['status']}"]
    if "reason" in result:
        return "\n".join(lines + [result["reason"]])
    server = result["server"]
    lines.append(f"Realm {server['realm_id']} | build {server['client_build']} | source {result['source']} | export age {result['export_age_ms']} ms")
    body = result.get("data")
    if body is None:
        return "\n".join(lines)
    if body.get("kind") == "skate_pilot_v1":
        lines.append("Pilot active observation: " + body["active_availability"])
        for record in body["terminal"]:
            lines.append(f"  Historical run {record['module_boot']}/{record['run_token']}: {record['end_reason']} | cleanup {record['cleanup']}")
        lines.append(body["note"])
        return "\n".join(lines)
    if "events" in body:
        lines.append(f"Historical engine observations for {body['guid']}; captured {body['capture_age_ms']} ms ago")
        lines.append("Action-method returns only; does not establish landed spells or complete decision coverage.")
        for event in body["events"]:
            lines.append(f"  {event['sequence']}: {event['engine']} / {event['action']} / {event['kind']} / {event['reason']} | called {event['execute_called']} | return {event['action_return']} | engine {event['engine_result']} | age {event['last_age_ms']} ms | repeats {event['repeats']}")
        lines.append(f"Loss counters: overwritten {body['overwritten']}, expired {body['expired']}, suppressed {body['suppressed']}")
        return "\n".join(lines)
    if "members" in body:
        rows = body["members"]
        lines.append("Configured characters; complete party roster is not established.")
    elif "guid" in body:
        rows = [body]
    else:
        lines.extend(["Queries: " + ", ".join(body["query_methods"]),
                      "Controls: disabled; history export: " + ("enabled" if body["history"] else "unavailable")])
        return "\n".join(lines)
    for row in rows:
        player, bot = row["player"], row["bot"]
        if player is None:
            lines.append(f"  {row['guid']}: {row['availability']}")
            continue
        health, power = player["health"], player["power"]
        lines.append(f"  {player['name']} [{row['guid']}] {row['availability']} | health {health['current']}/{health['max']} | power {power['current']}/{power['max']} | map/instance {player['map_id']}/{player['instance_id']} | combat {player['in_combat']}")
        diagnostic = player.get("diagnostics")
        if diagnostic is not None:
            phase = diagnostic["phase"]
            phase_ids = ",".join(str(entry["id"]) for entry in phase["entries"]) or "none"
            lines.append(f"    Native phase flags {phase['flags']}; IDs {phase_ids}; complete {phase['complete']}")
            for title, key in (("Selected unit", "selected_unit"), ("Attack victim", "attack_victim")):
                unit = diagnostic[key]
                if unit is None:
                    lines.append(f"    {title}: none")
                elif not unit["details_available"]:
                    lines.append(f"    {title}: {unit['guid']}; same-map details unavailable")
                else:
                    lines.append(f"    {title}: {unit['name']} [{unit['guid']}] | distance {unit['centre_distance_yards']:.2f} yd | angle {unit['relative_angle_rad']:.3f} rad | front-half {unit['in_front_half']} | native melee range {unit['within_native_melee_range']} | phase compatible {unit['player_can_see_unit_phase']}")
        if bot is not None:
            if bot.get("kind") == "wotlk_ai_attachment_v1":
                lines.append(f"    AI attached | observed mode {bot['control_mode']} | master {bot['controller_guid']} | engine details unsupported")
            elif bot["available"]:
                roles = ", ".join(bot["observed_roles"]) or "unassigned"
                lines.append(f"    {bot['engine_state']} | strategy roles {roles} | controller {bot['controller_guid']} | follow {bot['follow_target_guid']} | staying {bot['staying']} | last action {bot['last_executed_action']} | queued {bot['queued_count']}")
            else:
                lines.append("    Bot engine details unavailable")
    return "\n".join(lines)


def handler_for(queries):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = urlsplit(self.path)
            is_history = route.path.startswith("/v1/bots/") and route.path.endswith("/actions")
            if (route.query and not is_history) or route.fragment:
                self.send_error(400, "This interface accepts no query parameters")
                return
            routes = {"/v1/capabilities": "context.get_capabilities", "/v1/party": "game.get_party"}
            character = None
            if route.path == "/":
                result = queries.query("game.get_party")
                page = '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="2"><title>Realm Context</title><style>body{font:16px system-ui;max-width:1000px;margin:3rem auto;padding:1rem;background:#15191f;color:#e9eef5}pre{white-space:pre-wrap;line-height:1.6}a{color:#98c8ff}</style><h1>Realm Context</h1><p>Read-only â€¢ refreshes every two seconds</p><pre>' + html.escape(summary(result)) + '</pre><p><a href="/v1/party">Party JSON</a> Â· <a href="/v1/capabilities">Capabilities JSON</a></p>'
                self.reply(page.encode(), "text/html; charset=utf-8")
                return
            method = routes.get(route.path)
            history_args = {}
            if route.path.startswith("/v1/modules/"):
                method = "modules.get_observations"
                character = route.path.removeprefix("/v1/modules/")
            if route.path.startswith("/v1/bots/"):
                method = "playerbots.get_action_history" if is_history else "playerbots.get_bot_state"
                character = route.path.removeprefix("/v1/bots/")
                if is_history:
                    character = character.removesuffix("/actions")
                    params = parse_qs(route.query, keep_blank_values=True)
                    if set(params) - {"after_sequence", "limit"} or any(len(values) != 1 for values in params.values()):
                        self.send_error(400, "Invalid history parameters")
                        return
                    try:
                        history_args = {key: int(values[0]) for key, values in params.items()}
                    except ValueError:
                        self.send_error(400, "History parameters must be integers")
                        return
            if method is None:
                self.send_error(404)
                return
            try:
                result = queries.query(method, character, **history_args)
            except ValueError:
                self.send_error(400, "Invalid character GUID")
                return
            self.reply(json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), "application/json")

        def reply(self, body, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass
    return Handler


def main(argv=None, *, query_factory=Queries):
    parser = argparse.ArgumentParser(description="Read copied realm snapshots; no gameplay control.")
    parser.add_argument("--snapshot", required=True, help="Snapshot JSON path exported by mod-context-api")
    parser.add_argument("--max-age-ms", type=int, default=5000)
    parser.add_argument("--json", action="store_true", help="Return structured JSON instead of a human summary")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    commands.add_parser("party")
    commands.add_parser("bot").add_argument("guid")
    commands.add_parser("modules").add_argument("guid")
    history = commands.add_parser("actions")
    history.add_argument("guid")
    history.add_argument("--after-sequence", type=int, default=0)
    history.add_argument("--limit", type=int, default=16)
    capture = commands.add_parser("capture-movement")
    capture.add_argument("guid")
    capture.add_argument("--duration-seconds", type=int, default=10, choices=range(1, 61))
    capture.add_argument("--interval-ms", type=int, default=250)
    commands.add_parser("serve").add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        queries = query_factory(args.snapshot, args.max_age_ms)
        if args.command == "capture-movement":
            import time
            from .movement_capture import MovementCapture
            from .reader import guid
            guid(args.guid)
            if not 250 <= args.interval_ms <= 10000:
                raise ValueError("Capture interval must be 250-10000 ms")
            capture = MovementCapture(args.guid)
            deadline = time.monotonic() + args.duration_seconds
            while time.monotonic() < deadline:
                capture.observe(queries.query("game.get_party"))
                time.sleep(min(args.interval_ms / 1000, max(0, deadline - time.monotonic())))
            print(json.dumps(capture.result(), ensure_ascii=False, allow_nan=False))
            return 0
        if args.command == "serve":
            if not 0 < args.port < 65536:
                raise ValueError("Invalid local port")
            with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(queries)) as server:
                print(f"Read-only realm context: http://127.0.0.1:{args.port}", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
            return 0
        methods = {"capabilities": "context.get_capabilities", "party": "game.get_party", "bot": "playerbots.get_bot_state", "actions": "playerbots.get_action_history", "modules": "modules.get_observations"}
        result = queries.query(methods[args.command], getattr(args, "guid", None),
                               after_sequence=getattr(args, "after_sequence", 0), limit=getattr(args, "limit", 16))
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) if args.json else summary(result))
        return 0 if result["status"] == "ok" else 2
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
