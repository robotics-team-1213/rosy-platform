# D-411 Pilot Recording, Control Descriptor, Gripper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** D-411의 세 결정을 순서대로 구현한다. (A) Pinky Pilot이 로봇 카메라 유닛에 학습용 bag 녹화를 시키고, 정지 중에만 CORE HTTP로 받아 PC에서 검증·변환·짝 확인까지 한다. (B) 기기가 `rosy.controls/1` 조작부 서술자를 알리고 Pilot은 kind별 위젯으로 화면을 조립한다(팔 조이스틱 포함). (C) OMX 시뮬레이션에 그리퍼 전용 절대 목표·쥠 readback·UI·시연 기록 `action.gripper` 열을 더한다.

**Architecture:** 녹화 프로세스는 `rosy-camera` 유닛의 `pilot_recorder_node`가 소유하고, 상태기계는 ROS-free `control/pilot_recording.py`에 둔다(기존 `recording.py` + `capture_trigger_node.py` 패턴). CORE는 `std_srvs/SetBool` 한 번으로 시작·정지를 요청하고, 래치된 상태 토픽을 받아 ROS-free 가드(`core_common/domain/pilot_recording.py`)가 소유 토큰·링크 끊김·seat 변경을 판정한다. 목록·tar 스트림은 ROS-free 저장소 모듈이 디스크(setgid `rosy-core` 읽기)에서 만든다. `teleop/intent`는 `CommandManager`의 증거 훅이 내고 `ros_bridge`가 발행한다(제어 경로는 읽지 않는다). 서술자는 `core_common/protocol/controls.py`가 정본이고 Pinky는 CORE capabilities, OMX는 SIM `/target`이 낸다. Pilot은 순수 모듈(`controls.js`·`arm-stick.js`·`recording.js`)과 DOM 위젯을 분리한다.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI(StreamingResponse), pytest(호스트, rclpy 없음), rclpy/rosbag2(로봇·WSL), 바닐라 ES 모듈(Node 서브프로세스 시험·Playwright), mcap/mcap_ros2·ffmpeg(PC).

- 설계: [D-411](../adr/D-411-pilot-robot-recording-control-descriptor-and-gripper.md). 브랜치 `feat/d411-pilot-recording-controls`, worktree `.worktrees/d411-pilot`. main 합류는 `rosy-land-on-main` 스킬 절차.

---

## 구조 규칙 (모든 태스크에 적용)

이 저장소 시험이 강제하는 규칙이다. 어기면 아키텍처·계약 시험이 실패한다.

1. **import 방향** — `core_common ← core_events ← core_features ← core_api_web ← core`. `control`(sensing)은 `core_common`에 의존해도 된다(`package.xml:21`). `omx_adapter`는 `core_common`만 본다. 새 Pilot 순수 모듈(`controls.js`·`arm-stick.js`·`recording.js`)은 **import 없이** 자족해야 한다 — Node 시험이 data: URL로 읽어 상대 import가 풀리지 않는다.
2. **크기 예산(P6, `test/architecture/test_module_structure.py`)** — `core_common/protocol/schemas.py`(1153줄, 증가 0)는 **건드리지 않는다**; 새 스키마는 새 파일. `core_features` 패키지는 상한까지 약 129줄 남았다 — 이 계획은 `command/manager.py`에 약 20줄만 더한다. `ros_bridge.py`는 682/756줄 — 추가는 약 40줄 이내. `gateway/core/services.py`는 568/600 — 3줄 이내. JS 파일은 800줄 상한(`drive.js` 505줄).
3. **시험 위치(D-184)** — `core_features`를 import하는 새 시험은 `src/runtime/services/test/`에만. CORE 엔드포인트 시험은 `src/runtime/gateway/test/`의 `core_client` 픽스처(`conftest.py:35-70`)를 쓴다. 새 시험 파일 이름은 저장소 전체에서 유일해야 한다(같은 호출에서 basename 충돌).
4. **ROS 노드 시험** — rclpy가 없으므로 노드 파일은 소스 텍스트 단언(`test_capture_trigger.py:207-258` 패턴)으로, 논리는 ROS-free 모듈 단위 시험으로 본다. `ros_bridge` 배선은 `test_bridge_timers.py`의 구조 하네스(토픽·QoS·클라이언트 순서)로만 본다 — 콜백을 부르는 시험을 거기에 더하지 않는다.
5. **이벤트(§8)** — 이벤트 이름은 발행 지점 문자열 리터럴, 새 이벤트마다 API Ref §8 행(`test_event_catalogue.py`).
6. **Pilot 자산 등록** — 새 JS는 다섯 곳에 함께 등록한다: `src/runtime/api_web/core_api_web/api/app.py` `pilot_assets`(216-241), `src/products/omx/adapter/omx_adapter/pilot_sim_api.py` `PILOT_ASSETS`(25-45), `src/hmi/pilot/sw.js` `SHELL`(6-31, `CACHE` 이름 올림), `src/hmi/pilot/test/dev_server.py` `PILOT_MIME`(31-55), 최상위 파일이면 `src/hmi/pilot/CMakeLists.txt` `install(FILES)`(6-20) / 새 디렉터리면 `install(DIRECTORY)`(22-27). `app.js`가 `drive.js`를 정적으로 import하므로 OMX SIM 서버도 Pinky 쪽 모듈을 전부 서빙해야 한다.
7. **API Ref 버전** — 이 브랜치 전체가 **v1.76** 한 행이다. Part A가 v1.75→v1.76으로 올리고, B·C는 같은 v1.76 행과 본문에 덧붙인다(미배포 브랜치 안의 같은 버전). 핀 6곳: 문서 L5·§11 행, `app.py:1`·`:111`, `test/test_line_follow_contract_docs.py:15`, `src/site/fleet/test/test_task_contract_docs.py:26,88`, `src/site/fleet/test/test_mission_progress.py:512`. 합류 때 main이 v1.76을 먼저 썼으면 `rosy-land-on-main` 절차로 번호를 다시 매긴다.
8. **명령어** — Windows에서는 `python`(`python3` 아님). 하네스는 `python tools/harness/rosy_harness.py generate|lint`. 실패 비교는 `python test/known_failures.py <run.txt>`.
9. **커밋** — 태스크마다 `git add <명시 경로>`만(절대 `git add -A` 아님). 메시지 마지막 줄은 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. 공유 main 체크아웃(`F:\Dev\Control\Robot\ROS\Rosy\Rosy OS`)은 건드리지 않는다.

## 사전 확인 (Task 0, 코드 변경 없음)

- [ ] `git -C "F:/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/d411-pilot" status --short --branch` → `## feat/d411-pilot-recording-controls`, 깨끗함.
- [ ] `python tools/harness/rosy_harness.py lint` 실행. **알려진 선행 결함:** D-411 커밋(2182edfa)이 D-410 없이 들어와 `D-410: missing and not declared in adr_gaps`가 난다(`rosy_harness.py:363-366`, `test/test_harness_contracts.py:351`). 이 계획은 이것을 고치지 않는다 — D-410을 소유한 브랜치가 main에 오면 `git merge main`으로 해소한다. 그 전까지 lint·`test_harness_contracts.py`의 이 한 항목 실패는 "기존 실패"로 기록하고, 다른 lint 오류가 0인지만 본다.

---

## File Structure

### Part A — 로봇 녹화·HTTP 수신·PC 수신·Pilot UI

| 파일 | 상태 | 책임 |
|---|---|---|
| `src/contracts/foundation/core_common/protocol/recording.py` | 생성 | 녹화 계약 정본: 경로·토픽·서비스 이름 상수, `TeleopIntent`·`RecorderStatus`·`ManifestFile`·`RecordingManifest`·`RecordingSummary`, `recording_id_ok`, `safe_member`, `teleop_intent()` |
| `src/contracts/foundation/core_common/domain/pilot_recording.py` | 생성 | CORE 가드: 상태 캐시·신선도, 소유 토큰, `/ws/state` 링크 수, seat 변경, 시작/정지 요청, 이벤트 |
| `src/contracts/foundation/core_common/domain/pilot_recording_store.py` | 생성 | 디스크 읽기: 목록, manifest 검증, tar 멤버 계획(경로 탈출 차단), USTAR 스트림 생성기 |
| `src/contracts/foundation/test/test_pilot_recording_contract.py` | 생성 | 계약 시험 |
| `src/contracts/foundation/test/test_pilot_recording_guard.py` | 생성 | 가드 시험 |
| `src/contracts/foundation/test/test_pilot_recording_store.py` | 생성 | 목록·tar·탈출 차단 시험 |
| `src/runtime/sensing/control/pilot_recording.py` | 생성 | 녹화 상태기계(시작·정지·10분·쿼터·종료 감지·복구·manifest sha256·fetched 표시), `pilot_bag_command` |
| `src/runtime/sensing/control/pilot_recorder_node.py` | 생성 | 얇은 노드: SetBool 서비스, 래치 상태·활성 토픽, fetched 구독, 1 Hz 틱 |
| `src/runtime/sensing/control/camera_detect_node.py` | 수정 128-142, 486-497 | `pilot_recorder/active`가 참인 동안에만 `camera/front/compressed` 발행 |
| `src/runtime/sensing/launch/camera_preview.launch.py` | 수정 76-125 | `pilot_recorder_node` 상시 기동, `pilot_recording_root` 인자 |
| `src/runtime/sensing/setup.py` | 수정 46-52 | `pilot_recorder_node` entry point |
| `src/runtime/sensing/test/test_pilot_recorder.py` | 생성 | 상태기계 시험 |
| `src/runtime/sensing/test/test_pilot_recorder_node.py` | 생성 | 노드·카메라·launch 소스 텍스트 시험 |
| `src/runtime/sensing/test/test_camera_preview_launch.py` | 수정 107 | `BASE`에 `pilot_recorder_node` |
| `deploy/robot/pinky_pro/native/tmpfiles-rosy-state.conf` | 수정 12 뒤 | `d /var/lib/rosy/pilot-recordings 2750 rosy-camera rosy-core -` |
| `deploy/robot/pinky_pro/image/customize-rootfs.sh` | 수정 367 뒤 | 같은 디렉터리 이미지 생성 |
| `deploy/robot/pinky_pro/native/rosy-camera.service` | 수정 17 뒤 | `ReadWritePaths=/var/lib/rosy/pilot-recordings` |
| `deploy/robot/pinky_pro/native/rosy-core.service` | 수정 76 뒤 | `ReadOnlyPaths=/var/lib/rosy/pilot-recordings` |
| `test/test_native_systemd_contract.py` | 수정 364-368, 407-418, 466-470, 698-717, 916 | 쓰기·읽기 선언, 프로그램 소스, tmpfiles·customizer 핀, 카메라 `ReadWritePaths` |
| `src/runtime/services/core_features/command/manager.py` | 수정 72-73, 87-114 | `intent_sink`·`note_intent`, `teleop`→`_teleop_decision` 분리 |
| `src/runtime/services/test/test_teleop_intent.py` | 생성 | 수락·거절·싱크 예외 시험 |
| `src/runtime/api_web/core_api_web/api/v1/control.py` | 수정 35-45 | 사전 검사 거절도 intent, 수락 시 seat 변경 통지 |
| `src/runtime/api_web/core_api_web/api/v1/recordings.py` | 생성 | `/api/v1/recordings` 라우터, 수신 게이트 |
| `src/runtime/api_web/core_api_web/api/v1/routes.py` / `api/app.py` | 수정 app.py 1, 111, 160-185 | 라우터 등록, v1.76 |
| `src/runtime/api_web/core_api_web/api/ws.py` | 수정 84-97 | `/ws/state` 열림·닫힘을 가드에 알림 |
| `src/runtime/api_web/core_api_web/api/deps.py` | 수정 75-100 | `CoreServicesLike.pilot_recording` |
| `src/runtime/gateway/core/services.py` | 수정 252 부근, 540-546 | `pilot_recording` 필드·생성 |
| `src/runtime/gateway/core/bridge/ros_bridge.py` | 수정 29-30, 135, 144-150, 237 | intent·fetched 발행, 상태 구독, SetBool 클라이언트, 가드 배선 |
| `src/contracts/foundation/config/rosy_default.yaml` | 수정 | `recording.pilot_root` |
| `src/runtime/gateway/test/test_recordings_api.py` | 생성 | API 시험 |
| `src/runtime/gateway/test/test_bridge_timers.py` | 수정 212-264 | 새 구독·발행·클라이언트 |
| `docs/reference/ROSY API & Protocol Reference.md` | 수정 5, 116-157, 278-296, 779-, 1799- | v1.76, §5.10 녹화, ERR-102 코드 5개, §8 이벤트 2개 |
| 버전 핀 5곳 | 수정 | 위 구조 규칙 7 |
| `tools/perception/dataset/fetch_http.py` | 생성 | HTTP 목록·수신·안전 추출·sha256 검증·`bag_to_video`·짝 확인 |
| `tools/perception/dataset/bag_to_video.py` | 수정 56-57, 98-100 | `teleop/intent` 사이드 토픽 |
| `tools/perception/rosy_ml.py` | 수정 521-524, 569-578 | `fetch <robot> --http` |
| `tools/perception/test/test_fetch_http.py` | 생성 | 로컬 HTTP 서버로 끝까지 |
| `tools/perception/test/test_bag_to_video.py`, `test_rosy_ml.py` | 수정(추가) | intent 토픽, fetch 배선 |
| `src/hmi/pilot/recording.js` | 생성 | 순수: 경과·크기 서식, 토글 표시, 시트 행·차단 사유 |
| `src/hmi/pilot/screens/robot-recording.js` | 생성 | 로봇 녹화 토글·"녹화본" 시트 DOM |
| `src/hmi/pilot/client.js` | 수정 24-49 | `apiBlob()` |
| `src/hmi/pilot/screens/drive.js` | 수정 139-150, 386-425, 478-504 | "화면 녹화" 이름, 로봇 녹화 마운트·해제 |
| `src/hmi/pilot/styles.css` | 수정 319 부근 | `[data-recordings-sheet]` |
| `src/hmi/pilot/test/test_recording_view.py` | 생성 | 순수 모듈 Node 시험 |
| `src/hmi/pilot/test/dev_server.py`, `test_pilot_browser.py`, `src/runtime/api_web/test/test_pilot_route.py` | 수정 | 가짜 녹화 API, 브라우저 회귀, 자산 |

### Part B — `rosy.controls/1` 서술자·위젯 조립·팔 조이스틱

| 파일 | 상태 | 책임 |
|---|---|---|
| `src/contracts/foundation/core_common/protocol/controls.py` | 생성 | 서술자 정본(kind 3종, 판별 union), `pinky_controls()` |
| `src/contracts/foundation/core_common/protocol/omx_sim.py` | 수정 20-27 | `OmxSimTarget.controls` |
| `src/contracts/foundation/test/test_controls_contract.py` | 생성 | 스키마·유도 시험 |
| `src/runtime/api_web/core_api_web/api/v1/system.py` | 수정 186-207 | capabilities `controls` |
| `src/runtime/api_web/core_api_web/api/deps.py` | 수정 75-100 | `CoreServicesLike.adapter_registry` |
| `src/runtime/gateway/test/test_capabilities_controls.py` | 생성 | API 시험 |
| `src/products/omx/adapter/omx_adapter/pilot_sim_runtime.py` | 수정 13-26 | `controls()` |
| `src/products/omx/adapter/omx_adapter/pilot_sim_api.py` | 수정 182-188 | `/target`의 `controls` |
| `src/products/omx/adapter/omx_adapter/pilot_sim_server.py` | 수정 41-43 | 출처 해시에 `controls.py` |
| `src/hmi/pilot/controls.js` | 생성 | 순수: 서술자 읽기·대체·위젯 계획·Pinky 프로필 변환 |
| `src/hmi/pilot/arm-stick.js` | 생성 | 순수: 축 계산·우세 축 단계·순차 조거 |
| `src/hmi/pilot/screens/compose.js` | 생성 | kind→위젯 조립, 미지원 표시 |
| `src/hmi/pilot/widgets/joint_jog.js` | 생성 | 관절 버튼 + 조이스틱 패드 위젯 |
| `src/hmi/pilot/screens/arm.js` | 수정 전체(193줄) | OMX 세션 컨텍스트로 재구성, 위젯 조립 |
| `src/hmi/pilot/app.js`, `screens/connect.js:210`, `screens/drive.js:29-39` | 수정 | capabilities→서술자→프로필, 미지원 표시 |
| `src/hmi/pilot/test/test_controls.py`, `test_arm_stick.py` | 생성 | Node 시험 |

### Part C — OMX 그리퍼

| 파일 | 상태 | 책임 |
|---|---|---|
| `src/contracts/foundation/core_common/protocol/omx_sim.py` | 수정 49-63 뒤 | `OmxSimGripperGoal` |
| `src/products/omx/adapter/omx_adapter/pilot_sim_gripper.py` | 생성 | 순수 `gripper_state()`, 상수 |
| `src/products/omx/adapter/omx_adapter/pilot_sim_runtime.py` | 수정 14-93 | 공통 `_dispatch`, `submit_gripper`, 스냅샷 `gripper`, `controls()` 그리퍼 |
| `src/products/omx/adapter/omx_adapter/pilot_sim_api.py` | 수정 152, 276-295 | `POST /gripper`, 영수증 공유 |
| `src/products/omx/adapter/omx_adapter/pilot_sim_server.py` | 수정 51-59, 80 | 그리퍼 한계·열림·닫힘을 `cell_profile.yaml`에서, 목표 길이 2.0 s |
| `src/products/omx/adapter/omx_adapter/pilot_sim_capture.py` | 수정 81-87 | 출처에 `gripper_joint` |
| `src/products/omx/adapter/omx_adapter/demonstration.py` | 수정 97-98, 191-194 | `action.gripper` 열, 목표 길이 0.1–2.0 |
| `src/products/omx/adapter/omx_adapter/lerobot_export.py` | 수정 20-59 | `action.gripper` 특성·프레임 |
| `src/hmi/pilot/widgets/gripper.js` | 생성 | 열기/반/닫기, 열림 % 슬라이더, 상태 배지 |
| 시험 | 생성/수정 | `test_pilot_sim_gripper.py`(생성), `test_pilot_sim_runtime.py`·`test_pilot_sim_api.py`·`test_demonstration.py`·`test_lerobot_export.py`·`test_pilot_sim_browser.py`·`test_omx_sim_pilot_contract.py`(추가) |

---

# Part A — 로봇 녹화와 HTTP 수신

끝 상태: 카메라 유닛 녹화 노드가 Pilot 요청으로 10분 한도 bag을 쓰고, CORE가 시작·정지·목록·tar를 내며, PC `rosy_ml fetch --http`가 받아 검증·변환·짝 확인하고, Pilot 주행 화면에 로봇 녹화 토글과 "녹화본" 시트가 있다. 호스트 시험 전부 통과.

### Task A1: 녹화 계약 `core_common.protocol.recording`

**Files:**
- Create: `src/contracts/foundation/core_common/protocol/recording.py`
- Test: `src/contracts/foundation/test/test_pilot_recording_contract.py`

- [ ] **Step 1: 실패하는 시험 쓰기**

```python
"""D-411 A: the recording wire contract shared by recorder, CORE and the PC tool."""

import pytest
from pydantic import ValidationError

from core_common.protocol import recording as rec


def test_constants_name_the_d411_paths_and_topics():
    assert rec.PILOT_RECORDING_ROOT == "/var/lib/rosy/pilot-recordings"
    assert rec.MAX_DURATION_S == 600
    assert rec.TELEOP_INTENT_TOPIC == "teleop/intent"
    assert rec.SET_ACTIVE_SERVICE == "pilot_recorder/set_active"
    assert rec.STATUS_TOPIC == "pilot_recorder/status"
    assert rec.ACTIVE_TOPIC == "pilot_recorder/active"
    assert rec.FETCHED_TOPIC == "pilot_recorder/fetched"


@pytest.mark.parametrize("value, ok", [
    ("20261002T101500Z_rosy_01", True),
    ("20261002T101500Z_rosy_01_2", True),
    ("../20261002T101500Z_x", False),
    ("20261002T101500Z_", False),
    ("20261002T101500Z_a/b", False),
    ("", False),
])
def test_recording_id_shape(value, ok):
    assert rec.recording_id_ok(value) is ok


@pytest.mark.parametrize("path, ok", [
    ("bag/bag_0.mcap", True),
    ("session.json", True),
    ("/etc/passwd", False),
    ("../x", False),
    ("bag/../../x", False),
    ("bag\\x", False),
    ("bag//x", False),
    ("./x", False),
    ("", False),
])
def test_safe_member_blocks_escape(path, ok):
    assert rec.safe_member(path) is ok


def test_teleop_intent_records_raw_clipped_and_decision():
    body = rec.teleop_intent(raw_linear=0.5, raw_angular=0.0, clipped=(0.15, 0.0), source="manual",
                             mode="MANUAL", accepted=True, code="", t_mono_ns=123)
    assert body == {"schema": "rosy.teleop.intent/1", "raw_linear": 0.5, "raw_angular": 0.0,
                    "linear": 0.15, "angular": 0.0, "source": "manual", "mode": "MANUAL",
                    "accepted": True, "code": "", "t_mono_ns": 123}


def test_teleop_intent_rejection_has_no_clipped_value_and_nan_becomes_null():
    body = rec.teleop_intent(raw_linear=float("nan"), raw_angular=0.1, clipped=None, source="manual",
                             mode="IDLE", accepted=False, code="MODE_CONFLICT", t_mono_ns=5)
    assert body["raw_linear"] is None and body["linear"] is None and body["angular"] is None
    assert body["accepted"] is False and body["code"] == "MODE_CONFLICT"


def test_accepted_intent_requires_clipped_values():
    with pytest.raises(ValidationError):
        rec.TeleopIntent(raw_linear=0.1, raw_angular=0.0, linear=None, angular=None, source="manual",
                         mode="MANUAL", accepted=True, code="", t_mono_ns=1)


def test_manifest_rejects_unsafe_and_duplicate_paths():
    good = {"schema": rec.MANIFEST_SCHEMA, "id": "20261002T101500Z_rosy_01",
            "started_at": "2026-10-02T10:15:00Z", "ended_at": "2026-10-02T10:16:00Z",
            "duration_s": 60.0, "topics": ["cmd_vel"], "stop_reason": "requested",
            "files": [{"path": "bag/bag_0.mcap", "bytes": 10, "sha256": "a" * 64}]}
    assert rec.RecordingManifest.model_validate(good).id == good["id"]
    for files in ([{"path": "../x", "bytes": 1, "sha256": "a" * 64}],
                  [good["files"][0], good["files"][0]]):
        with pytest.raises(ValidationError):
            rec.RecordingManifest.model_validate({**good, "files": files})


def test_recorder_status_round_trip():
    status = rec.RecorderStatus(state="recording", id="20261002T101500Z_rosy_01", elapsed_s=3.0,
                                bytes=1024, max_duration_s=600, quota_free_bytes=10)
    dumped = status.model_dump(by_alias=True)
    assert dumped["schema"] == rec.STATUS_SCHEMA
    assert rec.RecorderStatus.model_validate(dumped) == status
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/contracts/foundation/test/test_pilot_recording_contract.py -q`
Expected: FAIL — `ImportError: cannot import name 'recording' from 'core_common.protocol'`

- [ ] **Step 3: 구현** — `recording.py`:

