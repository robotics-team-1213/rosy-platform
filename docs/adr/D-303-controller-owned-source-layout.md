## D-303 소스 폴더는 로컬 제어 권한과 사이트 정본을 먼저 드러낸다

**Status:** Rejected (2026-09-27, 실제 의존·이미지 경로 재검토). 아래 목표 트리는 실행하지 않는다. D-231의 Accepted 위치 규칙이 유지된다.

**재검토 결과:** 이 제안은 최종 명령의 소유권과 모든 실행 코드의 제품별 소유권을 동일시했다. CORE는 현행 Pinky에서 최종 `cmd_vel`을 소유하지만 `robot.model`의 프로필·capability를 로드하는 런타임이고, D-231은 여러 제품이 쓸 실행 코드를 제품 이름 아래 두지 않도록 정했다. `core_common.intent`는 Fleet와 CORE API 양쪽이, `core_common.succession`은 Fleet와 로봇 follower가 함께 실행한다. 이들을 통째로 `controllers/pinky_pro/foundation`에 넣으면 사이트 이미지가 Pinky 폴더에 의존한다. 현재 Fleet Dockerfile은 이미 `core_common` 전체를 복사하므로 실제 분리 범위는 모듈별 소비자와 설치 내용을 먼저 검증해야 한다.

`deploy/robot`은 CORE/IO 이미지와 선택 기능을 포함하고, IO 빌드는 OMX adapter·OMX 제품 설정도 싣는다. 필수 ROS 패키지 목록에도 `omx_adapter`가 있다. `deploy/image`, `release`, `sd`와 장치의 `/opt/rosy/.../deploy/robot` 경로는 이미지 제작·서명·설치 검증에 연결된다. `deploy/robot → deploy/pinky_pro`는 별도 아티팩트 이행 없이는 안전한 폴더 개명이 아니다. `devices/common/imu_bno055`를 Pinky 전용으로 옮길 근거도 부족하다. `sim/description`은 bringup과 필수 장치 이미지가 사용하는 로봇 모델이므로 시뮬레이션 전용이라고 단정할 수 없다.

**유지할 기준:** 폴더는 코드의 역할과 의존 방향을 나타내고, 장치의 최종 명령 소유권은 런타임·프로필·단일 writer 시험으로 검증하며, 이미지에 무엇이 실리는지는 배포 매니페스트로 별도 판정한다. 지금은 D-231의 `runtime / devices / products / hmi / site / contracts / sim`을 유지한다. Pinky 고유 하드웨어는 `devices/pinky_pro`, 제품 구성은 `products/pinky_pro`, CORE 실행은 `runtime`에 둔다. 공통 계약 후보는 실제 생산자·소비자, 버전, 직렬화 호환, 독립 설치 시험을 갖춘 뒤 개별 추출한다. `intent`·`succession`은 wire 스키마와 구분해 실행 규칙의 소유자를 판정한다. 폴더 재배치는 그 판정 뒤 의존 또는 아티팩트 경계를 실제로 개선할 때만 연다.

**다음 검증:** (1) `core_common` 모듈별 CORE·Fleet·Overhead 생산 의존 표, (2) Pinky 이미지의 `omx_adapter` 포함 이유와 제거 조건, (3) `description`의 제품/장치/시뮬레이션 소비자, (4) `deploy/robot` 경로의 설치·릴리스 계약을 확인한다. 이 일은 [플랫폼 역할·계약 계획](../plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md)의 P2 및 배포 게이트 안에서 진행한다.

**Context:** D-231의 `contracts/runtime/devices/hmi/site` 배치는 계층을 보여 주지만 한 Pinky 제어기의 실행 코드가 `runtime`, `devices`, `hmi`, `contracts/foundation`에 흩어져 있다. 반대로 `core_common`에는 Pinky 로컬 설정·도메인 코드와 로봇↔Fleet 스키마, 사이트 전용 `SiteSightingPayload`, `FleetTaskStatus`, `DiscoveryScanPayload`가 함께 있다. Fleet은 `schemas`, `sightings`, `intent`, `succession`을 생산 코드에서 사용하고, Overhead는 `sightings`를 사용한다. Overhead는 D-18의 세 번째 실제 소비자 재검토 조건에 해당한다. `src/contracts/interfaces`의 ROS `.srv`는 현재 로봇 내부 인터페이스이며 사이트 계약이 아니다.

**판정 순서:** (1) 최종 actuator 명령과 정지를 소유하는 제어기, (2) Fleet 미션 정본, (3) 실제로 교환하는 버전된 데이터, (4) 독립 배포·시험 단위, (5) 호스트와 제품 구성. 같은 호스트에 놓이는지는 1~4를 바꾸지 않는다. Pinky 탑재 OMX도 Pinky 주행과 OMX 팔의 최종 writer를 각각 유지하고 로컬 상호 인터록을 별도로 판정한다.

