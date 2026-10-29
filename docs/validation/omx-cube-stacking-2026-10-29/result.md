# OMX full cube stacking — measured execution entries

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