```python
"""D-411 A: Pilot robot recording contract. ROS-free; shared by the camera-unit
recorder (control), CORE (core_common.domain, core_api_web) and the PC fetch tool.

Recording is evidence only: nothing on the control path reads these topics (D-2, D-209).
"""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PILOT_RECORDING_ROOT = "/var/lib/rosy/pilot-recordings"
MAX_DURATION_S = 600
TELEOP_INTENT_TOPIC = "teleop/intent"
SET_ACTIVE_SERVICE = "pilot_recorder/set_active"
STATUS_TOPIC = "pilot_recorder/status"
ACTIVE_TOPIC = "pilot_recorder/active"
FETCHED_TOPIC = "pilot_recorder/fetched"
INTENT_SCHEMA = "rosy.teleop.intent/1"
STATUS_SCHEMA = "rosy.pilot.recording.status/1"
MANIFEST_SCHEMA = "rosy.pilot.recording.manifest/1"
MANIFEST_NAME = "manifest.json"
SESSION_NAME = "session.json"
FETCHED_NAME = "fetched.json"
RECORDING_ID = re.compile(r"\d{8}T\d{6}Z_[A-Za-z0-9_.-]{1,64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def recording_id_ok(value: object) -> bool:
    return isinstance(value, str) and RECORDING_ID.fullmatch(value) is not None \
        and not value.endswith("_")


def safe_member(path: object) -> bool:
    """A manifest path that may become a tar member: relative POSIX, no '.', '..' or empty part."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path or path.startswith("/"):
        return False
    raw_parts = path.split("/")
    return all(part not in ("", ".", "..") for part in raw_parts) \
        and PurePosixPath(path).as_posix() == path


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


class TeleopIntent(_Wire):
    schema_id: Literal["rosy.teleop.intent/1"] = Field(INTENT_SCHEMA, alias="schema")
    raw_linear: float | None
    raw_angular: float | None
    linear: float | None
    angular: float | None
    source: str = Field(min_length=1, max_length=32)
    mode: str = Field(min_length=1, max_length=32)
    accepted: bool
    code: str = Field(max_length=64)
    t_mono_ns: int = Field(ge=0)

    @model_validator(mode="after")
    def clipped_iff_accepted(self) -> "TeleopIntent":
        has_clip = self.linear is not None and self.angular is not None
        if self.accepted != has_clip or (self.accepted and self.code):
            raise ValueError("an accepted intent carries clipped values and no code")
        return self


def teleop_intent(*, raw_linear, raw_angular, clipped, source, mode, accepted, code, t_mono_ns) -> dict:
    linear, angular = (None, None) if clipped is None else (_finite(clipped[0]), _finite(clipped[1]))
    return TeleopIntent(raw_linear=_finite(raw_linear), raw_angular=_finite(raw_angular),
                        linear=linear, angular=angular, source=source, mode=mode,
                        accepted=bool(accepted), code=code or "", t_mono_ns=int(t_mono_ns),
                        ).model_dump(by_alias=True)


class RecorderStatus(_Wire):
    schema_id: Literal["rosy.pilot.recording.status/1"] = Field(STATUS_SCHEMA, alias="schema")
    state: Literal["idle", "recording", "stopping", "error"]
    id: str | None = None
    elapsed_s: float = Field(ge=0)
    bytes: int = Field(ge=0)
    max_duration_s: int = Field(gt=0, le=MAX_DURATION_S)
    quota_free_bytes: int = Field(ge=0)
    last_stop_reason: str = Field("", max_length=64)

    @model_validator(mode="after")
    def id_when_active(self) -> "RecorderStatus":
        if self.state in ("recording", "stopping") and not recording_id_ok(self.id):
            raise ValueError("an active recording names its id")
        return self


class ManifestFile(_Wire):
    path: str
    bytes: int = Field(ge=0)
    sha256: str

    @field_validator("path")
    @classmethod
    def _safe(cls, value: str) -> str:
        if not safe_member(value) or value in (MANIFEST_NAME, FETCHED_NAME):
            raise ValueError("unsafe or reserved manifest path")
        return value

    @field_validator("sha256")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hex")
        return value


class RecordingManifest(_Wire):
    schema_id: Literal["rosy.pilot.recording.manifest/1"] = Field(MANIFEST_SCHEMA, alias="schema")
    id: str
    started_at: str
    ended_at: str
    duration_s: float = Field(ge=0)
    topics: tuple[str, ...]
    stop_reason: str = Field(max_length=64)
    files: tuple[ManifestFile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _identity(self) -> "RecordingManifest":
        if not recording_id_ok(self.id):
            raise ValueError("invalid recording id")
        paths = [item.path for item in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate manifest path")
        return self


class RecordingSummary(_Wire):
    id: str
    started_at: str
    ended_at: str | None
    duration_s: float | None
    bytes: int = Field(ge=0)
    topics: tuple[str, ...]
    status: Literal["recording", "complete", "incomplete"]
    manifest_sha256: str | None
    fetched: bool
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/contracts/foundation/test/test_pilot_recording_contract.py -q`
Expected: PASS (21 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/contracts/foundation/core_common/protocol/recording.py src/contracts/foundation/test/test_pilot_recording_contract.py
git commit -m "feat(core_common): D-411 pilot recording wire contract" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A2: 녹화 상태기계 `control/pilot_recording.py`

**Files:**
- Create: `src/runtime/sensing/control/pilot_recording.py`
- Test: `src/runtime/sensing/test/test_pilot_recorder.py`

규칙: 동시 녹화 1개, 최대 600 s(`MAX_DURATION_S`), 쿼터 기본 4 GiB. 정지는 **비차단**이다 — `stop()`은 SIGINT만 보내고 `stopping`이 되며, `tick()`(1 Hz)이 종료를 확인해 `finish_session` → `manifest.json`(파일별 sha256) 순으로 마감하고, 6 s 안에 끝나지 않으면 `kill()`한다(카메라 유닛 `TimeoutStopSec=10` 안). 쿼터는 **받아 간(`fetched.json`) 끝난 세션만** 오래된 순으로 지운다. 받지 않은 세션으로 쿼터가 차면 시작을 거부한다(`RECORDING_QUOTA_FULL`). `session.json`은 마감 뒤 바꾸지 않는다 — 받은 표시는 별도 파일이라 manifest 해시가 계속 맞다.

- [ ] **Step 1: 실패하는 시험 쓰기** (`test_recording.py:188-229`의 FakePopen 패턴)

```python
"""D-411 A: the Pilot recording state machine (ROS-free)."""

import json
import signal
from datetime import datetime, timedelta, timezone

import pytest

from control import pilot_recording as pr
from core_common.protocol.recording import MANIFEST_NAME, RecorderStatus, RecordingManifest


class Proc:
    def __init__(self):
        self.signals, self.killed, self.code = [], False, None

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True
        self.code = -9

    def poll(self):
        return self.code


class Rig:
    def __init__(self, tmp_path, **kwargs):
        self.t = 100.0
        self.wall = datetime(2026, 10, 2, 10, 15, tzinfo=timezone.utc)
        self.procs, self.cmds = [], []

        def popen(cmd, **_):
            self.cmds.append(cmd)
            proc = Proc()
            self.procs.append(proc)
            return proc

        self.rec = pr.PilotRecorder(tmp_path, device="rosy_01", namespace="rosy_01", popen=popen,
                                    clock=lambda: self.t, now=lambda: self.wall, **kwargs)

    def write_bag(self, folder, size=2048):
        bag = folder / "bag"
        bag.mkdir(exist_ok=True)
        (bag / "bag_0.mcap").write_bytes(b"x" * size)


def test_bag_command_records_the_d411_topics_namespaced():
    cmd = pr.pilot_bag_command("/r/s", "rosy_01")
    assert cmd[:3] == ["ros2", "bag", "record"]
    topics = cmd[cmd.index("--topics") + 1:]
    assert topics == ["/rosy_01/camera/front/compressed", "/rosy_01/cmd_vel", "/rosy_01/odom",
                      "/rosy_01/scan", "/rosy_01/line/observation", "/rosy_01/teleop/intent"]
    assert "camera/front" not in [t.rsplit("/rosy_01/", 1)[-1] for t in topics]


def test_start_stop_finish_writes_a_verifiable_manifest(tmp_path):
    rig = Rig(tmp_path)
    ok, rid = rig.rec.start()
    assert ok and rig.rec.status()["state"] == "recording" and rig.rec.status()["id"] == rid
    assert rig.rec.start() == (False, "RECORDING_BUSY")
    folder = tmp_path / rid
    rig.write_bag(folder)
    rig.t += 30
    assert rig.rec.stop("requested") == (True, rid)
    assert rig.procs[0].signals == [signal.SIGINT]
    assert rig.rec.status()["state"] == "stopping"
    rig.procs[0].code = 0
    assert rig.rec.tick() == "requested"
    status = RecorderStatus.model_validate(rig.rec.status())
    assert status.state == "idle" and status.last_stop_reason == "requested"
    manifest = RecordingManifest.model_validate_json((folder / MANIFEST_NAME).read_text("utf-8"))
    assert {f.path for f in manifest.files} == {"bag/bag_0.mcap", "session.json"}
    assert manifest.duration_s == pytest.approx(30.0)
    assert json.loads((folder / "session.json").read_text("utf-8"))["ended_at"] is not None


def test_max_duration_stops_by_itself(tmp_path):
    rig = Rig(tmp_path)
    rig.rec.start()
    rig.t += 600
    assert rig.rec.tick() is None
    assert rig.procs[0].signals == [signal.SIGINT]
    rig.procs[0].code = 0
    assert rig.rec.tick() == "max_duration"


def test_recorder_exit_is_finished_as_incomplete_reason(tmp_path):
    rig = Rig(tmp_path)
    rig.rec.start()
    rig.procs[0].code = 1
    assert rig.rec.tick() == "recorder_exit"
    assert rig.rec.status()["state"] == "idle"


def test_stuck_recorder_is_killed_after_the_stop_timeout(tmp_path):
    rig = Rig(tmp_path)
    rig.rec.start()
    rig.rec.stop("requested")
    rig.t += pr.STOP_TIMEOUT_S + 0.1
    rig.rec.tick()
    assert rig.procs[0].killed


def test_quota_evicts_only_fetched_finished_sessions(tmp_path):
    rig = Rig(tmp_path, quota_bytes=3000)
    _, first = rig.rec.start()
    rig.write_bag(tmp_path / first, 2500)
    rig.rec.stop("requested"); rig.procs[0].code = 0; rig.rec.tick()
    rig.wall += timedelta(minutes=1)
    assert rig.rec.start() == (False, "RECORDING_QUOTA_FULL")
    assert rig.rec.mark_fetched(first) is True
    ok, second = rig.rec.start()
    assert ok and not (tmp_path / first).exists() and second != first


def test_mark_fetched_refuses_unknown_or_unsafe_ids(tmp_path):
    rig = Rig(tmp_path)
    assert rig.rec.mark_fetched("../etc") is False
    assert rig.rec.mark_fetched("20261002T101500Z_nothere") is False


def test_recover_finishes_an_interrupted_session(tmp_path):
    rig = Rig(tmp_path)
    _, rid = rig.rec.start()
    rig.write_bag(tmp_path / rid)
    again = Rig(tmp_path)          # a restart: the old process is gone
    again.rec.recover()
    manifest = RecordingManifest.model_validate_json((tmp_path / rid / MANIFEST_NAME).read_text("utf-8"))
    assert manifest.stop_reason == "recovered"


def test_status_is_idle_with_quota_when_nothing_runs(tmp_path):
    status = RecorderStatus.model_validate(Rig(tmp_path).rec.status())
    assert status.state == "idle" and status.max_duration_s == 600 and status.quota_free_bytes > 0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/sensing/test/test_pilot_recorder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'control.pilot_recording'`

- [ ] **Step 3: 구현** — `pilot_recording.py` 핵심(전체 약 200줄):

```python
"""D-411 A: the Pilot recording session. ROS-free; pilot_recorder_node is a thin wrapper.

One session at a time, at most MAX_DURATION_S, a dedicated quota. Stopping never blocks a
ROS callback: stop() sends SIGINT, tick() finishes the session once rosbag2 has exited.
Only fetched (fetched.json) finished sessions are ever evicted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from core_common.protocol.recording import (
    FETCHED_NAME, MANIFEST_NAME, MANIFEST_SCHEMA, MAX_DURATION_S, SESSION_NAME, STATUS_SCHEMA,
    TELEOP_INTENT_TOPIC, recording_id_ok)
from control.recording import (
    COMPRESSED_CAMERA_TOPIC, ODOM_TOPIC, SCAN_TOPIC, _iso, _ns_topics, _read_meta, _sessions,
    _total_bytes, finish_session, new_session)

PILOT_TOPICS = (COMPRESSED_CAMERA_TOPIC, "cmd_vel", ODOM_TOPIC, SCAN_TOPIC, "line/observation",
                TELEOP_INTENT_TOPIC)
DEFAULT_QUOTA_BYTES = 4 * 1024 ** 3
STOP_TIMEOUT_S = 6.0
_HASH_CHUNK = 1 << 20


def pilot_bag_command(folder, namespace: str = "") -> list[str]:
    return ["ros2", "bag", "record", "--storage", "mcap",
            "--storage-preset-profile", "zstd_fast", "--max-bag-duration", "30",
            "-o", str(Path(folder) / "bag"), "--topics", *_ns_topics(PILOT_TOPICS, namespace)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(folder: Path, *, stop_reason: str, duration_s: float) -> Path:
    meta = _read_meta(folder)
    files = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(folder).as_posix()
        if rel in (MANIFEST_NAME, FETCHED_NAME) or rel.endswith(".tmp") or rel.startswith("."):
            continue
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    body = {"schema": MANIFEST_SCHEMA, "id": folder.name, "started_at": meta["started_at"],
            "ended_at": meta["ended_at"], "duration_s": round(duration_s, 3),
            "topics": list(meta.get("topics", ())), "stop_reason": stop_reason, "files": files}
    tmp = folder / (MANIFEST_NAME + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(body, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, folder / MANIFEST_NAME)
    return folder / MANIFEST_NAME


class PilotRecorder:
    def __init__(self, root, *, device: str, namespace: str = "",
                 quota_bytes: int = DEFAULT_QUOTA_BYTES, max_duration_s: int = MAX_DURATION_S,
                 popen=subprocess.Popen, clock=time.monotonic,
                 now=lambda: datetime.now(timezone.utc)) -> None: ...
    def start(self) -> tuple[bool, str]: ...          # (True, id) | (False, code)
    def stop(self, reason: str) -> tuple[bool, str]:  # (True, id) | (False, "RECORDING_NOT_ACTIVE")
    def tick(self) -> str | None: ...                 # the stop reason when a session just finished
    def status(self) -> dict: ...                     # RecorderStatus.model_dump(by_alias=True) shape
    def recover(self) -> list[str]: ...               # finish sessions left open by a crash
    def mark_fetched(self, recording_id: str) -> bool: ...
    def shutdown(self) -> None: ...                   # stop("shutdown"), wait STOP_TIMEOUT_S, finish
```

메서드 규칙(구현자가 그대로 따른다):
- `start()`: 진행 중이면 `(False, "RECORDING_BUSY")`. `_evict()` 뒤 `_total_bytes(root) >= quota`면 `(False, "RECORDING_QUOTA_FULL")`. `new_session(root, device=..., camera_profile_revision="", model_revision="", task_id=None, reason="pilot", now=now(), topics=PILOT_TOPICS, extra={"mode": "pilot"})` → `popen(pilot_bag_command(folder, ns), stdin=subprocess.DEVNULL, start_new_session=True)`. `popen`이 예외면 `finish_session` 후 `(False, "RECORDER_UNAVAILABLE")`.
- `stop(reason)`: 활성 아니면 `(False, "RECORDING_NOT_ACTIVE")`; 이미 `stopping`이면 `(True, id)`; 아니면 `proc.send_signal(signal.SIGINT)`, `_stopping_since = clock()`, 사유 저장.
- `tick()`: 활성일 때 — `proc.poll()`이 None이 아니면 마감(사유: `stopping`이면 저장한 사유, 아니면 `"recorder_exit"`). `recording` 상태에서 `clock()-started >= max_duration_s`면 `stop("max_duration")`; `_total_bytes(root) >= quota`면 `stop("quota")`. `stopping` 상태에서 `STOP_TIMEOUT_S`가 지나면 `kill()`. 마감 = `finish_session(folder, now())` → `write_manifest(folder, stop_reason=..., duration_s=clock()-started)` → 상태 idle, `last_stop_reason` 저장, 반환값은 사유.
- `status()`: `{"schema": STATUS_SCHEMA, "state", "id", "elapsed_s", "bytes"(활성 세션 폴더 합), "max_duration_s", "quota_free_bytes": max(0, quota-_total_bytes(root)), "last_stop_reason"}`.
- `_evict()`: `_sessions(root)` 중 `meta.get("mode") == "pilot"`, `ended_at` 있음, `(folder/FETCHED_NAME).is_file()`인 것을 오래된 순으로 `shutil.rmtree`, 합계가 쿼터 아래가 될 때까지.
- `recover()`: `mode == "pilot"`이고 `ended_at is None`인 세션 → `finish_session` + `write_manifest(stop_reason="recovered", duration_s=0.0)`.
- `mark_fetched(rid)`: `recording_id_ok(rid)`이고 `root/rid/MANIFEST_NAME`이 있으면 `fetched.json`(`{"fetched_at": _iso(now())}`)을 원자적으로 쓰고 True, 아니면 False. 진행 중 세션 id면 False.

`_iso`, `_read_meta`, `_sessions`, `_total_bytes`, `_ns_topics`는 같은 패키지의 기존 비공개 함수다(`recording.py:93-195`). 이름 앞 밑줄을 유지한 채 import한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/sensing/test/test_pilot_recorder.py src/runtime/sensing/test/test_recording.py src/runtime/sensing/test/test_recording_snapshot.py -q`
Expected: PASS (새 9개 + 기존 그대로)

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/sensing/control/pilot_recording.py src/runtime/sensing/test/test_pilot_recorder.py
git commit -m "feat(control): D-411 pilot recording state machine (10 min, quota, manifest)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A3: 녹화 노드, 압축 카메라 온디맨드, launch

**Files:**
- Create: `src/runtime/sensing/control/pilot_recorder_node.py`
- Modify: `src/runtime/sensing/control/camera_detect_node.py:128-142` (구독·생성), `:486-497` (발행 경로)
- Modify: `src/runtime/sensing/launch/camera_preview.launch.py:76-78` (인자), `:105-125` 뒤 (노드)
- Modify: `src/runtime/sensing/setup.py:50-52` (entry point)
- Modify: `src/runtime/sensing/test/test_camera_preview_launch.py:107` (`BASE`)
- Test: `src/runtime/sensing/test/test_pilot_recorder_node.py`

`publish_compressed`는 시동 때 한 번 읽힌다(`camera_detect_node.py:137-142`). 녹화 중에만 압축 토픽을 내기 위해 카메라 노드가 래치된 `pilot_recorder/active`(Bool)를 구독하고, 참이면 발행자를 (처음 한 번) 만들어 쓰고 거짓이면 발행을 멈춘다. 발행자는 지우지 않는다(다중 스레드 실행기에서 발행 중 파괴를 피한다) — 대기 중엔 메시지가 없다. `test_os_camera_graph.py:45`("파라미터 false면 토픽 없음")는 녹화가 한 번도 켜지지 않은 시동 상태라 그대로 참이다.

- [ ] **Step 1: 실패하는 시험 쓰기**

```python
"""D-411 A: pilot_recorder_node stays thin; the camera publishes JPEG only while recording."""

from pathlib import Path

from core_common.protocol import recording as rec

CONTROL = Path(__file__).resolve().parents[1] / "control"
LAUNCH = Path(__file__).resolve().parents[1] / "launch" / "camera_preview.launch.py"
SETUP = Path(__file__).resolve().parents[1] / "setup.py"


def _src(name):
    return (CONTROL / name).read_text(encoding="utf-8")


def test_node_wraps_the_ros_free_recorder_and_never_drives():
    src = _src("pilot_recorder_node.py")
    assert "from .pilot_recording import PilotRecorder" in src
    assert "create_service(SetBool, SET_ACTIVE_SERVICE, self._on_set_active)" in src
    assert "create_subscription(String, FETCHED_TOPIC, self._on_fetched, 5)" in src
    assert "create_publisher(String, STATUS_TOPIC, _LATCHED)" in src
    assert "create_publisher(Bool, ACTIVE_TOPIC, _LATCHED)" in src
    assert "create_timer(1.0, self._tick)" in src
    assert "self._recorder.recover()" in src
    assert "cmd_vel" not in src and "Twist" not in src
    assert "subprocess" not in src  # the process belongs to PilotRecorder


def test_node_main_matches_the_capture_trigger_shape():
    src = _src("pilot_recorder_node.py")
    assert "executor_choice.spin(node, rclpy)" in src
    assert "node.destroy_node()" in src and "rclpy.shutdown()" in src


def test_camera_publishes_compressed_only_while_the_recorder_is_active():
    src = _src("camera_detect_node.py")
    assert "create_subscription(Bool, ACTIVE_TOPIC, self._on_recorder_active, _RECORDER_QOS)" in src
    assert "self._recorder_active" in src
    assert "def _compressed_publisher(self)" in src
    assert "destroy_publisher" not in src


def test_launch_starts_the_recorder_with_the_d411_root():
    src = LAUNCH.read_text(encoding="utf-8")
    assert "executable='pilot_recorder_node'" in src
    assert f"'{rec.PILOT_RECORDING_ROOT}'" in src
    assert "'recording_root': pilot_recording_root" in src


def test_entry_point_is_installed():
    assert "pilot_recorder_node = control.pilot_recorder_node:main" in SETUP.read_text(encoding="utf-8")
```

그리고 `test_camera_preview_launch.py:107`의 기대값을 바꾼다:

```python
BASE = ["camera_detect_node", "line_observer_node", "road_observer_node", "pilot_recorder_node"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/sensing/test/test_pilot_recorder_node.py src/runtime/sensing/test/test_camera_preview_launch.py -q`
Expected: FAIL — `FileNotFoundError: ...pilot_recorder_node.py` 및 `_started({}) == BASE` 불일치(launch 시험은 `launch_ros` 없으면 skip)

- [ ] **Step 3: 구현**

`pilot_recorder_node.py`:

```python
#!/usr/bin/env python3
"""D-411 A: Pilot recording, owned by the camera unit. CORE only asks (SetBool).

Thin wrapper over control.pilot_recording.PilotRecorder. Evidence only: publishes no
command topic. The latched status feeds CORE; the latched active flag turns the camera's
JPEG copy on only while a session runs.
"""
import json
import socket

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String
from std_srvs.srv import SetBool

from core_common.protocol.recording import (
    ACTIVE_TOPIC, FETCHED_TOPIC, PILOT_RECORDING_ROOT, SET_ACTIVE_SERVICE, STATUS_TOPIC)
from . import executor_choice
from .pilot_recording import DEFAULT_QUOTA_BYTES, PilotRecorder

_LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)


class PilotRecorderNode(Node):
    def __init__(self):
        super().__init__('pilot_recorder_node')
        self.declare_parameter('recording_root', PILOT_RECORDING_ROOT)
        self.declare_parameter('quota_gib', DEFAULT_QUOTA_BYTES / 1024 ** 3)
        namespace = self.get_namespace().strip('/')
        self._recorder = PilotRecorder(
            self.get_parameter('recording_root').value,
            device=namespace or socket.gethostname(), namespace=namespace,
            quota_bytes=int(float(self.get_parameter('quota_gib').value) * 1024 ** 3))
        self._recorder.recover()
        self._status_pub = self.create_publisher(String, STATUS_TOPIC, _LATCHED)
        self._active_pub = self.create_publisher(Bool, ACTIVE_TOPIC, _LATCHED)
        self.create_service(SetBool, SET_ACTIVE_SERVICE, self._on_set_active)
        self.create_subscription(String, FETCHED_TOPIC, self._on_fetched, 5)
        self.create_timer(1.0, self._tick)
        self._publish()

    def _on_set_active(self, request, response):
        ok, detail = self._recorder.start() if request.data else self._recorder.stop('requested')
        response.success = ok
        response.message = json.dumps({'code': '' if ok else detail, 'status': self._recorder.status()})
        self._publish()
        return response

    def _on_fetched(self, msg):
        try:
            recording_id = str(json.loads(msg.data).get('id', ''))
        except (ValueError, AttributeError):
            self.get_logger().warn('fetched notice ignored: not JSON')
            return
        if not self._recorder.mark_fetched(recording_id):
            self.get_logger().warn(f'fetched notice for unknown recording {recording_id!r}')

    def _tick(self):
        reason = self._recorder.tick()
        if reason:
            self.get_logger().info(f'pilot recording finished: {reason}')
        self._publish()

    def _publish(self):
        status = self._recorder.status()
        self._status_pub.publish(String(data=json.dumps(status)))
        self._active_pub.publish(Bool(data=status['state'] in ('recording', 'stopping')))

    def destroy_node(self):
        self._recorder.shutdown()
        super().destroy_node()


def main():
    rclpy.init()
    node = PilotRecorderNode()
    try:
        executor_choice.spin(node, rclpy)
    finally:
        node.destroy_node()
        rclpy.shutdown()
```

`main()`은 `capture_trigger_node.py:128-138`과 같은 모양으로 맞춘다(그 파일을 열어 줄 단위로 대조).

`camera_detect_node.py` — import에 `from core_common.protocol.recording import ACTIVE_TOPIC`, 모듈 상수 `_RECORDER_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)`. `:137-142` 블록을 바꾼다:

```python
        self._publish_compressed = bool(self.get_parameter('publish_compressed').value)
        self._recorder_active = False
        self.jpeg_pub = None
        if self._publish_compressed:
            self._compressed_publisher()
        # D-411: the Pilot recorder needs the JPEG copy only while it records.
        self.create_subscription(Bool, ACTIVE_TOPIC, self._on_recorder_active, _RECORDER_QOS)
