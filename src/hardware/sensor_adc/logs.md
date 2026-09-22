## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# sensor_adc logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/sensor_adc`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the sensor_adc harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed; LOCAL은 미실행 — `src/sensor_adc`에 `test/` 디렉터리가 없어 host-runnable 대상이 없음 (2026-09-15 Windows)
- gate 변화: 없음(신규 기록). SOURCE GO, LOCAL/ROS-SIM HOLD, ARTIFACT/DEVICE/FIELD N/A(이미지에 미포함)
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): regrade sensor_adc gates after review
- 변경: 2차 리뷰 반영. 이미지 제외 시험은 패키지 내용을 읽지 않으므로 SOURCE에서 ARTIFACT 근거로 옮기고, 배선 대기 중인 배포 gate를 N/A에서 HOLD/PARKED로
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed (2026-09-16 재실행)
- gate 변화: SOURCE GO→HOLD, ARTIFACT N/A→HOLD, DEVICE N/A→PARKED, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음
