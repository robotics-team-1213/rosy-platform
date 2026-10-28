# OMX map stacking — execution record

Status: **PASS — mapped deterministic three-layer reference, 3/3 seeded trials.**

Source `ea39371f17fdd57ae61c38396aa38e5693923203`, model-PC SDK 6.2.0.0,
run `03a9b112fb34518cb10997cc27e70d1e` completed with `SUCCEEDED`, verified
report, successful trials 3, and `OWNED_PROCESSES_EXITED_GPU_RELEASED`.
Seeds 42/43/44 each completed A/B/A pickup, unsupported contact lift, transport,
release and retreat. Every placed prefix and the final stack stayed accepted
over 1.1 s of observations after each release. Minimum observed cargo lift was
102.26 mm; maximum settled XY axis error was 0.927 mm. Cargo centre heights
were approximately 40/70/100 mm above the tabletop (25 mm pallet included).

This is the user's 3×1×3 fallback: 90×30×90 mm of cargo. It is not full mixed
3×3×3 packing, a learned-policy success, camera-based completion or hardware acceptance.

The user selected Confluence hardware architecture page 8683759, CAD attachment
8585450 and field photo 8585456. The board is 1.22 × 2.44 m. CAD paint is visually
transcribed; the yellow workbenches and cell pose are nominal photo-derived
simulation coordinates, without camera registration or hardware calibration.

The first physical target is three 90 × 30 × 30 mm, 60 g simulated bars, assigned
to arms A/B/A and stacked into a 90 × 30 × 90 mm envelope. The existing approved
model-PC SDK runner executes `omx-map-long-stack`; arbitrary attachment and scene
overrides are unavailable. New cargo is positioned only at external infeed/reset.
Transport uses contact physics. Success requires bilateral unsupported lift,
release, support by the expected lower body, retreat and stable earlier layers
over three seeded trials. The reference controller is deterministic IK.

## Executions

- Source `a7df4c5b90fbbedace767d0bdbff6808ef21f65f`, run
  `c7c29746d0ec5d818799cdc27333b5c4`: FAILED, missing report during model import.
  Importer interruption cause remains unconfirmed; owned cleanup completed.
- Same source, run `6d2e0b0b94d350c3a9a518cc9df7b4c9`: FAILED after actual map
  rendering and one attempted layer. Raw contacts show no bilateral free lift,
  substantial arm tracking error and displaced cargo. A subsequent infeed was
  displaced by the arm. This is not successful stacking. SDK exit was 0, report
  verification completed and owned process/GPU cleanup completed.
- Source `ac9d8e00db279444c88468d723b11f919abbd264`, run
  `1a991472d98c55b98079bd0b91293db2`: admission refused before SDK start while
  unrelated test workers held GPU contexts. No other session was interrupted.

Further diagnostic runs (all owned cleanup confirmed):

| Source | Run | Observation |
|---|---|---|
| ac9d8e00db | 3865b731c9e558eb8d3dbac764aa949f | Authored USD gains read back 57.3 times higher in native radian units; shoulder tracking failed. |
| c2a9316449 | 9667f71ae6585be7b7b2a54a5c8b6656 | Outward parking did not remove shoulder error (0.478 / 0.487 rad after 1 s). |
| 6baf8e3a88 | 5f777d8a7ac65d7f99595d9e909a1b46 | Native SI gains read back correctly; shoulder error remained. |
| bbbbf1bae1 | 47f3a762dfbe5c5eb6c942dee3a63c0d | Admission refused before SDK start. |
| 82214a247d | 6abc0e9751c059c49ae1411f7d848a30 | Native torque caps were 30 Nm, force modes matched, applied position targets matched, velocity targets were zero. Shoulder error remained. |
| 7532a4331a | af413f1cb6155ad8933d1cf62507e9f1 | Solver 64/16 reduced shoulder errors to 0.076/0.077 rad. Native body masses included a default 1 kg TCP frame absent from URDF inertia. |
| 5ccbad9154 | c18f9af9ca8a5e59a0c3f456a3f9f512 | Removing the TCP rigid body and fixed joint removed the extra mass, but articulation became nonfinite during initialization/first hold. |

The subsequent experiment authors moderate SI gains in USD degree units and
solver iteration counts before `world.reset`, in addition to runtime readback.
Neither the numerical failure nor complete physical stacking is resolved yet.

Artifacts for the second run are under workspace
`Rosy/artifacts/isaac/omx-stacking-20261029/6d2e0b0b94d350c3a9a518cc9df7b4c9-305f304bc6b34b7d9318db6af820d4e0/`.
The source run manifest binds the raw report and actual 800 × 600 PNGs.