```

메서드 두 개 추가:

```python
    def _compressed_publisher(self):
        if self._jpeg_pub_created is None:
            # Best effort, depth 1 (D-185): only the latest frame matters.
            self._jpeg_pub_created = self.create_publisher(
                CompressedImage, 'camera/front/compressed',
                QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
            self.get_logger().info(f'camera/front/compressed on (quality {self._jpeg_quality})')
        return self._jpeg_pub_created

    def _on_recorder_active(self, msg):
        self._recorder_active = bool(msg.data)
        wanted = self._publish_compressed or self._recorder_active
        self.jpeg_pub = self._compressed_publisher() if wanted else None
```

(`self._jpeg_pub_created = None`을 `self.jpeg_pub = None` 바로 위에 둔다.) `:486`의 `if self.jpeg_pub is not None:`은 `pub = self.jpeg_pub` 지역 변수를 먼저 읽고 `if pub is not None:` … `pub.publish(jpeg)`로 바꾼다(한 번 읽어 경쟁 없이 쓴다).

`camera_preview.launch.py` — `:77-78` 뒤에 인자:

```python
        DeclareLaunchArgument('pilot_recording_root', default_value='/var/lib/rosy/pilot-recordings'),
```

`pilot_recording_root = LaunchConfiguration('pilot_recording_root')`를 다른 `LaunchConfiguration` 옆에 두고, `road_observer_node` 뒤에 상시 노드:

```python
        # D-411 A: Pilot recording, idle until CORE asks; evidence only (no command topic).
        Node(package='control', executable='pilot_recorder_node', name='pilot_recorder_node',
             namespace=namespace, output='screen',
             parameters=[{'recording_root': pilot_recording_root}]),
```

`setup.py:52` 뒤: `'pilot_recorder_node = control.pilot_recorder_node:main',`.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/sensing/test/test_pilot_recorder_node.py src/runtime/sensing/test/test_camera_preview_launch.py src/runtime/sensing/test/test_capture_trigger.py -q`
Expected: PASS (launch 시험은 `launch_ros`가 없으면 기존처럼 skip)

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/sensing/control/pilot_recorder_node.py src/runtime/sensing/control/camera_detect_node.py src/runtime/sensing/launch/camera_preview.launch.py src/runtime/sensing/setup.py src/runtime/sensing/test/test_pilot_recorder_node.py src/runtime/sensing/test/test_camera_preview_launch.py
git commit -m "feat(control): D-411 pilot_recorder_node and on-demand compressed camera" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A4: 저장 디렉터리와 유닛 권한

**Files:**
- Modify: `deploy/robot/pinky_pro/native/tmpfiles-rosy-state.conf:12` 뒤
- Modify: `deploy/robot/pinky_pro/image/customize-rootfs.sh:367` 뒤
- Modify: `deploy/robot/pinky_pro/native/rosy-camera.service:17` 뒤
- Modify: `deploy/robot/pinky_pro/native/rosy-core.service:76` 뒤
- Test: `test/test_native_systemd_contract.py:364-368, 407-418, 466-470, 698-717, 916`

- [ ] **Step 1: 실패하는 시험 쓰기** — `test_native_systemd_contract.py` 수정:
  - `DECLARED_WRITES["rosy-camera.service"]`(364-368)에 `# D-411: the Pilot recorder (pilot_recorder_node), setgid rosy-core.` + `"/var/lib/rosy/pilot-recordings",`
  - `DECLARED_READS["rosy-core.service"]`(407-418)에 `# D-411: lists and streams Pilot recordings; ReadOnlyPaths. CORE never writes there.` + `"/var/lib/rosy/pilot-recordings",`
  - `PROGRAM_SOURCES["rosy-camera.service"]`(466-470)에 `"src/runtime/sensing/control/pilot_recorder_node.py", "src/runtime/sensing/control/pilot_recording.py",`
  - `test_state_rules_keep_the_parent_and_root_only_state_with_root`(698-717) 끝에:

```python
    # D-411: Pilot recordings — the camera unit writes, CORE reads through the setgid group.
    assert "d /var/lib/rosy/pilot-recordings 2750 rosy-camera rosy-core -" in rules
    assert "install -d -m 2750 -o rosy-camera -g rosy-core /var/lib/rosy/pilot-recordings" in customizer
    assert customizer.index("useradd --uid 963") < customizer.index("-o rosy-camera -g rosy-core")
```

  - `test_camera_reads_the_optional_learned_perception_switch_file`의 916줄 `assert "ReadWritePaths" not in directives`를 바꾼다:

```python
    # The switch opens no write path of its own; D-411's recorder owns exactly one.
    assert directives["ReadWritePaths"] == ["/var/lib/rosy/pilot-recordings"]
```

  - 새 시험 하나:

```python
def test_core_reads_pilot_recordings_read_only():
    directives = _directives("rosy-core.service")
    assert "/var/lib/rosy/pilot-recordings" in _words(directives, "ReadOnlyPaths")
    assert all("pilot-recordings" not in path for path, _optional in _writable(directives))
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest test/test_native_systemd_contract.py -q`
Expected: FAIL — `KeyError: 'ReadWritePaths'`, tmpfiles·customizer 단언 실패, 그리고 `test_declared_paths_account_for_every_write_root_in_the_program`이 launch의 새 경로 리터럴로 이미 실패하던 것이 선언으로 해소되는지 확인 대상

- [ ] **Step 3: 구현**

`tmpfiles-rosy-state.conf` models 줄(12) 뒤:

```
# D-411: Pilot recordings. rosy-camera's pilot_recorder_node writes them; the setgid
# group lets CORE (Group=rosy-core, ReadOnlyPaths) list and stream them under UMask=0027.
d /var/lib/rosy/pilot-recordings 2750 rosy-camera rosy-core -
```

`customize-rootfs.sh:367` 뒤:

```bash
chroot "$ROOT" install -d -m 2750 -o rosy-camera -g rosy-core /var/lib/rosy/pilot-recordings  # D-411
```

`rosy-camera.service:17`(`StateDirectoryMode=0750`) 뒤: `ReadWritePaths=/var/lib/rosy/pilot-recordings`
`rosy-core.service:76`(`ReadWritePaths=/run/rosy`) 뒤: `ReadOnlyPaths=/var/lib/rosy/pilot-recordings`

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest test/test_native_systemd_contract.py test/test_camera_image_stack.py test/test_learned_perception_pinky_runbook.py test/test_bench_learned_perception.py test/test_image_layer_sync.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add deploy/robot/pinky_pro/native/tmpfiles-rosy-state.conf deploy/robot/pinky_pro/image/customize-rootfs.sh deploy/robot/pinky_pro/native/rosy-camera.service deploy/robot/pinky_pro/native/rosy-core.service test/test_native_systemd_contract.py
git commit -m "feat(deploy): D-411 pilot-recordings dir, camera RW and CORE RO paths" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A5: `teleop/intent` 증거

**Files:**
- Modify: `src/runtime/services/core_features/command/manager.py:72-73` (필드), `:87-114` (분리)
- Modify: `src/runtime/api_web/core_api_web/api/v1/control.py:1-12` (import), `:35-45`
- Modify: `src/runtime/gateway/core/bridge/ros_bridge.py:63` 부근 (import), `:144` 뒤 (발행자), `:237` 뒤 (싱크)
- Modify: `src/runtime/gateway/test/test_bridge_timers.py:246-257`
- Modify: `tools/harness/harness.yaml:122-126` (core_features `tests:`에 새 시험)
- Test: `src/runtime/services/test/test_teleop_intent.py`, `src/runtime/gateway/test/test_recordings_api.py`(이 태스크에서 intent 시험 하나로 생성)

- [ ] **Step 1: 실패하는 시험 쓰기**

`src/runtime/services/test/test_teleop_intent.py`:

```python
"""D-411 A: every teleop decision is evidence; evidence never refuses a command."""

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


def _rig(mode=Mode.MANUAL):
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety)
    modes.transition(mode)
    seen = []
    command.intent_sink = lambda **fields: seen.append(fields)
    return command, seen


def test_accepted_teleop_records_raw_and_clipped():
    command, seen = _rig()
    assert command.teleop(0.5, 0.0) == (True, "")
    (intent,) = seen
    assert intent["raw_linear"] == 0.5 and intent["clipped"] == (0.15, 0.0)
    assert intent["accepted"] is True and intent["code"] == "" and intent["mode"] == "MANUAL"
    assert intent["source"] == "manual" and intent["t_mono_ns"] > 0


def test_rejected_teleop_records_the_code_without_clipped_values():
    command, seen = _rig(Mode.IDLE)
    assert command.teleop(0.1, 0.0) == (False, "MODE_CONFLICT")
    assert seen[0]["accepted"] is False and seen[0]["code"] == "MODE_CONFLICT"
    assert seen[0]["clipped"] is None and seen[0]["mode"] == "IDLE"


def test_a_failing_sink_never_refuses_the_command():
    command, _ = _rig()

    def boom(**_):
        raise RuntimeError("publisher gone")

    command.intent_sink = boom
    assert command.teleop(0.1, 0.0) == (True, "")
    assert command.intent_errors == 1
    assert command.select_output().linear > 0


def test_no_sink_is_inert():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety)
    modes.transition(Mode.MANUAL)
    assert command.teleop(0.1, 0.0) == (True, "")


def test_note_intent_covers_rejections_before_the_manager():
    command, seen = _rig()
    command.note_intent(0.2, 0.0, "manual", False, "CAPABILITY_WITHHELD")
    assert seen[0]["code"] == "CAPABILITY_WITHHELD" and seen[0]["clipped"] is None
```

`src/runtime/gateway/test/test_recordings_api.py`(생성, 이 태스크 분량):

```python
"""D-411 A: CORE recording control, download gate and teleop intent evidence."""

import pytest

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}


def test_teleop_rejected_before_the_manager_is_still_evidence(core_client):
    client, svc = core_client()
    seen = []
    svc.command.intent_sink = lambda **fields: seen.append(fields)
    svc.capability._data["teleop"] = False
    response = client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR)
    assert response.status_code == 501
    assert seen and seen[0]["accepted"] is False and seen[0]["code"] == "CAPABILITY_NOT_SUPPORTED"
```

`test_bridge_timers.py` `EXPECTED_PUBLISHERS`(246-257) 끝에 `("teleop/intent", 10),` (주석 `# D-411 A: teleop decisions as evidence for the Pilot recorder.`).

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/services/test/test_teleop_intent.py src/runtime/gateway/test/test_recordings_api.py src/runtime/gateway/test/test_bridge_timers.py -q`
Expected: FAIL — `AttributeError: 'CommandManager' object has no attribute 'intent_errors'`; 브리지 발행자 목록 불일치

- [ ] **Step 3: 구현**

`manager.py` — `:72` (`self.announce_errors = 0`) 뒤:

```python
        #: D-411: evidence hook for every teleop decision (rosy.teleop.intent/1).
        #: Set by the ROS bridge. It can never refuse or delay a command.
        self.intent_sink = None
        self.intent_errors = 0
```

`:87`의 `def teleop(...)`을 `def _teleop_decision(self, linear: float, angular: float, source: str) -> tuple[bool, str]:`로 이름만 바꾸고(본문 그대로), 그 위에:

```python
    def teleop(self, linear: float, angular: float, source: str = "manual") -> tuple[bool, str]:
        accepted, code = self._teleop_decision(linear, angular, source)
        held = self._manual_twist if accepted else None
        self.note_intent(linear, angular, source, accepted, code,
                         clipped=None if held is None else (held.linear, held.angular))
        return accepted, code

    def note_intent(self, linear: float, angular: float, source: str, accepted: bool, code: str,
                    clipped: Optional[tuple[float, float]] = None) -> None:
        """D-411: what the operator asked for and what CORE decided. Evidence only."""
        if self.intent_sink is None:
            return
        try:
            self.intent_sink(raw_linear=linear, raw_angular=angular, clipped=clipped, source=source,
                             mode=self._modes.mode.value, accepted=accepted, code=code,
                             t_mono_ns=time.monotonic_ns())
        except Exception:  # noqa: BLE001 - evidence must never refuse a command
            self.intent_errors += 1
```

`control.py` — import에 `from core_common.capability import CapabilityError`. `:35-45`:

```python
@control_router.post("/teleop")
def teleop(body: TeleopRequest, auth: AuthContext = Depends(operator),
           svc: CoreServicesLike = Depends(get_services)):
    try:
        TaskKind.MOVE.require(svc.capability)
        require_calibration_owner(svc, auth, "teleop")
        require_kept(svc, "teleop")
    except (ApiError, CapabilityError) as exc:
        # D-411: a refusal before the manager is still an operator intent.
        code = exc.code if isinstance(exc, ApiError) else "CAPABILITY_NOT_SUPPORTED"
        svc.command.note_intent(body.linear, body.angular, "manual", False, code)
        raise
    accepted, code = svc.command.teleop(body.linear, body.angular, source="manual")
    if not accepted:
        raise ApiError(code, 409 if code in ("MODE_CONFLICT", "EMERGENCY_ACTIVE") else 400,
                       f"teleop rejected: {code}")
    return {"accepted": True}
```

`ros_bridge.py` — import 블록(`:63` 부근)에 `from core_common.protocol.recording import TELEOP_INTENT_TOPIC, teleop_intent`. `:144`(`loc_mission_pub`) 뒤:

```python
        # D-411 A: teleop decisions as evidence for the Pilot recorder (never read by control).
        self.intent_pub = node.create_publisher(String, TELEOP_INTENT_TOPIC, 10)
```

`:237` (`loc_mission.publish = ...`) 뒤:

```python
        self._svc.command.intent_sink = lambda **fields: self.intent_pub.publish(
            String(data=json.dumps(teleop_intent(**fields))))
```

`harness.yaml`의 `core_features` `tests:`에 `src/runtime/services/test/test_teleop_intent.py` 추가.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/services/test/test_teleop_intent.py src/runtime/services/test/test_command_shadow.py src/runtime/gateway/test/test_recordings_api.py src/runtime/gateway/test/test_bridge_timers.py src/runtime/gateway/test/test_api.py src/runtime/gateway/test/test_teleop_watchdog_event.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/services/core_features/command/manager.py src/runtime/api_web/core_api_web/api/v1/control.py src/runtime/gateway/core/bridge/ros_bridge.py src/runtime/services/test/test_teleop_intent.py src/runtime/gateway/test/test_recordings_api.py src/runtime/gateway/test/test_bridge_timers.py tools/harness/harness.yaml
git commit -m "feat(core): D-411 teleop/intent evidence for accepted and rejected teleop" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A6: CORE 가드와 녹화 저장소 읽기

**Files:**
- Create: `src/contracts/foundation/core_common/domain/pilot_recording.py`
- Create: `src/contracts/foundation/core_common/domain/pilot_recording_store.py`
- Test: `src/contracts/foundation/test/test_pilot_recording_guard.py`, `src/contracts/foundation/test/test_pilot_recording_store.py`

CORE에는 Pilot seat가 없다(seat는 OMX SIM에만 있다). 그래서 D-411 §3의 "연결 끊김·seat 변경"을 CORE가 가진 사실로 정한다: **연결** = 녹화를 시작한 토큰의 열린 `/ws/state` 소켓 수(Pilot `link.js`가 그 토큰으로 연다). 0인 상태가 `LINK_GRACE_S`(5 s, `link.js` 재연결 백오프 1 s를 덮는다) 이어지면 정지. **seat 변경** = 다른 토큰의 teleop이 수락됨. 토큰 회수·만료는 `_watch_token`이 소켓을 4401로 닫으므로 연결 끊김으로 잡힌다. 판정은 상태 토픽 수신(녹화 중 1 Hz)마다 한다 — 브리지 타이머를 늘리지 않는다. 가드가 내는 정지는 **비차단**(`wait=False`) 요청이다: 실행기 콜백 스레드에서 서비스 응답을 기다리면 교착한다.

- [ ] **Step 1: 실패하는 시험 쓰기**

`test_pilot_recording_guard.py`:

```python
"""D-411 A: CORE's recording guard — owner, link loss, seat change, stale recorder."""

import json

import pytest

from core_common.domain.pilot_recording import LINK_GRACE_S, PilotRecordingGuard, RecordingRefused

RID = "20261002T101500Z_rosy_01"


def status(state="recording", rid=RID, reason=""):
    return {"schema": "rosy.pilot.recording.status/1", "state": state,
            "id": rid if state in ("recording", "stopping") else None, "elapsed_s": 1.0,
            "bytes": 10, "max_duration_s": 600, "quota_free_bytes": 100, "last_stop_reason": reason}


class Events:
    def __init__(self):
        self.published = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, data))


@pytest.fixture
def rig():
    t = [0.0]
    events = Events()
    guard = PilotRecordingGuard(events=events, clock=lambda: t[0])
    calls = []

    def request(on, wait):
        calls.append((on, wait))
        return True, json.dumps({"code": "", "status": status("recording" if on else "stopping")})

    guard.request_active = request
    guard.on_status(status("idle"))
    return guard, calls, events, t


def test_start_records_the_owner_and_announces(rig):
    guard, calls, events, _ = rig
    body = guard.start("tok-a")
    assert body["state"] == "recording" and calls == [(True, True)]
    assert guard.owner() == "tok-a" and guard.active()
    assert events.published[-1] == ("recording.started", {"id": RID, "owner": "tok-a"})


def test_second_start_is_busy(rig):
    guard, *_ = rig
    guard.start("tok-a")
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-b")
    assert (refused.value.code, refused.value.status) == ("RECORDING_BUSY", 409)


def test_stale_or_unwired_recorder_is_unavailable(rig):
    guard, _, _, t = rig
    t[0] = 10.0
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-a")
    assert refused.value.code == "RECORDER_UNAVAILABLE" and refused.value.status == 503


def test_recorder_refusal_maps_quota(rig):
    guard, *_ = rig
    guard.request_active = lambda on, wait: (False, '{"code": "RECORDING_QUOTA_FULL", "status": {}}')
    with pytest.raises(RecordingRefused) as refused:
        guard.start("tok-a")
    assert (refused.value.code, refused.value.status) == ("RECORDING_QUOTA_FULL", 507)


def test_only_owner_or_admin_stops(rig):
    guard, calls, events, _ = rig
    guard.start("tok-a")
    with pytest.raises(RecordingRefused) as refused:
        guard.stop("tok-b", is_admin=False)
    assert refused.value.status == 403
    guard.stop("tok-b", is_admin=True)
    assert calls[-1] == (False, True)
    assert events.published[-1] == ("recording.stopped", {"id": RID, "by": "tok-b", "reason": "operator"})


def test_link_loss_beyond_grace_stops_without_waiting(rig):
    guard, calls, events, t = rig
    guard.link_opened("tok-a")
    guard.start("tok-a")
    guard.link_closed("tok-a")
    guard.on_status(status())
    assert calls[-1] == (True, True)            # inside the grace: nothing yet
    t[0] += LINK_GRACE_S + 0.1
    guard.on_status(status())
    assert calls[-1] == (False, False)
    assert events.published[-1][1]["reason"] == "link_lost"


def test_reconnect_inside_grace_keeps_recording(rig):
    guard, calls, _, t = rig
    guard.link_opened("tok-a")
    guard.start("tok-a")
    guard.link_closed("tok-a")
    t[0] += 1.0
    guard.on_status(status())
    guard.link_opened("tok-a")
    t[0] += LINK_GRACE_S
    guard.on_status(status())
    assert calls == [(True, True)]


def test_another_drivers_teleop_is_a_seat_change(rig):
    guard, calls, events, _ = rig
    guard.link_opened("tok-a")
    guard.start("tok-a")
    guard.on_teleop("tok-a")
    assert calls == [(True, True)]
    guard.on_teleop("tok-b")
    assert calls[-1] == (False, False)
    assert events.published[-1][1]["reason"] == "seat_changed"


def test_recorder_side_end_clears_the_owner_once(rig):
    guard, _, events, _ = rig
    guard.start("tok-a")
    guard.on_status(status("idle", reason="max_duration"))
    assert guard.owner() is None and not guard.active()
    stopped = [e for e in events.published if e[0] == "recording.stopped"]
    assert stopped == [("recording.stopped", {"id": RID, "by": None, "reason": "max_duration"})]


def test_malformed_status_is_rejected(rig):
    guard, *_ = rig
    with pytest.raises(ValueError):
        guard.on_status({"state": "recording"})


def test_fetched_notice_uses_the_bridge(rig):
    guard, *_ = rig
    sent = []
    guard.publish_fetched = sent.append
    guard.fetched(RID)
    assert sent == [RID]
```

`test_pilot_recording_store.py`:

```python
"""D-411 A: listing and tar streaming never leave the recording folder."""

import hashlib
import io
import json
import os
import tarfile

import pytest

from core_common.domain import pilot_recording_store as store

RID = "20261002T101500Z_rosy_01"


def make(root, rid=RID, *, manifest=True, files=None, fetched=False):
    folder = root / rid
    (folder / "bag").mkdir(parents=True)
    (folder / "bag" / "bag_0.mcap").write_bytes(b"m" * 700)
    (folder / "session.json").write_text(json.dumps({
        "schema": "rosy.recording.session/1", "device": "rosy_01", "started_at": "2026-10-02T10:15:00Z",
        "ended_at": "2026-10-02T10:16:00Z" if manifest else None, "mode": "pilot",
        "topics": ["cmd_vel"], "harvested": False}), encoding="utf-8")
    if manifest:
        entries = files or [
            {"path": p, "bytes": (folder / p).stat().st_size,
             "sha256": hashlib.sha256((folder / p).read_bytes()).hexdigest()}
            for p in ("bag/bag_0.mcap", "session.json")]
        (folder / "manifest.json").write_text(json.dumps({
            "schema": "rosy.pilot.recording.manifest/1", "id": rid, "started_at": "2026-10-02T10:15:00Z",
            "ended_at": "2026-10-02T10:16:00Z", "duration_s": 60.0, "topics": ["cmd_vel"],
            "stop_reason": "requested", "files": entries}), encoding="utf-8")
    if fetched:
        (folder / "fetched.json").write_text("{}", encoding="utf-8")
    return folder


def test_list_reports_status_size_and_manifest_hash(tmp_path):
    make(tmp_path)
    make(tmp_path, "20261002T101700Z_rosy_01", manifest=False)
    (tmp_path / "not-a-recording").mkdir()
    items = {item["id"]: item for item in store.list_recordings(tmp_path, active_id=None)}
    assert set(items) == {RID, "20261002T101700Z_rosy_01"}
    assert items[RID]["status"] == "complete" and items[RID]["manifest_sha256"]
    assert items["20261002T101700Z_rosy_01"]["status"] == "incomplete"


def test_active_recording_is_listed_as_recording(tmp_path):
    make(tmp_path, manifest=False)
    (item,) = store.list_recordings(tmp_path, active_id=RID)
    assert item["status"] == "recording"


def test_archive_stream_is_a_valid_tar_with_exact_length(tmp_path):
    make(tmp_path)
    members, length = store.archive_plan(tmp_path, RID)
    data = b"".join(store.iter_archive(members))
    assert len(data) == length
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        names = archive.getnames()
        assert names == [f"{RID}/manifest.json", f"{RID}/bag/bag_0.mcap", f"{RID}/session.json"]
        assert archive.extractfile(f"{RID}/bag/bag_0.mcap").read() == b"m" * 700


@pytest.mark.parametrize("rid", ["../x", "20261002T101500Z_missing", "manifest.json"])
def test_unknown_or_unsafe_ids_are_not_found(tmp_path, rid):
    make(tmp_path)
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, rid)


def test_manifest_path_escape_is_refused(tmp_path):
    make(tmp_path, files=[{"path": "../../etc/passwd", "bytes": 1, "sha256": "a" * 64}])
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlinked_member_is_refused(tmp_path):
    folder = make(tmp_path)
    target = folder / "bag" / "bag_0.mcap"
    target.unlink()
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


def test_size_change_since_the_manifest_is_refused(tmp_path):
    folder = make(tmp_path)
    (folder / "bag" / "bag_0.mcap").write_bytes(b"m" * 10)
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)


def test_incomplete_recording_has_no_archive(tmp_path):
    make(tmp_path, manifest=False)
    with pytest.raises(LookupError):
        store.archive_plan(tmp_path, RID)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/contracts/foundation/test/test_pilot_recording_guard.py src/contracts/foundation/test/test_pilot_recording_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core_common.domain.pilot_recording'`

- [ ] **Step 3: 구현**

`pilot_recording.py`(가드, 약 170줄) 공개 표면:

```python
"""D-411 A: CORE's Pilot recording guard. ROS-free; ros_bridge wires the transport.

CORE only asks the camera unit's recorder to start or stop. It stops a recording when the
owner's /ws/state link is gone for LINK_GRACE_S, or when another token's teleop is accepted.
"""
STATUS_STALE_S = 3.0
LINK_GRACE_S = 5.0
_REFUSAL_STATUS = {"RECORDING_BUSY": 409, "RECORDING_QUOTA_FULL": 507,
                   "RECORDING_NOT_ACTIVE": 409, "RECORDER_UNAVAILABLE": 503}


class RecordingRefused(Exception):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


class PilotRecordingGuard:
    def __init__(self, *, events=None, clock=time.monotonic) -> None: ...
    request_active: Callable[[bool, bool], tuple[bool, str]] | None   # (on, wait) -> (ok, message)
    publish_fetched: Callable[[str], None] | None
    def status(self) -> dict | None: ...        # last RecorderStatus dict, None when stale/absent
    def active(self) -> bool: ...
    def owner(self) -> str | None: ...
    def on_status(self, payload: dict) -> None: ...   # validates RecorderStatus; checks the link
    def start(self, token_id: str) -> dict: ...       # raises RecordingRefused
    def stop(self, token_id: str, *, is_admin: bool) -> dict: ...
    def link_opened(self, token_id: str) -> None: ...
    def link_closed(self, token_id: str) -> None: ...
    def on_teleop(self, token_id: str) -> None: ...
    def fetched(self, recording_id: str) -> None: ...
```

규칙:
- 모든 상태는 `threading.Lock` 아래. `request_active` 호출은 **잠금 밖**.
- `on_status`: `RecorderStatus.model_validate(payload).model_dump(by_alias=True)`로 저장, 시각 기록. 새 상태가 비활성인데 `_owner`가 있었으면 `recording.stopped {id: 직전 활성 id, by: None, reason: 새 상태의 last_stop_reason}`을 한 번 내고 `_owner=None`. 이어서 `_check_link()`.
- `start`: `request_active is None` 또는 `status() is None` → `RECORDER_UNAVAILABLE`(503). `active()` → `RECORDING_BUSY`(409). `ok, message = request_active(True, True)`; `message`는 노드가 보낸 `{"code", "status"}` JSON(파싱 실패는 `{}`). 실패면 `code = body.get("code") or "RECORDER_UNAVAILABLE"`, `_REFUSAL_STATUS`로 HTTP 상태. 성공이면 `_owner = token_id`, `_lost_at = None`, 응답 상태로 캐시 갱신, `events.publish("recording.started", severity="info", source="pilot_recording", data={"id": ..., "owner": token_id})`, 상태 dict 반환.
- `stop`: 비활성 → `RECORDING_NOT_ACTIVE`(409). 소유자도 관리자도 아니면 `RecordingRefused("FORBIDDEN", 403, ...)`. `request_active(False, True)`가 실패면 `RECORDER_UNAVAILABLE`. 성공이면 `recording.stopped {id, by: token_id, reason: "operator"}`, `_owner=None`.
- `_stop_async(reason)`: `request_active(False, False)`; `recording.stopped {id, by: None, reason}`; `_owner=None`.
- `_check_link()`: 활성·소유자 있음·`_links.get(owner, 0) == 0`이면 `_lost_at`을 처음 시각으로 두고, `clock()-_lost_at >= LINK_GRACE_S`면 `_stop_async("link_lost")`. 링크가 있으면 `_lost_at=None`.
- `on_teleop(token)`: 활성이고 소유자가 있고 `token != owner`면 `_stop_async("seat_changed")`.
- 이벤트 이름은 발행 지점의 문자열 리터럴(`"recording.started"`, `"recording.stopped"`).

`pilot_recording_store.py`(약 130줄):

```python
"""D-411 A: read-only view of /var/lib/rosy/pilot-recordings for CORE (setgid rosy-core)."""

def list_recordings(root: Path, *, active_id: str | None) -> list[dict]:
    """Newest first; RecordingSummary dicts. Folders that are not recordings are skipped."""

def archive_plan(root: Path, recording_id: str) -> tuple[list[tuple[str, Path, int]], int]:
    """(arcname, path, size) for manifest.json then every manifest file, and the exact tar
    length. LookupError for an unknown/unsafe id, a missing or invalid manifest, a member that
    escapes the folder, is not a regular file, or whose size differs from the manifest."""

def iter_archive(members, chunk_size: int = 1 << 20):
    """Uncompressed USTAR stream (mcap is already zstd): header, data, pad, two zero blocks."""
```

`archive_plan` 경로 검사(이 순서):

```python
    if not recording_id_ok(recording_id):
        raise LookupError("unknown recording")
    folder = (root / recording_id)
    base = folder.resolve(strict=False)
    try:
        raw = (folder / MANIFEST_NAME).read_bytes()
        manifest = RecordingManifest.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise LookupError("recording has no valid manifest") from exc
    if manifest.id != recording_id:
        raise LookupError("manifest names another recording")
    members = [(f"{recording_id}/{MANIFEST_NAME}", folder / MANIFEST_NAME, len(raw))]
    for item in manifest.files:
        path = folder / item.path
        info = os.lstat(path)                       # never follow a link
        if (not stat.S_ISREG(info.st_mode) or not path.resolve().is_relative_to(base)
                or info.st_size != item.bytes):
            raise LookupError(f"member {item.path} changed or escapes the recording")
        members.append((f"{recording_id}/{item.path}", path, item.bytes))
    length = sum(512 + -(-size // 512) * 512 for _, _, size in members) + 1024
    return members, length
```

