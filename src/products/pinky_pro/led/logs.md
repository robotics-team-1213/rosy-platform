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

## 2026-09-30 · uncommitted · docs(harness): ROS-SIM blocker를 실제 조건으로 정정 — cmd 경로도 현재 트리로

- 변경: ROS-SIM blocker가 "Jazzy 컨테이너 재실행 필요"라고만 적혀 다음 회차를 불가능한 작업으로 보내었다. 실제 조건을 적었다: 노드의 `from rosylib import LED`는 공개 트리에서 의도적으로 실패한다(rosylib는 repo 밖 bench-only 헬퍼, bringup/test/test_rosylib_battery.py:140이 고정) — 사유 구현 반입 또는 stub 계약 결정이 선행 조건이다. SOURCE/LOCAL cmd의 옛 경로(src/led/test/...)도 현재 경로(src/products/pinky_pro/led/test)로 바로잡았다.
- 증거: 현재 경로 시험 2 passed 3 skipped(ament linter 3종은 이 호스트에 없어 skip) (2026-09-30 Windows).
- gate 변화: 없음 (HOLD 유지, blocker 사유만 정확화).
- 결정: 없음.
- 교훈: blocker 문구는 다음 회차의 작업 지시다 — "재실행 필요"가 실제로 불가능한 일이면 그 조건을 적어야 막힌 이유가 보인다.
