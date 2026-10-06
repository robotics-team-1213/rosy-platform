<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# calibration

## Purpose

Developer-side half of the D-47 addendum (2026-10-01) calibration protocol: drive a robot through a fixed motion protocol, fit wheel, LiDAR-yaw and camera values from the recording, and manage per-robot accepted calibration records. Runs on the PC, not on the robot. The store implementation is `core_common/calibration_store.py` (`contracts/foundation`); the PC mirror is `data/calibration/` (gitignored).

## Key Files

| File | Description |
|------|-------------|
| `run_calibration.py` | One command, protocol v1: per robot (one thread each) pair with a login code, drive the protocol through CORE teleop at 10 Hz, record on the robot over SSH (`~/rosy_rec.sh`), pull the session, analyse, write candidate records, repeat while the repeat rule fails. `--dry-run` prints the protocol and touches nothing; `--offline SESSION_DIR...` only analyses existing sessions |
| `analyze_session.py` | Fits from D-356 recordings (`session.json` + `bag/*.mcap`): wheel radius/separation, per-wheel scale, gain per speed, LiDAR mount yaw check, camera pitch/roll/height (PC grid `PC_FINE_STEPS`: roll 0.1°, height 1 mm, ~170 s per run; the robot's startup step keeps the robot grid, but since 2026-10-07 it too bands height on the fine table and clips the fine height window to the search range); across runs the mean, spread and 95 % interval; the camera record's band is max(widest run score half-band, across-run ci95), height from the runs that fitted it only. Writes `candidate.json` and `report.md` per robot and candidate records into the store mirror. Never applies anything |
| `store_cli.py` | Operator view of the store: `list`, `show`, `accept`, `reject`, `pin` (rollback/unpin), `sync` (merge another copy). `accept` refuses implausible values with the runtime's own check and needs `--actor` |
| `camera_auto.py` / `camera_capture.py` | Read-only stationary camera/LiDAR auto fit over a pinned SSH alias. No drive, mode change or candidate promotion. New local evidence JSON; exit 2 for rejected fit, 0 for a recommended candidate only |
| `camera_board.py` | Offline two-image checkerboard pose candidate with printed square scale, original-pixel reprojection and cross-view checks. Board elevation and its estimate provenance are explicit; existing intrinsics remain a seed. Never applies a result |
| `urdf_nominal.py` | Evaluates the fixed-joint chain of `middleware/apps/device/pinky/description/urdf/rosy.urdf.xacro` without ROS (stdlib only) and writes `middleware/apps/device/pinky/profile/config/geometry.yaml`; `--check` exits 1 on drift (D-397). Unsupported xacro raises instead of being guessed |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | `test_run_calibration.py` (protocol limits, clearance guards, stop/zero behaviour, repeat rule), `test_store_cli.py` (accept plausibility, sync merge, no overwrite), `test_analyze_store.py` (NaN/inf tolerated), `test_urdf_nominal.py` (checked-in geometry matches the URDF; consumers of the nominal values) |

## For AI Agents

### Working In This Directory

- What actually guards robot motion: login-code pairing per robot; commands clipped to the robot's limits; a LiDAR clearance guard (a straight aborts when a return in the direction of travel is under 0.20 m, a pivot when anything is within 0.20 m); a scan not refreshed for 0.5 s (PC monotonic clock) aborts; every abort and Ctrl-C sends zero and stops the recorder it started. There is no separate "operator is watching" prompt beyond the login code, so run it only with the operator present and use `--dry-run` first.
- A candidate is never applied here. Only `store_cli.py accept` makes a record current, and it happens on the PC mirror; the robot store receives decisions through `sync` (a sync that finds decisions on both sides refuses).
- The LiDAR yaw is never assumed: `--lidar-yaw-deg`, else the robot's accepted `lidar_mount` record, else the profile value with a warning.
- Every geometry default comes from the URDF (`urdf_nominal.py`); calibration refines per robot. Do not add magic numbers.
- Robot addresses and login codes go on the command line only; do not write them into files.

### Testing Requirements

```bash
python -m pytest tools/calibration/test -q
python tools/calibration/urdf_nominal.py --check
```

Needs numpy, PyYAML and `mcap` for the analysis path; tests inject fakes for CORE and SSH.

### Common Patterns

- Scripts put `contracts/foundation`, `middleware/perception` and `learning/training/perception/dataset` on `sys.path` instead of installing packages.
- Candidate and record JSON go through `json_safe` so NaN/inf do not break the store.

## Dependencies

### Internal

- `contracts/foundation/core_common/calibration_store.py`, `middleware/perception` (`odometry_fit`, `camera_extrinsic`), `learning/training/perception/dataset/autolabel.py`, `middleware/apps/device/pinky/description`, `docs/adr/D-47-core-sensor-adapter-calibration-binding.md`

### External

- numpy, PyYAML, `mcap`; `ssh`/`scp` and a robot reachable over the network for `run_calibration.py` (not for `--offline`)

<!-- MANUAL: -->
