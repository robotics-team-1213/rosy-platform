---
title: OMX incident reassess serial-lock contention, PARK_WINDUP gating, and cell/Fleet clear split
date: 2026-11-25
last_updated: 2026-11-25
category: runtime-errors
module: deploy/robot/omx/omx_incident_reassess.py, contracts/foundation/core_common/protocol/arm_incident/arm_incidents.py, deploy/robot/omx/omx_incident_pipeline.py
problem_type: runtime_error
component: omx_incident_reassess
symptoms:
  - "POST /jobs/incident_risk_clear failed with REASSESS_FAILED (RuntimeError: Serial device is busy or its ownership could not be checked) while rosy-omx-observer@arm_s.service held /dev/serial/by-id"
  - "Parked arm incidents with contact in park + body-joint wind-up were rejected with POLICY_NOT_CLEARABLE despite folded posture, torque off, and restored servo caps"
  - "Cell-side incident_risk_clear --apply evaluated safety_score=95 (auto_clear) locally yet returned cleared=false with HTTP Error 403: Forbidden from cell-a-fleet-1"
root_cause: observer_serial_lock_and_split_cell_fleet_policy_version
resolution_type: code_fix
severity: high
tags: [omx, incident, reassess, observer, park-windup, fleet, site-autoupdate, d-1040]
applies_when: "reassessing held OMX arm incidents alongside an active observer service or clearing PARK_WINDUP incidents across cell tools and containerized cell-a-fleet"
---

# OMX incident reassess must pause sole-holder observer safely and keep cell-a-fleet aligned with core_common

## Problem

On `arm_s` after a park wind-up hold (`contact in park:` + body-joint `windup_hits`), `incident_risk_clear --apply --reassess --min-score 95` could not machine-clear the arm:

1. `omx_incident_reassess.py` failed before reading servo registers (`REASSESS_FAILED: Serial device is busy or its ownership could not be checked`) because `rosy-omx-observer@<arm>.service` held the USB serial adapter open.
2. `arm_incidents.py` rejected `contact in park:` body-joint wind-up hits under `POLICY_NOT_CLEARABLE` even when `folded`, `torque_after == 0`, `caps_restored == True`, `latched == {}`, and motionless remeasure scored `>= 95`.
3. Even after deploying PR #786 (`9e7e02ceb5`) to `omx-tools-current` on `rosy-arm-cell` so local `evaluate_clear_safety` scored `safety_score: 95` (`allowed: true`, `decision: "auto_clear"`), `omx_incident_pipeline.py --apply` still received `HTTPError: HTTP Error 403: Forbidden` from Fleet.

## Cause

1. **Observer serial lock without sole-holder pause/resume:** `rosy-omx-observer@<arm>.service` keeps a persistent read handle on the servo bus for live monitoring, blocking motionless register remeasure (`D-1040`).
2. **Over-broad park wind-up veto:** Body-joint `windup_hits` from a `run park` contact fault had no distinct `PARK_WINDUP` classification in `arm_incidents.py`, grouping a post-fold park stall together with unrecoverable mid-reach collisions.
3. **Cell/Fleet version & image-base split:** `omx_incident_pipeline.py` reads `omx-tools-current` locally for scoring, then calls `/api/fleet/workcell-observations/arms/<source_id>/incidents/<id>/clear` on `ROSY_OBSERVATION_FLEET_URL` (`cell-a-fleet-1`). `cell-a-fleet-1` validates `machine_clearable` using its own containerized copy of `contracts/foundation/core_common`. While `cell-a-fleet-1` remained on pre-PR #786 `1cff4c1c8ace`, Fleet refused the `PARK_WINDUP` clear with HTTP 403 (`AI_CLEAR_KIND_REFUSED`); meanwhile `site-9e7e02ceb54f` was built as an incremental (`manifest_version: 2`) release over an uninstalled `base_commit`, so `rosy-cell-autoupdate` held it (`reused-image-missing-or-mismatched`).

## Solution

- Added sole-holder observer pause and outer-`finally` resume (`pause_observer_if_sole_holder` under `session_lock(arm)`, polling `port_holders` and calling `oh.restart(..., device=str(port))` after lock release) in `deploy/robot/omx/omx_incident_reassess.py` and reused it in `deploy/robot/omx/cell_safe_home.py` (PR #786, `9e7e02ceb5`).
- Added `PARK_WINDUP` classification (`contact in park:` + wind-up pattern) and `remeasure_kind` eligibility for folded/torque-off/caps-restored `run park` incidents in `contracts/foundation/core_common/protocol/arm_incident/arm_incidents.py`, still gated by D-1040 motionless remeasure and `evaluate_clear_safety >= 95`.
- Landed PR #786 on `main`, deployed `omx-tools-9e7e02ceb5` to `rosy-arm-cell` via `tools/remote/omx_hotfix.py`, and rolled `cell-a-fleet-1` forward via a signed `site-*` release whose `base_commit` matched an already-installed candidate (or full build).

## Verification

- **Remote pytest (`tools/remote/remote_pytest.py`):** Verified `contracts/foundation/test/test_arm_incident_{remeasure,risk_score,machine_clearable,held_object}.py` (`190 passed`), `test/test_omx_incident_reassess.py` + `test/test_omx_grasp_plan_tool.py` (`25 passed` on `9e7e02ceb5`), plus recovery/wrist/interrupt/round-trip suites prior to merge.
- **Live `rosy-arm-cell` (`omx-tools-9e7e02ceb5`):** `POST /jobs/incident_risk_clear` (`arm_s`, `cell-auto-arm-s-live.json`, `apply=true`, `reassess=true`, `min_score=95`) eliminated `REASSESS_FAILED`, resumed `rosy-omx-observer@arm_s.service` as `active`, and scored `safety_score=95` (`allowed=true`, `decision="auto_clear"`, `clear_path="machine_clearable"`), isolating remaining clear refusal strictly to stale `cell-a-fleet-1` (`1cff4c1c8ace`) HTTP 403 until the signed site candidate rollout completes.

## Recovery

1. Ensure `rosy-arm-cell` `~/rosy-test/omx-tools-current` points to the merged `main` SHA via `tools/remote/omx_hotfix.py test` + `deploy`.
2. Verify `rosy-cell-autoupdate` has installed a full base `site-*` candidate (`manifest_version: 1`) or build a new signed site candidate referencing an already-installed `base_commit` via `build-site-candidate.yml` `workflow_dispatch`.
3. Once `cell-a-fleet-1` runs the updated `rosy-site-fleet:<sha>`, re-run `POST /jobs/incident_risk_clear` with `apply=true`, `reassess=true`, `min_score=95` and confirm `cleared=true` and `rosy-omx-observer@<arm>.service` remains `active`.

## Prevention

- Never inspect or infer `machine_clearable` pass/fail from `omx-tools-current` alone when `core_common` rules change: `cell-a-fleet-1` (and `rosy-site-fleet-1`) enforce the containerized `core_common` version until a matching signed `site-*` release rolls out.
- Never pause `rosy-omx-observer@<arm>.service` if any foreign PID holds the serial port, and always resume via the `/dev/serial/by-id` symlink outside the session lock so telemetry resumes even on remeasure failure.
