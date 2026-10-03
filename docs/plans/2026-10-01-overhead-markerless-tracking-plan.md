# Overhead Markerless Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 천장 카메라(Rosy Cam → Rosy Vision)가 ArUco 마커 없이 로봇을 찾아 콘솔 지도에 그리고, 로봇이 스스로 보고한 map 자세와의 차이를 보여 준다. 표시·교차확인 전용이다(D-268). 로봇을 조향하지 않고, 교통정리·bays·미션·D-395 위치 확정의 입력이 아니다.

**Architecture:** 운용자가 D-375 페인트 맞춤 제안을 콘솔에서 "추적 보정 적용"하면 Fleet이 source별 보정 기록(SQLite, sighting DB 옆 표)을 둔다. Vision은 그 기록을 자기 source 토큰으로 읽고(`GET /api/fleet/detections/config`), 모서리 마커 넷이 보이면 마커 homography를, 아니면 기록을 써서 `rosy_vision/track/`의 `background_blob` 검출기(MOG2 고정 배경 + 바닥 크기 필터 + 높이 시차 보정)로 익명 바닥 위치를 낸다. 결과는 새 계약 `OverheadDetectionsPayload`로 `POST /api/fleet/detections`에 간다. Fleet은 source마다 1.0 s 보관하고, 콘솔 상태 경로가 넘겨 준 로봇 상태 중 map 프레임 자세만 헝가리안(정확, 0.30 m 게이트)으로 짝지어 `GET /api/fleet/tracking`으로 낸다. 콘솔은 "관제 카메라 추적" 레이어·상태줄·"배경 다시 학습"을 가진다.

**Tech Stack:** Python 3.14(Windows 벤치 `C:\Python314\python.exe`; venv의 cv2는 Application Control이 막는다), pydantic 2.13, FastAPI 0.141, httpx, OpenCV 5.0(`createBackgroundSubtractorMOG2`), numpy 2.5, SQLite(WAL), 브라우저 ES 모듈 + `node --test`(Node 24). scipy는 없다 — 매칭은 순수 Python 헝가리안이다.

**Spec:** `docs/plans/2026-10-01-overhead-markerless-tracking-design.md`(승인된 설계). 이 계획과 다르면 설계를 먼저 고친다.

---

## Conventions (모든 Task 공통)

- **작업 위치.** 구현은 이 docs 브랜치가 아니라 main에서 새로 딴 worktree에서 한다(main이 이 브랜치보다 28커밋 앞서 있다 — D-395 `localization` 계약, Fleet 웹 변경). 모든 명령은 그 worktree 루트에서 실행한다. 셸이 cwd를 유지하지 않으면 각 명령 앞에 붙인다:
  `cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl"`
- **Python.** `C:/Python314/python.exe`. 각 suite의 `conftest.py`가 `sys.path`를 잡으므로 pytest에는 `PYTHONPATH`가 필요 없다. pytest 밖에서 `rosy_vision`을 실행할 때만 `PYTHONPATH="F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl/src/site/vision;F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl/src/site/games;F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl/src/contracts/foundation"`(Windows 구분자 `;`).
- **ADR 번호.** Task 0에서 rosy-land-on-main 절차로 정한다. **이것이 이 계획에서 유일하게 실행 시점에 정하는 값이다.** 계획 본문의 `D-NNN`은 그 번호(예: `D-401`)를 뜻한다. Task 1부터 파일을 쓸 때 `D-NNN`을 실제 번호로 써 넣는다. Task 10에서 `git grep -n "D-NNN"`이 이 계획 파일 말고는 비어야 한다.
- **커밋.** `git add`에는 이 Task가 만든·바꾼 경로만 적는다. `git add -A`/`.`/디렉터리 금지. `git add`가 실패하면(경로 하나라도 틀리면 전체가 안 된다) 커밋하지 않는다. 커밋 전에 `git diff --cached --name-only`가 그 목록과 같아야 한다. 메시지 끝 줄: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. push하지 않는다.
- **산문은 한국어, 식별자·코드·주석은 영어.**
- **사전 확인.** 이 계획의 새 파일 코드, 편집 기준 문자열, 시험은 2026-10-01 main(`6594cf38`) 사본에 그대로 적용해 실행했다: 새 Python 시험은 모두 첫 실행에 통과했고, `node --test`는 87 pass, 비밀 스캐너는 새 파일 64개에서 0건이었다. 실행 때 결과가 다르면 main이 그 사이 바뀐 것이다 — 기준 문자열부터 다시 찾는다.
- **ADR 게이트.** 설계 문서는 "ADR이 Accepted되기 전에는 구현하지 않는다"고 적었다. Task 0이 끝나면 멈추고 사용자 승인을 받는다(Task 0 마지막 단계).

---

## File Structure

### 새 파일

| 경로 | 책임 |
|---|---|
| `docs/adr/D-NNN-overhead-markerless-tracking-display-only.md` | 결정 기록(Proposed → 사용자 승인 뒤 Accepted) |
| `src/contracts/foundation/core_common/protocol/overhead_detections.py` | 익명 검출 payload 계약(pydantic, extra 금지, 최대 16개) |
| `test/fixtures/protocol/overhead-detections.v1.json` | 계약 벡터 + Vision·Fleet 공용 보정 config 예시 |
| `src/contracts/foundation/test/test_overhead_detections_vectors.py` | 계약이 벡터를 따르는지 |
| `src/site/fleet/fleet/server/tracking_calibration.py` | 보정 기록 모델·검증·revision, SQLite/메모리 저장소와 감사 |
| `src/site/fleet/fleet/server/tracking_match.py` | 순수 매처: 헝가리안, 게이트, 상태 우선순위 |
| `src/site/fleet/fleet/server/tracking.py` | `TrackingService`: 인증, 수명 1.0 s, revision 검사, 상태 관찰, 스냅숏, 승인·회수·재학습 |
| `src/site/fleet/fleet/server/tracking_routes.py` | HTTP 경로 6개와 요청 모델 |
| `src/site/fleet/test/test_overhead_tracking_calibration.py` | 기록·저장소 시험 |
| `src/site/fleet/test/test_overhead_tracking_match.py` | 매처 시험 |
| `src/site/fleet/test/test_overhead_tracking_service.py` | 서비스 시험 |
| `src/site/fleet/test/test_overhead_tracking_api.py` | 경로·권한 시험 |
| `src/site/fleet/test/test_overhead_tracking_console.py` | 콘솔 자산 배선 시험 |
| `src/site/fleet/fleet/server/web/tracking-layer.js` | 추적 응답 → 그릴 것·상태줄 문구(순수, DOM 없음) |
| `src/site/fleet/fleet/server/web/tracking-view.js` | 폴링, 상태줄, "배경 다시 학습" 버튼(DOM) |
| `src/site/fleet/test/web/tracking-layer.test.mjs` | 순수 층 node 시험 |
| `src/site/vision/rosy_vision/track/__init__.py` | 패키지 표시 |
| `src/site/vision/rosy_vision/track/model.py` | 고정 인터페이스(`Frame`, `Calibration`, `Detection`, `DetectorResult`, `RobotDetector`)와 URDF 상수 |
| `src/site/vision/rosy_vision/track/geometry.py` | homography 계산, homography→카메라 위치, 시차 보정(numpy만) |
| `src/site/vision/rosy_vision/track/background_blob.py` | 첫 백엔드 `background-blob/1` |
| `src/site/vision/rosy_vision/track/calibration.py` | 프레임마다 쓸 보정 고르기(마커 우선, 렌즈·비율 검사) |
| `src/site/vision/rosy_vision/track/fleet_client.py` | source 토큰 Fleet 클라이언트(검출 쓰기, 자기 config 읽기) |
| `src/site/vision/rosy_vision/track/worker.py` | 프레임마다 추적 한 단계, config 동기화 |
| `src/site/vision/rosy_vision/track/replay.py` | 저장 프레임 재생 지표(LOCAL 증거용 CLI) |
| `src/site/vision/test/test_overhead_track_model.py` | 상수 드리프트·`Calibration` 검증 |
| `src/site/vision/test/test_overhead_track_geometry.py` | 기하 시험 |
| `src/site/vision/test/test_overhead_track_blob.py` | 합성 프레임 검출기 시험 |
| `src/site/vision/test/test_overhead_track_calibration.py` | 보정 고르기 시험 |
| `src/site/vision/test/test_overhead_track_client.py` | Fleet 클라이언트 시험 |
| `src/site/vision/test/test_overhead_track_worker.py` | 추적 단계·VisionWorker 연결 시험 |
| `src/site/vision/test/test_overhead_track_replay.py` | 재생 지표 시험 |

### 고치는 파일

| 경로 | 바꾸는 것 |
|---|---|
| `docs/reference/ROSY ADR Log.md` | D-NNN 행 1개(CRLF 유지, BOM은 있으면 유지) |
| `tools/harness/harness.yaml` | 충돌로 잃은 번호가 있을 때만 `adr_gaps` |
| `src/site/fleet/fleet/server/app.py` | `create_app(..., tracking=None)`, 검사, 경로 설치(`:107`, `:307` 앞, `:348-355`) |
| `src/site/fleet/fleet/server/console_routes.py` | `install_console_routes(..., tracking=None)`, `fleet_state`가 상태를 넘김(`:46-50`) |
| `src/site/fleet/fleet/cli.py` | `TrackingService` 생성·전달(`:392`, `:407-410`, `:473`) |
| `src/site/fleet/fleet/server/static_routes.py` | 자산 허용 목록 2개(`:35` 뒤) |
| `src/site/fleet/test/test_boundaries.py` | 교통정리·bays·미션·localization이 추적을 import하지 않는다(파일 끝) |
| `src/site/fleet/fleet/server/web/map-view.js` | 추적 레이어 그리기 |
| `src/site/fleet/fleet/server/web/console.js` | 추적 뷰 생성·폴링 |
| `src/site/fleet/fleet/server/web/index.html` | 상태줄·버튼·범례·레이어 토글·"추적 보정 적용" |
| `src/site/fleet/fleet/server/web/styles.css` | 클래스 3개(토큰만) |
| `src/site/fleet/fleet/server/web/field-layers.js` | `tracking` 레이어 키 |
| `src/site/fleet/fleet/server/web/map-fit.js` | `calibrationRequest()` 순수 함수 |
| `src/site/fleet/fleet/server/web/map-fit-view.js` | "추적 보정 적용" 버튼 |
| `src/site/fleet/fleet/server/web/vision-view.js` | 렌즈 전체(`kind`·`focal_mm`·`hfov_deg`) 노출 |
| `src/site/fleet/test/web/map-fit.test.mjs`, `src/site/fleet/test/web/field-layers.test.mjs` | 새 함수·키 시험 |
| `src/site/vision/rosy_vision/project.py` | `marker_homography()` 분리(`:56-74`) |
| `src/site/vision/rosy_vision/worker.py` | `tracker=` 연결(`:17-62`) |
| `src/site/vision/rosy_vision/cli.py` | `vision --track`(`:33`, `:291-336`, `:371` 뒤) |
| `src/site/vision/test/test_vision_project.py`, `src/site/vision/test/test_vision_cli.py` | 새 동작 시험 |
| `test/architecture/test_app_roles.py` | Vision이 쓸 수 있는 Fleet 경로에 `detections` 추가(`:29-35`, `:81-84`) |
| `test/architecture/test_module_structure.py` | `fleet` 패키지 크기 재판정 |
| `src/site/vision/AGENTS.md`, `src/contracts/foundation/core_common/protocol/AGENTS.md` | 새 모듈 행 |
| `docs/reference/ROSY API & Protocol Reference.md` | §10.6.3 경로 표(CRLF 유지) |
| `src/site/vision/{logs,progress}.md`, `src/site/fleet/{logs,progress}.md`, `src/contracts/foundation/{logs,progress}.md` | D-61 하네스 |
| `docs/plans/2026-10-01-overhead-markerless-tracking-design.md` | 첫 줄 결정 번호만 D-NNN으로 |

줄 번호는 main `6594cf38` 기준이다(Vision과 Fleet Python 파일은 이 docs 브랜치와 같다). 웹 파일은 main에서 몇 줄 바뀌었으므로 줄 번호 대신 아래에 적은 기준 문자열을 찾아 고친다.

---

## Task 0: 구현 worktree와 ADR 초안(Proposed)

**Files:**
- Create: `docs/adr/D-NNN-overhead-markerless-tracking-display-only.md`
- Modify: `docs/reference/ROSY ADR Log.md`(끝에 1행), 필요할 때만 `tools/harness/harness.yaml`

- [ ] **Step 1: worktree를 main에서 만들고 설계·계획을 가져온다**

```bash
cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
git status --short --branch
git worktree list
git worktree add --relative-paths .worktrees/markerless-impl -b feat/overhead-markerless-tracking main
cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl"
git merge --no-edit docs/overhead-markerless-tracking
git log --oneline -3
```

Expected: 마지막 커밋이 merge이고 `docs/plans/2026-10-01-overhead-markerless-tracking-{design,plan}.md`가 있다. main checkout(`Rosy OS/`)의 작업 트리는 건드리지 않는다.

- [ ] **Step 2: ADR 번호를 정한다(바로 쓰기 전에, 이 순서대로)**

```bash
cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl"
# 1) 이 worktree, main checkout 작업 트리(동료의 미추적 파일 포함), 모든 로컬 브랜치의 docs/adr
{ ls docs/adr; ls "../../docs/adr"; \
  for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do git ls-tree -r --name-only "$b" docs/adr; done; } \
  | grep -oE 'D-[0-9]+' | sort -t- -k2 -n -u | tail -8
# 2) ADR Log 행(파일보다 행이 먼저 생길 수 있다) — 이 worktree와 main checkout 둘 다
grep -ohE '^\| D-[0-9]+ \|' "docs/reference/ROSY ADR Log.md" "../../docs/reference/ROSY ADR Log.md" | grep -oE '[0-9]+' | sort -n -u | tail -5
# 3) 예약·건너뛴 번호
grep -oE '^  D-[0-9]+:' tools/harness/harness.yaml "../../tools/harness/harness.yaml" | grep -oE '[0-9]+' | sort -n -u | tail -5
```

규칙: `N = (세 목록의 최댓값) + 1`. 2026-10-01 기준 D-398은 충돌 중, D-399·D-400은 동료가 잡았다 — 아직 어디에도 보이지 않아도 쓴 것으로 친다. 그래서 `N ≥ 401`이다. ListAgents(있으면)로 동료가 방금 말한 번호도 확인한다. 이 `N`이 이후 모든 `D-NNN`이다.

- [ ] **Step 3: ADR 파일을 쓴다**

`docs/adr/D-NNN-overhead-markerless-tracking-display-only.md` (`D-NNN`은 실제 번호로):

````markdown
## D-NNN 천장 카메라 무마커 로봇 추적은 표시·교차확인 전용이다 — 승인된 페인트 맞춤이 추적 보정이 되고, Vision은 익명 검출만 내고, Fleet이 map 프레임 자가보고 자세와 짝짓는다

**Status:** Proposed (2026-10-01). 근거 설계: [2026-10-01-overhead-markerless-tracking-design.md](../plans/2026-10-01-overhead-markerless-tracking-design.md). 실행 계획: [2026-10-01-overhead-markerless-tracking-plan.md](../plans/2026-10-01-overhead-markerless-tracking-plan.md). [D-375](D-375-overhead-map-registration-from-lane-paint-proposal.md) 5·6항을 추적 표시 경로에 한해 고친다(Decision 1). D-257·D-268·D-395는 바꾸지 않는다.

잇는 결정: D-257(sighting은 표시 전용) · D-261(Vision 시계) · D-268(자동 작업 입력 아님) · D-318(영상은 Vision이 브라우저에 직접) · D-370(앱 역할) · D-375(페인트 맞춤 제안) · D-395(위치 프레임 표시, Proposed) · D-397(URDF NOMINAL).

### Context

1. 2026-10-01 실물 트랙에서 S21(`ceiling_north`) 영상은 3 fps로 들어왔지만 모서리 마커 30–33과 로봇 마커가 없어 sighting이 0건이었다. 검출은 ArUco뿐이다(`rosy_vision/detect.py`, `project.py`).
2. D-375 페인트 맞춤은 제안과 브라우저 표시 초안까지만이고 `CameraMap`·sighting에 들어가지 않는다.
3. sighting 계약은 `robot_id`가 필수라 이름 모를 검출을 담지 못한다. `core_common.protocol.detections`는 D-137 로봇 카메라 증거(정규화 상자)가 이미 쓰고 있다.
4. 로봇 상태의 `map_id`는 설정값(`navigation.map_id`)이라 map TF가 없을 때 odom 자세에도 그대로 붙는다(`ros_bridge.py` `_on_odom`, `core_features/state/manager.py`). 자세 프레임은 D-395 `StateSnapshot.localization.pose_frame`이 처음 알려 준다.
5. Pinky URDF NOMINAL(`geometry.yaml`): 회전 반경 0.08257 m(실기 메시, sim 상자는 0.08826 m), 가장 높은 부품은 LiDAR 0.125 m. 로봇 전체 높이 필드는 없다.

### Decision

1. **추적 보정 기록.** 콘솔 "맵 자동 맞춤"에서 통과한 최신(`current`) 제안을 운용자가 "추적 보정 적용"으로 승인하면 Fleet이 source마다 기록 하나를 둔다: `source_id`, `map_id`, `calibration_revision`(`paint-` + 정규화 JSON sha256 앞 12자), `map_to_image`(3×3, 원본 프레임 픽셀), `image{width,height}`, `track_bounds_m`(사이트 차선 범위), `lens`(Vision이 알린 `kind`·`focal_mm`·`hfov_deg` 또는 null), `fit_score`(recall×precision), `frame_seq`, `approved_by`, `approved_at`. `--sightings-db` 파일의 별도 표에 승인·회수 감사와 함께 저장한다. 브라우저 표시 초안(D-375 6항)은 그대로다. 기록은 추적 표시에만 쓴다 — sighting 좌표, `CameraMap`, 작업·주행에는 여전히 쓰지 않는다(D-375 5항의 예외는 이 경로 하나).
2. **프레임마다 쓰는 보정.** 모서리 마커 넷이 한 프레임에 다 보이면 마커 homography(측정)를 쓰고 revision은 `CameraMap.calibration_revision`이다. 아니면 승인 기록(추정)을 쓴다. 기록이 없거나, source·map이 다르거나, 지금 렌즈(hello `lens`)가 기록과 다르거나(렌즈 교체 = 무효), 프레임 가로세로 비가 1 %를 넘게 다르면 `CALIBRATION_REQUIRED`이고 검출을 내지 않는다. 같은 비의 다른 해상도는 배율로 맞춘다.
3. **검출기.** `rosy_vision/track/`의 고정 인터페이스 `RobotDetector.detect(Frame, Calibration) -> DetectorResult(detections, status)`와 `reset()`, `processor_revision`. 첫 백엔드 `background-blob/1`: 긴 변 640 px 사본에서 MOG2로 빈 트랙을 30프레임·10 s 학습(`LEARNING`)한 뒤 학습률 0으로 고정한다(멈춘 로봇이 배경으로 녹지 않게). 그림자(127)는 전경이 아니다. 트랙 사각형 밖은 지운다. 연결 성분의 바닥 면적은 homography의 국소 픽셀 면적으로 구하고, 렌즈 hfov가 있으면 homography에서 카메라 위치를 풀어(핀홀, 주점 중앙, 왜곡 무시) 위치와 크기를 LiDAR 높이 0.125 m로 시차 보정한다. 바닥 등가 지름 0.12–0.26 m만 남긴다(2×0.08257 = 0.165 m 주변). 방향은 내지 않는다. 트랙 면적의 30 %를 넘는 전경은 `SCENE_CHANGED`로 버리고 다시 학습한다. 숫자는 시작값이다.
4. **계약.** `core_common.protocol.overhead_detections.OverheadDetectionsPayload`: `source_id`, `map_id`, `calibration_revision`(`CALIBRATION_REQUIRED`일 때만 null), `processor_revision`, `captured_at`(Vision 시계), `seq`(source마다 Vision 카운터), `status`, `detections[{x, y, footprint_m, score}]`(`OK`일 때만, 최대 16개). 추가 필드 금지 — 영상, 픽셀 좌표, `robot_id`가 들어갈 자리가 없다. 벡터는 `test/fixtures/protocol/overhead-detections.v1.json`이고 Vision·Fleet 시험이 같이 읽는다. Vision은 그 source의 sighting 토큰으로 `POST /api/fleet/detections`를 쓰고 `GET /api/fleet/detections/config`로 자기 기록과 재학습 번호만 읽는다. Vision이 부를 수 있는 Fleet 경로에 이 둘을 더한다(`test_app_roles.py`).
5. **매칭(Fleet).** source마다 마지막 payload를 1.0 s 보관한다(sighting 수명). 대상 로봇은 그 source의 `robot_ids` 중 콘솔 상태 경로(`GET /api/fleet/state`)에서 2 s 안에 본 상태가 있고, `map_id`가 payload와 같고, `localization`이 있으면 `pose_frame == "map"`이고 `state == "LOCALIZED"`인 로봇이다. `localization`이 없는 로봇(D-395 이전)은 대상이지만 `pose_frame_verified: false`로 표시한다("위치 상태 미보고", D-395 Phase 2 레거시 정책과 같다). 헝가리안(정확, scipy 없음) 일대일, 게이트 0.30 m. 상태는 `MATCHED(offset_m)`/`NO_DETECTION`/`NO_POSE`/`CAMERA_UNAVAILABLE`(신선한 payload 없음 또는 `OK` 아님)이고, 남는 검출은 `unknown`(`UNKNOWN_OBJECT`)이다. `GET /api/fleet/tracking`(읽기 권한). Fleet은 로봇을 따로 부르지 않는다. 교통정리·bays·미션·localization 코드는 이 모듈을 import하지 않는다(`test_boundaries.py`).
6. **revision 검사.** payload revision이 그 source의 마커 revision도 승인 기록 revision도 아니면 409 `CALIBRATION_MISMATCH`이고 콘솔은 "보정 불일치"를 보인다. map이 다르면 409 `MAP_MISMATCH`.
7. **콘솔.** 지도 레이어 "관제 카메라 추적": `MATCHED`는 카메라 위치 고리 + 자가보고 위치까지 선 + 차이(cm). 0.15 m 초과는 주황(`--status-warn`), 프레임 미확인은 점선이다. `unknown`은 회색 점(`--ink-quiet`). 상태줄은 source마다 학습 중·보정 필요·장면 변화·오래됨·수신 없음·보정 불일치와 fps. "배경 다시 학습"(운용자, `POST /api/fleet/tracking/relearn`)은 트랙을 비운 채로 누른다. 검출이 없으면 아무것도 그리지 않고 지난 값을 남기지 않는다. 색은 토큰과 클래스로만(CSP `style-src 'self'`).

### Evidence levels

| 등급 | 이 ADR에서 뜻하는 것 |
|------|----------------------|
| SOURCE | 합성 프레임 검출기(학습·크기 필터·장면 변화·축소), 매칭 규칙(게이트, 일대일, `NO_POSE`, 수명), 계약 벡터, 경로 권한·이름 시험 |
| LOCAL | 실물 트랙에서 받은 저장 프레임 재생(`private/`, 공개 저장소에 커밋하지 않음). 정답은 로봇을 차선 그래프 노드에 둔 구간의 노드 좌표 |
| DEVICE | 모터 동작 없이 사람이 로봇을 노드에 옮겨 놓고 카메라 위치와 노드 좌표의 차이를 기록. G4/G5 필요 없음 |
| FIELD | 운영 중 장시간 관찰 |

잠정 합격: 정지 로봇의 노드 대비 차이 중앙값 ≤ 0.10 m, 재생 세트에서 오검출(라벨 없는 곳의 검출) 프레임당 평균 ≤ 0.1개. 측정 뒤 이 ADR에 확정 숫자를 적는다.

### Alternatives

- **sighting에 robot_id 없는 행 허용.** D-257 계약을 약하게 하고 표시 규칙과 섞인다.
- **Vision이 매칭.** Vision이 로봇 자세를 받아야 하므로 D-370 역할을 넘는다. Fleet은 자세를 이미 가진다.
- **MOG2 계속 학습.** 멈춘 로봇이 history 프레임 뒤 배경으로 사라진다. 고정 배경과 운용자 재학습을 고른다.
- **콘솔 `console.py`가 상태 시각을 기록.** `console.py`는 1021줄 판정(1000 초과, 성장 0)이라 고칠 수 없다. 상태는 상태 경로에서 넘긴다. 콘솔을 아무도 열지 않으면 모든 로봇이 `NO_POSE`다 — 표시 전용이라 문제없다.
- **학습형 검출기.** 데이터가 없다. 인터페이스만 연다.

### Not decided

- 학습형 백엔드, 붙은 두 로봇의 분리.
- 추적 결과를 D-395 위치 확정 단서(`overhead`)로 쓰는 것 — 별도 결정.
- 시작값(10 s·30프레임, 30 %, 0.12–0.26 m, 시차 높이 0.125 m)과 합격 숫자의 확정.
- 렌즈 왜곡 보정(지금은 핀홀 가정).

### Validation

- `C:/Python314/python.exe -m pytest src/contracts/foundation/test/test_overhead_detections_vectors.py -q -p no:cacheprovider`
- `C:/Python314/python.exe -m pytest src/site/vision/test -q -p no:cacheprovider`
- `C:/Python314/python.exe -m pytest src/site/fleet/test -q -p no:cacheprovider`
- `C:/Python314/python.exe -m pytest test/architecture -q -p no:cacheprovider`
- `node --test src/site/fleet/test/web/*.test.mjs`

### References

- 계약: `src/contracts/foundation/core_common/protocol/overhead_detections.py`, `test/fixtures/protocol/overhead-detections.v1.json`
- Vision: `src/site/vision/rosy_vision/track/`
- Fleet: `src/site/fleet/fleet/server/tracking*.py`, `web/tracking-layer.js`, `web/tracking-view.js`
````

- [ ] **Step 4: ADR Log에 행을 붙인다(CRLF 유지, BOM은 있던 그대로)**

`X:/DevTemp/overhead-tracking/add_adr_row.py`(커밋하지 않는 일회용, `D-NNN`은 실제 번호로):

