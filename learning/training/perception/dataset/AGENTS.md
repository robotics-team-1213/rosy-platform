<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# dataset

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

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
| `road_draft.py` | Robot-anchored drivable drafts (D-465 addendum 2026-10-07): Qwen `point_2d` parsing, point gate, footprint seed, carpet component the robot stands on bounded by lines, compose over a base map; pure numpy/cv2 |
| `qwen_points.py` | Every K-th video frame → local Ollama Qwen3-VL road points (`keypoints.jsonl`); training drafts only |
| `sam3_road_draft.py` | Model PC only (`~/rosy-ml/sam3-venv`): SAM 3 text lanes + SAM 3.0 tracker road → pending indexed drafts + `verified-inputs.jsonl` for `review_ingest` |
| `edge_capture.py` | Edge-capture loop steps: `frames` (one camera frame per second whose 40x30 thumb changed), `drafts` (v2: autolabel LiDAR mask + lane-model components >= 40 px, 255 elsewhere), `verified` (model PC: mp4 frames by log time + indexed drafts bound to classes.yaml), `sam3` (model PC GPU, lazy import: v3 = drop lane-model lane, fill 255 with SAM floor/wall, SAM white line over non-wall; receipt-v3.json), `import` (review_ingest); merges are pure functions |
| `edge_capture_session.py` | One re-runnable loop pass per recording id (`--from N`): operator-SSH copy verified by `fetch_http.verify`, bag_to_video, autolabel + frames, model-PC prelabel, v2 drafts, model-PC verified + SAM 3 + review import (review unit stopped for the import, always restarted) |
| `lane_failure.py`, `lane_failure_loop.py` (D-578) | Lane-failure analysis loop on the model PC: `collect` (keep_debug `no_boundary`/`washed` episodes, sensor facts, the robot's own model revision re-run, hidden canaries), `vlm` (pinned VLM identity facts only, or the `fake` backend), `sheets` (contact sheets for a Claude reviewer; never hand out `key.json`), `import-verdicts` (refused below the canary threshold), `fuse` (rule `lane_failure.SUPPORT`; only final `model_miss` frames become `verified-inputs.jsonl` label candidates, pose goes to the stuck handoff) |

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
python -m pytest learning/training/perception/test -q -p no:cacheprovider
```

Relevant files: `test_dataset_build.py`, `test_dataset_extract.py`, `test_dataset_harvest.py`, `test_dataset_publish.py`, `test_bag_to_video.py`, `test_shrink_session.py`, `test_autolabel_geometry.py`, `test_edge_capture_*.py`, `test_d379_*.py` (incl. `test_d379_evalset.py`), `test_lane_failure.py`. Needs `mcap`, `numpy`, `cv2`; tests skip where a package is missing.

### Edge-capture loop

Run order (one placeholder per secret; nothing is approved, every draft lands pending for a person):

1. Capture on the operator PC with the operator at the robot: `python tools/capture/edge_drive.py --robot <robot-ip> --token-file <operator-token-file> --insecure drive --max-s 45` (or `rec start`, `nudge ...`, `rec stop`).
2. Process the recording: `python learning/training/perception/dataset/edge_capture_session.py <recording-id> --robot <robot-ip> --identity <operator-key> --known-hosts <known-hosts> --model-host <model-pc-ssh-alias> --lane-model <model-pc-lane-model-dir> --classes <model-pc-classes.yaml> --sam3-checkpoint <model-pc-sam3.pt>`. Local outputs go to `data/perception/edge-capture/<id>/` (gitignored). `--from 4` re-runs from the model-PC prelabel.
3. Review the pixel queue in the review app on the model PC (D-462).

The model PC runs `--model-repo` (default `rosy-ml/repo`), a checkout that must include `edge_capture.py`. Keep hosts, keys and tokens out of the repo.

### Common Patterns

- Each script is a CLI with a docstring that is its usage text; keep the docstring current.
- Pure logic is separated from I/O so tests run without a robot.

## Dependencies

### Internal

- `../store.py`, `../operator_ssh.py`, `middleware/perception/control/sensing/perception/learned/` (manifest contract), `middleware/apps/device/pinky/description` (URDF geometry)

### External

- `mcap`, `numpy`, `opencv-python`, `ffmpeg` for video; `ssh`/`scp` for `harvest.py`

<!-- MANUAL: -->
