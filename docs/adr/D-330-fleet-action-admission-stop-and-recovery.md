## D-330 Fleet의 단일 발행 권한과 정지·재시작 차단을 Mission과 기존 작업에 공통 적용한다

**Status:** Accepted (2026-09-29, 제어권·정지·복구 구조 결정). 새 Mission/OMX API, 자동 정책 dispatch, 사이트 정지 가용성, 물리 E-stop, DEVICE/FIELD 수용을 승인하지 않는다.

**부분 개정 (D-403, 2026-10-01, 시뮬레이션 한정):** [D-403](D-403-fleet-cell-job-route-cell-transfer.md)(Proposed, 사용자 승인)은 §2의 Mission dispatch 보류를 `simulation` 프로필에서만 푼다. 조건은 고정 이미지에서 D-403 §7의 ROS-SIM 정지 세대 producer/consumer 시험을 통과하는 것이다. 그 밖의 프로필에서는 §2 보류가 그대로이고, §1·§3–§5는 바꾸지 않는다.

### Context

D-326은 모델을 Fleet의 실행권 없는 후보 생산자로, D-327은 조작 Action을 장치 로컬 owner의 책임으로, D-328은 Mission/Step 원장을 Fleet 책임으로 뒀다. [정합성 검토](../plans/2026-09-29-er2-adr-consistency-review.md)는 이 소유권들이 양립하지만 발행 경쟁과 정지 후 재발행을 막을 공통 제어 경계가 없다고 확인했다.

현행 `FleetTaskStore.claim_next()`는 `fleet_robot_reservations`를 SQLite 트랜잭션에서 잡지만, 이 표는 `fleet_tasks(task_id)` 외래키에 묶여 있다. 별도 Mission store의 예약만 추가하면 navigation task, Mission Step, Fleet 직접 조작이 같은 장치로 동시에 갈 수 있다. `/api/fleet/estop`과 `/api/fleet/do`의 stop/cancel은 기존 navigation 대기열만 취소한다. `/api/fleet/estop`은 D-276의 명령 전 감사 쓰기가 실패하면 CORE 호출 전에 `503`을 내며, 응답의 `stopped`는 D-298에 따라 CORE HTTP 응답 수이지 물리 정지 증거가 아니다. 장치에서는 ROS goal 접수와 Action 원장 확정 사이에 프로세스가 죽을 수 있다. 재시도 키만으로 이미 접수된 물리 동작을 배제할 수 없다.

### Decision

1. **Fleet의 발행 허가는 한 원자적 권한에서 판정한다.** 기존 navigation task와 새 Mission Step은 동일한 Fleet 저장소 트랜잭션에서 장치·공유 구역 claim을 경쟁한다. 현재의 task 전용 예약 표를 Mission 표와 병렬로 운용하지 않는다. 이관 시 기존 task/attempt 및 예약을 보존하고, 이미 발행된 장치 Action 결과가 불명인 자원은 자동 해제하지 않는다. 같은 장치의 Fleet 직접 조작도 해당 claim과 장치 로컬 lease에 걸쳐 중재한다. 로컬 lease와 출처를 끝까지 전달·검증하기 전에는 그 장치의 Mission과 직접 조작 혼합을 D-308대로 HOLD한다. Fleet claim은 물리 제어권 자체가 아니며 Pinky CORE와 OMX 로컬 owner가 최종 명령 허가를 다시 판정한다.
2. **정지는 발행 차단과 진행 중 동작을 각각 다룬다.** 인증된 사이트 정지 요청은 Fleet의 단조 증가 stop generation을 래치하고 기존 task와 Mission의 READY/QUEUED Step, 새로운 claim 및 직접 발행을 차단한다. claim 뒤 실제 송신 직전에 generation을 재검사하고, 장치 로컬 owner도 자신의 정지 래치와 검증된 허가 세대를 확인한다. Fleet 세대가 장치에 전달·지속·소비되는 계약은 실제 생산자/소비자 시험에서 정한다. 그 전에는 Fleet의 재검사만으로 네트워크 경합이 닫혔다고 주장하거나 Mission dispatch를 열지 않는다. 진행 중 Action에는 장치 로컬 정지를 별도로 요청하고 결과·driver readback을 수집한다. cancel 요청·정지 전송·CORE ACK·장치 Action 결과·물리 정지는 다른 사실이다. 정지 해제나 Fleet/장치 재시작은 어떤 대기 Step이나 미확인 Action도 자동 재발행하지 않는다. Fleet은 재시작 시 발행 차단 상태에서 원장·장치 상태를 조정한 뒤 운영자가 명시적으로 새 발행을 허가해야 한다. 정지 generation 저장에 실패하면 Fleet dispatch는 닫고, 인증된 정지 요청 자체는 가능한 장치에 계속 전달한다.
3. **감사 DB 장애가 전용 사이트 정지 전송을 막지 않는다.** D-276 Decision 4의 명령 전 감사 쓰기 실패 시 `503` 규칙은 `/api/fleet/estop`의 **정지 요청 전송에 한해** 대체한다. 요청자 인증과 operator 권한은 그대로 요구한다. 감사 쓰기를 시도하되 실패해도 정지 fanout을 수행하고 감사 기록의 성공/실패와 대상별 전송/응답 불명을 가능한 경로에 표시한다. 저장소 전체 장애로 감사 사실 자체가 남지 않을 수 있음을 운영상 열화로 보고 복구 뒤 대조하며, 일반 작업·재개·정책 변경은 계속 감사 실패 시 거절한다. `/api/fleet/do`의 순차 `steps`나 일반 cancel을 독립 긴급 정지 경로로 홍보하지 않는다. 이 Fleet API는 원격 **정지 요청**이지 물리 E-stop 회로가 아니다. 네트워크·Fleet 장애 때 사이트 호출이 성공한다고 주장하지 않으며, 장치의 독립 로컬 정지와 물리 E-stop은 별도 경로·실측 게이트다.
4. **장치 발행은 먼저 영속 의도를 기록하고 모호함을 보존한다.** 장치 로컬 owner는 `action_id`/`attempt_id`, 요청 digest, owner generation 및 발행 의도를 driver 호출 전에 영속화한다. driver 접수 후 결과 저장 전 장애가 나면 재시작 시 같은 goal의 readback과 이전 owner 차단을 시도한다. driver가 ID 조회·fencing을 제공하지 않거나 보유·운동 상태가 불명하면 `UNKNOWN`/HOLD로 두고 자동 재발행하지 않는다. Fleet은 이 로컬 모호함을 성공·실패·물리 정지로 추론하지 않는다. 새 attempt는 선행 attempt의 효과와 자원/물체 상태 조정 뒤에만 연다.
5. **외부 계약은 실제 소비자와 함께 승격한다.** 이 ADR은 기존 `/api/fleet/*` 응답을 재해석하거나 새 경로·필드·stop latency를 정하지 않는다. rearm/상태 API, Mission 발행 envelope, 장치 Action 상관관계는 D-18에 따라 API Reference·공유 schema·생산자/소비자 시험을 같은 변경에서 정한다. D-326의 정책 재발의 밸브, D-327/D-328의 Proposed 범위와 OMX disabled 상태는 유지한다.

