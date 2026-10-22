# Snapshot v1

The handoff is one UTF-8 JSON document capped by the reader at 1 MiB. A capture contains at most eight configured entities. `source` is `server` or `fixture`; fixture records are never runtime evidence. Legacy Cata reader support remains schema 1/build 15595. The shared reader also accepts the explicit WOTLK profile; see EXPANSION_PROFILES.md.

Semantic query responses are capped at 64 KiB. Exceeding that limit returns an explicit `too_large` result with null data, not a silently truncated partial snapshot.

## Server envelope

`server` includes `boot_id`, `status` (`running`/`stopped`), realm ID, client build, core revision, adapter version, wall-clock start/export times in milliseconds, monotonic uptime in milliseconds, publication sequence, and sampling interval. The core revision identifies the build source base and can include its dirty marker; it is not a claim that the experimental changes were committed.

The exporter uses `steady_clock` durations, not the native wrapping 32-bit millisecond counter. Lifecycle generations are meaningful only with the server boot ID. Capture timestamps are sampled from the server host; an externally running reader must have sufficiently aligned time or report a clock mismatch.

## Scope and availability

`scope.characters` lists full raw player GUIDs as canonical decimal strings. Config accepts player GUID counters, creates native Player GUIDs, then serializes the full raw values. Generic entity GUIDs remain strings to avoid numeric precision loss in JavaScript clients. `roster_complete` is false for this slice.

An entity has `guid`, `session_generation`, `state`, `sampled_ms`, `sampled_at_ms`, `player`, and `bot`. Initial state is `unobserved`, not assumed offline. Login changes to `awaiting_sample` with a new generation. Logout invalidates old data and records `offline`. Map-owned publication can report `online` or `transferring`; transfer rows contain no settled player/bot details.

Unavailable entity records contain null `player` and `bot` values. A currently sampled client-origin player has null bot data. A server-origin player has a bot envelope; `available=false` means its decision engine details are unavailable, not that it is a human.

The query service also removes live fields when the export is stale/stopped or an individual sample is stale. A newly written export must not make an old entity sample look current. Party responses include current sample skew and observed groups, and exclude unavailable rows from current group aggregation.

## Native ownership

`PlayerScript::OnUpdate` is dispatched by the map-session update after Playerbots' native map update. It samples basic player state and invokes the copied bot getter in that same context. Using the session pump keeps idle players sampled when grid visitation does not invoke `Player::Update`. It copies the native group identity only; it does not traverse cross-map party member objects. Queries contain no authoritative group membership enumeration.

Login/logout update the fixed-size cache under a mutex. A pending publication with a prior generation is rejected. The writer thread copies the cache under the mutex, then serializes and writes without holding it. It retains no native game object pointers. File failures are logged with throttling and do not stop gameplay.

Windows publication uses `ReplaceFileW` for an existing target and `MoveFileExW` for the first publication. The Python reader opens with read/write/delete sharing and permits bounded retries for transient Windows namespace/handle errors. POSIX publication uses rename. Readers accept only a complete validated document and do not reuse old successful results on error.

## Query semantics

- `context.get_capabilities`: capture/server status, supported methods, configured scope. Controls are false; history is optional as described below.
- `game.get_party`: configured entities, each with lifecycle and freshness; observed group IDs; sample skew. It does not claim complete party membership.
- `playerbots.get_bot_state`: one scoped GUID. Unknown GUID is out-of-scope; a fresh client-origin sample is not-a-bot. Offline/unobserved entities retain explicit uncertainty.

Player fields include name, session origin, selected target, group identity, alive/combat flags, health/power, map/instance, and position. Bot fields include controller, follow target, attack-request intent, role mask, and optionally engine state, staying, last executed action, queue count, and combat/noncombat strategies. Role mask is the module's native copied mask, not a universal role taxonomy. No current-action or spell-outcome claim is implied.

The query adapter derives `observed_roles` from the matching Cata module's strategy flags (tank=4, damage=8, healer=16), preserving the raw mask. Other flags such as melee=64 are excluded. This describes strategy roles, not proof of actual threat/healing performance or an authoritative party assignment. An unavailable engine reports unknown roles rather than an empty known list.

## Optional native phase and engagement data (adapter 0.2.0)

Schema 1 gains an additive `player.diagnostics` object when `ContextAPI.DiagnosticDetails` is enabled. `capabilities.diagnostic_fields` advertises the enabled fields. Older captures remain readable and report diagnostics as unsupported; a newer exporter with the gate off reports disabled. Missing diagnostics is not evidence of no attack victim.

The object kind is `native_phase_engagement_v1`. Its `phase` holds native PhaseShift flags, personal GUID, phase ID/flag pairs, total count, and completeness. At most 32 entries are copied; truncation is explicit. This is not a WotLK-style phase-mask equality test. Compatibility booleans come from the core's directional `IsInPhase` calls, including personal/inverse/cosmetic/unphased rules.

`selected_unit` and `attack_victim` are independent nullable relations. Null means no such native identity at the sample; a non-null GUID with `details_available=false` means the identity is known but same-map unit details could not be safely sampled. Selected game objects/non-resolved units are not treated as known absent targets.

Resolved relations contain copied identity/name/alive/combat/map/instance/phase information plus player-to-unit and reverse phase compatibility, centre distance in yards, signed relative angle in radians, native front-half result, native melee-range threshold, and the native melee-range result. The angle is normalized to [-pi, pi]. The front-half predicate is the core's HasInArc(pi), not an individual spell's facing rule. Native melee range also checks map/phase; its failure is not independently proof of excessive distance. No expensive LOS/pathfinding probe is added, and no complete attack eligibility/result is asserted.

`configured_peer_phases` samples only other configured characters resolved on this map. Unresolved peers have unavailable compatibility, not false compatibility. These records use this entity's sampling timestamp and do not make independently collected party snapshots atomic.

All geometry, phase collections, and compatibility results are copied in the map-session context; the exporter and query service retain no native object pointers. Stale/transfer/offline/stopped query responses still remove player and diagnostic fields. Bounded reporter before/after context is explicitly historical.

Current gameplay integration clarification: `last_executed_action` comes from
the active engine's historical last-success value, rather than an all-engine
timeline. The legacy `attack_requested` field exposes the adapter's IsAttacking
flag; it does not expose the pending combat-command mailbox or prove a landed
attack. Use sampled native combat state and client evidence for those questions.
# Optional engine action history (exporter 0.3.0)

`capabilities.history` and `playerbots.get_action_history` advertise export support.
An entity may include top-level `action_history`, independent of current player
availability. Its `available` flag separately describes native collector support.
Records never contain native pointers. The capture has boot identity (server),
session generation, collection epoch, monotonic/wall capture time, last sequence,
capacity 64, retention 60000 ms and explicit overwritten/expired/suppressed totals.

Each record has sequence, first_sequence, repeats, first_age_ms, last_age_ms,
engine, action, kind, reason, execute_called, nullable action_return and nullable
engine_result. Admission records have no execution evidence. Execution records
distinguish the raw method return from listener-adjusted results. These are
engine observations, not spell success/completion or client outcome evidence.
Readers age historical copies without refreshing them, filter expired events,
and withhold history when the external clock cannot support reliable aging.
Legacy snapshots without the optional field remain readable.

## Optional retained module observations

The additive `module_observations` capability/entity envelope and dedicated
`modules.get_observations` query are specified in
[MODULE_OBSERVATIONS_V1.md](MODULE_OBSERVATIONS_V1.md). They do not enable
Playerbots history or add module history to current party/bot payloads.
