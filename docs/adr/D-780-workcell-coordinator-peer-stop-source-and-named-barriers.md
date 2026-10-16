## D-780 작업대 조율자와 owner의 연결: 조율자 peer, COORDINATOR 정지 출처, 이름 붙은 barrier

**Status:** Proposed

이 ADR은 D-778 §9의 두 선행 조건을 정한다. 하나는 조율자 peer와 `COORDINATOR` 정지 출처이고, 다른 하나는 `PHASE_WAIT` 상태와 barrier 해제 연산이다. 둘 다 같은 연결, 즉 조율자와 팔 owner 사이의 Unix socket을 다루므로 한 ADR에 둔다. 코드 변경, 실제 서비스 UID, 장치 수용을 뜻하지 않는다. 폴더나 패키지 구조는 바꾸지 않는다.

## Context

[D-778](D-778-bimanual-workcell-foundation.md) §5는 작업대 조율자의 권한을 두 가지로 정했다. barrier 해제와 결합 정지다. 조율자는 grant를 만들거나 전달하지 않는다. [D-779](D-779-per-arm-cell-job-ledger-and-arm-zone-claims.md)는 원장과 grant 필드(`arm_role`, `pair_id`, `partner_instance_id`)를 팔 단위로 나눴다.

지금 owner 연결은 Fleet 하나만 상대한다. 로컬 main 기준의 소스를 읽은 결과다.

| 영역 | 지금 | 근거 |
|---|---|---|
| peer 인증 | owner는 `SO_PEERCRED` UID를 Fleet 서비스 UID 하나와 비교한다. 주체 이름은 `fleet-uid-<uid>`다 | D-336 §2, `middleware/devices/omx/agent/src/rosy_agent/omx_cell_owner.py` |
| 정지 출처 | `StopRequestSource`는 `fleet`과 `operator_local` 둘이다. owner는 Fleet UID의 정지를 `FLEET`으로 기록한다 | `contracts/foundation/core_common/protocol/schemas.py`, `omx_cell_owner.py` |
| UDS 연산 | `SubmitAction`, `GetAction`, `CancelAction`, `GetOwnerIdentity`, `GetOwnerState`, `RecoverOwner`, `StopLocal`, `GetStopState`, `RearmLocal` | `middleware/devices/omx/adapter/omx_adapter/action_api.py` |
| phase 진행 | 실행기는 앞 phase가 SUCCEEDED일 때 다음 phase 하나만 낸다. 그 전에 `phase_gate`를 부른다. gate가 True가 아니면 기다리지 않고 예외를 낸다. cell owner는 gate를 늘 True로 둔다 | `pick_place_runner.py` `start`·`advance`, `omx_cell_owner.py` |
| 시간 한계 | `ArmCommandOwner`의 `action_timeout_s`는 ROS 목표 하나의 한계다. phase 사이의 시간은 세지 않는다 | `command_owner.py` |
| HOLD | owner HOLD는 걸리면 풀리지 않고, 운영자 확인 `RecoverOwner`가 필요하다 | D-386, `owner_recovery_api.py` |
| phase 상태 전달 | Fleet에는 phase 요약을 UDS v2 receipt로 읽기 전용 전달한다. 새 공개 REST 경로는 만들지 않는다 | D-376 §7 |

## Decision

### 1. 조율자는 별도 서비스 UID를 가진 두 번째 peer다 (D-336 §2 보강)

- 양팔 작업대 조율자는 전용 서비스 UID로 실행한다. Fleet과 같은 UID를 쓰지 않는다.
- 각 팔 owner는 설정으로 허용 peer 목록 두 개를 가진다. `fleet_peer_uids`와 `coordinator_peer_uids`다. 주체 이름은 `coordinator-uid-<uid>`다. 팔이 하나인 작업대는 조율자 목록이 비어 있다.
- 연산별로 허용 주체가 다르다.

