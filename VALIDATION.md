# Alpha 1 validation â€” October 21, 2026

Version `0.4.0a1`, published GitHub prerelease tag `v0.4.0-alpha.1`.

- Independent release suite: **58 tests passed** with Python 3.14 and the
  optional MCP SDK 2.3.0. Real stdio auto and legacy handshakes passed.
- The shared development suite passed **105 tests** separately. Do not add this count
  to the independent release suite.
- Own-profile reads pass; foreign-expansion snapshots are rejected by public
  query/MCP interfaces and internal consumer reads.
- Wheel and source distributions built successfully. The archive checker passed,
  including license/attribution, selected native source and excluded runtime data.
- Wheel installation outside the checkout passed in a clean isolated environment.
  Both expansion wheels also co-installed without profile or namespace collision.
- The known-pattern private-data scan found no matches in the prepared release source, and
  all relative Markdown links resolved. This is a focused check, not a guarantee
  against every possible secret format.

No new full native core build or live realm replay was run in this publication
batch. Native code was copied unchanged from its canonical adapter. See
[QUALIFICATION.md](QUALIFICATION.md) for dated evidence and compatibility limits.

[Hosted GitHub validation](https://github.com/iotadev/cata-context-api/actions/runs/39730890696)
passed for the [published alpha 1 source](https://github.com/iotadev/cata-context-api/tree/v0.4.0-alpha.1):
core Python 3.10, optional MCP on Python 3.11/3.14 (including Windows 3.14),
and package build/install checks.
The release includes source ZIP, Python wheel/source distribution and SHA-256
checksums. Published asset digests and main/tag commits were verified. These
results apply to the tagged release, not automatically to later changes. Logs,
environments and private captures are excluded from source.

The October 22 documentation review updates setup and release status on the
working branch; the alpha 1 tag and downloadable archives retain their original
contents. That review also adds the section header required when loading the
Cata config as a separate module file; no configuration values changed.
