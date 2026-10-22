# License and provenance

This project is distributed under the GNU General Public License, version 2
or (at your option) any later version. See [LICENSE](LICENSE). Existing upstream
copyright notices and attribution remain applicable.

The Cataclysm adapter targets the [iotadev TrinityCore fork](https://github.com/iotadev/TrinityCore),
derived from the [Cataclysm Preservation Project](https://github.com/The-Cataclysm-Preservation-Project/TrinityCore).
The WOTLK adapter targets [AzerothCore](https://github.com/azerothcore/azerothcore-wotlk)
with [mod-playerbots](https://github.com/mod-playerbots/mod-playerbots).
The native adapters use those projects' interfaces and preserve their ownership
boundaries; they are not interchangeable core modules. Native source headers
retain their GPL notices. Integration patches must retain the notices in their
target files when applied.

The shared Python reader, query, capture and consumer helpers are part of this
project. The optional MCP extra uses the separately distributed
[official Python SDK](https://github.com/modelcontextprotocol/python-sdk);
it is not vendored here. Each dependency retains its own license.

This repository contains source, contracts and synthetic tests. Game clients,
extracted game data, databases, credentials and private runtime captures are not
part of the distribution. Dated qualification documents describe observations,
not guarantees about an arbitrary server or current deployment.
