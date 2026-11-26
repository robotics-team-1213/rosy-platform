---
title: OMX Recovery Simplification — clear-air tucked park_path, FifoCell unlatch, live-verified clearable_after_fold, and unified safe_home
date: 2026-11-25
category: runtime-errors
module: deploy/robot/omx (cell_safe_home.py, cell_auto_fold.py, cell_pipeline_io.py, omx_incident.py, cell_job_api.py, cell_job_spec.py, cell_area_job_spec.py), middleware/devices/omx/adapter/omx_adapter/chunk_library.py, contracts/foundation/core_common/protocol/arm_incident/arm_incidents.py
problem_type: architecture_deadlock
component: omx-recovery-pipeline
symptoms:
  - "After a transient RX-desync hardware-error stop, recovery locked up across 6 layers: clearable_after_fold blocked any motor fault record permanently (403 AI_CLEAR_KIND_REFUSED), multi-incident holds (>=2) blocked D-1048 auto_fold, tucked park_path unfolded outward to elbow=18 against gravity (-472 PWM), FifoCell.act('recover-unlatch') self-rejected with profile_mismatch, and job endpoints split across recover_hold vs home vs auto-fold CLI"
root_cause: fragmented_recovery_gates_and_overbroad_string_vetoes
resolution_type: code_fix
severity: high
tags: [omx, recovery, auto-fold, safe-home, park-path, clearable-after-fold, unlatch]
applies_when: "Recovering a held or extended OMX arm back to home via Cell Job API or D-1048 auto-fold"
---

# OMX Recovery Simplification (`safe_home`)

## Deadlocks Eliminated
1. **`park_path` unfolding tucked arms outward (`chunk_library.py`):** Added a `tucked_pose` branch (`-50 < shoulder_lift <= -15`, `elbow_flex >= 35`) that clears the plate (`elbow_flex <= 43`), lifts `shoulder_lift -> -42`, folds `shoulder_lift -> goal[1]` together with gravity-assisted `elbow_flex -> goal[2]`, centers `pan`/`wrist` in high air, and settles to `home` without unfolding to `transit (elbow=18)`.
2. **`FifoCell.act("recover-unlatch")` self-rejection (`cell_pipeline_io.py`) & `pushing at rest` unlatch lockout (`chunk_runner_recover.py`):** Allowed recovery commands (`recover-unlatch`, `park-slow`, `fold-from-hold`) with fresh timestamps and matching `operating_profile` to skip `_state_current()`'s `human_hold_latched == False` / `fault is None` check, and added `"pushing at rest"` to `is_recoverable_fault()` so live `recover-unlatch` / `fold-from-hold` can still fold after static-droop PWM windup once `_verify_hardware_ready()` confirms `hardware_error == 0`, `torque == 1`, and safe temperatures (while keeping unlatched normal `park` blocked in `chunk_runner_commands.py`).
3. **Stale fault-string permanent lockout (`arm_incidents.py` `clearable_after_fold`):** Allowed `clearable_after_fold` to clear transient fault records when post-fold `recovery` includes verified `hardware_error_after` (all 6 motors `== 0`) and `caps_restored_after is True`, while continuing to reject real `latched` hardware errors, `windup_hits`, and the `3/24h` repeat limit.
4. **Single-incident-only lockout (`omx_incident.py`, `cell_auto_fold.py`):** Extended `refuse_if_held` (`allow_incident="id1,id2"`) and `launch(..., allow_multi=True)` to handle up to 3 open incidents in one recovery fold with per-incident bound evidence.
5. **Fragmented endpoints (`cell_safe_home.py`, `cell_area_job_spec.py`, `cell_job_api.py`, `cell_job_spec.py`):** Added unified `POST /jobs/safe_home` that attaches to active torque-ON `human-hold` sessions or runs `ROSY_RECOVERY_INCIDENT` auto-fold after read-only `register_probe` confirms `hardware_error == 0`, while keeping Fleet safety stop (`E-stop` / `human_detected`) and human-token authorization enforced.

## Preserved Safety Invariants
The site recovery view can show an old local hold reason even after the cell Fleet has classified the same ID as USB home recovery.
Compare both reasons and the unsent outbox. An empty outbox and a positive cell Fleet hold identify the current classification.
Use the incident-bound recovery entry and the worker's active arm configuration when verifying deployment. An eligible historical cell task or a staged `.pending` configuration does not establish that the worker can recover this record.

- Never drops torque on an extended arm; live hold uses `recover-unlatch`; torque-OFF recovery refuses if any motor has `hardware_error != 0` on `register_probe`.
- Never clears `latched` hardware faults or `windup_hits`; enforces `<= 3` open incidents per `safe_home` and Fleet's `3/24h` machine clear limit.
- Fleet safety block (`409 FLEET_SAFETY_STOP`) and machine commissioning ban (`403 MACHINE_COMMISSIONING_FORBIDDEN`) still block `safe_home`.
