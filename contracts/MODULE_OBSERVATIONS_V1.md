# Optional module observations v1

This additive schema-1 extension is distinct from Playerbots action history.
`capabilities.module_observations` is absent/empty without a provider, or contains
`skate_pilot_v1`. Only the latter adds `modules.get_observations` to query discovery.
The schema is shared, but each release accepts only its own expansion; the native provider currently
exists only for statically linked WOTLK skate/context modules. Cata does not
advertise unsupported native skate diagnostics.

Each configured entity may carry `module_observations` with observer-relative
`captured_ms`, wall `captured_at_ms`, and a `skate_pilot` object or explicit null.
The exporter reads only configured subjects on the world thread. It releases the
observer cache lock before calling the provider; the provider copies records
under its own mutex and serializes those copies after releasing that mutex.
The background writer sees immutable JSON values and never reads game objects.
The statically registered serializer is trusted native code, not an external JSON
input. Its per-subject output is bounded to 48 KiB; failures become unavailable.
The existing 1 MiB snapshot and 64 KiB query limits still apply.

The provider envelope identifies kind/source, module boot, source identity,
capacity 16, retention scope `realm`, last terminal event sequence and cumulative
overwritten count. Its `active` record is nullable; `terminal` contains at most
sixteen selected-subject records in increasing event order. The ring is shared
across subjects, so gaps and global eviction counters do not establish whether
this subject ran. This is in-memory diagnostic history, not a persistent database.
Restart changes module boot and resets token/event space. Treat
`(module_boot, guid, run_token)` as run identity; reset cursors on boot changes.

Records identify subject GUID (decimal string), realm/map/instance, module/source,
token, observer binding status/boot/generation, start/sample wall anchors, module
steady start/sample times, elapsed time, segment count and exact terminal reason.
Active records have sequence zero, status `active`, historical false and null
end_reason. Terminal records have a positive event sequence, status `terminal`
and historical true even when copied into a fresh publication.

`pre_cleanup` is the native decision state before movement/presentation/speed
cleanup. It includes copied position, raw movement flags, native reported falling,
free control/self mover/casting/forced state, actual/owned run rates and actual/
owned spline IDs plus initialization/falling/finalization. It is null when the
player is unavailable. Configured run rate is not actual velocity.

`ground` is a nullable native height-query record, with its own position and
module/wall sample times, nullable height/contact offset, whether reconciliation
applied at that observation, and null normal. Unknown/nonfinite native numbers
remain null. The cumulative reconciliation count is separate. A height query is
not a complete collision/contact solver and does not prove client contact.

`model` contains modeled velocity components, heading and yaw rate. `input`
contains the last accepted transport sequence, receipt age and push/brake/steer.
No accepted input has null age and sequence zero. These are model/transport facts;
they do not prove a physical key is held or a client rendered the modeled pose.
`cleanup` separately records spline release/finalization or foreign preservation,
presentation release/preservation, speed restoration/normal or foreign
preservation, and a nullable post-cleanup actual run rate. Cleanup is appended
after the pre-cleanup state has been copied. `release_unconfirmed` remains explicit.

The dedicated semantic query returns `active_availability` and suppresses active
payload on stale/stopped/clock-mismatched exports, stale module/entity samples,
fixture sources, unavailable players, unbound/changed sessions and changed native
map/instance. It re-ages accepted input on current active records. Terminal
records remain historical with sample ages and explicit current-binding comparison;
clock ambiguity yields a null age. Module and observer steady epochs are never
subtracted from one another. Wall/elapsed anchors provide their correlation.
Party/bot queries omit module records, so retained decisions cannot silently
become live dialogue facts. No gameplay commands or control authority are added.

CLI: `python -m cata_context --snapshot PATH --json modules GUID`.
Loopback GET: `/v1/modules/GUID`. Optional stdio MCP: `modules_get_observations`.
Missing provider/capture returns `module_unavailable`; out-of-scope returns no
data. A successful transport still requires inspection of semantic status,
source and active availability. Historical records are not current facts.
