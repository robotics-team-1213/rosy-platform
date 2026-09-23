# ROSY — Robot Middleware & Fleet Control Platform

**Rosy** (ROS + Pinky 계보) — Pinky Pro 하드웨어(첫 구현)를 시작으로, 어떤 로봇이든
웹·표준 API로 제어하고 중앙 Fleet에서 군집 관리하는 범용 로봇 플랫폼.

> Upstream: [pinky_pro](https://github.com/pinklab-kr/pinky_pro) 기반 포크 — 전면 리네임(D-16), Apache-2.0.

## 구조

Rosy Control의 개발 기준은 이 저장소의 `src/apps/control`로 통합했다.
별도 Control 저장소·웹 서버를 새 운영 구성으로 사용하지 않는다.
현재 소스 편입과 보정 노드 경계 정리는 완료했으며, 전체 runtime·안전 중재·이미지·Pi 인수는 진행 중이다.
현황은 [흡수 실행 결과](docs/plans/2026-09-12-control-absorption-results.md),
결정은 [ADR D-37~D-65](docs/reference/ROSY%20ADR%20Log.md)를 따른다.

```text
rosy/ (이 리포지토리)
├── env.sh                    # 개발 PC: ROS와 워크스페이스를 읽는 유일한 루트 셸
├── docs/                     # 요구사항·ADR·계획·검증 기록
│   └── reference/            # 살아 있는 API 계약과 ADR 로그
├── deploy/                   # 이미지·릴리스·로봇 설치 셸
├── tools/                    # tools/fix_ament_resource.sh, tools/run_fleet_sim.sh, tools/run_data.py
├── data/                     # data/teleop 확인 기록, data/drive 주행 기록. 세션은 커밋하지 않음
├── dock/                     # 충전 도크 펌웨어
├── signal/                   # 신호 제어 펌웨어
├── reference/                # 얼린 pinky_pro zip. 현재 코드가 아님
├── test/                     # 호스트 계약 시험
└── src/                      # ROS 2 패키지 (도메인 그룹)
    ├── core/                 # core·core_common·core_events·core_features·core_api_web·interfaces
    ├── apps/                 # control·emotion·games·omx_adapter
    ├── hardware/             # bringup·led·lamp_control·imu_bno055·sensor_adc
    ├── navigation/           # Nav2/SLAM
    ├── sim/                  # description·gz_sim
    └── site/                 # fleet
```

## 문서 (거버넌스: docs/)

| 문서 | 역할 |
|---|---|
| `docs/spec/ROSY CORE SRS.md` | 로봇(엣지) 요구사항 |
| `docs/spec/ROSY FLEET SRS.md` | 중앙 서버 요구사항 |
| `docs/reference/ROSY API & Protocol Reference.md` | 공유 API/프로토콜 계약 |
| `docs/reference/ROSY ADR Log.md` | 의사결정 색인. 개별 본문은 `docs/adr/D-*.md` |
| `docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md` | 실행 계획·추적 매트릭스 |
| `docs/plans/2026-09-14-site-middleware-role-fabric-design.md` | 관제 서버 gather/scatter와 역할 단일 경계 (D-59) |
| `docs/plans/2026-09-15-navigation-swarm-split-design.md` | 추종을 navigation에서 분리 (D-60) |
| `docs/plans/2026-09-15-navigation-swarm-split.md` | D-60 실행 계획 |
| `docs/plans/2026-09-16-optional-runtime-slices-design.md` | CORE 필수, 나머지 슬라이스 선택 설치 (D-62) |
| `docs/plans/2026-09-16-optional-runtime-slices.md` | D-62 실행 계획 |
| `docs/deployment/arm64-build-notes.md` | ARM64/Pi 빌드 경계와 인수 전제 |

## 빌드

```bash
source env.sh
colcon build --symlink-install --base-paths src

# 시뮬레이션 2대
ros2 launch gz_sim gz_multi.launch.py robots:=2

# core 게이트웨이
ros2 launch core rosy_core.launch.py

# 다로봇 시뮬과 Fleet 콘솔을 한 번에
bash tools/run_fleet_sim.sh
```

## Raspberry Pi 5 런타임

Raspberry Pi OS Lite 64-bit에서는 ROS 2 Jazzy 실행환경을 단계별 서비스로
분리한다. `rosy-core`는 FastAPI/rclpy만 소유하고, `rosy-motor`는 LiDAR 없는
벤치 커미셔닝, `rosy-io`는 승인된 모터·LiDAR 통합 운용에 사용한다.

```bash
cd deploy/robot
sudo ROSY_ROBOT_NUMBER=1 bash ./install-pi.sh
# 신원은 로봇 번호 하나에서 나온다 (ADR D-33). Device installer가 .env를
# 관리하고 두 값을 함께 유도하므로 수동으로 identity를 덮어쓰지 않는다.
# stationary core와 readback gate를 통과하기 전에는 motor/hardware mode를 켜지 않는다.
sudo ./runtime-mode.sh up
```

기동 후 같은 네트워크의 브라우저에서 `http://<raspberry-pi-ip>:8080/dashboard`
를 연다. Rosy API viewer/operator/administrator 토큰으로 로그인하면 로봇 상태,
비상정지, 기능 계약과 Raspberry Pi OS의 CPU·메모리·디스크·온도를 한 화면에서
확인할 수 있다. 화면은 FastAPI에 내장되어 별도 Node.js 서버가 필요 없다.

모터 명령은 ROS와 분리된 `MotorController` 함수 계층에서 유효성 검사,
차동구동 변환, 선속도·각속도·바퀴 RPM 제한을 거친다. 결과는
`APPLIED / LIMITED / REJECTED / DRIVER_ERROR`로 명확히 남으며, 잘못된 입력이나
UART 오류에는 즉시 zero-RPM 정지를 시도한다. DYNAMIXEL 드라이버도 동일한
RPM 상한을 독립적으로 검사하고 엔코더 32비트 롤오버를 안전하게 처리한다.

유선 LAN 없는 SD 카드 굽기, Wi-Fi·SSH 설정, Windows 배포 및 첫 접속은
[`docs/deployment/raspberry-pi-wifi-image.md`](docs/deployment/raspberry-pi-wifi-image.md)를
따른다. 장치 권한과 물리 인수시험은
[`docs/deployment/raspberry-pi-runtime.md`](docs/deployment/raspberry-pi-runtime.md)에
정리되어 있다.
ARM64 빌드 경계와 컨테이너 포함 범위는
[`docs/deployment/arm64-build-notes.md`](docs/deployment/arm64-build-notes.md)를 따른다.

## 로드맵

Phase 0 리네임·멀티로봇 리팩토링 → **Phase 1 core** → Phase 2 웹 대시보드 →
Phase 3 2대 검증 → Phase 4 fleet → Phase 5 Formation → Phase 6 확장.
상세: `docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md`