```python
from pathlib import Path

path = Path("docs/reference/ROSY ADR Log.md")
raw = path.read_bytes()
bom = raw.startswith(b"\xef\xbb\xbf")
text = raw.decode("utf-8-sig")
assert "\r\n" in text, "ADR Log must stay CRLF"
row = (
    "| D-NNN | 천장 카메라 무마커 로봇 추적은 표시·교차확인 전용이다 — 승인된 D-375 페인트 맞춤이 "
    "source별 추적 보정 기록이 되고(모서리 마커가 보이면 마커 우선, 렌즈가 바뀌면 무효), Vision은 "
    "익명 바닥 검출만 낸다(`POST /api/fleet/detections`, 영상·픽셀·robot_id 없음, 최대 16개). Fleet이 "
    "1.0 s 안의 검출을 map 프레임 자가보고 자세와 헝가리안 0.30 m로 짝지어 `GET /api/fleet/tracking`으로 "
    "콘솔에만 보인다 | Proposed (2026-10-01; D-375 5·6항을 추적 표시 경로에 한해 개정; 교통정리·bays·미션·"
    "D-395 입력 아님; 시작값 10 s·30 %·0.12–0.26 m와 잠정 합격 0.10 m는 재생·DEVICE 측정 뒤 확정) |"
)
if not text.endswith("\r\n"):
    text += "\r\n"
text += row + "\r\n"
path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
print("bom" if bom else "no-bom", "ok")
```

```bash
mkdir -p X:/DevTemp/overhead-tracking
C:/Python314/python.exe X:/DevTemp/overhead-tracking/add_adr_row.py
git diff --stat -- "docs/reference/ROSY ADR Log.md"
file "docs/reference/ROSY ADR Log.md"
C:/Python314/python.exe tools/harness/rosy_harness.py lint
```

Expected: `1 file changed, 1 insertion(+)`, `file`가 `with CRLF line terminators`라고 한다, lint가 0으로 끝난다. (2026-10-01 main의 Log는 BOM이 없다 — 스크립트는 있으면 유지, 없으면 그대로 둔다.) 고른 번호가 충돌로 밀렸다면(Step 2 이후 동료가 가져감) 잃은 번호를 `tools/harness/harness.yaml` `adr_gaps`에 `  D-<lost>: "skipped: overhead markerless tracking moved to D-NNN in a concurrent-session numbering collision (2026-10-01)"`로 적는다.

- [ ] **Step 5: 커밋**

```bash
git add "docs/adr/D-NNN-overhead-markerless-tracking-display-only.md" "docs/reference/ROSY ADR Log.md"
git diff --cached --name-only
git commit -m "docs(adr): D-NNN overhead markerless tracking is display and cross-check only (Proposed)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(`harness.yaml`을 고쳤으면 `git add`에 `tools/harness/harness.yaml`도 적는다.)

- [ ] **Step 6: 멈추고 사용자 승인을 받는다**

사용자에게 ADR 경로와 Decision 1–7 요약을 보내고 "Accepted로 올려도 되는가"를 묻는다. 승인되면 ADR `**Status:**`를 `Accepted (YYYY-MM-DD, 사용자 승인)`으로, Log 행의 `Proposed (2026-10-01; …)`를 `Accepted (YYYY-MM-DD, 사용자 승인; …)`로 바꾸고(Step 4와 같은 방식으로 바이트 보존) 커밋한다:

```bash
git add "docs/adr/D-NNN-overhead-markerless-tracking-display-only.md" "docs/reference/ROSY ADR Log.md"
git commit -m "docs(adr): accept D-NNN overhead markerless tracking" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

승인 전에는 Task 1로 넘어가지 않는다.

---

## Task 1: 익명 검출 계약과 공용 벡터

**Files:**
- Create: `src/contracts/foundation/core_common/protocol/overhead_detections.py`
- Create: `test/fixtures/protocol/overhead-detections.v1.json`
- Test: `src/contracts/foundation/test/test_overhead_detections_vectors.py`

- [ ] **Step 1: 공용 벡터를 쓴다**

`test/fixtures/protocol/overhead-detections.v1.json`:

```json
{
  "version": 1,
  "doc": "D-NNN 4 overhead detection vectors. Machine source for core_common.protocol.overhead_detections, the Vision publisher (rosy_vision.track) and the Fleet ingest (POST /api/fleet/detections). Anonymous floor positions in map metres from one ceiling camera: no image, no pixel coordinates, no robot id, extra fields forbidden, at most max_detections, detections only when status is OK, calibration_revision null only when status is CALIBRATION_REQUIRED. Display and cross-check only (D-268); not an input to D-395 localization, traffic, bays or missions. config_example is the body of GET /api/fleet/detections/config (Fleet tracking_calibration.CalibrationRecord.to_dict, read by rosy_vision.track.calibration.from_record).",
  "max_detections": 16,
  "statuses": ["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED"],
  "config_example": {
    "source_id": "ceiling_north",
    "map_id": "map_v2_fleet",
    "calibration": {
      "source_id": "ceiling_north",
      "map_id": "map_v2_fleet",
      "calibration_revision": "paint-3f9a1c2b7d40",
      "map_to_image": [100.0, 0.0, 0.0, 0.0, -100.0, 360.0, 0.0, 0.0, 1.0],
      "image": {"width": 640, "height": 360},
      "track_bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 6.4, "max_y": 3.6},
      "lens": null,
      "fit_score": 0.81,
      "frame_seq": 12,
      "approved_by": "site-console",
      "approved_at": 1790000000.0,
      "use": "display-only"
    },
    "relearn_seq": 0
  },
  "cases": [
    {"id": "ok_two_detections", "expect": {"valid": true}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "OK",
      "detections": [{"x": 1.2345, "y": 0.4321, "footprint_m": 0.181, "score": 0.83},
                     {"x": 2.5, "y": 1.0, "footprint_m": 0.2, "score": 0.5}]}},
    {"id": "ok_empty", "expect": {"valid": true}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 42, "status": "OK",
      "detections": []}},
    {"id": "learning_without_detections", "expect": {"valid": true}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 1, "status": "LEARNING",
      "detections": []}},
    {"id": "calibration_required_without_revision", "expect": {"valid": true}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": null,
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 0,
      "status": "CALIBRATION_REQUIRED", "detections": []}},
    {"id": "robot_id_is_forbidden", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "OK",
      "detections": [], "robot_id": "rosy_01"}},
    {"id": "image_is_forbidden", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "OK",
      "detections": [], "image": "data:image/jpeg;base64,AAAA"}},
    {"id": "pixel_coordinates_are_forbidden", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "OK",
      "detections": [{"x": 1.0, "y": 1.0, "footprint_m": 0.18, "score": 0.8, "u": 320, "v": 180}]}},
    {"id": "detections_only_when_ok", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "LEARNING",
      "detections": [{"x": 1.0, "y": 1.0, "footprint_m": 0.18, "score": 0.8}]}},
    {"id": "revision_required_unless_calibration_required", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": null,
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "OK",
      "detections": []}},
    {"id": "no_revision_when_calibration_required", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41,
      "status": "CALIBRATION_REQUIRED", "detections": []}},
    {"id": "score_above_one", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "OK",
      "detections": [{"x": 1.0, "y": 1.0, "footprint_m": 0.18, "score": 1.2}]}},
    {"id": "boolean_coordinate", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "OK",
      "detections": [{"x": true, "y": 1.0, "footprint_m": 0.18, "score": 0.8}]}},
    {"id": "unknown_status", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": 41, "status": "BLIND",
      "detections": []}},
    {"id": "negative_seq", "expect": {"valid": false}, "payload": {
      "source_id": "ceiling_north", "map_id": "map_v2_fleet", "calibration_revision": "paint-3f9a1c2b7d40",
      "processor_revision": "background-blob/1", "captured_at": 1790000000.25, "seq": -1, "status": "OK",
      "detections": []}}
  ]
}
```

- [ ] **Step 2: 실패하는 시험을 쓴다**

`src/contracts/foundation/test/test_overhead_detections_vectors.py`:

```python
"""D-NNN 4: overhead detections follow the shared vectors (Vision and Fleet read the same file)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core_common.protocol.overhead_detections import (
    MAX_DETECTIONS, STATUSES, OverheadDetectionsPayload,
)

FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
def test_payload_validation_matches_the_vector(case):
    if case["expect"]["valid"]:
        payload = OverheadDetectionsPayload.model_validate(case["payload"])
        assert payload.model_dump(mode="json") == case["payload"]
    else:
        with pytest.raises(ValidationError):
            OverheadDetectionsPayload.model_validate(case["payload"])


def test_constants_are_the_vector_constants():
    assert MAX_DETECTIONS == FIXTURE["max_detections"] == 16
    assert STATUSES == tuple(FIXTURE["statuses"])


def test_more_than_the_maximum_is_refused():
    body = dict(CASES["ok_two_detections"]["payload"])
    one = body["detections"][0]
    body["detections"] = [one] * MAX_DETECTIONS
    assert len(OverheadDetectionsPayload.model_validate(body).detections) == MAX_DETECTIONS
    body["detections"] = [one] * (MAX_DETECTIONS + 1)
    with pytest.raises(ValidationError):
        OverheadDetectionsPayload.model_validate(body)


def test_payload_is_immutable():
    payload = OverheadDetectionsPayload.model_validate(CASES["ok_empty"]["payload"])
    with pytest.raises(ValidationError):
        payload.seq = 7
```

- [ ] **Step 3: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/contracts/foundation/test/test_overhead_detections_vectors.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'core_common.protocol.overhead_detections'` (collection error).

- [ ] **Step 4: 계약을 쓴다**

`src/contracts/foundation/core_common/protocol/overhead_detections.py`:

```python
"""Anonymous overhead-camera robot detections for the site Fleet console (D-NNN 4).

Display and cross-check only (D-268). A payload carries floor positions in map metres:
no image, no pixel coordinates and no robot id (Fleet pairs detections with robot
self-reported poses). Not an input to D-395 localization, traffic, bays or missions.
The machine source is ``test/fixtures/protocol/overhead-detections.v1.json``.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_DETECTIONS = 16
STATUSES = ("OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED")
DetectorStatus = Literal["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED"]


def _no_boolean(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric detection value")
    return value


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("detection numbers must be finite")
    return value


class OverheadDetection(BaseModel):
    """One floor blob: position and floor-equivalent diameter in map metres."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float
    y: float
    footprint_m: float = Field(gt=0.0, le=2.0)
    score: float = Field(ge=0.0, le=1.0)

    _numbers_not_boolean = field_validator("x", "y", "footprint_m", "score", mode="before")(
        classmethod(lambda cls, value: _no_boolean(value)))
    _numbers_finite = field_validator("x", "y", "footprint_m", "score")(
        classmethod(lambda cls, value: _finite(value)))


class OverheadDetectionsPayload(BaseModel):
    """One processed frame of one camera source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=64)
    map_id: str = Field(min_length=1, max_length=160)
    calibration_revision: Optional[str] = Field(default=None, min_length=1, max_length=128)
    processor_revision: str = Field(min_length=1, max_length=128)
    captured_at: float
    seq: int = Field(ge=0, le=0xFFFFFFFF, strict=True)
    status: DetectorStatus
    detections: tuple[OverheadDetection, ...] = Field(default=(), max_length=MAX_DETECTIONS)

    _captured_not_boolean = field_validator("captured_at", mode="before")(
        classmethod(lambda cls, value: _no_boolean(value)))
    _captured_finite = field_validator("captured_at")(classmethod(lambda cls, value: _finite(value)))

    @model_validator(mode="after")
    def _status_rules(self) -> "OverheadDetectionsPayload":
        if self.status != "OK" and self.detections:
            raise ValueError("detections are reported only with status OK")
        if self.status == "CALIBRATION_REQUIRED" and self.calibration_revision is not None:
            raise ValueError("CALIBRATION_REQUIRED carries no calibration revision")
        if self.status != "CALIBRATION_REQUIRED" and self.calibration_revision is None:
            raise ValueError("calibration_revision is required unless CALIBRATION_REQUIRED")
        return self
```

- [ ] **Step 5: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/contracts/foundation/test/test_overhead_detections_vectors.py -q -p no:cacheprovider`
Expected: PASS — `17 passed`.

- [ ] **Step 6: 커밋**

```bash
git add src/contracts/foundation/core_common/protocol/overhead_detections.py test/fixtures/protocol/overhead-detections.v1.json src/contracts/foundation/test/test_overhead_detections_vectors.py
git diff --cached --name-only
git commit -m "feat(contracts): D-NNN anonymous overhead detections payload and shared vectors" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Fleet 보정 기록과 저장소

**Files:**
- Create: `src/site/fleet/fleet/server/tracking_calibration.py`
- Test: `src/site/fleet/test/test_overhead_tracking_calibration.py`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/site/fleet/test/test_overhead_tracking_calibration.py`:

```python
"""D-NNN 1: an approved paint fit becomes one validated, revisioned record per camera source."""

import json
from pathlib import Path

import pytest

from fleet.server.sighting_store import SightingStore
from fleet.server.tracking_calibration import REVISION_PREFIX, TrackingCalibrationStore, build_record

FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
EXAMPLE = FIXTURE["config_example"]["calibration"]


def _record(**changes):
    args = dict(source_id="ceiling_north", map_id="map_v2_fleet",
                map_to_image=EXAMPLE["map_to_image"], image_width=640, image_height=360,
                track_bounds_m=(0.0, 0.0, 6.4, 3.6), lens=None, fit_score=0.81, frame_seq=12,
                approved_by="site-console", approved_at=1_790_000_000.0)
    args.update(changes)
    return build_record(**args)


def test_record_has_the_shape_vision_reads():
    row = _record().to_dict()
    assert set(row) == set(EXAMPLE)
    for key in set(EXAMPLE) - {"calibration_revision"}:
        assert row[key] == EXAMPLE[key], key
    revision = row["calibration_revision"]
    assert revision.startswith(REVISION_PREFIX) and len(revision) == len(REVISION_PREFIX) + 12


def test_revision_is_deterministic_and_follows_the_fit():
    assert _record().calibration_revision == _record().calibration_revision
    moved = _record(map_to_image=[101.0] + EXAMPLE["map_to_image"][1:])
    assert moved.calibration_revision != _record().calibration_revision
    lens = _record(lens={"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9})
    assert lens.to_dict()["lens"] == {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9}
    assert lens.calibration_revision != _record().calibration_revision


@pytest.mark.parametrize("changes", [
    {"map_to_image": [1.0] * 8},
    {"map_to_image": [float("nan")] + [1.0] * 8},
    {"map_to_image": [0.0] * 9},
    {"image_width": 0},
    {"image_height": 9000},
    {"track_bounds_m": (1.0, 0.0, 1.0, 3.6)},
    {"fit_score": 1.5},
    {"lens": {"kind": "standard", "focal_mm": -1.0, "hfov_deg": 60.0}},
    {"lens": {"kind": "standard"}},
    {"frame_seq": -1},
    {"approved_by": ""},
])
def test_invalid_records_are_refused(changes):
    with pytest.raises(ValueError):
        _record(**changes)


def test_sqlite_store_persists_and_audits(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = TrackingCalibrationStore(path)
    record = _record()
    store.put(record)
    again = TrackingCalibrationStore(path)
    assert again.get("ceiling_north") == record
    assert again.delete("ceiling_north", principal_id="operator-1", at=1_790_000_100.0) is True
    assert again.delete("ceiling_north", principal_id="operator-1", at=1_790_000_101.0) is False
    assert TrackingCalibrationStore(path).get("ceiling_north") is None
    assert [(row["event"], row["principal_id"]) for row in again.audit_events()] == [
        ("calibration.approved", "site-console"), ("calibration.revoked", "operator-1")]


def test_store_shares_the_sightings_database_without_touching_it(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    SightingStore(path)
    TrackingCalibrationStore(path).put(_record())
    assert SightingStore(path).load_latest() == {}
    assert TrackingCalibrationStore(path).get("ceiling_north") == _record()


def test_memory_store_needs_no_file():
    store = TrackingCalibrationStore()
    store.put(_record())
    assert store.all() == [_record()]
    assert store.audit_events() == []
    assert store.delete("ceiling_north", principal_id="operator-1", at=0.0) is True
    assert store.get("ceiling_north") is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_calibration.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.server.tracking_calibration'`.

- [ ] **Step 3: 구현한다**

`src/site/fleet/fleet/server/tracking_calibration.py`:

```python
"""Approved overhead-camera calibration records for markerless tracking (D-NNN 1).

An operator applies a D-375 lane-paint fit in the console; Fleet keeps one record per
camera source. Vision reads only its own source's record with that source's token and
uses it only to place anonymous display detections. A record is never a sighting
calibration, a CameraMap, a task input or a motion input (D-268; D-375 5 is amended
for this display path only).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .sqlite_policy import configure_connection, enable_wal

REVISION_PREFIX = "paint-"
MAX_IMAGE_SIDE = 8192
_LENS_KEYS = ("kind", "focal_mm", "hfov_deg")


@dataclass(frozen=True)
class CalibrationRecord:
    source_id: str
    map_id: str
    calibration_revision: str
    map_to_image: tuple[float, ...]                    # 9 values, row-major: map metres -> frame pixels
    image_width: int
    image_height: int
    track_bounds_m: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    lens: Optional[tuple[str, float, float]]           # (kind, focal_mm, hfov_deg) as Vision reported
    fit_score: float
    frame_seq: Optional[int]
    approved_by: str
    approved_at: float

    def to_dict(self) -> dict:
        min_x, min_y, max_x, max_y = self.track_bounds_m
        return {
            "source_id": self.source_id,
            "map_id": self.map_id,
            "calibration_revision": self.calibration_revision,
            "map_to_image": list(self.map_to_image),
            "image": {"width": self.image_width, "height": self.image_height},
            "track_bounds_m": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
            "lens": None if self.lens is None else dict(zip(_LENS_KEYS, self.lens)),
            "fit_score": self.fit_score,
            "frame_seq": self.frame_seq,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "use": "display-only",
        }

    @classmethod
    def from_dict(cls, row: Mapping) -> "CalibrationRecord":
        bounds = row["track_bounds_m"]
        lens = row.get("lens")
        return cls(
            source_id=row["source_id"],
            map_id=row["map_id"],
            calibration_revision=row["calibration_revision"],
            map_to_image=tuple(float(value) for value in row["map_to_image"]),
            image_width=int(row["image"]["width"]),
            image_height=int(row["image"]["height"]),
            track_bounds_m=(float(bounds["min_x"]), float(bounds["min_y"]),
                            float(bounds["max_x"]), float(bounds["max_y"])),
            lens=None if lens is None else (str(lens["kind"]), float(lens["focal_mm"]),
                                            float(lens["hfov_deg"])),
            fit_score=float(row["fit_score"]),
            frame_seq=row.get("frame_seq"),
            approved_by=row["approved_by"],
            approved_at=float(row["approved_at"]),
        )


