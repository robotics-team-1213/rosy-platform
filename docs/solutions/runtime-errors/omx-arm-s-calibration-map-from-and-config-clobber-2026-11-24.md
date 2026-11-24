---
title: OMX calibration must sync map_from follower sites, avoid clobbering concurrent config edits, and keep arm_s pivot geometry current
date: 2026-11-24
module: deploy/robot/omx
tags: [omx, arm_s, cell_calibrate, map_from, pivot, belt]
problem_type: runtime-error
applies_when: calibrate.map_sites omits a site with map_from, concurrent cell_calibrate runs overwrite config, or arm_s pivot_near fails with jaw-circle/occlusion mismatch
---

## Symptom

During `arm_s` (Cell S) live calibration on 2026-11-24:

1. After a 9-point `remap`, `calibration.json["sites"]["floor"]`, `pinky`, and `board` updated to the new homography, while `calibration.json["sites"]["belt"]` stayed 8 days stale (43–51 px offset) even though `belt` configured `"map_from": "floor"`.
2. When a concurrent `cell_calibrate.py` job finished, it rewrote `args.config` on exit with its startup snapshot, wiping out a `pivot.geometry` edit made while the job was running.
3. `pivot_near` on `arm_s` `floor` failed with `"marks disagree: 11.3 mm from their centre"` against stale 2026-11-15 `pivot.geometry` (`radius_mm=26.3, phase_deg=80.1`), and `belt` failed with `"jaws marked at 1 yaws, need 2"` because default `pivot_yaws` (`-74..+25 deg`) hid the reference jaw beneath the forearm over the belt.

## Cause

1. `cell_calibrate.main()` (`remap` and `consensus-repair`) only wrote to `map_sites(config)` and `cell_pivot.map_record()` returns `calibration["sites"]["belt"]` directly when that key already exists rather than following `map_from`. Meanwhile `check()` only checked `missing_maps(config, calibration, map_sites(config))`.
2. `cell_calibrate.main()` unconditionally serialized `config` back to `args.config` at exit even for steps (`pivot-near`, `post-eval`, `depth-verify`) that never modified `config`.
3. On `arm_s` (with `tcp_x_m=0.074`), the actual open/closed white-jaw circle measures `radius_mm=31.8, phase_deg=75.6` (verified via full-circle `fit_pivot_yaw`, `rms_mm=2.8, n=5`). Over the belt, `sites.belt.pivot_yaws=[35, 45, 55, 65, 75]` swings the reference jaw clear of the forearm.

## Fix

1. In `deploy/robot/omx/cell_calibrate.py`:
   - Added `_map_write_sites(config)` so `remap` and `consensus-repair` also refresh every site whose `map_from` points to a mapped parent, and updated `check()` to flag stale `map_from` copies whose homography differs from their parent.
   - Tracked `config_dirty` so `main()` only rewrites `args.config` when `move_regions` or `surface` actually mutated `config`.
   - Regression tests: `test/test_omx_cell_calibrate.py::test_map_from_site_is_synced_on_remap_and_stale_copy_flagged_in_check` and `test_pivot_near_does_not_overwrite_concurrent_config_edits`.
2. In `arm_s` live config (`cell-auto-arm-s-live.json`): added `"belt"` to `calibrate.map_sites`, updated `pivot.geometry` to `radius_mm=31.8, phase_deg=75.6`, and set `sites.belt.pivot_yaws=[35, 45, 55, 65, 75]`. Measured `floor` (`bias_mm=[12.6, -14.9], rms=4.8 mm, n=5`) and `belt` (`bias_mm=[-10.0, -20.0], rms=3.6 mm, n=3`) via `cell-job-api` `pivot_near`.

## Watch for

- Whenever `pivot.geometry` is refreshed on an arm, omit `z_view` only if all target sites share the same jaw kinematics at their `pivot_z_view`; verify `pivot_precheck` on every site first.
- If `belt` `pivot_near` drops yaws with `"no changed blob"`, inspect `pivot-frames/` for forearm occlusion over the jaw before adjusting `jaw_side` thresholds.