(`os.lstat`의 `FileNotFoundError`도 `LookupError`로 바꾼다.) `iter_archive`:

```python
def _header(arcname: str, size: int, mtime: float) -> bytes:
    info = tarfile.TarInfo(arcname)
    info.size, info.mtime, info.mode, info.type = size, int(mtime), 0o640, tarfile.REGTYPE
    return info.tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8", errors="strict")


def iter_archive(members, chunk_size: int = 1 << 20):
    for arcname, path, size in members:
        yield _header(arcname, size, path.stat().st_mtime)
        sent = 0
        with path.open("rb") as handle:
            while sent < size:
                block = handle.read(min(chunk_size, size - sent))
                if not block:
                    raise OSError(f"{arcname} shrank while streaming")
                sent += len(block)
                yield block
        if size % 512:
            yield b"\0" * (512 - size % 512)
    yield b"\0" * 1024
```

`list_recordings`: `root.iterdir()` 중 `recording_id_ok(name)`인 디렉터리만, `session.json`이 `mode == "pilot"`인 것만. `status`: `name == active_id` → `"recording"`, `manifest.json`이 유효 → `"complete"`, 그 밖 → `"incomplete"`. `bytes`는 폴더 안 일반 파일 합(`os.lstat`), `manifest_sha256`은 manifest 바이트의 sha256, `duration_s`는 manifest 값(없으면 None), `fetched`는 `fetched.json` 존재. `started_at` 내림차순.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/contracts/foundation/test/test_pilot_recording_guard.py src/contracts/foundation/test/test_pilot_recording_store.py src/contracts/foundation/test/test_pilot_recording_contract.py -q`
Expected: PASS (symlink 시험은 Windows에서 skip)

- [ ] **Step 5: 커밋**

```bash
git add src/contracts/foundation/core_common/domain/pilot_recording.py src/contracts/foundation/core_common/domain/pilot_recording_store.py src/contracts/foundation/test/test_pilot_recording_guard.py src/contracts/foundation/test/test_pilot_recording_store.py
git commit -m "feat(core_common): D-411 recording guard and read-only recording store" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A7: CORE 녹화 API, 링크 훅, 브리지 배선, API Ref v1.76

**Files:**
- Create: `src/runtime/api_web/core_api_web/api/v1/recordings.py`
- Modify: `src/runtime/api_web/core_api_web/api/v1/routes.py` (라우터 export), `api/app.py:1, 111, 160-185`
- Modify: `src/runtime/api_web/core_api_web/api/ws.py:84-97`
- Modify: `src/runtime/api_web/core_api_web/api/deps.py:75-100`
- Modify: `src/runtime/api_web/core_api_web/api/v1/control.py` (수락 뒤 `on_teleop`)
- Modify: `src/runtime/gateway/core/services.py:252` 부근(필드), `:540-546`(생성)
- Modify: `src/runtime/gateway/core/bridge/ros_bridge.py:29-30, 135, 144-150, 237`
- Modify: `src/contracts/foundation/config/rosy_default.yaml` (`recording.pilot_root`)
- Modify: `src/runtime/gateway/test/test_bridge_timers.py:204-264, latched 시험`
- Modify: `docs/reference/ROSY API & Protocol Reference.md`, 버전 핀 5곳
- Test: `src/runtime/gateway/test/test_recordings_api.py`(추가)

수신 게이트(D-136 §6, D-411 §5): 녹화 중이면 `RECORDING_BUSY`(409). MANUAL 입력이 살아 있거나(`command.manual_active`), 모드가 NAVIGATION·DOCKING이거나, line-follow가 돌거나, 신선한 0 속도 증거가 없으면(E-Stop이면 예외) `ROBOT_MOVING`(409). MANUAL 모드 자체는 막지 않는다 — 스틱을 놓은 Pilot이 그 자리에서 받을 수 있어야 한다(`traffic.py:54-68`의 `_robot_stopped`는 MANUAL을 막으므로 그대로 쓰지 않고 같은 증거 판정만 따른다). 목록은 viewer, 시작·정지·tar는 operator(카메라 영상 반출이므로). tar 스트림이 끝까지 나가면 가드가 `pilot_recorder/fetched`를 낸다(녹화기가 `fetched.json`을 써 쿼터 정리 대상으로 만든다).

- [ ] **Step 1: 실패하는 시험 쓰기** — `test_recordings_api.py`에 추가:

```python
import hashlib
import io
import json
import tarfile

RID = "20261002T101500Z_rosy_01"


def _status(state="idle", rid=None, reason=""):
    return {"schema": "rosy.pilot.recording.status/1", "state": state, "id": rid, "elapsed_s": 0.0,
            "bytes": 0, "max_duration_s": 600, "quota_free_bytes": 1000, "last_stop_reason": reason}


def _wire(svc, *, ok=True):
    calls = []

    def request(on, wait):
        calls.append((on, wait))
        state = ("recording", RID) if on else ("stopping", RID)
        return ok, json.dumps({"code": "" if ok else "RECORDING_QUOTA_FULL",
                               "status": _status(*state)})

    svc.pilot_recording.request_active = request
    sent = []
    svc.pilot_recording.publish_fetched = sent.append
    svc.pilot_recording.on_status(_status())
    return calls, sent


def _recording(root):
    folder = root / RID
    (folder / "bag").mkdir(parents=True)
    (folder / "bag" / "bag_0.mcap").write_bytes(b"m" * 600)
    (folder / "session.json").write_text(json.dumps({"mode": "pilot", "started_at": "2026-10-02T10:15:00Z",
                                                    "ended_at": "2026-10-02T10:16:00Z", "topics": []}))
    files = [{"path": p, "bytes": (folder / p).stat().st_size,
              "sha256": hashlib.sha256((folder / p).read_bytes()).hexdigest()}
             for p in ("bag/bag_0.mcap", "session.json")]
    (folder / "manifest.json").write_text(json.dumps({
        "schema": "rosy.pilot.recording.manifest/1", "id": RID, "started_at": "2026-10-02T10:15:00Z",
        "ended_at": "2026-10-02T10:16:00Z", "duration_s": 60.0, "topics": [], "stop_reason": "requested",
        "files": files}))


@pytest.fixture
def rec_client(core_client, tmp_path):
    client, svc = core_client(config_overrides={"recording": {"pilot_root": str(tmp_path / "rec")}})
    (tmp_path / "rec").mkdir()
    return client, svc, tmp_path / "rec"


def test_start_and_stop_go_through_the_recorder(rec_client):
    client, svc, _ = rec_client
    calls, _ = _wire(svc)
    assert client.post("/api/v1/recordings", headers=VIEWER).status_code == 403
    started = client.post("/api/v1/recordings", headers=OPERATOR)
    assert started.status_code == 201 and started.json()["state"] == "recording"
    assert client.post("/api/v1/recordings", headers=OPERATOR).json()["error"]["code"] == "RECORDING_BUSY"
    stopped = client.post("/api/v1/recordings/active/stop", headers=OPERATOR)
    assert stopped.status_code == 200 and calls == [(True, True), (False, True)]


def test_quota_refusal_is_507(rec_client):
    client, svc, _ = rec_client
    _wire(svc, ok=False)
    response = client.post("/api/v1/recordings", headers=OPERATOR)
    assert response.status_code == 507 and response.json()["error"]["code"] == "RECORDING_QUOTA_FULL"


def test_unwired_recorder_is_503(rec_client):
    client, _, _ = rec_client
    assert client.post("/api/v1/recordings", headers=OPERATOR).json()["error"]["code"] == "RECORDER_UNAVAILABLE"


def test_list_and_download_when_stopped(rec_client):
    client, svc, root = rec_client
    _, sent = _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    listing = client.get("/api/v1/recordings", headers=VIEWER).json()
    assert listing["download_allowed"] is True and listing["items"][0]["id"] == RID
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.status_code == 200 and response.headers["content-type"] == "application/x-tar"
    assert int(response.headers["content-length"]) == len(response.content)
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:") as archive:
        assert f"{RID}/bag/bag_0.mcap" in archive.getnames()
    assert sent == [RID]


def test_download_refused_while_recording(rec_client):
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.0, 0.0)
    client.post("/api/v1/recordings", headers=OPERATOR)
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.status_code == 409 and response.json()["error"]["code"] == "RECORDING_BUSY"


def test_download_refused_while_moving(rec_client):
    client, svc, root = rec_client
    _wire(svc)
    _recording(root)
    svc.state.set_velocity(0.2, 0.0)
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.status_code == 409 and response.json()["error"]["code"] == "ROBOT_MOVING"
    svc.state.set_velocity(0.0, 0.0)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.post("/api/v1/teleop", json={"linear": 0.1}, headers=OPERATOR).status_code == 200
    response = client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR)
    assert response.json()["error"]["code"] == "ROBOT_MOVING"
    svc.command.clear_manual()
    assert client.get(f"/api/v1/recordings/{RID}/archive", headers=OPERATOR).status_code == 200


def test_unknown_or_traversal_ids_are_not_found(rec_client):
    client, svc, _ = rec_client
    _wire(svc)
    svc.state.set_velocity(0.0, 0.0)
    for rid in ("20261002T101500Z_missing", "..%2F..%2Fetc"):
        response = client.get(f"/api/v1/recordings/{rid}/archive", headers=OPERATOR)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RECORDING_NOT_FOUND"


def test_ws_state_link_feeds_the_guard(rec_client):
    client, svc, _ = rec_client
    with client.websocket_connect("/ws/state?token=rosy-dev-operator") as socket:
        socket.receive_json()
        assert sum(svc.pilot_recording._links.values()) == 1
    assert sum(svc.pilot_recording._links.values()) == 0


def test_another_tokens_teleop_stops_the_recording(rec_client):
    client, svc, _ = rec_client
    calls, _ = _wire(svc)
    svc.state.set_velocity(0.0, 0.0)
    client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR)
    client.post("/api/v1/recordings", headers=OPERATOR)
    client.post("/api/v1/teleop", json={"linear": 0.05}, headers=ADMIN)
    assert calls[-1] == (False, False)
```

`test_bridge_timers.py`:
- `EXPECTED_SUBSCRIPTIONS` 끝(`localization/result` 뒤)에 `("pilot_recorder/status", "_on_pilot_recorder_status", "LATCHED"),`
- `EXPECTED_PUBLISHERS` 끝(`teleop/intent` 뒤)에 `("pilot_recorder/fetched", 5),`
- `EXPECTED_CLIENTS = ["set_led", "set_emotion", "start_motor", "stop_motor", "pilot_recorder/set_active", "slam_toolbox/save_map"]`
- `test_the_three_latched_endpoints_stay_latched`의 집합에 `"pilot_recorder/status"` 추가

`core_client`의 `config_overrides` 인자가 어떻게 병합되는지 `conftest.py:35-70`에서 확인하고(얕은 병합이면 `{"recording": {...}}`로 충분), 다르면 같은 픽스처의 기존 사용 예를 따른다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/gateway/test/test_recordings_api.py src/runtime/gateway/test/test_bridge_timers.py -q`
Expected: FAIL — `404 Not Found` (`/api/v1/recordings`), `AttributeError: 'CoreServices' object has no attribute 'pilot_recording'`, 브리지 목록 불일치

- [ ] **Step 3: 구현**

`recordings.py`:

```python
"""core_api_web.api.v1.recordings — D-411 A Pilot robot recording control and download."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from core_api_web.api.deps import AuthContext, CoreServicesLike, Mode, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer
from core_common.domain.pilot_recording import RecordingRefused
from core_common.domain.pilot_recording_store import archive_plan, iter_archive, list_recordings
from core_common.protocol.recording import PILOT_RECORDING_ROOT

recordings_router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])


def _root(svc: CoreServicesLike) -> Path:
    return Path((svc.config.get("recording") or {}).get("pilot_root") or PILOT_RECORDING_ROOT)


def _download_blocker(svc: CoreServicesLike) -> str | None:
    if svc.pilot_recording.active():
        return "RECORDING_BUSY"
    if (svc.command.manual_active or svc.modes.mode in (Mode.NAVIGATION, Mode.DOCKING)
            or svc.line_follow.active):
        return "ROBOT_MOVING"
    snapshot = svc.state.snapshot()
    evidence = snapshot.evidence.get("velocity")
    fresh = bool(evidence and evidence.evidence.value == "fresh")
    still = abs(float(snapshot.velocity.linear)) <= 0.005 and abs(float(snapshot.velocity.angular)) <= 0.01
    return None if svc.safety.estop or (fresh and still) else "ROBOT_MOVING"


def _refused(exc: RecordingRefused) -> ApiError:
    return ApiError(exc.code, exc.status, exc.message)


@recordings_router.get("")
def recordings(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    status = svc.pilot_recording.status()
    active_id = status["id"] if status and status["state"] in ("recording", "stopping") else None
    blocker = _download_blocker(svc)
    return {"active": status, "items": list_recordings(_root(svc), active_id=active_id),
            "download_allowed": blocker is None, "download_blocker": blocker}


@recordings_router.get("/active")
def active(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return {"active": svc.pilot_recording.status(),
            "owned": svc.pilot_recording.owner() == auth.token_id}


@recordings_router.post("", status_code=201)
def start(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    try:
        return svc.pilot_recording.start(auth.token_id)
    except RecordingRefused as exc:
        raise _refused(exc) from exc


@recordings_router.post("/active/stop")
def stop(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    try:
        return svc.pilot_recording.stop(auth.token_id, is_admin=auth.role == "administrator")
    except RecordingRefused as exc:
        raise _refused(exc) from exc


@recordings_router.get("/{recording_id}/archive")
def archive(recording_id: str, _: AuthContext = Depends(operator),
            svc: CoreServicesLike = Depends(get_services)):
    blocker = _download_blocker(svc)
    if blocker is not None:
        raise ApiError(blocker, 409, "recordings can only be downloaded while the robot is stopped")
    try:
        members, length = archive_plan(_root(svc), recording_id)
    except LookupError as exc:
        raise ApiError("RECORDING_NOT_FOUND", 404, str(exc)) from exc

    def stream():
        yield from iter_archive(members)
        svc.pilot_recording.fetched(recording_id)   # only after the last byte left

    return StreamingResponse(stream(), media_type="application/x-tar", headers={
        "Content-Length": str(length), "Cache-Control": "no-store", "Content-Encoding": "identity",
        "Content-Disposition": f'attachment; filename="{recording_id}.tar"'})
```

`routes.py`에 `from core_api_web.api.v1.recordings import recordings_router`를 다른 라우터 export와 같은 방식으로 더하고, `app.py:160-185`의 `include_router` 목록에서 `vision` 다음에 `app.include_router(recordings_router)`. `app.py:1`과 `:111`의 `v1.75` → `v1.76`.

`ws.py:84-97`(`ws_state`):

```python
    svc = await _authorize(websocket)
    if svc is None:
        return
    token_id = websocket.state.token_id
    svc.pilot_recording.link_opened(token_id)     # D-411: the Pilot link for recording ownership
    rate = float(svc.config.get("state", {}).get("rate_hz", 10.0))
    try:
        while True:
            await websocket.send_json(svc.state.snapshot().model_dump())
            await asyncio.sleep(1.0 / rate)
    except WebSocketDisconnect:
        return
    except Exception:
        return
    finally:
        svc.pilot_recording.link_closed(token_id)
```

`control.py` — 수락 뒤(`if not accepted: raise ...` 다음):

```python
    svc.pilot_recording.on_teleop(auth.token_id)   # D-411: another driver ends the recording
```

`deps.py` `CoreServicesLike`(알파벳 순서 유지): `pilot_recording: Any`.

`services.py` — 필드(`adapter_registry` 필드 옆): `pilot_recording: PilotRecordingGuard = field(default_factory=PilotRecordingGuard)`; `build()`의 `cls(...)` 인자(`:544` 부근)에 `pilot_recording=PilotRecordingGuard(events=events),`; import `from core_common.domain.pilot_recording import PilotRecordingGuard`. 순증 3줄.

`rosy_default.yaml` — 최상위:

```yaml
recording:
  pilot_root: "/var/lib/rosy/pilot-recordings"   # D-411; tests and Gazebo override via ROSY_CONFIG
```

`ros_bridge.py`:
- `:30` `from std_srvs.srv import Empty, SetBool`; import에 `from core.bridge.save_map import await_call`(이미 있으면 생략), `from core_common.protocol.recording import FETCHED_TOPIC, SET_ACTIVE_SERVICE, STATUS_TOPIC, TELEOP_INTENT_TOPIC, teleop_intent`.
- `:135` (`localization/result` 구독) 바로 뒤: `node.create_subscription(String, STATUS_TOPIC, self._on_pilot_recorder_status, _LATCHED)`
- `intent_pub` 바로 뒤: `self.pilot_fetched_pub = node.create_publisher(String, FETCHED_TOPIC, 5)`
- `:150` (`_lidar_stop_client`) 뒤: `self._pilot_recorder_client = node.create_client(SetBool, SET_ACTIVE_SERVICE)`
- intent 싱크 배선 뒤:

```python
        guard = self._svc.pilot_recording
        guard.request_active = self._request_pilot_recording
        guard.publish_fetched = lambda rid: self.pilot_fetched_pub.publish(
            String(data=json.dumps({"id": rid})))
```

- 메서드 두 개:

```python
    def _on_pilot_recorder_status(self, msg: String) -> None:
        try:
            self._svc.pilot_recording.on_status(json.loads(msg.data))
        except (ValueError, TypeError) as exc:
            self._node.get_logger().warn(f"pilot recorder status ignored: {exc}",
                                         throttle_duration_sec=10.0)

    def _request_pilot_recording(self, on: bool, wait: bool) -> tuple[bool, str]:
        """D-411: ask the camera unit's recorder. wait=False from executor callbacks."""
        client = self._pilot_recorder_client
        if not client.service_is_ready():
            return False, ""
        request = SetBool.Request()
        request.data = on
        future = client.call_async(request)
        if not wait:
            return True, ""
        try:
            response = await_call(future, timeout=3.0)
        except RuntimeError:
            return False, ""
        return bool(response.success), str(response.message)
```

**API Ref** (`docs/reference/ROSY API & Protocol Reference.md`):
- L5 `**Version:** v1.76`.
- ERR-102 표(116-157)에 5행: `RECORDING_BUSY` 409 "녹화 중 — 동시 녹화 1개, 녹화 중 수신 불가(D-411)", `ROBOT_MOVING` 409 "수신은 정지 중에만: MANUAL 입력 없음·NAVIGATION/DOCKING 아님·line-follow OFF·신선한 0 속도(또는 E-Stop)(D-411, D-136 §6)", `RECORDING_NOT_FOUND` 404, `RECORDING_QUOTA_FULL` 507 "받지 않은 녹화로 전용 쿼터가 참", `RECORDER_UNAVAILABLE` 503 "카메라 유닛 녹화기 상태가 없거나 3 s 넘게 낡음".
- §5.9 뒤에 새 절 `## 5.10 Pilot 로봇 녹화 (D-411, v1.76)`: 표 5행(GET `/api/v1/recordings` Viewer `{active, items[RecordingSummary], download_allowed, download_blocker}`; GET `/active` Viewer `{active, owned}`; POST `/api/v1/recordings` Operator → 201 `RecorderStatus`; POST `/active/stop` Operator(시작 토큰 또는 Admin, 아니면 403); GET `/{id}/archive` Operator, `application/x-tar` 무압축 USTAR, `Content-Length` 정확, 멤버는 `<id>/manifest.json` + manifest 파일만). 본문: 녹화 주체는 카메라 유닛 `pilot_recorder_node`, 1회 600 s, 전용 쿼터, 토픽 목록, `teleop/intent`(`rosy.teleop.intent/1` 필드 표), 시작 토큰의 `/ws/state`가 5 s 넘게 없거나 다른 토큰 teleop 수락 시 정지, 끝까지 받은 녹화만 쿼터 정리 대상, 스키마 정본 `core_common.protocol.recording`.
- §8 표에 2행: `recording.started` info 로봇 `{id, owner}`; `recording.stopped` info 로봇 `{id, by, reason}` — `reason` ∈ `operator`·`link_lost`·`seat_changed`·`max_duration`·`quota`·`recorder_exit`·`requested`·`shutdown`·`recovered`, `by`는 토큰 id 또는 null.
- §11 맨 위 행: `| v1.76 | 2026-10-02 | Additive (D-411 A): §5.10 Pilot 로봇 녹화(시작·정지·목록·tar), ERR-102 다섯 코드, §8 \`recording.started\`·\`recording.stopped\`, ROS 증거 토픽 \`teleop/intent\`. 기존 필드 변화 없음 |`

버전 핀: `test/test_line_follow_contract_docs.py:15`, `src/site/fleet/test/test_task_contract_docs.py:26`·`:88`, `src/site/fleet/test/test_mission_progress.py:512`의 `v1.75` → `v1.76`.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/gateway/test/test_recordings_api.py src/runtime/gateway/test/test_bridge_timers.py src/runtime/gateway/test/test_event_catalogue.py src/runtime/gateway/test/test_protocol_version_alignment.py src/runtime/gateway/test/test_api.py test/test_line_follow_contract_docs.py src/site/fleet/test/test_task_contract_docs.py src/site/fleet/test/test_mission_progress.py test/architecture/test_module_structure.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/api_web/core_api_web/api/v1/recordings.py src/runtime/api_web/core_api_web/api/v1/routes.py src/runtime/api_web/core_api_web/api/app.py src/runtime/api_web/core_api_web/api/ws.py src/runtime/api_web/core_api_web/api/deps.py src/runtime/api_web/core_api_web/api/v1/control.py src/runtime/gateway/core/services.py src/runtime/gateway/core/bridge/ros_bridge.py src/contracts/foundation/config/rosy_default.yaml src/runtime/gateway/test/test_recordings_api.py src/runtime/gateway/test/test_bridge_timers.py "docs/reference/ROSY API & Protocol Reference.md" test/test_line_follow_contract_docs.py src/site/fleet/test/test_task_contract_docs.py src/site/fleet/test/test_mission_progress.py
git commit -m "feat(core): D-411 recordings API, link guard, recorder bridge (API v1.76)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A8: PC `rosy_ml fetch --http`

**Files:**
- Create: `tools/perception/dataset/fetch_http.py`
- Modify: `tools/perception/dataset/bag_to_video.py:56-57, 98-100`
- Modify: `tools/perception/rosy_ml.py:521-524` (파서), `:569-578` (디스패치)
- Test: `tools/perception/test/test_fetch_http.py`, `tools/perception/test/test_bag_to_video.py`(추가), `tools/perception/test/test_rosy_ml.py`(추가)

저장 위치(D-379): 원본 세션은 `--dest`(기본 `data/perception/raw`) 아래 `<dest>/<id>/` — `catalog.py scan`이 `raw/*/session.json` 한 단계만 본다(`catalog.py:230`). 영상·사이드카는 `bag_to_video` 기본 `data/teleop/learning`. 로봇 쿼터 정리 신호는 서버가 낸다(스트림 완료). PC는 sha256 불일치 시 해당 세션을 지우고 실패로 끝낸다.

- [ ] **Step 1: 실패하는 시험 쓰기**

`test_fetch_http.py`:

```python
"""D-411 A: HTTP fetch verifies every byte, refuses tar escapes and pair-checks the sidecar."""

import hashlib
import http.server
import io
import json
import tarfile
import threading

import pytest

import fetch_http

RID = "20261002T101500Z_rosy_01"


def _tar(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, body in entries:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return data.getvalue()


def _recording(tamper=False):
    bag, session = b"m" * 300, json.dumps({"device": "rosy_01", "started_at": "2026-10-02T10:15:00Z"}).encode()
    files = [{"path": "bag/bag_0.mcap", "bytes": len(bag), "sha256": hashlib.sha256(bag).hexdigest()},
             {"path": "session.json", "bytes": len(session), "sha256": hashlib.sha256(session).hexdigest()}]
    manifest = json.dumps({"schema": fetch_http.MANIFEST_SCHEMA, "id": RID, "files": files}).encode()
    return _tar([(f"{RID}/manifest.json", manifest), (f"{RID}/bag/bag_0.mcap", b"x" * 300 if tamper else bag),
                 (f"{RID}/session.json", session)])


@pytest.fixture
def server():
    state = {"listing": {"items": [{"id": RID, "status": "complete"}], "download_allowed": True,
                         "download_blocker": None}, "archive": _recording(), "auth": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state["auth"].append(self.headers.get("Authorization"))
            body = (json.dumps(state["listing"]).encode() if self.path == "/api/v1/recordings"
                    else state["archive"])
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    httpd.shutdown()


def _main(base, tmp_path, convert, *extra):
    token = tmp_path / "token"
    token.write_text("op-token\n", encoding="utf-8")
    return fetch_http.main([base, "--token-file", str(token), "--dest", str(tmp_path / "raw"),
                            "--video-out", str(tmp_path / "video"), *extra], convert=convert)


def test_fetch_verifies_extracts_converts_and_pair_checks(server, tmp_path):
    base, state = server

    def convert(folder, out, codec):
        out.mkdir(parents=True, exist_ok=True)
        rows = [{"side": {"cmd_vel": {"linear": 0.1}, "teleop/intent": {"accepted": True}}},
                {"side": {"cmd_vel": None, "teleop/intent": None}}]
        path = out / "teleop_rosy_01_20261002T101500Z.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return 0, path

    assert _main(base, tmp_path, convert) == 0
    assert (tmp_path / "raw" / RID / "bag" / "bag_0.mcap").read_bytes() == b"m" * 300
    assert state["auth"][0] == "Bearer op-token"
    assert not list((tmp_path / "raw").glob(".part-*"))


def test_a_tampered_member_fails_and_leaves_nothing(server, tmp_path):
    base, state = server
    state["archive"] = _recording(tamper=True)
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
    assert not (tmp_path / "raw" / RID).exists()


def test_escaping_member_is_refused(server, tmp_path):
    base, state = server
    state["archive"] = _tar([("../evil.txt", b"x")])
    assert _main(base, tmp_path, lambda *a: (0, None)) == 1
    assert not (tmp_path / "evil.txt").exists()


def test_robot_not_idle_exits_4(server, tmp_path):
    base, state = server
    state["listing"] = {**state["listing"], "download_allowed": False, "download_blocker": "ROBOT_MOVING"}
    assert _main(base, tmp_path, lambda *a: (0, None)) == fetch_http.EXIT_NOT_IDLE


def test_no_paired_frame_is_a_failure(server, tmp_path):
    base, _ = server

    def convert(folder, out, codec):
        out.mkdir(parents=True, exist_ok=True)
        path = out / "rows.jsonl"
        path.write_text(json.dumps({"side": {"cmd_vel": {"linear": 0.1}, "teleop/intent": None}}) + "\n",
                        encoding="utf-8")
        return 0, path

    assert _main(base, tmp_path, convert) == 1


def test_pair_counts():
    rows = [{"side": {"cmd_vel": {}, "teleop/intent": {}}}, {"side": {"cmd_vel": {}, "teleop/intent": None}},
            {"side": {"cmd_vel": None, "teleop/intent": None}}]
    assert fetch_http.pair_counts(rows) == {"frames": 3, "with_cmd_vel": 2, "with_intent": 1, "paired": 1}


def test_manifest_schema_matches_the_robot_contract():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "contracts" / "foundation"))
    from core_common.protocol.recording import MANIFEST_SCHEMA, TELEOP_INTENT_TOPIC
    assert fetch_http.MANIFEST_SCHEMA == MANIFEST_SCHEMA and fetch_http.INTENT_TOPIC == TELEOP_INTENT_TOPIC
```