| UDS 연산 | Fleet | 조율자 |
|---|---|---|
| `SubmitAction`, `CancelAction`, `RecoverOwner`, `RearmLocal` | 허용(지금처럼) | 거부 |
| `GetAction`, `GetOwnerIdentity`, `GetOwnerState`, `GetStopState` | 허용 | 허용(읽기) |
| `StopLocal` | 허용, 출처 `FLEET` | 허용, 출처 `COORDINATOR` |
| `GetBarrier`, `ReleaseBarrier` (§3) | 거부 | 허용 |

- `ReleaseBarrier`를 Fleet에 허용하지 않는다. barrier는 실시간 동기이고, Fleet은 그 경로에 있지 않다(D-778 §5).
- 조율자 UID가 보낸 `SubmitAction`은 grant 내용이 맞아도 거부한다. owner는 grant의 출처를 Fleet UID로만 인정한다.

### 2. 정지 출처에 `COORDINATOR`를 더한다

- `StopRequestSource`에 `coordinator`를 더한다. 이는 공개 프로토콜 변경이므로 API reference 버전과 `schemas.py`를 같은 변경에서 고친다(D-18).
- 조율자의 `StopLocal`은 지금의 로컬 정지와 같은 효과를 낸다. 진행 중 목표를 취소하고 owner를 HOLD로 둔다. HOLD는 걸리면 풀리지 않는다.
- 조율자는 `RearmLocal`이나 `RecoverOwner`를 할 수 없다. 조율자가 건 정지를 푸는 것은 지금처럼 운영자 확인을 거친 Fleet이나 로컬 운영자다.
- 조율자는 정지를 보낼 때 이유를 함께 적는다. `PARTNER_FAILED`, `PARTNER_UNKNOWN`, `PARTNER_LINK_LOST`, `BARRIER_TIMEOUT` 가운데 하나다. owner는 출처와 이유를 정지 기록에 남긴다.

### 3. 이름 붙은 barrier와 `PHASE_WAIT`

**barrier 정의:**

- 협조 Step의 각 팔 Action 내용에는 `barriers` 목록이 들어간다. 항목마다 이름(`barrier_id`), 그 barrier가 놓이는 phase 경계(`after_phase` 또는 `before_first_phase`), 그 뒤 구간의 결합 방식(`coupling_after`), 최대 대기 시간(`max_wait_s`)이 있다.
- 두 팔의 같은 `barrier_id`가 짝을 이룬다. 이름은 역할 짝마다 정한다. D-778 §6의 예는 `handover`의 `both_grasped`, `place`+`push`의 `placed_before_push`다. barrier의 차례 번호(k)는 쓰지 않는다. 두 팔의 phase 수가 다르기 때문이다.
- `barriers`는 컴파일 결과의 일부다. 그래서 Job 해시와 승인이 덮는다(D-401 §3, D-779 §2).

**owner의 동작:**

- 실행기는 barrier가 놓인 경계에 이르면 다음 phase를 내지 않는다. 대신 phase 기록에 `PHASE_WAIT`(`barrier_id`, 도착 시각)를 남긴다. 이 상태에는 ROS 목표가 없다. 그러므로 `ArmCommandOwner`의 목표 시간 한계는 적용되지 않는다.
- `phase_gate`는 예외를 내지 않고 "기다림"을 돌려줄 수 있어야 한다. 실행기는 기다림이면 `PHASE_WAIT`를 기록하고 돌아간다. owner는 lock 안에서 기다리지 않는다(D-386). 이후 owner의 주기 점검이 해제 여부를 보고 다음 phase를 낸다.
- **`GetBarrier`:** Action의 barrier 상태(`not_reached`, `waiting`, `released`, `expired`)와 도착 시각을 돌려준다.
- **`ReleaseBarrier`:** 조율자가 `action_id`, `pair_id`, `barrier_id`, 짝 팔의 도착 기록을 보낸다. owner는 아래 다섯 가지가 모두 맞을 때만 해제를 기록하고, 그 뒤에 다음 phase를 낸다.
    - 자기 grant의 `pair_id`와 같다.
    - 그 `barrier_id`가 자기 계획에 있다.
    - 자기가 그 barrier에 도착해 있다.
    - 정지 세대와 권한 epoch가 현재와 같다.
    - 아직 해제되지 않았다.
