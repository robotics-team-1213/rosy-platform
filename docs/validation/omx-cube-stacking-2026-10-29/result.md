# OMX opposing-arm stacking — measured execution entries

## Current scope: Rosy Cam correction, one layer only

The user rejected the earlier layout. Current `omx-map-cube-stack` uses fixture
`rosycam-opposed-first-layer-v2`: one common yellow workplate, both arm bases
on that plate facing each other, a lower conveyor over the gray map, and an
internal 90×90×30 mm target for three 90×30×30 mm bars. It stops at one layer.
The retained scenario identifier does not imply a completed 90 mm cube.

Topology follows the user's correction and the actual ceiling/close camera
stills captured on 2026-10-29. Dimensions remain nominal: 400×420 mm plate,
50 mm plate top, 25 mm conveyor top, arm spacing 300 mm. The target rectangle
is provisionally inside the plate; its exact photo registration is unmeasured.
Top, side and oblique SDK images are required for visual comparison. No
corrected-scene runtime or learning acceptance is claimed by this source edit.

The entries below describe the superseded map and retain their original
outcomes. They cannot establish success for the current arrangement.

Each dated entry binds its own source, run and outcome. The earlier three-bar
fallback success is recorded separately in
[the mapped stacking record](../omx-map-stacking-2026-10-29/result.md).
It does not establish nine-bar cube success.

The target uses nine 90×30×30 mm, 60 g bars in three rows and three layers,
inside a nominal 90×90×90 mm envelope. The Confluence page 8683759 plywood CAD
and field photo remain the map source; workbench registration is nominal and
photo-derived, without hardware calibration. Near rows use arm A, far rows arm B,
and the middle row alternates by layer, within the nominal SIM planning profile.

The fixed `omx-map-cube-stack` scenario runs one seed within the existing 900 s
service / 870 s SDK budget. Three independent seeded passes are the intended
repeatability check. Cargo enters only at external infeed; subsequent transport
uses physical contact. Original lift, expected support, release, retreat, speed,
position and envelope tolerances are retained. Reference and learned-policy
success remain separate; camera and hardware acceptance are unverified.

## 2026-10-29 — initial seed-42 cube attempt: FAILED

Source `5ea2fc7e5d3b87569ef5f2e1919a3389020c0d0e`, run
`eeb0dc35dfe158c9a42c1ac4001118b3`, Isaac Sim 6.2.0.0.
The first bar passed. After the second release, cargo centre y was approximately
0.055053 m instead of 0.045 m and rotation was about 90° around its long axis.
The bar had low final velocity, pallet support and no finger contact, but missed
the position criterion. The interlock blocked further infeed. Two of nine bars
were attempted; raw judgement was `nine_bars_not_completed`.

SDK exit 0, verified report, terminal FAILED and
`OWNED_PROCESSES_EXITED_GPU_RELEASED` were confirmed. Snapshot under workspace:
`Rosy/artifacts/isaac/omx-cube-20261029/eeb0dc35dfe158c9a42c1ac4001118b3-a0679db0bc024c5c8d5bfee29804e214/`.
Report: 248,768 bytes,
`sha256=d06c0c4f10b10cadc32b07d40a3171fff530624c9dbc411effb807f633540799`.
The actual final PNG was inspected. Intermediate carry/release observations were
absent, so this run alone does not identify the collision mechanism.

## 2026-10-29 — phase-observed seed-42 rerun: FAILED

Source `0b4f56d8b870a872a2d80516ac9be58ec04e23f0`, run
`9b7ff4d4133354bdb9e6d66e538520fe`. The physical commands and acceptance were
unchanged; carry, pre-release and post-opening snapshots were added.

The second bar remained nearly upright before opening. Its pre-release centre
y=0.04452506 m and measured y half-extent=0.01510753 m. The first bar's centre
y=0.01473950 m and half-extent=0.01513232 m. Thus their horizontal footprints
overlapped by approximately 0.455 mm while the second bar was held above the
first. After opening, the second bar rolled approximately 90° and moved to
y≈0.055053 m. This supports correcting the observed placement overlap before
the gravity release. It is not a general simulator-defect finding.

Both expected finger contacts were measured before opening; final pallet support
and finger release were observed. The same position failure blocked progress.
SDK exit 0, verified report, terminal FAILED and owned process/GPU cleanup were
confirmed. Snapshot under workspace:
`Rosy/artifacts/isaac/omx-cube-20261029/9b7ff4d4133354bdb9e6d66e538520fe-35b06ac6b63844bea02bb7b35919c014/`.
Report: 290,019 bytes,
`sha256=3f528a04abfa459b90a37e2669000317cef7ef88d078c879065316a8b0d16ed9`.

## Source verification at the measured-release stage

Source `4b88808273` passed 428 remote Isaac tests with one ROS xacro-overlay skip,
exit 0 / 0 NEW. This includes nine assigned-arm reach cases, expected-row support,
earlier-bar disturbance rejection, strict speed, report bounds and worker outcome
contracts. Source `5ea2fc7e5d` separately passed 20 remote transport tests.

The measured-release implementation computes the TCP correction from observed
cargo centre and oriented neighboring footprint, with a 0.2 mm clearance and a
bounded number of iterations. The independent reviewer identified the need for
a final retention/clearance check after the last correction and before opening.
This source verification is not a passing physical cube run.

CE: 미해결 — the full cube release mechanism is under correction. The earlier
fixed-root lesson remains verified for the fallback; no new solved lesson or
full-cube success is claimed by these diagnostic entries.

## 2026-10-29 — final release gate stopped seed 42: FAILED

Source `2689a0c35a994e59bd7386705dd415d79f9d1d25`, run
`4fecd020591e5bfc9a8872f52de14fc5`. The final gate prevented opening on the first
bar after four measured-correction moves. Bilateral retention was present, but
position correction remained approximately 0.868, 0.866, 0.866 and 0.865 mm.
Thus this was a retained-cargo convergence failure, not a completed placement.

The repeated calculation anchored the next target at measured TCP position.
Because the held cargo and measured TCP shared the loaded-arm tracking offset,
that expression repeatedly produced almost the same absolute IK target. The
observed constant error was not integrated into the next command. A regression
now models constant loaded-arm tracking bias; the next experiment accumulates
measured cargo error from the previous commanded TCP target. Final retention,
50 µm convergence and 1 µm neighbor-clearance-deficit gates remain unchanged.

SDK exit 0, verified report, terminal FAILED and owned cleanup were confirmed.
Snapshot under workspace:
`Rosy/artifacts/isaac/omx-cube-20261029/4fecd020591e5bfc9a8872f52de14fc5-03e2e1845cf8453e82fc39f0b65a32e0/`.
Report: 85,388 bytes,
`sha256=b840fc676499a68799272c723d89340191d173d271245589fe37ea495dcd81b1`.
No later seed was started by the failed-run orchestration.
