<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# dataset

## Purpose

Recordings to datasets (D-356, D-373, D-379): pull finished sessions off a robot, cut frames, label them (by hand through CVAT or automatically from LiDAR geometry), build a session-split dataset and publish it into the store for the trainer. Developer-side only; outputs live in `data/perception/` (gitignored) and `data/teleop/learning/`.

## Key Files

| File | Description |
|------|-------------|
| `harvest.py` | Pulls un-harvested recording sessions from a robot over ssh/scp, only while CORE reports idle (D-136); `--assume-idle` is bench-only; never deletes robot data |
| `bag_to_video.py` | Session camera topic to an H.265/H.264 mp4 plus a per-frame `.jsonl` sidecar (`--codec hevc|h264`, `--crf`) |
| `shrink_session.py` | Writes `<session>.compact/` with raw images turned into JPEG `CompressedImage`; never modifies the source; verifies by default |
| `extract.py` | Training frames from an mp4 (with sidecar) or an MCAP session; side topics attach by the clock rule in `../AGENTS.md` |
| `frames.py` | Frame selection: time spacing plus perceptual-hash de-duplication |
| `prelabel.py` | Pre-labels frames with a learned lane model and packs a CVAT import zip |
| `build.py` | Builds a dataset from a CVAT export (`classes.yaml` is the source of truth for names and indices; CVAT colours are not trusted) or, with `--auto-labels`, from D-379 labels; session split by a stable per-session hash, `ignore_index` 255. `--eval-set` writes a fixed eval set to `<store>/evalsets/<name>/<content_sha>/` (lidar/trajectory frames only); `--exclude-eval` refuses training sessions that are in an eval set |
| `publish.py` | Shards a built dataset (at most 1000 frames per shard) into `<store>/datasets/<name>/<content_sha>/`, never overwriting; HF is optional |
| `catalog.py` | `data/perception/catalog.jsonl`: `scan`, `add`, `update-tags`, `list` (one row per session) |
| `autolabel.py` | D-379 automatic labels for a session or video: LiDAR walls, driven floor |
| `labels.py` | Per-frame label sources, most trusted first (LiDAR first); pure numpy/cv2, no I/O |
| `geometry.py` | Nominal camera, LiDAR mount and planar poses used by the labels |

## For AI Agents

### Working In This Directory

- Labels are automatic only; rule masks from the device (`line`, keep) are compared, never used as labels. Geometry comes from the sim URDF; camera pitch is fitted per session to the LiDAR walls, so a session without `scan` needs `--pitch-deg` from a LiDAR session with the same mount.
- No class may use index 255 (`ignore_index`).
- Keep frame and label stamps untouched; a sidecar without `stamp_ns` on stamped entries yields null, never a shifted value.
- Training and eval sets are disjoint by session (D-379 d3): pass `--exclude-eval` for every eval set in use.
- A store version folder is never overwritten. Do not commit recordings, frames or datasets.
- `harvest.py` uses the operator SSH options (`../operator_ssh.py`); keep hosts, keys and tokens out of the repo.

### Testing Requirements

```bash
python -m pytest tools/perception/test -q -p no:cacheprovider
```

Relevant files: `test_dataset_build.py`, `test_dataset_extract.py`, `test_dataset_harvest.py`, `test_dataset_publish.py`, `test_bag_to_video.py`, `test_shrink_session.py`, `test_autolabel_geometry.py`, `test_d379_*.py` (incl. `test_d379_evalset.py`). Needs `mcap`, `numpy`, `cv2`; tests skip where a package is missing.

### Common Patterns

- Each script is a CLI with a docstring that is its usage text; keep the docstring current.
- Pure logic is separated from I/O so tests run without a robot.

## Dependencies

### Internal

- `../store.py`, `../operator_ssh.py`, `src/runtime/sensing/control/sensing/perception/learned/` (manifest contract), `src/sim/description` (URDF geometry)

### External

- `mcap`, `numpy`, `opencv-python`, `ffmpeg` for video; `ssh`/`scp` for `harvest.py`

<!-- MANUAL: -->
