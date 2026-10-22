# Compatibility and qualification

This is a source alpha, not a prebuilt or universally compatible core module.
Target: TrinityCore build 15595; native module directory `mod-context-api`.

Earlier isolated native build evidence used core base `80d1fc7491d24741de1c2954ddbe307dc331584d` and
Playerbots base `1e108ca6c2451afb528aae151532dcf8610af563`, with additional recorded development inputs.
These base SHAs are not a claim that every release file was tested against an
immutable clean pair. Retain exact source/binary identity for your deployment.
The source hash manifest identifies this release's shared Python inputs.

Python/package and hosted CI results are recorded in [VALIDATION.md](VALIDATION.md).
Publication did not include a fresh full native core build or live realm replay.
Earlier native observations include copied-state lifecycle and observer operation;
broader controller transitions, native overhead, client outcomes and complete
dungeon behavior remain unqualified.

Completed Cata far transfers remain unqualified.

Cata requires the matching iotadev/TrinityCore optional-module and copied Playerbot observation hooks, with iotadev/cata-playerbots. Stock TrinityCore is not a drop-in target. The integration patches are historical reference artifacts: check applicability and never reapply hooks already present. The known no-PCH Creature include fix was carried into the canonical Playerbots source during publication preparation.

## Current matching-source preflight

The October 21 clean source commits `2e03c2a31ee39bd2c39f958014fed9b5de607307` (iotadev/TrinityCore)
and `39e7000b6a361bbd455ac006efb6d0d386febe13` (iotadev/cata-playerbots) contain the copied
observation hooks and the no-PCH Creature include correction. This was checked
from committed source. Do not reapply archived hook/include patches to these
files. This source preflight is not a fresh native build/runtime qualification;
the older isolated native build above retains its own dated input identity.