`test_bag_to_video.py`에 추가:

```python
def test_teleop_intent_is_a_side_topic():
    assert b2v._side_name("/rosy_01/teleop/intent") == "teleop/intent"
    frames = [{"log_ns": 1_000_000_000, "stamp_ns": 1_000_000_000}]
    side = {"teleop/intent": ([900_000_000], [{"accepted": True, "linear": 0.1}])}
    (row,) = list(b2v.sidecar_rows(frames, side, 0.5))
    assert row["side"]["teleop/intent"]["accepted"] is True
```

`test_rosy_ml.py`에 추가(`test_harvest_uses_core_token_file` 패턴):

```python
def test_fetch_http_uses_core_token_and_port(tmp_path, monkeypatch):
    _init(tmp_path, "--core-token-file", str(tmp_path / "core.token"), monkeypatch=monkeypatch)
    seen = []
    fake = types.ModuleType("fetch_http")
    fake.main = lambda argv: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "fetch_http", fake)
    assert rosy_ml.main(["fetch", "pinky-a", "--http", "--dest", str(tmp_path / "raw")]) == 0
    assert seen[0][0] == "http://10.0.0.11:8080"
    assert seen[0][seen[0].index("--token-file") + 1] == str(tmp_path / "core.token")
    with pytest.raises(SystemExit):
        rosy_ml.main(["fetch", "pinky-a"])          # --http is required: SSH stays `harvest`
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tools/perception/test/test_fetch_http.py tools/perception/test/test_bag_to_video.py tools/perception/test/test_rosy_ml.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'fetch_http'`, `_side_name(...)` None, `invalid choice: 'fetch'`

- [ ] **Step 3: 구현**

`bag_to_video.py:57` import에 `INTENT_TOPIC = "teleop/intent"`를 상수로 두고(제어 패키지 import 없이; `control.recording`에는 넣지 않는다 — `SIDE_TOPICS`는 스냅샷 녹화기 계약이다), `_side_name`(98-100)의 후보 튜플을 `(*SIDE_TOPICS, ODOM_TOPIC, SCAN_TOPIC, INTENT_TOPIC)`로.

`fetch_http.py`(약 190줄):

```python
"""D-411 A: pull finished Pilot recordings over CORE HTTP (no SSH), verify every byte against
the robot's sha256 manifest, convert with bag_to_video and check frame/action pairing.

Only while CORE says the robot is stopped (D-136 §6). Usage:
  python tools/perception/dataset/fetch_http.py http://<robot-ip>:8080 --token-file op.token
"""
EXIT_NOT_IDLE = 4
MANIFEST_SCHEMA = "rosy.pilot.recording.manifest/1"   # core_common.protocol.recording
INTENT_TOPIC = "teleop/intent"
RECORDING_ID = re.compile(r"\d{8}T\d{6}Z_[A-Za-z0-9_.-]{1,64}")
CHUNK = 1 << 20


class FetchError(Exception):
    pass


def list_recordings(base: str, token: str, timeout: float) -> dict: ...
def download(base: str, token: str, recording_id: str, part: Path, timeout: float) -> None: ...
def safe_extract(tar_path: Path, staging: Path, recording_id: str) -> Path: ...
def verify(folder: Path, recording_id: str) -> dict: ...
def pair_counts(rows) -> dict: ...
def default_convert(folder: Path, out: Path, codec: str) -> tuple[int, Path | None]: ...
def main(argv=None, *, convert=default_convert) -> int: ...
```

규칙:
- `list_recordings`/`download`: `urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})`. `download`은 `CHUNK`씩 `part`로 스트리밍.
- `safe_extract`: `tarfile.open(tar_path, "r:")`; 모든 멤버가 `isfile()`이고, 이름이 `/`로 시작하지 않고, `\\` 없고, `PurePosixPath(name).parts`에 `..`·`.`가 없고, 첫 부분이 `recording_id`여야 한다. 하나라도 어기면 `FetchError`. 통과하면 `archive.extractall(staging, members=members, filter="data")`. 반환 `staging / recording_id`.
- `verify`: `manifest.json` 로드, `schema == MANIFEST_SCHEMA`, `id == recording_id`; 각 파일 경로 재검사(같은 규칙), 크기·sha256 일치; manifest에 없는 파일(manifest.json 제외)이 있으면 실패. manifest dict 반환.
- `pair_counts(rows)`: `{"frames", "with_cmd_vel", "with_intent", "paired"}` — `side["cmd_vel"]`·`side["teleop/intent"]`가 None이 아닌 행 수.
- `default_convert`: `bag_to_video.main([str(folder), "--out", str(out), "--codec", codec])`, 행 파일은 `out / f"{bag_to_video.output_stem(folder, meta)}.jsonl"`(`meta`는 `session.json`).
- `main`: 인자 `base`, `--token-file`(없으면 `harvest.TOKEN_ENV` 환경변수), `--dest`(기본 `data/perception/raw`), `--video-out`(기본 `bag_to_video.DEFAULT_OUT`), `--codec`(기본 `hevc`), `--only ID`, `--timeout 600`. 목록에서 `download_allowed`가 거짓이면 사유를 찍고 `EXIT_NOT_IDLE`. `status == "complete"`이고 `<dest>/<id>`가 없는 항목마다: `.part-<id>.tar`로 받기 → `.staging-<id>/`에 안전 추출 → 검증 → `os.replace(staging/id, dest/id)` → 임시물 삭제 → `convert` → `pair_counts`; `paired == 0`이면 실패. 실패한 항목은 `dest/id`·임시물을 지우고 rc 1. 요약 한 줄: `"{id}: {frames} frames, {paired} paired cmd_vel+intent"`.

`rosy_ml.py:521-524` 뒤에 파서:

```python
    p = sub.add_parser("fetch", help="D-411: pull Pilot recordings over CORE HTTP")
    p.add_argument("robot")
    p.add_argument("--http", action="store_true", required=True,
                   help="CORE HTTP; the SSH path stays `harvest`")
    p.add_argument("--dest")
    p.add_argument("--port", type=int, default=8080)
```

`:578` 뒤 디스패치:

```python
    if args.cmd == "fetch":
        import fetch_http
        if not cfg.get("core_token_file"):
            print("✗ fetch --http needs an operator token — fix: rosy_ml init --core-token-file <file>")
            return 2
        argv = [f"http://{hosts[0]}:{args.port}", "--token-file", cfg["core_token_file"]]
        if args.dest:
            argv += ["--dest", args.dest]
        return fetch_http.main(argv)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tools/perception/test -q -p no:cacheprovider`
Expected: PASS (ffmpeg·mcap 의존 시험은 기존처럼 조건부 skip)

- [ ] **Step 5: 커밋**

```bash
git add tools/perception/dataset/fetch_http.py tools/perception/dataset/bag_to_video.py tools/perception/rosy_ml.py tools/perception/test/test_fetch_http.py tools/perception/test/test_bag_to_video.py tools/perception/test/test_rosy_ml.py
git commit -m "feat(perception): D-411 rosy_ml fetch --http with sha256 verify and pair check" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A9: Pilot 로봇 녹화 토글과 "녹화본" 시트

**Files:**
- Create: `src/hmi/pilot/recording.js`, `src/hmi/pilot/screens/robot-recording.js`
- Modify: `src/hmi/pilot/client.js:24-49` (`apiBlob`)
- Modify: `src/hmi/pilot/screens/drive.js:139-150` (라벨), `:386-425` (버튼), `:478-504` (해제)
- Modify: `src/hmi/pilot/styles.css` (`[data-inputs-panel]` 319 옆에 `[data-recordings-sheet]`)
- Modify: 자산 등록 다섯 곳(구조 규칙 6): `recording.js`(최상위, CMake FILES 포함), `screens/robot-recording.js`; `sw.js` `CACHE`를 `rosy-pilot-shell-2026-10-02-1`로
- Modify: `src/hmi/pilot/test/dev_server.py` (가짜 녹화 API), `src/hmi/pilot/test/test_pilot_browser.py`, `src/runtime/api_web/test/test_pilot_route.py:24-47`
- Test: `src/hmi/pilot/test/test_recording_view.py`

- [ ] **Step 1: 실패하는 시험 쓰기**

`test_recording_view.py`(`test_stick.py:18-30` 패턴, 모듈 `recording.js`):

```python
"""D-411 A: pure view logic for the robot recording toggle and the recordings sheet."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[1] / "recording.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const m = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_formats():
    out = _run_js("console.log(JSON.stringify([m.formatElapsed(65.4), m.formatElapsed(0), "
                  "m.formatBytes(0), m.formatBytes(1536), m.formatBytes(12.5e6)]))")
    assert out == ["1:05", "0:00", "0 B", "1.5 KB", "12.5 MB"]


def test_toggle_view():
    out = _run_js("""console.log(JSON.stringify([
      m.recordingView(null),
      m.recordingView({state: 'idle', elapsed_s: 0, bytes: 0, max_duration_s: 600}),
      m.recordingView({state: 'recording', elapsed_s: 65, bytes: 1536, max_duration_s: 600}),
      m.recordingView({state: 'stopping', elapsed_s: 70, bytes: 2048, max_duration_s: 600}),
    ]))""")
    assert out[0] == {"recording": False, "available": False, "label": "로봇 녹화 · 연결 안 됨", "busy": False}
    assert out[1] == {"recording": False, "available": True, "label": "로봇 녹화", "busy": False}
    assert out[2]["recording"] is True and out[2]["label"] == "로봇 녹화 중지 · 1:05 / 10:00 · 1.5 KB"
    assert out[3]["busy"] is True


def test_sheet_rows_follow_the_download_gate():
    out = _run_js("""console.log(JSON.stringify([
      m.sheetRows({download_allowed: false, download_blocker: 'ROBOT_MOVING', items: [
        {id: 'a', status: 'complete', started_at: '2026-10-02T10:15:00Z', duration_s: 60, bytes: 1000}]}),
      m.sheetRows({download_allowed: true, download_blocker: null, items: [
        {id: 'a', status: 'complete', started_at: '2026-10-02T10:15:00Z', duration_s: 60, bytes: 1000},
        {id: 'b', status: 'incomplete', started_at: '2026-10-02T10:20:00Z', duration_s: null, bytes: 5}]}),
    ]))""")
    assert out[0][0]["canFetch"] is False and out[0][0]["reason"] == "로봇이 멈춘 뒤에 받을 수 있습니다"
    assert out[1][0]["canFetch"] is True and out[1][0]["reason"] == ""
    assert out[1][1]["canFetch"] is False and out[1][1]["reason"] == "끝나지 않은 녹화입니다"
```

`test_pilot_browser.py`에 추가(기존 `_enter_drive`, `tablet_page` 사용):

```python
@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_robot_recording_toggle_and_sheet(base_url, tablet_page):
    page, errors = tablet_page
    _enter_drive(page, base_url)
    assert page.locator("[data-evidence-record]").inner_text().strip() == "화면 녹화"
    page.click("[data-robot-record]")
    page.wait_for_function("document.querySelector('[data-robot-record]').textContent.includes('중지')")
    assert page.request.get(f"{base_url}/__test__/recordings").json()["log"] == ["start"]
    page.click("[data-robot-record]")
    page.click("[data-recordings-open]")
    row = page.locator("[data-recordings-sheet] [data-recording-id='20261002T101500Z_rosy_dev']")
    page.request.post(f"{base_url}/__test__/recordings", data={"blocker": "ROBOT_MOVING"})
    page.click("[data-recordings-refresh]")
    assert row.locator("[data-recording-fetch]").is_disabled()
    page.request.post(f"{base_url}/__test__/recordings", data={"blocker": None})
    page.click("[data-recordings-refresh]")
    with page.expect_download() as download:
        row.locator("[data-recording-fetch]").click()
    assert download.value.suggested_filename == "20261002T101500Z_rosy_dev.tar"
    assert errors == [], errors
```

`test_pilot_route.py` 단언 목록(24-47)에 `"recording.js"`, `"screens/robot-recording.js"` 200 단언 추가.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/hmi/pilot/test/test_recording_view.py src/hmi/pilot/test/test_shell_assets.py src/runtime/api_web/test/test_pilot_route.py -q`
Expected: FAIL — `ENOENT ... recording.js`, 자산 404

- [ ] **Step 3: 구현**

`recording.js`(import 없음):

```js
// D-411 A: pure view logic for robot recording (no DOM, no fetch, no clock).
export const RECORDING_POLL_MS = 1000;
const BLOCKER_TEXT = Object.freeze({
  RECORDING_BUSY: "녹화 중에는 받을 수 없습니다",
  ROBOT_MOVING: "로봇이 멈춘 뒤에 받을 수 있습니다",
});

export function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function formatBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  if (value < 1000) return `${value} B`;
  if (value < 1e6) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1e6).toFixed(1)} MB`;
}

export function recordingView(active) {
  if (!active) return {recording: false, available: false, label: "로봇 녹화 · 연결 안 됨", busy: false};
  const recording = active.state === "recording" || active.state === "stopping";
  if (!recording) return {recording: false, available: true, label: "로봇 녹화", busy: false};
  return {
    recording: true, available: true, busy: active.state === "stopping",
    label: `로봇 녹화 중지 · ${formatElapsed(active.elapsed_s)} / ${formatElapsed(active.max_duration_s)} · ${formatBytes(active.bytes)}`,
  };
}

export function sheetRows(listing) {
  const blocker = listing?.download_allowed ? "" : (BLOCKER_TEXT[listing?.download_blocker] ?? "지금은 받을 수 없습니다");
  return (listing?.items ?? []).map((item) => {
    const complete = item.status === "complete";
    return {
      id: item.id,
      title: item.started_at,
      detail: `${item.duration_s == null ? "—" : formatElapsed(item.duration_s)} · ${formatBytes(item.bytes)}`,
      canFetch: complete && !blocker,
      reason: !complete ? (item.status === "recording" ? "녹화 중입니다" : "끝나지 않은 녹화입니다") : blocker,
    };
  });
}
```

`client.js` — `postJson`(47) 뒤:

```js
// D-411: binary download with the same bearer header; the token never enters a URL.
export async function apiBlob(path, {timeoutMs} = {}) {
  const controller = timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(path, {cache: "no-store", headers: authHeaders(), signal: controller?.signal});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      return {status: response.status, ok: false, body, blob: null};
    }
    return {status: response.status, ok: true, body: null, blob: await response.blob()};
  } finally {
    if (timer) clearTimeout(timer);
  }
}
```

`screens/robot-recording.js`(약 150줄) 서명과 구조:

```js
// D-411 A: robot-side training recording (camera unit) — toggle in the HUD and a "녹화본" sheet.
import {api, apiBlob} from "../client.js";
import {saveCameraFile} from "/common/evidence.js";
import {RECORDING_POLL_MS, recordingView, sheetRows} from "../recording.js";

export function mountRobotRecording({toggle, openButton, sheetHost,
                                     request = api, requestBlob = apiBlob, save = saveCameraFile,
                                     schedule = (fn, ms) => { const id = setInterval(fn, ms); return () => clearInterval(id); },
                                     onError = () => {}} = {}) {
  // toggle: <ui-button data-robot-record>; openButton: <ui-button data-recordings-open>
  // sheetHost: element that receives <div data-recordings-sheet hidden> with a
  //   [data-recordings-refresh] button and one row per recording:
  //   <div data-recording-id=ID><span>title</span><span>detail</span>
  //     <ui-button data-recording-fetch [disabled reason=...]>받기</ui-button></div>
  // poll():   GET /api/v1/recordings/active → recordingView → toggle text/disabled/data-state
  // toggle:   POST /api/v1/recordings (start) or POST /api/v1/recordings/active/stop
  // open:     GET /api/v1/recordings → sheetRows → rows; refresh re-lists
  // fetch:    requestBlob(`/api/v1/recordings/${encodeURIComponent(id)}/archive`) → save(blob, `${id}.tar`)
  //           a 409 shows the blocker text in the row, never retries by itself
  return {
    async stopIfOwned() { /* GET /active; owned && recording → POST /active/stop */ },
    dispose() { /* stop polling, remove the sheet */ },
  };
}
```

`drive.js`:
- `:147` → `element.recordButton.textContent = state.recording ? "화면 녹화 중지" : "화면 녹화";`
- `:391` → `el("ui-button", "화면 녹화", {...})`
- `:398` 뒤:

```js
  const robotRecordButton = el("ui-button", "로봇 녹화", {type: "button", "data-robot-record": ""});
  robotRecordButton.setAttribute("kind", "quiet");
  const recordingsButton = el("ui-button", "녹화본", {type: "button", "data-recordings-open": ""});
  recordingsButton.setAttribute("kind", "quiet");
```

- `:424` → `actions.append(zoomButton, shotButton, recordButton, robotRecordButton, recordingsButton, inputsButton, exit);` 그리고 그 뒤 `const robotRecording = mountRobotRecording({toggle: robotRecordButton, openButton: recordingsButton, sheetHost: root.querySelector("[data-drive-stage]")});`
- `teardown()`(478-504)의 `capture.stop()` 줄 뒤: `robotRecording.stopIfOwned().finally(() => robotRecording.dispose());`
- import에 `import {mountRobotRecording} from "./robot-recording.js";`

`styles.css`: `[data-recordings-sheet]`는 `[data-inputs-panel]`(319)과 같은 위치·여백 규칙, 색·타이포는 `tokens.css` 변수만.

`dev_server.py`: 모듈 상태 `_RECORDINGS = {"active": {"schema": "rosy.pilot.recording.status/1", "state": "idle", "id": None, "elapsed_s": 0.0, "bytes": 0, "max_duration_s": 600, "quota_free_bytes": 10**9, "last_stop_reason": ""}, "blocker": None, "log": []}`와 항목 하나(`20261002T101500Z_rosy_dev`, complete). 라우트(`_role` 401 패턴): GET `/api/v1/recordings`, GET `/api/v1/recordings/active`, POST `/api/v1/recordings`(log `start`, 상태 recording·id), POST `/api/v1/recordings/active/stop`(log `stop`, idle), GET `/api/v1/recordings/{rid}/archive`(blocker 있으면 409 `{"error":{"code":blocker}}`, 아니면 작은 tar 바이트, `Content-Disposition`), 시험 훅 GET/POST `/__test__/recordings`(`{"log": [...]}` / `{"blocker": ...}`). `PILOT_MIME`에 두 새 자산.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py src/products/omx/adapter/test/test_pilot_sim_api.py -q -p no:cacheprovider`
그리고: `$env:ROSY_RUN_BROWSER_TESTS = '1'; python -m pytest src/hmi/pilot/test/test_pilot_browser.py -q -p no:cacheprovider`
Expected: PASS (Node·Playwright 없으면 해당 시험 skip — 이 경우 브라우저 시험은 Verification에서 반드시 한 번 돌린다)

- [ ] **Step 5: 커밋**

```bash
git add src/hmi/pilot/recording.js src/hmi/pilot/screens/robot-recording.js src/hmi/pilot/client.js src/hmi/pilot/screens/drive.js src/hmi/pilot/styles.css src/hmi/pilot/sw.js src/hmi/pilot/CMakeLists.txt src/runtime/api_web/core_api_web/api/app.py src/products/omx/adapter/omx_adapter/pilot_sim_api.py src/hmi/pilot/test/dev_server.py src/hmi/pilot/test/test_recording_view.py src/hmi/pilot/test/test_pilot_browser.py src/runtime/api_web/test/test_pilot_route.py
git commit -m "feat(pilot): D-411 robot recording toggle and recordings sheet" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task A10: Part A 하네스 기록

**Files:**
- Modify: `src/runtime/sensing/logs.md`, `src/contracts/foundation/logs.md`, `src/runtime/services/logs.md`, `src/runtime/api_web/logs.md`, `src/runtime/gateway/logs.md`, `src/hmi/pilot/logs.md`, `deploy/logs.md` (추가만)
- Modify: 같은 모듈의 `progress.md` — `adrs:`에 `D-411`, `plans:`에 이 계획 경로, `last_verified`
- Modify: `src/hmi/pilot/AGENTS.md` Key Files 표(`recording.js`, `screens/robot-recording.js`)
- Regenerate: 각 모듈 `index.md`, `STATUS.md`

- [ ] **Step 1:** 모듈마다 logs.md 끝에 한 항목(형식 `src/hmi/pilot/logs.md:241-246`):

```
## 2026-10-02 · uncommitted · feat(<module>): D-411 A <한 줄 요약>
- 변경: <이 모듈에서 바뀐 파일과 행동>
- 증거: <Task A1–A9에서 실제로 돌린 명령과 passed/skipped 수>
- gate 변화: SOURCE 유지(또는 GO 근거 갱신). ROS-SIM HOLD — Verification ROS-SIM 체크리스트 미실행.
- 결정: D-411 A.
```

- [ ] **Step 2:** `python tools/harness/rosy_harness.py generate` 후 `python tools/harness/rosy_harness.py lint`
Expected: D-410 선행 결함(Task 0) 하나 외 오류 0
- [ ] **Step 3:** `python -m pytest test/test_harness_contracts.py test/architecture/test_module_structure.py -q`
Expected: `test_repository_adr_log_is_contiguous_and_indexed`(D-410)와 그것에 묶인 lint 시험만 실패, 나머지 PASS
- [ ] **Step 4: 커밋** — 바뀐 `logs.md`·`progress.md`·`index.md`·`STATUS.md`·`AGENTS.md`를 경로로 나열해 `git add` 후:

```bash
git commit -m "docs(harness): D-411 part A module records" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Part B — 조작부 서술자 `rosy.controls/1`

끝 상태: CORE capabilities와 OMX SIM `/target`이 서술자를 내고, Pilot은 서술자로 위젯을 조립한다(구 서버는 기존 Pinky 프로필로 대체, 모르는 kind는 "지원하지 않는 조작부"). OMX 화면에 팔 조이스틱이 있고 이전 목표가 끝난 뒤에만 다음 제한 목표를 보낸다.

### Task B1: 서술자 계약 `core_common.protocol.controls`

**Files:**
- Create: `src/contracts/foundation/core_common/protocol/controls.py`
- Modify: `src/contracts/foundation/core_common/protocol/omx_sim.py:20-27`
- Test: `src/contracts/foundation/test/test_controls_contract.py`, `src/contracts/foundation/test/test_omx_sim_pilot_contract.py`(추가)

- [ ] **Step 1: 실패하는 시험 쓰기**

```python
"""D-411 B: rosy.controls/1 — the device announces its controls; Pilot builds widgets from it."""

import pytest
from pydantic import ValidationError

from core_common.protocol import controls as c


def test_pinky_with_drive_announces_one_base_velocity_control():
    body = c.pinky_controls(provides={"drive", "battery"}, max_linear=0.15, max_angular=0.6)
    assert body == {"schema": "rosy.controls/1", "items": [{
        "id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.15,
        "max_angular": 0.6, "pivot": True, "fine": True, "autonomy": ["line"]}]}


def test_no_drive_no_controls():
    assert c.pinky_controls(provides=set(), max_linear=0.15, max_angular=0.6)["items"] == []


def test_joint_jog_is_bounded_goal_with_limits():
    jog = c.JointJogControl(id="arm", label="팔", joints=[{"name": "joint1", "lower": -1.0, "upper": 1.0}],
                            max_step_rad=0.05, duration_s=0.4)
    assert jog.command == "bounded_goal"
    for bad in ({"max_step_rad": 0.06}, {"duration_s": 1.5}, {"joints": []},
                {"joints": [{"name": "j", "lower": 1.0, "upper": 1.0}]},
                {"joints": [{"name": "j", "lower": 0, "upper": 1}, {"name": "j", "lower": 0, "upper": 1}]}):
        with pytest.raises(ValidationError):
            c.JointJogControl(**{"id": "arm", "label": "팔",
                                 "joints": [{"name": "joint1", "lower": -1.0, "upper": 1.0}],
                                 "max_step_rad": 0.05, "duration_s": 0.4, **bad})


def test_gripper_presets_stay_between_open_and_closed():
    grip = c.GripperControl(id="gripper", label="그리퍼", joint="gripper_joint_1", closed=0.0, open=1.0,
                            presets={"open": 1.0, "half": 0.5, "close": 0.0})
    assert grip.unit == "rad" and grip.readback == ("position", "grasp")
    with pytest.raises(ValidationError):
        c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.0, open=1.0,
                         presets={"open": 1.2, "half": 0.5, "close": 0.0})
    with pytest.raises(ValidationError):
        c.GripperControl(id="gripper", label="그리퍼", joint="g", closed=0.5, open=0.5,
                         presets={"open": 0.5, "half": 0.5, "close": 0.5})


def test_descriptor_discriminates_kinds_and_rejects_duplicate_ids():
    body = {"schema": "rosy.controls/1", "items": [
        {"id": "base", "kind": "base_velocity", "label": "주행", "max_linear": 0.1, "max_angular": 0.5,
         "pivot": False, "fine": False}]}
    parsed = c.ControlsDescriptor.model_validate(body)
    assert isinstance(parsed.items[0], c.BaseVelocityControl)
    with pytest.raises(ValidationError):
        c.ControlsDescriptor.model_validate({**body, "items": body["items"] * 2})
    with pytest.raises(ValidationError):
        c.ControlsDescriptor.model_validate({**body, "items": [{"id": "x", "kind": "laser", "label": "x"}]})
```

`test_omx_sim_pilot_contract.py`에 추가:

```python
def test_target_may_carry_a_controls_descriptor():
    from core_common.protocol.controls import ControlsDescriptor
    descriptor = ControlsDescriptor(items=())
    target = OmxSimTarget(instance_id="omx_01", joints=("joint1",), gripper="gripper_joint_1",
                          controls=descriptor)
    assert target.model_dump(by_alias=True)["controls"] == {"schema": "rosy.controls/1", "items": ()}
```

(서버가 모르는 kind를 **내보내지** 않음을 스키마가 보장한다. "모르는 kind에서 멈추지 않는다"는 Pilot 쪽 시험(Task B4·B5)이 본다.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/contracts/foundation/test/test_controls_contract.py src/contracts/foundation/test/test_omx_sim_pilot_contract.py -q`
Expected: FAIL — `ImportError: cannot import name 'controls'`

- [ ] **Step 3: 구현** — `controls.py`:

```python
"""D-411 B: rosy.controls/1 — a device announces the controls it accepts (D-323, D-366).