def build_record(*, source_id: str, map_id: str, map_to_image: Sequence[float], image_width: int,
                 image_height: int, track_bounds_m: Sequence[float], lens: Optional[Mapping],
                 fit_score: float, frame_seq: Optional[int], approved_by: str,
                 approved_at: float) -> CalibrationRecord:
    """Validate one operator-approved fit and derive its revision. Raises ``ValueError``."""
    matrix = tuple(float(value) for value in map_to_image)
    if len(matrix) != 9 or not all(math.isfinite(value) for value in matrix):
        raise ValueError("map_to_image must be nine finite numbers")
    if abs(_det3(matrix)) < 1e-12:
        raise ValueError("map_to_image is singular")
    for side in (image_width, image_height):
        if type(side) is not int or not 0 < side <= MAX_IMAGE_SIDE:
            raise ValueError(f"image sides must be integers in 1..{MAX_IMAGE_SIDE}")
    bounds = tuple(float(value) for value in track_bounds_m)
    if (len(bounds) != 4 or not all(math.isfinite(value) for value in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError("track bounds must be a finite non-empty rectangle")
    score = float(fit_score)
    if not 0.0 <= score <= 1.0:
        raise ValueError("fit_score must be in [0, 1]")
    lens_value = None if lens is None else _lens(lens)
    if frame_seq is not None and (type(frame_seq) is not int or frame_seq < 0):
        raise ValueError("frame_seq must be a non-negative integer")
    if not source_id or not map_id or not approved_by:
        raise ValueError("source, map and approver are required")
    revision_fields = {
        "source_id": source_id, "map_id": map_id, "map_to_image": list(matrix),
        "image": [image_width, image_height], "track_bounds_m": list(bounds),
        "lens": None if lens_value is None else list(lens_value), "approved_at": float(approved_at),
    }
    canonical = json.dumps(revision_fields, sort_keys=True, separators=(",", ":"), allow_nan=False)
    revision = REVISION_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return CalibrationRecord(source_id, map_id, revision, matrix, image_width, image_height,
                             bounds, lens_value, score, frame_seq, approved_by, float(approved_at))


def _lens(lens: Mapping) -> tuple[str, float, float]:
    try:
        kind, focal, hfov = str(lens["kind"]), float(lens["focal_mm"]), float(lens["hfov_deg"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("lens needs kind, focal_mm and hfov_deg") from exc
    if not kind or not 0.0 < focal <= 1000.0 or not 0.0 < hfov < 180.0:
        raise ValueError("lens values are out of range")
    return kind, focal, hfov


def _det3(m: Sequence[float]) -> float:
    a, b, c, d, e, f, g, h, i = m
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


class TrackingCalibrationStore:
    """One record per source: SQLite tables beside the sighting tables when ``path`` is set
    (``--sightings-db``), memory only otherwise (records are then lost on restart)."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: dict[str, CalibrationRecord] = {}
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tracking_calibrations (
                    source_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tracking_calibration_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    calibration_revision TEXT,
                    principal_id TEXT,
                    at REAL NOT NULL
                );
                """
            )
            rows = connection.execute(
                "SELECT payload_json FROM tracking_calibrations ORDER BY source_id").fetchall()
        if os.name != "nt":
            self.path.chmod(0o600)
        for row in rows:
            record = CalibrationRecord.from_dict(json.loads(row["payload_json"]))
            self._records[record.source_id] = record

    def get(self, source_id: str) -> Optional[CalibrationRecord]:
        return self._records.get(source_id)

    def all(self) -> list[CalibrationRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def put(self, record: CalibrationRecord) -> None:
        if self.path is not None:
            payload = json.dumps(record.to_dict(), separators=(",", ":"), allow_nan=False)
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """INSERT INTO tracking_calibrations(source_id, payload_json) VALUES (?, ?)
                           ON CONFLICT(source_id) DO UPDATE SET payload_json=excluded.payload_json""",
                        (record.source_id, payload),
                    )
                    connection.execute(
                        """INSERT INTO tracking_calibration_audit
                           (event, source_id, calibration_revision, principal_id, at)
                           VALUES ('calibration.approved', ?, ?, ?, ?)""",
                        (record.source_id, record.calibration_revision, record.approved_by,
                         record.approved_at),
                    )
        self._records[record.source_id] = record

    def delete(self, source_id: str, *, principal_id: str, at: float) -> bool:
        record = self._records.get(source_id)
        if record is None:
            return False
        if self.path is not None:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("DELETE FROM tracking_calibrations WHERE source_id = ?",
                                       (source_id,))
                    connection.execute(
                        """INSERT INTO tracking_calibration_audit
                           (event, source_id, calibration_revision, principal_id, at)
                           VALUES ('calibration.revoked', ?, ?, ?, ?)""",
                        (source_id, record.calibration_revision, principal_id, at),
                    )
        del self._records[source_id]
        return True

    def audit_events(self) -> list[dict]:
        if self.path is None:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT event, source_id, calibration_revision, principal_id, at
                   FROM tracking_calibration_audit ORDER BY audit_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_calibration.py -q -p no:cacheprovider`
Expected: PASS — `16 passed`.

- [ ] **Step 5: 커밋**

```bash
git add src/site/fleet/fleet/server/tracking_calibration.py src/site/fleet/test/test_overhead_tracking_calibration.py
git diff --cached --name-only
git commit -m "feat(fleet): D-NNN approved overhead calibration records and store" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Fleet 순수 매처

**Files:**
- Create: `src/site/fleet/fleet/server/tracking_match.py`
- Test: `src/site/fleet/test/test_overhead_tracking_match.py`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/site/fleet/test/test_overhead_tracking_match.py`:

```python
"""D-NNN 5: overhead detections pair one-to-one with map-frame robot poses inside 0.30 m."""

import pytest

from fleet.server.tracking_match import GATE_M, Pose, Seen, Track, assign, better, match


def _seen(x, y=0.0):
    return Seen(x=x, y=y, footprint_m=0.18, score=0.8)


def test_assignment_is_the_exact_minimum():
    assert assign([[4.0, 1.0, 3.0], [2.0, 0.0, 5.0], [3.0, 2.0, 2.0]]) == [1, 0, 2]
    assert assign([]) == []


def test_one_to_one_pairing_beats_greedy_nearest():
    poses = {"a": Pose(0.0, 0.0, True), "b": Pose(0.2, 0.0, True)}
    tracks, unknown = match(("a", "b"), poses, [_seen(0.1), _seen(-0.15)])
    by_id = {track.robot_id: track for track in tracks}
    assert by_id["a"].status == "MATCHED" and by_id["a"].offset_m == pytest.approx(0.15)
    assert by_id["a"].camera == _seen(-0.15)
    assert by_id["b"].status == "MATCHED" and by_id["b"].offset_m == pytest.approx(0.1)
    assert unknown == []


def test_a_detection_outside_the_gate_is_an_unknown_object():
    tracks, unknown = match(("a",), {"a": Pose(0.0, 0.0, True)}, [_seen(GATE_M + 0.01)])
    assert [track.status for track in tracks] == ["NO_DETECTION"]
    assert unknown == [_seen(GATE_M + 0.01)]


def test_two_robots_one_detection_the_nearer_wins():
    poses = {"a": Pose(0.0, 0.0, True), "b": Pose(0.25, 0.0, True)}
    tracks, unknown = match(("a", "b"), poses, [_seen(0.2)])
    assert [(track.robot_id, track.status) for track in tracks] == [("a", "NO_DETECTION"), ("b", "MATCHED")]
    assert unknown == []


def test_robot_without_map_pose_is_no_pose_and_never_claims_a_detection():
    tracks, unknown = match(("a",), {"a": None}, [_seen(0.0)])
    assert tracks == [Track("a", "NO_POSE")]
    assert unknown == [_seen(0.0)]


def test_no_fresh_payload_is_camera_unavailable_for_everyone():
    pose = Pose(1.0, 1.0, False)
    tracks, unknown = match(("a", "b"), {"a": pose, "b": None}, None)
    assert tracks == [Track("a", "CAMERA_UNAVAILABLE", pose=pose), Track("b", "CAMERA_UNAVAILABLE")]
    assert unknown == []


def test_the_more_informative_status_wins_across_sources():
    matched = Track("a", "MATCHED", 0.1, _seen(0.1), Pose(0.0, 0.0, True))
    assert better(Track("a", "CAMERA_UNAVAILABLE"), matched) is matched
    assert better(Track("a", "NO_DETECTION"), Track("a", "NO_POSE")).status == "NO_DETECTION"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_match.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.server.tracking_match'`.

- [ ] **Step 3: 구현한다**

`src/site/fleet/fleet/server/tracking_match.py`:

```python
"""Pure matcher: anonymous overhead detections <-> robot self-reported map poses (D-NNN 5).

One-to-one by distance inside a gate, solved exactly (Hungarian; scipy is not a Fleet
dependency). A pair outside the gate costs more than every gated pair together, so the
solution first maximises the number of matches, then minimises their total distance.
Display and cross-check only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

GATE_M = 0.30
#: When one robot is covered by several sources, the most informative status wins.
STATUS_RANK = {"MATCHED": 0, "NO_DETECTION": 1, "NO_POSE": 2, "CAMERA_UNAVAILABLE": 3}
_OUT_OF_GATE = 1e6


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    verified: bool  # D-395 localization says LOCALIZED in map; False = the robot predates D-395


@dataclass(frozen=True)
class Seen:
    x: float
    y: float
    footprint_m: float
    score: float


@dataclass(frozen=True)
class Track:
    robot_id: str
    status: str
    offset_m: Optional[float] = None
    camera: Optional[Seen] = None
    pose: Optional[Pose] = None


def assign(cost: Sequence[Sequence[float]]) -> list[int]:
    """Minimum-cost perfect assignment on a square matrix; ``result[row] = column``."""
    n = len(cost)
    if n == 0:
        return []
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if current < minv[j]:
                        minv[j] = current
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1] * n
    for j in range(1, n + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


def match(robot_ids: Sequence[str], poses: Mapping[str, Optional[Pose]],
          detections: Optional[Sequence[Seen]], gate_m: float = GATE_M) -> tuple[list[Track], list[Seen]]:
    """Tracks in ``robot_ids`` order and the detections no robot claimed.

    ``detections`` None means no fresh OK payload for this source.
    """
    if detections is None:
        return [Track(rid, "CAMERA_UNAVAILABLE", pose=poses.get(rid)) for rid in robot_ids], []
    tracks: dict[str, Track] = {rid: Track(rid, "NO_POSE") for rid in robot_ids if poses.get(rid) is None}
    eligible = [rid for rid in robot_ids if poses.get(rid) is not None]
    used: set[int] = set()
    if eligible and detections:
        size = max(len(eligible), len(detections))
        cost = [[_OUT_OF_GATE] * size for _ in range(size)]
        for i, rid in enumerate(eligible):
            pose = poses[rid]
            for j, seen in enumerate(detections):
                distance = math.hypot(seen.x - pose.x, seen.y - pose.y)
                if distance <= gate_m:
                    cost[i][j] = distance
        for i, j in enumerate(assign(cost)):
            if i < len(eligible) and j < len(detections) and cost[i][j] <= gate_m:
                rid = eligible[i]
                tracks[rid] = Track(rid, "MATCHED", round(cost[i][j], 4), detections[j], poses[rid])
                used.add(j)
    for rid in eligible:
        tracks.setdefault(rid, Track(rid, "NO_DETECTION", pose=poses[rid]))
    unknown = [seen for j, seen in enumerate(detections) if j not in used]
    return [tracks[rid] for rid in robot_ids], unknown


def better(a: Track, b: Track) -> Track:
    return a if STATUS_RANK[a.status] <= STATUS_RANK[b.status] else b
```

- [ ] **Step 4: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_match.py -q -p no:cacheprovider`
Expected: PASS — `7 passed`.

- [ ] **Step 5: 커밋**

```bash
git add src/site/fleet/fleet/server/tracking_match.py src/site/fleet/test/test_overhead_tracking_match.py
git diff --cached --name-only
git commit -m "feat(fleet): D-NNN exact one-to-one overhead detection matcher" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Fleet 추적 서비스, 경로, 배선

**Files:**
- Create: `src/site/fleet/fleet/server/tracking.py`, `src/site/fleet/fleet/server/tracking_routes.py`
- Modify: `src/site/fleet/fleet/server/app.py:107`, `:307`(앞), `:348-355`; `src/site/fleet/fleet/server/console_routes.py:46-50`; `src/site/fleet/fleet/cli.py:392`, `:407-410`, `:473`; `src/site/fleet/test/test_boundaries.py`(끝)
- Test: `src/site/fleet/test/test_overhead_tracking_service.py`, `src/site/fleet/test/test_overhead_tracking_api.py`

- [ ] **Step 1: 실패하는 서비스 시험을 쓴다**

`src/site/fleet/test/test_overhead_tracking_service.py`:

```python
"""D-NNN 5-6: Fleet keeps 1.0 s of detections per source and pairs them with fresh map poses."""

import json
from pathlib import Path

import pytest

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from fleet.server.sightings import SightingSource
from fleet.server.tracking import TrackingError, TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore

NOW = 1_790_000_000.0
TOKEN = "north-source-secret"
AUTH = f"Bearer {TOKEN}"
FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}
APPROVAL = {
    "source_id": "ceiling_north", "map_id": None,
    "map_to_image": [100.0, 0.0, 0.0, 0.0, -100.0, 360.0, 0.0, 0.0, 1.0],
    "image": {"width": 640, "height": 360},
    "track_bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 6.4, "max_y": 3.6},
    "fit_score": 0.81, "lens": None, "frame_seq": 12,
}


class _Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def _source():
    return SightingSource(source_id="ceiling_north", token=TOKEN, robot_ids=("rosy_01", "rosy_02"),
                          map_id="map_v2_fleet", calibration_revision="cal-v3",
                          corner_marker_ids=(30, 31, 32, 33))


def _service():
    clock = _Clock()
    return TrackingService([_source()], calibrations=TrackingCalibrationStore(), clock=clock), clock


def _payload(**changes):
    body = dict(CASES["ok_two_detections"]["payload"])
    body["captured_at"] = NOW - 0.1
    body.update(changes)
    return OverheadDetectionsPayload.model_validate(body)


def _state(x, y, *, map_id="map_v2_fleet", localization=None):
    state = {"robot_id": "rosy_01", "map_id": map_id, "pose": {"x": x, "y": y, "yaw": 0.0}}
    if localization is not None:
        state["localization"] = localization
    return state


def _robots(**states):
    return [{"robot_id": rid, "online": True, "state": state} for rid, state in states.items()]


def _rows(service):
    return {row["robot_id"]: row for row in service.snapshot()["robots"]}


def test_matched_robot_reports_the_offset_and_the_rest_is_unknown():
    service, _ = _service()
    record = service.approve(dict(APPROVAL), approved_by="operator-1")
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4, localization={
        "state": "LOCALIZED", "pose_frame": "map", "confidence": 0.9})))
    service.accept(AUTH, _payload(calibration_revision=record["calibration_revision"]))
    snap = service.snapshot()
    rows = {row["robot_id"]: row for row in snap["robots"]}
    assert rows["rosy_01"]["status"] == "MATCHED"
    assert rows["rosy_01"]["offset_m"] == pytest.approx(0.0471, abs=1e-4)
    assert rows["rosy_01"]["camera"] == {"x": 1.2345, "y": 0.4321, "footprint_m": 0.181, "score": 0.83}
    assert rows["rosy_01"]["pose"] == {"x": 1.2, "y": 0.4}
    assert rows["rosy_01"]["pose_frame_verified"] is True
    assert rows["rosy_02"]["status"] == "NO_POSE"
    assert [(row["x"], row["y"]) for row in snap["unknown"]] == [(2.5, 1.0)]
    assert snap["sources"][0]["status"] == "OK"
    assert snap["use"] == "display-only"


def test_marker_calibration_revision_is_accepted_without_a_record():
    service, _ = _service()
    assert service.accept(AUTH, _payload(calibration_revision="cal-v3")) == {
        "accepted": True, "source_id": "ceiling_north", "seq": 41, "status": "OK"}


def test_unknown_calibration_revision_is_409_and_shown_as_mismatch():
    service, _ = _service()
    with pytest.raises(TrackingError) as err:
        service.accept(AUTH, _payload())
    assert (err.value.status_code, err.value.code) == (409, "CALIBRATION_MISMATCH")
    assert service.snapshot()["sources"][0]["last_error"] == "CALIBRATION_MISMATCH"
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert service.snapshot()["sources"][0]["last_error"] is None


@pytest.mark.parametrize("authorization,changes,status,code", [
    (None, {}, 401, "DETECTION_UNAUTHORIZED"),
    ("Bearer wrong", {}, 401, "DETECTION_UNAUTHORIZED"),
    (AUTH, {"source_id": "ceiling_south"}, 403, "SOURCE_MISMATCH"),
    (AUTH, {"map_id": "other_map"}, 409, "MAP_MISMATCH"),
    (AUTH, {"captured_at": NOW - 1.5}, 409, "DETECTION_STALE"),
    (AUTH, {"captured_at": NOW + 1.0}, 409, "DETECTION_FUTURE"),
])
def test_rejected_payloads(authorization, changes, status, code):
    service, _ = _service()
    with pytest.raises(TrackingError) as err:
        service.accept(authorization, _payload(calibration_revision="cal-v3", **changes))
    assert (err.value.status_code, err.value.code) == (status, code)


def test_out_of_order_payload_is_rejected():
    service, _ = _service()
    service.accept(AUTH, _payload(calibration_revision="cal-v3", seq=2))
    with pytest.raises(TrackingError) as err:
        service.accept(AUTH, _payload(calibration_revision="cal-v3", seq=3, captured_at=NOW - 0.2))
    assert err.value.code == "DETECTION_OUT_OF_ORDER"


def test_payload_expires_after_the_lease_and_nothing_old_is_shown():
    service, clock = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    clock.now = NOW + 1.0
    snap = service.snapshot()
    assert snap["sources"][0]["status"] == "STALE"
    assert {row["status"] for row in snap["robots"]} == {"CAMERA_UNAVAILABLE"}
    assert snap["unknown"] == []


def test_no_payload_yet_is_none_and_camera_unavailable():
    service, _ = _service()
    snap = service.snapshot()
    assert snap["sources"][0]["status"] == "NONE"
    assert {row["status"] for row in snap["robots"]} == {"CAMERA_UNAVAILABLE"}


def test_learning_status_means_camera_unavailable():
    service, _ = _service()
    service.accept(AUTH, _payload(calibration_revision="cal-v3", status="LEARNING", detections=[]))
    snap = service.snapshot()
    assert snap["sources"][0]["status"] == "LEARNING"
    assert {row["status"] for row in snap["robots"]} == {"CAMERA_UNAVAILABLE"}


@pytest.mark.parametrize("state", [
    _state(1.2, 0.4, map_id="other_map"),
    _state(1.2, 0.4, localization={"state": "LOCALIZED", "pose_frame": "odom"}),
    _state(1.2, 0.4, localization={"state": "SUSPECT", "pose_frame": "map"}),
    {"robot_id": "rosy_01", "map_id": "map_v2_fleet"},
])
def test_robot_without_a_trusted_map_pose_is_no_pose(state):
    service, _ = _service()
    service.observe_states(_robots(rosy_01=state))
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"
    assert len(service.snapshot()["unknown"]) == 2


def test_robot_that_predates_d395_is_matched_but_marked_unverified():
    service, _ = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    row = _rows(service)["rosy_01"]
    assert row["status"] == "MATCHED" and row["pose_frame_verified"] is False


def test_state_older_than_two_seconds_is_no_pose():
    service, clock = _service()
    service.observe_states(_robots(rosy_01=_state(1.2, 0.4)))
    clock.now = NOW + 2.5
    service.accept(AUTH, _payload(calibration_revision="cal-v3", captured_at=NOW + 2.4))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"


def test_offline_rows_are_ignored():
    service, _ = _service()
    service.observe_states([{"robot_id": "rosy_01", "online": False, "state": None}])
    service.accept(AUTH, _payload(calibration_revision="cal-v3"))
    assert _rows(service)["rosy_01"]["status"] == "NO_POSE"


def test_config_returns_the_approved_record_and_relearn_counter():
    service, _ = _service()
    assert service.config_for(AUTH) == {"source_id": "ceiling_north", "map_id": "map_v2_fleet",
                                        "calibration": None, "relearn_seq": 0}
    record = service.approve(dict(APPROVAL), approved_by="operator-1")
    assert service.request_relearn("ceiling_north") == {"source_id": "ceiling_north", "relearn_seq": 1}
    config = service.config_for(AUTH)
    assert config["calibration"] == record and config["relearn_seq"] == 1
    assert record["approved_by"] == "operator-1" and record["map_id"] == "map_v2_fleet"
    assert record["calibration_revision"].startswith("paint-")
    assert service.calibration_listing() == {"calibrations": [record], "use": "display-only"}
    with pytest.raises(TrackingError) as err:
        service.config_for("Bearer wrong")
    assert err.value.status_code == 401


@pytest.mark.parametrize("changes,code", [
    ({"source_id": "nope"}, "UNKNOWN_SOURCE"),
    ({"map_id": "other_map"}, "MAP_MISMATCH"),
    ({"map_to_image": [0.0] * 9}, "INVALID_CALIBRATION"),
])
def test_approval_refuses_unknown_source_other_map_and_bad_matrix(changes, code):
    service, _ = _service()
    with pytest.raises(TrackingError) as err:
        service.approve({**APPROVAL, **changes}, approved_by="operator-1")
    assert err.value.code == code


def test_revoke_removes_the_record_and_unknown_sources_are_404():
    service, _ = _service()
    service.approve(dict(APPROVAL), approved_by="operator-1")
    assert service.revoke("ceiling_north", principal_id="operator-1") == {
        "source_id": "ceiling_north", "removed": True}
    assert service.config_for(AUTH)["calibration"] is None
    for call in (lambda: service.revoke("nope", principal_id="operator-1"),
                 lambda: service.request_relearn("nope")):
        with pytest.raises(TrackingError) as err:
            call()
        assert err.value.status_code == 404


def test_fps_counts_accepted_payloads_over_three_seconds():
    service, clock = _service()
    for index in range(6):
        clock.now = NOW + index / 3
        service.accept(AUTH, _payload(calibration_revision="cal-v3", seq=index,
                                      captured_at=clock.now - 0.05))
    assert service.snapshot()["sources"][0]["fps"] == 2.0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_service.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.server.tracking'`.

- [ ] **Step 3: 서비스를 구현한다**

`src/site/fleet/fleet/server/tracking.py`:

```python
"""Overhead markerless tracking on the console map (D-NNN 4-6). Display and cross-check only.

Vision posts anonymous floor detections per camera source with that source's sighting
token. Fleet keeps the last payload per source for ``lease_s`` (1.0 s, the sighting
lease), checks its calibration revision against the corner-marker revision and the
approved paint-fit record, and pairs fresh map-frame robot poses with detections
(tracking_match.py). Robot states arrive through ``observe_states`` from the console
state route; nothing here calls a robot. Traffic, bays, missions and localization never
import this module (test_boundaries.py).
"""

from __future__ import annotations

import hmac
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from fleet.server.sightings import SightingSource
from fleet.server.tracking_calibration import TrackingCalibrationStore, build_record
from fleet.server.tracking_match import GATE_M, Pose, Seen, Track, better, match

DETECTION_LEASE_S = 1.0
MAX_FUTURE_S = 0.05
#: A robot state older than this (seen through the console state route) is no pose.
STATE_FRESH_S = 2.0
FPS_WINDOW_S = 3.0


class TrackingError(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class _SourceState:
    payload: Optional[OverheadDetectionsPayload] = None
    arrivals: deque = field(default_factory=deque)
    last_error: Optional[str] = None
    relearn_seq: int = 0


class TrackingService:
    def __init__(self, sources: Sequence[SightingSource], *, calibrations: TrackingCalibrationStore,
                 clock: Callable[[], float] = time.time, lease_s: float = DETECTION_LEASE_S,
                 state_fresh_s: float = STATE_FRESH_S, gate_m: float = GATE_M) -> None:
        for value in (lease_s, state_fresh_s, gate_m):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("tracking lease, state freshness and gate must be positive")
        self.sources = tuple(sources)
        self._by_id = {source.source_id: source for source in self.sources}
        self.calibrations = calibrations
        self._clock = clock
        self.lease_s = lease_s
        self.state_fresh_s = state_fresh_s
        self.gate_m = gate_m
        self._sources = {source.source_id: _SourceState() for source in self.sources}
        self._states: dict[str, tuple[dict, float]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.sources)

    def authenticate(self, authorization: Optional[str]) -> SightingSource:
        candidate = authorization or ""
        matched: Optional[SightingSource] = None
        for source in self.sources:
            if hmac.compare_digest(candidate, f"Bearer {source.token}"):
                matched = source
        if matched is None:
            raise TrackingError(401, "DETECTION_UNAUTHORIZED", "source token required")
        return matched

    def config_for(self, authorization: Optional[str]) -> dict:
        source = self.authenticate(authorization)
        record = self.calibrations.get(source.source_id)
        usable = record is not None and record.map_id == source.map_id
        return {"source_id": source.source_id, "map_id": source.map_id,
                "calibration": record.to_dict() if usable else None,
                "relearn_seq": self._sources[source.source_id].relearn_seq}

    def accept(self, authorization: Optional[str], payload: OverheadDetectionsPayload) -> dict:
        source = self.authenticate(authorization)
        state = self._sources[source.source_id]
        if payload.source_id != source.source_id:
            raise TrackingError(403, "SOURCE_MISMATCH", "payload source does not match the token")
        if payload.map_id != source.map_id:
            state.last_error = "MAP_MISMATCH"
            raise TrackingError(409, "MAP_MISMATCH", "detection map does not match source configuration")
        if (payload.calibration_revision is not None
                and payload.calibration_revision not in self._revisions(source)):
            state.last_error = "CALIBRATION_MISMATCH"
            raise TrackingError(409, "CALIBRATION_MISMATCH",
                                "detection calibration is neither the marker nor the approved one")
        now = self._clock()
        age_s = now - payload.captured_at
        if age_s < -MAX_FUTURE_S:
            raise TrackingError(409, "DETECTION_FUTURE", "detection capture time is in the future")
        if age_s > self.lease_s:
            raise TrackingError(409, "DETECTION_STALE", "detection exceeded the display lease")
        if state.payload is not None and payload.captured_at <= state.payload.captured_at:
            raise TrackingError(409, "DETECTION_OUT_OF_ORDER", "detection is not newer than readback")
        state.payload = payload
        state.last_error = None
        state.arrivals.append(now)
        self._trim(state, now)
        return {"accepted": True, "source_id": source.source_id, "seq": payload.seq,
                "status": payload.status}

    def approve(self, body: Mapping, *, approved_by: str) -> dict:
        source = self._by_id.get(body.get("source_id"))
        if source is None:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        map_id = body.get("map_id") or source.map_id
        if map_id != source.map_id:
            raise TrackingError(409, "MAP_MISMATCH", "calibration map does not match source configuration")
        try:
            image = body["image"]
            bounds = body["track_bounds_m"]
            record = build_record(
                source_id=source.source_id, map_id=map_id, map_to_image=body["map_to_image"],
                image_width=image["width"], image_height=image["height"],
                track_bounds_m=(bounds["min_x"], bounds["min_y"], bounds["max_x"], bounds["max_y"]),
                lens=body.get("lens"), fit_score=body["fit_score"], frame_seq=body.get("frame_seq"),
                approved_by=approved_by, approved_at=self._clock())
        except (KeyError, TypeError, ValueError) as exc:
            raise TrackingError(422, "INVALID_CALIBRATION", str(exc)) from exc
        self.calibrations.put(record)
        return record.to_dict()

    def revoke(self, source_id: str, *, principal_id: str) -> dict:
        if source_id not in self._by_id:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        removed = self.calibrations.delete(source_id, principal_id=principal_id, at=self._clock())
        return {"source_id": source_id, "removed": removed}

    def calibration_listing(self) -> dict:
        return {"calibrations": [record.to_dict() for record in self.calibrations.all()],
                "use": "display-only"}

    def request_relearn(self, source_id: str) -> dict:
        if source_id not in self._by_id:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        state = self._sources[source_id]
        state.relearn_seq += 1
        return {"source_id": source_id, "relearn_seq": state.relearn_seq}

    def observe_states(self, robots: Sequence[Mapping]) -> None:
        """Remember the robot states the console state route just gathered."""
        now = self._clock()
        for row in robots:
            if not isinstance(row, Mapping):
                continue
            robot_id = row.get("robot_id")
            state = row.get("state")
            if row.get("online") and isinstance(robot_id, str) and isinstance(state, Mapping):
                self._states[robot_id] = (dict(state), now)

    def snapshot(self) -> dict:
        now = self._clock()
        sources_out: list[dict] = []
        unknown: list[dict] = []
        tracks: dict[str, Track] = {}
        track_source: dict[str, str] = {}
        for source in self.sources:
            state = self._sources[source.source_id]
            self._trim(state, now)
            payload = state.payload
            fresh = payload is not None and now - payload.captured_at <= self.lease_s
            status = payload.status if fresh else ("STALE" if payload is not None else "NONE")
            sources_out.append({
                "source_id": source.source_id,
                "map_id": source.map_id,
                "status": status,
                "calibration_revision": payload.calibration_revision if fresh else None,
                "age_ms": None if payload is None else round((now - payload.captured_at) * 1000.0),
                "fps": round(len(state.arrivals) / FPS_WINDOW_S, 1),
                "last_error": state.last_error,
                "relearn_seq": state.relearn_seq,
            })
            seen = ([Seen(d.x, d.y, d.footprint_m, d.score) for d in payload.detections]
                    if fresh and status == "OK" else None)
            poses = {rid: self._pose(rid, source.map_id, now) for rid in source.robot_ids}
            rows, extra = match(source.robot_ids, poses, seen, self.gate_m)
            for row in rows:
                prior = tracks.get(row.robot_id)
                chosen = row if prior is None else better(prior, row)
                if chosen is row:
                    track_source[row.robot_id] = source.source_id
                tracks[row.robot_id] = chosen
            unknown.extend({"source_id": source.source_id, "x": item.x, "y": item.y,
                            "footprint_m": item.footprint_m, "score": item.score} for item in extra)
        robots = [_render(tracks[rid], track_source[rid]) for rid in sorted(tracks)]
        return {"ts": now, "lease_s": self.lease_s, "gate_m": self.gate_m, "use": "display-only",
                "sources": sources_out, "robots": robots, "unknown": unknown}

    def _revisions(self, source: SightingSource) -> set[str]:
        allowed = {source.calibration_revision}  # corner-marker path (CameraMap), D-NNN 2
        record = self.calibrations.get(source.source_id)
        if record is not None and record.map_id == source.map_id:
            allowed.add(record.calibration_revision)
        return allowed

    def _pose(self, robot_id: str, map_id: str, now: float) -> Optional[Pose]:
        entry = self._states.get(robot_id)
        if entry is None or now - entry[1] > self.state_fresh_s:
            return None
        state = entry[0]
        if state.get("map_id") != map_id:
            return None
        localization = state.get("localization")
        verified = False
        if localization is not None:
            if (not isinstance(localization, Mapping) or localization.get("pose_frame") != "map"
                    or localization.get("state") != "LOCALIZED"):
                return None
            verified = True
        pose = state.get("pose")
        try:
            x, y = float(pose["x"]), float(pose["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        return Pose(x, y, verified)

    @staticmethod
    def _trim(state: _SourceState, now: float) -> None:
        while state.arrivals and now - state.arrivals[0] > FPS_WINDOW_S:
            state.arrivals.popleft()


def _render(track: Track, source_id: str) -> dict:
    return {
        "robot_id": track.robot_id,
        "status": track.status,
        "source_id": source_id,
        "offset_m": track.offset_m,
        "camera": None if track.camera is None else {
            "x": track.camera.x, "y": track.camera.y,
            "footprint_m": track.camera.footprint_m, "score": track.camera.score},
        "pose": None if track.pose is None else {"x": track.pose.x, "y": track.pose.y},
        "pose_frame_verified": None if track.pose is None else track.pose.verified,
    }
```

- [ ] **Step 4: 서비스 시험 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_service.py -q -p no:cacheprovider`
Expected: PASS — `26 passed`.

- [ ] **Step 5: 실패하는 경로·경계 시험을 쓴다**

`src/site/fleet/test/test_overhead_tracking_api.py`:

```python
"""D-NNN routes: Vision writes and reads with its source token; the console reads and approves."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore
from fleet.swarm.robots import RobotEndpoint

NOW = 1_790_000_000.0
SOURCE_TOKEN = "north-source-secret"
OPERATOR_TOKEN = "operator-secret"
VIEWER_TOKEN = "viewer-secret"
FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
OK = next(case for case in FIXTURE["cases"] if case["id"] == "ok_two_detections")["payload"]
APPROVAL = {
    "source_id": "ceiling_north",
    "map_to_image": [100.0, 0.0, 0.0, 0.0, -100.0, 360.0, 0.0, 0.0, 1.0],
    "image": {"width": 640, "height": 360},
    "track_bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 6.4, "max_y": 3.6},
    "fit_score": 0.81, "lens": None, "frame_seq": 12,
}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _source():
    return SightingSource(source_id="ceiling_north", token=SOURCE_TOKEN, robot_ids=("rosy_01",),
                          map_id="map_v2_fleet", calibration_revision="cal-v3",
                          corner_marker_ids=(30, 31, 32, 33))


def _client(tmp_path):
    def clock():
        return NOW

    robot = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "map_id": "map_v2_fleet",
                                        "pose": {"x": 1.2, "y": 0.4, "yaw": 0.0}})
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-rest")], [robot])
    sightings = SightingService([_source()], known_robot_ids=console.robot_ids, clock=clock)
    tracking = TrackingService(sightings.sources, calibrations=TrackingCalibrationStore(), clock=clock)
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"rosy_01"})
    users = {
        sha256(OPERATOR_TOKEN.encode()).hexdigest(): {"principal_id": "operator-1", "role": "operator"},
        sha256(VIEWER_TOKEN.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"},
    }
    app = create_app(console, sightings=sightings, tracking=tracking, task_service=task_service,
                     start_task_dispatcher=False, site_users=users)
    return TestClient(app)


def _detections(**changes):
    return {**OK, "calibration_revision": "cal-v3", "captured_at": NOW - 0.1, **changes}


def test_vision_writes_detections_and_reads_only_its_own_config(tmp_path):
    with _client(tmp_path) as client:
        accepted = client.post("/api/fleet/detections", json=_detections(), headers=_auth(SOURCE_TOKEN))
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {"accepted": True, "source_id": "ceiling_north", "seq": 41, "status": "OK"}
        config = client.get("/api/fleet/detections/config", headers=_auth(SOURCE_TOKEN))
        assert config.json() == {"source_id": "ceiling_north", "map_id": "map_v2_fleet",
                                 "calibration": None, "relearn_seq": 0}
        assert client.get("/api/fleet/detections/config").status_code == 401
        assert client.get("/api/fleet/tracking", headers=_auth(SOURCE_TOKEN)).status_code == 401
        assert client.post("/api/fleet/calibrations", json=APPROVAL,
                           headers=_auth(SOURCE_TOKEN)).status_code == 401


@pytest.mark.parametrize("extra", [{"robot_id": "rosy_01"}, {"image": "AAAA"}])
def test_payload_with_a_robot_id_or_image_is_refused(tmp_path, extra):
    with _client(tmp_path) as client:
        response = client.post("/api/fleet/detections", json=_detections(**extra),
                               headers=_auth(SOURCE_TOKEN))
    assert response.status_code == 422


def test_operator_approves_viewer_reads_and_vision_sees_the_record(tmp_path):
    with _client(tmp_path) as client:
        assert client.post("/api/fleet/calibrations", json=APPROVAL,
                           headers=_auth(VIEWER_TOKEN)).status_code == 403
        approved = client.post("/api/fleet/calibrations", json=APPROVAL, headers=_auth(OPERATOR_TOKEN))
        assert approved.status_code == 200, approved.text
        record = approved.json()
        assert record["approved_by"] == "operator-1" and record["use"] == "display-only"
        listing = client.get("/api/fleet/calibrations", headers=_auth(VIEWER_TOKEN)).json()
        assert listing == {"calibrations": [record], "use": "display-only"}
        assert client.get("/api/fleet/detections/config",
                          headers=_auth(SOURCE_TOKEN)).json()["calibration"] == record
        mismatch = client.post("/api/fleet/detections",
                               json=_detections(calibration_revision="paint-000000000000"),
                               headers=_auth(SOURCE_TOKEN))
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "CALIBRATION_MISMATCH"
        fitted = client.post("/api/fleet/detections",
                             json=_detections(calibration_revision=record["calibration_revision"]),
                             headers=_auth(SOURCE_TOKEN))
        assert fitted.status_code == 200, fitted.text
        assert client.delete("/api/fleet/calibrations/ceiling_north",
                             headers=_auth(VIEWER_TOKEN)).status_code == 403
        assert client.delete("/api/fleet/calibrations/ceiling_north",
                             headers=_auth(OPERATOR_TOKEN)).json() == {"source_id": "ceiling_north",
                                                                       "removed": True}


def test_bad_approval_bodies_are_refused(tmp_path):
    with _client(tmp_path) as client:
        for body, status in [({**APPROVAL, "map_to_image": [1.0] * 8}, 422),
                             ({**APPROVAL, "extra": 1}, 422),
                             ({**APPROVAL, "map_to_image": [0.0] * 9}, 422),
                             ({**APPROVAL, "source_id": "nope"}, 404),
                             ({**APPROVAL, "map_id": "other_map"}, 409)]:
            response = client.post("/api/fleet/calibrations", json=body, headers=_auth(OPERATOR_TOKEN))
            assert response.status_code == status, (body, response.text)


def test_tracking_pairs_the_console_state_with_detections(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/fleet/state", headers=_auth(VIEWER_TOKEN)).status_code == 200
        client.post("/api/fleet/detections", json=_detections(), headers=_auth(SOURCE_TOKEN))
        snap = client.get("/api/fleet/tracking", headers=_auth(VIEWER_TOKEN)).json()
    assert [(row["robot_id"], row["status"]) for row in snap["robots"]] == [("rosy_01", "MATCHED")]
    assert snap["robots"][0]["pose_frame_verified"] is False
    assert [(row["x"], row["y"]) for row in snap["unknown"]] == [(2.5, 1.0)]


def test_relearn_is_an_operator_action(tmp_path):
    with _client(tmp_path) as client:
        body = {"source_id": "ceiling_north"}
        assert client.post("/api/fleet/tracking/relearn", json=body,
                           headers=_auth(VIEWER_TOKEN)).status_code == 403
        response = client.post("/api/fleet/tracking/relearn", json=body, headers=_auth(OPERATOR_TOKEN))
        assert response.json() == {"source_id": "ceiling_north", "relearn_seq": 1}
        assert client.post("/api/fleet/tracking/relearn", json={"source_id": "nope"},
                           headers=_auth(OPERATOR_TOKEN)).status_code == 404
        assert client.get("/api/fleet/detections/config",
                          headers=_auth(SOURCE_TOKEN)).json()["relearn_seq"] == 1


def test_tracking_routes_are_exactly_these_and_name_no_media(tmp_path):
    with _client(tmp_path) as client:
        paths = {route.path for route in client.app.routes if hasattr(route, "path")}
    ours = {path for path in paths
            if any(word in path for word in ("detections", "tracking", "calibrations"))}
    assert ours == {"/api/fleet/detections", "/api/fleet/detections/config", "/api/fleet/tracking",
                    "/api/fleet/tracking/relearn", "/api/fleet/calibrations",
                    "/api/fleet/calibrations/{source_id}"}


def test_tracking_needs_the_sighting_sources():
    tracking = TrackingService([_source()], calibrations=TrackingCalibrationStore())
    with pytest.raises(ValueError, match="sighting sources"):
        create_app(FleetConsole([], []), tracking=tracking)
```

`src/site/fleet/test/test_boundaries.py` 끝에 붙인다:

```python


#: D-NNN 5: overhead tracking is display only. Besides its own modules, only the app wiring,
#: the console state route (which hands it robot states) and the CLI may name it.
TRACKING_IMPORTERS = {"server/app.py", "server/console_routes.py", "server/tracking.py",
                      "server/tracking_routes.py", "cli.py"}


def _names_tracking(name: str) -> bool:
    leaf = name.rsplit(".", 1)[-1]
    return leaf.startswith("tracking") and (name.startswith("fleet.server.") or "." not in name)


def test_traffic_bays_missions_and_localization_never_read_overhead_tracking():
    offenders = []
    for path in _py_files(FLEET_PKG):
        rel = path.relative_to(FLEET_PKG).as_posix()
        if rel in TRACKING_IMPORTERS:
            continue
        offenders += [f"{rel} imports {name}" for name in _imports(path) if _names_tracking(name)]
    assert offenders == []
```

- [ ] **Step 6: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_api.py src/site/fleet/test/test_boundaries.py -q -p no:cacheprovider`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'tracking'` (경계 시험은 이미 PASS).

- [ ] **Step 7: 경로를 쓴다**

`src/site/fleet/fleet/server/tracking_routes.py`:

```python
"""Overhead markerless tracking routes (D-NNN 4-7).

Vision writes detections and reads its own tracking config with its source token; the
console reads tracking and calibrations (viewer) and approves, revokes and relearns
(operator). No path names a camera, image or video (test_no_video_relay) and none
contains "vision" (test_app_roles): Fleet never relays frames (D-318).
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from fleet.server.site_auth import SitePrincipal
from fleet.server.tracking import TrackingError


class _ImageSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0, le=8192, strict=True)
    height: int = Field(gt=0, le=8192, strict=True)


class _Bounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_x: float = Field(allow_inf_nan=False)
    min_y: float = Field(allow_inf_nan=False)
    max_x: float = Field(allow_inf_nan=False)
    max_y: float = Field(allow_inf_nan=False)


class _Lens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z_]{1,32}$")
    focal_mm: float = Field(gt=0.0, le=1000.0, allow_inf_nan=False)
    hfov_deg: float = Field(gt=0.0, lt=180.0, allow_inf_nan=False)


class CalibrationApproval(BaseModel):
    """The console's "추적 보정 적용" body: one accepted D-375 fit for one source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    map_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    map_to_image: list[float] = Field(min_length=9, max_length=9)
    image: _ImageSize
    track_bounds_m: _Bounds
    fit_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    lens: Optional[_Lens] = None
    frame_seq: Optional[int] = Field(default=None, ge=0)


class RelearnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)


def _http(exc: TrackingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def install_tracking_routes(app, *, tracking, require_operator, read_guard, operator_guard) -> None:
    @app.post("/api/fleet/detections", tags=["tracking"])
    async def submit_detections(body: OverheadDetectionsPayload,
                                authorization: Optional[str] = Header(default=None)) -> dict:
        try:
            return tracking.accept(authorization, body)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.get("/api/fleet/detections/config", tags=["tracking"])
    async def detection_config(authorization: Optional[str] = Header(default=None)) -> dict:
        try:
            return tracking.config_for(authorization)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.get("/api/fleet/tracking", dependencies=read_guard, tags=["tracking"])
    async def tracking_readback() -> dict:
        return tracking.snapshot()

    @app.post("/api/fleet/tracking/relearn", dependencies=operator_guard, tags=["tracking"])
    async def tracking_relearn(body: RelearnRequest) -> dict:
        try:
            return tracking.request_relearn(body.source_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.get("/api/fleet/calibrations", dependencies=read_guard, tags=["tracking"])
    async def calibration_listing() -> dict:
        return tracking.calibration_listing()

    @app.post("/api/fleet/calibrations", tags=["tracking"])
    async def approve_calibration(body: CalibrationApproval,
                                  principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.approve(body.model_dump(), approved_by=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc

    @app.delete("/api/fleet/calibrations/{source_id}", tags=["tracking"])
    async def revoke_calibration(source_id: str,
                                 principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return tracking.revoke(source_id, principal_id=principal.principal_id)
        except TrackingError as exc:
            raise _http(exc) from exc
```

- [ ] **Step 8: app·console_routes·cli를 잇는다**

`src/site/fleet/fleet/server/app.py:107` — 바꾼다:

```python
               pairing=None, pairing_sync_token: Optional[str] = None) -> FastAPI:
```
→
```python
               pairing=None, pairing_sync_token: Optional[str] = None,
               tracking=None) -> FastAPI:
```

`app.py:307`의 `    principals = parse_site_principals(site_users, console)` 바로 앞에 넣는다:

```python
    # D-NNN: tracking authenticates with the sighting source tokens, which install_ingest_routes
    # isolates from every other credential; it must therefore be built from those same sources.
    if tracking is not None and (sightings is None
                                 or tuple(tracking.sources) != tuple(sightings.sources)):
        raise ValueError("overhead tracking must use the configured sighting sources")
```

`app.py:353-355`의 `install_console_routes(...)` 호출을 바꾼다:

```python
    install_console_routes(app, console=console, sightings=sightings,
                           require_viewer=require_viewer, read_guard=read_guard,
                           operator_guard=operator_guard, site_lanes=site_lanes)
```
→
```python
    install_console_routes(app, console=console, sightings=sightings,
                           require_viewer=require_viewer, read_guard=read_guard,
                           operator_guard=operator_guard, site_lanes=site_lanes,
                           tracking=tracking)

    if tracking is not None and tracking.enabled:
        from fleet.server.tracking_routes import install_tracking_routes

        install_tracking_routes(app, tracking=tracking, require_operator=require_operator,
                                read_guard=read_guard, operator_guard=operator_guard)
```

`src/site/fleet/fleet/server/console_routes.py:46-50` — 바꾼다:

```python
def install_console_routes(app, *, console, sightings, require_viewer,
                           read_guard, operator_guard, site_lanes=None) -> None:
    @app.get("/api/fleet/state", dependencies=read_guard, tags=["fleet"])
    async def fleet_state() -> dict:
        return await console.snapshot()
```
→
```python
def install_console_routes(app, *, console, sightings, require_viewer,
                           read_guard, operator_guard, site_lanes=None, tracking=None) -> None:
    @app.get("/api/fleet/state", dependencies=read_guard, tags=["fleet"])
    async def fleet_state() -> dict:
        snapshot = await console.snapshot()
        if tracking is not None:
            # D-NNN 5: overhead tracking reads the states the console already gathered; it never
            # calls a robot itself (console.py is at its size verdict and stays untouched).
            tracking.observe_states(snapshot["robots"])
        return snapshot
```

`src/site/fleet/fleet/cli.py:392` — `    sighting_service = None` 다음 줄에 넣는다:

```python
    tracking_service = None
```

`cli.py:407-410`의 `sighting_service = SightingService(...)` 문 바로 뒤(같은 `if sightings_config is not None:` 블록 안, 들여쓰기 8칸)에 넣는다:

```python
        from fleet.server.tracking import TrackingService
        from fleet.server.tracking_calibration import TrackingCalibrationStore

        # D-NNN: approved tracking calibrations live beside the sightings (memory without a DB).
        tracking_service = TrackingService(
            sighting_service.sources, calibrations=TrackingCalibrationStore(sightings_db))
```

`cli.py:473` — 바꾼다:

```python
                     hub=hub, sightings=sighting_service, task_service=task_service,
```
→
```python
                     hub=hub, sightings=sighting_service, tracking=tracking_service,
                     task_service=task_service,
```

- [ ] **Step 9: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_api.py src/site/fleet/test/test_overhead_tracking_service.py src/site/fleet/test/test_boundaries.py src/site/fleet/test/test_sightings_api.py src/site/fleet/test/test_no_video_relay.py src/site/fleet/test/test_server_app.py src/site/fleet/test/test_cli.py test/architecture/test_app_roles.py -q -p no:cacheprovider`
Expected: PASS(새 시험 `test_overhead_tracking_api.py` 9 passed 포함, 기존 시험은 이전과 같은 수).

- [ ] **Step 10: 커밋**

```bash
git add src/site/fleet/fleet/server/tracking.py src/site/fleet/fleet/server/tracking_routes.py src/site/fleet/fleet/server/app.py src/site/fleet/fleet/server/console_routes.py src/site/fleet/fleet/cli.py src/site/fleet/test/test_overhead_tracking_service.py src/site/fleet/test/test_overhead_tracking_api.py src/site/fleet/test/test_boundaries.py
git diff --cached --name-only
git commit -m "feat(fleet): D-NNN overhead tracking service, routes and console-state wiring" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Vision 추적 인터페이스와 기하

**Files:**
- Create: `src/site/vision/rosy_vision/track/__init__.py`, `src/site/vision/rosy_vision/track/model.py`, `src/site/vision/rosy_vision/track/geometry.py`
- Test: `src/site/vision/test/test_overhead_track_model.py`, `src/site/vision/test/test_overhead_track_geometry.py`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/site/vision/test/test_overhead_track_model.py`:

```python
"""D-NNN 3: tracking constants come from the Pinky URDF NOMINAL; Calibration refuses bad input."""

from pathlib import Path

import pytest
import yaml

from rosy_vision.track.model import (
    FOOTPRINT_MAX_M, FOOTPRINT_MIN_M, ROBOT_TOP_HEIGHT_M, ROTATION_RADIUS_M, Calibration,
)

GEOMETRY = Path(__file__).resolve().parents[3] / "products/pinky_pro/profile/config/geometry.yaml"


def test_robot_constants_follow_the_urdf_nominal():
    nominal = yaml.safe_load(GEOMETRY.read_text(encoding="utf-8"))
    assert ROBOT_TOP_HEIGHT_M == nominal["lidar"]["height_m"]
    assert ROTATION_RADIUS_M == nominal["footprint"]["rotation_radius_m"]
    assert FOOTPRINT_MIN_M < 2 * ROTATION_RADIUS_M < FOOTPRINT_MAX_M


def _calibration(**changes):
    args = dict(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                image_to_map=(0.01, 0.0, 0.0, 0.0, -0.01, 3.6, 0.0, 0.0, 1.0),
                image_size=(640, 360), track_bounds_m=(0.0, 0.0, 6.4, 3.6))
    args.update(changes)
    return Calibration(**args)


def test_a_valid_calibration_is_kept_as_given():
    calibration = _calibration(hfov_deg=66.9)
    assert calibration.image_size == (640, 360) and calibration.hfov_deg == 66.9


@pytest.mark.parametrize("changes", [
    {"image_to_map": (1.0,) * 8},
    {"image_to_map": (float("inf"),) + (1.0,) * 8},
    {"image_size": (0, 360)},
    {"track_bounds_m": (0.0, 0.0, 0.0, 3.6)},
    {"revision": " "},
])
def test_bad_calibrations_are_refused(changes):
    with pytest.raises(ValueError):
        _calibration(**changes)
```

`src/site/vision/test/test_overhead_track_geometry.py`:

```python
"""D-NNN 3: homography helpers — camera position from a floor homography and height parallax."""

import math

import numpy as np
import pytest

from rosy_vision.track import geometry

SIZE = (1280, 720)
FOCAL = 800.0
HFOV = math.degrees(2 * math.atan((SIZE[0] / 2) / FOCAL))


def _image_to_map(centre, pitch_deg):
    k = np.array([[FOCAL, 0.0, SIZE[0] / 2], [0.0, FOCAL, SIZE[1] / 2], [0.0, 0.0, 1.0]])
    down = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
    a = math.radians(pitch_deg)
    tilt = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(a), -math.sin(a)], [0.0, math.sin(a), math.cos(a)]])
    rotation = tilt @ down
    t = -rotation @ np.asarray(centre, float)
    map_to_image = k @ np.column_stack([rotation[:, 0], rotation[:, 1], t])
    return np.linalg.inv(map_to_image)


@pytest.mark.parametrize("pitch", [0.0, 20.0])
@pytest.mark.parametrize("scale", [1.0, -3.0])
def test_camera_position_is_recovered_from_the_floor_homography(pitch, scale):
    camera = geometry.camera_from_homography(_image_to_map((1.0, 0.5, 2.5), pitch) * scale, SIZE, HFOV)
    assert camera == pytest.approx((1.0, 0.5, 2.5), abs=1e-6)


def test_no_lens_or_implausible_height_means_no_camera():
    image_to_map = _image_to_map((1.0, 0.5, 2.5), 0.0)
    assert geometry.camera_from_homography(image_to_map, SIZE, None) is None
    assert geometry.camera_from_homography(image_to_map, SIZE, 0.0) is None
    assert geometry.camera_from_homography(_image_to_map((0.0, 0.0, 20.0), 0.0), SIZE, HFOV) is None


def test_parallax_pulls_a_top_point_toward_the_nadir():
    assert geometry.parallax_correct((1.0, 0.0), (0.0, 0.0, 2.5), 0.125) == pytest.approx((0.95, 0.0))
    assert geometry.parallax_correct((0.0, 0.0), (0.0, 0.0, 2.5), 0.125) == pytest.approx((0.0, 0.0))


def test_apply_and_scaled_agree_for_a_resized_image():
    image_to_map = np.array([[0.005, 0.0, 0.0], [0.0, -0.005, 3.6], [0.0, 0.0, 1.0]])
    full = geometry.apply(image_to_map, [[600.0, 200.0]])[0]
    half = geometry.apply(geometry.scaled(image_to_map, 0.5, 0.5), [[300.0, 100.0]])[0]
    assert full == pytest.approx((3.0, 2.6)) and half == pytest.approx(full)


def test_as_matrix_refuses_non_finite_values_and_normalized_divides_by_h22():
    with pytest.raises(ValueError):
        geometry.as_matrix([float("nan")] + [0.0] * 8)
    assert geometry.normalized(np.diag([2.0, 2.0, 2.0]))[2, 2] == pytest.approx(1.0)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test/test_overhead_track_model.py src/site/vision/test/test_overhead_track_geometry.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'rosy_vision.track'`.

- [ ] **Step 3: 구현한다**

`src/site/vision/rosy_vision/track/__init__.py`:

```python
"""Markerless overhead robot tracking (D-NNN): anonymous detections, display only."""
```

`src/site/vision/rosy_vision/track/model.py`:

```python
"""Fixed tracking interface (D-NNN 3). Backends change; these types do not."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

Status = Literal["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED"]

#: Pinky Pro URDF NOMINAL (D-397, products/pinky_pro/profile/config/geometry.yaml; the drift
#: test is test_overhead_track_model.py). The silhouette seen from above is the top deck and
#: the LiDAR, the highest part listed, so the parallax height is the LiDAR height.
ROBOT_TOP_HEIGHT_M = 0.125
ROTATION_RADIUS_M = 0.08257
#: Floor-equivalent diameter window around 2 x rotation radius (0.165 m). Start values.
FOOTPRINT_MIN_M = 0.12
FOOTPRINT_MAX_M = 0.26
#: The first LEARNING_FRAMES frames and LEARNING_MIN_S seconds learn the empty track (3 fps).
LEARNING_FRAMES = 30
LEARNING_MIN_S = 10.0
#: More foreground than this share of the track area is a light or camera change.
SCENE_CHANGE_FRACTION = 0.30
MAX_DETECTIONS = 16


@dataclass(frozen=True, eq=False)
class Frame:
    image: np.ndarray   # BGR uint8 at the frame's own resolution
    captured_at: float  # Vision clock (D-261)


@dataclass(frozen=True)
class Calibration:
    source_id: str
    map_id: str
    revision: str
    image_to_map: tuple[float, ...]                    # 9, row-major: frame pixels -> map metres
    image_size: tuple[int, int]                        # (width, height) of the frames it is for
    track_bounds_m: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    hfov_deg: float | None = None                      # lens FOV across the long side; None = no parallax

    def __post_init__(self) -> None:
        if len(self.image_to_map) != 9 or not all(math.isfinite(v) for v in self.image_to_map):
            raise ValueError("image_to_map must be nine finite numbers")
        if len(self.image_size) != 2 or min(self.image_size) <= 0:
            raise ValueError("calibration image size must be positive")
        min_x, min_y, max_x, max_y = self.track_bounds_m
        if (not all(math.isfinite(v) for v in self.track_bounds_m)
                or min_x >= max_x or min_y >= max_y):
            raise ValueError("track bounds must be a finite non-empty rectangle")
        if not self.revision.strip() or not self.source_id.strip() or not self.map_id.strip():
            raise ValueError("source, map and calibration revision are required")


@dataclass(frozen=True)
class Detection:
    x: float            # map m
    y: float            # map m
    footprint_m: float  # floor-projected equivalent diameter
    score: float        # 0..1


@dataclass(frozen=True)
class DetectorResult:
    detections: tuple[Detection, ...]
    status: Status


class RobotDetector(Protocol):
    processor_revision: str

    def detect(self, frame: Frame, calib: Calibration) -> DetectorResult: ...

    def reset(self) -> None: ...
```

`src/site/vision/rosy_vision/track/geometry.py`:

```python
"""Homography helpers for overhead tracking (numpy only, no OpenCV)."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

#: A camera solved from a homography outside this height is not trusted (no parallax step).
MIN_CAMERA_HEIGHT_M = 0.3
MAX_CAMERA_HEIGHT_M = 10.0


def as_matrix(values) -> np.ndarray:
    matrix = np.asarray(values, dtype=float).reshape(3, 3)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("homography must be finite")
    return matrix


def normalized(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=float)
    return matrix / matrix[2, 2] if abs(matrix[2, 2]) > 1e-12 else matrix


def apply(matrix, points) -> np.ndarray:
    """Map (N, 2) points through a 3x3 homography."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    out = np.c_[pts, np.ones(len(pts))] @ np.asarray(matrix, dtype=float).T
    return out[:, :2] / out[:, 2:3]


def scaled(image_to_map, sx: float, sy: float) -> np.ndarray:
    """Image-to-map for an image resized by (sx, sy) from the size the matrix is for."""
    return np.asarray(image_to_map, dtype=float) @ np.diag([1.0 / sx, 1.0 / sy, 1.0])


def camera_from_homography(image_to_map, image_size: Sequence[int],
                           hfov_deg: float | None) -> tuple[float, float, float] | None:
    """Camera nadir (x, y) and height above the floor in map metres, or None.

    Pinhole camera with the principal point at the image centre, square pixels and the
    lens horizontal FOV across the long image side; lens distortion is ignored.
    """
    if hfov_deg is None or not 0.0 < hfov_deg < 180.0:
        return None
    width, height = float(image_size[0]), float(image_size[1])
    focal = (max(width, height) / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    k = np.array([[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]])
    try:
        i2m = as_matrix(image_to_map)
        b = np.linalg.solve(k, np.linalg.inv(i2m))  # K^-1 (map -> image) = s [r1 r2 t]
    except (ValueError, np.linalg.LinAlgError):
        return None
    norm = (np.linalg.norm(b[:, 0]) + np.linalg.norm(b[:, 1])) / 2.0
    if not math.isfinite(norm) or norm < 1e-12:
        return None
    r1, r2, t = b[:, 0] / norm, b[:, 1] / norm, b[:, 2] / norm
    centre = apply(i2m, [[width / 2.0, height / 2.0]])[0]
    if (r1 * centre[0] + r2 * centre[1] + t)[2] < 0:  # the floor point in view is in front
        r1, r2, t = -r1, -r2, -t
    rotation = np.column_stack([r1, r2, np.cross(r1, r2)])
    camera = -rotation.T @ t
    camera_height = abs(float(camera[2]))
    if not MIN_CAMERA_HEIGHT_M <= camera_height <= MAX_CAMERA_HEIGHT_M:
        return None
    return float(camera[0]), float(camera[1]), camera_height


def parallax_correct(point: Sequence[float], camera: Sequence[float],
                     height_m: float) -> tuple[float, float]:
    """The floor point under an object top seen at ``point``: pulled toward the camera nadir."""
    cx, cy, camera_height = camera
    keep = (camera_height - height_m) / camera_height
    return cx + (point[0] - cx) * keep, cy + (point[1] - cy) * keep
```

- [ ] **Step 4: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test/test_overhead_track_model.py src/site/vision/test/test_overhead_track_geometry.py -q -p no:cacheprovider`
Expected: PASS — `15 passed`.

- [ ] **Step 5: 커밋**

```bash
git add src/site/vision/rosy_vision/track/__init__.py src/site/vision/rosy_vision/track/model.py src/site/vision/rosy_vision/track/geometry.py src/site/vision/test/test_overhead_track_model.py src/site/vision/test/test_overhead_track_geometry.py
git diff --cached --name-only
git commit -m "feat(vision): D-NNN tracking interface, URDF constants and homography geometry" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: `background_blob` 검출기

**Files:**
- Create: `src/site/vision/rosy_vision/track/background_blob.py`
- Test: `src/site/vision/test/test_overhead_track_blob.py`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/site/vision/test/test_overhead_track_blob.py`:

```python
"""D-NNN 3: background_blob on synthetic frames (floor with lane paint + a dark robot square)."""

import numpy as np
import pytest

from rosy_vision.track.background_blob import PROCESSOR_REVISION, BackgroundBlobDetector
from rosy_vision.track.model import Calibration, Frame

CAL = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                  image_to_map=(0.01, 0.0, 0.0, 0.0, -0.01, 3.6, 0.0, 0.0, 1.0),
                  image_size=(640, 360), track_bounds_m=(0.0, 0.0, 6.4, 3.6))


def _floor(width=640, height=360):
    image = np.full((height, width, 3), 120, np.uint8)
    image[:, 100:104] = 230
    image[200:204, :] = 230
    return image


def _with_square(side, cx=300, cy=150, image=None):
    image = _floor() if image is None else image
    half = side // 2
    image[cy - half: cy - half + side, cx - half: cx - half + side] = 30
    return image


def _learned(detector=None, calibration=CAL, floor=_floor):
    detector = detector or BackgroundBlobDetector()
    statuses = [detector.detect(Frame(floor(), index / 3), calibration).status for index in range(31)]
    assert statuses == ["LEARNING"] * 31
    return detector


def test_learning_needs_thirty_frames_and_ten_seconds():
    detector = BackgroundBlobDetector()
    statuses = [detector.detect(Frame(_floor(), index / 3), CAL).status for index in range(30)]
    assert statuses == ["LEARNING"] * 30
    assert detector.detect(Frame(_floor(), 10.0), CAL).status == "LEARNING"
    result = detector.detect(Frame(_floor(), 10.34), CAL)
    assert (result.status, result.detections) == ("OK", ())
    assert detector.processor_revision == PROCESSOR_REVISION == "background-blob/1"


def test_robot_sized_blob_is_found_at_its_floor_position():
    detector = _learned()
    result = detector.detect(Frame(_with_square(18), 11.0), CAL)
    assert result.status == "OK" and len(result.detections) == 1
    found = result.detections[0]
    assert found.x == pytest.approx(2.995, abs=0.006)
    assert found.y == pytest.approx(2.105, abs=0.006)
    assert found.footprint_m == pytest.approx(0.2031, abs=0.003)
    assert 0.0 < found.score <= 1.0


@pytest.mark.parametrize("side", [8, 30])
def test_blobs_outside_the_footprint_window_are_dropped(side):
    detector = _learned()
    assert detector.detect(Frame(_with_square(side), 11.0), CAL).detections == ()


def test_a_parked_robot_stays_foreground():
    detector = _learned()
    for index in range(40):
        result = detector.detect(Frame(_with_square(18), 11.0 + index / 3), CAL)
    assert len(result.detections) == 1


def test_more_than_thirty_percent_foreground_is_a_scene_change_and_relearns():
    detector = _learned()
    bright = np.full((360, 640, 3), 200, np.uint8)
    assert detector.detect(Frame(bright, 11.0), CAL).status == "SCENE_CHANGED"
    assert detector.detect(Frame(_floor(), 11.34), CAL).status == "LEARNING"


def test_reset_and_resolution_change_start_learning_again():
    detector = _learned()
    detector.reset()
    assert detector.detect(Frame(_floor(), 11.0), CAL).status == "LEARNING"
    other = _learned()
    assert other.detect(Frame(_floor(320, 180), 11.0), CAL).status == "LEARNING"


def test_blobs_outside_the_track_rectangle_are_ignored():
    narrow = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                         image_to_map=CAL.image_to_map, image_size=(640, 360),
                         track_bounds_m=(0.0, 0.0, 2.0, 3.6))
    detector = _learned(calibration=narrow)
    result = detector.detect(Frame(_with_square(18), 11.0), narrow)
    assert (result.status, result.detections) == ("OK", ())


def test_large_frames_are_downscaled_before_detection():
    big = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                      image_to_map=(0.005, 0.0, 0.0, 0.0, -0.005, 3.6, 0.0, 0.0, 1.0),
                      image_size=(1280, 720), track_bounds_m=(0.0, 0.0, 6.4, 3.6))

    def big_floor():
        image = np.full((720, 1280, 3), 120, np.uint8)
        image[:, 200:208] = 230
        return image

    detector = _learned(calibration=big, floor=big_floor)
    frame = big_floor()
    frame[282:318, 582:618] = 30
    result = detector.detect(Frame(frame, 11.0), big)
    assert len(result.detections) == 1
    found = result.detections[0]
    assert found.x == pytest.approx(2.9975, abs=0.01)
    assert found.y == pytest.approx(3.6 - 0.005 * 299.5, abs=0.01)
    assert found.footprint_m == pytest.approx(0.2031, abs=0.01)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test/test_overhead_track_blob.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'rosy_vision.track.background_blob'`.

- [ ] **Step 3: 구현한다**

`src/site/vision/rosy_vision/track/background_blob.py`:

```python
"""First tracking backend: frozen background and floor-sized blobs (D-NNN 3).

MOG2 learns the empty track while LEARNING (LEARNING_FRAMES frames and LEARNING_MIN_S
seconds), then runs with learning rate 0 so a parked robot stays foreground instead of
fading into the background. MOG2 shadows (127) are not foreground. Pixels outside the
calibrated track rectangle are cleared. Each connected component's floor area is its
pixel count times the homography's local pixel area; with a lens FOV the camera position
is solved from the homography and position and size are corrected for the robot height.
Only blobs whose floor-equivalent diameter is inside the footprint window are kept; no
heading is reported. More than SCENE_CHANGE_FRACTION of the track in the foreground
(light change, camera knocked) drops the frame as SCENE_CHANGED and learns again. A
relearn with robots on the track bakes them in: relearn on an empty track.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from rosy_vision.track import geometry
from rosy_vision.track.model import (
    FOOTPRINT_MAX_M, FOOTPRINT_MIN_M, LEARNING_FRAMES, LEARNING_MIN_S, MAX_DETECTIONS,
    ROBOT_TOP_HEIGHT_M, ROTATION_RADIUS_M, SCENE_CHANGE_FRACTION,
    Calibration, Detection, DetectorResult, Frame,
)

PROCESSOR_REVISION = "background-blob/1"
#: Detection runs on a copy whose long side is at most this many pixels.
WORK_LONG_SIDE = 640
_FOREGROUND = 200  # MOG2 mask: 255 foreground, 127 shadow, 0 background
_MIN_BLOB_PX = 4
_KERNEL = np.ones((3, 3), np.uint8)
_NOMINAL_M = 2.0 * ROTATION_RADIUS_M


class BackgroundBlobDetector:
    processor_revision = PROCESSOR_REVISION

    def __init__(self, *, learning_frames: int = LEARNING_FRAMES,
                 learning_min_s: float = LEARNING_MIN_S,
                 scene_change_fraction: float = SCENE_CHANGE_FRACTION,
                 footprint_m: tuple[float, float] = (FOOTPRINT_MIN_M, FOOTPRINT_MAX_M),
                 robot_height_m: float = ROBOT_TOP_HEIGHT_M) -> None:
        low, high = footprint_m
        if not 0.0 < low < high:
            raise ValueError("footprint window must be 0 < min < max")
        if learning_frames < 1 or learning_min_s < 0:
            raise ValueError("learning needs at least one frame and a non-negative duration")
        if not 0.0 < scene_change_fraction <= 1.0:
            raise ValueError("scene change fraction must be in (0, 1]")
        self._learning_frames = learning_frames
        self._learning_min_s = learning_min_s
        self._scene_change_fraction = scene_change_fraction
        self._footprint = (low, high)
        self._half_window = max(_NOMINAL_M - low, high - _NOMINAL_M)
        self._robot_height_m = robot_height_m
        self._shape: tuple[int, ...] | None = None
        self.reset()

    def reset(self) -> None:
        """Learn the background again from the next frames (operator relearn, scene change)."""
        self._model = cv2.createBackgroundSubtractorMOG2(
            history=self._learning_frames, varThreshold=16, detectShadows=True)
        self._learned = 0
        self._first_at: float | None = None
        self._ready = False

    def detect(self, frame: Frame, calib: Calibration) -> DetectorResult:
        image, sx, sy = _work_image(frame.image)
        if image.shape != self._shape:
            self.reset()
            self._shape = image.shape
        if not self._ready:
            self._model.apply(image, learningRate=-1)
            if self._first_at is None:
                self._first_at = frame.captured_at
            self._learned += 1
            if (self._learned >= self._learning_frames
                    and frame.captured_at - self._first_at >= self._learning_min_s):
                self._ready = True
            return DetectorResult((), "LEARNING")
        raw = self._model.apply(image, learningRate=0)
        image_to_map = geometry.as_matrix(calib.image_to_map)
        work_to_map = geometry.scaled(image_to_map, sx, sy)
        mask = _track_mask(work_to_map, calib.track_bounds_m, image.shape)
        track_px = int(np.count_nonzero(mask))
        if track_px == 0:
            return DetectorResult((), "OK")
        foreground = np.where(raw >= _FOREGROUND, 255, 0).astype(np.uint8)
        foreground = cv2.morphologyEx(cv2.bitwise_and(foreground, mask), cv2.MORPH_OPEN, _KERNEL)
        if np.count_nonzero(foreground) > self._scene_change_fraction * track_px:
            self.reset()
            return DetectorResult((), "SCENE_CHANGED")
        height, width = frame.image.shape[:2]
        camera = geometry.camera_from_homography(image_to_map, (width, height), calib.hfov_deg)
        shrink = 1.0 if camera is None else (camera[2] - self._robot_height_m) / camera[2]
        found: list[Detection] = []
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(foreground, connectivity=8)
        for label in range(1, count):
            pixels = int(stats[label, cv2.CC_STAT_AREA])
            if pixels < _MIN_BLOB_PX:
                continue
            u, v = float(centroids[label][0]), float(centroids[label][1])
            area_m2 = pixels * _pixel_area_m2(work_to_map, u, v)
            diameter = 2.0 * math.sqrt(area_m2 / math.pi) * shrink
            if not self._footprint[0] <= diameter <= self._footprint[1]:
                continue
            x, y = geometry.apply(work_to_map, [[u, v]])[0]
            if camera is not None:
                x, y = geometry.parallax_correct((x, y), camera, self._robot_height_m)
            score = max(0.0, 1.0 - abs(diameter - _NOMINAL_M) / self._half_window)
            found.append(Detection(x=float(x), y=float(y), footprint_m=diameter, score=score))
        found.sort(key=lambda item: item.score, reverse=True)
        return DetectorResult(tuple(found[:MAX_DETECTIONS]), "OK")


def _work_image(image: np.ndarray) -> tuple[np.ndarray, float, float]:
    height, width = image.shape[:2]
    long_side = max(width, height)
    if long_side <= WORK_LONG_SIDE:
        return image, 1.0, 1.0
    factor = WORK_LONG_SIDE / long_side
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    small = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    return small, size[0] / width, size[1] / height


def _track_mask(work_to_map: np.ndarray, bounds, shape) -> np.ndarray:
    height, width = shape[:2]
    mask = np.zeros((height, width), np.uint8)
    min_x, min_y, max_x, max_y = bounds
    corners = np.array([[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]], float)
    try:
        map_to_work = np.linalg.inv(work_to_map)
    except np.linalg.LinAlgError:
        return mask
    points = np.c_[corners, np.ones(4)] @ map_to_work.T
    w = points[:, 2]
    if not (np.all(w > 1e-12) or np.all(w < -1e-12)):
        mask[:] = 255  # a track corner is behind the camera: keep the whole frame
        return mask
    polygon = np.clip(points[:, :2] / w[:, None], -1e6, 1e6)
    cv2.fillPoly(mask, [np.round(polygon).astype(np.int32)], 255)
    return mask


def _pixel_area_m2(work_to_map: np.ndarray, u: float, v: float) -> float:
    p = geometry.apply(work_to_map, [[u, v], [u + 1.0, v], [u, v + 1.0]])
    ax, ay = p[1] - p[0]
    bx, by = p[2] - p[0]
    return abs(float(ax * by - ay * bx))
```

- [ ] **Step 4: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test/test_overhead_track_blob.py -q -p no:cacheprovider`
Expected: PASS — `9 passed`. 위치 시험이 0.006 m를 넘게 빗나가면 그 숫자를 고치지 말고 원인(픽셀 중심 규약, 열림 연산)을 먼저 찾는다(superpowers:systematic-debugging).

- [ ] **Step 5: 커밋**

```bash
git add src/site/vision/rosy_vision/track/background_blob.py src/site/vision/test/test_overhead_track_blob.py
git diff --cached --name-only
git commit -m "feat(vision): D-NNN background_blob tracking backend with frozen background" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: Vision 보정 고르기, Fleet 클라이언트, 추적 단계, `--track`

**Files:**
- Create: `src/site/vision/rosy_vision/track/calibration.py`, `src/site/vision/rosy_vision/track/fleet_client.py`, `src/site/vision/rosy_vision/track/worker.py`
- Modify: `src/site/vision/rosy_vision/project.py:56-74`, `src/site/vision/rosy_vision/worker.py:17-62`, `src/site/vision/rosy_vision/cli.py:33`, `:291-336`, `:371-373`(뒤), `test/architecture/test_app_roles.py:29-35`, `:81-84`
- Test: `src/site/vision/test/test_overhead_track_calibration.py`, `src/site/vision/test/test_overhead_track_client.py`, `src/site/vision/test/test_overhead_track_worker.py`, `src/site/vision/test/test_vision_project.py`(끝), `src/site/vision/test/test_vision_cli.py`(끝)

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/site/vision/test/test_overhead_track_calibration.py`:

```python
"""D-NNN 2: corner markers win; an approved record is used only for its source, map, lens and aspect."""

import json
from pathlib import Path

import pytest

from rosy_vision.project import CameraMap
from rosy_vision.track.calibration import choose, from_record, same_lens

FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
RECORD = FIXTURE["config_example"]["calibration"]
LENS = {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9}
CAMERA = CameraMap(
    source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="cal-v3",
    processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
    corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)), robot_markers={"rosy_01": 7},
)


