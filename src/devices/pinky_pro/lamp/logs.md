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
