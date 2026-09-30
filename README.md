# ROSY Platform — 장치 미들웨어와 현장 Fleet

**Rosy** (ROS + Pinky 계보) — Pinky Pro 하드웨어(첫 구현)를 시작으로, 어떤 로봇이든
웹·표준 API로 제어하고 중앙 Fleet에서 군집 관리하는 범용 로봇 플랫폼.

> Upstream: [pinky_pro](https://github.com/pinklab-kr/pinky_pro) 기반 포크 — 전면 리네임(D-16), Apache-2.0.

`ROSY Platform`은 전체 제품이다. 장치 미들웨어는 각 장치에서 API·상태·안전·최종
명령을 소유하며, 현장 `Fleet`은 미션 순서와 작업 원장을 소유한다([D-296](docs/adr/D-296-device-middleware-and-site-orchestration-terminology.md)).
Pinky 주행은 CORE, OMX 팔은 장치 수용을 마친 OMX 로컬 제어기가 최종 명령을 맡는다.
`src/runtime/`은 소스 분류이며 모든 장비가 공유하는 실행기나 배포 단위가 아니다.

## 관제 배치

현장 Ubuntu PC가 Fleet·Vision·Caddy 서비스를 실행하고, 관제 PC는 HTTPS로 Fleet의
`/console`을 여는 브라우저 단말이다. 두 역할은 한 물리 PC에 함께 놓을 수도 있다.
Pinky의 화면과 최종 주행·정지 판단은 각 로봇의 CORE에 남는다. OMX-AI 작업대 제어는
별도 로컬 인스턴스의 수용 절차가 필요하다. 현재 화면은 Fleet 콘솔이며,
`ROSY Console`은 사람의 화면·대화 접점에 쓰는 제품 이름이다. 자연어 명령과
OMX 원격 작업은 아직 수용된 기능이 아니다.

배치 결정은 [D-275](docs/adr/D-275-web-surface-and-video-runtime-ownership.md)와
[D-290](docs/adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md),
현장 접속 절차는 [사이트 배포 설명](deploy/site/README.md)을 따른다.

## 구조

D-315는 폴더의 뜻을 **소스 책임 분류**로 한정한다. 디렉터리 경로, ROS 패키지명,
실행 프로세스, 최종 명령 writer, 설치 호스트·이미지 단위는 각각 별도 증거로 판단한다.
따라서 products/가 최종 명령을 소유한다고 보거나, runtime/을 모든 제품이 공유하는
엔진으로 보거나, site/·hmi/ 경로만으로 PC 배치를 추론하지 않는다.
실제 패키지 소비와 설치 묶음은 deploy/ 및 각 package.xml에서 확인한다.
상세 판정은 [D-315](docs/adr/D-315-source-folder-responsibility-and-runtime-authority.md),
실행과 후속 감사 범위는 [계획](docs/plans/2026-09-28-source-folder-roles-and-runtime-audit.md)에 기록했다.

구조를 정할 때는 아래 축을 각각 판단한다. `src/` 경로는 코드 책임 분류이고,
ROS package.xml은 colcon 패키지 경계다. 둘 다 실행 프로세스·호스트·최종 명령
소유자·설치 이미지까지 자동으로 정하지 않는다.

| 질문 | 배치 기준 | 현재 예 |
|---|---|---|
| 계약·타입인가? | ROS 인터페이스는 `src/contracts/interfaces`, 공통 Python 계약 모듈은 의미에 따라 `src/contracts/foundation`에 둔다. 계약은 동작을 실행하지 않는다. | `interfaces`, `core_common` |
| 로봇 실행 구성요소인가? | ROS 실행 패키지는 `src/runtime/<role>`에 둔다. `runtime/`은 모든 제품이 공유하는 단일 엔진을 뜻하지 않는다. | `runtime/gateway`의 `core`는 Pinky 장치 미들웨어다. `runtime/sensing`의 `control`은 별도 ROS 패키지다. |
| 제품별 소스·번역기인가? | 실제 제품 전용 프로필·bringup·ROS/vendor API adapter는 `src/products/<model>`에 둔다. adapter 경로만으로 최종 writer나 운용 수용을 선언하지 않는다. | `products/pinky_pro`, `products/omx/adapter` |
| 현장 서버 기능인가? | 중앙 현장 서비스는 `src/site/<service>`에 둔다. Fleet은 작업 원장을 소유하고 장치 actuator를 쓰지 않는다. | `site/fleet`, `site/vision` |
| 사용자 표시 자산인가? | 화면 자산은 `src/hmi/<surface>`에 둔다. 실제 제공 프로세스와 호스트는 서버·배포 정의에서 확인한다. | CORE가 제공하는 `hmi/dashboard`, Fleet이 제공하는 `site/fleet` console |
| 드라이버·시뮬레이션인가? | 칩 수준 코드는 `src/drivers`, ROS/Gazebo 모델과 world는 `src/sim`에 둔다. | `drivers/imu_bno055`, `sim/description`, `sim/gz_sim` |
| 어디서 설치·실행되는가? | 호스트별 설치·이미지·릴리스 closure는 `deploy/`에서 정의하고 package manifest와 빌드 규칙으로 검증한다. | `deploy/robot/pinky_pro`, `deploy/site`, `deploy/robot/pinky_pro/image`, `deploy/robot/pinky_pro/release` |

기기 명령 해석은 그 기기의 로컬 최종 명령 소유자에서 수행한다. Pinky는 CORE가
외부 API intent를 Pinky 주행 동작으로 해석하고 최종 `cmd_vel`을 발행한다.
제품 adapter는 ROS/vendor 표현 사이의 변환에 두며, 그 자체로 별도 동작 owner가
되지는 않는다. 둘 이상의 실제 구현이 같은 코드를 필요로 하고 소유자·생산자/소비자·독립
시험·빌드/설치 경계가 확인되기 전에는
`devices/`, `device_control/`, `controllers/<model>/` 같은 공용 제어 루트를 만들지
않는다. OMX와 드론은 실제 제품 API, 로컬 writer, 설치 경계가 수용되기 전까지
각각 별도 검토 대상으로 둔다. 상세한 재배치 기준은 [D-317](docs/adr/D-317-control-and-shared-contract-source-boundaries.md)을 따른다.

runtime/sensing의 ROS 패키지 이름은 control이며, 현재 센싱·보정·계획·안전·진단 경로가
함께 있다. 이 혼합만으로 즉시 디렉터리를 나누지 않는다. 별도 소비자·시험·설치 경계가
확인될 때 별도 ADR로 판단한다. CORE(runtime/gateway)는 Pinky 최종 cmd_vel 경계다.
폴더 배치 변경은 writer 권한이나 장치 수용을 뜻하지 않는다.

    src/
    ├── contracts/
    │   ├── foundation/            # core_common 공유 타입·프로토콜·설정
    │   └── interfaces/            # ROS 인터페이스
    ├── runtime/
    │   ├── gateway/               # package: core
    │   ├── services/              # package: core_features
    │   ├── events/                # package: core_events
    │   ├── api_web/               # package: core_api_web
    │   ├── navigation/            # navigation
    │   └── sensing/               # package: control (혼합 runtime 경로)
    ├── products/
    │   ├── pinky_pro/             # profile, bringup, ADC, lamp, LED
    │   └── omx/                   # profile, adapter
    ├── drivers/imu_bno055/        # 칩 드라이버
    ├── site/
    │   ├── fleet/                 # 현장 미션·작업 원장·콘솔 서버
    │   ├── vision/                # Rosy Vision: 천장 카메라 입력·sighting 처리(패키지 rosy_vision)
    │   ├── cam/                   # Rosy Cam: 천장 카메라 폰 앱(Android, ROS 패키지 아님)
    │   └── games/                 # 게임 호스트
    ├── hmi/
    │   ├── dashboard/             # CORE API가 제공하는 operator 화면
    │   ├── face/                  # package: emotion
    │   └── web/                   # package: web_common 공유 웹 자산
    └── sim/
        ├── description/
        ├── gz_sim/
        └── isaac_sim/          # Isaac Sim 6.1 standalone integration; GPU runtime validation pending

폴더명과 ROS 패키지 이름은 항상 같지 않다. 예를 들어 runtime/gateway는 core다.
앱은 D-377에 따라 폴더 끝 이름이 `<word>`, 패키지 이름이 `rosy_<word>`다(site/vision은 rosy_vision). products/omx/adapter는 소스 위치를 말할 뿐,
OMX 장치의 운영 writer 수용 완료를 뜻하지 않는다. Fleet console은 site/fleet 서버가
제공하고, 브라우저 관제 PC는 별도 배치가 가능하다. 영상 경계는 [D-275](docs/adr/D-275-web-surface-and-video-runtime-ownership.md)를 따른다.

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

새 Python ament 패키지를 추가하거나 옮긴 뒤 resource marker가 빠졌다면
`bash tools/fix_ament_resource.sh`로 `resource/<package>` marker를 다시 만든다.
이 스크립트는 패키지 manifest나 colcon build를 대신하지 않는다.
로컬 수동주행 메모와 주행 세션은 소스나 설치물이 아니라 `data/teleop` 및
`data/drive`에 둔다. 세션 파일은 커밋하지 않으며, 예외는 `data/README.md`를 따른다.

## Raspberry Pi 5 런타임

**로봇은 네이티브로 돈다.** 제품 런타임은 Docker가 아니라 Ubuntu Server 24.04
arm64 위의 ROS 2 Jazzy + systemd다 (D-161). `rosy-runtime.target`이 CORE를 기본
기동하고, I/O와 navigation은 승인 후 명시적으로 켠다. Docker/Compose는 개발·CI
전용이며 제품 이미지에는 설치하지 않는다. 장치마다 컨테이너를 켜고 끄는 옵션은
없고, 유연성은 프로필/slice로만 표현한다 — 컨테이너는 안전 계획 밖 비전·AI 같은
선언된 사이드카 워크로드에만 허용된다 (D-197, D-246).

런타임 슬라이스는 단계별로 나뉜다. `rosy-core`는 FastAPI/rclpy만 소유하고,
`rosy-motor`는 LiDAR 없는 벤치 커미셔닝, `rosy-io`는 승인된 모터·LiDAR 통합
운용에 사용한다.

```bash
cd deploy/robot/pinky_pro
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
