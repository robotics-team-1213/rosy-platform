---
module: emotion
logical_modules: [M02]
owner: 장치
last_verified: { commit: "47d3e6ec", date: 2026-09-29 }
gates:
  SOURCE:
    state: GO
    evidence: "F-01 수정 후 현재 트리 재실행. 정보 카드 긴 문자열 가장자리 회귀 포함 info/boot/palette/Wi-Fi QR 128 passed (2026-09-27 Windows)"
    cmd: "PYTHONPATH=src/hmi/face python -X utf8 -m pytest src/hmi/face/test/test_info_screen.py src/hmi/face/test/test_info_screen_boot.py src/hmi/face/test/test_info_screen_palette.py src/hmi/face/test/test_wifi_qr.py -q -p no:cacheprovider"
  LOCAL:
    state: GO
    evidence: "호스트 PIL 렌더 128 passed, 캡처 시험 1 passed. 부팅/AP QR/실패/긴 문자열 및 wake 카드 4종 320×240 PNG를 X:\\DevTemp\\rosy-uiux-lcd-2026-09-27에 저장. 실물 판독성 증거 아님"
    cmd: "PYTHONPATH=src/hmi/face ROSY_FACE_CAPTURE_DIR=X:\\DevTemp\\rosy-uiux-lcd-2026-09-27 python -X utf8 -m pytest src/hmi/face/test/test_info_screen_capture.py -q -p no:cacheprovider"
  ROS-SIM:
    state: HOLD
    blocker: "emotion.py가 모듈 최상위에서 `from .rosy_lcd import LCD`를 부르고 rosy_lcd는 spidev·RPi.GPIO를 최상위에서 import한다 — Pi가 아닌 Jazzy 컨테이너에서 노드 import가 죽는다. 컨테이너 smoke는 하드웨어 import 지연/가드 리팩터가 선행 조건이다(없으면 Pi 벤치는 DEVICE 계층이다)"
  ARTIFACT:
    state: HOLD
    blocker: "hardware 프로필이 이미지에 배선되지 않았다. core/io 이미지 제외는 test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers가 고정한다"
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-57, D-153, D-306, D-433, D-504]
plans:
  - docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-27-uiux-surface-closure.md
---
## 지금 상태

- D-504 브랜치 후보: 여덟 얼굴 GIF를 320×240·20프레임·100 ms로 만들고, 첫 프레임 공백과 운용 표정 실루엣 중복을 줄였다. 호스트 시험은 LOCAL 근거이며 실물 LCD 거리·각도·조도 판독은 미확인이다.
- `set_emotion` 서비스(LCD GIF)와 PWR-003 info-card 렌더러(`info_screen.py`, ROS-free PIL)를 제공한다.
- D-306 LCD 점검: 320×240 호스트 카드의 긴 동적 문자열은 기존 부팅 카드의 `_fit`으로 화면 안에 맞추고 말줄임을 표시한다. 부팅/AP QR/실패 캡처는 LOCAL 증거다. 실물 LCD의 거리·각도·조명 판독성은 미확인이라 DEVICE/BENCH GO가 아니다.
- **F-01 해결 (2026-09-21, D-153 회차2):** 재편(9b77daa)이 선언만 `emotion.*`로 바꾸고 파일을 `rosy_emotion/`에 남겨둔 불일치를 닫았다 — 파이썬 파일을 `emotion/`으로 평탄화하고 `rosy_emotion.py`는 `emotion.py`로 환원했으며 마커 `resource/rosy_emotion`를 지웠다. SOURCE/LOCAL 재실행 22 passed로 GO 복원.
- `test/test_copyright.py`·`test_flake8.py`·`test_pep257.py`는 ament_copyright/flake8/pep257을 import한다. 이 호스트에는 설치되어 있지 않아(`ModuleNotFoundError`) 실행할 수 없고, 시도해도 증거로 세지 않는다.
- `deploy/robot/pinky_pro/image/ 빌더`에는 core/io 두 이미지만 있고 emotion을 포함하지 않는다. 하드웨어(LED/lamp/IMU/ADC/emotion) 프로필은 아직 배선되지 않았다.

## 다음 gate

1. ROS 2 Jazzy 컨테이너에서 `set_emotion` 서비스 노드 graph/parameter smoke를 실행해 ROS-SIM을 되돌린다 — 단 `rosy_lcd`의 spidev·RPi.GPIO 최상위 import 때문에 Pi 외 컨테이너에서는 노드가 뜨지 않는다. 하드웨어 import 지연/가드 리팩터가 선행 조건이다.
3. hardware 프로필이 `deploy/robot/pinky_pro/image/ 빌더`에 배선되면 ARTIFACT blocker를 서명 artifact 발행으로 바꾸고 DEVICE/FIELD를 PARKED에서 HOLD로 올린다.

## 현재 유효한 금지사항

- PIL 렌더링은 `emotion`에만 둔다. `core`는 `display/info` JSON만 발행한다.
- `info_screen.py`의 320×240 landscape 출력 계약을 깨지 않는다(LCD 코드가 회전/리사이즈로 가정).
