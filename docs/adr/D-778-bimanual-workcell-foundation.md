## D-778 양팔 작업대 기반: 팔 둘을 한 작업대로 묶고, 권한은 짝으로 잡고, 동기는 작업대 안에서 한다

**Status:** Proposed

이 ADR은 양팔 협응을 위한 구조 기반을 제안한다. 구현, 장치 수용, 학습 정책 승격, D-496 스트림 금지의 해제를 뜻하지 않는다.

## Context

2026-10-17 사용자 지시: 양팔 협응은 관제를 하는 핵심 이유 가운데 하나다. 그러니 ADR을 고치고 구조를 개선해, 양팔 협응의 기반을 지금 마련한다. 목표 작업은 천 접기, 뚜껑 열기, 팔레타이징이다.

조사 보고서 [듀얼 로봇팔 운용 조사](../assessments/2026-10-17-dual-arm-operation-research.md)를 바탕으로 한다. 그 보고서는 양팔 협응을 마지막 선택 단계로 두었다. 이 ADR은 그 순서를 바꾼다. 기반은 지금 깔고, 실물에서 여는 것은 단계별로 한다.

### 이번에 확인한 사실

로컬 main `855817932` 기준의 소스와 ADR을 읽은 결과다. 장치나 현장은 관측하지 않았다.

| 영역 | 관측 | 근거 |
|---|---|---|
| 실행 인스턴스 | OMX마다 native systemd 인스턴스가 하나씩 있다. 두 팔을 한 프로세스나 그래프로 합치는 안은 기각됐다 | D-281 §2, Alternatives |
| 로봇 간 조정 | 로봇 간 조정은 공개 API 계약을 거친다. actuator마다 단일 owner를 둔다 | D-282 |
| 작업대 문서 | `cell.yaml`에는 가르친 좌표계 하나만 있고, Step 목표는 `robot_base` 자세다 | D-401 |
| Cell Job | Job 하나에 작업대 하나가 붙는다. 작업대마다 진행 중인 Action은 하나다. Step은 앞 Step이 확인된 뒤에만 실행된다 | D-403 §4–5 |
| 병렬 Step | "복수 Action/병렬 Step"은 아직 결정되지 않았다. 1 Step → 1 Action 제약을 유지한다 | D-435 |
| claim | `fleet_action_claims`는 robot·workcell·object·pallet 종류를 한 트랜잭션 안에서 잡는다 | `operations/fleet/fleet/server/cell/dispatch_admission.py` |
| grant | grant 범위는 (workcell_id, instance_id)에 사이트 공통 `authority_epoch`·`dispatch_generation`을 더한 것이다. TTL은 15 s다 | `step_dispatcher.py` |
| owner | owner는 작업대마다 프로세스 하나이고, 같은 호스트의 Unix socket을 쓴다. 한 명령이 진행 중이면 `busy`를 돌려준다 | D-336, `omx_cell_owner.py`, `command_owner.py` |
| phase 순서 | 다음 phase는 같은 팔의 앞 ROS 목표가 끝난 뒤에만 시작된다. owner는 ROS 응답을 기다리며 막히지 않는다 | D-376 §4, D-386 |
| 실물 명령 | 한 번에 제한된 목표 하나만 보낸다. 100 ms 주기 스트림은 금지된다 | D-496 |
| 학습 정책 | 바인딩은 단일 owner 기준이다. `learned_policy`는 허용 owner가 아니다 | D-449, D-773 §2 |

정리하면, 양팔을 막는 것은 D-281이 아니다. D-401·D-403·D-435의 Cell 계약이 막는다. 두 팔을 함께 잡는 단위, 원자적 권한, 팔 간 barrier가 없다.

## Decision

팔 실행 인스턴스는 지금처럼 팔마다 따로 둔다. 그 위에 **양팔 작업대**라는 단위와 **작업대 조율자**를 더한다. 한 팔 작업대의 경로는 바뀌지 않는다.

### 1. 작업대는 팔 하나 또는 둘을 가진다 (D-401 부분 대체)

`cell.yaml`에 `arms` 목록과 작업대 좌표계를 둔다.

```yaml
cell_frame: cell
arms:
  - role: left
    instance_id: omx_01_control
    base_in_cell: {calibration_revision: ..., T: [...]}
  - role: right
    instance_id: omx_02_control
    base_in_cell: {calibration_revision: ..., T: [...]}
```

- 팔이 하나인 작업대는 `arms`의 길이가 1이다. 지금 문서는 이 형태로 그대로 읽힌다.
- Step 목표는 `cell` 좌표계로 쓴다. 팔로 보낼 때 그 팔의 `base_in_cell`로 바꾼다. 팔이 하나이고 변환이 단위 행렬이면 지금의 `robot_base`와 같다.
- `base_in_cell`은 보정 revision을 가진다. revision이 없거나 만료된 팔이 있으면 양팔 Step을 거부한다.
- 양팔 작업대의 두 팔은 같은 호스트에 있어야 한다(D-336 같은 호스트 socket, 공통 시계).

