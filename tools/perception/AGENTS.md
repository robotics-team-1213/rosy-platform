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
| `model/` | `export_onnx.py` exports ONNX, `intake.py` + `intake_gate.yaml` verify a returned model, `deliver.py` ships it (and rolls back) |
| `training/` | Trainer contract (`README.md`), step-by-step Colab manual (`COLAB.md`), `check_manifest.py`, `export_cell.py`. Training itself runs outside this repo |
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
- Delivery refuses a model whose intake failed; unharvested robot data is never deleted; HF revisions must be commit hashes, not tags.
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
