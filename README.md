# Cataclysm Context API

Read-only game and Playerbots context for **Cataclysm build 15595 / TrinityCore**.
A small server module copies state for selected characters into a JSON snapshot.
The Python package makes that snapshot available through a command line, a local
browser view, queries and an optional MCP server for development tools.

Use it to inspect health, power, position, combat state, selected targets and
observed group membership while investigating bot behavior.

Cata bot diagnostics include controller/follow targets, strategy roles, engine
state and queue counts. Optional capture adds phase, attack-victim/facing data
and bounded engine action history.

This is an experimental alpha. It observes server state; it does not log in as a
WoW client or issue gameplay commands. Samples retain their age and availability,
so stale or missing observations are not presented as current facts. The selected
characters are a configured scope, not a guaranteed complete party roster.

## Get started

1. Read [compatibility and validation limits](QUALIFICATION.md). The native
   module needs a matching core and Playerbots checkout.
2. Download the [alpha source release](https://github.com/iotadev/cata-context-api/releases/tag/v0.4.0-alpha.1)
   or clone this repository. The source contains both the native module and Python
   interfaces; the wheel contains only the Python interfaces.
3. Follow [installation and usage](USAGE.md) to build the native module, select
   characters, enable snapshots, and connect the CLI or MCP client.

The native module defaults off. Python requires 3.10+ for queries and the CLI;
optional MCP requires 3.11+. No model service is needed to collect or inspect data.

## Project information

- [Usage and MCP setup](USAGE.md)
- [Compatibility and native qualification](QUALIFICATION.md)
- [Release validation](VALIDATION.md) and [release notes](RELEASE_NOTES.md)
- [Snapshot contract](contracts/SNAPSHOT_V1.md) and
  [expansion differences](contracts/EXPANSION_PROFILES.md)
- [License and credits](NOTICE.md) â€” GPL-2.0-or-later

This repository owns its native module and `cata_context` query/MCP interfaces.
The [other expansion](https://github.com/iotadev/wotlk-context-api)
is released separately. Common helper code is bundled under a private namespace;
[SHARED-SOURCE.json](SHARED-SOURCE.json) records the shared input hashes. Neither
package depends on the other, and each rejects the other expansion's snapshots.