def _quad(cx, cy, half=2):
    return ((cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half))


MARKERS = {30: _quad(100, 100), 31: _quad(500, 100), 32: _quad(500, 300), 33: _quad(100, 300)}


def _from(record=RECORD, **changes):
    args = dict(source_id="ceiling_north", map_id="map_v2_fleet", frame_size=(640, 360), lens=None)
    args.update(changes)
    return from_record(record, **args)


def test_record_maps_frames_of_its_own_size():
    calibration = _from()
    assert calibration.revision == "paint-3f9a1c2b7d40"
    assert calibration.image_to_map == pytest.approx((0.01, 0.0, 0.0, 0.0, -0.01, 3.6, 0.0, 0.0, 1.0))
    assert calibration.track_bounds_m == (0.0, 0.0, 6.4, 3.6)
    assert calibration.image_size == (640, 360) and calibration.hfov_deg is None


def test_same_aspect_other_resolution_is_scaled():
    calibration = _from(frame_size=(1280, 720))
    assert calibration.image_to_map[0] == pytest.approx(0.005)
    assert calibration.image_to_map[4] == pytest.approx(-0.005)
    assert calibration.image_to_map[5] == pytest.approx(3.6)


@pytest.mark.parametrize("changes", [
    {"source_id": "ceiling_south"},
    {"map_id": "other_map"},
    {"frame_size": (640, 480)},
    {"lens": LENS},
])
def test_record_is_unusable_for_other_source_map_aspect_or_lens(changes):
    assert _from(**changes) is None


