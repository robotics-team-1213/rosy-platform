# OMX opposing-arm stacking — measured execution entries

## Current scope: Rosy Cam correction, one layer only

The user rejected the earlier layout. Current `omx-map-cube-stack` uses fixture
`rosycam-edge-terminal-first-layer-v3`: one common yellow workplate, both arm bases
on that plate facing each other, a lower conveyor over the gray map, and an
internal 90×90×30 mm target for three 90×30×30 mm bars. It stops at one layer.
The retained scenario identifier does not imply a completed 90 mm cube.

Topology follows the user's correction and the actual ceiling/close camera
stills captured on 2026-10-29. Dimensions remain nominal: 400×420 mm plate,
30 mm plate top, 25 mm conveyor top, arm spacing 260 mm. The target rectangle
is provisionally inside the plate; its exact photo registration is unmeasured.
The conveyor terminal now approaches the plate edge along -X, ending at x=.201
(1 mm nominal gap). Its stop is at x=.203 and cargo pickup at x=.250, 20 mm
closer than the former parallel-belt arrangement. The upstream -Y segment is
layout-only; cargo turn transfer is unverified. Rows use arms A/B/B. Release
height is 15 mm and planned row clearance 0.1 mm; acceptance tolerances remain
1.5 mm in position and 1 mm on the outer envelope. Exact registration and
learned-policy acceptance remain unverified.

Each entry below retains its own geometry, source and outcome. Superseded-map
results cannot establish success for the current arrangement.

### Terminal correction and lower release: bounded observations

- Source `534c98c0a4`, run `9ccf9d73839550d78980a28a10c05093`: terminal
  transported cargo from x≈.295 to .250 and stopped it at the plate edge.
  First placement passed; second ended at y=1.846 mm and failed. Opening
  snapshots located loss of finger contact around .583 s and first landing
  around .658 s, with approximately 7.93 N vertical contact force. This run
  had SDK exit0, verified import and confirmed owned cleanup.
  Report sha256: `66546cd390b9c440659fb70700058ac90ee2bceaa0c309f1b55112879e9c5c3c`.
- Source `81bae67682`, run `f0de57a9651455ebb5d828bc17a06d5b`: reducing
  release clearance35→15 mm retained the initial observed30 mm lift proof.
  Two placements logged passes, then an arm-A correction for the far row
  requested a point below the base and the owner planner refused it. SDK
  exit1, no final physical report. Owned cleanup was confirmed. These partial
  observations are not a completed layer or verified import result.
- Source `edbf49d6e0`, run `db17b3d401c45e13ac3f032371a8d3b5`: assigned
  the far row to the nearer arm B, blocked further correction after >.03 rad
  joint tracking error, and preserved bounded planner-refusal diagnostics.
  The raw report and artifact manifest passed independent read-only checks.
  All three bars settled, but the third center y=.031017 m plus its oriented
  extent exceeded the envelope tolerance by about21 µm. Physical task FAILED.
  Worker state remains UNKNOWN because its final cleanup check was not
  confirmed; no accepted final manifest was published. Later independent
  checks found MainPID0, no owned cgroup and GPU ready. The UNKNOWN record was
  retained and only its owned stale resource reservation was released.
- Source `c1786ef9d6`, run `254a87c630f8581dbdc53a5218438a36`: row
  clearance .2→.1 mm, with unchanged pose/contact/envelope criteria. Approved
  seed42 retry links the previous run as parent. SDKexit0, import verified,
  owned cleanup confirmed, physicalFAILED. All3bars settled, but the third
  center y=.031203907 plus oriented half width reached maxY=.046420896,
  exceeding the permitted .046 by .420896 mm. A rendered three-bar layer is
  not acceptance. Registered report786395 bytes.
  Report sha256: `3b8228db09636b50ae3e056ff85b5e691a03e0a2492431723c7734a7397bdcc4`.
- Source `5c89f3d1f3`: compensates the repeatedly observed positive first-row
  opening drift with a -.6 mm first-row release bias. The nominal acceptance
  targets and all position/contact/envelope tolerances stay unchanged. Focused
 32tests passed0NEW. Physical retry was refused by GPU admission while another
  compute process held194MiB; its result remains unverified. No unrelated
  process was stopped and no admission check was bypassed.

Validation: terminal focused27passes; lower-release focused29passes; nearer-arm
and final clearance focused31passes, each successful invocation0NEW. Source
`edbf49d6e0` broad regression807passed1skip plus one failure: an existing
report checksum was on a separate unlabeled line and triggered the entropy
guard. Metadata-only `972f2ae2d1` put its integrity label on the same line;
all80 release-boundary checks then passed0NEW. The scanner was not relaxed.

### Corrected layout, seed 42: scene rendered; first layer FAILED

Source `76587c5124a18760c8ef04ac2d5e9533e8af7d6e`, run
`3c2016972fc05704a1e30382efb37133`, Isaac Sim 6.2.0.0. The SDK completed
with exit 0, verified import and `OWNED_PROCESSES_EXITED_GPU_RELEASED` cleanup.
This is a failed physical task, not a completed layer or a trained policy.

Actual `mapped-top.png`, `mapped-initial.png` and `mapped-side.png` show the
common yellow plate, opposing bases, lower external belt and internal square.
The first bar passed lift, release and settling. After the second release,
the first and second bar centers settled at y=-32.624 mm and -2.624 mm,
respectively, outside the ±1.5 mm target tolerance. The next infeed was blocked.
The release sample was near the commanded pose; displacement appeared after
opening. The release/contact mechanism needs further diagnosis; no cause is
asserted from this observation alone.

Registered snapshot: `Rosy/artifacts/isaac/omx-opposed-floor-20261029/`
`3c2016972fc05704a1e30382efb37133-780cd59e10cf449db3609358875dedc5/`.
Report sha256: `119cab4bc340c10f70537b3790a71e4594ca827d8788a52170ca5809eb97f723`.

Remote validation for that source: 13 focused planning/acceptance tests passed;
broader Isaac/remote/OMX-owner/document regression: 514 passed and one ROS
xacro-overlay skip; affected guards: 336 passed. Each successful invocation
was compared with `test/known_failures.py`: zero new failures. Harness lint:
zero errors, 39 pre-existing status warnings after updating verification records. Exact camera registration, real
dimensions, first-layer physical success and learning success remain unverified.

CE: 미해결 — corrected scene is observed, but metric registration and the
post-release displacement remain unresolved. No solved lesson is claimed.

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