Accepted artifacts are under workspace
`Rosy/artifacts/isaac/omx-stacking-20261029/03a9b112fb34518cb10997cc27e70d1e-3cda294dfabc45ec878a9add9a0600c9/`.
The bounded report is 455,980 bytes, SHA-256
`sha256=6f2d6eaff258dcbcdddc84aa37f9955a8fcd5658f9ba01d420af849b3ae4e0df`.
Actual images include the map overview, initial workcell, layers 1/2/3 and each
trial's final state. `mapped-layer-3.png` SHA-256 is
`sha256=a35f8ea27734afe5339324ad4919951e08ee42d36f21e4563ef962187f115ce7`.

The successful continuation corrected imported topology and collider traversal:

- `30110634c2` / `3a0755127fc85e619e85ea7ebc3aa2aa`: moving the articulation root
  to the world fixed joint produced native fixed bases and joint errors below
  0.0001 rad; layer 1 passed. Layers 2/3 did not grasp.
- `b52addebb3` / `aa7e3302ff2f5363b3e169fcd37935f9`: narrowed pre-open, 2 mm TCP
  grasp offset and free-lift interlock prevented unheld transport; B still blocked.
- `0e828fb1be` / `60db677816ae5eb4a991ca4e223fb050`: per-link contacts proved B's
  original finger hull touched already-placed cargo before closure.
- `98d89b3631` / `c848b42aba8452baac523a27610a48c2`: admission refused before SDK.
- `ea39371f17` / accepted run above: deinstanced imported robot geometry before
  traversing colliders, so original finger hulls were disabled and each finger
  retained exactly one calibrated capsule. All 3 layers passed in all 3 trials.

## Separate earlier PPO smoke

The current map was subsequently used by `omx-map-stacking-rl` on source
`77d74168bb` (full source binding in its snapshot), run
`394741d76b9c582e97bdabc48dd9aef0`. It completed 32 updates / 1,024 transitions
with finite parameter delta 0.5232045650482178 and confirmed owned cleanup.
The separate evaluation seed 10042 ran 6,000 control steps (200 simulated seconds)
and completed **0/1** stacks. The policy directly controls bounded joint motions;
it does not replay the successful reference trajectory.

Its checkpoint is 200,319 bytes, SHA-256
`sha256=cbe0e45f25949a4930c6258cd276c3d9a96f94fd1b7562e705a34bdacb58823a`.
Its report is 2,518 bytes, SHA-256
`sha256=d13d69d51a13ce16d84e1835af0104e0fdf741e3438f5e881bc9b5fcdbe3705c`.
The snapshot is under workspace
`Rosy/artifacts/isaac/omx-stacking-20261029/394741d76b9c582e97bdabc48dd9aef0-5012136c47b44dfcb3211666b040d0d5/`.
This proves mapped training integration, not learned palletizing proficiency.

Source `83e3d61303703e6dc334f96ad2e72adaf6bea1d0`, run
`c6cb3a15e1985f0bb686c272867734ce`: the earlier synthetic cell completed 32 PPO
updates / 1,024 transitions and changed finite policy parameters (delta
0.6181039810180664). Physical evaluation success was **0/1**. This does not prove
mapped stacking, learned task proficiency, vision-based completion or hardware
acceptance. It used direct simulator state observations.

## Source verification

The mapped fixture/IK/catalog/contact-acceptance suite on `a7df4c5b90` passed
4 remote tests. Full Isaac regression on `ac9d8e00db` passed 415 tests and skipped
one ROS xacro-overlay-dependent test, exit 0 / 0 NEW. Later runtime changes need
their own verification; that source result does not establish physical success.
The mapped-RL source `729acc9729` then passed 417 tests, skipped one and had
0 NEW. The `77d74168bb` runtime additionally verified the corrected grasp-goal
variable and one-episode mapped RL metadata. Final affected checks follow below.

## Scope and remaining uncertainty

Fixed-base state, drive units, masses, original finger hulls and imported Newton
mimic were checked during the investigation. The final scene uses a derived
physical URDF without a default-mass TCP body and restores its visual frame.
It uses bounded nominal drives and model gravity compensation. Vendor assets
and hardware settings were not edited. The initial isolated importer interruption
has no verified explanation and is retained as a failed run.

CE: 새 교훈 기록 — [fixed-joint articulation root](../../solutions/runtime-errors/isaac62-omx-fixed-joint-articulation-root-2026-10-29.md)
records the verified native topology discrepancy and correction. Initial importer
interruption remains unexplained; physical stacking success does not resolve that event.
