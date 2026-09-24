# imu_bno055 logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/imu_bno055`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the imu_bno055 harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed; `python3 -m pytest src/imu_bno055/test/test_package_contract.py -q` 3 passed; `python3 -m pytest src/imu_bno055/test/test_driver_faults.py -q` 10 skipped(BNO055_TEST_EXECUTABLE 미설정, 증거 아님) (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, ROS-SIM HOLD, ARTIFACT/DEVICE/FIELD N/A(이미지에 미포함)
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): back imu source with its package contract
- 변경: 2차 리뷰 반영. SOURCE 근거를 이미지 제외 시험에서 패키지 파일을 직접 단언하는 `test_package_contract.py`로 교체하고, 배선 대기 중인 배포 gate를 N/A에서 HOLD/PARKED로
- 증거: `python3 -m pytest src/imu_bno055/test/test_package_contract.py -q` 3 passed; 이미지 제외 시험 1 passed (2026-09-16 재실행)
- gate 변화: SOURCE GO 유지(근거 교체), ARTIFACT N/A→HOLD, DEVICE N/A→PARKED, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-20 · uncommitted · feat(imu): publish raw calibration and health evidence

- 변경: read temperature, `CALIB_STAT`, `ST_RESULT`, `SYS_STATUS`, and `SYS_ERR`; publish component calibration fields without treating them as robot-level calibration success; replace invented covariance with explicit standard-deviation parameters whose zero defaults mean unknown covariance.
- 증거: `python -m pytest src/hardware/imu_bno055/test -q -p no:cacheprovider` produced `4 passed, 10 skipped`.
- gate 변화: SOURCE/host contract GO. ARM64 compiled fault injection, live I2C, DEVICE, and FIELD remain HOLD.
- 결정: IMUPLUS magnetometer calibration is diagnostic evidence only and does not invalidate an otherwise healthy IMUPLUS stream.
- 교훈: sensor-internal fusion status cannot substitute for robot geometry, extrinsic, or stopping-envelope validation.

## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# imu_bno055 logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/imu_bno055`를 본다.
