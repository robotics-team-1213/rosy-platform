
# Perception curation

**Parent context:** `../AGENTS.md`

## Purpose

Recordings to datasets (D-356, D-373, D-379): pull finished sessions off a robot, cut frames, label them (CVAT or automatic from LiDAR geometry), build a session-split dataset and publish it into the store for the trainer. Developer-side only; outputs live in gitignored `data/perception/` and `data/teleop/learning/`.

Each script is a CLI whose docstring is its usage text. Also holds review transport (`review_*.py`), road drafts, lane-failure loops (D-578) and map-projected drivable (D-563).

## For AI Agents

### Working In This Directory

- D-663 road review uses explicit semantic bindings: `road_surface/1` is not clipped to ego-lane edges by generic draft merge/import/approval. Own-road lane clipping and Qwen completion refuse whole-road inputs; drafts stay pending until explicit review.
- Labels are automatic only; device rule masks (`line`, keep) are compared, never used as labels. Camera pitch is fitted per session to LiDAR walls; a session without `scan` needs `--pitch-deg`.
- No class may use index 255 (`ignore_index`). Keep frame and label stamps untouched; a sidecar without `stamp_ns` yields null, never a shifted value.
- Training and eval sets are disjoint by session (D-379 d3): pass `--exclude-eval` for every eval set in use. A store version folder is never overwritten. Do not commit recordings, frames or datasets.
- `harvest.py` pulls sessions only while CORE reports idle (D-136; `--assume-idle` is bench-only) and never deletes robot data. It uses `../../../tools/perception/operator_ssh.py`; keep hosts, keys and tokens out of the repo.
- `media_pipeline.py --apply` and `reclaim.py --apply` delete verified raw directories (and their `.compact` sibling when the video checked out). A compact with no video stays; the recording job never deletes raw.
- Review admission stays owner-side in `learning/training/perception/`; `review_*` helpers neither grant training admission nor activate robot behavior.
- `sam3_road_draft.py` and the `edge_capture.py` `sam3`/`verified` steps run on the model PC only; every draft lands pending for a person (D-462 review app).
- Pure logic is separate from I/O so tests run without a robot. `edge_capture_session.py <recording-id> --from N` re-runs a pass; capture with the operator at the robot via `tools/capture/edge_drive.py`.
- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- D-637 split keeps bare import identities and the shared artifact/provenance store.

### Testing Requirements

`python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/learning-perception" -- test/learning/perception -q -p no:cacheprovider` (needs `mcap`, `numpy`, `cv2`; tests skip when missing).

### 검수 UI 역할

- `review_app_web`은 작업 목록·자료 등록·객체 검수·픽셀 검수 네 하위 화면이다. 검수는 원본 사진과 현재 결과를 먼저 보여주고 편집·승인·다음 대기를 연결한다. 객체/픽셀 승인·export·로봇 실행 수용은 별개다.
- 공용 토큰과 `ui-*`를 쓰고 canvas 서체는 `canvasFont(role, family, displayScale)`로 읽는다. annotation 색·brush/box 좌표·원본 영상 비율은 데이터 기하이며 UI 테마로 바꾸지 않는다.
- 재시도는 editing content가 숨겨진 실패·빈 상태에도 도달 가능해야 한다. 단일 작업에서 숨긴 필터는 실제 다중 작업 시험으로 검증한다.
