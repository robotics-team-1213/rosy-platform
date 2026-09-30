# Fleet Mission control implementation evidence — 2026-09-29

## Scope

Source-only implementation work on the isolated `feat/fleet-mission-control` worktree. No site API or Mission executor was enabled, no ROS goal was submitted, and no physical stop or robot motion was exercised.

## Implemented

- Shared durable resource claims arbitrate task, Mission, and direct-action owners for robot, workcell, and object resources. Normal reservations must enter as `CLAIMED`; restoring unresolved external work uses a separate recovery-only path while dispatch is closed.
- Fleet dispatch starts closed. An explicit operator rearm advances the persisted stop generation. A Mission Step can transition `READY → RUNNING` only while the expected generation is still enabled and its full resource claim is held.
- The internal single-step Mission journal stores idempotent proposals, immutable `PICK_PLACE` goal predicates, admission, attempt correlation, terminal Action results, and goal evidence in the same SQLite database as Fleet claims.
- Driver `SUCCEEDED` becomes `ACTION_SUCCEEDED`, not Mission completion. Fresh matching `camera_observation` evidence is required to become `GOAL_CONFIRMED` and release claims. Invalid goal evidence holds the Mission. Model-authored completion text is not accepted as goal evidence.
- The Mission store is internal SOURCE code only: it has no REST route, scheduler executor, or OMX/ROS submission binding.
- Follow-up review closed the stale-READY gap: if a stop changes the generation or a Mission claim is missing before start, the Mission now atomically enters `HOLD`, records `STEP_HELD_BEFORE_SUBMISSION`, and releases any remaining pre-dispatch Mission claims.

## Verification

| Command | Result |
|---|---|
| `python -m pytest src/site/fleet/test/test_mission_store.py src/site/fleet/test/test_mission_service.py src/site/fleet/test/test_goal_evidence.py -q` | 15 passed |
| `python -m pytest src/site/fleet/test/ -q` | 578 passed, 5 skipped |
| `python -m pytest src/site/fleet/test/ -q` after follow-up review fix | 578 passed, 5 skipped |
| `python -m pytest src/products/omx/adapter/test/ -q` | 72 passed, 3 skipped |
| `python -m pytest src/hmi/dashboard/test/ -q` | 14 passed, 32 skipped (browser/runtime-dependent cases skipped) |
| `python -m pytest src/hmi/web/test/ test/test_web_dialog_contract.py test/test_fleet_console_browser.py -q` | 90 passed, 31 skipped; explicit rearm confirmation is pinned in the native-dialog contract |
| `python test/test_network_topology_contracts.py test/test_harness_contracts.py -q` | Passed |
| `python tools/harness/rosy_harness.py lint` | 0 errors, 18 freshness warnings |
| `python tools/harness/rosy_harness.py generate` | Generated Fleet and OMX adapter indexes after execution-record update |
| `flake8 <changed Python files>` | Not run: `flake8` command is not installed in this environment |
| Site candidate build from merged main | Built Fleet, Vision, and proxy `linux/amd64` images with SPDX SBOMs; source commit `a86dd19ca48e13c4512a1cf815f169c78f827e7d`; archive `X:\DevTemp\rosy-site-candidate-a86dd19\images.tar`; archive SHA-256 `e9c9e4968e156a2ea9292a17218827af7b29a0e0890f5afa539a94afc822c3c6` |
| Candidate manifest verification | Matched all three local Docker image IDs/platforms, archive hash, and SBOM hashes to `release.json`; `release.json.sig` is absent. Fleet `sha256:190210391d35d654d13331041bca17532a4fe5b9e2c7e03fe1795369f3df3a19`; Vision `sha256:a61180c3af031d5fe0ae77fc2813b4459b2e7afaf810ed79803085a35163e618`; proxy `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f` |
| Isolated Docker Compose smoke | Fleet, Vision, and Caddy all healthy; local `https://127.0.0.1:18443/healthz` returned HTTP 200. Used only fake local credentials, TEST-NET robot configuration, and an internal-only robot egress network. After a 10-second stop timeout all three services exited 0; Vision used `SIGINT`, `OOMKilled=false`, and no runtime error. |
| Vision shutdown regression | `python -m pytest test/test_site_task_queue_deploy.py -q`: 4 passed. `docker compose config --format json` resolved Vision `stop_signal` to SIGINT. |

The preceding Fleet/OMX implementation commits and their focused evidence are summarized in `docs/plans/2026-09-29-fleet-mission-control-arbitration-implementation.md` and `docs/validation/er2-omx-action-baseline-2026-09-29/README.md`.

## Limits and next gate

This evidence does not prove that a site/network stop always reaches the robot, that the robot consumes and fences the stop generation, that an independent physical E-stop exists, or that gripper/camera feedback is calibrated and trustworthy. The camera goal evidence contract is a source-level check; provenance authentication must be established before any public submission path. OMX remains disabled and the Mission ledger cannot dispatch. D-322 requires an actual Ubuntu 24.04/Jazzy/Isaac Sim 6.1 GPU host; that environment is absent here, so Isaac ROS-SIM fault injection remains open. The final site candidate is unsigned because the production site signing key and trusted host enrollment are not provisioned. It was not transferred or activated on a production host, and no DEVICE/FIELD acceptance is claimed.
