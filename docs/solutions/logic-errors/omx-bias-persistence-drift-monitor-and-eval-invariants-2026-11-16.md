---
title: OMX bias persistence preserves pivot circles, raw innovations survive window rejections, and NIS/CUSUM uses per-axis 1-sigma with min_n=15
date: 2026-11-16
category: logic-errors
module: deploy/robot/omx (cell_pivot_bias, cell_calibrate_auto, cell_cal_monitor, cell_map_fit, cell_cal_eval)
modules: [deploy, test]
problem_type: logic_error
component: calibration_and_evaluation
severity: high
symptoms:
  - "`place_look` saved within 10 mm of a pivot region overwrote its `radius_mm`/`phase_deg` fields and silently disabled `cell_look.hook`"
  - "Out-of-window (`exceeds_bias_learn_max_mm`) `learn_bias` rejections left zero innovation trail (survivorship bias hiding gradual drift)"
  - "2D RSS `sqrt(2)` mismatch inflated `look` NIS ~2x, and Phase-I `min_n=8` with `0.5*floor` MAD clamp gave 32% false CUSUM alarms over 60 stationary runs"
  - "`consensus-repair` unconditionally called affine `cal.fit` on pose-calibrated `camera_in_base` maps, leaving stale pose metadata next to an affine H"
root_cause: unseparated_bias_kinds_and_unit_mismatch
resolution_type: code_fix
tags: [omx, calibration, pivot-bias, cusum, nis, residuals, evaluation, modularization]
applies_when:
  - "Persisting or looking up `place_look` vs `pivot`/`known_geometry` entries in `bias.json`"
  - "Computing leave-one-out residuals, predictive extrapolation sigma, or NIS/CUSUM drift monitoring"
  - "Splitting calibration evaluation helpers while enforcing `< 400`-line `deploy/robot/omx/*.py` modularization limits"
---

# OMX bias persistence, drift monitor, and evaluator invariants

## Root causes

- `save_bias` deduplicated purely by `(site, dist <= 10 mm)`, letting a scalar `place_look` region delete an overlapping `pivot` circle region (`radius_mm`/`phase_deg`), while `learn_bias` omitted `map_sha` (unless calibrated) and returned early without recording rejected raw innovations.
- `cell_cal_monitor` initially assumed 2D RSS input (`/ sqrt(2)`) while `cell_look` logged per-axis `verify.mark_sigma_mm`; additionally, Monte Carlo checks showed Phase-I `min_n=8` with `0.5*floor` MAD clamp triggered 32% false alarms on 60 stationary runs vs 0.7–4% at `cusum_min_n=15` and `[1.0*floor, 2.0*floor]`.
- `predict_sigma_mm` on small/exact fits (`n=4..5`) yielded near-zero in-sample residuals (`s2 -> 0`), flattening extrapolation uncertainty unless floored by `(loo_error_mm.mean)^2`.
- `cell_depth.py` (596 lines) and `cell_calibration_view.py` (534 lines) violated `test_all_omx_control_modules_under_400_lines` (`len < 400`).

## Solution

- Tag bias kinds (`pivot`, `known_geometry`, `place_look`), preserve overlapping pivot circles in `save_bias`, record `map_sha` when a site record exists, and log both accepted and rejected raw innovations to `work_dir/cal-monitor.jsonl` (`cell_cal_monitor.py`).
- Standardize `cell_cal_monitor` on per-axis 1D `sigma_mm`, `verify.cusum_min_n=15`, `3.5*MAD` Phase-I trimming clamped to `[1.0*floor, 2.0*floor]`, AR(1) lag-1 inflation, `shift_mm = tail_mean - mu`, and distinct `(map_sha/map_from)` grouping before advising `"remap"` vs `"pivot-near"`.
- Consolidate fitting/residuals (`cell_map_fit.py`) and read-only cross-verification (`cell_cal_eval.py`) so `cell_depth.py` (395L) and `cell_calibration_view.py` (393L) stay `< 400` lines while preserving test monkeypatch seams (`cell_pivot.joints_tcp`, `cell_depth.height_map/table_plane/...`, `cc.cal.fit`).

## Verification

- `test/test_omx_cal_eval_and_monitor.py` + `test/test_omx_cell_auto_pick.py` + `test/test_omx_cell_pipeline.py` + `test/test_omx_control_modularization.py` + `test/architecture/test_module_structure.py` + `rosy_harness.py lint` (`0 error(s)`) verified cleanly before remote Linux pytest & landing queue submission.
