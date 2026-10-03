<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# prototype

## Purpose

Unreviewed D-205 prototypes from the 2026-09-24 session: estimating the real camera from video (`camcal/`) and replaying the current perception on real teleop video (`realrun/`). Only paths were changed from the original scripts; logic was not. There are no tests and the output is not acceptance evidence. The reviewed D-205 P2 `perception_replay` tool replaces `realrun/`, and this folder is then deleted. Not part of the learned loop (D-356).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Korean run guide: environment, run order, what each script reads and writes. Read it before running anything |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `camcal/` | Camera estimation from video. Shared: `common.py`, `getframes.py`, `cammodel.py`. Ordered chain writing intermediates to the current folder: `findcw.py` -> `cwcorners.py` -> `calib.py` (crosswalk corners, focal length, pose); `horizon.py` -> `vpstats.py` (vanishing point, horizon, tilt); `wallh.py`, `ring.py`, `distort.py` (lens height, focal cross-check, distortion); `bevfinal.py`, `annotate.py` (BEV and overlays). Side statistics: `hazards.py`, `hazsum.py`, `samefr.py` |
| `realrun/` | Replays video through the current `middleware/perception` perception, read-only: `replay.py` (modes `centre`, `line`, `lane`, `road`), `analyze.py` (aggregate the seven part files), `whatif.py` (threshold sensitivity), `stills.py`, `geom.py` (BEV range of real vs sim camera), `vo_test.py` (stand-in visual odometry check on synthetic floor) |

## For AI Agents

### Working In This Directory

- Do not treat results as acceptance. Do not polish or extend these scripts; new work goes into the reviewed P2 replay tool (`learning/training/perception/road_replay.py` and its tests).
- Scripts write `out/`, `*.pkl` and `*.json` into the current working directory. Run from an empty folder outside the repo (for example under `X:\DevTemp`) and never commit the output.
- Input video defaults to `data/teleop/learning/teleop_20260919_151213_part01..07.mp4` (override `ROSY_TELEOP_DIR`); the camera profile defaults to the draft under `docs/validation/perception-real-video/2026-09-24/` (override `ROSY_CAMERA_PROFILE`).
- Run order matters in `camcal/` (each step reads the previous step's file) and in `realrun/` (`analyze.py` needs all seven `frames_pNN.jsonl`).
- Windows host with `python`; no ROS. Needs `opencv-python` and `numpy`.

### Testing Requirements

None. `learning/training/perception/test` does not cover this folder.

### Common Patterns

- Paths come from the repo root or environment variables, never absolute machine paths.
- Numbers from here are cited only through the baseline and draft-profile documents named in `README.md`.

## Dependencies

### Internal

- `middleware/perception` perception code (imported by `realrun/`), `data/teleop/learning/`, `docs/validation/perception-real-video/2026-09-24/`

### External

- `opencv-python`, `numpy`

<!-- MANUAL: -->
