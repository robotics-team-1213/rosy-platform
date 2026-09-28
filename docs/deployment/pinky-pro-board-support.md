# Pinky Pro — ROSY OS v1 첫 보드 지원

Pinky Pro는 ROSY OS의 첫 하드웨어다. 이 문서는 그 보드 지원 범위다. 새 리눅스가
아니라 Raspberry Pi OS Lite 64-bit + Device Runtime + CORE + 어댑터다.

설계: `docs/plans/2026-09-01-rosy-os-v1-image-release-design.md`.

## 런타임 모드가 광고하는 기능

`ROSY_RUNTIME_MODE`가 CORE에 마운트되는 capability/profile을 고른다.
광고와 실장이 같아야 한다.

| 모드 | 서비스 | 장치 | Capability |
|------|--------|------|------------|
| `core` (기본) | `rosy-core` | 없음 | teleop/lidar/nav/slam 꺼짐 |
| `motor` | + `rosy-motor` | UART4 Dynamixel만 | teleop + encoder. lidar/nav 꺼짐 |
| `hardware` | + `rosy-io` | 모터 + RPLidar (`/dev/ttyAMA0`) | teleop + encoder + lidar + Nav2 goal/return-home. **slam 꺼짐** |

`hardware`는 `navigation/hardware.launch.py`로 모터·LiDAR와 Nav2
localization/navigation을 같이 띄운다. velocity_smoother 출력은 `nav_cmd_vel`이라
Command Manager만 `cmd_vel`을 발행한다(D-2). odom/base TF는 `ROSY_NAMESPACE`(로봇 번호에서 유도, 예: `rosy_01/`) 접두를
붙이고 `map`은 전역으로 둔다(D-4). 현장 맵은 호스트
`/var/lib/rosy/maps/site.yaml`(+이미지)이다. 파일이 없으면 패키지 데모
`map/my_map.yaml`로 떨어진다. 데모 맵으로 맵 클릭을 현장 주행으로 보지 마라.
SLAM은 런치하지 않는다.
IMU·ADC·LCD·LED·lamp는 io 이미지에 넣지 않았다. ADC는 I2C로 아날로그
전압(배터리, IR, 초음파)을 읽는 칩이다. 지금 슬라이스는 그 노드를 띄우지
않으므로 배터리 %는 팩 전압이 아니다.

`GET /api/v1/host/commissioning`은 모드를 CORE가 직접 보고한다.
`motor_hold`는 `core`에서만 참, `lidar_hold`는 `hardware`가 아니면 참이다.
`battery_hold`와 `imu_hold`는 ADC/IMU 드라이버가 이미지에 없는 동안 항상 참이다.
`slam_hold`는 slam_toolbox를 런치하지 않는 동안 항상 참이다. 현장 맵은 SLAM이
아니라 `/var/lib/rosy/maps/site.yaml`을 넣어서 쓴다.
`fleet_hold`는 Fleet 서버와 outbound WS가 없는 동안 항상 참이다. `swarm`은
꺼져 있다.

## 시운전 순서

1. 이미지는 항상 `core`로 기동한다. `MOTOR_HOLD`는 유지한다.
2. UART4와 토크 없는 ping이 끝나면 `.env`에서 `ROSY_RUNTIME_MODE=motor`.
3. LiDAR 수락 후 `hardware`. 모터와 hardware 프로파일은 동시에 켜지 않는다.
   대시보드 맵에서 먼저 **초기 자세**를 찍고 AMCL을 맞춘 뒤 **목표**로 전환한다.
4. 서명 SD 이미지는 아직 없다 (`BUILD_GO` HOLD). 개발 태그는 현장이 아니다.

파일: `deploy/robot/pinky_pro/config/capabilities.{core,motor,hardware}.yaml`.
`pi5-lite`는 `board.yaml` 별칭이며 `resolve-mode.sh`가 `hardware`로 푼다. YAML 복사본은 두지 않는다.