### 2. 협조 Step이 팔마다 Action 하나를 낸다 (D-435 미결 항목 결정, D-403 §4–5 부분 대체)

- "복수 Action"은 **협조 Step**에만 허용한다. 협조 Step은 같은 작업대의 팔 역할마다 Action을 최대 하나씩 낸다. 서로 다른 작업대에 걸친 병렬 Step은 이 ADR의 범위가 아니다.
- 한 팔만 쓰는 Step도 작업대 전체를 claim한다. 짝 팔이 그 Step을 위해 움직이지 않아도 작업공간을 공유하기 때문이다.
- 양팔 작업대의 Job은 두 팔의 claim을 **한 트랜잭션에서 모두 잡거나 하나도 잡지 않는다**. 일부만 잡힌 상태로 남기지 않는다.
- claim을 유지하고 해제하는 규칙(HELD·UNKNOWN 유지, 타임아웃으로 풀지 않음)은 D-403을 그대로 따른다.

### 3. grant는 짝으로 발급한다

- Fleet은 협조 Step 하나에 팔마다 grant를 하나씩 발급한다. 두 grant는 같은 `authority_epoch`·`dispatch_generation`·`pair_id`를 가지고, 서로의 `instance_id`를 짝으로 적는다.
- 각 owner는 지금처럼 자기 grant를 스스로 재검사한다. `pair_id`가 있는 grant는 작업대 조율자를 통해서만 받는다.
- lease 발급자는 계속 Fleet 하나다(D-773 §2). 조율자는 grant를 만들지 않는다.

### 4. 동기는 작업대 조율자가 한다

작업대 조율자는 양팔 작업대마다 하나 있는 같은 호스트의 프로세스다. 두 owner의 클라이언트일 뿐, 관절에 쓰는 writer가 아니다. 팔 관절의 writer는 계속 각 팔의 `ArmCommandOwner`다(D-773 §1).

- **phase barrier:** 협조 Step의 phase k+1은 두 팔이 모두 phase k를 끝내 terminal 성공을 보고한 뒤에만 시작한다. 조율자는 owner의 lock 안에서 기다리지 않는다(D-386).
- **결합 정지:** 한 팔이 실패, UNKNOWN, 링크 상실, E-stop 상태가 되면 조율자는 짝 팔에 즉시 HOLD를 보낸다. 자동으로 재시도하거나 재생하지 않는다. 다시 시작하려면 두 팔 모두 장치를 재승인하고 새 grant 짝을 받아야 한다.
- **물리 정지:** 양팔 작업대의 하드웨어 E-stop은 두 팔의 서보 전원을 함께 끊는다. 프로세스를 나눈 것은 안전 경계가 아니다(D-281 §3).
- **Fleet의 몫:** Fleet은 작업대를 한 단위로 배정하고 Step 순서를 정한다. 실시간 동기는 Fleet을 거치지 않는다. UDS 왕복과 Fleet의 순차 실행이 동기 주기보다 느리기 때문이다.

조율자는 owner socket으로 두 팔과 통신한다. ROS 그래프를 직접 잇지 않는다. 그러므로 D-281의 인스턴스 분리와 도메인 격리는 그대로 둘 수 있다.

### 5. 협응 수준은 세 단계로 열고, 이 ADR은 L1만 연다

| 수준 | 동작 | 대표 작업 | 이 ADR에서 |
|---|---|---|---|
| L1 phase 동기 | 팔마다 제한된 목표를 받고, phase 경계에서 barrier로 맞춘다 | 팔레타이징(번갈아 적재, 건네주기, 양쪽에서 잡고 들기) | 연다 |
| L2 시작 시각 동기 | grant의 phase에 공통 시작 시각을 담는다. 각 owner는 `JointTrajectory` header stamp를 그 시각으로 둔다 | 물체를 쥔 채 함께 옮기기 | 자리만 둔다. L1 SIM 통과 뒤 별도 수용한다. D-496의 "제한 목표 하나" 규칙 안에서 한다 |
| L3 양팔 스트리밍 정책 | 학습 정책이 두 팔에 짧은 주기로 함께 명령한다 | 천 접기, 뚜껑 열기 | 열지 않는다. D-496 스트림 금지 개정, 두 팔에 걸친 정책 바인딩(D-449), 독립 Safety 리뷰가 든 별도 ADR이 필요하다 |

L3를 나중에 막지 않도록 데이터 모델은 지금 정한다.

- 정책 바인딩은 한 인스턴스가 아니라 작업대(`workcell_id`)와 팔 역할 순서를 가리킨다.
- 양팔 행동과 관측은 `arms`의 역할 순서(left, right)로 이어 붙인다. OMX 기준으로 행동은 12차원(5축 + 그리퍼, 팔 둘)이다. 시연 데이터의 키는 LeRobot의 양팔 관례(`left_*`, `right_*`)를 따른다.
- 양팔 시연 수집은 leader 두 대와 follower 두 대를 같은 작업대 조율자 아래 둔다. 단일 팔 수집 경로(D-770)는 그대로 둔다.