### Alternatives

- **Mission 전용 예약 표와 별도 scheduler:** 기존 task와 동시에 발행할 경합 창이 생겨 거절한다.
- **정지 때 기존 task queue만 비우고 Mission은 API 호출로 취소:** Fleet/감사 DB 장애, 프로세스 재시작, 늦은 claim을 막지 못해 거절한다.
- **모든 정지에 명령 전 감사 성공을 요구:** 현재처럼 감사 DB 장애가 장치 정지 전송을 막으므로 전용 정지 요청에는 채택하지 않는다.
- **감사 없는 무인 정지 endpoint:** 호출 권한과 사고 추적이 사라지므로 채택하지 않는다.
- **driver ACK 미수신 시 같은 요청 키로 재발행:** 접수 후 응답 손실 창에 이중 동작이 가능하므로 거절한다.

### Transition / validation

1. SOURCE/LOCAL: 현재 task 예약의 migration·동시 claim·직접 조작 경합, 정지 generation과 재시작 후 재발행 차단을 실패 주입으로 검증한다. 사이트 감사 DB를 쓰기 불능으로 만든 상태에서 인증/인가와 전용 정지 fanout을 각각 검증하고, 일반 명령은 계속 거절하는지 확인한다. driver 접수 직후 원장 기록 전 crash window는 fake driver/clock으로 시험한다.
2. ROS-SIM: Pinky navigation과 OMX 고정 `PICK_PLACE`의 발행 경쟁, 한 장치/공유 구역 예약, 정지 직후 late ACK, Fleet/장치 재시작, 통신 상실과 stop generation 재조회, 물체 보유 불명을 분리 재현한다. 시뮬레이션 ACK는 물리 정지 증거가 아니다.
3. ARTIFACT/DEVICE/FIELD: 설치된 Fleet/CORE/OMX 버전과 각 최종 writer, 독립 정지 회로·driver readback·물체 낙하/보유·정지 시간, 감사 DB·네트워크 장애 중 사이트 요청의 도달률, 재개 절차를 별도 판정한다. 실측 전에는 원격 물리 Action과 사이트 전체 정지 가용성, 자동 재발의 capability를 GO로 표시하지 않는다.

**Consequences:** Fleet에는 하나의 발행 권한과 stop generation이 생기며 기존 task API는 호환을 유지한다. 장치 로컬 owner의 안전 판단과 물리 정지는 Fleet 저장소 상태로 대체되지 않는다. D-276의 감사 선행 규칙은 전용 정지 요청 전송에서만 좁게 변경되고, 그 밖의 역할·감사 규칙은 유지된다.

**References:** [D-18](D-18-rosy-core.md), [D-276](D-276-site-fleet-per-principal-api-authorization.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-307](D-307-final-action-outcome-and-stop-readback-evidence.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md), [D-316](D-316-pinky-site-fleet-navigation-result-correlation.md), [D-326](D-326-agent-loop-boundary.md), [D-327](D-327-semantic-manipulation-actions-and-device-adapters.md), [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md).
