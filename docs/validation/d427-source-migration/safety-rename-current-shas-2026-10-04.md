# D-427 safety rename final independent audit

- Frozen reviewed HEAD: `69779adb524e` (push5 in progress; untouched).
- Current remote baseline: `7e26295117b9`.
- Pure migration endpoint: `d7409e996481`; later deliberate behavior commits are excluded from rename equivalence.
- Reviewer: independent d427_safety_review; read-only repository; this report and script only under X:.

## Existing evidence and coverage gap

- Existing tracked evidence: `docs/validation/d427-source-migration/safety-rename-review-2026-10-04.md` (last touching commit `f4a99840ff5f`). It records prior `c402cc45e..6820c2dc5` review, old relocation SHAs, 17 modules/35 anchors/3 roots, and 21 known violations.
- The existing record is substantive prior review evidence but is not by itself a current rebased-candidate per-commit proof: its IDs predate the latest origin rebase and sensing scope lacks a specific relocation SHA. This audit supplies that missing current-SHA link.
- Its raw local evidence remains `X:/DevTemp/rosy-d427/resume/review/inspect.txt` and `commits.txt`; raw text alone is not durable device/artifact acceptance.

## Current relocation SHA mapping

| Scope | Previously reviewed SHA | Current SHA |
|---|---|---|
| signal | `dd6238b08` | `9711e2da3598` |
| dock | `6ea10c14b` | `cad0caad9149` |
| Fleet | `040ef50ff` | `d44aaada50a3` |
| OMX | `6b0bb9f02` | `ea62919a7b11` |
| CORE | `21de6b578` | `3cc2bdd8a250` |
| sensing safety subtree | prior aggregate review | `67f83db1ca69` (wave 4e) |

## Source equivalence

- Explicit old-path  ->  manifest target-path blob checks: **31 safety production files**, **30 byte-identical**, **1 docstring-only** (console.py). All executable AST nodes of the latter are identical after removing documentation.
- Safety file scope: all 17 listed modules, production files beneath all three safety roots, and the eight ROS sensing safety Python files. Empty `__init__.py` blobs have identical content; git can assign their R100 match to another identical empty module, so explicit destination blob checks prevent relying on that heuristic.
- No safety execution behavior change found inside migration commits, including migration residue. Non-R100 console path link is the known documentation issue recorded by the original review. Other non-safety package web/resource/path corrections are outside this safety rename equivalence claim.

## Manifest and known violations

- Migration modules **17 -> 17**, exact set after manifest path remapping.
- Migration anchors **35 -> 35**, exact ordered values.
- Migration safety roots **3 -> 3**, exact target paths and retained safety concerns; legacy fields added for provenance.
- `KNOWN_SAFETY_VIOLATIONS` **21 -> 21 -> 21**, exact dictionary equality after old-path remapping (baseline -> migration -> current). No new waiver.
- Current safety fixes intentionally add tags: modules now 21, anchors now 40. Every migration module and anchor remains present. These additions are not rename-only claims.

## Per-commit git diff -M evidence

| SHA | Subject | Monitored safety changes |
|---|---|---|
| `9711e2da3598` | refactor(d427): move firmware/signal to operations/site_devices/signal | 1 R100 |
| `cad0caad9149` | refactor(d427): move firmware/dock to operations/site_devices/dock | 1 R100 |
| `d44aaada50a3` | refactor(d427): wave 3c bulk move (299 files) | 1 R099, 5 R100 |
| `ea62919a7b11` | refactor(d427): wave 4c bulk move (477 files) | 3 R100 |
| `3cc2bdd8a250` | refactor(d427): wave 4d bulk move (566 files) | 13 R100 |
| `67f83db1ca69` | refactor(d427): wave 4e bulk move (731 files) | 8 R100 |

`git diff -M <sha>^ <sha> --name-status` was used for every migration commit; only those touching the monitored safety file set appear above. All wave 3b -> 4e migration commits were traversed.

## Sole non-identical safety production file

```diff
--- src/site/fleet/fleet/server/console.py

+++ operations/fleet/fleet/server/console.py

@@ -1,6 +1,6 @@

 """사이트 오케스트레이터의 관제 표면 — 모음(gather)과 흩뿌림(scatter).

-역할 경계는 [사이트 미들웨어 역할 패브릭 설계](../../../../docs/plans/2026-09-14-site-middleware-role-fabric-design.md)
+역할 경계는 [사이트 미들웨어 역할 패브릭 설계](../../../docs/plans/2026-09-14-site-middleware-role-fabric-design.md)
 §2 가 정한다. 이 모듈이 하는 일은 등록된 로봇의 상태를 모으고, 원자 액션
 (goal / cancel / e-stop)을 내리는 것뿐이다. 하지 않는 일:

```

## Separate deliberate safety behavior commits

- `fcf8ce3f10e5`: fix(fleet): supervise signals and fence stale operator intent. Separately reviewed behavior; not part of rename equivalence.
- `f425eae33237`: fix(safety): keep live manual control against autonomous navigation. Separately reviewed behavior; not part of rename equivalence.
- `cffd0a6044de`: fix(omx): latch preemption and expose audited owner recovery. Separately reviewed behavior; not part of rename equivalence.
- `60ed52480cc1`: fix(pinky): bind final Twist writes to a single-use original guard. Separately reviewed behavior; not part of rename equivalence.
- `aaf40fd0c`: charging safety tagging; `65941ea1a`: static learned-policy configuration guard; `0b3d90470`: attribute-independent cmd_vel publisher static gate. These are separate source changes, not movement.
- `69779adb5`: test ownership/type-name exception and internal guard marker correction; previously independently approved, not treated as migration behavior equivalence.

