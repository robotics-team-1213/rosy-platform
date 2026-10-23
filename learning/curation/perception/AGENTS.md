<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# Perception curation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose

D-663 road review uses explicit semantic bindings: `road_surface/1` is not clipped to ego-lane edges by generic draft merge/import/approval. Legacy/current-region lane restrictions remain. Own-road lane clipping and Qwen completion refuse whole-road inputs before processing; draft state remains pending until explicit review.

Recordings to datasets (D-356, D-373, D-379): pull finished sessions off a robot, cut frames, label them (by hand through CVAT or automatically from LiDAR geometry), build a session-split dataset and publish it into the store for the trainer. Developer-side only; outputs live in `data/perception/` (gitignored) and `data/teleop/learning/`.

Media stage, before a recording job: `media_pipeline.py` scans raw sessions, makes a missing learning video, verifies it, and writes a `rosy.learning.media/1` receipt. `--apply` then deletes the verified raw directories and, when the video checked out, that session's `.compact` sibling. A compact with no video stays. `trainer_recordings` turns the checked videos into recording-job `video` entries. The recording job still does not delete raw.

## Key Files

| File | Description |
|------|-------------|
| `harvest.py` | Pulls un-harvested recording sessions from a robot over ssh/scp, only while CORE reports idle (D-136); `--assume-idle` is bench-only; never deletes robot data |
| `bag_to_video.py` | Session camera topic to an H.265/H.264 mp4 plus a per-frame `.jsonl` sidecar (`--codec hevc|h264`, `--crf`) |
| `shrink_session.py` | Writes `<session>.compact/` with raw images turned into JPEG `CompressedImage`; never modifies the source; verifies by default |
| `reclaim.py` | Reports raw sessions whose mp4, sidecar and meta agree; deletes those directories only with `--apply`. A verified video also removes its `.compact` sibling. A compact that is the only remaining bag stays. Unmatched videos stay |
| `media_pipeline.py` | Disk stage before a recording job: scan, video, verify, reclaim, receipt (`rosy.learning.media/1`). A checked video becomes the trainer input. `--apply` deletes that raw directory and its verified `.compact` sibling |
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
| `ceiling_pose.py` | D-563 3: robot ArUco (D-562 id = robot number) in a `tools/capture/ceiling_record.py` recording -> map poses via the approved tracking calibration (parallax-corrected); `fuse` carries detections to robot frame stamps by odometry, flags gaps and disagreement; clock offset from motion onset |
| `camera_setup.py` | D-792: `make_reference` builds a sealed `rosy.camera-setup-reference/1` from one frame; default `features` needs no markers (ORB homography against the reference still: screen shift, pan/tilt/roll, scale), optional `markers` uses DICT_4X4_50 work-surface markers for height and distance in cm; `check`/`measure` give ok/adjust/unmeasurable; pure cv2/numpy, advice only |
| `camera_setup_web.py` | D-792 S2: `/api/learning/camera/*` helpers for `review_app.py`; references stay immutable under `<state>/camera-setup/` and are revalidated on every read; page `review_app_web/camera.html` (`/learning/camera`) |
| `omx_web.py` | `/learning/omx`: registered native intake inspection, original frame preview and D-833 immutable grasp-segment review revisions. Original decisions stay unchanged; selection JSON feeds `learning/curation/omx/native_segments.py` and the existing offline ACT path. See `learning/curation/omx/README.md`; no device action or host paths in responses |
| `learning_domains.py` | D-857 §3: read-only home rows for `/api/learning` `domains` — every Learning domain on the six loop stages with one next action, from data the workspace already holds; unknown stages are `not_available` with a reason |
| `vlm_judge.py`, `vlm_judge_web.py` | D-853: `/learning/vlm` human answers to closed VLM questions per photo (model answers stored but never shown or applied) and model-vs-human evaluation over labelled photos only; evaluation truth, never exported to training. CLI `vlm_judge.py import`; see `docs/review-app.md` 「VLM 판단」 |
| `map_projected_drivable.py` | D-563 3: map road raster (lane_graph centrelines +-0.0925 m, STL line paint, 2 mm, cached) projected into the robot camera at the fused pose, 0.15-0.40 m ahead -> `rosy.map-projected-drivable/1` (`map_projected`); review/finalize with `lane_derived_drivable.py` sheets/import-verdicts/finalize |
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
- `harvest.py` uses the operator SSH options (`../../../tools/perception/operator_ssh.py`); keep hosts, keys and tokens out of the repo.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/learning-perception" -- test/learning/perception -q -p no:cacheprovider
```

Relevant files: `test_dataset_build.py`, `test_dataset_extract.py`, `test_dataset_harvest.py`, `test_dataset_publish.py`, `test_bag_to_video.py`, `test_shrink_session.py`, `test_reclaim.py`, `test_media_pipeline.py`, `test_autolabel_geometry.py`, `test_edge_capture_*.py`, `test_d379_*.py` (incl. `test_d379_evalset.py`), `test_lane_failure.py`. Needs `mcap`, `numpy`, `cv2`; tests skip where a package is missing.

Before landing changes to `pixel_label_job.prepare_sources`, the catalog-relative importer, or their portable fixtures, run committed HEAD through `tools/remote/remote_pytest.py --test-tools pinky-raw` with `test/learning/perception/test_pixel_label_job.py`, `test_catalog_relative_import.py`, and `test_catalog_relative_import_capture.py` (all under `test/learning/perception/`). Require exit 0 and zero skips, including the MCAP control, and compare every log with `test/known_failures.py`. A default-environment MCAP skip does not satisfy this check; the raw profile must validate its pinned package origins, versions, and dependency closure first.

### Edge-capture loop

Run order (one placeholder per secret; nothing is approved, every draft lands pending for a person):

1. Capture on the operator PC with the operator at the robot: `python tools/capture/edge_drive.py --robot <robot-ip> --token-file <operator-token-file> --insecure drive --max-s 45` (or `rec start`, `nudge ...`, `rec stop`).
2. Process the recording: `python learning/curation/perception/edge_capture_session.py <recording-id> --robot <robot-ip> --identity <operator-key> --known-hosts <known-hosts> --model-host <model-pc-ssh-alias> --lane-model <model-pc-lane-model-dir> --classes <model-pc-classes.yaml> --sam3-checkpoint <model-pc-sam3.pt>`. Local outputs go to `data/perception/edge-capture/<id>/` (gitignored). `--from 4` re-runs from the model-PC prelabel.
3. Review the pixel queue in the review app on the model PC (D-462).

The model PC runs `--model-repo` (default `rosy-ml/repo`), a checkout that must include `edge_capture.py`. Keep hosts, keys and tokens out of the repo.

### Common Patterns

- Each script is a CLI with a docstring that is its usage text; keep the docstring current.
- Pure logic is separated from I/O so tests run without a robot.

## Dependencies

### Internal

- `learning/registry/perception/store.py`, `../../../tools/perception/operator_ssh.py`, `middleware/perception/front_camera/perception/learned/` (manifest contract), `middleware/devices/pinky/description` (URDF geometry)

### External

- `mcap`, `numpy`, `opencv-python`, `ffmpeg` for video; `ssh`/`scp` for `harvest.py`

<!-- MANUAL: -->

### 검수 UI 역할

- `review_app_web`은 작업 목록·자료 등록·객체 검수·픽셀 검수 네 하위 화면이다. 검수는 원본 사진과 현재 결과를 먼저 보여주고 편집·승인·다음 대기를 연결한다. 객체/픽셀 승인·export·로봇 실행 수용은 별개다.
- 공용 토큰과 `ui-*`를 쓰고 canvas 서체는 `canvasFont(role, family, displayScale)`로 읽는다. annotation 색·brush/box 좌표·원본 영상 비율은 데이터 기하이며 UI 테마로 바꾸지 않는다.
- 재시도는 editing content가 숨겨진 실패·빈 상태에도 도달 가능해야 한다. 단일 작업에서 숨긴 필터는 실제 다중 작업 시험으로 검증한다.
## Owner evidence

See [progress.md](progress.md), [logs.md](logs.md), and [index.md](index.md). The folder split in D-637 preserves bare import identities and the shared artifact/provenance store. Remote host tests do not admit learning or activate robot behavior.