### 6. 바꾸지 않는 것

- D-281: 팔마다 실행 인스턴스를 두고, 장치 소유를 고정하고, 프로세스를 나눈 것이 안전 경계가 아니라는 점.
- D-282·D-773 §1: actuator마다 단일 owner를 두고, 두 writer를 합치지 않는다.
- D-336: owner는 같은 호스트의 Unix socket으로만 받는다.
- D-496: 실물에서는 제한된 목표를 하나씩 보낸다.
- 한 팔 작업대의 Cell 문서, Job, grant, 수용 순서.

## Alternatives

- **두 팔을 ROS 그래프 하나와 MoveIt 하나로 합치기:** 팔 간 충돌 검사와 동기 계획은 공짜로 얻는다. 그러나 장치와 재시작·복구를 팔마다 검증할 수 없게 된다(D-281이 기각한 이유와 같다). MoveIt 2 본선은 독립 동시 실행도 지원하지 않는다. L3에서 한 프로세스가 꼭 필요하다는 증거가 나오면 그때 다시 본다.
- **Fleet이 직접 동기화하기:** Fleet은 Step을 순차로 실행하고, UDS 왕복 한계가 0.25 s다. barrier와 결합 정지를 맡기기에는 느리고 멀다. 기각한다.
- **D-401·D-403·D-435를 각각 개정하기:** 양팔이라는 한 결정이 세 문서에 흩어진다. 이 ADR 하나에 모으고, 해당 조항만 부분 대체한다.
- **양팔을 L3 학습 정책으로 바로 시작하기:** 목표 작업 가운데 천 접기와 뚜껑 열기는 결국 L3가 필요하다. 그러나 단일 팔도 아직 실물에서 수용되지 않았고, D-496은 스트림을 막고 있다. 그래서 기반과 데이터 모델을 먼저 두고, L3는 별도로 연다.

## Consequences

- Cell 문서, Job 저장소, grant 타입에 `arms`, `pair_id`, 짝 instance 필드가 생긴다. 팔이 하나일 때의 기본값은 지금의 동작과 같다.
- 작업대 조율자라는 새 프로세스가 생긴다. 이 프로세스는 writer가 아니지만 HOLD를 보낼 권한이 있다. 그러므로 owner는 조율자를 peer allowlist에 따로 올린다.
- 양팔 작업대에서는 "한 팔이 재시작해도 다른 팔은 계속 간다"는 지금의 검증 기준이 반대로 뒤집힌다. 한 팔 작업대의 검증은 그대로 둔다.
- 하드코딩된 루트 토픽(`/joint_states`, `/arm_controller/follow_joint_trajectory`)은 인스턴스 namespace로 받게 바꾼다. 이 일은 양팔 작업보다 먼저 한다.

## Transition / Validation

1. **G0 문서:**
    - `cell.yaml` `arms` 스키마와 `cell` 좌표계를 정의한다.
    - 지금의 한 팔 Cell 문서가 바뀌지 않고 읽힌다.
    - 시험: 스키마 시험, 기존 Cell 시험.
2. **G1 SIM 권한:**
    - 2-인스턴스 ROS-SIM에 조율자를 더한다.
    - claim을 한쪽만 잡는 데 실패하면 아무것도 남지 않는지 확인한다.
    - `pair_id`가 맞지 않는 grant를 거부하는지 확인한다.
    - 한 팔에 장애를 주입하면 짝 팔이 HOLD하는지 확인한다.
3. **G2 SIM 작업:** 두 팔이 한 팔레트에 번갈아 적재하는 L1 팔레타이징을 끝까지 실행한다.
4. **G3 DEVICE:**
    - 단일 OMX DEVICE 수용(D-496)과 2개 동시 DEVICE(D-281)를 거친다.
    - 그 뒤 양팔 작업대에서 결합 E-stop을 확인하고 L1을 실물로 실행한다.
5. **L2·L3:** 각각 별도로 수용한다. L3는 별도 ADR이 필요하다.

열린 질문:
- 작업대 조율자를 둘 위치(`middleware/devices/omx/agent` 안 또는 별도 패키지)
- `base_in_cell` 보정 절차와 허용 오차
- L3에서 두 팔에 걸친 단일 writer가 필요한지 여부

**References:** [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-401](D-401-rosy-cell-application.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md), [D-435](D-435-work-orchestration-fleet-and-device-authority.md), [D-449](D-449-learning-artifact-and-owner-binding-contracts.md), [D-474](D-474-caution-point-zone-grant.md), [D-496](D-496-omx-hardware-arm-control-acceptance.md), [D-770](D-770-fleet-omx-autonomous-imitation-pipeline.md), [D-773](D-773-omx-ai-extension-platform-structure.md), [조사 보고서](../assessments/2026-10-17-dual-arm-operation-research.md).
