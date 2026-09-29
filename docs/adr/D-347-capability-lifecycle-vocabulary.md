## D-347 capability 상태는 단일 생애 어휘로 말한다

**Status:** Accepted (2026-09-29, 계약·어휘만). `GET /api/v1/system/capabilities` 의 `lifecycle` 블록(v1.58 additive)이 전부다. 그래프 기동·컴포넌트 spawn·신규 이벤트 없음. inventory 기술자의 PresentationState는 바꾸지 않는다. `activating` 으로의 진입은 후속 ADR(세션 경계 온디맨드, 토론 B레인) 없이 금지다.

### Context

"각 장비에서 필요할 때 기능을 구동하는 구조"를 향한 설계 토론(2026-09-29)에서 세 레인이 나왔다 — A(프로세스 내 지연 생성), B(노드/그래프 온디맨드), C(상태 계약 선행). 합의: **C가 선행 조건**이다. 클라이언트가 capability를 믿는데 선언과 가용성이 다른 채로는 어떤 동적화도 거짓말을 양산한다.

정찰 결과, 이 저장소는 이미 대부분 지어져 있었다: CAP-001 정적 선언(D-11, 프로파일이 원천 — HWA-003), `runtime_truth`·`withheld` 의 실측 증거 판정(D-32/D-161/D-192), inventory 기술자의 PresentationState 5어휘(concept 16 §8). 진짜 갭은 세 개였다:

1. `GET /system/capabilities` 응답에 **플래그별 상태 필드가 없다** — 클라이언트는 `flags`·`withheld`·`runtime` 을 교차 조인해서 상태를 재구성한다.
2. 어휘가 **이중**이다 — inventory 는 presentation 어휘를 쓰고 capabilities 끝점은 상태가 없다.
3. 온디맨드(B레인)가 착지할 때 쓸 **`activating` 예약 슬롯**이 계약에 없다.

### Decision

1. **단일 생애 어휘를 정의한다.** `CapabilityLifecycle`: `ready` / `unavailable`(+`reason`·`reasons`) / `activating`(예약). `activating` 은 생산자가 없다 — 클라이언트는 이 값을 "준비 안 됨, 실패 아님"으로 읽는다: 갱신하거나 기다리지, 오류로 승격하지 않는다.
2. **판정을 새로 만들지 않는다.** `lifecycle_from` 은 이미 있는 값만 합친다: 모드 마스킹의 `withheld` 사유(선에 실리는 쪽이므로 우선)와 `runtime_truth` 의 플래그별 사유, 그리고 플래그의 참/거짓. 프로파일과 런타임 어느 쪽도 true 로 말하지 않는 플래그는 결과에 없다(설계 §7). 불변식: **wire 의 `withheld.flags` 는 항상 `lifecycle` 의 `unavailable` 집합과 정확히 일치** — 시험이 핀으로 지킨다.
3. **끝점은 additive 다.** v1.58. 기존 필드·501-when-false 게이트(CAP-003)·409 `CAPABILITY_WITHHELD` 는 그대로.
4. **PresentationState 는 그대로 두고 대응은 표로만 정한다.** `unavailable` ≈ `blocked`, `ready` ≈ `available`·`constrained`·`degraded_fallback`, lifecycle에 없음 ≈ `not_provided`. 코드 매핑을 만들지 않는다 — 두 어휘는 쓰임이 다르다(presentation 은 화면 문구, lifecycle 은 기계 계약).
5. **`activating` 진입 금지를 시험이 지킨다.** B레인(세션 경계 그래프 기동)이 착지할 때 이 ADR 의 후속 변경으로 생산자를 허용한다. 예약 슬롯 덕에 그날의 클라이언트는 이미 준비되어 있다.

### Alternatives

- **A레인(매니저 지연 생성):** 매니저는 가볍다 — 절약 실익 없음. 살린 것은 501-when-false 규약 수호뿐. 기각.
- **B레인 즉시 착수:** 실측 관문(D-185 숫자로 낭비 입증) 통과 전 불가. 이 ADR 이 그 관문 앞의 계약 단계다.
- **PresentationState 를 capabilities 끝점에 확장:** 화면 어휘와 기계 계약이 한 enum 에 섞인다. 기각.

### Transition / validation

- `core_common.domain.capabilities.CapabilityLifecycle`·`lifecycle_from`(ROS-free) + `system.py` 끝점 배선.
- `test_capability_lifecycle.py` 6건: 유도 3(사유 있는 플래그 unavailable/§7 부재/`activating` 무생산 핀) + 일관성 2(core+device 전체 보류 일치, motor 마스킹 부재) + wire 1(끝점 additive·withheld 정합). 이웃 185 passed(truth·truthful_core_only·api·foundation).
- API Ref §9.1 `lifecycle` 절 + 변경 이력 v1.58 + 버전 핀 3곳 동시 갱신(ref 헤더·app.py·line-follow 핀).

**Consequences:** 대시보드·Fleet 는 상태 표시의 단일 소스로 `lifecycle` 을 쓸 수 있고, 교차 조인 코드를 걷어낼 수 있다. B레인 착수 시 상태 계약은 이미 제자리 — 남는 결정은 "누가 언제 그래프를 띄우고 내리는가"뿐이다.

**References:** [D-11 capability 정적 선언](D-11-capability-yaml-api.md), [D-32 inventory 가용성](D-32-200.md), [D-161 네이티브 런타임](D-161-ubuntu-server-native-ros-runtime.md), [D-192 하드웨어 런타임](D-192-hardware-runtime-in-the-image.md), 토론 기록(2026-09-29 회차, docs/logs.md), `core_common/domain/capabilities.py`.
