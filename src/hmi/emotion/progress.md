---
module: emotion
logical_modules: [M02]
owner: 장치
last_verified: { commit: "uncommitted", date: 2026-09-21 }
gates:
  SOURCE:
    state: GO
    evidence: "F-01 수정(패키지 평탄화 + rosy_emotion.py→emotion.py) 후 현재 트리 재실행 — test_info_screen·test_info_screen_palette 22 passed (2026-09-21 Windows)"
    cmd: "PYTHONPATH=src/hmi/emotion python -m pytest src/hmi/emotion/test/test_info_screen.py src/hmi/emotion/test/test_info_screen_palette.py -q"
  LOCAL:
    state: GO
    evidence: "같은 실행 24 passed(F-04 회귀 + 캡처 재현 시험 포함) + info_screen 카드 PNG 4종 재생성(D-153 회차6, docs/validation/uiux-surfaces-2026-09-21)"
    cmd: "PYTHONPATH=src/hmi/emotion python -m pytest src/hmi/emotion/test/test_info_screen.py src/hmi/emotion/test/test_info_screen_palette.py src/hmi/emotion/test/test_info_screen_capture.py -q"
  ROS-SIM:
    state: HOLD
    blocker: "rclpy set_emotion 서비스 노드가 있음. ROS 2 Jazzy 컨테이너 재실행 필요, 미실행"
  ARTIFACT:
    state: HOLD
    blocker: "hardware 프로필이 이미지에 배선되지 않았다. core/io 이미지 제외는 test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers가 고정한다"
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-57, D-153]
plans:
  - docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- `set_emotion` 서비스(LCD GIF)와 PWR-003 info-card 렌더러(`info_screen.py`, ROS-free PIL)를 제공한다.
- **F-01 해결 (2026-09-21, D-153 회차2):** 재편(9b77daa)이 선언만 `emotion.*`로 바꾸고 파일을 `rosy_emotion/`에 남겨둔 불일치를 닫았다 — 파이썬 파일을 `emotion/`으로 평탄화하고 `rosy_emotion.py`는 `emotion.py`로 환원했으며 마커 `resource/rosy_emotion`를 지웠다. SOURCE/LOCAL 재실행 22 passed로 GO 복원.
- `test/test_copyright.py`·`test_flake8.py`·`test_pep257.py`는 ament_copyright/flake8/pep257을 import한다. 이 호스트에는 설치되어 있지 않아(`ModuleNotFoundError`) 실행할 수 없고, 시도해도 증거로 세지 않는다.
- `deploy/image/ 빌더`에는 core/io 두 이미지만 있고 emotion을 포함하지 않는다. 하드웨어(LED/lamp/IMU/ADC/emotion) 프로필은 아직 배선되지 않았다.

## 다음 gate

1. ROS 2 Jazzy 컨테이너에서 `set_emotion` 서비스 노드 graph/parameter smoke를 실행해 ROS-SIM을 되돌린다.
3. hardware 프로필이 `deploy/image/ 빌더`에 배선되면 ARTIFACT blocker를 서명 artifact 발행으로 바꾸고 DEVICE/FIELD를 PARKED에서 HOLD로 올린다.

## 현재 유효한 금지사항

- PIL 렌더링은 `emotion`에만 둔다. `core`는 `display/info` JSON만 발행한다.
- `info_screen.py`의 320×240 landscape 출력 계약을 깨지 않는다(LCD 코드가 회전/리사이즈로 가정).
