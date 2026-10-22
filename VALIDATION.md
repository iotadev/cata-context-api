# Release candidate validation — October 21, 2026

Version `0.4.0a1`, intended GitHub prerelease tag `v0.4.0-alpha.1`.

- Independent candidate suite: **58 tests passed** with Python 3.14 and the
  optional MCP SDK 2.3.0. Real stdio auto and legacy handshakes passed.
- The shared development suite passed **105 tests** separately. These are shared
  development checks, not 163 independent candidate tests.
- Own-profile reads pass; foreign-expansion snapshots are rejected by public
  query/MCP interfaces and internal consumer reads.
- Wheel and source distributions built successfully. The archive checker passed,
  including license/attribution, selected native source and excluded runtime data.
- Wheel installation outside the checkout passed in a clean isolated environment.
  Both expansion wheels also co-installed without profile or namespace collision.
- The known-pattern private-data scan found no matches in candidate source, and
  all relative Markdown links resolved. This is a focused check, not a guarantee
  against every possible secret format.

No new full native core build or live realm replay was run in this publication
batch. Native code was copied unchanged from its canonical adapter. See
QUALIFICATION.md for dated evidence and compatibility limits. Hosted GitHub CI
has not run; no remote, public push, tag or GitHub Release is implied by these
local checks. Logs, environments and private captures are excluded from source.
