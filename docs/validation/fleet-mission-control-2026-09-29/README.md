# Fleet Mission control implementation evidence — 2026-09-29

## Scope

Source-only implementation work on the isolated `feat/fleet-mission-control` worktree. No site API or Mission executor was enabled, no ROS goal was submitted, and no physical stop or robot motion was exercised.

## Implemented

- Shared durable resource claims arbitrate task, Mission, and direct-action owners for robot, workcell, and object resources. Normal reservations must enter as `CLAIMED`; restoring unresolved external work uses a separate recovery-only path while dispatch is closed.
- Fleet dispatch starts closed. An explicit operator rearm advances the persisted stop generation. A Mission Step can transition `READY → RUNNING` only while the expected generation is still enabled and its full resource claim is held.
- The internal single-step Mission journal stores idempotent proposals, immutable `PICK_PLACE` goal predicates, admission, attempt correlation, terminal Action results, and goal evidence in the same SQLite database as Fleet claims.
- Driver `SUCCEEDED` becomes `ACTION_SUCCEEDED`, not Mission completion. Fresh matching `camera_observation` evidence is required to become `GOAL_CONFIRMED` and release claims. Invalid goal evidence holds the Mission. Model-authored completion text is not accepted as goal evidence.
- The Mission store is internal SOURCE code only: it has no REST route, scheduler executor, or OMX/ROS submission binding.

## Verification

| Command | Result |
|---|---|
| `python -m pytest src/site/fleet/test/test_mission_store.py src/site/fleet/test/test_mission_service.py src/site/fleet/test/test_goal_evidence.py -q` | 15 passed |
| `python -m pytest src/site/fleet/test/ -q` | 578 passed, 5 skipped |
| `python -m pytest src/products/omx/adapter/test/ -q` | 72 passed, 3 skipped |
| `python test/test_network_topology_contracts.py test/test_harness_contracts.py -q` | Passed |
| `python tools/harness/rosy_harness.py lint` | 0 errors, 18 freshness warnings |
| `python tools/harness/rosy_harness.py generate` | Generated Fleet and OMX adapter indexes after execution-record update |
| `flake8 <changed Python files>` | Not run: `flake8` command is not installed in this environment |

The preceding Fleet/OMX implementation commits and their focused evidence are summarized in `docs/plans/2026-09-29-fleet-mission-control-arbitration-implementation.md` and `docs/validation/er2-omx-action-baseline-2026-09-29/README.md`.

## Limits and next gate

This evidence does not prove that a site/network stop always reaches the robot, that the robot consumes and fences the stop generation, that an independent physical E-stop exists, or that gripper/camera feedback is calibrated and trustworthy. The camera goal evidence contract is a source-level check; provenance authentication must be established before any public submission path. OMX remains disabled and the Mission ledger cannot dispatch. ROS-SIM fault injection, target artifact, DEVICE, and FIELD acceptance remain open.
