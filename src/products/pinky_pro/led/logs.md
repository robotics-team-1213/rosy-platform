# led logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/led`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the led harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed; `python3 -m pytest src/led/test/ -q` 3 errors — `ModuleNotFoundError: No module named 'ament_copyright'`(flake8/pep257 동일), host-runnable 비-ROS 시험 없음 (2026-09-15 Windows)
- gate 변화: 없음(신규 기록). SOURCE GO, LOCAL/ROS-SIM HOLD, ARTIFACT/DEVICE/FIELD N/A(이미지에 미포함)
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): regrade led gates after review
- 변경: 2차 리뷰 반영. 이미지 제외 시험은 패키지 내용을 읽지 않으므로 SOURCE에서 ARTIFACT 근거로 옮기고, 배선 대기 중인 배포 gate를 N/A에서 HOLD/PARKED로
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed (2026-09-16 재실행); `src/led/test` 3 errors(ament linter 미설치) 재확인
- gate 변화: SOURCE GO→HOLD, ARTIFACT N/A→HOLD, DEVICE N/A→PARKED, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# led logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/led`를 본다.

## 2026-09-25 · uncommitted · refactor(devices): move led under src/devices/pinky_pro/led (D-231)

- 변경: src/devices/pinky_pro/led로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 장치 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음