- 같은 해제를 두 번 받으면 같은 결과를 돌려준다. 한 번 해제된 barrier는 되돌리지 않는다.
- owner는 짝 팔의 도착을 직접 확인할 수 없다. 짝의 도착 기록은 해제 기록에 함께 남겨 추적에만 쓴다. 인증된 조율자를 믿는 것이 이 연결의 전제다.

**기다림의 한계:**

- `max_wait_s`가 지나도록 해제되지 않으면 owner가 스스로 정한다.
    - 그 Action에서 아직 움직인 phase가 없으면(`before_first_phase`) Action을 `FAILED`(`BARRIER_TIMEOUT`)로 끝낸다. 움직인 것이 없으므로 HOLD하지 않는다.
    - 이미 움직인 phase가 있으면 owner를 HOLD로 둔다. 팔이 물체를 잡고 있거나 다른 물체 곁에 있을 수 있기 때문이다.
- `max_wait_s`의 값은 Step마다 컴파일러가 정한다. 시작 값은 G1 시뮬레이션에서 정한다.

### 4. 단단한 결합 구간에서는 조율자의 생존을 확인한다

- owner는 `coupling_after: tight`인 barrier를 지난 뒤부터, 다음 barrier에서 결합이 `loose`나 `independent`로 바뀔 때까지를 단단한 결합 구간으로 본다.
- 이 구간에서 조율자는 짝의 두 owner에 정해진 주기로 `GetBarrier`나 `GetAction`을 보낸다. owner는 마지막 조율자 연락 시각을 기록한다.
- 이 구간에서 조율자 연락이 `coordinator_liveness_s`보다 오래 끊기면 owner는 스스로 HOLD한다. 정지 출처는 `COORDINATOR`, 이유는 `PARTNER_LINK_LOST`로 기록한다. 조율자가 죽어 결합 정지를 보낼 수 없는 경우를 이것으로 막는다.
- `coordinator_liveness_s`의 시작 값은 G1에서 정한다. UDS 왕복 한계(0.25 s)보다 충분히 커야 한다.
- 독립·느슨한 구간에서는 조율자 생존을 확인하지 않는다. 조율자가 없어도 Fleet과 원장이 팔 단위 HOLD를 처리한다(D-779 §6).

### 5. 결합 방식은 grant에도 적는다

- 짝 grant에 `coupling` 필드(`independent`, `loose`, `tight`)를 더한다. 그 Step 전체에서 가장 강한 결합 방식이다. D-779 §7의 짝 grant 필드에 더하는 것이다.
- 조율자는 이 값과 owner가 돌려주는 barrier 상태로, 짝 팔의 실패를 받았을 때 결합 정지를 보낼지 정한다(D-778 §5).
- owner는 grant의 `coupling`과 계획의 `coupling_after`가 어긋나면 그 grant를 거부한다.

### 6. 조율자의 실행

- 소스는 `middleware/devices/omx/agent` 안에 둔다(D-778 §5). 양팔 작업대마다 native systemd 인스턴스 하나다.
- 조율자는 상태를 오래 보관하지 않는다. 재시작하면 두 owner의 `GetAction`·`GetBarrier`로 상태를 다시 읽는다. 재시작 동안 단단한 결합 구간에 있던 팔은 §4로 HOLD된다.
- 조율자와 두 owner는 같은 호스트에 있다(D-336 §1, D-778 §1).

## Alternatives

