## D-303 소스 폴더는 로컬 제어 권한과 사이트 정본을 먼저 드러낸다

**Status:** Proposed (2026-09-27). 현재 소스 이동이나 배포 승인이 아니다.

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