**선택:** 소스의 최상위 경계는 **`controllers / site / contracts / shared_ui / products / sim`** 으로 잡는다. `controllers` 아래는 현재 실재하는 로컬 제어 인스턴스별로 `pinky_pro`와 `omx`를 둔다. `pinky_pro`는 CORE의 최종 주행 명령, Pinky 하드웨어 적응, 로컬 화면을 포함한다. CORE의 내부 구현에 재사용 가능한 부분이 있어도 두 번째 차체의 동일한 실행 규칙은 아직 검증되지 않았으므로 `base`라는 공용 제어기 루트를 선점하지 않는다. 다른 차체가 실제로 생기면 그 차체의 로컬 제어기를 추가하고, 중복이 확인된 실행 코드만 별도 추출한다. `omx`는 팔 로컬 제어기 후보만 포함하며 운영 capability는 기존 게이트 전까지 비활성이다. `site`는 Fleet 원장과 Overhead 관측, Games를 유지한다. `contracts`는 실제 독립 소유자 사이의 교환 모델만 담는다. `shared_ui`는 CORE와 Fleet이 실제로 함께 설치하는 시각 자산 `web_common`을 소유하며 제어 권한이 없다. `products/pinky_pro`는 차체·능력의 설정과 조립을 보유한다. `ROSY Platform`은 이 집합의 제품 이름이며 프로세스나 `src/platform` 패키지 이름이 아니다.

```text
src/
├─ controllers/
│  ├─ pinky_pro/
│  │  ├─ foundation/       # core_common 중 로봇 로컬 설정·도메인·profile
│  │  ├─ interfaces/       # 현행 ROS .srv, 로봇 내부 소유
│  │  ├─ gateway/          # core, 최종 cmd_vel 경로
│  │  ├─ services/         # core_features
│  │  ├─ events/           # core_events
│  │  ├─ api_web/          # core_api_web
│  │  ├─ sensing/          # control, 최종 명령 중복 발행 금지
│  │  ├─ navigation/
│  │  ├─ hardware/         # 현행 Pinky 보드·IMU 적응
│  │  └─ hmi/{dashboard,face}/
│  └─ omx/adapter/        # 현행 omx_adapter, 팔 로컬 owner 후보
├─ site/{fleet,overhead,games}/
├─ shared_ui/web/        # CORE와 Fleet이 소비하는 web_common
├─ contracts/             # 실제 교환 계약을 추출할 때 생성
│  ├─ robot_link/         # Fleet↔Pinky CORE 기존 wire 의미만
│  └─ site_sighting/      # Overhead↔Fleet 관측 의미만
├─ products/{pinky_pro,omx}/
└─ sim/{description,gz_sim}/

deploy/
├─ pinky_pro/            # 현행 deploy/robot의 Pinky 이미지·설치 경로 목표
├─ omx/                  # 현행 비활성 OMX 작업대 경로
└─ site/                 # Fleet·관측 경로
```

위 트리의 `contracts/*`는 **목표 위치**이며 지금 빈 폴더나 새 패키지를 만들지 않는다. `robot_link`에 OMX를 미리 편입하지 않는다. 로봇 전용 값(`RobotMode`, 주행·배터리)과 Fleet 미션 상태(`FleetTaskStatus`)를 범용 장치 enum으로 합치지 않는다. `core_common.intent`와 `succession`은 호출자가 둘이라는 이유만으로 wire contract가 되지 않는다. 이 두 규칙은 실행 책임과 의존 관계를 별도로 판정한다.

**대안:** D-231 현행 계층을 유지하면 이행 비용이 작지만 `core_common`의 소유 혼합과 제어기 소스 분산이 남는다. `src/platform`에 모든 실행을 모으면 설치·권한 경계를 폴더에서 읽기 어렵다. `controllers/base`는 현재 검증된 Pinky 제어 코드를 공용 차체 제어기로 보이게 한다. 두 번째 차체에서 코드 복사가 실제로 나타나면 같은 실행 규칙을 확인해 추출한다.

**D-231/D-18 관계:** 채택되면 D-231의 소스 위치 표, 제품 이름을 실행 루트에 쓰지 않는 위치 규칙, 배포 폴더 제외 범위와 `test_target_layout.py` 목표를 이 결정으로 대체한다. D-231의 기존 패키지 이름 유지, 제품 설정 전용, 빈 골격 금지, 릴리스 사이 이동, 검증 게이트는 유지한다. D-18의 단일 스키마 재사용은 기존 wire 호환을 유지한 채 실제 교환 계약을 분리하는 시점에 대체한다. 이 Proposed 문서만으로 Accepted ADR을 바꾸지 않는다.

**이행 순서:** [폴더 이행 계획](../plans/2026-09-27-platform-owner-layout-migration.md). 계약 추출과 경로 이동은 별개 변경으로 검증한다. 호스트 시험은 DEVICE/FIELD 수용을 대체하지 않는다.