- **owner끼리 직접 연결하기:** 조율자 없이 두 owner가 서로 barrier를 확인한다. 프로세스가 하나 줄지만, owner가 다른 owner의 peer가 되어 owner마다 연결과 정지 경로가 두 배가 된다. 결합 정지의 판단도 두 곳에 흩어진다. 기각한다.
- **Fleet이 barrier를 해제하기:** 연결은 하나로 충분하다. 그러나 Fleet은 Step을 순차로 처리하고, 틱마다 I/O 상한이 있다. barrier 지연이 Fleet 부하에 묶인다. 기각한다(D-778 Alternatives).
- **barrier 차례 번호(k)로 맞추기:** 단순하지만 역할 짝마다 phase 수가 달라 번호가 맞지 않는다. 기각한다.
- **barrier 시간 초과를 늘 HOLD로 두기:** 단순하지만 아무것도 움직이지 않은 Action까지 운영자 확인이 필요해진다. 움직이기 전의 시간 초과는 FAILED로 둔다.
- **조율자 생존을 확인하지 않기:** 조율자가 단단한 결합 중에 죽으면 짝 팔의 실패가 전달되지 않는다. 기각한다.

## Consequences

- `action_api.py`에 `GetBarrier`·`ReleaseBarrier`가 생기고, 연산별로 허용 주체가 나뉜다. owner 설정에 `coordinator_peer_uids`와 `coordinator_liveness_s`가 생긴다.
- `StopRequestSource`에 `coordinator`가 생기고, 짝 grant에 `coupling`이 생긴다. API reference 버전이 오른다.
- 실행기의 phase 기록에 `PHASE_WAIT`와 barrier 해제 기록이 생긴다. `phase_gate`는 세 값(허용, 기다림, 거부)을 돌려준다. 팔이 하나인 작업대에서는 barrier가 없으므로 지금처럼 늘 허용이다.
- 정지 기록과 Console에 정지 출처 `COORDINATOR`와 그 이유가 보인다.
- D-376 §7의 "UDS operation 6개 유지"는 이미 지금 연산 수와 맞지 않는다. 이 ADR은 두 연산을 더하는 것으로 §7을 부분 대체한다. Fleet에는 계속 읽기 전용 phase 요약만 간다.

## Transition / Validation

1. **SOURCE 시험:**
    - 조율자 UID의 `SubmitAction`·`RecoverOwner`·`RearmLocal`이 거부되는지 확인한다.
    - Fleet UID의 `ReleaseBarrier`가 거부되는지 확인한다.
    - `pair_id`, `barrier_id`, 세대가 다른 해제가 거부되는지 확인한다. 같은 해제를 두 번 받으면 같은 결과를 돌려주는지 확인한다.
    - 움직이기 전의 barrier 시간 초과는 FAILED, 움직인 뒤의 시간 초과는 HOLD인지 확인한다.
2. **G1 SIM:**
    - 두 owner와 조율자로 `place`+`push`와 `handover` 짝을 끝까지 실행한다.
    - 단단한 결합 구간에서 조율자를 죽이면 두 팔이 `coordinator_liveness_s` 안에 HOLD하는지 확인한다.
    - 한 팔에 실패를 주입하면 짝 팔이 `COORDINATOR` 정지로 HOLD하는지 확인한다.
    - `max_wait_s`와 `coordinator_liveness_s`의 시작 값을 정한다.
3. **DEVICE:** 실제 서비스 UID와 systemd 권한, 조율자 재시작 중의 정지를 장치 단계에서 확인한다(D-336 §3, D-281).

열린 질문:

- `GetBarrier`를 따로 둘지, D-376 §7의 v2 phase 요약 receipt에 barrier 상태를 넣을지
- 조율자 정지의 이유 코드를 Console에서 운영자에게 어떻게 보일지

**References:** [D-778](D-778-bimanual-workcell-foundation.md), [D-779](D-779-per-arm-cell-job-ledger-and-arm-zone-claims.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-401](D-401-rosy-cell-application.md), [D-281](D-281-site-host-placement-and-omx-instance-isolation.md).
