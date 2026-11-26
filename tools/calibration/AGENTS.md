<!-- Parent: ../AGENTS.md -->

# calibration

**Parent context:** `../AGENTS.md`

## Purpose

Developer-side half of the D-47 addendum calibration protocol: drive a robot through a fixed motion protocol, fit wheel, LiDAR-yaw and camera values, manage per-robot accepted records. Runs on the PC. Store: `core_common/calibration_store.py`; PC mirror `data/calibration/` (gitignored).

## For AI Agents

### Working In This Directory

- Guards in `run_calibration.py`: login-code pairing; commands clipped to robot limits; LiDAR clearance (a straight aborts under 0.20 m ahead, a pivot at 0.20 m anywhere); a scan stale over 0.5 s aborts; every abort and Ctrl-C sends zero and stops its recorder.
- There is no "operator is watching" prompt beyond the login code: run it only with the operator present and use `--dry-run` first (prints the protocol, touches nothing). `--offline SESSION_DIR...` only analyses.
- A candidate is never applied here. Only `store_cli.py accept` (needs `--actor`, refuses implausible values) makes a record current, on the PC mirror; the robot store gets decisions through `sync`, which refuses when both sides hold decisions.
- The LiDAR yaw is never assumed: `--lidar-yaw-deg`, else the robot's accepted `lidar_mount` record, else the profile value with a warning.
- Every geometry default comes from the URDF (`urdf_nominal.py`; `--check` exits 1 on drift, D-397). Do not add magic numbers.
- Robot addresses and login codes go on the command line only; never write them into files.
- `camera_auto.py` and `camera_capture.py` are read-only (no drive, mode change or promotion). `camera_board.py` refuses where `/opt/rosy/current` exists and never applies or accepts.
- `camera_board.py --store` needs an independent truth (`--truth-height-mm/--truth-pitch-deg/--truth-roll-deg VALUE TOL`; TOL ≥ 1 mm, ≥ 0.2°): tape, caliper or inclinometer, never the wall-edge fit or anything through the same intrinsics (`TRUTH_MIN_TOL`).
- `ceiling_marker_yaw.py` (D-587 5) needs one straight forward drive and refuses under 5 samples, 0.25 m travel, 0.02 m off line or 5 deg yaw spread; it writes nothing.
- `slam_map_align.py` exits 3 when max residual > 0.05 m, under 3 or collinear points, mirrored pairs, or a 180-degree alternative that fits; `--write` never overwrites.
- `floor_paint_gate.py`: accept with `store_cli.py accept ROBOT floor_paint ID`, then copy or sync to the robot. Thresholds are per robot; remeasure close up.
- `migrate_calibration.py` (moved from perception/tools, D-751) rejects existing destinations and bound records and never activates values.
- Scripts put `contracts/foundation`, `middleware/perception` and `learning/curation/perception` on `sys.path`; candidate JSON goes through `json_safe`.

### Testing Requirements

```bash
python -m pytest tools/calibration/test -q
python tools/calibration/urdf_nominal.py --check
```

Needs numpy, PyYAML and `mcap`; tests inject fakes for CORE and SSH.

<!-- MANUAL: -->

`fleet_map_exchange.py` (2026-11-23): operator CLI for pulling `/api/fleet/robots/{robot_id}/map/bundle`, uploading sealed `master_map_fuse.py --seal-bundle` bundles via `PUT /api/fleet/site-map/master-grid`, pushing/activating via `POST /api/fleet/robots/{robot_id}/master-map/push`, and verifying stationary `LOCALIZED` + matching `grid_id` convergence.