## Qualified verdict

**APPROVE safety rename source review**: no movement-contained safety behavior defect found. Current-SHA/per-commit, module/root/anchor preservation, and known-violation-count evidence is now sufficient for the source-review part of P1-3. The plan separately requires main landing; HEAD is still a candidate here. Push5/CI/ARM64 payload/SD equivalence/ROS-SIM/DEVICE/FIELD are not proven by this audit.

## Raw filtered name-status details

### 9711e2da3598 refactor(d427): move firmware/signal to operations/site_devices/signal

```text
R100	firmware/signal/firmware/rosy_signal/rosy_signal.ino	operations/site_devices/signal/firmware/rosy_signal/rosy_signal.ino
```

### cad0caad9149 refactor(d427): move firmware/dock to operations/site_devices/dock

```text
R100	firmware/dock/firmware/rosy_dock/rosy_dock.ino	operations/site_devices/dock/firmware/rosy_dock/rosy_dock.ino
```

### d44aaada50a3 refactor(d427): wave 3c bulk move (299 files)

```text
R100	src/site/fleet/fleet/server/cancel_all.py	operations/fleet/fleet/server/cancel_all.py
R100	src/site/fleet/fleet/server/cancel_all_store.py	operations/fleet/fleet/server/cancel_all_store.py
R099	src/site/fleet/fleet/server/console.py	operations/fleet/fleet/server/console.py
R100	src/site/fleet/fleet/server/dispatch_admission.py	operations/fleet/fleet/server/dispatch_admission.py
R100	src/site/fleet/fleet/server/local_stop_transport.py	operations/fleet/fleet/server/local_stop_transport.py
R100	src/site/fleet/fleet/server/task_dispatch_routes.py	operations/fleet/fleet/server/task_dispatch_routes.py
```

### ea62919a7b11 refactor(d427): wave 4c bulk move (477 files)

```text
R100	src/products/omx/adapter/omx_adapter/action_api.py	middleware/apps/device/omx/adapter/omx_adapter/action_api.py
R100	src/products/omx/adapter/omx_adapter/command_owner.py	middleware/apps/device/omx/adapter/omx_adapter/command_owner.py
R100	src/products/omx/adapter/omx_adapter/local_stop.py	middleware/apps/device/omx/adapter/omx_adapter/local_stop.py
```

### 3cc2bdd8a250 refactor(d427): wave 4d bulk move (566 files)

```text
R100	src/contracts/foundation/core_common/robot_body.py	contracts/foundation/core_common/robot_body.py
R100	src/runtime/api_web/core_api_web/api/v1/safety.py	middleware/core/api_web/core_api_web/api/v1/safety.py
R100	src/runtime/gateway/core/bridge/cmd_vel.py	middleware/core/gateway/core/bridge/cmd_vel.py
R100	src/runtime/gateway/core/fleet_loss_wiring.py	middleware/core/gateway/core/fleet_loss_wiring.py
R100	src/runtime/services/core_features/command/arbitration.py	middleware/core/services/core_features/command/arbitration.py
R100	src/runtime/services/core_features/command/manager.py	middleware/core/services/core_features/command/manager.py
R100	src/runtime/services/core_features/line_follow/body_stop.py	middleware/core/services/core_features/line_follow/body_stop.py
R100	src/runtime/services/core_features/line_follow/clearance.py	middleware/core/services/core_features/line_follow/clearance.py
R100	src/runtime/services/core_features/safety/__init__.py	middleware/core/services/core_features/navigation/__init__.py
R100	src/runtime/services/core_features/state/__init__.py	middleware/core/services/core_features/safety/__init__.py
R100	src/runtime/services/core_features/safety/fleet_loss.py	middleware/core/services/core_features/safety/fleet_loss.py
R100	src/runtime/services/core_features/safety/manager.py	middleware/core/services/core_features/safety/manager.py
R100	src/runtime/services/core_features/safety/shadow.py	middleware/core/services/core_features/safety/shadow.py
```

### 67f83db1ca69 refactor(d427): wave 4e bulk move (731 files)

```text
R100	src/runtime/sensing/control/safety/__init__.py	middleware/perception/control/safety/__init__.py
R100	src/runtime/sensing/control/safety/bumper.py	middleware/perception/control/safety/bumper.py
R100	src/runtime/sensing/control/safety/evidence.py	middleware/perception/control/safety/evidence.py
R100	src/runtime/sensing/control/safety/gate.py	middleware/perception/control/safety/gate.py
R100	src/runtime/sensing/control/safety/hazard.py	middleware/perception/control/safety/hazard.py
R100	src/runtime/sensing/control/safety/node.py	middleware/perception/control/safety/node.py
R100	src/runtime/sensing/control/safety/obstacles.py	middleware/perception/control/safety/obstacles.py
R100	src/runtime/sensing/control/safety/scale.py	middleware/perception/control/safety/scale.py
```


## Additional completeness checks

- At every one of the 26 rebased migration/residue commits: 17 mapped safety modules, 35 unchanged anchor values, 3 safety concerns, and 21 exact remapped known violations. No temporary/new safety waiver or dropped tag was observed.
- Production file membership under each migrated safety root is exact after path mapping; no new unreviewed production member was added in the migration endpoint.
- Firmware AGENTS non-R100 entries are documentation link rewrites recorded in the prior independent review; the actual two .ino runtime files are R100 in the current commits.