Drivers only transport; Pilot has one widget per kind. Arm controls are bounded goals
issued one after another, never a 100 ms stream (D-390 §2).
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTROLS_SCHEMA = "rosy.controls/1"
_ID = r"^[a-z][a-z0-9_]{0,31}$"


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class BaseVelocityControl(_Wire):
    id: str = Field(pattern=_ID)
    kind: Literal["base_velocity"] = "base_velocity"
    label: str = Field(min_length=1, max_length=40)
    max_linear: float = Field(gt=0, le=2.0)
    max_angular: float = Field(gt=0, le=6.0)
    pivot: bool
    fine: bool
    autonomy: tuple[Literal["line"], ...] = ()


class JointRange(_Wire):
    name: str = Field(min_length=1, max_length=64)
    lower: float
    upper: float

    @model_validator(mode="after")
    def _ordered(self) -> "JointRange":
        if not (math.isfinite(self.lower) and math.isfinite(self.upper) and self.lower < self.upper):
            raise ValueError("joint range must be finite with lower < upper")
        return self


class JointJogControl(_Wire):
    id: str = Field(pattern=_ID)
    kind: Literal["joint_jog"] = "joint_jog"
    label: str = Field(min_length=1, max_length=40)
    joints: tuple[JointRange, ...] = Field(min_length=1, max_length=8)
    max_step_rad: float = Field(gt=0, le=0.05)
    duration_s: float = Field(ge=0.1, le=1.0)
    command: Literal["bounded_goal"] = "bounded_goal"

    @model_validator(mode="after")
    def _unique(self) -> "JointJogControl":
        names = [joint.name for joint in self.joints]
        if len(set(names)) != len(names):
            raise ValueError("joint names must be unique")
        return self


class GripperPresets(_Wire):
    open: float
    half: float
    close: float


class GripperControl(_Wire):
    id: str = Field(pattern=_ID)
    kind: Literal["gripper"] = "gripper"
    label: str = Field(min_length=1, max_length=40)
    joint: str = Field(min_length=1, max_length=64)
    closed: float
    open: float
    unit: Literal["rad"] = "rad"
    presets: GripperPresets
    readback: tuple[Literal["position", "grasp"], ...] = ("position", "grasp")

    @model_validator(mode="after")
    def _within(self) -> "GripperControl":
        low, high = sorted((self.closed, self.open))
        if not (math.isfinite(low) and math.isfinite(high)) or low == high:
            raise ValueError("open and closed must be finite and differ")
        if any(not low <= value <= high for value in (self.presets.open, self.presets.half, self.presets.close)):
            raise ValueError("presets must lie between closed and open")
        return self


Control = Annotated[Union[BaseVelocityControl, JointJogControl, GripperControl], Field(discriminator="kind")]


