---
title: Every arm S Isaac run ended UNKNOWN; the worker crashed on a missing report field, not a shared GPU
date: 2026-10-26
category: runtime-errors
module: learning/envs/isaac (run_worker.py, run_store.py), tools/remote/remote_isaac.py, deploy/robot/omx/cell_case_suite.py
problem_type: runtime_error
component: development_workflow
symptoms:
  - "remote_isaac status: UNKNOWN, 'owned cleanup or GPU release unconfirmed' or 'unit is inactive; cleanup and result unconfirmed'"
  - "the run folder still holds a complete arm-s-cell-report.json and phase PNGs"
  - "remote_isaac fetch: 'Isaac operation failed; retain the request and receipt for status/retry'"
root_cause: wrong_diagnosis_masked_a_code_error
resolution_type: code_fix
severity: high
tags: [isaac, run-manager, unknown, arm-s, windows-path-length]
applies_when: "an Isaac run manager run ends UNKNOWN or fetch fails, before blaming the GPU or the host"
---

# Every arm S Isaac run ended UNKNOWN: a worker crash, not the GPU

## Problem

On 2026-10-25 all arm S Isaac runs (six scene revisions, three scenarios each) ended UNKNOWN. A GPU-sharing
process (ollama llama-server, about 8 GB) was on the model PC, and the worker's cleanup check needs a GPU with
no other compute owner, so the UNKNOWNs were blamed on it and the reports were read over SSH instead.

## Cause

Three separate faults, found once the GPU was idle and the runs still failed:

1. `run_worker._finish` read `report['completed_frames']` from every report. The arm S report has none, so a
   KeyError killed the worker after the SDK had finished (systemd `status=1/FAILURE`): UNKNOWN every time.
2. The worker rebuilt each run's input from `{'seed': ...}` alone. An `arm-s-cell-case` run also has a case,
   so `normalize` refused it at once (`status=2/INVALIDARGUMENT`, phase `LAUNCH_RESERVED`).
3. On Windows, `fetch` wrote `<out>/<case id>/snapshots/<run id>-<uuid>/.pending-<uuid>`, past 260 characters
   under the scratch folder. remote_isaac turns that FileNotFoundError into its generic "operation failed".

## Fix

- `_finish` takes `report.get('completed_frames')`; `run_store.requested(config)` gives the worker the seed and
  the case back. Tests: `learning/envs/isaac/test/test_run_worker.py::test_a_finished_arm_s_run_is_recorded_from_its_own_report`,
  `test_run_store.py::test_the_worker_rebuilds_a_case_runs_input_from_its_normalized_config`.
- `cell_case_suite.py` names each case folder by an 8-character hash of its id.
- After the fixes, with ollama still installed, the runs ended SUCCEEDED or FAILED by their judgement and
  fetch returned the report (validation `docs/validation/omx-arm-s-cell-cases-2026-10-26/`).

## Next time

- UNKNOWN: read the unit's exit code first (`journalctl --user -u rosy-isaac-<run>.service`). Exit 1 or 2 is
  the worker's own error; only exit 0 with a residual GPU owner is the cleanup check.
- A complete report in the run folder with UNKNOWN means the failure is after the SDK: verification or `_finish`.
- remote_isaac's generic error hides the exception; call `remote_isaac.main()` from Python to see it.
- A new run kind needs one worker-level test through `execute`/`_finish`, not only catalog tests: the catalog
  tests passed while faults 1 and 2 stopped every real run.
