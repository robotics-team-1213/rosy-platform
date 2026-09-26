# Rosy 자동 보정과 적응형 속도 승인 구조 연구

작성: 2026-09-20

범위: Pinky Pro 차동구동, ROS 2 Jazzy, Dynamixel wheel odometry, BNO055, RPLIDAR C1, 초음파/IR, SLAM·Nav2

상태: 설계 입력을 위한 조사. 생산 코드 변경이나 실물 속도 승인을 포함하지 않는다.

## 결론

적응형 속도를 안전하게 도입하려면 현재의 단일 `calibration ready` 개념을 다음 세 계층으로 분리해야 한다.

1. **기구·센서 보정 인증서**: wheel scale/effective separation, LiDAR·IMU 배치, 센서 잡음과 잔차를 기록한다.
2. **속도·정지 엔벨로프 인증서**: 기구·센서 인증서의 digest에 종속되어, 속도 구간별 명령 지연·실제 감속·정지거리의 보수적 상한을 기록한다.
3. **짧은 런타임 lease**: 현재 센서 freshness, TF, 안전 정책 revision, surface/전압/온도 범위, drift 잔차가 두 인증서의 조건 안에 있는 동안에만 해당 속도 단계를 허용한다.

보정기는 값을 직접 활성 설정에 덮어쓰지 않는다. `candidate → holdout 검증 → 원자적 승격(active)`으로 처리하고, 실패하면 last-known-good를 보존한다. 정상 운행 중 관찰값은 active 값을 몰래 학습시키지 않고 새 candidate나 drift 증거만 만든다.

현재 실물에서 검증된 `0.014 m/s`를 넘기는 것은 이 구조가 구현됐다는 이유만으로 허용할 수 없다. 속도별 정지 시험과 독립 holdout, Pi 재부팅 readback, 실제 바닥·배터리·payload 조건의 Device/FIELD 증거가 필요하다.

## 공식 자료가 정하는 경계

### 차동구동 기구 보정

ROS 2 Jazzy `diff_drive_controller` 문서는 잘못된 `wheel_radius`가 실제 선속도 scale을 바꾸고, 잘못된 `wheel_separation`이 곡선 동작을 망친다고 명시한다. 이를 보정하기 위한 `wheel_separation_multiplier`, 좌·우 `wheel_radius_multiplier`가 별도로 있다. 또한 velocity/acceleration/jerk 제한과 stale-command 정지를 제공한다. 즉 이 파라미터들은 보정 결과의 **소비 지점**이지 온라인 추정기는 아니다. 보정 시험은 command에서 odom을 다시 만드는 `open_loop=true`가 아니라 실제 wheel feedback을 사용해야 한다.

