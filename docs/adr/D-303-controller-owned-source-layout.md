## D-303 소스 폴더는 로컬 제어 권한과 사이트 정본을 먼저 드러낸다

**Status:** Proposed (2026-09-27). 현재 소스 이동이나 배포 승인이 아니다.

**Context:** D-231의 `contracts/runtime/devices/hmi/site` 배치는 계층을 보여 주지만 한 Pinky 제어기의 실행 코드가 `runtime`, `devices`, `hmi`, `contracts/foundation`에 흩어져 있다. 반대로 `core_common`에는 Pinky 로컬 설정·도메인 코드와 로봇↔Fleet 스키마, 사이트 전용 `SiteSightingPayload`, `FleetTaskStatus`, `DiscoveryScanPayload`가 함께 있다. Fleet은 `schemas`, `sightings`, `intent`, `succession`을 생산 코드에서 사용하고, Overhead는 `sightings`를 사용한다. Overhead는 D-18의 세 번째 실제 소비자 재검토 조건에 해당한다. `src/contracts/interfaces`의 ROS `.srv`는 현재 로봇 내부 인터페이스이며 사이트 계약이 아니다.

**판정 순서:** (1) 최종 actuator 명령과 정지를 소유하는 제어기, (2) Fleet 미션 정본, (3) 실제로 교환하는 버전된 데이터, (4) 독립 배포·시험 단위, (5) 호스트와 제품 구성. 같은 호스트에 놓이는지는 1~4를 바꾸지 않는다. Pinky 탑재 OMX도 base와 arm의 최종 writer를 각각 유지하고 로컬 상호 인터록을 별도로 판정한다.

**선택:** 소스의 최상위 경계는 **`controllers / site / contracts / products / sim`** 으로 잡는다. `controllers` 아래는 물리 권한별로 `base`와 `arm`을 둔다. `base`는 로봇 로컬 미들웨어와 현재 Pinky 하드웨어 적응·로컬 화면을 포함한다. `arm/omx`는 OMX 로컬 제어기 후보만 포함하며 운영 capability는 기존 게이트 전까지 비활성이다. `site`는 Fleet 원장과 Overhead 관측, Games를 유지한다. `contracts`는 실제 독립 소유자 사이의 교환 모델만 담는다. 제품 폴더는 설정·조립만 담는다. `ROSY Platform`은 이 집합의 제품 이름이며 프로세스나 `src/platform` 패키지 이름이 아니다.

```text
src/
├─ controllers/
│  ├─ base/
│  │  ├─ foundation/       # core_common 중 로봇 로컬 설정·도메인·profile
│  │  ├─ interfaces/       # 현행 ROS .srv, 로봇 내부 소유
│  │  ├─ gateway/          # core, 최종 cmd_vel 경로
│  │  ├─ services/         # core_features
│  │  ├─ events/           # core_events
│  │  ├─ api_web/          # core_api_web
│  │  ├─ sensing/          # control, 최종 명령 중복 발행 금지
│  │  ├─ navigation/
│  │  ├─ hardware/{pinky_pro,common}/
│  │  └─ hmi/{dashboard,face,web}/
│  └─ arm/omx/adapter/    # 현행 omx_adapter
├─ site/{fleet,overhead,games}/
├─ contracts/             # 실제 교환 계약을 추출할 때 생성
│  ├─ robot_link/         # Fleet↔base 기존 wire 의미만
│  └─ site_sighting/      # Overhead↔Fleet 관측 의미만
├─ products/{pinky_pro,omx}/
└─ sim/{description,gz_sim}/
```

위 트리의 `contracts/*`는 **목표 위치**이며 지금 빈 폴더나 새 패키지를 만들지 않는다. `robot_link`에 OMX를 미리 편입하지 않는다. 로봇 전용 값(`RobotMode`, 주행·배터리)과 Fleet 미션 상태(`FleetTaskStatus`)를 범용 장치 enum으로 합치지 않는다. `core_common.intent`와 `succession`은 호출자가 둘이라는 이유만으로 wire contract가 되지 않는다. 이 두 규칙은 실행 책임과 의존 관계를 별도로 판정한다.

**대안:** D-231 현행 계층을 유지하면 이행 비용이 작지만 `core_common`의 소유 혼합과 제어기 소스 분산이 남는다. `src/platform`에 모든 실행을 모으면 설치·권한 경계를 폴더에서 읽기 어렵다. 제품별 `pinky_pro`·`omx` 최상위 실행 루트는 두 번째 차체에서 base 실행 코드 복사를 부른다.

**D-231/D-18 관계:** 채택되면 D-231의 소스 위치 표와 `test_target_layout.py` 목표를 이 결정으로 대체한다. D-231의 패키지 이름 유지, 제품 설정 전용, 빈 골격 금지, 릴리스 사이 이동, 검증 게이트는 유지한다. D-18의 단일 스키마 재사용은 기존 wire 호환을 유지한 채 실제 교환 계약을 분리하는 시점에 대체한다. 이 Proposed 문서만으로 Accepted ADR을 바꾸지 않는다.

**이행 순서:** [폴더 이행 계획](../plans/2026-09-27-platform-owner-layout-migration.md). 계약 추출과 경로 이동은 별개 변경으로 검증한다. 호스트 시험은 DEVICE/FIELD 수용을 대체하지 않는다.
