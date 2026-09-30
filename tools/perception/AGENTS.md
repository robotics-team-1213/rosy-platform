<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-30 | Updated: 2026-09-30 -->

# perception

## Purpose

Developer-side half of the D-356 perception learning loop: turn robot recordings into datasets, hand them to a trainer that lives outside this repository, and check and deliver the returned model. Not installed on the robot and not a ROS package. The robot side is `src/runtime/sensing/control/sensing/perception/learned/`.

## Key Files

| File | Description |
|------|-------------|
| `dataset/` | `harvest.py` pulls sessions off a robot, `extract.py`/`frames.py` cut frames, `bag_to_video.py` turns a session into an H.265/H.264 mp4 plus per-frame sidecar in `data/teleop/learning/` (gitignored), `prelabel.py` pre-labels, `build.py` builds a session-split dataset, `publish.py` publishes it for the trainer |
| `dataset/` (D-379) | `catalog.py` keeps `data/perception/catalog.jsonl` (one row per session); `autolabel.py` + `labels.py` + `geometry.py` label frames automatically (LiDAR walls, driven floor); `build.py --auto-labels` builds them into `<store>/datasets/<name>/<content_sha>/` |
| `model/` | `export_onnx.py` exports ONNX, `intake.py` + `intake_gate.yaml` verify a returned model, `deliver.py` ships it to the shadow slot (and rolls back), `watch.py` does intake + shadow push for each READY folder in the store inbox (or, with `backend: hf`, each new HF commit) on the site host (D-373) |
| `store.py` | The store folder (D-373 decision 8): `content_sha`, `datasets/<name>/<content_sha>/`, `models/{inbox,accepted,rejected}`, the READY rule. Stdlib only |
| `rosy_ml.py` | The operator CLI (D-373 decision 7): `init`, `doctor`, `status`, `store-status`, `deliver`, `rollback`, `release-hold`, `harvest`, `intake`; guide in `docs/deployment/learned-perception-operators.md` |
| `operator_ssh.py` | Operator SSH options shared by `deliver.py` and `harvest.py`: user `rosy`, key + pinned known_hosts, BatchMode (D-373) |
| `training/` | Trainer contract (`README.md`), step-by-step Colab manual (`COLAB.md`), `check_manifest.py`, `export_cell.py`, `handover.py` (drop a READY folder into the store inbox), the Colab notebook (`gen_notebook.py` generates it). Training itself runs outside this repo |
| `test/` | Host tests for the above |
| `prototype/` | Unreviewed D-205 prototypes, see `prototype/README.md` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `dataset/` | Recordings to datasets |
| `model/` | Export, intake, delivery |
| `training/` | Trainer contract |
| `test/` | Tests |
| `prototype/` | D-205 prototypes, not the learned loop |

## For AI Agents

### Working In This Directory

- Model weights never go in `src/` or git. Artifacts (recordings, datasets, models, reports) live in `data/perception/`, which is gitignored.
- Delivery refuses a model whose intake failed; unharvested robot data is never deleted; the store is the source of truth (HF is an optional backend; its revisions must be commit hashes, not tags); a store version folder is never overwritten and an inbox folder counts only with a matching READY.
- Robot writes go through `sudo -n` as `rosy` (D-373); `harvest.py` pulls only while CORE `/api/v1/robot/state` reports idle (D-136), `--assume-idle` is bench-only.
- `extract.py` (MCAP or mp4 + sidecar) follows one clock rule: stamped evidence (shadow, `line/observation` from `CAMERA_LINE` only) attaches by equal stamp (1 us) when logged after the frame's capture and at most 0.5 s after its log time; every other side topic, `scan` and `odom` included, is the latest at or before the frame's log time. A sidecar without `stamp_ns` on stamped entries gives null, never a shifted value. Rows carry `t` (header stamp), `stamp_ns`, `log_ns`, `dt`.
- Datasets carry `ignore_index` (255, unlabelled, D-379); the trainer leaves those pixels out of the loss and IoU and no class may use that index.
- The delivered model runs shadow-only. Activating it for driving is a separate decision after the D-205 P3 gate.
- D-379 labels are automatic only. Rule masks (device `line`, keep) are compared, never used as labels. LiDAR geometry comes from the sim URDF; the camera pitch is fitted per session to the LiDAR walls, so a session without `scan` needs `--pitch-deg` from a LiDAR session of the same camera mount.

### Testing Requirements

```bash
python -m pytest tools/perception/test -q -p no:cacheprovider
```

Needs `onnxruntime`, `torch` and `mcap`; use a venv that has them. Tests skip cleanly where a package is missing.

## Dependencies

### Internal

- `src/runtime/sensing/control/sensing/perception/learned/manifest.py` (manifest contract)

### External

- `onnxruntime`, `torch`, `mcap` (dev venv only)

<!-- MANUAL: -->
