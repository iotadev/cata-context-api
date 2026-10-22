# Installation and usage

## Native exporter

Start with the core's existing server build prerequisites and a compatible
Playerbots module. This package supplies neither a server binary nor game data.
Read [qualification](QUALIFICATION.md) before selecting revisions.

Copy **the contents of `server-module/`** into a new
`modules/mod-context-api/` directory in the core source tree. Cloning this entire
repository into that module directory would leave the native sources one level
too deep. Review any existing installation before replacing it.

Use [iotadev/TrinityCore](https://github.com/iotadev/TrinityCore) with
[iotadev/cata-playerbots](https://github.com/iotadev/cata-playerbots). The
[matching-source record](QUALIFICATION.md#current-matching-source-preflight)
identifies commits with the required observation hooks. Archived integration
patches are references; do not reapply hooks already present. Configure the core
with `-DMODULE_MOD_CONTEXT_API=ON` and build/install through its usual workflow.

Copy `server-module/conf/context-api.conf.dist` to `context-api.conf` in the core
module config directory: by default, `modules/` beside the selected
`worldserver.conf`, or the directory set by `Modules.ConfigDirectory`. Keep the
`[worldserver]` section header; the Cata loader requires one non-empty INI section.
The original alpha archive omitted that header: add it when using that archive.

Set the scope and destination in the active config. For example:

```ini
ContextAPI.Enabled = 1
ContextAPI.Characters = "123,456"
ContextAPI.SnapshotFile = "/absolute/path/to/context-api/snapshot.json"
ContextAPI.IntervalMs = 1000
```

Replace `123,456` with one to eight unique positive **player GUID counters** from
your realm; they are not account IDs or character names. Use comma separators
without spaces, and include the human controller if you want its state sampled.
Use a writable path for the worldserver and the same readable path for the Python
process. On Windows, a path such as `G:/realm/context-api/snapshot.json` is valid.
Relative snapshot paths resolve from the worldserver's working directory.

These settings are read at startup; apply them during a planned realm restart.
After selected characters are online, check that the snapshot exists and the
queries below report fresh samples. A newly enabled observer may initially report
`unobserved` or `awaiting_sample`; missing observations are not assumed offline.

Optional `ContextAPI.Movement = 1` adds movement flags and configured unit speeds.
It does not measure actual velocity or provide collision/physics state.
Cata also supports `ContextAPI.DiagnosticDetails = 1` for native phase and
selected-unit/attack-victim geometry. `ContextAPI.ActionHistory = 1` additionally
requires `Playerbots.Diagnostics.Actions.Enabled = 1` in the active Playerbots
config. History records engine admission/execution observations, not proof that a
spell landed or completed.

## Python and command line

From this repository's root, create an environment and use its Python executable.
For example, on Windows:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/python.exe -m cata_context --snapshot G:/realm/context-api/snapshot.json party
```

On Linux/macOS, use `.venv/bin/python` instead. The following examples assume the
environment is activated. Replace the snapshot path and GUID for your realm:

```sh
python -m cata_context --snapshot /absolute/path/snapshot.json capabilities
python -m cata_context --snapshot /absolute/path/snapshot.json party
python -m cata_context --snapshot /absolute/path/snapshot.json --json bot 123
python -m cata_context --snapshot /absolute/path/snapshot.json serve --port 8765
```

The browser view is at `http://127.0.0.1:8765`. It also serves read-only JSON at
`/v1/capabilities`, `/v1/party` and `/v1/bots/GUID`. GUID arguments use the full
canonical decimal strings returned by the snapshot/query scope. The default
freshness limit is 5000 ms; global options such as `--json` and `--max-age-ms`
go before the subcommand. Check the response status and each entity's availability.
A successful HTTP/MCP exchange alone does not mean the data is fresh.

`actions GUID --after-sequence 0 --limit 16` reads bounded history when supported.
`capture-movement GUID --duration-seconds 10 --interval-ms 250` collects bounded
historical samples; polling faster does not increase native sampling frequency.
`modules GUID` queries optional module records when advertised by capabilities.

## MCP client

Install the optional dependency using Python 3.11 or newer:

```sh
python -m pip install ".[mcp]"
python -m cata_context.mcp_server --snapshot /absolute/path/snapshot.json
```

The second command waits for MCP messages over standard input/output; it does
not open a web service. Configure your MCP client with
[the example JSON](examples/mcp-client.example.json), replacing the Python and
snapshot paths with absolute paths. Use the environment's Python that has the
MCP dependency installed. Client registration is manual.

Start with `cata_get_capabilities`, then use `game_get_party` or
`playerbots_get_bot_state`. `playerbots_get_action_history` and
`modules_get_observations` return explicit unavailable results when the native
capability is absent. Resources are `cata://contract` and
`cata://capabilities`. No tool accepts an arbitrary snapshot path or gameplay
command; the snapshot path is fixed when the server starts.

## Existing consumers and development

Earlier shared-workspace consumers used `game_context`. This release uses
`cata_context` imports and launch commands; update each owning consumer explicitly.
It does not install the old shared namespace or automatically migrate Chatter.

To check a source checkout:

```sh
python -m unittest discover -s tests -v
python -m pip install build
python -m build
python scripts/check-release.py --artifacts dist
```

MCP tests skip explicitly if its optional dependency is absent. See
[release validation](VALIDATION.md) for the results associated with alpha 1.
