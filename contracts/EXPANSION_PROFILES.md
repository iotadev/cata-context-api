# Shared context, expansion-specific native adapters

The canonical project remains at `CATA/cata-context-api` for now; its location and
distribution name are retained to avoid a repository/runtime migration. The
`game_context` package owns common parsing, queries, captures and optional MCP.
`cata_context` remains the build-15595 compatibility interface. No new installation,
entry-point registration, service or host configuration is applied by this change.

## Profiles

| Build | Expansion | Core | Native source |
|---|---|---|---|
| 15595 | cata | TrinityCore | Existing `server-module`, native bot getter in Cata Playerbots |
| 12340 | wotlk | AzerothCore | `adapters/wotlk`, matching WOTLK Playerbots lookup |

Schema 1 envelopes keep the existing freshness, boot/session, scope and bounded
query rules. Old Cata schema-1 captures lacking expansion/core labels are accepted
only as the legacy 15595 profile. Other profiles must match all three fields.
Existing Cata readers/commands remain pinned to 15595; the common entry points
accept either supported profile. This does not make native binaries interchangeable.

WOTLK `player.origin=unknown` deliberately makes no assertion about client/session
origin. A nullable bot envelope is a sampled AI attachment, not Cata's server-origin
engine envelope. `kind=wotlk_ai_attachment_v1`, `ai_attached=true`,
`controller_guid`, and `control_mode=self|other_master|other_master_unresolved|no_master` report only the
observed attachment/master relation. A null envelope means no attached AI at that
sample; it is not a classification of human intent. No permission or activity
reservation is granted by these fields. Strategies/roles/follow intent/engine
history remain unsupported in this first WOTLK adapter.

Cata retains its existing bot engine/phase/history semantics. Cata phase objects
are not accepted under WOTLK. Missing diagnostic fields remain unsupported or
disabled; they do not assert negative gameplay facts. Consumers inspect profile
and capability metadata rather than assuming the union of both expansions.

## Optional movement observation

Both adapters add startup-only `ContextAPI.Movement=0` by default. If enabled,
capabilities reports `movement=true` and settled online player samples include
`movement.kind=native_movement_v1`, `source=server_native_state`, `flags_raw`,
`falling`, `run_speed`, `swim_speed`, and `flight_speed`. Flags retain their native
profile meaning. Speeds are native configured unit speeds in yards/sec, not a
measurement of displacement, acceleration or actual velocity. Falling is the
native falling/falling-far flag predicate; jump arc, collision normal, slope and
packet completeness are not reported. Position and these fields share the entity
sampling timestamp and lifecycle identity. Transfer/offline/stale/stopped results
withhold current player fields, including movement.

`MovementCapture` and `game-context ... capture-movement GUID` preserve bounded
historical copies for either expansion: 256 records, explicit overwritten count,
boot/build/profile, session generation, map/instance and sample timestamps.
Duplicate current entity samples are skipped. Unavailable polls produce gap
records without positions. Fixture source stays fixture; history never becomes
current state. CLI polling lasts 1-60 seconds and exposes no gameplay writes.

## Native ownership and qualification

WOTLK samples `OnPlayerUpdate` in the map's player update. It precedes Playerbots'
`OnPlayerAfterUpdate` decision hook; it is not a post-decision receipt. Group
identity is copied without traversing cross-map party objects. Boot-local session
generations reject a publication from a prior login/logout. Before-logout clears
the live cache; unobserved identities are not assumed offline. No reload is
supported; the service is retained until shutdown and no game pointers reach the
writer. Publication uses a private temporary file and atomic replacement.

The Cata sampling seam remains its map-session hook after the Cata bot update.
Existing bot history is historical engine evidence, not spell completion.
Separate native builds and isolated captures are still required for both modified
adapters. Source/fixture qualification cannot certify native threading, overhead,
live inventory, client collision or gameplay outcomes.

## Consumers

Bot-context consumers use `game_context.queries.Queries` with a fixed trusted
snapshot path, then `query('game.get_party')`. Check status, source and each
entity's availability; the selected character list is not a complete party roster.
The library creates no model calls, goal state, actions or Chatter integration.

Skate research can use `python -m game_context --snapshot PATH capture-movement
GUID --duration-seconds 10 --interval-ms 250`. Sampling/export interval may be
slower than polling. The native movement capability must be qualified independently
before using these records as runtime evidence. This command does not activate a
skate mode or modify movement.

The optional shared stdio MCP surface provides five read-only queries under
`context_get_capabilities`, `game_get_party`, `playerbots_get_bot_state`, and
`playerbots_get_action_history`; resources use `context://`. Existing Cata MCP
tool/resource names stay compatible and pinned. There is no MCP movement-control
tool, listener or host registration in this implementation.

WOTLK master identity resolution never dereferences the native master pointer
across maps: self identity is local, and another master is resolved by pointer
comparison against at most 64 entries in the current map's player list. An
unresolved cross-map/out-of-bound master reports `other_master_unresolved` with
null controller GUID. That means a native master relation exists but its GUID
was not safely captured; it is distinct from `no_master` and grants no authority.

Optional retained module diagnostics use the same expansion-neutral query and
`modules_get_observations` MCP tool. The new WOTLK native provider advertises
`skate_pilot_v1`; Cata returns module_unavailable until it has a native provider.
This does not change either profile's AI-history support. See
[MODULE_OBSERVATIONS_V1.md](MODULE_OBSERVATIONS_V1.md).
