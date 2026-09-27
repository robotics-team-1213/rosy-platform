# lamp_control logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/lamp_control`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the lamp_control harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed; LOCAL은 미실행 — `src/lamp_control`에 `test/` 디렉터리가 없어 host-runnable 대상이 없음 (2026-09-15 Windows)
- gate 변화: 없음(신규 기록). SOURCE GO, LOCAL/ROS-SIM HOLD, ARTIFACT/DEVICE/FIELD N/A(이미지에 미포함)
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): regrade lamp_control gates after review
- 변경: 2차 리뷰 반영. 이미지 제외 시험은 패키지 내용을 읽지 않으므로 SOURCE에서 ARTIFACT 근거로 옮기고, 배선 대기 중인 배포 gate를 N/A에서 HOLD/PARKED로
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed (2026-09-16 재실행)
- gate 변화: SOURCE GO→HOLD, ARTIFACT N/A→HOLD, DEVICE N/A→PARKED, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# lamp_control logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/lamp_control`를 본다.

## 2026-09-25 · uncommitted · refactor(devices): move lamp_control under src/devices/pinky_pro/lamp_control (D-231)

- 변경: src/devices/pinky_pro/lamp_control로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 장치 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-26 · 8e6902fd · feat(devices): lamp_selftest for the D-247 lamp test

- 변경: `src/lamp_selftest.c`는 ROS 없는 C 도우미다. 8 LED, GPIO19, GBR, dma 10이다. 빨강·초록·파랑을 1 s씩 켰다가 끄고, 신호를 받아도 끈다. CMake가 aarch64에서 main_node와 함께 빌드해 `lib/lamp_control`에 설치한다. `rosy-hw-test`가 root로 실행한다.
- 증거: x86 WSL gcc 13에서 `-Wall -Wextra -Wpedantic` 경고 없이 컴파일·링크했다. Pi 밖에서는 "Hardware revision is not supported"로 종료 2. 패키지 계약 2 passed
- 미증명: ARM64 colcon 빌드와 실기 점등
- gate 변화: 없음
- 결정: D-247
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(lamp_control): D-260 lamp_pattern helper
- 변경: `src/lamp_pattern.c` 신규(booting/ready/failed/caution/test/off, SIGTERM이면 끄고 종료), CMake 빌드·설치, 패키지 계약 시험
- 증거: WSL gcc `-std=c11 -Wall -Wextra -Wpedantic` 구문 검사 통과, 가짜 ws2811로 무늬 시퀀스 확인(ready 3 s 뒤 꺼짐, test R→G→B, 잘못된 인자 64). ARM64 빌드·실기 점등은 미확인; 2026-09-26 Windows, `feat/d260-status-signals`: 호스트 묶음(foundation·gateway·api_web·hmi web/dashboard/face·lamp·boot display·hw-test·hw-probe·boot-status·native systemd·device surface·image customization·lamp image·harness) 2051 passed, 32 skipped, 2 failed — 둘 다 main의 `src/hmi/dashboard/logs.md` 두 항목(`- 근거:`)이 원인이고 깨끗한 main worktree에서도 같게 실패한다. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 62 passed
- gate 변화: 없음
- 결정: D-260 Proposed
- 교훈: 없음
## 2026-09-26 · uncommitted · fix(lamp_control): strip order GRB, not GBR
- 변경: `lamp_pattern.c`, `lamp_selftest.c`, `main_node.cpp`의 `strip_type`을 `WS2811_STRIP_GRB`로 바꿨다. 패키지 계약 시험도 같이 바꿨다
- 증거: rosy_18(release 016)에서 부팅 표시가 파랑 대신 빨강, 주황(주의) 대신 파란 계열로 보였다. 같은 라이브러리로 GRB 빨강→초록→파랑을 3 s씩 켜자 사람이 "빨초파"로 확인했다
- 미증명: 수정한 바이너리의 실기 점등(다음 release)
- gate 변화: 없음
- 결정: D-260
- 교훈: 제조사 코드의 색 순서를 그대로 믿지 말고 사람이 단색을 보고 확인한다