출처: [ROS 2 Jazzy diff_drive_controller](https://control.ros.org/jazzy/doc/ros2_controllers/diff_drive_controller/doc/userdoc.html)

Borenstein과 Feng은 차동구동의 대표적인 체계 오차를 effective wheelbase 오차와 좌우 wheel diameter 불일치로 분리하고, 시계/반시계 폐루프 주행을 함께 측정해야 두 효과를 구별할 수 있음을 보였다. Censi 등은 wheel radii·wheel distance와 range sensor의 2D extrinsic을 wheel velocity와 외부 motion estimate로 동시에 추정하는 관측 가능성 및 maximum-likelihood 해법을 제시했다. 따라서 한 번의 직진이나 한 방향 제자리 회전으로 모든 기구 파라미터를 확정하면 안 된다.

출처: [Borenstein & Feng, Measurement and Correction of Systematic Odometry Errors](https://web.cecs.pdx.edu/~mperkows/CLASS_479/S2006/Paper-correction-odometry-error.pdf), [Censi et al., Simultaneous Calibration of Odometry and Sensor Parameters](https://doi.org/10.1109/TRO.2012.2226380), [저자 공개본](https://censi.science/pub/research/2012-joint_calibration.pdf)

### IMU와 상태 추정

`robot_localization`은 센서 융합기이지 wheel geometry 보정기가 아니다. 평면 로봇에는 `two_d_mode`가 적합하지만, 같은 encoder에서 나온 pose와 velocity를 독립 관측처럼 중복 융합하지 말아야 하고, 실제 covariance가 중요하다. 절대 yaw 소스가 여러 개일 때 covariance가 실제 불일치보다 작으면 추정값이 소스 사이에서 진동할 수 있다.

출처: [robot_localization Jazzy configuration](https://github.com/cra-ros-pkg/robot_localization/blob/jazzy-devel/doc/configuring_robot_localization.rst), [sensor data preparation](https://github.com/cra-ros-pkg/robot_localization/blob/jazzy-devel/doc/preparing_sensor_data.rst)

REP-145는 gyro를 rad/s, acceleration을 m/s²로 내보내고, IMU mount는 `imu_link`와 `base_link`의 TF로 표현하며, covariance를 알지 못하면 0, 해당 측정 자체가 없으면 첫 원소를 -1로 표시하도록 한다. 따라서 임의의 고정 covariance는 “보정 완료”의 대체물이 아니다.

출처: [REP-145 IMU conventions](https://ros.org/reps/rep-0145.html), [sensor_msgs/Imu](https://docs.ros.org/en/jazzy/p/sensor_msgs/msg/Imu.html)

Bosch 자료상 BNO055의 background calibration은 끌 수 없고, `CALIB_STAT`은 accel/gyro/mag/system 상태를 각각 나타낸다. gyro는 수초 정지, accelerometer는 6개 안정 자세, magnetometer는 8자형 움직임을 요구한다. 저장한 offset/radius가 틀리면 calibration level 3이어도 orientation이 신뢰할 수 없다고 Bosch가 경고한다. Rosy 드라이버는 `OPR_MODE=8`, 즉 magnetometer를 쓰지 않는 IMU fusion mode이므로, 실내 주행 보정에서 magnetic absolute yaw를 새로 요구하지 말고 **stationary gyro + relative yaw**를 LiDAR motion과 교차검증하는 편이 현재 구조와 맞다.

출처: [Bosch BNO055 datasheet, 3.3·3.9·3.11](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bno055-ds000.pdf), [Bosch quick start](https://www.bosch-sensortec.com/media/boschsensortec/downloads/application_notes_1/bst-bno055-an007.pdf)

### LiDAR·SLAM

RPLIDAR C1의 보장 범위는 표적 반사율에 의존한다. 공식 사양은 70% 흰색 표적 0.05–12 m, 10% 검은 표적 0.05–6 m, 정확도 ±30 mm, 5 kHz, 회전 8–12 Hz다. 한 회전은 약 83–125 ms이므로 회전 중 스캔은 동시에 취득된 한 장의 사진이 아니다. 속도를 올리기 전에 scan completeness, source timestamp, 회전 중 odom/IMU 기반 deskew 또는 충분히 낮은 회전속도가 필요하다. health `Good`은 물체별 거리 정확도를 인증하지 않는다.

출처: [SLAMTEC C1 product specification](https://www.slamtec.com/en/c1/spec), [C1 datasheet](https://wiki.slamtec.com/download/attachments/83066883/SLAMTEC_rplidar_datasheet_C1_v1.0_en.pdf?api=v2&modificationDate=1700531479533&version=1), [SLAMTEC protocol](https://bucket.download.slamtec.com/f010c72be308cdc618e91746d643278185ed02b2/LR001_SLAMTEC_rplidar_protocol_v2.2_en.pdf)

SLAM Toolbox는 odom으로 scan pose를 만들고 scan matching으로 이를 보정해 pose graph와 `map→odom`을 만든다. pose와 covariance, loop closure event는 품질 관찰에 유용하지만, 같은 LiDAR·odom으로 만든 map을 다시 LiDAR·odom 보정의 독립 정답으로 사용할 수는 없다. active/lifelong map은 오차를 pose graph에 흡수할 수도 있으므로, 보정 검증에는 고정 serialized graph의 localization mode 또는 별도 기준 geometry/측정 장치를 우선한다.

출처: [SLAM Toolbox official repository](https://github.com/SteveMacenski/slam_toolbox), [ROS Index Jazzy slam_toolbox](https://index.ros.org/p/slam_toolbox/)

### 속도와 충돌 방어

Nav2 Velocity Smoother는 velocity/acceleration/deceleration/deadband/timeout을 명시적으로 제한한다. `CLOSED_LOOP`는 고주기·저지연 odom을 필요로 한다. Regulated Pure Pursuit는 곡률, obstacle cost, 목표 접근 거리, forward-projected collision time으로 속도를 줄일 수 있다. Collision Monitor는 sensor freshness가 끊기면 정지하고 stop/slowdown/limit/approach(time-to-collision)를 제공할 수 있지만, Nav2 문서 자체가 이것을 hard real-time 또는 safety-certified 기능으로 보지 않는다. 따라서 software 감속은 motor deadman, E-stop, 물리 시험을 대체하지 않는다.

출처: [Nav2 Velocity Smoother](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/configuring_velocity_smoother/), [Regulated Pure Pursuit](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/), [Collision Monitor](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/collision_monitor/configuring_collision_monitor_node/), [Speed Filter](https://docs.nav2.org/rolling/configuration_and_development/configuration_guide/core_servers/costmap_2d/costmap_filters/speed_filter/)

## 현재 Rosy 구현에서 확인한 것

### 이미 좋은 기반

- `startup_calibration_node.py`는 fresh TF, LiDAR, odom, IMU, US, IR, camera, map을 정지 상태에서 확인하고, safety가 시험 명령을 수정하면 trial을 무효화한다.
- `RoundTrip`은 2–4 cm 전진/후진을 두 cycle 수행하고 LiDAR 변화와 wheel odom을 비교하며, 두 번째 cycle에서 추정 scale의 재현성을 확인한다.
- `RotationTrial`은 ±10° 왕복을 반복하고 LiDAR scan registration, BNO055 relative yaw, wheel odom yaw가 3° 안에서 일치해야 통과시킨다. onset latency와 양·음 방향 steady response도 분리한다.
- `RotationEnvelope`는 empirical residual과 excitation에서 center uncertainty를 만들고, 이것이 통계적 신뢰도 보장은 아니라고 코드에 명시한다.
- `calibration_record.py`와 `calibration_storage.py`는 robot/hardware/geometry/sensor/data-generation context, revision, previous digest, atomic replace, concurrent writer 방어를 이미 갖춘다.
- `calibration_profile.py`는 1.5 s TTL lease, geometry revision 일치, replay 거절을 갖고 `domain=low_speed_straight`, `physical_commissioned=false`를 명시한다. 즉 현재 증거가 고속 운행 인증서가 아니라는 경계가 올바르다.

### 속도 승격을 막는 현재 gap

| 영역 | 현재 상태 | 구조 개선 필요 |
|---|---|---|
| BNO055 readiness | `imu_raw` freshness와 read error만 보며 covariance를 세 종류 모두 고정 `0.01`로 발행 | `SYS_STATUS`, `SYS_ERR`, `ST_RESULT`, accel/gyro `CALIB_STAT`, temperature/offset signature와 정지 실측 variance를 health evidence로 분리 |
| Wheel geometry | `wheel_radius=0.027`, `wheel_separation=0.0961`을 정적으로 사용 | nominal geometry와 자동 추정 correction multiplier를 분리하고, 양방향 직진·CW/CCW·arc excitation으로 식별 |
| Odom uncertainty | bringup odom이 pose/twist covariance를 채우지 않음 | raw encoder sample에서 구한 covariance 또는 명시적 unknown을 내보내고 융합 설정과 일치시킴 |
| Linear calibration | 짧은 LiDAR 기준 왕복 scale만 추정 | wheel common scale과 좌우 비대칭, 바닥별 repeatability/holdout을 구분 |
| Rotation calibration | response scale은 추정하지만 `angular_gains=[1,1]`, `compensation_verified=false`로 의도적으로 미적용 | candidate multiplier를 별도 holdout에서 적용 검증한 뒤에만 승격 |
| Space speed | `space_speed.py`가 스스로 “measured braking model 아님”이라고 명시하고 2 cm band 비례 감속만 수행 | 속도별 실제 stop latency/deceleration/distance 인증서와 clearance uncertainty를 소비 |
| Nav2 | params는 `desired_linear_vel=0.2`, smoother `OPEN_LOOP`, max 0.2; curvature 감속은 꺼져 있고 별도 Collision Monitor가 없음 | 최종 CORE cap 아래에서 closed-loop 가능 여부를 실측하고, curvature/cost/TTC 제한을 각각 검증. 설치된 Jazzy 파라미터 의미도 재검증 |
| 보정 기록 | identity/revision/digest는 강하지만 품질·환경·유효 범위 필드가 부족 | raw evidence hash, estimator version, uncertainty, holdout, surface/payload/voltage/temperature band, invalidation reason 추가 |

관련 파일:

- `src/core/control/control/startup_calibration_node.py`
- `src/core/control/control/control/{calibration.py,round_trip.py,rotation_trial.py,rotation_envelope.py,calibration_profile.py,space_speed.py}`
- `src/core/control/control/{calibration_record.py,calibration_storage.py}`
- `src/hardware/imu_bno055/src/{main_node.cpp,bno055_device.cpp}`
- `src/hardware/bringup/bringup/bringup.py`
- `src/navigation/navigation/params/nav2_params.yaml`

## 자동 추정 가능성과 금지선

| 항목 | 자동 처리 | 조건/한계 |
|---|---|---|
| 센서 연결·rate·freshness·scan coverage | 가능 | source timestamp와 실제 유효 return 비율을 함께 확인; topic 존재만으로 통과 금지 |
| stationary gyro bias/noise, gravity consistency | 가능 | motor zero, 수초 안정, temperature/전압 기록; BNO internal level과 외부 통계는 별도 |
| 공통 wheel distance scale | 가능 | 정·역방향 반복, feedback encoder, 독립 LiDAR motion 또는 외부 거리 기준, 충분한 이동량 |
| 좌우 wheel radius 비대칭 | 조건부 가능 | 직진만으로는 부족; CW/CCW 및 arc를 함께 쓰고 repeatability/observability 조건 충족 |
| effective wheel separation | 조건부 가능 | 양방향 회전/arc의 외부 yaw가 필요. 물리 치수 대신 bounded multiplier로 저장 |
| LiDAR x/y/yaw extrinsic | 조건부 가능 | translation+rotation의 다양한 excitation, 충분한 환경 구조, joint estimator의 rank/condition 검사 필요 |
| IMU mount roll/pitch/yaw | 조건부 가능 | roll/pitch는 gravity, yaw는 반복 상대회전으로 검증. IMUPLUS에서 absolute yaw 자동 인증 금지 |
| speed별 command latency·stop distance | 조건부 가능 | 넓고 비어 있는 승인 구역, 여러 속도·방향·battery·surface 반복, independent/heldout distance 필요 |
| 초음파/IR | health·guard 보정만 | blind zone·반사율·바닥 조건 때문에 wheel/LiDAR geometry의 정밀 기준으로 사용하지 않음 |
| footprint·실제 돌출물·mount 체결 | 자동 확정 금지 | 신뢰된 BOM/측정/정비자 승인 입력. sensor-consistent하다는 이유로 축소 금지 |
| 사람 주변 안전속도·E-stop 성능 인증 | 자동 확정 금지 | 비안전등급 C1/Nav2 software 결과로 인증 불가 |
| SLAM map 정확도 | 동일 입력만으로 자기 인증 금지 | reference geometry, 독립 측량 또는 분리된 holdout 세션 필요 |

## 제안 아키텍처

### 1. `GeometrySensorCertificate`

보정값과 그 값이 성립한 조건을 함께 저장한다.

```yaml
schema_version: 2
context:                       # 기존 5-field context 유지
source_record_digest: ...
estimator:
  name: rosy_joint_diffdrive_lidar
  version: ...
inputs:
  bag_digests: [...]
  firmware: {bno055: ..., rplidar: ..., motor: ...}
  nominal_geometry_revision: ...
estimates:
  wheel_radius_common_multiplier: {value: ..., std: ..., ci95: [...]}
  wheel_radius_left_multiplier:  {value: ..., std: ..., ci95: [...]}
  wheel_radius_right_multiplier: {value: ..., std: ..., ci95: [...]}
  effective_separation_multiplier: {value: ..., std: ..., ci95: [...]}
  lidar_extrinsic_delta: {x_m: ..., y_m: ..., yaw_rad: ..., covariance: [...]}
  imu_gyro_bias_rad_s: [...]
quality:
  excitation_rank: ...
  train_residuals: ...
  holdout_residuals: ...
  trials_by_direction: ...
status: candidate | active | rejected | superseded
```

중요한 규칙은 다음과 같다.

- nominal physical geometry는 유지하고 correction multiplier만 bounded range 안에서 자동 추정한다.
- 학습에 쓴 motion과 holdout motion을 세션 또는 시간 구간으로 분리한다.
- train은 좋고 holdout이 나쁘면 승격하지 않는다.
- estimate와 uncertainty가 모두 있어야 하며, `confidence=high` 같은 단일 문자열만 저장하지 않는다.
- 기존 context/digest/revision/atomic write 계약을 재사용하되 raw evidence digest와 estimator version을 추가한다.

### 2. `MotionEnvelopeCertificate`

이 인증서는 geometry/sensor 인증서와 독립 revision을 갖고 반드시 그 digest를 참조한다.

```yaml
schema_version: 1
geometry_sensor_digest: ...
conditions:
  surface_class: ...
  payload_range_g: [...]
  battery_voltage_range_v: [...]
  imu_temperature_range_c: [...]
  tire_or_wheel_revision: ...
speed_bins_mps:
  - speed: 0.014
    direction: forward
    trials: ...
    command_to_decel_p99_s: ...
    decel_lower_bound_mps2: ...
    stop_distance_upper_m: ...
    lateral_error_upper_m: ...
holdout:
  passed: false
  bag_digests: [...]
authorized_max_linear_mps: 0.014
status: candidate
```

직선 정지뿐 아니라 회전 command→zero 지연, reverse, 곡선 감속도 따로 측정한다. 평균 감속이 아니라 보수적인 하한과 정지거리 상한을 사용한다. 한 번의 성공은 인증서가 아니다.

### 3. 런타임 `CalibrationLease`

인증서는 장기 기록이고 lease는 현재 조건의 짧은 권한이다. CORE의 최종 `cmd_vel` 소유권을 유지한 채 다음 최솟값으로 매 cycle 제한한다.

```text
v_allowed = min(
  authorized_tier_cap,
  clearance_cap,
  curvature_cap,
  time_to_collision_cap,
  sensor_health_cap,
  localization_confidence_cap,
  operator_or_fleet_cap
)
```

요구 정지거리의 시작 모델은 다음처럼 두되, 각 항은 실측 상한·하한으로 교체한다.

```text
d_required(v) = d_static
              + u_footprint + u_extrinsic + u_localization
              + v * (t_command_p99 + t_sensor_age + t_control_cycle)
              + v^2 / (2 * a_stop_lower)
```

여기서 `a_stop_lower`는 해당 surface/voltage/payload speed bin의 보수적 감속 하한이다. 측면 여유도 `nominal clearance - (u_footprint + u_extrinsic + u_localization)`로 판단한다. `map_260905_update_v2`의 명목상 285–290 mm 통로가 넓어 보여도 이 불확실성 합과 실제 정지 엔벨로프가 없으면 고속 단계를 허용하지 않는다.

## 단계별 속도 승인

아래 값은 **구조 예시**이며 실물 승인값이 아니다. `0.005`와 `0.014 m/s`는 현재 코드의 제한/저속 domain이고, 그 위 값은 인증 자료가 생길 때까지 HOLD다.

| 단계 | 상한 예시 | 필요한 증거 | 즉시 강등 조건 |
|---|---:|---|---|
| `HOLD` | 0 | identity/context 불일치 또는 필수 센서 미준비 | 기본 상태 |
| `LIMITED` | 0.005 m/s | 명시적 제한 센서 모드, fresh safety evidence | lease 만료, 장애/tilt/cliff |
| `CRAWL` | 0.014 m/s | 현행 translation+rotation certificate, geometry revision 일치 | cross-sensor residual 초과 |
| `LOW` | 0.03 m/s 후보 | 별도 stop-envelope holdout, closed-loop odom 지연 검증, 충분한 여유 | 환경 band 이탈 또는 stop residual 초과 |
| `NOMINAL` | 0.06 m/s 후보 | 여러 surface/전압/payload 세션과 FIELD 승인 | 어떤 하위 조건이라도 악화 |

승격은 정지 상태에서만 명시적으로 수행한다. 강등은 즉시 자동 수행한다. 단계 경계에는 히스테리시스와 release consecutive samples를 두되, 진입 지연은 허용해도 정지/강등 지연에는 쓰지 않는다.

## 런타임 drift와 무효화

### hard invalidation

- robot identity, hardware model, geometry/sensor revision, data generation 불일치
- wheel/tire, motor, caster, payload mount, LiDAR/IMU mount 변경
- encoder resolution/sign, motor firmware/profile, URDF/TF 변경
- BNO offset signature 또는 axis mapping/operation mode 변경
- calibration schema/estimator version 비호환, record digest 실패

hard invalidation은 `HOLD` 또는 last-known-good의 더 낮은 명시적 단계로 간다. 자동으로 새 active 값을 만들지 않는다.

### runtime downgrade

- wheel yaw와 IMU relative yaw innovation 증가
- wheel delta와 LiDAR scan-match delta의 연속 residual 증가
- commanded zero 뒤 실제 stop latency/distance가 인증 상한을 초과
- scan rate/completeness 저하, source age 증가, SLAM pose covariance 또는 correction jump 증가
- battery/temperature/payload/surface proxy가 인증 band 이탈
- 좌우 slip 비대칭 또는 lateral drift 증가

한 번의 outlier는 증거로 기록하고, 위험 임계 초과는 즉시 감속한다. 연속적인 완만한 drift는 `CRAWL`로 강등하고 새 candidate 보정을 요청한다. 운행 데이터로 active parameter를 바로 갱신하지 않는다.

## 권장 실행 순서

1. **관측 계약부터 확장**: BNO status/calibration/self-test/temperature, LiDAR health·scan completeness·frequency, encoder raw delta와 odom covariance를 기록한다.
2. **인증서 분리**: 현재 calibration record v1의 context/locking/digest를 보존하면서 geometry/sensor와 motion-envelope schema를 분리한다.
3. **candidate estimator**: 기존 왕복·회전 trial을 raw evidence producer로 바꾸고 joint wheel/LiDAR estimator를 오프라인으로 실행한다.
4. **holdout runner**: candidate를 실제 active에 적용하지 않은 격리 제어 경로에서 별도 arc/rotation/round-trip을 검증한다.
5. **저속 정지 벤치**: 먼저 0.014 m/s에서 command→motor→odom→정지 latency와 거리를 반복 측정한다. 실패 시 고속 연구를 중단한다.
6. **CORE lease 연결**: 최종 cap은 CORE `SafetyManager`가 소유하고 Nav2/수동/Fleet 모두 같은 cap과 fresh sensor policy를 통과시킨다.
7. **Nav2 재구성 검증**: installed Jazzy 기준으로 curvature regulation, cost regulation, velocity smoother closed-loop, Collision Monitor last-stage 구성을 simulation→Device 순으로 시험한다.
8. **단계별 FIELD 승인**: `CRAWL → LOW → NOMINAL`을 각각 별도 기록으로 승인하며, Gazebo 성공을 실물 단계의 근거로 사용하지 않는다.

## 판정

현재 Rosy auto-calibration은 “정지 센서 점검 + 매우 짧은 저속 translation/rotation 일관성 검증”으로는 상당히 방어적이다. 그러나 wheel kinematic parameter의 관측 가능한 joint estimate, 실제 covariance, 속도별 braking response, 환경별 유효범위, 독립 holdout이 없으므로 고속 적응 제어의 근거로 확장해서는 안 된다.

가장 먼저 구현할 구조적 변화는 **보정값 인증서와 속도·정지 엔벨로프 인증서를 분리하고**, 두 인증서를 fresh runtime drift monitor가 짧은 lease로 결합하도록 만드는 것이다. 이 구조라면 열린 공간에서는 검증된 단계만큼 속도를 올리고, 좁은 공간·센서 열화·바닥 변화에서는 즉시 낮은 단계로 돌아갈 수 있다.