class ControlsDescriptor(_Wire):
    schema_id: Literal["rosy.controls/1"] = Field(CONTROLS_SCHEMA, alias="schema")
    items: tuple[Control, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _ids(self) -> "ControlsDescriptor":
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("control ids must be unique")
        return self


def pinky_controls(*, provides, max_linear: float, max_angular: float) -> dict:
    """Pinky's controls from its adapter manifest's `provides` (D-411 §8)."""
    items = []
    if "drive" in provides:
        items.append(BaseVelocityControl(id="base", label="주행", max_linear=max_linear,
                                         max_angular=max_angular, pivot=True, fine=True,
                                         autonomy=("line",)))
    return ControlsDescriptor(items=tuple(items)).model_dump(by_alias=True, mode="json")
```

(`mode="json"`이라 튜플이 리스트가 된다 — 시험의 `"autonomy": ["line"]`·`"items": []`와 맞다. `omx_sim.py` 시험은 `model_dump(by_alias=True)`라 튜플 그대로다.)

`omx_sim.py`: import `from core_common.protocol.controls import ControlsDescriptor`, `OmxSimTarget`(20-27)에 `controls: ControlsDescriptor | None = None`.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/contracts/foundation/test -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/contracts/foundation/core_common/protocol/controls.py src/contracts/foundation/core_common/protocol/omx_sim.py src/contracts/foundation/test/test_controls_contract.py src/contracts/foundation/test/test_omx_sim_pilot_contract.py
git commit -m "feat(core_common): D-411 rosy.controls/1 descriptor contract" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B2: CORE capabilities `controls`

**Files:**
- Modify: `src/runtime/api_web/core_api_web/api/v1/system.py:186-207`
- Modify: `src/runtime/api_web/core_api_web/api/deps.py:75-100` (`adapter_registry: Any`)
- Modify: `docs/reference/ROSY API & Protocol Reference.md` §5.1 capabilities 행, §11 v1.76 행
- Test: `src/runtime/gateway/test/test_capabilities_controls.py`

`provides` 출처: 켜진 adapter manifest가 있으면 그 `provides` 합집합. **현재 CORE 설정은 manifest가 비어 있다**(`rosy_default.yaml:31` `manifests: []`, 기기 오버레이도 목록을 주지 않는다 — 목록은 `commission-pinky.py`만 읽는다). 그때는 capability의 `teleop`이 참이면 `{"drive"}`로 본다 — Pinky manifest가 `drive`를 내는 것과 같은 사실이다(`src/products/pinky_pro/bringup/config/adapter.manifest.yaml:6`). 어느 경우든 `teleop`이 보류되면 `drive`를 뺀다.

- [ ] **Step 1: 실패하는 시험 쓰기**

```python
"""D-411 B: CORE announces Pinky's controls from adapter provides (or teleop)."""

from core_common.domain.adapters import AdapterManifest, AdapterRegistry

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


def _controls(client):
    return client.get("/api/v1/system/capabilities", headers=VIEWER).json()["controls"]


def test_teleop_capable_core_announces_base_velocity(core_client):
    client, svc = core_client()
    controls = _controls(client)
    assert controls["schema"] == "rosy.controls/1"
    (base,) = controls["items"]
    assert base["kind"] == "base_velocity" and base["autonomy"] == ["line"]
    assert base["max_linear"] == svc.safety.limits.manual_linear


def test_manifest_without_drive_announces_nothing(core_client):
    client, svc = core_client()
    svc.adapter_registry = AdapterRegistry([AdapterManifest(id="omx", provides=())])
    assert _controls(client)["items"] == []


def test_withheld_teleop_drops_the_drive_control(core_client):
    client, svc = core_client()
    svc.capability._data["teleop"] = False
    assert _controls(client)["items"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/runtime/gateway/test/test_capabilities_controls.py -q`
Expected: FAIL — `KeyError: 'controls'`

- [ ] **Step 3: 구현** — `system.py` import `from core_common.protocol.controls import pinky_controls`, `capabilities()`의 `return data` 앞:

```python
    # `controls` (v1.76 additive, D-411 B): rosy.controls/1, what Pilot may draw.
    data["controls"] = pinky_controls(provides=_drive_provides(svc, data),
                                      max_linear=svc.safety.limits.manual_linear,
                                      max_angular=svc.safety.limits.manual_angular)
```

모듈 함수:

```python
def _drive_provides(svc: CoreServicesLike, data: dict) -> set[str]:
    enabled = svc.adapter_registry.enabled()
    provides = ({p for item in enabled for p in item.provides} if enabled
                else ({"drive"} if data.get("teleop") is True else set()))
    if data.get("teleop") is not True:
        provides.discard("drive")
    return provides
```

`deps.py` `CoreServicesLike`에 `adapter_registry: Any`. API Ref §5.1 capabilities 행 끝에 "`controls`(v1.76, D-411): `rosy.controls/1` `{schema, items[]}` — Pinky는 adapter `provides`의 `drive`(manifest가 없으면 `teleop`)에서 `base_velocity` 하나. 스키마 정본 `core_common.protocol.controls`", §11 v1.76 행에 "B: capabilities `controls`" 덧붙임.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/runtime/gateway/test/test_capabilities_controls.py src/runtime/gateway/test/test_api.py src/runtime/gateway/test/test_protocol_version_alignment.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/runtime/api_web/core_api_web/api/v1/system.py src/runtime/api_web/core_api_web/api/deps.py src/runtime/gateway/test/test_capabilities_controls.py "docs/reference/ROSY API & Protocol Reference.md"
git commit -m "feat(core): D-411 capabilities announce rosy.controls/1" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B3: OMX SIM `/target`의 `controls`

**Files:**
- Modify: `src/products/omx/adapter/omx_adapter/pilot_sim_runtime.py:13-26` (`controls()`)
- Modify: `src/products/omx/adapter/omx_adapter/pilot_sim_api.py:182-188`
- Modify: `src/products/omx/adapter/omx_adapter/pilot_sim_server.py:41-43` (출처 해시)
- Test: `src/products/omx/adapter/test/test_pilot_sim_runtime.py`, `test_pilot_sim_api.py`(추가)

Part B 동안 그리퍼는 **기존처럼 관절 조그 대상**이다(지금 `submit`이 그리퍼 관절을 받는다, `pilot_sim_runtime.py:56`). 그래서 B의 `joint_jog`는 그리퍼 관절까지 담는다. Part C가 그리퍼를 빼고 `gripper` 조작부를 더한다.

- [ ] **Step 1: 실패하는 시험 쓰기**

`test_pilot_sim_runtime.py`:

```python
def test_controls_announce_a_bounded_joint_jog_with_limits():
    from core_common.protocol.controls import ControlsDescriptor
    descriptor = ControlsDescriptor.model_validate(PilotSimRuntime(Arm()).controls())
    (jog,) = descriptor.items
    assert jog.kind == "joint_jog" and jog.max_step_rad == 0.05 and jog.duration_s == 0.4
    assert [(j.name, j.lower, j.upper) for j in jog.joints] == [("joint1", -1, 1), ("gripper_joint_1", -0.1, 0.1)]
```

`test_pilot_sim_api.py` — `FakeRuntime`에 `def controls(self): return {"schema": "rosy.controls/1", "items": []}` 추가, 그리고:

```python
def test_target_carries_the_runtime_controls():
    client, _ = _client()
    body = client.get(f"{PREFIX}/target").json()
    assert body["controls"] == {"schema": "rosy.controls/1", "items": []}
    assert body["joints"] == ["joint1", "joint2"] and body["gripper"] == "gripper_joint_1"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/products/omx/adapter/test/test_pilot_sim_runtime.py src/products/omx/adapter/test/test_pilot_sim_api.py -q`
Expected: FAIL — `AttributeError: 'PilotSimRuntime' object has no attribute 'controls'`; `KeyError: 'controls'`

- [ ] **Step 3: 구현**

`pilot_sim_runtime.py`: import `from core_common.protocol.controls import ControlsDescriptor, JointJogControl, JointRange`; 상수 `JOG_MAX_STEP_RAD = 0.05`, `JOG_DURATION_S = 0.4`; 메서드:

```python
    def controls(self) -> dict:
        """rosy.controls/1 for this SIM workcell (D-411 B). Bounded goals only (D-390 §2)."""
        limits = self.arm.owner.config.position_limits
        jog = JointJogControl(id="arm", label="팔", max_step_rad=JOG_MAX_STEP_RAD, duration_s=JOG_DURATION_S,
                              joints=tuple(JointRange(name=n, lower=limits[n][0], upper=limits[n][1])
                                           for n in self.joint_names))
        return ControlsDescriptor(items=(jog,)).model_dump(by_alias=True, mode="json")
```

`pilot_sim_api.py:182-188` `target()`에 `controls=runtime.controls() if hasattr(runtime, "controls") else None,`.
`pilot_sim_server.py:43` 뒤: `source_hasher.update((repo / "src/contracts/foundation/core_common/protocol/controls.py").read_bytes())` (omx_sim이 이제 controls를 import한다 — 시연 출처 해시에 포함).

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/products/omx/adapter/test -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/products/omx/adapter/omx_adapter/pilot_sim_runtime.py src/products/omx/adapter/omx_adapter/pilot_sim_api.py src/products/omx/adapter/omx_adapter/pilot_sim_server.py src/products/omx/adapter/test/test_pilot_sim_runtime.py src/products/omx/adapter/test/test_pilot_sim_api.py
git commit -m "feat(omx_adapter): D-411 SIM target announces rosy.controls/1" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B4: Pilot 순수 모듈 `controls.js`, `arm-stick.js`

**Files:**
- Create: `src/hmi/pilot/controls.js`, `src/hmi/pilot/arm-stick.js`
- Test: `src/hmi/pilot/test/test_controls.py`, `src/hmi/pilot/test/test_arm_stick.py`

**떼면 취소(D-411 §10) 조정:** OMX `ArmCommandOwner.cancel()`은 소유자를 HOLD로 걸고(`command_owner.py:535-544`, `_enter_hold("cancel_requested")`), 풀려면 `recover(operator_confirmed=True, ...)`가 필요한데 Pilot SIM API에는 recover 경로가 없다. 떼는 순간마다 취소하면 첫 손 떼기 뒤 팔이 다시 움직일 수 없다. 그래서 조거는 손을 떼면 **다음 목표 발행을 즉시 끊고**, 이미 나간 목표(≤ `max_step_rad` 0.05 rad, `duration_s` 0.4 s)는 끝까지 둔다. 명시적 "진행 중 명령 취소" 버튼(HOLD를 거는 비상 경로)은 그대로 남긴다. 이 조정은 ADR에 부록으로 적는다(Task B6).

두 축 동시 기울임: 목표 하나는 관절 하나(`OmxSimJog.joint`)라 **우세 축** 하나만 보낸다.

- [ ] **Step 1: 실패하는 시험 쓰기**

`test_arm_stick.py`(Node 패턴, 모듈 `arm-stick.js`):

```python
def test_axes_from_offset_clamps_and_flips_y():
    out = _run_js("console.log(JSON.stringify([m.axesFromOffset(50, -50, 100), m.axesFromOffset(300, 0, 100)]))")
    assert out == [{"x": 0.5, "y": 0.5}, {"x": 1, "y": 0}]


def test_step_uses_the_dominant_axis_scaled_past_the_deadzone():
    out = _run_js("""
const map = {x: 'joint1', y: 'joint2'};
console.log(JSON.stringify([
  m.stepFor({x: 0.1, y: 0.05}, map, 0.05),
  m.stepFor({x: 1, y: 0.3}, map, 0.05),
  m.stepFor({x: 0.2, y: -1}, map, 0.05),
  m.stepFor({x: 0.575, y: 0}, map, 0.05),
]))""")
    assert out[0] is None
    assert out[1] == {"joint": "joint1", "delta": 0.05}
    assert out[2] == {"joint": "joint2", "delta": -0.05}
    assert out[3] == {"joint": "joint1", "delta": 0.025}


def test_jogger_sends_the_next_goal_only_after_the_previous_settles():
    out = _run_js("""
const sent = [];
const jog = m.createArmJogger({submit: async (step) => { sent.push(step); return true; },
                               mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
jog.move({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
const beforeSettle = sent.length;
jog.settled('SUCCEEDED');
await new Promise((r) => setTimeout(r, 0));
const afterSettle = sent.length;
const released = jog.release();
jog.settled('SUCCEEDED');
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({beforeSettle, afterSettle, released, final: sent.length, state: jog.state()}));
""")
    assert out["beforeSettle"] == 1 and out["afterSettle"] == 2
    assert out["released"] == {"inFlight": True}
    assert out["final"] == 2 and out["state"] == {"pressed": False, "inFlight": False}


def test_a_failed_goal_stops_the_jogger_until_pressed_again():
    out = _run_js("""
const sent = [];
const jog = m.createArmJogger({submit: async (s) => { sent.push(s); return true; },
                               mapping: {x: 'joint1', y: 'joint2'}, maxStep: 0.05});
jog.press({x: 1, y: 0});
await new Promise((r) => setTimeout(r, 0));
jog.settled('UNKNOWN_HOLD');
await new Promise((r) => setTimeout(r, 0));
console.log(JSON.stringify({sent: sent.length, state: jog.state()}));
""")
    assert out == {"sent": 1, "state": {"pressed": False, "inFlight": False}}
```

(`_run_js`는 `test_recording_view.py`와 같고 `MODULE`만 `arm-stick.js`.)

`test_controls.py`(모듈 `controls.js`):

```python
def test_read_controls_accepts_only_the_v1_schema():
    out = _run_js("""console.log(JSON.stringify([
      m.readControls({schema: 'rosy.controls/1', items: [{id: 'base', kind: 'base_velocity'}]}),
      m.readControls({schema: 'rosy.controls/2', items: []}),
      m.readControls(undefined),
    ]))""")
    assert out[0] == [{"id": "base", "kind": "base_velocity"}] and out[1] is None and out[2] is None


def test_widget_plan_marks_unknown_kinds_unsupported_without_throwing():
    out = _run_js("""console.log(JSON.stringify(m.widgetPlan(
      [{id: 'base', kind: 'base_velocity'}, {id: 'x', kind: 'laser', label: '레이저'}], ['base_velocity'])))""")
    assert [p["supported"] for p in out] == [True, False]


def test_pinky_fallback_and_profile_round_trip():
    out = _run_js("""
const items = m.fallbackPinkyControls({kind: 'base', command: 'velocity', pivot: true, fine: true, autonomy: ['line']});
console.log(JSON.stringify([items, m.profileFromBaseVelocity(items[0]),
  m.profileFromBaseVelocity({kind: 'base_velocity', pivot: false, fine: true, autonomy: []})]))""")
    assert out[0][0]["kind"] == "base_velocity"
    assert out[1] == {"kind": "base", "command": "velocity", "pivot": True, "fine": True, "autonomy": ["line"]}
    assert out[2]["pivot"] is False and out[2]["autonomy"] == []


def test_omx_fallback_keeps_the_legacy_gripper_jog():
    out = _run_js("""console.log(JSON.stringify(m.fallbackOmxControls(
      {joints: ['joint1', 'joint2'], gripper: 'gripper_joint_1'})))""")
    (jog,) = out
    assert jog["kind"] == "joint_jog" and jog["max_step_rad"] == 0.02
    assert [j["name"] for j in jog["joints"]] == ["joint1", "joint2", "gripper_joint_1"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/hmi/pilot/test/test_controls.py src/hmi/pilot/test/test_arm_stick.py -q`
Expected: FAIL — `ENOENT: no such file ... controls.js` / `arm-stick.js`

- [ ] **Step 3: 구현**

`arm-stick.js`(import 없음):

```js
// D-411 B: arm joystick — sequential bounded goals (D-390 §2). No DOM, no fetch, no clock.
// Release stops issuing; a goal already sent (<= max step, 0.4 s) finishes: OMX cancel
// latches the owner in HOLD and the SIM API has no recover path (plan B4).
export const DEADZONE = 0.15;
const TERMINAL_OK = "SUCCEEDED";

const clamp = (v) => Math.max(-1, Math.min(1, v));
const round4 = (v) => Math.round(v * 1e4) / 1e4;

export function axesFromOffset(dx, dy, radius) {
  const r = radius > 0 ? radius : 1;
  return {x: round4(clamp(dx / r)), y: round4(clamp(-dy / r))};
}

export function stepFor(axes, mapping, maxStep, deadzone = DEADZONE) {
  const ax = Math.abs(axes?.x ?? 0), ay = Math.abs(axes?.y ?? 0);
  const [axis, value] = ax >= ay ? ["x", axes?.x ?? 0] : ["y", axes?.y ?? 0];
  const magnitude = Math.abs(value);
  if (magnitude <= deadzone || !mapping?.[axis]) return null;
  const delta = round4(Math.sign(value) * maxStep * Math.min(1, (magnitude - deadzone) / (1 - deadzone)));
  return delta === 0 ? null : {joint: mapping[axis], delta};
}

export function createArmJogger({submit, mapping, maxStep, deadzone = DEADZONE}) {
  let pressed = false, inFlight = false, axes = {x: 0, y: 0};
  async function pump() {
    if (!pressed || inFlight) return;
    const step = stepFor(axes, mapping, maxStep, deadzone);
    if (!step) return;
    inFlight = true;
    let ok = false;
    try { ok = await submit(step); } catch { ok = false; }
    if (!ok) { inFlight = false; pressed = false; }
  }
  return {
    press(next) { pressed = true; axes = next; pump(); },
    move(next) { axes = next; pump(); },
    release() { const was = inFlight; pressed = false; axes = {x: 0, y: 0}; return {inFlight: was}; },
    settled(state) { inFlight = false; if (state !== TERMINAL_OK) pressed = false; pump(); },
    state: () => ({pressed, inFlight}),
  };
}
```

`controls.js`(import 없음; Part C에서 그리퍼 함수 추가):

```js
// D-411 B: rosy.controls/1 on the Pilot side. Drivers only transport; one widget per kind.
export const CONTROLS_SCHEMA = "rosy.controls/1";

export function readControls(descriptor) {
  if (!descriptor || descriptor.schema !== CONTROLS_SCHEMA || !Array.isArray(descriptor.items)) return null;
  return descriptor.items.filter((item) => item && typeof item.kind === "string" && typeof item.id === "string");
}

export function widgetPlan(items, kinds) {
  const known = new Set(kinds);
  return (items ?? []).map((control) => ({control, supported: known.has(control.kind)}));
}

export function fallbackPinkyControls(profile) {
  return [{id: "base", kind: "base_velocity", label: "주행", max_linear: null, max_angular: null,
           pivot: profile?.pivot !== false, fine: profile?.fine !== false,
           autonomy: [...(profile?.autonomy ?? [])]}];
}

export function profileFromBaseVelocity(control) {
  return {kind: "base", command: "velocity", pivot: control.pivot !== false,
          fine: control.fine !== false, autonomy: [...(control.autonomy ?? [])]};
}

export function fallbackOmxControls(target) {
  const names = [...(target?.joints ?? []), ...(target?.gripper ? [target.gripper] : [])];
  return [{id: "arm", kind: "joint_jog", label: "팔", max_step_rad: 0.02, duration_s: 0.4,
           command: "bounded_goal", joints: names.map((name) => ({name, lower: null, upper: null}))}];
}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/hmi/pilot/test/test_controls.py src/hmi/pilot/test/test_arm_stick.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/hmi/pilot/controls.js src/hmi/pilot/arm-stick.js src/hmi/pilot/test/test_controls.py src/hmi/pilot/test/test_arm_stick.py
git commit -m "feat(pilot): D-411 controls descriptor reader and sequential arm jogger" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B5: 위젯 조립과 팔 조이스틱 화면

**Files:**
- Create: `src/hmi/pilot/screens/compose.js`, `src/hmi/pilot/widgets/joint_jog.js`
- Modify: `src/hmi/pilot/screens/arm.js` (전체 재구성, 193줄)
- Modify: `src/hmi/pilot/app.js:20-37` (`showDrive`), `src/hmi/pilot/screens/connect.js:210` (`onEnter`에 capabilities), `src/hmi/pilot/screens/drive.js:29-39` (`profile` 옵션·미지원 표시)
- Modify: `src/hmi/pilot/styles.css` (`.arm-controls` 그리드: 왼손 `joint_jog`, 오른손 `gripper`; `[data-arm-pad]`; `[data-control-unsupported]`)
- Modify: 자산 등록 다섯 곳 — `controls.js`·`arm-stick.js`(최상위, CMake FILES), `screens/compose.js`, `widgets/joint_jog.js`(새 디렉터리: CMake `install(DIRECTORY ... widgets ...)`); `sw.js` `CACHE` → `rosy-pilot-shell-2026-10-02-2`
- Modify: `src/hmi/pilot/test/test_pilot_browser.py`, `src/products/omx/adapter/test/test_pilot_sim_browser.py`, `src/runtime/api_web/test/test_pilot_route.py`, `src/hmi/pilot/test/dev_server.py` (capabilities에 `controls`, 시험 훅으로 미지 kind 주입)

- [ ] **Step 1: 실패하는 시험 쓰기** — `test_pilot_browser.py`:

```python
@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_unknown_control_kind_is_shown_not_fatal(base_url, tablet_page):
    page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls", data={"extra": {"id": "laser", "kind": "laser", "label": "레이저"}})
    _enter_drive(page, base_url)
    assert page.locator("[data-control-unsupported]").inner_text().strip() == "지원하지 않는 조작부 · 레이저"
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_old_core_without_controls_falls_back_to_the_pinky_profile(base_url, tablet_page):
    page, errors = tablet_page
    page.request.post(f"{base_url}/__test__/controls", data={"omit": True})
    _enter_drive(page, base_url)
    assert page.locator("[data-drive-stage]").count() == 1
    assert errors == [], errors
```

`_enter_drive` 기존 시험 전부는 descriptor가 있는 기본 상태로 계속 통과해야 한다. OMX 쪽(`test_pilot_browser.py:27-105`의 `mountArm` 직접 마운트 패턴)에 조이스틱 시험:

```python
@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_arm_joystick_sends_bounded_goals_one_at_a_time(base_url, tablet_page):
    page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    result = page.evaluate("""async () => {
      const {mountArm} = await import('/pilot/assets/screens/arm.js');
      const goals = []; let terminal = 'RUNNING';
      const target = {kind: 'omx_sim', simulation: true, instance_id: 'omx_01', joints: ['joint1', 'joint2'],
        gripper: 'gripper_joint_1', controls: {schema: 'rosy.controls/1', items: [{id: 'arm', kind: 'joint_jog',
        label: '팔', max_step_rad: 0.05, duration_s: 0.4, command: 'bounded_goal',
        joints: [{name: 'joint1', lower: -1, upper: 1}, {name: 'joint2', lower: -1, upper: 1}]}]}};
      const driver = {request: async (path, options = {}) => {
        if (path === '/pair') return {token: 't'};
        if (path === '/whoami') return {role: 'operator'};
        if (path === '/seat') return {seat_id: 's'};
        if (path.startsWith('/seat/')) return {seat_id: 's'};
        if (path === '/state') return {ready: true, state_sequence: 1, positions: {joint1: 0, joint2: 0, gripper_joint_1: 0}};
        if (path === '/goals') { const body = JSON.parse(options.body); goals.push(body); return {command_id: body.request_id, state: 'LOCAL_ACCEPTED'}; }
        if (path.startsWith('/goals/')) return {state: terminal};
        return {};
      }};
      const root = document.createElement('div'); document.body.append(root);
      sessionStorage.setItem(`rosy.pilot.omx-sim.${location.origin}`, 't');
      mountArm(root, target, driver);
      await new Promise((r) => setTimeout(r, 300));
      const pad = root.querySelector('[data-arm-pad]');
      const box = pad.getBoundingClientRect();
      pad.dispatchEvent(new PointerEvent('pointerdown', {clientX: box.right, clientY: box.top + box.height / 2, pointerId: 1, bubbles: true}));
      await new Promise((r) => setTimeout(r, 300));
      const whileRunning = goals.length;
      terminal = 'SUCCEEDED';
      await new Promise((r) => setTimeout(r, 1300));
      pad.dispatchEvent(new PointerEvent('pointerup', {pointerId: 1, bubbles: true}));
      const atRelease = goals.length;
      await new Promise((r) => setTimeout(r, 1300));
      return {whileRunning, atRelease, after: goals.length, deltas: goals.map((g) => g.delta_rad), joint: goals[0]?.joint};
    }""")
    assert result["whileRunning"] == 1
    assert result["atRelease"] >= 2 and result["after"] == result["atRelease"]
    assert all(0 < d <= 0.05 for d in result["deltas"]) and result["joint"] == "joint1"
    assert errors == [], errors
```

`test_pilot_sim_browser.py`의 기존 조그 버튼 시험(`data-sim-delta`, `data-sim-joint`)은 그대로 통과해야 한다 — `joint_jog` 위젯이 같은 data 속성을 유지한다.

- [ ] **Step 2: 실패 확인**

Run: `$env:ROSY_RUN_BROWSER_TESTS = '1'; python -m pytest src/hmi/pilot/test/test_pilot_browser.py src/products/omx/adapter/test/test_pilot_sim_browser.py -q -p no:cacheprovider -k "unknown_control or old_core or joystick or sim"`
Expected: FAIL — `[data-control-unsupported]` 없음, `[data-arm-pad]` 없음

- [ ] **Step 3: 구현**

`screens/compose.js`:

```js
// D-411 B: build a control surface from rosy.controls/1. Unknown kinds are shown, never fatal.
import {widgetPlan} from "../controls.js";

export function composeControls(root, items, widgets, context) {
  const disposers = [];
  for (const {control, supported} of widgetPlan(items, Object.keys(widgets))) {
    const slot = document.createElement("section");
    slot.dataset.control = control.kind;
    slot.dataset.controlId = control.id;
    root.append(slot);
    if (!supported) {
      slot.dataset.controlUnsupported = "";
      slot.textContent = `지원하지 않는 조작부 · ${control.label || control.kind}`;
      continue;
    }
    const dispose = widgets[control.kind](slot, control, context);
    if (typeof dispose === "function") disposers.push(dispose);
  }
  return () => { disposers.forEach((dispose) => dispose()); root.replaceChildren(); };
}
```

`arm.js` 재구성(서명 유지 `export function mountArm(root, target, driver)`):
- 마크업에서 `data-sim-controls` 안의 관절 select·±버튼·그리퍼 버튼을 `<div class="arm-controls" data-sim-widgets></div>`로 바꾼다. `data-sim-cancel`, `data-sim-readback`, 기록 패널, 페어링은 그대로.
- 세션 컨텍스트:

```js
  const listeners = new Set();
  const session = {
    target,
    state: () => state,
    busy: () => Boolean(active),
    onUpdate(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    async submitJog(joint, delta, durationS = 0.4) { /* 기존 jog() 본문, 성공 시 command_id 반환, 실패 시 showError 후 null */ },
    async submitGripper(position, durationS) { /* Part C */ return null; },
  };
```

- `refresh()`(82): 활성 goal이 종결 상태(`SUCCEEDED|REJECTED|CANCELED|UNKNOWN_HOLD`)가 되면 `active=""` 전에 `listeners.forEach((fn) => fn({state, settled: {commandId, state: goal.state}}))`; 아니면 `fn({state, settled: null})`. 조이스틱이 종결을 1 s 하트비트보다 빨리 알도록, `active`가 있으면 `refresh`를 250 ms 간격 타이머로도 돈다(활성 goal이 없으면 멈춤).
- `showError`(52)는 `[data-sim-widgets] ui-button, [data-sim-widgets] input`을 비활성화.
- 조립: `const items = readControls(target.controls) ?? fallbackOmxControls(target); disposeWidgets = composeControls($("[data-sim-widgets]"), items, {joint_jog: mountJointJog}, session);` (Part C에서 `gripper: mountGripper` 추가). 반환 dispose에서 `disposeWidgets()`.

`widgets/joint_jog.js`(약 120줄):

```js
// D-411 B: joint jog widget — ± buttons for one joint and a two-axis pad. Bounded goals only.
import {axesFromOffset, createArmJogger} from "../arm-stick.js";

export function mountJointJog(slot, control, session) {
  // markup: <label>관절 <select data-sim-joint></select></label>
  //   <div class="sim-jog"><ui-button data-sim-delta="-STEP">− STEP rad</ui-button>
  //                        <ui-button data-sim-delta="STEP">+ STEP rad</ui-button></div>
  //   <label>좌우 <select data-arm-axis="x"></select></label> <label>상하 <select data-arm-axis="y"></select></label>
  //   <div data-arm-pad role="application" aria-label="팔 조이스틱"></div>
  // STEP = min(0.02, control.max_step_rad) for the buttons (current behaviour), the pad uses max_step_rad.
  // pad mapping defaults: x → joints[0], y → joints[1] (or joints[0] when only one); selects change it.
  // jogger = createArmJogger({submit: async ({joint, delta}) => Boolean(await session.submitJog(joint, delta, control.duration_s)),
  //                           mapping, maxStep: control.max_step_rad});
  // pointerdown → setPointerCapture, jogger.press(axesFromOffset(dx, dy, radius)); pointermove → jogger.move(...);
  // pointerup / pointercancel / lostpointercapture / document hidden → jogger.release().
  // session.onUpdate(({settled}) => settled && jogger.settled(settled.state));
  // buttons disabled while session.busy() or !session.state()?.ready (updated in onUpdate).
  return () => { /* release, remove listeners, unsubscribe */ };
}
```

`connect.js:210` → `enter.addEventListener("click", () => onEnter?.({role: me.body?.role, capabilities: caps.body ?? {}}));`

`app.js` `showDrive`:

```js
function showDrive({capabilities} = {}) {
  document.body.dataset.pilotScreen = "drive";
  connectRoot.hidden = true;
  driveRoot.hidden = false;
  const items = readControls(capabilities?.controls) ?? fallbackPinkyControls(pinkyCore.profile);
  const plan = widgetPlan(items, ["base_velocity"]);
  const base = plan.find((entry) => entry.supported)?.control;
  if (!base) {
    driveRoot.replaceChildren(Object.assign(document.createElement("p"), {
      textContent: "이 기기는 주행 조작부를 알리지 않습니다"}));
    return;
  }
  mountDrive(driveRoot, {
    profile: profileFromBaseVelocity(base),
    unsupported: plan.filter((entry) => !entry.supported).map((entry) => entry.control),
    onExit: () => { driveRoot.hidden = true; showConnect(); },
  });
}
```

`drive.js:29-31` → `export function mountDrive(root, {onExit, profile: given, unsupported = []} = {})`, `const profile = given ?? gate.profile ?? {};`. `root.replaceChildren(...)`(39) 뒤에 미지원 표시:

```js
  for (const control of unsupported) {
    const note = el("p", `지원하지 않는 조작부 · ${control.label || control.kind}`, {"data-control-unsupported": ""});
    root.querySelector("[data-drive-stage]").append(note);
  }
```

`dev_server.py`: capabilities 응답(189)에 `"controls": _CONTROLS_BODY()` — 기본 `{"schema": "rosy.controls/1", "items": [base_velocity 한 개]}`, 시험 훅 POST `/__test__/controls` `{"extra": item}`(항목 덧붙임) / `{"omit": true}`(키 생략) / `{}`(기본 복원). 각 브라우저 시험 끝에 복원되도록 `base_url` 픽스처 뒤 `autouse` 픽스처에서 `POST /__test__/controls {}`.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py src/products/omx/adapter/test -q -p no:cacheprovider`
그리고: `$env:ROSY_RUN_BROWSER_TESTS = '1'; python -m pytest src/hmi/pilot/test/test_pilot_browser.py src/products/omx/adapter/test/test_pilot_sim_browser.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/hmi/pilot/screens/compose.js src/hmi/pilot/widgets/joint_jog.js src/hmi/pilot/screens/arm.js src/hmi/pilot/app.js src/hmi/pilot/screens/connect.js src/hmi/pilot/screens/drive.js src/hmi/pilot/styles.css src/hmi/pilot/sw.js src/hmi/pilot/CMakeLists.txt src/runtime/api_web/core_api_web/api/app.py src/products/omx/adapter/omx_adapter/pilot_sim_api.py src/hmi/pilot/test/dev_server.py src/hmi/pilot/test/test_pilot_browser.py src/products/omx/adapter/test/test_pilot_sim_browser.py src/runtime/api_web/test/test_pilot_route.py
git commit -m "feat(pilot): D-411 compose controls from rosy.controls/1 and arm joystick" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task B6: Part B 문서·하네스

**Files:**
- Modify: `docs/reference/ROSY API & Protocol Reference.md` §5.9 `/target` 행에 `controls`(v1.76), §11 v1.76 행에 "B: SIM target `controls`"
- Modify: `docs/adr/D-411-pilot-robot-recording-control-descriptor-and-gripper.md` 끝에 `## 구현 부록 (2026-10-02)` — (1) 떼면 다음 목표 발행만 끊고 진행 목표는 끝까지(사유: `command_owner.py:542` HOLD, SIM recover 경로 없음), (2) 두 축 동시 기울임은 우세 축 하나, (3) CORE capabilities의 `provides`는 manifest가 없으면 `teleop`에서 유도, (4) CORE "seat"는 시작 토큰의 `/ws/state` 링크와 다른 토큰 teleop으로 정의
- Modify: `src/hmi/pilot/AGENTS.md` Key Files·Subdirectories(`widgets/`), 모듈 logs/progress(pilot, omx_adapter, core_common, core_api_web)
- Regenerate: `python tools/harness/rosy_harness.py generate`

- [ ] **Step 1:** 위 문서 수정. **Step 2:** `python tools/harness/rosy_harness.py generate; python tools/harness/rosy_harness.py lint` → D-410 외 오류 0. **Step 3:** `python -m pytest src/runtime/gateway/test/test_protocol_version_alignment.py test/test_harness_contracts.py -q` → D-410 항목 외 PASS.
- [ ] **Step 4: 커밋** — 바뀐 파일을 경로로 나열해 `git add` 후 `git commit -m "docs(d411): part B API ref, ADR implementation notes, module records" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

# Part C — OMX 그리퍼

끝 상태: SIM API에 그리퍼 전용 절대 목표가 있고(한계 밖 거절, 같은 owner·seat·HOLD 규칙), readback에 `open|closed|holding|moving|unknown`이 있으며, Pilot 오른손 영역에 열기/반/닫기·열림 %·상태 배지가 있고, 시연 기록과 LeRobot export에 `action.gripper` 열이 있다.

### Task C1: `OmxSimGripperGoal` 계약

**Files:**
- Modify: `src/contracts/foundation/core_common/protocol/omx_sim.py:63` 뒤
- Test: `src/contracts/foundation/test/test_omx_sim_pilot_contract.py`(추가)

- [ ] **Step 1: 실패하는 시험 쓰기**

```python
def _gripper(**changes):
    from core_common.protocol.omx_sim import OmxSimGripperGoal
    body = {"instance_id": "omx_01", "seat_id": "s", "request_id": "r", "position": 0.5,
            "duration_s": 0.8, "state_sequence": 3, "expires_at_ms": 10**13}
    return OmxSimGripperGoal(**{**body, **changes})


def test_gripper_goal_is_absolute_and_duration_bounded():
    assert _gripper().position == 0.5
    for bad in ({"duration_s": 0.1}, {"duration_s": 2.5}, {"position": float("nan")},
                {"position": float("inf")}, {"joint": "x"}):
        with pytest.raises(ValidationError):
            _gripper(**bad)
```

- [ ] **Step 2: 실패 확인** — `python -m pytest src/contracts/foundation/test/test_omx_sim_pilot_contract.py -q` → FAIL `ImportError: cannot import name 'OmxSimGripperGoal'`

- [ ] **Step 3: 구현**

```python
class OmxSimGripperGoal(_Wire):
    """D-411 C: absolute gripper target. Limits are the workcell's; the runtime rejects outside them."""
    instance_id: str = Field(min_length=1, max_length=64)
    seat_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=64)
    position: float
    duration_s: float = Field(ge=0.2, le=2.0)
    state_sequence: int = Field(ge=0)
    expires_at_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def finite_position(self) -> "OmxSimGripperGoal":
        if not math.isfinite(self.position):
            raise ValueError("position must be finite")
        return self
```

- [ ] **Step 4: 통과 확인** — 같은 명령 PASS.
- [ ] **Step 5: 커밋**

```bash
git add src/contracts/foundation/core_common/protocol/omx_sim.py src/contracts/foundation/test/test_omx_sim_pilot_contract.py
git commit -m "feat(core_common): D-411 OmxSimGripperGoal absolute gripper target" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task C2: 그리퍼 판정·런타임·서버 설정

**Files:**
- Create: `src/products/omx/adapter/omx_adapter/pilot_sim_gripper.py`
- Modify: `src/products/omx/adapter/omx_adapter/pilot_sim_runtime.py:14-26` (생성자), `:27-47` (스냅샷), `:49-93` (`_dispatch` 추출), `controls()`
- Modify: `src/products/omx/adapter/omx_adapter/pilot_sim_server.py:51-59, 80`
- Test: `src/products/omx/adapter/test/test_pilot_sim_gripper.py`, `test_pilot_sim_runtime.py`(추가)

열림·닫힘·한계는 시뮬레이션 셀 프로필에서 온다: `deploy/robot/omx/sim/cell_profile.yaml` `gripper: {joint: gripper_joint_1, position: [-0.1, 1.1], open: 1.0, closed: 0.0}` — `CellPlanningProfile.load`(`pose_plan.py:103-107`)가 검증한다. 지금 SIM 서버의 그리퍼 한계 `(-0.5, 0.5)`(`pilot_sim_server.py:55`)는 열림 1.0을 막으므로 프로필 값으로 바꾼다(팔 관절 `(-3.0, 3.0)`은 그대로). 그리퍼 목표는 최대 2.0 s라 `max_goal_duration_s`를 2.0으로 올린다(`OmxSimJog`의 1.0 s 상한은 스키마가 계속 지킨다).

- [ ] **Step 1: 실패하는 시험 쓰기**

`test_pilot_sim_gripper.py`:

```python
"""D-411 C: gripper state from readback and the last gripper goal."""

import pytest

from omx_adapter.pilot_sim_gripper import GRIPPER_TOLERANCE_RAD, gripper_state

OPEN, CLOSED = 1.0, 0.0


def state(position, *, ready=True, goal=None, moved=False):
    return gripper_state(position=position, ready=ready, open_=OPEN, closed=CLOSED, goal=goal,
                         moved_recently=moved)


def test_unknown_without_fresh_readback():
    assert state(None) == "unknown" and state(0.0, ready=False) == "unknown"


@pytest.mark.parametrize("goal_state", ["LOCAL_ACCEPTED", "ROS_ACCEPTED", "RUNNING", "CANCEL_REQUESTED"])
def test_moving_while_a_goal_runs(goal_state):
    assert state(0.4, goal={"target": CLOSED, "state": goal_state}) == "moving"


def test_moving_when_readback_still_changes():
    assert state(0.4, moved=True) == "moving"


def test_closed_and_open():
    assert state(CLOSED + GRIPPER_TOLERANCE_RAD / 2) == "closed"
    assert state(OPEN) == "open" and state(0.5) == "open"


def test_holding_when_a_finished_close_stops_short():
    goal = {"target": CLOSED, "state": "SUCCEEDED"}
    assert state(0.3, goal=goal) == "holding"
    assert state(CLOSED, goal=goal) == "closed"


def test_a_finished_half_goal_is_open_not_holding():
    assert state(0.5, goal={"target": 0.5, "state": "SUCCEEDED"}) == "open"


def test_hold_or_unknown_terminal_is_unknown():
    assert state(0.3, goal={"target": CLOSED, "state": "UNKNOWN_HOLD"}) == "unknown"
```

`test_pilot_sim_runtime.py`에 추가(기존 `Arm`, 그리퍼 한계 `(-0.1, 0.1)`을 쓰므로 open=0.1, closed=0.0으로 생성):

```python
from core_common.protocol.omx_sim import OmxSimGripperGoal


def grip(position, sequence=8, request_id="grip"):
    return OmxSimGripperGoal(instance_id="instance", seat_id="seat", request_id=request_id,
                             position=position, duration_s=0.8, state_sequence=sequence,
                             expires_at_ms=9999999999999)


def _runtime():
    return PilotSimRuntime(Arm(), gripper_open=0.1, gripper_closed=0.0)


def test_gripper_goal_sets_only_the_gripper_absolutely():
    arm = Arm()
    runtime = PilotSimRuntime(arm, gripper_open=0.1, gripper_closed=0.0)
    runtime.snapshot()
    assert runtime.submit_gripper(grip(0.05))["state"] == "LOCAL_ACCEPTED"
    assert arm.commands[0].positions == {"joint1": 0.0, "gripper_joint_1": 0.05}
    assert arm.commands[0].duration_s == 0.8


def test_gripper_goal_outside_limits_is_rejected():
    runtime = _runtime()
    runtime.snapshot()
    assert runtime.submit_gripper(grip(0.2)) == {"command_id": "grip", "state": "REJECTED",
                                                 "reason": "gripper_limit"}


def test_gripper_goal_obeys_the_single_active_goal_rule():
    runtime = _runtime()
    runtime.snapshot()
    runtime.submit(jog())
    assert runtime.submit_gripper(grip(0.05))["reason"] == "goal_active"


def test_jog_no_longer_admits_the_gripper_joint():
    runtime = _runtime()
    runtime.snapshot()
    gripper_jog = OmxSimJog(instance_id="instance", seat_id="seat", request_id="j", joint="gripper_joint_1",
                            delta_rad=0.02, duration_s=0.4, state_sequence=8, expires_at_ms=9999999999999)
    assert runtime.submit(gripper_jog)["reason"] == "joint_not_admitted"


def test_snapshot_reports_gripper_state():
    snap = _runtime().snapshot()
    assert snap["gripper"] == {"joint": "gripper_joint_1", "position": 0.0, "state": "closed",
                               "open": 0.1, "closed": 0.0}


def test_controls_move_the_gripper_out_of_joint_jog():
    from core_common.protocol.controls import ControlsDescriptor
    descriptor = ControlsDescriptor.model_validate(_runtime().controls())
    jog_control, grip_control = descriptor.items
    assert [j.name for j in jog_control.joints] == ["joint1"]
    assert grip_control.kind == "gripper" and grip_control.presets.half == pytest.approx(0.05)
```

(이 파일 상단에 `import pytest`가 없으면 추가.)

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest src/products/omx/adapter/test/test_pilot_sim_gripper.py src/products/omx/adapter/test/test_pilot_sim_runtime.py -q`
Expected: FAIL — `ModuleNotFoundError: omx_adapter.pilot_sim_gripper`; `TypeError: unexpected keyword 'gripper_open'`

- [ ] **Step 3: 구현**

`pilot_sim_gripper.py`:

```python
"""D-411 C: gripper state for the SIM Pilot. ROS-free and policy-only.

holding: a close goal finished but the readback stopped short of closed by more than the
tolerance — the fingers met something. This is SIM evidence, not grip force (D-390 §5).
"""

from __future__ import annotations

GRIPPER_TOLERANCE_RAD = 0.05
STILL_RAD = 0.005
STILL_WINDOW_S = 0.5
_RUNNING = {"LOCAL_ACCEPTED", "ROS_ACCEPTED", "RUNNING", "CANCEL_REQUESTED"}


def gripper_state(*, position: float | None, ready: bool, open_: float, closed: float,
                  goal: dict | None, moved_recently: bool) -> str:
    if not ready or position is None:
        return "unknown"
    if goal is not None and goal["state"] in _RUNNING:
        return "moving"
    if goal is not None and goal["state"] == "UNKNOWN_HOLD":
        return "unknown"
    if moved_recently:
        return "moving"
    if abs(position - closed) <= GRIPPER_TOLERANCE_RAD:
        return "closed"
    if (goal is not None and goal["state"] == "SUCCEEDED"
            and abs(goal["target"] - closed) <= GRIPPER_TOLERANCE_RAD):
        return "holding"
    return "open"
```

`pilot_sim_runtime.py`:
- 생성자 `def __init__(self, arm, *, gripper: str = "gripper_joint_1", gripper_open: float | None = None, gripper_closed: float | None = None)`. 둘 다 주어지면 그리퍼 전용 모드(`self._gripper_spec = (open, closed)`), 아니면 `None`(기존 동작: 그리퍼도 조그 대상 — 기존 시험 보존). `self._gripper_goal: dict | None = None`, `self._gripper_samples: collections.deque(maxlen=32)` of `(received_at, position)`.
- `submit(jog)`: `_dispatch(jog.request_id, jog.instance_id, jog.state_sequence, jog.duration_s, place)`로 옮기고, 조그 대상은 `self._jog_joints()` = 그리퍼 전용 모드면 그리퍼를 뺀 `joint_names`, 아니면 전부. 대상 밖이면 `"joint_not_admitted"`. `place(target, config)`는 `target[joint] += delta` 후 한계 밖이면 `"joint_limit"`.
- `submit_gripper(goal)`: 그리퍼 전용 모드가 아니면 `REJECTED "gripper_not_configured"`. `place`는 `target[self.gripper] = goal.position`, 한계 밖이면 `"gripper_limit"`. 수락되면 `self._gripper_goal = {"command_id": goal.request_id, "target": goal.position}`.
- `_dispatch(request_id, instance_id, state_sequence, duration_s, place)`: 기존 `submit` 49-93의 검사 순서(instance → active → ready → served sequence) 그대로, 이어서 `target = dict(state.positions)`; `reason = place(target, config)`; 그 뒤 `TrajectoryCommand(...)` 생성·등록·`capture.prepare`·`arm.submit` 그대로(`duration_s=duration_s`).
- `snapshot()`: 그리퍼 전용 모드면 `state`가 있을 때 `(state.received_at, positions[gripper])`를 시퀀스가 바뀔 때만 샘플에 넣고, `moved_recently = any(abs(p - current) > STILL_RAD for t, p in samples if now - t <= STILL_WINDOW_S)`. 반환 dict에 `"gripper": {"joint", "position", "state": gripper_state(...), "open", "closed"}` — `goal`은 `_gripper_goal`이 있으면 `{"target": ..., "state": self._goals[command_id]["state"]}`.
- `controls()`: 그리퍼 전용 모드면 `joint_jog`에서 그리퍼를 빼고 `GripperControl(id="gripper", label="그리퍼", joint=self.gripper, closed=closed, open=open_, presets=GripperPresets(open=open_, half=(open_+closed)/2, close=closed))`를 더한다.

`pilot_sim_server.py`:
- import `from .pose_plan import CellPlanningProfile`; `:50` 뒤 `cell = CellPlanningProfile.load(repo / "deploy/robot/omx/sim/cell_profile.yaml")`.
- `position_limits={name: (cell.position_limits[name] if name == cell.gripper_joint else (-3.0, 3.0)) for name in JOINTS}`, `max_goal_duration_s=2.0` (주석: `# D-411 C: gripper goals take up to 2.0 s; OmxSimJog stays <= 1.0 s by schema.`).
- `:80` `facade = PilotSimRuntime(arm, gripper=cell.gripper_joint, gripper_open=cell.gripper_open, gripper_closed=cell.gripper_closed)`.
- `source_hasher`에 `cell_profile.yaml` 바이트도 넣는다(시연 출처).

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/products/omx/adapter/test -q`
Expected: PASS (기존 `test_pilot_sim_runtime.py`는 그리퍼 인자 없이 기존 동작을 유지하므로 그대로 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/products/omx/adapter/omx_adapter/pilot_sim_gripper.py src/products/omx/adapter/omx_adapter/pilot_sim_runtime.py src/products/omx/adapter/omx_adapter/pilot_sim_server.py src/products/omx/adapter/test/test_pilot_sim_gripper.py src/products/omx/adapter/test/test_pilot_sim_runtime.py
git commit -m "feat(omx_adapter): D-411 gripper absolute goal, holding readback, cell-profile limits" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task C3: SIM API `POST /gripper`

**Files:**
- Modify: `src/products/omx/adapter/omx_adapter/pilot_sim_api.py:19-20` (import), `:152` (영수증 타입), `:276-295` (공통 제출)
- Test: `src/products/omx/adapter/test/test_pilot_sim_api.py`(추가)

- [ ] **Step 1: 실패하는 시험 쓰기** — `FakeRuntime`에 `def submit_gripper(self, goal): self.calls.append(goal); return {"command_id": goal.request_id, "state": "LOCAL_ACCEPTED"}` 추가:

```python
def _grip(seat_id, **changes):
    body = {"instance_id": "omx_01", "seat_id": seat_id, "request_id": "grip-1", "position": 0.5,
            "duration_s": 0.8, "state_sequence": 8, "expires_at_ms": int(time.time() * 1000) + 1000}
    return {**body, **changes}


def test_gripper_goal_needs_the_seat_and_is_idempotent():
    client, runtime = _client()
    token = client.post(f"{PREFIX}/pair", json={"code": "ABCD-EFGH"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    seat = client.post(f"{PREFIX}/seat", headers=headers).json()["seat_id"]
    assert client.post(f"{PREFIX}/gripper", json=_grip("other"), headers=headers).status_code == 409
    first = client.post(f"{PREFIX}/gripper", json=_grip(seat), headers=headers)
    again = client.post(f"{PREFIX}/gripper", json=_grip(seat), headers=headers)
    assert first.status_code == again.status_code == 202 and len(runtime.calls) == 1
    reused = client.post(f"{PREFIX}/gripper", json=_grip(seat, position=0.1), headers=headers)
    assert reused.status_code == 409


def test_gripper_and_jog_share_request_ids():
    client, _ = _client()
    token = client.post(f"{PREFIX}/pair", json={"code": "ABCD-EFGH"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    seat = client.post(f"{PREFIX}/seat", headers=headers).json()["seat_id"]
    client.post(f"{PREFIX}/goals", json=_jog(seat, request_id="same"), headers=headers)
    assert client.post(f"{PREFIX}/gripper", json=_grip(seat, request_id="same"), headers=headers).status_code == 409


def test_gripper_duration_out_of_range_is_validation_error():
    client, _ = _client()
    token = client.post(f"{PREFIX}/pair", json={"code": "ABCD-EFGH"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    seat = client.post(f"{PREFIX}/seat", headers=headers).json()["seat_id"]
    response = client.post(f"{PREFIX}/gripper", json=_grip(seat, duration_s=3.0), headers=headers)
    assert response.status_code == 400 and response.json()["error"]["code"] == "VALIDATION_ERROR"
```

(`_jog` 헬퍼가 `request_id` 덮어쓰기를 받는지 확인하고, 받지 않으면 `**changes` 병합을 이미 하는 기존 서명을 그대로 쓴다.)

- [ ] **Step 2: 실패 확인** — `python -m pytest src/products/omx/adapter/test/test_pilot_sim_api.py -q` → FAIL `404`

- [ ] **Step 3: 구현** — import에 `OmxSimGripperGoal`; `receipts: dict[str, tuple[BaseModel, dict[str, Any]]]`; 기존 `submit` 본문을 `_submit(request, token, call)`로 추출:

```python
    def _submit(request, authorization, call) -> dict[str, Any]:
        token = auth(authorization)
        sessions.check_seat(token, request.seat_id)
        if request.instance_id != runtime.instance_id:
            raise HTTPException(409, "instance mismatch")
        now_ms = int(time.time() * 1000)
        if not now_ms < request.expires_at_ms <= now_ms + 6000:
            raise HTTPException(409, "request expired or expiry too distant")
        with receipt_lock:
            previous = receipts.get(request.request_id)
            if previous is not None:
                if previous[0] != request:
                    raise HTTPException(409, "request id reused")
                return previous[1]
            result = OmxSimGoal.model_validate(call(request)).model_dump()
            receipts[request.request_id] = (request, result)
            if result["state"] in {"REJECTED", "UNKNOWN_HOLD"}:
                raise HTTPException(409, result["reason"])
            return result

    @app.post(f"{PREFIX}/goals", status_code=202)
    def submit(jog: OmxSimJog, authorization: str | None = Header(None)) -> dict[str, Any]:
        return _submit(jog, authorization, runtime.submit)

    @app.post(f"{PREFIX}/gripper", status_code=202)
    def submit_gripper(goal: OmxSimGripperGoal, authorization: str | None = Header(None)) -> dict[str, Any]:
        return _submit(goal, authorization, runtime.submit_gripper)
```

(`OmxSimJog`와 `OmxSimGripperGoal`은 다른 모델이라 `!=`가 참 — 같은 id 재사용은 409.) GET `/goals/{id}`·취소는 그리퍼 목표에도 그대로 쓴다(같은 `receipts`).

- [ ] **Step 4: 통과 확인** — `python -m pytest src/products/omx/adapter/test -q` → PASS
- [ ] **Step 5: 커밋**

```bash
git add src/products/omx/adapter/omx_adapter/pilot_sim_api.py src/products/omx/adapter/test/test_pilot_sim_api.py
git commit -m "feat(omx_adapter): D-411 POST /api/v1/sim/omx/gripper" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task C4: 시연 기록·LeRobot `action.gripper`

**Files:**
- Modify: `src/products/omx/adapter/omx_adapter/pilot_sim_capture.py:81-87` (출처 `gripper_joint`)
- Modify: `src/products/omx/adapter/omx_adapter/demonstration.py:34-63` (`_provenance`), `:97-98` (길이 0.1–2.0), `:191-194` (행)
- Modify: `src/products/omx/adapter/omx_adapter/lerobot_export.py:20-36, 39-59`
- Test: `src/products/omx/adapter/test/test_demonstration.py`, `test_lerobot_export.py`(추가)

`gripper_joint`는 출처에서 **선택**이다 — 이전 에피소드(`rosy.omx-demonstration.v1`)는 그대로 검증·export된다. 있으면 모든 행이 `action.gripper`를 가져야 하고 그 값은 `action`의 그리퍼 칸과 같아야 한다.

- [ ] **Step 1: 실패하는 시험 쓰기** — `test_demonstration.py`의 `provenance()` 픽스처(12-19)와 기존 `sample` 헬퍼를 쓴다:

```python
def test_gripper_column_is_written_and_checked(tmp_path, provenance):
    source = {**provenance, "gripper_joint": provenance["joint_names"][-1]}
    recorder = DemonstrationRecorder(tmp_path, source)
    recorder.start("grip")
    sample(recorder, frame=0)                     # helper writes action == target vector
    row = json.loads((tmp_path / recorder.episode_id / "samples.jsonl").read_text().splitlines()[0])
    assert row["action.gripper"] == row["action"][-1]


def test_gripper_goals_may_take_up_to_two_seconds(tmp_path, provenance):
    recorder = DemonstrationRecorder(tmp_path, provenance)
    recorder.start("slow grip")
    sample(recorder, frame=0, duration_s=1.6)
    assert recorder.status()["issues"] == []


def test_episodes_without_gripper_joint_still_validate(tmp_path, provenance):
    recorder = DemonstrationRecorder(tmp_path, provenance)
    recorder.start("old")
    sample(recorder, frame=0)
    assert "action.gripper" not in (tmp_path / recorder.episode_id / "samples.jsonl").read_text()
```

`sample` 헬퍼가 `duration_s`·`frame` 인자를 받지 않으면 기존 서명의 키워드로 맞춘다(헬퍼 본문은 `recorder.sample(...)` 호출 한 번이다). `test_lerobot_export.py`:

```python
def test_gripper_feature_when_the_episode_names_a_gripper():
    manifest = {"provenance": {"joint_names": ["joint1", "gripper_joint_1"], "gripper_joint": "gripper_joint_1",
                               "camera": {"width": 4, "height": 4}}}
    features = dataset_features(manifest)
    assert features["action.gripper"] == {"dtype": "float32", "shape": (1,), "names": ["position_rad"]}
    assert "action.gripper" not in dataset_features(
        {"provenance": {**manifest["provenance"], "gripper_joint": None}})
```

- [ ] **Step 2: 실패 확인** — `python -m pytest src/products/omx/adapter/test/test_demonstration.py src/products/omx/adapter/test/test_lerobot_export.py -q` → FAIL `KeyError: 'action.gripper'`, `goal_duration`

- [ ] **Step 3: 구현**
- `_provenance`: `gripper = value.get("gripper_joint")`; `None`이 아니면 `names` 안에 있어야 한다(아니면 `ValueError("gripper joint must be one of the joints")`).
- `_row_error:97` `0.1 <= row["duration_s"] <= 1` → `<= 2`. 그리고 `gripper = source.get("gripper_joint")`가 있으면 `row.get("action.gripper") != row["action"][names.index(gripper)]`일 때 `"gripper_action"`.
- `sample`(191-194) 행 dict 뒤: `if self.source.get("gripper_joint"): row["action.gripper"] = target[self.source["gripper_joint"]]`.
- `pilot_sim_capture.py:81-87` 출처에 `"gripper_joint": self.runtime.gripper if getattr(self.runtime, "_gripper_spec", None) else None,`.
- `lerobot_export.dataset_features`: `if source.get("gripper_joint"): features["action.gripper"] = {"dtype": "float32", "shape": (1,), "names": ["position_rad"]}`. `iter_dataset_frames`: 같은 조건에서 `frame["action.gripper"] = np.array([row["action.gripper"]], dtype=np.float32)`.

- [ ] **Step 4: 통과 확인** — `python -m pytest src/products/omx/adapter/test -q` → PASS (LeRobot 의존 시험은 기존처럼 조건부 skip)
- [ ] **Step 5: 커밋**

```bash
git add src/products/omx/adapter/omx_adapter/pilot_sim_capture.py src/products/omx/adapter/omx_adapter/demonstration.py src/products/omx/adapter/omx_adapter/lerobot_export.py src/products/omx/adapter/test/test_demonstration.py src/products/omx/adapter/test/test_lerobot_export.py
git commit -m "feat(omx_adapter): D-411 action.gripper column in demonstrations and LeRobot export" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task C5: Pilot 그리퍼 위젯

**Files:**
- Create: `src/hmi/pilot/widgets/gripper.js`
- Modify: `src/hmi/pilot/controls.js` (그리퍼 순수 함수), `src/hmi/pilot/screens/arm.js` (`submitGripper`, `gripper` 위젯 등록), `src/hmi/pilot/styles.css` (`[data-control="gripper"]` 오른손 영역)
- Modify: 자산 등록(`widgets/gripper.js`, 디렉터리는 이미 설치), `sw.js` `CACHE` → `rosy-pilot-shell-2026-10-02-3`
- Test: `src/hmi/pilot/test/test_controls.py`(추가), `src/products/omx/adapter/test/test_pilot_sim_browser.py`(추가)

- [ ] **Step 1: 실패하는 시험 쓰기** — `test_controls.py`:

```python
def test_gripper_percent_round_trip_and_labels():
    out = _run_js("""
const g = {open: 1.0, closed: 0.0};
const r = {open: 0.0, closed: 1.0};
console.log(JSON.stringify([m.gripperPercent(0.25, g), m.gripperPosition(25, g), m.gripperPercent(2, g),
  m.gripperPercent(0.25, r), m.gripperPosition(100, r), m.GRIPPER_STATE_LABEL.holding, m.GRIPPER_DURATION_S]))""")
    assert out == [25, 0.25, 100, 75, 0, "쥐고 있음", 0.8]
```

`test_pilot_sim_browser.py`(기존 가짜 런타임 패턴, `/state`에 `gripper` 블록, `/target`에 `controls` 두 항목, 그리고 `submit_gripper` 기록):

```python
@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="ROSY_RUN_BROWSER_TESTS=1")
def test_gripper_presets_slider_and_badge(sim_page):
    page, runtime, errors = sim_page
    page.click("[data-gripper-preset='half']")
    page.wait_for_function("document.querySelector('[data-gripper-state]').textContent.length > 0")
    assert runtime.gripper_goals[-1].position == pytest.approx(0.5)
    page.fill("[data-gripper-percent]", "100")
    page.dispatch_event("[data-gripper-percent]", "change")
    page.wait_for_timeout(300)
    assert runtime.gripper_goals[-1].position == pytest.approx(1.0)
    runtime.gripper_state = "holding"
    page.wait_for_timeout(1200)
    assert page.inner_text("[data-gripper-state]") == "쥐고 있음"
    assert page.locator("[data-sim-gripper]").count() == 0      # the ±0.02 rad buttons are gone
    assert errors == [], errors
```

(`sim_page` 픽스처는 이 파일의 기존 페이지 픽스처를 확장한다: 가짜 런타임에 `gripper_goals`, `gripper_state`, `submit_gripper`, `controls()`(gripper 포함)를 더하고 페어링·seat까지 진행한 페이지를 돌려준다. 기존 파일의 픽스처 이름이 다르면 그 이름을 쓴다.)

- [ ] **Step 2: 실패 확인** — `python -m pytest src/hmi/pilot/test/test_controls.py -q` 와 `$env:ROSY_RUN_BROWSER_TESTS = '1'; python -m pytest src/products/omx/adapter/test/test_pilot_sim_browser.py -q -p no:cacheprovider` → FAIL

- [ ] **Step 3: 구현**

`controls.js`에 추가:

```js
export const GRIPPER_DURATION_S = 0.8;
export const GRIPPER_STATE_LABEL = Object.freeze({
  open: "열림", closed: "닫힘", holding: "쥐고 있음", moving: "이동 중", unknown: "알 수 없음",
});

export function gripperPercent(position, g) {
  const span = g.open - g.closed;
  return Math.round(Math.max(0, Math.min(1, (position - g.closed) / span)) * 100);
}

export function gripperPosition(percent, g) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0)) / 100;
  return Math.round((g.closed + (g.open - g.closed) * p) * 1e4) / 1e4;
}
```

`widgets/gripper.js`(약 90줄):

```js
// D-411 C: gripper widget — 열기/반/닫기, 열림 % slider, state badge. One absolute goal per action.
import {GRIPPER_DURATION_S, GRIPPER_STATE_LABEL, gripperPercent, gripperPosition} from "../controls.js";

export function mountGripper(slot, control, session) {
  // markup: <h3>그리퍼</h3> <span data-gripper-state role="status"></span>
  //   <ui-button data-gripper-preset="open">열기</ui-button> <ui-button data-gripper-preset="half">반</ui-button>
  //   <ui-button data-gripper-preset="close">닫기</ui-button>
  //   <label>열림 <input type="range" min="0" max="100" step="5" data-gripper-percent></label>
  // preset click → session.submitGripper(control.presets[key], GRIPPER_DURATION_S)
  // slider "change" (not "input") → session.submitGripper(gripperPosition(value, control), GRIPPER_DURATION_S)
  // session.onUpdate(({state}) => badge = GRIPPER_STATE_LABEL[state?.gripper?.state ?? "unknown"];
  //   slider value follows gripperPercent(state.gripper.position, control) unless the user is dragging;
  //   buttons/slider disabled while session.busy() or !state?.ready)
  return () => { /* unsubscribe, remove listeners */ };
}
```

`arm.js`: `session.submitGripper(position, durationS)` — `submitJog`와 같은 가드(`seat`, `state.ready`, `!active`) 뒤 `request("/gripper", {method: "POST", body: JSON.stringify({instance_id: target.instance_id, seat_id: seat, request_id: crypto.randomUUID(), position, duration_s: durationS, state_sequence: state.state_sequence, expires_at_ms: Date.now() + 5000})})`, `active = goal.command_id`. 위젯 표에 `gripper: mountGripper`. `fallbackOmxControls`는 구 서버용이라 그대로(그리퍼 ±0.02 조그).

`styles.css`: `.arm-controls { display: grid; grid-template-columns: 1fr 1fr; grid-template-areas: "left right"; }`, `[data-control="joint_jog"] { grid-area: left; }`, `[data-control="gripper"] { grid-area: right; }`, 좁은 화면(<40rem)은 한 열.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py src/products/omx/adapter/test -q -p no:cacheprovider`
그리고: `$env:ROSY_RUN_BROWSER_TESTS = '1'; python -m pytest src/hmi/pilot/test/test_pilot_browser.py src/products/omx/adapter/test/test_pilot_sim_browser.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/hmi/pilot/widgets/gripper.js src/hmi/pilot/controls.js src/hmi/pilot/screens/arm.js src/hmi/pilot/styles.css src/hmi/pilot/sw.js src/runtime/api_web/core_api_web/api/app.py src/products/omx/adapter/omx_adapter/pilot_sim_api.py src/hmi/pilot/test/dev_server.py src/hmi/pilot/test/test_controls.py src/products/omx/adapter/test/test_pilot_sim_browser.py src/runtime/api_web/test/test_pilot_route.py
git commit -m "feat(pilot): D-411 gripper widget (presets, open %, grasp badge)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task C6: Part C 문서·하네스

**Files:**
- Modify: `docs/reference/ROSY API & Protocol Reference.md` §5.9 — 표에 `POST /api/v1/sim/omx/gripper`(`OmxSimGripperGoal` → `OmxSimGoal` 202, 같은 영수증·seat·HOLD 규칙, 한계 밖 409 `gripper_limit`), `/state` 행에 `gripper {joint, position, state ∈ open·closed·holding·moving·unknown, open, closed}`, `holding` 정의, 기록 문단에 `action.gripper`와 목표 길이 0.1–2.0 s; §11 v1.76 행에 "C: SIM 그리퍼 목표·readback, 시연 `action.gripper`"
- Modify: 모듈 logs/progress(omx_adapter, pilot, core_common), `src/products/omx/adapter/AGENTS.md`(새 `pilot_sim_gripper.py`)
- Regenerate: `python tools/harness/rosy_harness.py generate`

- [ ] **Step 1–3:** 문서 수정 → `generate` → `lint`(D-410 외 오류 0) → `python -m pytest src/runtime/gateway/test/test_protocol_version_alignment.py test/test_harness_contracts.py -q`(D-410 항목 외 PASS)
- [ ] **Step 4: 커밋** — 바뀐 파일을 경로로 나열해 `git add` 후 `git commit -m "docs(d411): part C API ref and module records" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

# Verification

## 호스트 전체 시험 (Windows, `python`)

같은 basename을 가진 묶음은 따로 돈다(`gateway`·`sensing` 모두 `test_battery.py`).

```powershell
# CORE·계약·서비스·웹
python -m pytest src/runtime/gateway/test/ src/runtime/services/test/ src/runtime/events/test/ src/contracts/foundation/test/ src/runtime/api_web/test/ src/hmi/web_common/test/ -q -p no:cacheprovider
# sensing (단독)
python -m pytest src/runtime/sensing/test/ -q -p no:cacheprovider
# fleet·OMX·games·루트 계약
python -m pytest src/site/fleet/test/ src/products/omx/adapter/test/ src/site/games/test/ test/ -q -p no:cacheprovider
# PC 도구
python -m pytest tools/perception/test -q -p no:cacheprovider
# Pilot (Node 순수 + 자산)
python -m pytest src/hmi/pilot/test -q -p no:cacheprovider
# 브라우저 (Playwright)
$env:ROSY_RUN_BROWSER_TESTS = '1'; python -m pytest src/hmi/pilot/test/test_pilot_browser.py src/products/omx/adapter/test/test_pilot_sim_browser.py -q -p no:cacheprovider
# quick tier (pre-push와 같음)
python -m pytest test/test_harness_contracts.py test/architecture/test_module_structure.py test/test_io_image_closure.py test/test_line_follow_contract_docs.py src/runtime/gateway/test/test_protocol_version_alignment.py -q
```

각 실행 결과를 파일로 남겨 `python test/known_failures.py <run.txt>`로 비교한다. 허용되는 실패는 `test/known_failures.txt`의 두 항목과 Task 0의 D-410 항목뿐이다.

## 하네스

```powershell
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
```

Expected: 오류는 D-410 하나(선행 결함, Task 0). 다른 오류·mojibake·append-only 위반 0.

## 남은 자리표시 검사

```powershell
git diff main --name-only | Select-String -Pattern '\.(py|js|md|yaml|service|conf|sh)$'
```

바뀐 파일에서 `TODO`, `TBD`, `test.skip`, `.only(`, 빈 함수 본문(`/* ... */` 주석만 남은 구현)을 찾아 0이어야 한다(이 계획의 `/* ... */` 표기는 구현 지시이며 코드에 남으면 실패다).

## ROS-SIM 체크리스트 (수동 — WSL Ubuntu, 사용자 확인 후)

D-411 수용 범위의 ROS-SIM이다. 결과는 `docs/validation/d411-pilot-recording-2026-10-<dd>/README.md`에 명령·출력·해시로 남긴다. 실물 로봇은 쓰지 않는다(공유 로봇 규칙: 움직이기 전에 묻는다).

**Gazebo Pinky — Pilot 녹화 → 정지 → HTTP 수신 → 변환 → 짝 재독출**

- [ ] WSL에서 `~/rosy_ws`로 `src/` 복사 후 `colcon build --symlink-install`(`control`, `core`, `core_common`, `pilot`, `web_common` 포함). `typing_extensions`가 `/usr/local/lib/python3.12/dist-packages`에 있는지 확인(메모리 `gz-sim-bench-unblocked`).
- [ ] 한 대 Pinky 레인 월드 기동: `ros2 launch gz_sim map_v2_fleet_lane.launch.py`(기존 절차). CORE 설정 오버레이(`ROSY_CONFIG`)에 `recording: {pilot_root: /tmp/pilot-recordings}`.
- [ ] Gazebo에는 `camera_detect_node`가 없으므로 압축 토픽을 따로 만든다: `ros2 run image_transport republish --ros-args -p in_transport:=raw -p out_transport:=compressed -r in:=/rosy_01/camera/front -r out/compressed:=/rosy_01/camera/front/compressed` (플러그인이 없으면 `sudo apt install ros-jazzy-compressed-image-transport`).
- [ ] 녹화 노드: `ros2 run control pilot_recorder_node --ros-args -r __ns:=/rosy_01 -p recording_root:=/tmp/pilot-recordings`. `ros2 topic echo --once /rosy_01/pilot_recorder/status` → `state: idle`.
- [ ] Windows 포워더로 CORE를 `localhost:18080`에 열고 브라우저 `http://localhost:18080/pilot`, 토큰 `rosy-dev-operator`로 진입.
- [ ] 주행 화면 "로봇 녹화" → 경과·크기가 오른다. 30–60 s 수동 주행(스틱). `ros2 topic hz /rosy_01/teleop/intent` ≈ 10 Hz(누르는 동안).
- [ ] "로봇 녹화 중지" → 상태 `idle`, `/tmp/pilot-recordings/<id>/manifest.json` 존재.
- [ ] 스틱을 놓은 채 "녹화본" → 받기 가능. 주행 중엔 `ROBOT_MOVING`으로 비활성인지 확인.
- [ ] 브라우저 탭을 닫아 링크를 끊은 녹화가 5 s 뒤 `link_lost`로 멈추는지, 다른 토큰(`rosy-dev-admin`)의 teleop이 `seat_changed`로 멈추는지 각각 한 번.
- [ ] PC(Windows): `python tools/perception/dataset/fetch_http.py http://localhost:18080 --token-file <operator-token-file> --dest X:\DevTemp\d411\raw --video-out X:\DevTemp\d411\video` → sha256 검증 통과, mp4·jsonl 생성, `N frames, M paired cmd_vel+intent`에서 `M > 0`.
- [ ] 사이드카 재독출: jsonl 행 수 == `ffprobe`의 프레임 수, 주행 구간 행에 `side.cmd_vel`과 `side["teleop/intent"]`가 함께 있음. 녹화본 `fetched.json`이 로봇 쪽 폴더에 생겼는지 확인.

**OMX Gazebo — 그리퍼 열기/닫기/쥠과 시연 export**

- [ ] `deploy/robot/omx/run_pilot_sim.sh`로 OMX 컨테이너 기동(`ROSY_SIM_SOURCE_REVISION`은 이 브랜치 HEAD), 페어링 코드로 `/pilot` 연결.
- [ ] `/api/v1/sim/omx/target`의 `controls`에 `joint_jog`(그리퍼 제외)와 `gripper`(open 1.0, closed 0.0)가 있는지.
- [ ] 열기 → 배지 "열림", 닫기(빈 손) → "닫힘", 반 → "열림"(위치 ≈0.5). 매 목표 `SUCCEEDED`.
- [ ] 작업대 물체를 집게 사이에 두고 닫기 → 배지 "쥐고 있음"(위치가 닫힘에서 0.05 rad 넘게 떨어져 멈춤). 이때 목표가 `SUCCEEDED`가 아니라 HOLD로 끝나면(컨트롤러 goal tolerance) 그 사실과 `owner_reason`을 기록하고 `holding` 판정 수용을 보류한다.
- [ ] **차단 관문(D-411 C 검토, 구현 부록 13):** `python deploy/robot/omx/probe_pilot_sim_http.py rosy-omx-pilot-sim` 통과(그리퍼는 `POST /gripper` 절대 목표, 닫기 뒤 열기), 이어서 새 컨테이너에서 `--stall` 통과 — `stall_probe=` JSON 의 `terminal_state` SUCCEEDED·`status` 4·`result_code` 0·`gripper_state` holding·`holding_jogs` 세 개 모두 SUCCEEDED/holding. JSON 전체(끝까지 걸린 시간, readback, 마지막 0.5 s 최고 속도)를 검증 기록에 남기고, 실패하면 `goal_time`·`stopped_velocity_tolerance`(SIM 패치)·`gripper.preload`·정육면체 크기·집기 높이를 조정한 값과 함께 다시 돌린다. 이 관문 전에는 `holding` 을 수용하지 않는다.
- [ ] 팔 조이스틱: 패드를 누른 채 관절이 0.05 rad 단위로 이어서 움직이고, 떼면 다음 목표가 나가지 않는지(`/goals` 수 증가 멈춤).
- [ ] 시연 기록 시작 → 조그·그리퍼 조작 → 결과 "성공"으로 종료 → `samples.jsonl` 행에 `action.gripper` 존재, `validate_episode` 통과 → `python -m omx_adapter.lerobot_export <episode> --out X:\DevTemp\d411\lerobot`(F: 거부) 성공, 특성에 `action.gripper`.

## 범위 밖 (이 계획이 하지 않는 것)

- DEVICE: 실기 Pinky 녹화·수신은 사용자 확인 후 별도 기록(D-411 수용 기준). 이미지에 `ReadWritePaths`·tmpfiles가 실렸는지(ARTIFACT)도 릴리스 절차에서 본다.
- 실물 OMX 조종(D-390 §5), 직교좌표 조그(D-404), 녹화본 원격 게시(D-356/D-373).
- `harvest.py`(SSH)의 `raw/<device>/<session>` 배치와 `catalog.py scan`의 한 단계 glob 불일치는 기존 결함이다. `fetch --http`는 catalog가 읽는 `raw/<id>`에 둔다.
