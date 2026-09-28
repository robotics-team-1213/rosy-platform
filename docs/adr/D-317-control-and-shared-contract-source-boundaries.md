## D-317 장치별 해석과 공유 계약은 실제 소비·실행 경계로 분류한다

**Status:** Accepted (소스 분류와 재배치 판정 기준에 한정). 이 결정은 새 패키지, API, 명령 프로세스, 제품 이미지 또는 장치 capability를 만들거나 수용하지 않는다.

**Context:** D-310은 Pinky·OMX 전용 패키지를 `products/<model>`로 옮겼고 D-315는 폴더가 실행 권한·호스트·배포 closure를 대신하지 않는다고 정했다. 후속 읽기 감사에서 `runtime/sensing`의 ROS 패키지 `control`은 센싱 외에도 보정·계획·안전·진단과 legacy proposal 경로를 한 패키지 안에 담고 있음을 확인했다. `core_common`도 `protocol`, `domain`, 설정·identity·profile, `intent`, `succession`처럼 의미가 다른 모듈을 포함한다. 이 혼합은 검토할 구조 신호지만, 이름만으로 각각을 이동하거나 패키지로 나눌 근거는 아니다.

**Decision:**

1. **현재 소스 배치를 유지한다.** `runtime/gateway`의 `core`는 Pinky 장치 미들웨어이며 최종 주행 `cmd_vel`을 소유한다. `runtime/sensing`은 ROS 패키지 `control`의 현 위치다. 제품 전용 소스와 로컬 adapter는 `products/<model>`에 둔다. `products/omx/adapter`라는 경로는 OMX 팔의 실물 운영 owner나 허가를 뜻하지 않는다.

2. **장치별 명령 해석은 최종 writer 소유자 경계에 둔다.** 외부 Intent의 공통 문법·wire 표현은 로컬 writer를 만들지 않는다. Pinky의 주행 해석과 최종 발행은 CORE가 맡는다. 제품별 ROS·vendor API 변환 코드가 실제로 분리될 때 해당 제품의 adapter 위치를 검토한다. 새 `devices/`, `device_control/`, `controllers/<model>/` 루트나 미래 드론의 빈 골격을 미리 만들지 않는다.

3. **`core_common`을 하나의 보편 Action 계약으로 간주하지 않는다.** 모듈을 wire schema, 장치 API 타입, 사이트 계약, 공유 실행 규칙, 로컬 설정·identity/profile로 나눠 실제 생산자·소비자·직렬화 경계와 버전 책임을 기록한다. 현재 `intent` 해석은 Fleet과 CORE가 사용하고, `succession` 규칙은 Fleet과 CORE swarm이 사용한다. `SiteSightingPayload`는 Overhead 생산과 Fleet 소비 경계에 속한다. 이들 소비가 있다는 사실만으로 새 공통 실행 라이브러리나 별도 ROS 패키지를 추출하지 않는다.

4. **`control`은 독립 경계 증거가 생길 때만 분할을 검토한다.** 검토표에는 하위 책임별 소유자, import, console entry point, launch, ROS topic/service writer·consumer, 독립 테스트, package manifest 의존, 이미지·systemd 설치 closure, rollback을 포함한다. 적어도 별도 소유자와 실제로 독립 가능한 빌드·시험·설치·실행 경계가 확인되고 CORE 최종 writer 단일성이 유지될 때 좁은 ADR로 이동 범위를 결정한다. `control`의 ROS 패키지명은 경로 정리만을 이유로 바꾸지 않는다.

5. **소스와 배포 수용을 따로 기록한다.** `deploy/robot`, `deploy/site`, `deploy/omx` 및 각 이미지의 package closure는 실행·설치 증거로 확인한다. source import나 OCI closure 비교만으로 실제 ARM64/Jazzy native payload, 장치 설치, 정지 readback 또는 FIELD 수용을 주장하지 않는다.

6. **D-316 결과의 등급을 보존한다.** Pinky Site Fleet `attempt_id`와 CORE navigation 최종 이벤트의 상관관계는 SOURCE/LOCAL 구현으로 기록한다. ROS-SIM, 이미지, 실제 장치 결과, 물리 정지 readback, SITE/FIELD 수용은 별도 게이트다.

**Alternatives:**

- 모든 장치 해석을 `device_control/` 또는 `controllers/<model>/` 아래로 옮기면 제품별 adapter, 로컬 writer, 로봇 런타임을 다시 한 종류의 계층으로 섞는다. 거부한다.
- `runtime/sensing`을 지금 `runtime/control`이나 Pinky 제품 폴더로 통째 이동하면 단일 `control` 패키지의 실제 역할·설치 closure를 바꾸지 않은 채 이름만 바꾼다. 분리 증거가 나오기 전에는 현 위치를 유지한다.
- `core_common` 전체를 그대로 모든 장치의 공통 계약으로 승격하면 CORE·Fleet·Overhead의 다른 소비 의미를 뭉갠다. 현 패키지는 유지하되 모듈별 소비자 표를 만들고, 분리는 호환·독립 배포 경계가 확인된 뒤 판단한다.

**Consequences:** 소스 트리는 `contracts/`, `runtime/`, `products/`, `drivers/`, `site/`, `hmi/`, `sim/` 분류를 유지한다. 이 결정은 제품별 interpreter 프로세스, 새 Device Action schema, OMX 또는 드론 활성화, 단일 제품별 이미지 정책, 물리 인터록을 승인하지 않는다. 첫 후속 산출물은 책임·소비자·이미지 closure 감사표와 갱신된 구조 계획이다.

**Validation:** [경계 감사 계획](../plans/2026-09-28-control-and-contract-boundary-audit.md)의 SOURCE/LOCAL 출구를 따른다. ROS-SIM·ARTIFACT·DEVICE/FIELD 검증 결과는 본문이나 docs gate에 소급해 주장하지 않는다.

**References:** [D-18](D-18-rosy-core.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-305](D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md), [D-310](D-310-product-specific-source-and-runtime-boundaries.md), [D-315](D-315-source-folder-responsibility-and-runtime-authority.md), [D-316](D-316-pinky-site-fleet-navigation-result-correlation.md), [감사 계획](../plans/2026-09-28-control-and-contract-boundary-audit.md).
