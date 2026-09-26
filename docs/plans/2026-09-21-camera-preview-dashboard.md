# Camera Preview Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Gazebo와 Pinky의 실제 전방 카메라 프레임 및 도로 인식 오버레이를 인증된 CORE 대시보드에서 저대역폭으로 확인한다.

**Architecture:** D-152에 따라 Control이 `camera/front`를 인식하고 bounded JPEG preview를 발행한다. CORE는 디코딩·재인코딩 없이 최신 한 장만 보관하고 인증 REST로 제공하며, 대시보드는 Bearer fetch로 2 FPS 표시한다. raw/Fleet/WebSocket 영상 경로는 만들지 않는다.

**Tech Stack:** ROS 2 Jazzy, sensor_msgs Image/CompressedImage, OpenCV, FastAPI, vanilla ES modules, pytest, Playwright

---

### Task 1: 최신 프레임 저장소

**Files:**
- Create: `src/core/core_features/core_features/vision/__init__.py`
- Create: `src/core/core_features/core_features/vision/store.py`
- Create: `src/core/core/test/test_vision_preview.py`

1. 크기·MIME·시각·stale 경계를 요구하는 실패 테스트를 작성한다.
2. `python -m pytest src/core/core/test/test_vision_preview.py -q`로 RED를 확인한다.
3. lock으로 보호되는 최신 한 장 저장소를 구현한다.
4. 같은 명령으로 GREEN을 확인한다.

### Task 2: CORE REST와 ROS bridge

**Files:**
- Create: `src/core/core_api_web/core_api_web/api/v1/vision.py`
- Modify: `src/core/core_api_web/core_api_web/api/v1/routes.py`
- Modify: `src/core/core_api_web/core_api_web/api/app.py`
- Modify: `src/core/core_api_web/core_api_web/api/deps.py`
- Modify: `src/core/core/core/services.py`
- Modify: `src/core/core/core/bridge/ros_bridge.py`
- Modify: `src/core/core/test/test_bridge_timers.py`
- Modify: `src/core/core/test/test_vision_preview.py`

1. viewer 인증, status, JPEG, missing/stale 동작 테스트를 먼저 작성해 RED를 확인한다.
2. `VisionFrameStore`를 services에 배선하고 `CompressedImage` callback을 추가한다.
3. API route를 구현하고 GREEN을 확인한다.

### Task 3: Control 오버레이 preview

**Files:**
- Modify: `src/core/control/control/sensing/road.py`
- Modify: `src/core/control/control/road_observer_node.py`
- Modify: `src/core/control/config/line_follow.yaml`
- Modify: `src/core/control/test/test_road_perception.py`
- Modify: `src/core/control/test/test_road_observer_wiring.py`

1. 차선·정지선·횡단보도·신호 표시와 압축 발행 계약 테스트를 작성해 RED를 확인한다.
2. 원본 판정을 바꾸지 않는 오버레이와 2 FPS JPEG 발행을 구현한다.
3. Control 집중 테스트를 GREEN으로 만든다.

### Task 4: Gazebo opt-in 연결

**Files:**
- Modify: `src/sim/gz_sim/launch/launch_sim.launch.xml`
- Create: `src/core/control/launch/semantic_road_dashboard.launch.py`
- Modify: `test/test_dds_rmw_contracts.py`
- Modify: `test/test_line_follow_runtime.py`

1. 카메라 bridge가 `camera/front`로 remap되고 의미론적 launch가 opt-in 하는 실패 계약을 작성한다.
2. launch를 구현하고 계약 테스트를 통과시킨다.

### Task 5: 대시보드 패널

**Files:**
- Modify: `src/core/core_api_web/core_api_web/web/index.html`
- Modify: `src/core/core_api_web/core_api_web/web/styles.css`
- Modify: `src/core/core_api_web/core_api_web/web/app.js`
- Modify: `src/core/core/test/test_dashboard.py`
- Modify: `test/test_dashboard_browser.py`

1. 영상 panel, 인증 blob fetch, stale 표현 브라우저 테스트를 작성해 RED를 확인한다.
2. 지도 옆 운용 패널에 산업용 모니터 형태의 preview를 구현한다.
3. Playwright로 실제 렌더와 스크린샷을 확인한다.

### Task 6: 리뷰 경계 강화

1. 로컬 monotonic 2 FPS, 640 px, 512000 byte, DDS depth 1을 강제한다.
2. status/frame sequence binding과 token별 400 ms pull 제한을 적용한다.
3. capture-clock epoch reset, 재인증/pagehide/hidden-tab 취소를 시험한다.
4. Chromium에서 캡처 시각과 receipt latency를 별도로 표시하고 재촬영한다.

### Task 7: 계약·문서·최종 검증

**Files:**
- Modify: `docs/reference/ROSY API & Protocol Reference.md`
- Modify: `docs/validation/semantic-road-2026-09-21/README.md`
- Modify: module `logs.md` / `progress.md` files as required

1. API와 Gazebo 실행 명령, HOST-SIM/GAZEBO/DEVICE 증거 경계를 문서화한다.
2. Core, Control, root/browser 집중 테스트와 harness lint를 실행한다.
3. 스크린샷과 git diff/status를 확인한 뒤 기능 커밋을 만든다.
