---
title: Standalone cell-job-api daemon crashed with RemoteDisconnected on missing joint_tune import
date: 2026-11-23
category: runtime-errors
module: deploy/robot/omx (omx_incident_fleet.py, cell_job_guards.py, joint_tune_lock.py)
problem_type: runtime_error
component: deploy
symptoms:
  - "POST /jobs/remap on the deployed cell-job-api daemon dropped the TCP connection (http.client.RemoteDisconnected) even though GET /health returned 200 ok"
  - "cell_job_api journal logged ModuleNotFoundError: No module named 'joint_tune' inside omx_incident_fleet.incidents_dir() even inside cell_job_guards.check_arm_incident_hold()'s except Exception fallback"
root_cause: standalone_cell_job_api_deploy_ships_joint_tune_lock_not_joint_tune
resolution_type: code_and_regression_test_fix
severity: high
tags: [omx, cell-job-api, standalone-deploy, omx_incident_fleet, joint_tune_lock, regression-test]
applies_when: "adding or modifying imports in modules copied into the standalone cell-job-api runtime directory"
---

# Standalone cell-job-api daemon crashed on missing `joint_tune` import

## Problem

After clearing `arm_a`'s Fleet hold and calling `POST /jobs/remap` on the live `rosy-omx-cell-job-api.service` daemon, every moving job failed with `http.client.RemoteDisconnected` while `GET /health` succeeded.

Inspection of the service journal showed:

1. `rosy-omx-cell-job-api.service` runs `/usr/bin/python3` on a standalone flat directory (`~/rosy-omx/cell-job-api/`) containing the 17 API/guard/incident modules and `joint_tune_lock.py`, without `joint_tune.py` or workspace parent directories.
2. When checking moving-job incident holds, `cell_job_guards.check_arm_incident_hold()` called `omx_incident.status(arm)` -> `omx_incident_fleet.incidents_dir()`, which ran `from joint_tune import lock_root` -> `ModuleNotFoundError: No module named 'joint_tune'`.
3. `check_arm_incident_hold()` caught `Exception` and fell back to `omx_incident.hold_file(arm)`, which called `incidents_dir()` again and hit the exact same uncaught `ModuleNotFoundError`, crashing the HTTP request handler before sending headers.
4. Repo-checkout `pytest` missed the bug because `deploy/robot/omx/joint_tune.py` exists in a full checkout, and `omx_incident_fleet.link_for()` also assumed `len(Path(__file__).resolve().parents) > 3`.

## Fix

- Switched `omx_incident_fleet.incidents_dir()` from `from joint_tune import lock_root` to `from joint_tune_lock import lock_root` (matching `cell_depth_lock.py`, `cell_task_transport.py`, and `bench_record_guard.py`, since `joint_tune_lock.py` defines `lock_root()` and is included in the standalone layout).
- Guarded `here.parents[3]` in `omx_incident_fleet.link_for()` with `if len(here.parents) > 3:` so shallow standalone paths cannot raise `IndexError`.
- Added `test_check_arm_incident_hold_supports_standalone_cell_api_layout` in `test/test_omx_cell_job_api.py`, staging only the standalone `cell-job-api` files without `joint_tune.py` and with `PYTHONPATH` stripped to assert both unheld and `HOLD-<arm>.json` handling.

## Prevention & Verification Rule

- Any module deployed into the standalone `cell-job-api` directory must only import stdlib modules or modules explicitly present in that standalone layout on its non-best-effort call paths (`test_check_arm_incident_hold_supports_standalone_cell_api_layout` and `/usr/bin/python3` smoke check calling `cell_job_guards.check_arm_incident_hold('arm_a')` on service restart).
