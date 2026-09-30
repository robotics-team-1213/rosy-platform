<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-30 | Updated: 2026-09-30 -->

# perception

## Purpose

Developer-side half of the D-356 perception learning loop: turn robot recordings into datasets, hand them to a trainer that lives outside this repository, and check and deliver the returned model. Not installed on the robot and not a ROS package. The robot side is `src/runtime/sensing/control/sensing/perception/learned/`.

## Key Files

| File | Description |
|------|-------------|
| `dataset/` | `harvest.py` pulls sessions off a robot, `extract.py`/`frames.py` cut frames, `prelabel.py` pre-labels, `build.py` builds a session-split dataset, `publish.py` publishes it for the trainer |
| `model/` | `export_onnx.py` exports ONNX, `intake.py` + `intake_gate.yaml` verify a returned model, `deliver.py` ships it to the shadow slot (and rolls back), `watch.py` does intake + shadow push for each new HF commit on the site host (D-373) |
| `operator_ssh.py` | Operator SSH options shared by `deliver.py` and `harvest.py`: user `rosy`, key + pinned known_hosts, BatchMode (D-373) |
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
- Robot writes go through `sudo -n` as `rosy` (D-373); `harvest.py` pulls only while CORE `/api/v1/robot/state` reports idle (D-136), `--assume-idle` is bench-only.
- The delivered model runs shadow-only. Activating it for driving is a separate decision after the D-205 P3 gate.

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