def test_lens_must_match_and_brings_its_fov():
    calibration = _from({**RECORD, "lens": LENS}, lens=dict(LENS))
    assert calibration.hfov_deg == pytest.approx(66.9)
    assert _from({**RECORD, "lens": LENS}, lens=None) is None


def test_lens_match_tolerates_header_rounding():
    printed = {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9123}
    assert same_lens({**printed, "hfov_deg": 66.912345}, printed)
    assert not same_lens({**printed, "kind": "wide"}, printed)
    assert same_lens(None, None) and not same_lens(None, printed)


@pytest.mark.parametrize("record", [
    {**RECORD, "map_to_image": [0.0] * 9},
    {key: value for key, value in RECORD.items() if key != "image"},
    {**RECORD, "track_bounds_m": {"min_x": 1.0, "min_y": 0.0, "max_x": 1.0, "max_y": 3.6}},
    None,
])
def test_malformed_record_is_unusable(record):
    assert _from(record) is None


def test_corner_markers_win_over_the_record():
    marker = choose(CAMERA, MARKERS, RECORD, frame_size=(640, 360), lens=None)
    assert marker.revision == "cal-v3" and marker.track_bounds_m == (0.0, 0.0, 4.0, 2.0)
    assert choose(CAMERA, {}, RECORD, frame_size=(640, 360), lens=None).revision == "paint-3f9a1c2b7d40"
    assert choose(CAMERA, {30: MARKERS[30]}, None, frame_size=(640, 360), lens=None) is None
```

`src/site/vision/test/test_overhead_track_client.py`:

```python
"""D-NNN 4: Vision writes detections and reads its own config with the source token only."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from rosy_vision.track.fleet_client import TrackClient, TrackPublishError

FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}
CONFIG = FIXTURE["config_example"]


def _run(handler, call):
    async def run():
        async with TrackClient("http://127.0.0.1:8090", "source-secret",
                               transport=httpx.MockTransport(handler)) as client:
            return await call(client)
    return asyncio.run(run())


def test_publish_posts_the_payload_with_the_source_token_header_only():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"accepted": True, "source_id": "ceiling_north", "seq": 41,
                                         "status": "OK"})

    payload = OverheadDetectionsPayload.model_validate(CASES["ok_two_detections"]["payload"])
    assert _run(handler, lambda client: client.publish(payload))["accepted"] is True
    request = observed[0]
    assert (request.method, request.url.path, request.url.query) == ("POST", "/api/fleet/detections", b"")
    assert request.headers["authorization"] == "Bearer source-secret"
    assert json.loads(request.content) == CASES["ok_two_detections"]["payload"]
    assert b"source-secret" not in request.content


def test_rejection_carries_the_fleet_code():
    def handler(_request):
        return httpx.Response(409, json={"detail": {"code": "CALIBRATION_MISMATCH", "message": "no"}})

    payload = OverheadDetectionsPayload.model_validate(CASES["ok_empty"]["payload"])
    with pytest.raises(TrackPublishError) as err:
        _run(handler, lambda client: client.publish(payload))
    assert (err.value.status_code, err.value.code) == (409, "CALIBRATION_MISMATCH")


def test_config_read_returns_the_source_config():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json=CONFIG)

    assert _run(handler, lambda client: client.fetch_config()) == CONFIG
    assert (observed[0].method, observed[0].url.path) == ("GET", "/api/fleet/detections/config")
    assert observed[0].headers["authorization"] == "Bearer source-secret"


@pytest.mark.parametrize("body", [[], {"source_id": "ceiling_north"},
                                  {**CONFIG, "relearn_seq": "1"}, {**CONFIG, "calibration": []}])
def test_malformed_config_is_an_error(body):
    with pytest.raises(TrackPublishError) as err:
        _run(lambda _request: httpx.Response(200, json=body), lambda client: client.fetch_config())
    assert err.value.code == "CONFIG_BAD_RESPONSE"


@pytest.mark.parametrize("url,token", [("ftp://fleet", "t"), ("https://u:p@fleet", "t"),
                                       ("https://fleet?x=1", "t"), ("https://fleet", "")])
def test_base_url_must_be_a_plain_origin_and_token_present(url, token):
    with pytest.raises(ValueError):
        TrackClient(url, token)
```

`src/site/vision/test/test_overhead_track_worker.py`:

```python
"""D-NNN 2-4: one tracking step per fresh frame, hooked after the ArUco step of VisionWorker."""

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from rosy_vision.project import CameraMap
from rosy_vision.track.fleet_client import TrackPublishError
from rosy_vision.track.model import Detection, DetectorResult
from rosy_vision.track.worker import TrackWorker, build_payload
from rosy_vision.worker import VisionWorker

FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}
CONFIG = FIXTURE["config_example"]
CAMERA = CameraMap(
    source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="cal-v3",
    processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
    corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)), robot_markers={"rosy_01": 7},
)
JPEG = cv2.imencode(".jpg", np.full((360, 640, 3), 120, np.uint8))[1].tobytes()
FOUND = DetectorResult((Detection(1.2345, 0.4321, 0.181, 0.83), Detection(2.5, 1.0, 0.2, 0.5)), "OK")


def _quad(cx, cy, half=2):
    return ((cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half))


MARKERS = {30: _quad(100, 100), 31: _quad(500, 100), 32: _quad(500, 300), 33: _quad(100, 300),
           7: _quad(300, 200, 10)}


class _Detector:
    processor_revision = "background-blob/1"

    def __init__(self, result=FOUND):
        self.result = result
        self.calls = []
        self.resets = 0

    def detect(self, frame, calib):
        self.calls.append((frame, calib))
        return self.result

    def reset(self):
        self.resets += 1


class _Client:
    def __init__(self, configs=(), error=None):
        self.configs = list(configs)
        self.published = []
        self.error = error

    async def publish(self, payload):
        self.published.append(payload)
        if self.error is not None:
            raise self.error
        return {"accepted": True}

    async def fetch_config(self):
        return self.configs.pop(0)


class _Ingest:
    def __init__(self, lens=None, frame=None):
        self.lens = lens
        self.frame = frame
        self.reports = []

    def source_lens(self, source_id):
        assert source_id == "ceiling_north"
        return self.lens

    def latest_frame(self, source_id):
        return self.frame

    def report_markers(self, source_id, corners_seen, robots_seen):
        self.reports.append((source_id, list(corners_seen), list(robots_seen)))


def _frame(seq=1, captured_at=99.75):
    return SimpleNamespace(header=SimpleNamespace(seq=seq), jpeg=JPEG, captured_at=captured_at,
                           received_at=100.0)


def _worker(*, configs=(), lens=None, detector=None, error=None):
    client = _Client(configs, error)
    worker = TrackWorker(camera=CAMERA, ingest=_Ingest(lens), client=client,
                         detector=detector or _Detector())
    return worker, client


def test_payload_builder_matches_the_shared_vector():
    payload = build_payload(source_id="ceiling_north", map_id="map_v2_fleet",
                            calibration_revision="paint-3f9a1c2b7d40",
                            processor_revision="background-blob/1", captured_at=1790000000.25,
                            seq=41, result=FOUND)
    assert payload.model_dump(mode="json") == CASES["ok_two_detections"]["payload"]


def test_without_calibration_the_payload_says_so_and_the_detector_is_not_run():
    detector = _Detector()
    worker, client = _worker(detector=detector)
    payload = asyncio.run(worker.process(_frame(), {}))
    assert (payload.status, payload.calibration_revision, payload.detections) == (
        "CALIBRATION_REQUIRED", None, ())
    assert detector.calls == [] and client.published == [payload]


def test_the_approved_record_is_used_when_markers_are_missing():
    detector = _Detector()
    worker, client = _worker(configs=[CONFIG], detector=detector)
    asyncio.run(worker.refresh_config())
    payload = asyncio.run(worker.process(_frame(), {}))
    assert payload.calibration_revision == "paint-3f9a1c2b7d40"
    assert [(d.x, d.y) for d in payload.detections] == [(1.2345, 0.4321), (2.5, 1.0)]
    assert detector.calls[0][1].image_size == (640, 360)
    assert detector.calls[0][0].captured_at == 99.75


def test_corner_markers_win_over_the_record():
    detector = _Detector()
    worker, _ = _worker(configs=[CONFIG], detector=detector)
    asyncio.run(worker.refresh_config())
    payload = asyncio.run(worker.process(_frame(), MARKERS))
    assert payload.calibration_revision == "cal-v3"
    assert detector.calls[0][1].track_bounds_m == (0.0, 0.0, 4.0, 2.0)


def test_a_new_lens_invalidates_the_record():
    worker, _ = _worker(configs=[CONFIG], lens={"kind": "wide", "focal_mm": 2.2, "hfov_deg": 120.0})
    asyncio.run(worker.refresh_config())
    assert asyncio.run(worker.process(_frame(), {})).status == "CALIBRATION_REQUIRED"


def test_relearn_counter_resets_the_detector_once_per_change():
    detector = _Detector()
    worker, _ = _worker(configs=[CONFIG, {**CONFIG, "relearn_seq": 1}, {**CONFIG, "relearn_seq": 1}],
                        detector=detector)
    for seq in (1, 2, 3):
        asyncio.run(worker.refresh_config())
        asyncio.run(worker.process(_frame(seq=seq, captured_at=99.75 + seq), {}))
    assert detector.resets == 1


def test_sequence_counts_up_per_published_frame():
    worker, client = _worker()
    for seq in (5, 1, 9):
        asyncio.run(worker.process(_frame(seq=seq), {}))
    assert [payload.seq for payload in client.published] == [0, 1, 2]


def test_a_rejected_publish_is_logged_not_raised(caplog):
    worker, _ = _worker(error=TrackPublishError(409, "CALIBRATION_MISMATCH", "no"))
    with caplog.at_level(logging.WARNING, logger="rosy_vision.track"):
        payload = asyncio.run(worker.process(_frame(), {}))
    assert payload.status == "CALIBRATION_REQUIRED"
    assert "CALIBRATION_MISMATCH" in caplog.text


def test_config_read_failure_keeps_the_last_good_config():
    worker, client = _worker(configs=[CONFIG])
    asyncio.run(worker.refresh_config())

    async def broken():
        raise TrackPublishError(503, "CONFIG_HTTP_ERROR", "down")

    client.fetch_config = broken
    asyncio.run(worker.refresh_config())
    assert worker.config == CONFIG


def test_vision_worker_hands_each_fresh_frame_and_its_markers_to_the_tracker():
    calls = []

    class _Tracker:
        async def process(self, frame, markers):
            calls.append((frame.header.seq, sorted(markers)))

    class _Publisher:
        async def publish(self, sighting):
            return {"seq": sighting.seq}

    worker = VisionWorker(source_id="ceiling_north", ingest=_Ingest(frame=_frame()), camera=CAMERA,
                          publisher=_Publisher(), detector=lambda _jpeg: MARKERS,
                          clock=lambda: 100.0, tracker=_Tracker())
    asyncio.run(worker.process_latest())
    asyncio.run(worker.process_latest())
    assert calls == [(1, [7, 30, 31, 32, 33])]
```

`src/site/vision/test/test_vision_project.py` 끝에 붙인다:

```python


def test_marker_homography_needs_all_four_corners():
    from rosy_vision.project import marker_homography

    camera = CameraMap(
        source_id="ceiling_north", map_id="site-v1", calibration_revision="cal-v3",
        processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
        corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)), robot_markers={"rosy_01": 7},
    )

    def quad(cx, cy):
        return ((cx - 2, cy - 2), (cx + 2, cy - 2), (cx + 2, cy + 2), (cx - 2, cy + 2))

    corners = {30: quad(100, 100), 31: quad(500, 100), 32: quad(500, 300), 33: quad(100, 300)}
    homography = marker_homography(camera, corners)
    assert homography.apply(500, 300) == pytest.approx((4.0, 2.0))
    assert marker_homography(camera, {30: corners[30]}) is None
```

(`test_vision_project.py`가 `pytest`를 import하지 않으면 파일 맨 위 `import math` 다음 줄에 `import pytest`를 더한다.)

`src/site/vision/test/test_vision_cli.py` 끝에 붙인다:

```python


def test_vision_track_flag_is_off_by_default():
    assert parse_args(["vision", "--config", "site-cameras.yaml"]).track is False
    assert parse_args(["vision", "--config", "site-cameras.yaml", "--track"]).track is True
```

`test/architecture/test_app_roles.py:29-35` — 바꾼다:

```python
# 2. Rosy Vision: no CORE API, no robot command, and to Fleet only the sighting write plus
#    the D-341 12 read of paired-camera credential digests.
VISION_FORBIDDEN = {
    "CORE API": re.compile(r"/api/v1/"),
    "cmd_vel": re.compile(r"cmd_vel"),
    "Fleet route other than sightings": re.compile(
        r"/api/fleet/(?!sightings\b)(?!pairing/v1/credentials\b)"),
}
```
→
```python
# 2. Rosy Vision: no CORE API, no robot command, and to Fleet only the sighting write, the
#    D-NNN detections write and own-config read, plus the D-341 12 read of paired-camera
#    credential digests.
VISION_FORBIDDEN = {
    "CORE API": re.compile(r"/api/v1/"),
    "cmd_vel": re.compile(r"cmd_vel"),
    "Fleet route other than sightings or detections": re.compile(
        r"/api/fleet/(?!sightings\b)(?!detections\b)(?!pairing/v1/credentials\b)"),
}
```

`test_app_roles.py:81-84` — 바꾼다:

```python
def test_vision_has_no_robot_command_and_writes_only_sightings_to_fleet():
    assert VISION.is_dir()
    assert _hits(VISION, (".py",), VISION_FORBIDDEN) == []
    assert "/api/fleet/sightings" in (VISION / "publish.py").read_text(encoding="utf-8")
```
→
```python
def test_vision_has_no_robot_command_and_writes_only_sightings_and_detections_to_fleet():
    assert VISION.is_dir()
    assert _hits(VISION, (".py",), VISION_FORBIDDEN) == []
    assert "/api/fleet/sightings" in (VISION / "publish.py").read_text(encoding="utf-8")
    assert "/api/fleet/detections" in (VISION / "track" / "fleet_client.py").read_text(encoding="utf-8")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test/test_overhead_track_calibration.py src/site/vision/test/test_overhead_track_client.py src/site/vision/test/test_overhead_track_worker.py src/site/vision/test/test_vision_project.py src/site/vision/test/test_vision_cli.py test/architecture/test_app_roles.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'rosy_vision.track.calibration'`(그리고 `fleet_client`, `worker`), `ImportError: cannot import name 'marker_homography'`, `AttributeError: 'Namespace' object has no attribute 'track'`, app_roles의 `FileNotFoundError ... track/fleet_client.py`.

- [ ] **Step 3: `project.py`에서 마커 homography를 분리한다**

`src/site/vision/rosy_vision/project.py:56-74` — `project_frame`의 머리를 바꾼다:

```python
def project_frame(
    camera: CameraMap,
    *,
    source_id: str,
    seq: int,
    captured_at: float,
    markers: Mapping[int, Sequence[Point]],
) -> tuple[SiteSightingPayload, ...]:
    """Return display-only poses when every calibration corner is in this frame."""

    if source_id != camera.source_id:
        return ()
    if any(marker_id not in markers for marker_id in camera.corner_marker_ids):
        return ()
    try:
        corner_centers = tuple(_center(markers[marker_id]) for marker_id in camera.corner_marker_ids)
        homography = fit(corner_centers, camera.corner_world_m)
    except (TypeError, ValueError, ZeroDivisionError):
        return ()
```
→
```python
def marker_homography(camera: CameraMap, markers: Mapping[int, Sequence[Point]]):
    """Image-to-map homography from the four corner markers, or None unless all four are in view."""

    if any(marker_id not in markers for marker_id in camera.corner_marker_ids):
        return None
    try:
        corner_centers = tuple(_center(markers[marker_id]) for marker_id in camera.corner_marker_ids)
        return fit(corner_centers, camera.corner_world_m)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def project_frame(
    camera: CameraMap,
    *,
    source_id: str,
    seq: int,
    captured_at: float,
    markers: Mapping[int, Sequence[Point]],
) -> tuple[SiteSightingPayload, ...]:
    """Return display-only poses when every calibration corner is in this frame."""

    if source_id != camera.source_id:
        return ()
    homography = marker_homography(camera, markers)
    if homography is None:
        return ()
```

- [ ] **Step 4: 보정 고르기를 쓴다**

`src/site/vision/rosy_vision/track/calibration.py`:

```python
"""Which calibration a frame uses for tracking (D-NNN 2).

