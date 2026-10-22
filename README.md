# Cataclysm Context API

Experimental read-only realm context for **Cataclysm, build 15595, TrinityCore**.
This is an independent expansion release with its own query/MCP entry points,
native compatibility requirements and release cadence. It does not accept the
other expansion's snapshots, even through its internal shared helpers.

## Install Python interfaces

Python 3.10+ is required for the stdlib-only CLI/query layer; optional MCP needs
Python 3.11+. From this source checkout:

```sh
python -m venv .venv
# Use .venv/Scripts/python.exe on Windows; .venv/bin/python on Linux/macOS.
python -m pip install .
# Or install the optional official MCP SDK dependency in the chosen environment:
python -m pip install ".[mcp]"
python -m cata_context --snapshot /absolute/path/context-api/snapshot.json capabilities
python -m cata_context.mcp_server --snapshot /absolute/path/context-api/snapshot.json
```

Activate the environment first or use its Python executable explicitly. The MCP
command waits for stdio protocol messages from a local MCP client. See
[the client example](examples/mcp-client.example.json); replace its two paths.
No automatic client registration, public listener or remote hosting is supplied.

For consumers of the earlier shared development tree, use `cata_context` instead
of `game_context` imports and launch commands. This release does not install the
shared `game_context` namespace. Update and pin any owning consumer (including an
optional Chatter worker) separately; this is not an automatic deployment migration.

## Install the native module

Copy `server-module/` into a **new** `modules/mod-context-api/` directory in the matching
TrinityCore source checkout. Do not overwrite an existing module. Use the core's normal
static-module build/configuration workflow. Runtime configuration defaults off.
Choose scoped player GUID counters and a trusted snapshot path explicitly.
Installation starts no services and changes no account, database or game state.
Optional engine action history requires the matching Playerbots collector and both native gates.

See [compatibility and qualification](QUALIFICATION.md) before building. The
wheel contains only Python interfaces and licenses; the source archive contains
the native module, contracts and tests. No server binary, database, client/game
data, credentials, model runtime or private captures are distributed.

Local release checks are recorded in [VALIDATION.md](VALIDATION.md).

## Boundaries

All reads preserve source, build, realm, boot, session, scope and freshness.
Missing, stale, stopped and unavailable data are never presented as live state.
Configured scope is not a complete roster or an atomic multi-map snapshot.
Server state is not client-rendered/packet-observed state. Action returns do not
prove asynchronous completion or landed spells. No gameplay controls are exposed.

The public `cata_context/queries.py` and `cata_context/mcp_server.py` belong to this
expansion and can evolve independently. `_cata_context_core/` contains common copied
value/validation/freshness/transport helpers; [SHARED-SOURCE.json](SHARED-SOURCE.json)
records identical input hashes for carrying common fixes between releases.
It is bundled source, not a dependency on the other expansion or a shared server.

## Validate

```sh
python -m unittest discover -s tests -v
python -m pip install build
python -m build
python scripts/check-release.py --artifacts dist
```

MCP tests are skipped explicitly when its optional dependency is absent. GitHub
CI is configured for core Python 3.10 and optional MCP on 3.11/3.14, including
Windows. A configured workflow is not evidence that hosted jobs have run.

GPL-2.0-or-later; see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
