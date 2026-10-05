# Lane evidence pipeline implementation plan

**Goal:** Preserve source-frame lane targets from robot recordings through model-PC conversion so a straight departure can be investigated.

**Architecture:** Reuse PilotRecorder's local MCAP storage, segmentation, quota and recovery. Record existing keep debug independently of preview mode. Match debug by source image stamp through MCAP conversion and frame extraction; retain it only as unreviewed evidence.

**Tech Stack:** Python, ROS 2 rosbag2 MCAP, existing dataset conversion and pytest.

## Task 1: Default recording diagnostics

- Modify `middleware/perception/control/pilot_recording.py` and its existing tests.
- Write failing tests for raw recording of `line/keep_debug`, correct manifest topics and no duplicate subscription in annotated mode.
- Include the existing topic in base Pilot topics; preserve preview/annotation metadata and all quotas, permissions and stop behavior.

## Task 2: Preserve source-frame alignment

- Modify `learning/training/perception/dataset/bag_to_video.py`, `extract.py` and existing tests.
- Write failing tests where debug arrives after its source frame and where missing/wrong stamps must produce null. Include an MCAP integration fixture.
- Reuse existing stamped evidence matching and its 1us tolerance/0.5s arrival bound. Preserve diagnostic fields in sidecars and extracted frames. Do not use debug as training ground truth.

## Task 3: Verify and land

- Run recorder, conversion, extraction and related label/review tests with logs under `X:/DevTemp/lane-evidence-20261005/`; classify with `test/known_failures.py`.
- Document the new recording path and the remaining physical failure evidence gap.
- Commit only owned paths, merge current main, rerun related tests, and land with `--ff-only`.
- Device installation/readback and a new synchronized stationary capture require a reachable robot and the normal signed release path. This source change does not establish a fixed physical lane departure.

## 운영 경로

CORE의 기존 `POST /api/v1/recordings`로 녹화를 시작하고 `POST /api/v1/recordings/active/stop`으로 종료한다. 설치된 구버전에서는 `{"preview_mode":"annotated"}`가 keep debug를 포함한다. 새 소스에서는 기본 raw 녹화도 동일 진단을 포함하므로 주석 영상 옵션을 요구하지 않는다. 시작·종료 확인과 저장 한도, 연결 끊김 처리, 정지 상태에서만 허용되는 수신 조건을 유지한다.

기존 HTTP fetch의 manifest 검증을 거쳐 PC에서 `dataset/bag_to_video.py <session> --out <video-dir>`로 변환한다. `dataset/extract.py <session> --out <frame-dir>` 또는 변환된 MP4 입력으로 검토 프레임을 추출한다. `side.line/keep_debug`의 선택 경계·좌우·목표점·paint source와 해당 프레임의 최종 명령·odometry를 함께 비교한다. 원본 이미지 stamp가 없거나 맞지 않는 진단은 null로 취급한다. `line/keep_debug`는 자동 라벨이나 검토 승인 권한이 아니다.

이번 구현은 증거 손실 구간을 보완한다. 실패 구간 우선 선택, 검토된 마스크를 이용한 기하 비교, 확인된 원인의 제어 수정은 상위 설계의 후속 단계다. 현재 정지 녹화는 원본 이탈 당시의 기록을 대신하지 않는다.