Corner markers are a measurement and win when all four are in this frame; the approved
lane-paint fit from Fleet is an estimate and is used otherwise. A record for another
source or map, another lens (the lens was changed: the record is void), or another frame
aspect ratio is not used — the frame is then CALIBRATION_REQUIRED.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from rosy_vision.project import CameraMap, Point, marker_homography
from rosy_vision.track import geometry
from rosy_vision.track.model import Calibration

#: Same rule as the console map-fit view (map-fit.js SCALE_TOLERANCE): never stretch a fit.
ASPECT_TOLERANCE = 0.01
#: The console reads the lens back from X-Source-Lens, printed with 6 significant digits.
LENS_REL_TOL = 1e-4


def same_lens(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return (a["kind"] == b["kind"]
                and math.isclose(float(a["focal_mm"]), float(b["focal_mm"]), rel_tol=LENS_REL_TOL)
                and math.isclose(float(a["hfov_deg"]), float(b["hfov_deg"]), rel_tol=LENS_REL_TOL))
    except (KeyError, TypeError, ValueError):
        return False


def from_record(record, *, source_id: str, map_id: str, frame_size: Sequence[int],
                lens) -> Calibration | None:
    """An approved Fleet record as a Calibration for frames of ``frame_size``, or None."""
    if (not isinstance(record, Mapping) or record.get("source_id") != source_id
            or record.get("map_id") != map_id or not same_lens(record.get("lens"), lens)):
        return None
    try:
        map_to_image = geometry.as_matrix(record["map_to_image"])
        width, height = int(record["image"]["width"]), int(record["image"]["height"])
        bounds = record["track_bounds_m"]
        track = (float(bounds["min_x"]), float(bounds["min_y"]),
                 float(bounds["max_x"]), float(bounds["max_y"]))
        revision = str(record["calibration_revision"])
        image_to_map = np.linalg.inv(map_to_image)
    except (KeyError, TypeError, ValueError, np.linalg.LinAlgError):
        return None
    if width <= 0 or height <= 0:
        return None
    sx, sy = frame_size[0] / width, frame_size[1] / height
    if abs(sx / sy - 1.0) > ASPECT_TOLERANCE:
        return None
    image_to_map = geometry.normalized(geometry.scaled(image_to_map, sx, sy))
    try:
        return Calibration(source_id=source_id, map_id=map_id, revision=revision,
                           image_to_map=tuple(float(v) for v in image_to_map.reshape(-1)),
                           image_size=(int(frame_size[0]), int(frame_size[1])), track_bounds_m=track,
                           hfov_deg=None if lens is None else float(lens["hfov_deg"]))
    except (KeyError, TypeError, ValueError):
        return None


def from_markers(camera: CameraMap, markers: Mapping[int, Sequence[Point]], *,
                 frame_size: Sequence[int], lens) -> Calibration | None:
    homography = marker_homography(camera, markers)
    if homography is None:
        return None
    xs = [point[0] for point in camera.corner_world_m]
    ys = [point[1] for point in camera.corner_world_m]
    try:
        return Calibration(source_id=camera.source_id, map_id=camera.map_id,
                           revision=camera.calibration_revision,
                           image_to_map=tuple(float(v) for v in homography.h),
                           image_size=(int(frame_size[0]), int(frame_size[1])),
                           track_bounds_m=(min(xs), min(ys), max(xs), max(ys)),
                           hfov_deg=None if lens is None else float(lens["hfov_deg"]))
    except (KeyError, TypeError, ValueError):
        return None


def choose(camera: CameraMap, markers: Mapping[int, Sequence[Point]], record, *,
           frame_size: Sequence[int], lens) -> Calibration | None:
    """Corner markers (a measurement) win; else the approved paint fit (an estimate)."""
    marker = from_markers(camera, markers, frame_size=frame_size, lens=lens)
    if marker is not None:
        return marker
    if record is None:
        return None
    return from_record(record, source_id=camera.source_id, map_id=camera.map_id,
                       frame_size=frame_size, lens=lens)
```

- [ ] **Step 5: Fleet 클라이언트를 쓴다**

`src/site/vision/rosy_vision/track/fleet_client.py`:

```python
"""Source-token client for the Fleet detections endpoints (D-NNN 4).

Writes anonymous detections and reads this source's own tracking config (approved
calibration record and relearn counter). The token is sent only as a header. Vision
calls no other Fleet route besides sightings and pairing sync (test_app_roles.py).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from core_common.protocol.overhead_detections import OverheadDetectionsPayload

DETECTIONS_PATH = "/api/fleet/detections"
CONFIG_PATH = "/api/fleet/detections/config"


class TrackPublishError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class TrackClient:
    def __init__(self, base_url: str, source_token: str, *, transport=None,
                 timeout_s: float = 2.0) -> None:
        parts = urlsplit(base_url)
        if (parts.scheme not in {"http", "https"} or not parts.netloc or parts.query
                or parts.fragment or parts.username or parts.password):
            raise ValueError("Fleet base URL must be an absolute HTTP(S) origin without credentials")
        if not source_token:
            raise ValueError("detection source token is required")
        self._authorization = f"Bearer {source_token}"
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s,
                                         transport=transport, follow_redirects=False)

    async def __aenter__(self) -> "TrackClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def publish(self, payload: OverheadDetectionsPayload) -> dict[str, Any]:
        response = await self._client.post(DETECTIONS_PATH, json=payload.model_dump(mode="json"),
                                           headers={"Authorization": self._authorization})
        return _body(response, "DETECTION_HTTP_ERROR", "BAD_RESPONSE")

    async def fetch_config(self) -> dict[str, Any]:
        response = await self._client.get(CONFIG_PATH, headers={"Authorization": self._authorization})
        body = _body(response, "CONFIG_HTTP_ERROR", "CONFIG_BAD_RESPONSE")
        calibration = body.get("calibration")
        if (not isinstance(body.get("source_id"), str) or not isinstance(body.get("map_id"), str)
                or type(body.get("relearn_seq")) is not int
                or not (calibration is None or isinstance(calibration, dict))):
            raise TrackPublishError(response.status_code, "CONFIG_BAD_RESPONSE",
                                    "Fleet returned a malformed tracking config")
        return body


def _body(response: httpx.Response, error_code: str, bad_code: str) -> dict[str, Any]:
    if not response.is_success:
        try:
            detail = response.json().get("detail", {})
        except (ValueError, AttributeError):
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        raise TrackPublishError(response.status_code, str(detail.get("code", error_code)),
                                str(detail.get("message", "Fleet rejected the request")))
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise TrackPublishError(response.status_code, bad_code, "Fleet returned a non-object response")
    return body
```

- [ ] **Step 6: 추적 단계를 쓴다**

`src/site/vision/rosy_vision/track/worker.py`:

```python
"""Markerless tracking step per fresh frame (D-NNN 2-4). Display only, no robot command.

VisionWorker calls ``process`` with the frame and the ArUco markers it already found.
The corner markers win when all four are in view; otherwise the approved paint-fit
record from Fleet is used (calibration.py). Without either the payload says
CALIBRATION_REQUIRED and carries no detections. ``run_config_sync`` reads the record
and the relearn counter every CONFIG_REFRESH_S on the event loop; a failed read keeps
the last good config (Fleet still checks every revision, 409).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Mapping, Sequence

import cv2
import httpx
import numpy as np

from core_common.protocol.overhead_detections import OverheadDetection, OverheadDetectionsPayload
from rosy_vision.project import CameraMap, Point
from rosy_vision.track.background_blob import BackgroundBlobDetector
from rosy_vision.track.calibration import choose
from rosy_vision.track.fleet_client import TrackPublishError
from rosy_vision.track.model import DetectorResult, Frame, RobotDetector

logger = logging.getLogger("rosy_vision.track")

CONFIG_REFRESH_S = 2.0


def decode_jpeg(jpeg: bytes) -> np.ndarray | None:
    if not isinstance(jpeg, bytes) or not jpeg:
        return None
    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def build_payload(*, source_id: str, map_id: str, calibration_revision: str | None,
                  processor_revision: str, captured_at: float, seq: int,
                  result: DetectorResult) -> OverheadDetectionsPayload:
    detections = () if result.status != "OK" else tuple(
        OverheadDetection(x=round(d.x, 4), y=round(d.y, 4), footprint_m=round(d.footprint_m, 4),
                          score=round(d.score, 3))
        for d in result.detections)
    return OverheadDetectionsPayload(
        source_id=source_id, map_id=map_id, calibration_revision=calibration_revision,
        processor_revision=processor_revision, captured_at=captured_at, seq=seq,
        status=result.status, detections=detections)


class TrackWorker:
    def __init__(self, *, camera: CameraMap, ingest, client, detector: RobotDetector | None = None,
                 decode: Callable[[bytes], np.ndarray | None] = decode_jpeg) -> None:
        self.camera = camera
        self.ingest = ingest
        self.client = client
        self.detector = detector if detector is not None else BackgroundBlobDetector()
        self.decode = decode
        self._config: dict | None = None
        self._relearn_seen: int | None = None
        self._seq = 0

    @property
    def config(self) -> dict | None:
        return self._config

    async def refresh_config(self) -> None:
        try:
            self._config = await self.client.fetch_config()
        except (TrackPublishError, httpx.HTTPError) as exc:
            logger.warning("tracking config read failed source=%s error_type=%s",
                           self.camera.source_id, type(exc).__name__)

    async def run_config_sync(self, stop_event: asyncio.Event,
                              interval_s: float = CONFIG_REFRESH_S) -> None:
        while not stop_event.is_set():
            await self.refresh_config()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass

    async def process(self, frame, markers: Mapping[int, Sequence[Point]]
                      ) -> OverheadDetectionsPayload | None:
        config = self._config or {}
        relearn = config.get("relearn_seq")
        if type(relearn) is int:
            if self._relearn_seen is not None and relearn != self._relearn_seen:
                self.detector.reset()
            self._relearn_seen = relearn
        image = self.decode(frame.jpeg)
        if image is None:
            return None
        size = (int(image.shape[1]), int(image.shape[0]))
        lens = self.ingest.source_lens(self.camera.source_id)
        calibration = choose(self.camera, markers, config.get("calibration"), frame_size=size, lens=lens)
        if calibration is None:
            result = DetectorResult((), "CALIBRATION_REQUIRED")
        else:
            result = self.detector.detect(Frame(image, frame.captured_at), calibration)
        payload = build_payload(
            source_id=self.camera.source_id, map_id=self.camera.map_id,
            calibration_revision=None if calibration is None else calibration.revision,
            processor_revision=self.detector.processor_revision, captured_at=frame.captured_at,
            seq=self._seq, result=result)
        self._seq = (self._seq + 1) % 0x100000000
        try:
            await self.client.publish(payload)
        except TrackPublishError as exc:
            logger.warning("detections rejected source=%s status=%d code=%s",
                           self.camera.source_id, exc.status_code, exc.code)
        except httpx.HTTPError as exc:
            logger.warning("detections not delivered source=%s error_type=%s",
                           self.camera.source_id, type(exc).__name__)
        return payload
```

- [ ] **Step 7: VisionWorker와 CLI에 잇는다**

`src/site/vision/rosy_vision/worker.py:17-19` — 생성자 서명을 바꾼다:

```python
    def __init__(self, *, source_id: str, ingest, camera: CameraMap, publisher,
                 detector: Callable = detect_markers, clock: Callable[[], float] = time.time,
                 max_age_s: float = 0.75) -> None:
```
→
```python
    def __init__(self, *, source_id: str, ingest, camera: CameraMap, publisher,
                 detector: Callable = detect_markers, clock: Callable[[], float] = time.time,
                 max_age_s: float = 0.75, tracker=None) -> None:
```

같은 생성자 본문의 `self._last_frame_key: tuple[int, float, float] | None = None` 바로 뒤에 넣는다:

```python
        # D-NNN: optional markerless tracking step (rosy_vision.track.worker.TrackWorker).
        self.tracker = tracker
```

`worker.py:60-62` — 바꾼다:

```python
        for sighting in sightings:
            await self.publisher.publish(sighting)
        return sightings
```
→
```python
        for sighting in sightings:
            await self.publisher.publish(sighting)
        if self.tracker is not None:
            await self.tracker.process(frame, markers)
        return sightings
```

`src/site/vision/rosy_vision/cli.py:33` — `from rosy_vision.worker import VisionWorker` 앞에 넣는다:

```python
from rosy_vision.track.fleet_client import TrackClient
from rosy_vision.track.worker import TrackWorker
```

`cli.py:371-373`의 `vision.add_argument("--map-paint", ...)` 문 바로 뒤에 넣는다:

```python
    vision.add_argument("--track", action="store_true",
                        help="D-NNN markerless tracking: publish anonymous floor detections to Fleet "
                             "(needs an approved paint-fit calibration or all four corner markers)")
```

`cli.py:291-336`의 `_run_vision`을 통째로 바꾼다:

```python
async def _run_vision(args: argparse.Namespace) -> int:
    configs = load_vision_sources(args.config)
    ingest, sync_settings = _vision_ingest(args, configs)
    workers = []
    trackers = []
    async with AsyncExitStack() as stack:
        for config in configs:
            publisher = await stack.enter_async_context(
                SightingPublisher(config.fleet_base_url, config.sighting_token)
            )
            tracker = None
            if getattr(args, "track", False):
                client = await stack.enter_async_context(
                    TrackClient(config.fleet_base_url, config.sighting_token))
                tracker = TrackWorker(camera=config.camera, ingest=ingest, client=client)
                trackers.append(tracker)
            workers.append(VisionWorker(
                source_id=config.camera.source_id,
                ingest=ingest,
                camera=config.camera,
                publisher=publisher,
                tracker=tracker,
            ))
        ws_server = await ingest.start(args.host, args.port,
                                       ssl_context=_server_ssl_context(args.tls_cert, args.tls_key))
        print(f"vision pipeline listening on {args.host}:{args.port}{protocol.WS_PATH} "
              f"for {len(workers)} configured sources"
              f"{' with markerless tracking' if trackers else ''}", flush=True)
        sync = None
        if sync_settings is not None:
            loop = asyncio.get_running_loop()
            # Own thread (2026-10-01 starvation lesson); only enforcement hops onto the loop.
            sync = PairingSync(ingest.paired, **sync_settings,
                               on_cycle=lambda: loop.call_soon_threadsafe(
                                   ingest.enforce_paired_credentials))
            sync.start()
        stop_tracking = asyncio.Event()
        config_tasks = [asyncio.create_task(tracker.run_config_sync(stop_tracking))
                        for tracker in trackers]
        try:
            while True:
                for worker in workers:
                    try:
                        await worker.process_latest()
                    except SightingPublishError as exc:
                        logger.warning("sighting rejected status=%d code=%s",
                                       exc.status_code, exc.code)
                    except Exception as exc:
                        # Do not log URLs, request bodies, headers, or arbitrary exception text.
                        logger.error("vision frame failed error_type=%s", type(exc).__name__)
                await asyncio.sleep(0.03)
        finally:
            stop_tracking.set()
            await asyncio.gather(*config_tasks, return_exceptions=True)
            if sync is not None:
                sync.stop()
            ws_server.close()
            await ws_server.wait_closed()
            ingest.close_map_worker()
    return 0
```

- [ ] **Step 8: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test -q -p no:cacheprovider`
Expected: PASS — main의 Vision 시험 수에 새 시험 60개(보정 13, 클라이언트 11, 작업 10, 모델 7, 기하 8, 검출기 9, project 1, cli 1)를 더한 수가 모두 통과(2026-10-01 main 사본에서 실측: 새 시험 전부 첫 실행에 통과).

Run: `C:/Python314/python.exe -m pytest test/architecture/test_app_roles.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 9: 커밋**

```bash
git add src/site/vision/rosy_vision/track/calibration.py src/site/vision/rosy_vision/track/fleet_client.py src/site/vision/rosy_vision/track/worker.py src/site/vision/rosy_vision/project.py src/site/vision/rosy_vision/worker.py src/site/vision/rosy_vision/cli.py src/site/vision/test/test_overhead_track_calibration.py src/site/vision/test/test_overhead_track_client.py src/site/vision/test/test_overhead_track_worker.py src/site/vision/test/test_vision_project.py src/site/vision/test/test_vision_cli.py test/architecture/test_app_roles.py
git diff --cached --name-only
git commit -m "feat(vision): D-NNN markerless tracking step, Fleet detections client and vision --track" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: 콘솔 — 추적 보정 적용, 추적 레이어, 상태줄, 배경 다시 학습

**Files:**
- Create: `src/site/fleet/fleet/server/web/tracking-layer.js`, `src/site/fleet/fleet/server/web/tracking-view.js`
- Modify: `web/map-fit.js`(끝), `web/map-fit-view.js`, `web/vision-view.js`, `web/field-layers.js`, `web/map-view.js`, `web/console.js`, `web/index.html`, `web/styles.css`(끝), `src/site/fleet/fleet/server/static_routes.py:35`(뒤)
- Test: `src/site/fleet/test/web/tracking-layer.test.mjs`, `src/site/fleet/test/web/map-fit.test.mjs`(끝), `src/site/fleet/test/web/field-layers.test.mjs`(끝), `src/site/fleet/test/test_overhead_tracking_console.py`

(이 Task의 `web/`는 `src/site/fleet/fleet/server/web/`이다.)

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/site/fleet/test/web/tracking-layer.test.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";

import {
  classifyTracking, trackingStatusLine, offsetLabel, OFFSET_WARN_M, TRACKING_STATUS_TEXT,
} from "../../fleet/server/web/tracking-layer.js";

const source = (changes = {}) => ({
  source_id: "ceiling_north", map_id: "map_v2_fleet", status: "OK",
  calibration_revision: "paint-3f9a1c2b7d40", age_ms: 120, fps: 3, last_error: null, relearn_seq: 0,
  ...changes,
});

const body = (changes = {}) => ({
  ts: 10, lease_s: 1, gate_m: 0.3, use: "display-only",
  sources: [source()],
  robots: [
    { robot_id: "rosy_02", status: "MATCHED", source_id: "ceiling_north", offset_m: 0.2,
      camera: { x: 1.2, y: 0.4, footprint_m: 0.18, score: 0.8 }, pose: { x: 1.0, y: 0.4 },
      pose_frame_verified: true },
    { robot_id: "rosy_01", status: "MATCHED", source_id: "ceiling_north", offset_m: 0.05,
      camera: { x: 2, y: 1, footprint_m: 0.18, score: 0.9 }, pose: { x: 2.05, y: 1 },
      pose_frame_verified: false },
    { robot_id: "rosy_03", status: "NO_DETECTION", source_id: "ceiling_north", offset_m: null,
      camera: null, pose: { x: 3, y: 1 }, pose_frame_verified: true },
  ],
  unknown: [{ source_id: "ceiling_north", x: 0.5, y: 0.5, footprint_m: 0.2, score: 0.4 }, { x: "bad" }],
  ...changes,
});

test("only matched robots with finite numbers are drawn; unknowns become grey points", () => {
  const out = classifyTracking(body());
  assert.deepEqual(out.robots.map((r) => [r.robotId, r.warn, r.verified]),
    [["rosy_01", false, false], ["rosy_02", true, true]]);
  assert.deepEqual(out.robots[1].camera, { x: 1.2, y: 0.4 });
  assert.deepEqual(out.robots[1].pose, { x: 1.0, y: 0.4 });
  assert.deepEqual(out.unknown, [{ x: 0.5, y: 0.5 }]);
  assert.deepEqual(classifyTracking(null), { robots: [], unknown: [] });
  assert.equal(OFFSET_WARN_M, 0.15);
});

test("an offset exactly at the threshold is not orange", () => {
  const out = classifyTracking(body({ robots: [{ ...body().robots[0], offset_m: 0.15 }] }));
  assert.equal(out.robots[0].warn, false);
});

test("the status line names each source state, fps and unverified frames", () => {
  assert.deepEqual(trackingStatusLine(body()), {
    state: "ok", text: "관제 카메라 추적: ceiling_north 추적 중 · 3.0 fps · 위치 상태 미보고 1대",
  });
  assert.deepEqual(trackingStatusLine(body({ sources: [source({ status: "LEARNING" })], robots: [] })), {
    state: "warn", text: "관제 카메라 추적: ceiling_north 배경 학습 중",
  });
  assert.equal(trackingStatusLine(body({ sources: [source({ last_error: "CALIBRATION_MISMATCH" })],
    robots: [] })).text, "관제 카메라 추적: ceiling_north 보정 불일치");
  assert.equal(trackingStatusLine(body({ sources: [source({ status: "BLIND" })], robots: [] })).text,
    "관제 카메라 추적: ceiling_north 알 수 없음(BLIND)");
  assert.deepEqual(trackingStatusLine({ sources: [] }), { state: "none", text: "관제 카메라 추적 소스 없음" });
  for (const key of ["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED", "STALE", "NONE"]) {
    assert.equal(typeof TRACKING_STATUS_TEXT[key], "string");
  }
});

test("the offset label is in whole centimetres", () => {
  assert.equal(offsetLabel({ robotId: "rosy_02", offsetM: 0.204 }), "rosy_02 · 차이 20 cm");
});
```

`src/site/fleet/test/web/map-fit.test.mjs` 끝에 붙인다(`calibrationRequest`를 파일 맨 위 `map-fit.js` import 목록에 더한다):

```js

test("an applied fit becomes a Fleet calibration request; previous or other-source fits never do", () => {
  const body = {
    accepted: true, image: { width: 1280, height: 720 }, frame_seq: 12,
    proposal: { image_to_map: [[0.005, 0, 0], [0, -0.005, 3.6], [0, 0, 1]], score: 0.9, precision: 0.95,
      coverage: 0.8, cut_directions: [] },
  };
  const pending = { source: "ceiling_north", norm: normalizeMapProposal(body, {}) };
  const laneSet = { mapId: "map_v2_fleet", bounds: { min_x: 0, min_y: 0, max_x: 6.4, max_y: 3.6 } };
  const lens = { kind: "standard", focal_mm: 5.4, hfov_deg: 66.9 };
  const request = calibrationRequest(pending, "ceiling_north", laneSet, lens);
  assert.equal(request.source_id, "ceiling_north");
  assert.equal(request.map_id, "map_v2_fleet");
  assert.equal(request.map_to_image.length, 9);
  close(request.map_to_image[0], 200);
  close(request.map_to_image[4], -200);
  close(request.map_to_image[5], 720);
  assert.deepEqual(request.image, { width: 1280, height: 720 });
  assert.deepEqual(request.track_bounds_m, { min_x: 0, min_y: 0, max_x: 6.4, max_y: 3.6 });
  assert.equal(request.fit_score, 0.855);
  assert.deepEqual(request.lens, lens);
  assert.equal(request.frame_seq, 12);
  const previous = { ...pending, norm: { ...pending.norm, previous: true } };
  assert.equal(calibrationRequest(previous, "ceiling_north", laneSet, lens), null);
  assert.equal(calibrationRequest(pending, "ceiling_south", laneSet, lens), null);
  assert.equal(calibrationRequest(pending, "ceiling_north", null, lens), null);
  const noMap = calibrationRequest(pending, "ceiling_north", { mapId: null, bounds: laneSet.bounds }, null);
  assert.equal("map_id" in noMap, false);
  assert.equal(noMap.lens, null);
});
```

`src/site/fleet/test/web/field-layers.test.mjs` 끝에 붙인다:

```js

test("the overhead tracking layer is on by default and can be switched off", () => {
  assert.equal(LAYER_DEFAULTS.tracking, true);
  assert.equal(parseLayers(JSON.stringify({ tracking: false })).tracking, false);
});
```

`src/site/fleet/test/test_overhead_tracking_console.py`:

```python
"""D-NNN 7: the console ships the overhead tracking layer, its status line and the apply button."""

from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.console import FleetConsole


def test_console_serves_the_tracking_layer_wired_into_the_map_and_shell():
    client = TestClient(create_app(FleetConsole([], [])))
    page = client.get("/console").text
    layer = client.get("/console/assets/tracking-layer.js")
    view = client.get("/console/assets/tracking-view.js")
    shell = client.get("/console/assets/console.js").text
    map_view = client.get("/console/assets/map-view.js").text
    fit_view = client.get("/console/assets/map-fit-view.js").text
    vision_view = client.get("/console/assets/vision-view.js").text

    assert layer.status_code == 200 and "classifyTracking" in layer.text
    assert view.status_code == 200
    assert '"/api/fleet/tracking"' in view.text and '"/api/fleet/tracking/relearn"' in view.text
    assert 'import { createTrackingView } from "./tracking-view.js";' in shell
    assert "trackingView.refresh()" in shell
    assert 'import { offsetLabel } from "./tracking-layer.js";' in map_view
    assert 'layerOn("tracking")' in map_view
    assert '"/api/fleet/calibrations"' in fit_view and "calibrationRequest(" in fit_view
    assert "currentLensInfo: () => currentLensInfo" in vision_view
    for element_id in ("tracking-state", "tracking-relearn", "legend-tracking", "map-fit-apply"):
        assert f'id="{element_id}"' in page
    assert 'data-layer="tracking"' in page
    assert "<script>" not in page and 'style="' not in page
```

- [ ] **Step 2: 실패를 확인한다**

Run: `node --test src/site/fleet/test/web/tracking-layer.test.mjs src/site/fleet/test/web/map-fit.test.mjs src/site/fleet/test/web/field-layers.test.mjs`
Expected: FAIL — `Cannot find module .../tracking-layer.js`, `calibrationRequest` export 없음(`SyntaxError: The requested module ... does not provide an export named 'calibrationRequest'`), `LAYER_DEFAULTS.tracking`이 `undefined`.

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_console.py -q -p no:cacheprovider`
Expected: FAIL — `assert 404 == 200`(`tracking-layer.js`가 허용 목록에 없음).

- [ ] **Step 3: 순수 층과 뷰를 쓴다**

`web/tracking-layer.js`:

```js
// D-NNN 관제 카메라 추적 층. DOM 없는 순수 계산 — map-view.js 가 그리고 tracking-view.js 가 상태줄을 쓴다.
// 표시·교차확인 전용이다. 목표·교통정리·미션 입력이 아니다.

export const OFFSET_WARN_M = 0.15;
export const TRACKING_STATUS_TEXT = Object.freeze({
  OK: "추적 중",
  LEARNING: "배경 학습 중",
  CALIBRATION_REQUIRED: "보정 필요",
  SCENE_CHANGED: "장면 변화 — 배경 다시 학습",
  STALE: "오래됨",
  NONE: "수신 없음",
});
const ERROR_TEXT = { CALIBRATION_MISMATCH: "보정 불일치", MAP_MISMATCH: "지도 불일치" };

const finite = (value) => typeof value === "number" && Number.isFinite(value);

// GET /api/fleet/tracking → 그릴 것만. MATCHED 만 고리·선을 그리고, 형식이 틀린 행은 버린다.
// 응답이 없으면 빈 층이다 — 지난 값을 남기지 않는다.
export function classifyTracking(body) {
  const robots = [];
  for (const row of body?.robots || []) {
    if (!row || typeof row.robot_id !== "string" || row.status !== "MATCHED") continue;
    const camera = row.camera;
    const pose = row.pose;
    if (!camera || !pose || ![camera.x, camera.y, pose.x, pose.y, row.offset_m].every(finite)) continue;
    robots.push({
      robotId: row.robot_id,
      camera: { x: camera.x, y: camera.y },
      pose: { x: pose.x, y: pose.y },
      offsetM: row.offset_m,
      warn: row.offset_m > OFFSET_WARN_M,
      verified: row.pose_frame_verified === true,
    });
  }
  const unknown = [];
  for (const item of body?.unknown || []) {
    if (item && finite(item.x) && finite(item.y)) unknown.push({ x: item.x, y: item.y });
  }
  robots.sort((a, b) => a.robotId.localeCompare(b.robotId));
  return { robots, unknown };
}

// 상태줄: source 마다 한 조각. Fleet 409(보정·지도 불일치)가 검출기 상태보다 먼저다.
export function trackingStatusLine(body) {
  const sources = Array.isArray(body?.sources) ? body.sources : [];
  if (!sources.length) return { state: "none", text: "관제 카메라 추적 소스 없음" };
  let state = "ok";
  const parts = sources.map((source) => {
    const error = ERROR_TEXT[source.last_error];
    const label = error || TRACKING_STATUS_TEXT[source.status] || `알 수 없음(${source.status})`;
    if (error || source.status !== "OK") state = "warn";
    const fps = !error && source.status === "OK" && finite(source.fps) ? ` · ${source.fps.toFixed(1)} fps` : "";
    return `${source.source_id} ${label}${fps}`;
  });
  const unverified = (body.robots || [])
    .filter((row) => row?.status === "MATCHED" && row.pose_frame_verified !== true).length;
  const note = unverified ? ` · 위치 상태 미보고 ${unverified}대` : "";
  return { state, text: `관제 카메라 추적: ${parts.join(" / ")}${note}` };
}

export function offsetLabel(row) {
  return `${row.robotId} · 차이 ${Math.round(row.offsetM * 100)} cm`;
}
```

`web/tracking-view.js`:

```js
// D-NNN 관제 카메라 추적 상태줄·"배경 다시 학습". 그림은 map-view.js 가 view.cameraTracking 으로 그린다.
// 표시 전용 — 목표·교통정리·미션에 넘기지 않는다.

import { classifyTracking, trackingStatusLine } from "./tracking-layer.js";

export function createTrackingView({ el, view, call, auth, onChanged = () => {} }) {
  const line = el("tracking-state");
  const relearn = el("tracking-relearn");
  const legend = el("legend-tracking");
  let inFlight = false;
  let unavailable = false; // 404 — 이 Fleet 에 추적 경로가 없다(카메라 source 미설정)
  let sources = [];

  async function refresh() {
    if (auth.locked || inFlight || unavailable) return;
    inFlight = true;
    let body = null;
    try {
      body = await call("/api/fleet/tracking");
    } catch (error) {
      if (error.status === 404) unavailable = true;
    } finally {
      inFlight = false;
    }
    view.cameraTracking = classifyTracking(body);
    sources = (body?.sources || []).map((source) => source.source_id);
    legend.hidden = !(view.cameraTracking.robots.length || view.cameraTracking.unknown.length);
    if (unavailable) {
      line.hidden = true;
      relearn.hidden = true;
    } else {
      const status = body ? trackingStatusLine(body)
        : { state: "warn", text: "관제 카메라 추적 상태를 읽지 못했습니다" };
      line.hidden = false;
      line.dataset.state = status.state;
      line.textContent = status.text;
      relearn.hidden = !sources.length;
    }
    onChanged();
  }

  relearn.addEventListener("click", async () => {
    if (!sources.length) return;
    try {
      for (const sourceId of sources) {
        await call("/api/fleet/tracking/relearn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: sourceId }),
        });
      }
      line.dataset.state = "warn";
      line.textContent = "배경을 다시 학습합니다 — 트랙을 비워 두세요(약 10초).";
    } catch (error) {
      line.dataset.state = "warn";
      line.textContent = `배경 다시 학습 실패: ${error.message || error}`;
    }
  });

  function reset() {
    unavailable = false;
  }

  return { refresh, reset };
}
```

- [ ] **Step 4: 기존 웹 파일을 고친다**

`web/map-fit.js` 끝에 붙인다:

```js

// D-NNN 1항: 통과한 최신 제안 → Fleet 추적 보정 기록 요청 본문. 행렬은 원본 프레임 픽셀 기준이다.
// 관제 카메라 추적 표시에만 쓰인다 — sighting·CameraMap·주행에 쓰지 않는다.
export function calibrationRequest(pending, source, laneSet, lens) {
  if (!canAccept(pending, source) || !laneSet?.bounds) return null;
  const { fit, image, seq } = pending.norm;
  if (fit.score == null || fit.precision == null) return null;
  const b = laneSet.bounds;
  const lensBody = lens && typeof lens.kind === "string" && finite(lens.focal_mm) && finite(lens.hfov_deg)
    ? { kind: lens.kind, focal_mm: lens.focal_mm, hfov_deg: lens.hfov_deg } : null;
  return {
    source_id: source,
    ...(laneSet.mapId ? { map_id: laneSet.mapId } : {}),
    map_to_image: fit.mapToImage.map((v) => Number(v.toPrecision(10))),
    image: { width: image.width, height: image.height },
    track_bounds_m: { min_x: b.min_x, min_y: b.min_y, max_x: b.max_x, max_y: b.max_y },
    fit_score: Math.round(fit.score * fit.precision * 1000) / 1000,
    lens: lensBody,
    frame_seq: Number.isInteger(seq) ? seq : null,
  };
}
```

`web/map-fit-view.js`:
1. 맨 위 `from "./map-fit.js";` import 목록의 `retryDelay, MAP_FIT_MAX_TRIES, canAccept, fitUsable, STALE_FIT_TEXT,` 줄을 `retryDelay, MAP_FIT_MAX_TRIES, canAccept, fitUsable, STALE_FIT_TEXT, calibrationRequest,`로 바꾼다.
2. `  const clearButton = el("map-fit-clear");` 다음 줄에 넣는다:
```js
  const applyButton = el("map-fit-apply");
```
3. `render()` 안 `    acceptButton.hidden = !canAccept(pending, source) || !fit || fit.kind !== "proposal";` 다음 줄에 넣는다:
```js
    applyButton.hidden = acceptButton.hidden;
```
4. `  dismissButton.addEventListener("click", () => {` 바로 앞에 넣는다:
```js
  // D-NNN 1항: 같은 최신 제안을 Fleet 추적 보정 기록으로 승인한다(운용자). 관제 카메라 추적 표시에만 쓰인다.
  applyButton.addEventListener("click", async () => {
    const source = visionView.currentSource();
    const laneSet = lanes ? pickLanes(lanes, source) : null;
    const body = calibrationRequest(pending, source, laneSet, visionView.currentLensInfo());
    if (!body) return;
    try {
      const record = await call("/api/fleet/calibrations", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      showSummary({ tone: "good", guidance: null, headline: `추적 보정 ${record.calibration_revision} 적용 — `
        + "관제 카메라 추적 표시에만 씁니다(관측·주행 아님). 렌즈를 바꾸면 다시 맞추세요." });
    } catch (error) {
      showSummary({ tone: "warn", guidance: null, headline: `추적 보정 적용 실패: ${error.message || error}` });
    }
  });

```

`web/vision-view.js`:
1. `  let currentLens = null;` 다음 줄에 넣는다:
```js
  // D-NNN: 추적 보정 기록에 싣는 렌즈 전체(kind·focal_mm·hfov_deg). 옛 앱이면 null.
  let currentLensInfo = null;
```
2. `      const lens = parseLensHeader(response.headers.get("X-Source-Lens"));` 다음 줄에 넣는다:
```js
      if (response.ok) currentLensInfo = lens;
```
3. `reset()` 안의 `    currentLens = null;`과 `select.addEventListener("change", ...)` 안의 `    currentLens = null;` 각각 다음 줄에 넣는다:
```js
    currentLensInfo = null;
```
4. 반환 객체의 `    currentSource: () => select.value,` 다음 줄에 넣는다:
```js
    currentLensInfo: () => currentLensInfo,
```

`web/field-layers.js` — 바꾼다:

```js
// lanes·maptop: D-375 지도 맞춤의 카메라 위 차선 겹침과 지도 평면 뷰(map-fit-view.js).
export const LAYER_KEYS = Object.freeze(["raw", "rectified", "site", "grid", "sightings", "poses", "lanes", "maptop"]);
export const LAYER_DEFAULTS = Object.freeze({
  raw: true, rectified: true, site: true, grid: true, sightings: true, poses: true, lanes: true, maptop: true,
});
```
→
```js
// lanes·maptop: D-375 지도 맞춤의 카메라 위 차선 겹침과 지도 평면 뷰(map-fit-view.js).
// tracking: D-NNN 관제 카메라 추적(map-view.js).
export const LAYER_KEYS = Object.freeze(["raw", "rectified", "site", "grid", "sightings", "poses", "lanes", "maptop", "tracking"]);
export const LAYER_DEFAULTS = Object.freeze({
  raw: true, rectified: true, site: true, grid: true, sightings: true, poses: true, lanes: true, maptop: true,
  tracking: true,
});
```

`web/map-view.js`:
1. `} from "./site-layer.js";` 다음 줄에 넣는다:
```js
import { offsetLabel } from "./tracking-layer.js";
```
2. `  function sitePolygons() {` 바로 앞에 넣는다:
```js
  // D-NNN 관제 카메라 추적: 카메라 위치 고리 + 자가보고 위치까지 선 + 차이 칩. 0.15 m 초과는 주황,
  // 프레임 미확인(D-395 이전 로봇)은 점선. 이름 모를 검출은 회색 점. 표시 전용 — 목표·교통정리에 쓰지 않는다.
  function drawCameraTracking(ctx, toPoint, size, lineWidth) {
    const tracking = view.cameraTracking;
    if (!layerOn("tracking") || !tracking) return;
    ctx.save();
    ctx.lineWidth = lineWidth;
    for (const row of tracking.robots) {
      const cam = toPoint(row.camera.x, row.camera.y);
      const pose = toPoint(row.pose.x, row.pose.y);
      ctx.strokeStyle = css(row.warn ? "--status-warn" : "--series-primary");
      ctx.setLineDash(row.verified ? [] : [lineWidth * 2, lineWidth * 2]);
      ctx.beginPath();
      ctx.moveTo(cam.x, cam.y);
      ctx.lineTo(pose.x, pose.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(cam.x, cam.y, size * 0.9, 0, Math.PI * 2);
      ctx.stroke();
      drawChip(ctx, null, cam.x, cam.y - size * 1.8, offsetLabel(row), row.warn ? "warn" : undefined);
    }
    ctx.fillStyle = css("--ink-quiet");
    for (const item of tracking.unknown) {
      const p = toPoint(item.x, item.y);
      ctx.beginPath();
      ctx.arc(p.x, p.y, size * 0.35, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

```
3. `drawSiteOverlay` 안 — 바꾼다:
```js
    if (!layerOn("sightings")) return;
    for (const s of view.sightings) drawSighting(ctx, s, toCell, size, 0.5);
```
→
```js
    drawCameraTracking(ctx, toCell, size, 0.5);
    if (!layerOn("sightings")) return;
    for (const s of view.sightings) drawSighting(ctx, s, toCell, size, 0.5);
```
4. `drawSiteView` 끝 — 바꾼다:
```js
    if (!layerOn("sightings")) return;
    for (const s of view.sightings) drawSighting(ctx, s, toPx, Math.max(7, t.scale * 0.09), 1.5);
    flushChips(ctx);
```
→
```js
    drawCameraTracking(ctx, toPx, Math.max(7, t.scale * 0.09), 1.5);
    if (layerOn("sightings")) {
      for (const s of view.sightings) drawSighting(ctx, s, toPx, Math.max(7, t.scale * 0.09), 1.5);
    }
    flushChips(ctx);
```

`web/console.js`:
1. `import { createMapFitView } from "./map-fit-view.js";` 다음 줄에 넣는다:
```js
import { createTrackingView } from "./tracking-view.js";
```
2. `const view = {` 안 `  sightings: [],   // 카메라 관측 — 표시 전용, CORE pose 와 섞지 않는다` 다음 줄에 넣는다:
```js
  cameraTracking: { robots: [], unknown: [] }, // D-NNN 관제 카메라 추적 — 표시·교차확인 전용
```
3. `mapFit = createMapFitView({ el, view, call, visionView, onChanged: () => fieldView.render() });` 다음 줄에 넣는다:
```js
// D-NNN: 관제 카메라 추적 상태줄·배경 다시 학습. 그림은 map-view.js 가 view.cameraTracking 으로 그린다.
const trackingView = createTrackingView({ el, view, call, auth, onChanged: () => mapView.draw() });
```
4. `saveToken()` 안 `  mapFit.reset();` 다음 줄에 넣는다:
```js
  trackingView.reset();
```
5. `setInterval(() => mapView.refreshSightings(), STATE_MS);` 다음 줄에 넣는다:
```js
setInterval(() => trackingView.refresh(), STATE_MS);
```

`web/index.html`:
1. `        <span id="legend-sighting" hidden><i class="sw sighting"></i>카메라 관측</span>` 다음 줄에 넣는다:
```html
        <span id="legend-tracking" hidden><i class="sw tracking"></i>관제 카메라 추적</span>
```
2. `      <p class="hint" id="hint" aria-live="polite">` 줄 바로 앞에 넣는다:
```html
      <div class="tracking-bar">
        <p class="hint tracking-state" id="tracking-state" role="status" data-state="none" hidden></p>
        <ui-button kind="quiet" id="tracking-relearn" type="button" hidden>배경 다시 학습</ui-button>
      </div>
```
3. `          <ui-button kind="quiet" id="map-fit-accept" type="button" hidden>맞춤 수락</ui-button>` 다음 줄에 넣는다:
```html
          <ui-button kind="quiet" id="map-fit-apply" type="button" hidden>추적 보정 적용</ui-button>
```
4. `            <label class="ui-check"><input class="ui-field" type="checkbox" data-layer="maptop" checked> 지도 맞춤 평면</label>` 다음 줄에 넣는다:
```html
            <label class="ui-check"><input class="ui-field" type="checkbox" data-layer="tracking" checked> 관제 카메라 추적</label>
```

`web/styles.css` 끝에 붙인다:

```css

/* D-NNN 관제 카메라 추적 — 상태줄과 범례. 색은 토큰만(CSP style-src 'self'). */
.tracking-bar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.tracking-state[data-state="warn"] { color: var(--status-warn); }
.sw.tracking { background: transparent; border: 2px solid var(--series-primary); border-radius: 50%; }
```

`src/site/fleet/fleet/server/static_routes.py:35` — `    "site-layer.js": "application/javascript",` 다음 줄에 넣는다:

```python
    "tracking-layer.js": "application/javascript",
    "tracking-view.js": "application/javascript",
```

- [ ] **Step 5: 통과를 확인한다**

Run: `node --test src/site/fleet/test/web/*.test.mjs`
Expected: PASS — 모든 spec(새 `tracking-layer.test.mjs` 4개 포함) `fail 0`.

Run: `C:/Python314/python.exe -m pytest src/site/fleet/test/test_overhead_tracking_console.py src/site/fleet/test/test_site_lanes_api.py src/site/fleet/test/test_site_map_api.py src/site/fleet/test/test_console_palette.py src/site/fleet/test/test_server_console.py src/site/fleet/test/test_grammar_separation.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: 브라우저에서 확인한다(합성)**

`rosy-dashboard-drive` 스킬은 대시보드용이다. 여기서는 `webapp-testing` 스킬로 합성 Fleet을 띄워 본다: `test_overhead_tracking_api.py`의 `_client` 구성을 uvicorn으로 띄우는 일회용 스크립트를 `X:/DevTemp/overhead-tracking/console_smoke.py`에 두고, 검출 하나를 넣은 뒤 `/console`에서 (a) "관제 카메라 추적: ceiling_north 추적 중" 상태줄, (b) 지도 위 고리·선·"rosy_01 · 차이 5 cm" 칩, (c) 레이어 끄면 사라짐, (d) 1.1 s 뒤 고리가 사라지고 "오래됨"을 확인한다. 스크린숏은 `X:/DevTemp/overhead-tracking/`에만 둔다. 이 확인은 LOCAL 증거이고 커밋하지 않는다.

- [ ] **Step 7: 커밋**

```bash
git add src/site/fleet/fleet/server/web/tracking-layer.js src/site/fleet/fleet/server/web/tracking-view.js src/site/fleet/fleet/server/web/map-fit.js src/site/fleet/fleet/server/web/map-fit-view.js src/site/fleet/fleet/server/web/vision-view.js src/site/fleet/fleet/server/web/field-layers.js src/site/fleet/fleet/server/web/map-view.js src/site/fleet/fleet/server/web/console.js src/site/fleet/fleet/server/web/index.html src/site/fleet/fleet/server/web/styles.css src/site/fleet/fleet/server/static_routes.py src/site/fleet/test/web/tracking-layer.test.mjs src/site/fleet/test/web/map-fit.test.mjs src/site/fleet/test/web/field-layers.test.mjs src/site/fleet/test/test_overhead_tracking_console.py
git diff --cached --name-only
git commit -m "feat(console): D-NNN overhead tracking layer, status line, relearn and calibration apply" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: 재생 지표(LOCAL)와 실물 확인 절차(DEVICE)

**Files:**
- Create: `src/site/vision/rosy_vision/track/replay.py`
- Test: `src/site/vision/test/test_overhead_track_replay.py`
- 커밋하지 않는 것: `X:/DevTemp/overhead-replay/` 스크립트, 실물 프레임·라벨(`Rosy OS/private/vision-replay/` — gitignored)

- [ ] **Step 1: 실패하는 시험을 쓴다**

`src/site/vision/test/test_overhead_track_replay.py`:

```python
"""D-NNN LOCAL: replay metrics over saved frames (here synthetic; real frames stay in private/)."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from rosy_vision.track.replay import main, score_frames
from rosy_vision.track.calibration import from_record

FIXTURE = json.loads((Path(__file__).resolve().parents[4]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
RECORD = FIXTURE["config_example"]["calibration"]


def _floor():
    image = np.full((360, 640, 3), 120, np.uint8)
    image[:, 100:104] = 230
    image[200:204, :] = 230
    return image


def _robot():
    image = _floor()
    image[141:159, 291:309] = 30
    return image


def _write(directory: Path):
    frames = [_floor()] * 31 + [_robot()] * 5 + [_floor()] * 3
    for index, image in enumerate(frames):
        cv2.imwrite(str(directory / f"{index:06d}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 100])
    labels = {f"{index:06d}.jpg": [[299.5, 149.5]] for index in range(31, 36)}
    labels.update({f"{index:06d}.jpg": [] for index in range(36, 39)})
    labels["000000.jpg"] = []
    return labels


def _expected(metrics):
    assert metrics["frames"] == 39
    assert metrics["statuses"] == {"LEARNING": 31, "OK": 8}
    assert metrics["scored_frames"] == 8
    assert (metrics["matched"], metrics["missed"], metrics["false_positives"]) == (5, 0, 0)
    assert metrics["false_positives_per_frame"] == 0.0
    assert metrics["offset_m"]["median"] < 0.01


def test_score_frames_counts_matches_misses_and_false_positives(tmp_path):
    labels = _write(tmp_path)
    frames = [(path.name, cv2.imread(str(path))) for path in sorted(tmp_path.glob("*.jpg"))]
    calibration = from_record(RECORD, source_id="ceiling_north", map_id="map_v2_fleet",
                              frame_size=(640, 360), lens=None)
    _expected(score_frames(frames, calibration, labels))


def test_cli_prints_the_metrics_as_json(tmp_path, capsys):
    frames = tmp_path / "frames"
    frames.mkdir()
    labels = _write(frames)
    (tmp_path / "record.json").write_text(json.dumps(RECORD), encoding="utf-8")
    (tmp_path / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    assert main(["--frames", str(frames), "--calibration", str(tmp_path / "record.json"),
                 "--labels", str(tmp_path / "labels.json")]) == 0
    _expected(json.loads(capsys.readouterr().out))


def test_cli_refuses_a_record_that_does_not_fit_the_frames(tmp_path, capsys):
    frames = tmp_path / "frames"
    frames.mkdir()
    cv2.imwrite(str(frames / "000000.jpg"), np.full((480, 640, 3), 120, np.uint8))
    (tmp_path / "record.json").write_text(json.dumps(RECORD), encoding="utf-8")
    (tmp_path / "labels.json").write_text("{}", encoding="utf-8")
    assert main(["--frames", str(frames), "--calibration", str(tmp_path / "record.json"),
                 "--labels", str(tmp_path / "labels.json")]) == 2
    assert "does not fit" in capsys.readouterr().err


def test_an_empty_folder_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no .jpg frames"):
        main(["--frames", str(tmp_path), "--calibration", str(tmp_path / "x.json"),
              "--labels", str(tmp_path / "y.json")])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test/test_overhead_track_replay.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'rosy_vision.track.replay'`.

- [ ] **Step 3: 구현한다**

`src/site/vision/rosy_vision/track/replay.py`:

```python
"""Replay saved overhead frames through the tracking backend (D-NNN, LOCAL evidence).

    python -m rosy_vision.track.replay --frames DIR --calibration record.json --labels labels.json [--fps 3]

DIR holds JPEGs whose sorted file names are capture order; frame i is taken at i / fps
seconds. record.json is one approved calibration record as the Fleet calibration listing
returns it (one element of "calibrations"). labels.json maps a file name to the
floor-centre pixels of each robot, {"000123.jpg": [[u, v], ...]}; [] means "no robot"
(scores false positives) and frames without an entry are not scored. The empty-track
frames at the start are the LEARNING frames. Prints one JSON object and writes nothing.
Frames from a real site are internal evidence: keep them under the gitignored private/
folder, never in the repository.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

import cv2
import numpy as np

from rosy_vision.track import geometry
from rosy_vision.track.background_blob import BackgroundBlobDetector
from rosy_vision.track.calibration import from_record
from rosy_vision.track.model import Calibration, Frame, RobotDetector

GATE_M = 0.30


def score_frames(frames: Iterable[tuple[str, np.ndarray]], calibration: Calibration,
                 labels: Mapping[str, Sequence[Sequence[float]]], *, fps: float = 3.0,
                 gate_m: float = GATE_M, detector: RobotDetector | None = None) -> dict:
    detector = detector or BackgroundBlobDetector()
    image_to_map = geometry.as_matrix(calibration.image_to_map)
    statuses: dict[str, int] = {}
    offsets: list[float] = []
    count = scored = missed = false_positives = 0
    for index, (name, image) in enumerate(frames):
        count += 1
        result = detector.detect(Frame(image, index / fps), calibration)
        statuses[result.status] = statuses.get(result.status, 0) + 1
        if name not in labels or result.status != "OK":
            continue
        scored += 1
        truth = (geometry.apply(image_to_map, labels[name]) if len(labels[name])
                 else np.zeros((0, 2)))
        found = [(d.x, d.y) for d in result.detections]
        pairs = sorted((float(np.hypot(fx - tx, fy - ty)), i, j)
                       for i, (tx, ty) in enumerate(truth) for j, (fx, fy) in enumerate(found))
        used_truth: set[int] = set()
        used_found: set[int] = set()
        for distance, i, j in pairs:
            if distance > gate_m or i in used_truth or j in used_found:
                continue
            used_truth.add(i)
            used_found.add(j)
            offsets.append(distance)
        missed += len(truth) - len(used_truth)
        false_positives += len(found) - len(used_found)
    return {
        "frames": count,
        "statuses": statuses,
        "scored_frames": scored,
        "matched": len(offsets),
        "missed": missed,
        "false_positives": false_positives,
        "false_positives_per_frame": round(false_positives / scored, 3) if scored else None,
        "offset_m": None if not offsets else {
            "mean": round(statistics.fmean(offsets), 4),
            "median": round(statistics.median(offsets), 4),
            "p90": round(float(np.percentile(offsets, 90)), 4),
            "max": round(max(offsets), 4),
        },
    }


def iter_frames(directory: Path | str) -> Iterator[tuple[str, np.ndarray]]:
    """Decode frames lazily (a few hundred full frames do not fit in memory at once)."""
    paths = sorted(Path(directory).glob("*.jpg"))
    if not paths:
        raise ValueError(f"no .jpg frames in {directory}")
    for path in paths:
        image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"cannot decode {path.name}")
        yield path.name, image


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rosy_vision.track.replay")
    parser.add_argument("--frames", required=True, type=Path)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--fps", type=float, default=3.0)
    args = parser.parse_args(argv)
    frames = iter_frames(args.frames)
    first = next(frames)
    record = json.loads(args.calibration.read_text(encoding="utf-8"))
    size = (first[1].shape[1], first[1].shape[0])
    calibration = from_record(record, source_id=record.get("source_id"), map_id=record.get("map_id"),
                              frame_size=size, lens=record.get("lens"))
    if calibration is None:
        print("calibration record does not fit these frames (size, aspect or fields)", file=sys.stderr)
        return 2
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    metrics = score_frames(itertools.chain([first], frames), calibration, labels, fps=args.fps)
    print(json.dumps(metrics, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 통과를 확인한다**

Run: `C:/Python314/python.exe -m pytest src/site/vision/test/test_overhead_track_replay.py -q -p no:cacheprovider`
Expected: PASS — `4 passed`.

- [ ] **Step 5: 커밋**

```bash
git add src/site/vision/rosy_vision/track/replay.py src/site/vision/test/test_overhead_track_replay.py
git diff --cached --name-only
git commit -m "feat(vision): D-NNN replay metrics for saved overhead frames" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: 실물 프레임을 받는다(LOCAL 재생 세트, 사람 필요)**

로봇은 공유 자원이다(9dfk `.201`, 8kcn `.202`, 동료 세션이 쓴다). 사용자에게 먼저 묻는다: "천장 카메라 재생 세트를 찍으려고 합니다. 로봇 한 대를 전원만 켠 채(모터 명령 없음, G4/G5 불필요) 손으로 트랙 노드에 옮겨 놓아 주실 수 있나요? 그동안 다른 세션이 그 로봇을 쓰지 않는지 확인해 주세요." 승인 없이는 진행하지 않는다.

`X:/DevTemp/overhead-replay/capture_frames.py`(커밋하지 않음):

```python
"""Save the bench Vision latest frames at ~3 fps through a Fleet viewer lease.

usage: capture_frames.py FLEET_ORIGIN OUT_DIR SECONDS
env:   ROSY_CONSOLE_TOKEN (viewer or operator), ROSY_SITE_CA (site CA PEM)
"""

import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path

FLEET, OUT, SECONDS = sys.argv[1].rstrip("/"), Path(sys.argv[2]), float(sys.argv[3])
VISION = "https://192.168.1.102:18447"
SOURCE = "ceiling_north"
OUT.mkdir(parents=True, exist_ok=True)
context = ssl.create_default_context(cafile=os.environ["ROSY_SITE_CA"])
console_token = os.environ["ROSY_CONSOLE_TOKEN"]


def lease():
    request = urllib.request.Request(
        f"{FLEET}/api/fleet/vision/lease", method="POST",
        data=json.dumps({"source_id": SOURCE}).encode(),
        headers={"Authorization": f"Bearer {console_token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, context=context, timeout=5) as response:
        return json.load(response)["lease"], time.monotonic() + 50.0


bearer, renew_at = lease()
index, last_seq, end = 0, None, time.monotonic() + SECONDS
log = (OUT / "frames.jsonl").open("w", encoding="utf-8")
while time.monotonic() < end:
    if time.monotonic() > renew_at:
        bearer, renew_at = lease()
    request = urllib.request.Request(f"{VISION}/api/vision/sources/{SOURCE}/frame",
                                     headers={"Authorization": f"Bearer {bearer}"})
    try:
        with urllib.request.urlopen(request, context=context, timeout=5) as response:
            seq = response.headers.get("X-Frame-Seq")
            if seq != last_seq:
                (OUT / f"{index:06d}.jpg").write_bytes(response.read())
                log.write(json.dumps({"file": f"{index:06d}.jpg", "seq": seq, "t": time.time(),
                                      "lens": response.headers.get("X-Source-Lens")}) + "\n")
                index, last_seq = index + 1, seq
    except OSError as exc:
        print("frame read failed:", type(exc).__name__, file=sys.stderr)
    time.sleep(0.34)
log.close()
print(f"saved {index} frames to {OUT}")
```

절차(사람과 함께):
1. 트랙을 비운다. 콘솔에서 "맵 자동 맞춤" → 통과 제안 → "추적 보정 적용". `GET /api/fleet/calibrations`의 해당 행을 `X:/DevTemp/overhead-replay/record.json`으로 저장한다(콘솔 응답 그대로, 한 원소).
2. `C:/Python314/python.exe X:/DevTemp/overhead-replay/capture_frames.py <bench Fleet origin> X:/DevTemp/overhead-replay/2026-10-0X-ceiling-north 150`을 시작한다. Vision 인증서가 IP SAN이 없어 실패하면 Fleet이 알려 준 `frame_path`의 호스트 이름(`<name>.local`)으로 `VISION`을 바꾼다. TLS 검사를 끄지 않는다.
3. 처음 15 s는 트랙을 비워 둔다(LEARNING). 이어서 로봇 하나를 노드 `NE`(-0.1818, 0.1999) → `NW`(-0.5198, 0.1723) → `SW`(-0.5216, -0.1682) → `SE`(-0.1826, -0.1983) → 주차 `spot`(-1.0, 0.0) 순서로 옮겨 각 자리에 15 s씩 둔다(`src/runtime/sensing/map/map_v2_fleet/lane_graph.yaml`; 실제 사이트 지도가 다르면 그 지도의 노드를 쓴다). 사람 손이 화면에 있는 동안은 라벨을 붙이지 않는다. 각 정지 구간의 시작·끝 시각(벽시계)을 적는다. 마지막 15 s는 다시 빈 트랙.
4. `X:/DevTemp/overhead-replay/make_labels.py`(커밋하지 않음)로 라벨을 만든다 — 정지 구간 프레임은 노드 좌표를 기록의 `map_to_image`로 픽셀로 옮긴 값, 빈 트랙 구간(학습 뒤)은 `[]`:

```python
"""usage: make_labels.py CAPTURE_DIR record.json segments.json > labels.json
segments.json: [{"from": t0, "to": t1, "node": [x, y] or null}, ...]  (wall-clock seconds)"""

import json
import sys
from pathlib import Path

import numpy as np

capture, record, segments = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), json.loads(Path(sys.argv[3]).read_text())
map_to_image = np.asarray(record["map_to_image"], float).reshape(3, 3)
labels = {}
for line in (capture / "frames.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    for segment in segments:
        if segment["from"] <= row["t"] <= segment["to"]:
            if segment["node"] is None:
                labels[row["file"]] = []
            else:
                u, v, w = map_to_image @ np.array([segment["node"][0], segment["node"][1], 1.0])
                labels[row["file"]] = [[u / w, v / w]]
print(json.dumps(labels, indent=1))
```

5. 지표를 낸다:

```bash
PYTHONPATH="F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl/src/site/vision;F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl/src/site/games;F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl/src/contracts/foundation" \
  C:/Python314/python.exe -m rosy_vision.track.replay --frames X:/DevTemp/overhead-replay/2026-10-0X-ceiling-north \
  --calibration X:/DevTemp/overhead-replay/record.json --labels X:/DevTemp/overhead-replay/labels.json
```

Expected(잠정 합격): `offset_m.median ≤ 0.10`, `false_positives_per_frame ≤ 0.1`. 못 미치면 숫자를 고치기 전에 원인을 적는다(시차 높이, 축소, 그림자, 크기 창).
6. 고른 프레임·`frames.jsonl`·`record.json`·`segments.json`·`labels.json`·지표 JSON을 main checkout의 gitignored `F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/private/vision-replay/2026-10-0X-ceiling-north/`로 복사한다(git 색인에 닿지 않는다). 공개 저장소에는 지표 숫자만 Task 10의 `logs.md`에 적는다(IP·토큰·영상 없이).

- [ ] **Step 7: 실물 확인(DEVICE, 모터 동작 없음)**

전제: Step 6과 같은 사용자 승인. Fleet은 이 브랜치 코드로 `--sightings-config`(`ceiling_north` 포함)·`--sightings-db`와 함께, Vision은 같은 `site-cameras.yaml`로 `rosy-vision vision ... --track`으로 돌아야 한다. 벤치의 기존 스택(다른 세션 것일 수 있다)을 재시작하기 전에 사용자에게 묻는다.

1. 트랙을 비우고 콘솔 "배경 다시 학습" → 상태줄이 "배경 학습 중"에서 약 10 s 뒤 "추적 중 · ~3.0 fps"가 되는지 본다.
2. 빈 트랙 60 s 동안 `GET /api/fleet/tracking`을 1 s마다 읽어 `unknown`이 0인지 기록한다.
3. 로봇 두 대(전원만, 모터 명령 없음)를 사람이 노드 5곳(Step 6과 같은 노드)에 차례로 놓는다. 각 자리에서 5 s 기다린 뒤 `/api/fleet/tracking`을 5회 읽어 `camera.x/y`의 중앙값과 노드 좌표의 거리, 그리고 로봇이 `MATCHED`면 `offset_m`과 `pose_frame_verified`를 기록한다. 손으로 옮긴 로봇의 자가보고 자세는 바퀴가 돌지 않아 틀릴 수 있다 — 합격 판정은 노드 대비 카메라 거리로 하고, 자가보고 차이는 참고로만 적는다.
4. 합격(잠정): 노드 대비 카메라 거리 중앙값 ≤ 0.10 m(10곳 이상), 빈 트랙 `unknown` 평균 ≤ 0.1개/읽기. 렌즈 교체가 가능하면 앱에서 렌즈를 바꿔 상태줄이 "보정 필요"가 되는지도 본다.
5. 원자료(CSV)는 `private/vision-replay/`에, 요약 숫자는 Task 10의 `src/site/vision/logs.md`에 적는다.

---

## Task 10: 하네스·문서·크기 판정·landing

**Files:**
- Modify: `src/site/vision/{logs,progress}.md`, `src/site/fleet/{logs,progress}.md`, `src/contracts/foundation/{logs,progress}.md`, `src/site/vision/AGENTS.md`, `src/contracts/foundation/core_common/protocol/AGENTS.md`, `docs/reference/ROSY API & Protocol Reference.md`, `docs/plans/2026-10-01-overhead-markerless-tracking-design.md`(3행), `test/architecture/test_module_structure.py`(`"fleet"` 판정), 하네스가 다시 만드는 `index.md`들

- [ ] **Step 1: 크기 판정을 확인하고 고친다**

Run: `C:/Python314/python.exe -m pytest test/architecture/test_module_structure.py -q -p no:cacheprovider -k "size_verdicts or over_budget"`
Expected: `fleet` 패키지가 판정(main 23,543) + 150을 넘으면 FAIL — 메시지 `fleet: <N> lines, grew past 23543+150; re-judge`의 `<N>`이 지금 줄 수다. 그 경우 `test/architecture/test_module_structure.py`의 `"fleet": (` 항목 숫자를 `<N>`으로 바꾸고, 판정 문자열의 `"Split remains unscheduled (docs/plans/2026-09-30-er2-mission-feedback-loop.md)",` 바로 앞에 이 조각을 넣는다(`<N>`은 출력의 숫자 그대로):

```python
        "re-judged 2026-10-0X at <N> after D-NNN overhead tracking joined as its own modules "
        "(server/tracking.py service, tracking_match.py pure matcher, tracking_calibration.py store, "
        "tracking_routes.py, web/tracking-layer.js pure, web/tracking-view.js DOM, each under the "
        "D-362 budget) plus tests; app.py, console_routes.py and cli.py only gained wiring; verdict "
        "unchanged. "
```

다시 실행해 PASS를 확인한다. 개별 파일은 모두 600(.py)·800(웹) 아래여야 한다 — 넘으면 판정을 쓰지 말고 나눈다.

- [ ] **Step 2: 저장소 가드를 돌린다**

```bash
# 시험 파일 이름이 suite 사이에서 새로 겹치지 않는다(main과 같은 목록이어야 한다)
git ls-files | grep -E '/test_[^/]*\.py$' | sed 's#.*/##' | sort | uniq -d > X:/DevTemp/overhead-tracking/dups-branch.txt
git ls-tree -r --name-only main | grep -E '/test_[^/]*\.py$' | sed 's#.*/##' | sort | uniq -d > X:/DevTemp/overhead-tracking/dups-main.txt
diff X:/DevTemp/overhead-tracking/dups-main.txt X:/DevTemp/overhead-tracking/dups-branch.txt
# 비밀 스캔(40자 이상 hex, 50자 이상 영숫자, 비밀 이름 리터럴)
C:/Python314/python.exe -m pytest test/test_release_boundary_guards.py -q -p no:cacheprovider -k secret
# 구조·배치·역할·D-310 배치
C:/Python314/python.exe -m pytest test/architecture -q -rfE -p no:cacheprovider > X:/DevTemp/overhead-tracking/arch.txt
C:/Python314/python.exe test/known_failures.py X:/DevTemp/overhead-tracking/arch.txt
# D-178 평가표(새 패키지 없음)
C:/Python314/python.exe -m pytest test/test_module_scorecard.py -q -p no:cacheprovider
# 남은 D-NNN 자리표시
git grep -n "D-NNN" -- . ":!docs/plans/2026-10-01-overhead-markerless-tracking-plan.md"
```

Expected: `diff` 출력 없음, 비밀 스캔은 main의 기존 실패 말고 새 실패 없음(`known_failures.py`로 확인), `known_failures.py` exit 0, 평가표 PASS, `git grep` 출력 없음.

- [ ] **Step 3: 하네스 기록을 쓴다**

`src/site/vision/logs.md` 끝에 붙인다(`<...>`는 실제 출력 숫자로):

```markdown

## 2026-10-0X · uncommitted · feat(vision): D-NNN 무마커 천장 카메라 추적

- 변경: 새 `rosy_vision/track/` — `model.py`(고정 인터페이스, URDF 상수 0.125 m·0.08257 m), `geometry.py`(homography→카메라 위치, 시차 보정), `background_blob.py`(`background-blob/1`: MOG2 30프레임·10 s 학습 뒤 고정, 그림자 제외, 트랙 사각형, 바닥 지름 0.12–0.26 m, 30 % 초과 `SCENE_CHANGED`), `calibration.py`(마커 우선, 승인 기록은 source·map·렌즈·비율이 맞을 때만), `fleet_client.py`(`POST /api/fleet/detections`, `GET /api/fleet/detections/config`), `worker.py`(`TrackWorker`), `replay.py`. `project.marker_homography` 분리, `VisionWorker(tracker=)`, `rosy-vision vision --track`.
- 증거: `python -m pytest src/site/vision/test -q` <N> passed (2026-10-0X Windows, Python 3.14). 재생(LOCAL, `private/vision-replay/...`): median <m> m, FP/frame <f> 또는 "미실시". DEVICE: <요약> 또는 "미실시".
- gate 변화: 없음(SOURCE/LOCAL 코드·합성). 재생·DEVICE 숫자가 잠정 합격을 넘으면 D-NNN에 확정 숫자를 적는다.
```

`src/site/fleet/logs.md` 끝에 붙인다:

```markdown

## 2026-10-0X · uncommitted · feat(fleet): D-NNN 관제 카메라 추적 — 보정 기록, 매칭, 콘솔 레이어

- 변경: `server/tracking_calibration.py`(source별 승인 기록, `paint-` revision, sighting DB 옆 표 + 감사), `tracking_match.py`(순수 헝가리안, 0.30 m), `tracking.py`(1.0 s 수명, revision 409, D-395 `localization` 규칙, 상태 경로가 넘긴 상태만 사용), `tracking_routes.py`(`/api/fleet/detections`, `/detections/config`, `/tracking`, `/tracking/relearn`, `/calibrations`, `/calibrations/{source_id}`). 콘솔: "추적 보정 적용", "관제 카메라 추적" 레이어(`tracking-layer.js` 순수, `tracking-view.js` DOM), 상태줄, "배경 다시 학습". 교통정리·bays·미션·localization이 추적을 import하지 않는다는 경계 시험.
- 증거: `python -m pytest src/site/fleet/test -q` <N> passed, `node --test src/site/fleet/test/web/*.test.mjs` <M> pass (2026-10-0X Windows).
- gate 변화: 없음.
```

`src/contracts/foundation/logs.md` 끝에 붙인다:

```markdown

## 2026-10-0X · uncommitted · feat(contracts): D-NNN `overhead_detections` 계약

- 변경: `core_common/protocol/overhead_detections.py`(`OverheadDetectionsPayload`, extra 금지, 최대 16개, `OK`일 때만 검출, `CALIBRATION_REQUIRED`일 때만 revision null). 벡터 `test/fixtures/protocol/overhead-detections.v1.json`(Vision·Fleet 공용, config 예시 포함). 기존 `detections.py`(D-137 로봇 카메라 상자)와 이름을 나눴다.
- 증거: `python -m pytest src/contracts/foundation/test/test_overhead_detections_vectors.py -q` 17 passed.
- gate 변화: 없음.
```

세 모듈의 `progress.md` front matter에서 `adrs:` 목록 끝에 `D-NNN`을, `plans:` 목록 끝에 다음 두 줄을 더한다(게이트 상태는 바꾸지 않는다):

```yaml
  - docs/plans/2026-10-01-overhead-markerless-tracking-design.md
  - docs/plans/2026-10-01-overhead-markerless-tracking-plan.md
```

- [ ] **Step 4: 안내 문서를 고친다**

`src/site/vision/AGENTS.md` — Subdirectories 표의 `rosy_vision/` 행 끝 `` `cli.py` |``를 `` `cli.py`, `track/` (D-NNN markerless tracking: fixed detector interface, `background_blob`, calibration choice, Fleet detections client, replay) |``로 바꾸고, "Working In This Directory" 목록 끝에 붙인다:

```markdown
- D-NNN markerless tracking (`rosy_vision/track/`, `vision --track`) sends anonymous floor detections (map metres, no image, pixels or robot id) to `POST /api/fleet/detections` and reads only its own approved calibration and relearn counter from `GET /api/fleet/detections/config`, both with the source's sighting token. Corner markers win over the approved paint fit; a changed lens voids the fit. Display only: never sightings, `CameraMap`, tasks or motion. Real replay frames stay in the gitignored `private/` folder.
```

`src/contracts/foundation/core_common/protocol/AGENTS.md` — `localization.py` 행 다음에 넣는다:

```markdown
| `overhead_detections.py` | D-NNN anonymous overhead-camera floor detections (`OverheadDetectionsPayload`: map metres, no image/pixels/robot id, max 16, display only); vectors `test/fixtures/protocol/overhead-detections.v1.json`. Not the D-137 robot-camera `detections.py` |
```

`docs/reference/ROSY API & Protocol Reference.md` — `## 10.6.2 Site Fleet policy-eligible evidence` 제목 바로 앞에 넣는다(파일은 CRLF — 고친 뒤 `file`로 `CRLF`인지 확인한다):

```markdown
## 10.6.3 Site Fleet overhead tracking (D-NNN)

표시·교차확인 전용이다(D-268). 영상·픽셀·robot_id를 받지 않고, 교통정리·bays·미션·D-395 위치 확정의 입력이 아니다. `fleet console --sightings-config`가 있을 때만 등록되고, 보정 기록은 `--sightings-db` 파일의 별도 표에 둔다(없으면 메모리).

| Method | Path | Credential | 요구사항 |
|---|---|---|---|
| POST | `/api/fleet/detections` | source 전용 Bearer token(sighting과 같음) | `OverheadDetectionsPayload`. source·map이 설정과 같고, revision이 마커 revision 또는 승인 기록 revision이어야 한다(아니면 409 `CALIBRATION_MISMATCH`/`MAP_MISMATCH`). 1 s 수명, 미래 50 ms 허용, `captured_at` 순서 |
| GET | `/api/fleet/detections/config` | source 전용 Bearer token | `{source_id, map_id, calibration, relearn_seq}` — 자기 source의 승인 기록만 |
| GET | `/api/fleet/tracking` | viewer 이상 | source 상태(`OK`/`LEARNING`/`CALIBRATION_REQUIRED`/`SCENE_CHANGED`/`STALE`/`NONE`, fps, `last_error`), 로봇별 `MATCHED`/`NO_DETECTION`/`NO_POSE`/`CAMERA_UNAVAILABLE`와 `offset_m`·`pose_frame_verified`, `unknown` |
| POST | `/api/fleet/tracking/relearn` | operator | `{source_id}` → `relearn_seq` 증가(Vision이 배경을 다시 학습) |
| GET | `/api/fleet/calibrations` | viewer 이상 | 승인 기록 목록 |
| POST | `/api/fleet/calibrations` | operator | D-375 통과 제안 승인: `{source_id, map_id?, map_to_image[9], image{width,height}, track_bounds_m, fit_score, lens?, frame_seq?}` → 기록(`paint-` revision, `approved_by`) |
| DELETE | `/api/fleet/calibrations/{source_id}` | operator | 기록 회수(감사 행) |
```

`docs/plans/2026-10-01-overhead-markerless-tracking-design.md:3` — 바꾼다:

```markdown
**결정:** 새 ADR 하나(번호는 main에 들일 때 rosy-land-on-main 절차로 정한다). 이 문서는 그 ADR의 근거다.
```
→
```markdown
**결정:** [D-NNN](../adr/D-NNN-overhead-markerless-tracking-display-only.md). 이 문서는 그 ADR의 근거다.
```

- [ ] **Step 5: 하네스를 다시 만들고 검사한다**

```bash
C:/Python314/python.exe tools/harness/rosy_harness.py generate
C:/Python314/python.exe tools/harness/rosy_harness.py lint
git status --short
```

Expected: lint 0. `git status`에 이 Task에서 고친 파일과 하네스가 다시 만든 `index.md`(vision·fleet·foundation, 그리고 하네스가 고치는 다른 생성 파일)만 보인다. 모르는 파일이 보이면 손대지 않고 원인을 확인한다.

- [ ] **Step 6: 전체 시험을 suite별로 돌리고 기존 실패와 비교한다**

```bash
C:/Python314/python.exe -m pytest src/contracts/foundation/test -q -rfE -p no:cacheprovider > X:/DevTemp/overhead-tracking/foundation.txt
C:/Python314/python.exe test/known_failures.py X:/DevTemp/overhead-tracking/foundation.txt
C:/Python314/python.exe -m pytest src/site/vision/test -q -rfE -p no:cacheprovider > X:/DevTemp/overhead-tracking/vision.txt
C:/Python314/python.exe test/known_failures.py X:/DevTemp/overhead-tracking/vision.txt
C:/Python314/python.exe -m pytest src/site/fleet/test -q -rfE -p no:cacheprovider > X:/DevTemp/overhead-tracking/fleet.txt
C:/Python314/python.exe test/known_failures.py X:/DevTemp/overhead-tracking/fleet.txt
node --test src/site/fleet/test/web/*.test.mjs
```

Expected: 세 `known_failures.py` 모두 exit 0, node `fail 0`. `NEW` 줄은 이 브랜치 잘못으로 보고 고친다(목록에 더하지 않는다).

- [ ] **Step 7: 커밋**

```bash
git status --short
git add src/site/vision/logs.md src/site/vision/progress.md src/site/vision/AGENTS.md src/site/fleet/logs.md src/site/fleet/progress.md src/contracts/foundation/logs.md src/contracts/foundation/progress.md src/contracts/foundation/core_common/protocol/AGENTS.md "docs/reference/ROSY API & Protocol Reference.md" docs/plans/2026-10-01-overhead-markerless-tracking-design.md test/architecture/test_module_structure.py
# 하네스가 다시 만든 생성 파일은 git status --short에 나온 경로를 하나씩 더한다(예):
git add src/site/vision/index.md src/site/fleet/index.md src/contracts/foundation/index.md
git diff --cached --name-only
git commit -m "docs(harness): D-NNN overhead tracking logs, progress, API reference and size verdict" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(크기 판정을 고치지 않았으면 `test/architecture/test_module_structure.py`를 `git add`에서 뺀다. 생성 파일 목록은 Step 5의 `git status`에 실제로 나온 것만 적는다.)

- [ ] **Step 8: 독립 리뷰**

superpowers:requesting-code-review로 다른 에이전트(code-reviewer 또는 verifier)에게 브랜치 `feat/overhead-markerless-tracking`의 `main...HEAD` diff를 리뷰받는다. 특히: 표시 전용 경계(교통정리·미션 import 없음), 자격 분리(source 토큰만), 경로 이름(영상 단어 없음), 1 s 수명과 지난 값 미표시, D-395 레거시 정책. 지적을 superpowers:receiving-code-review로 처리하고 Step 6을 다시 돈다. 교훈이 있으면 `/ce-compound`.

- [ ] **Step 9: main에 들인다(rosy-land-on-main, push 없음)**

```bash
cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/markerless-impl"
git merge --no-edit main
# 충돌이 ADR Log면 양쪽 행을 모두 남긴다(CRLF 유지). 번호가 겹쳤으면 Task 0 Step 2부터 다시 정하고 모든 D-NNN 자리를 바꾼다.
```

Step 6을 다시 돌려 새 실패가 없음을 확인한 뒤 main checkout에서:

```bash
cd "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
git status --short --branch
git merge --ff-only feat/overhead-markerless-tracking
```

ff가 안 되면 worktree에서 `git merge main`을 반복한다. 동료의 미커밋 파일이 막으면 그 파일을 건드리지 않고 기다리거나(최대 10 × 60 s) 사용자에게 묻는다. push하지 않는다. main에 들인 뒤 사용자에게 커밋 해시와 남은 DEVICE/재생 항목을 알린다.
