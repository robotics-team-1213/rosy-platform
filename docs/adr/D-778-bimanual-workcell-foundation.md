## D-778 양팔 작업대 기반: 팔 둘을 한 작업대로 묶고, 권한은 Fleet이 짝으로 주고, 동기는 작업대 조율자가 하고, 역할은 Step마다 정한다

**Status:** Proposed

이 ADR은 한 팔과 두 팔 작업대가 함께 쓰는 구조 기반을 제안한다. 구현, 장치 수용, 학습 정책 승격, D-496 스트림 금지의 해제를 뜻하지 않는다. 새 Action 종류, 정지 감지, barrier 연산처럼 기존 실행 계약을 바꾸는 부분은 이 ADR이 방향과 선행 조건만 정하고, 각각 후속 ADR에서 정한다(§9).

## Context

2026-10-17 사용자 지시: 양팔 협응은 관제를 하는 핵심 이유 가운데 하나다. ADR을 고치고 구조를 개선해, 양팔 협응의 기반을 지금 마련한다. 한 팔이나 두 팔로, 도구를 써서 정렬하는 것까지 구현하는 것을 전제로 한다.

목표 작업은 **혼합 팔레타이징**이다. 크기와 모양이 다른 물체를 테트리스처럼 맞춰 쌓는다. 천 접기나 뚜껑 열기 같은 정교한 양손 조작은 목표가 아니다.

근거 보고서: [듀얼 로봇팔 운용 조사](../assessments/2026-10-17-dual-arm-operation-research.md), [혼합 팔레타이징 적재 계획과 양팔 역할](../assessments/2026-10-17-mixed-palletizing-stacking-plan-research.md).

### 두 팔은 어떻게 협응하는가

두 번째 팔은 고정 받침대도, 늘 함께 드는 짝도 아니다. 평소에는 따로 일하고, 계획기가 부를 때만 짧게 돕는다.

| 근거 | 관측 |
|---|---|
| 사람의 양손 작업 | 느슨한 결합(따로 일하며 타이밍만 맞춤)이 46%로 가장 흔했다. 한 손이 받치고 다른 손이 일하는 시간은 28%, 함께 드는 시간은 16%였다. 역할은 순간마다 바뀐다(Krebs & Asfour 2022) |
| 작업 연구 | 손으로 잡고 있기(Hold)는 낭비이고, 해법은 고정구다(Barnes) |
| 물류 현장 | Dexterity는 두 팔로 처리량을 얻어 정밀한 놓기에 쓴다. Amazon Vulcan은 도구로 밀어 자리를 만들고 물건은 밀어 넣는다(성공률 약 80% → 99%). 두 번째 팔로 더미를 받친다고 공개한 업체는 없다 |
| 꽃게 | 큰 집게 둘은 평소 각자 먹이를 잡고, 단단한 먹이만 한쪽이 잡고 다른 쪽이 부순다. 집게 하나를 잃으면 걷는 다리가 대신한다 |

### OMX가 정하는 물리 한계

| 항목 | 값 | 근거 |
|---|---|---|
| 관절 | ID 11~13 XL430-W250(베이스·어깨·팔꿈치로 추정), ID 14~16 XL330-M288 | `docs/validation/omx-follower-registers-2026-10-15/result.md` |
| 힘 감지 | XL430은 전류 제어 모드와 전류 레지스터가 없다. Present Load는 내부 출력으로 추정한 값이며, 방향과 대략의 크기만 믿을 수 있다. XL330만 전류 기반 위치 제어(모드 5)와 Present Current를 지원한다. 힘 센서는 없다 | [XL430 e-Manual](https://emanual.robotis.com/docs/en/dxl/x/xl430-w250/), [XL330 e-Manual](https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/) |
| 순응성 | 손목 전류를 제한해도 손목 피치가 움직이는 방향으로만 물러난다. 베이스 회전 방향과 수직 방향은 XL430의 위치 오차만큼 힘이 생기고, 그 힘을 제한하는 장치는 없다 | 직렬 팔 기구학(추론) |
| 정확도 | 반복 정밀도 공개값이 없다. XL 계열 백래시와 보정 오차를 고려하면 실제 오차는 2~5 mm로 추정한다 | 추론 |
| 물체 | 예시 레시피는 40×30×30 mm, 20 g 폼 블록이다. 20 g 블록을 μ 0.5로 미는 힘은 약 0.1 N이다 | `operations/processes/cell/examples/omx_sim/recipe.yaml` |

추론: Present Load로 가벼운 밀기를 감지하기는 어렵다. 3~4개 블록을 미는 힘은 XL430 정지 토크의 2~5%이고, 자세에 따른 중력 부하 변화가 이보다 크다.

### 이번에 확인한 실행 계약

로컬 main 기준의 소스와 ADR을 읽은 결과다. 장치나 현장은 관측하지 않았다.

| 영역 | 관측 | 근거 |
|---|---|---|
| 실행 인스턴스 | OMX마다 native systemd 인스턴스 하나다. 두 팔을 한 프로세스나 그래프로 합치는 안은 기각됐다 | D-281 |
| 작업대 문서 | `cell.yaml`에는 팔레트마다 가르친 좌표계(`frames`)가 있다. 로봇 베이스는 하나다. Step 목표는 `robot_base` 자세다 | `cell.py:50`, D-401 |
| Cell Job | Job 하나에 `workcell_id`와 `instance_id`가 하나씩 붙는다. Job 상태와 `current_step_index`는 하나다. 실패·UNKNOWN 결과는 Job 전체를 HOLD하고, 그 Job의 claim을 모두 HELD/UNKNOWN으로 바꾼다 | `cell_job_store.py:30-37, 91, 100-102, 405, 480` |
| Step 원장 | Step 행의 키는 `(mission_id, step_index)`이고 Action은 하나다 | `work/step_ledger_schema.py:31, 39` |
| claim | 종류는 robot·workcell·object·pallet다. 여러 claim을 한 트랜잭션(savepoint)에서 모두 잡거나 하나도 잡지 않는다. 구역(zone) 종류는 없다 | `operations/fleet/fleet/server/dispatch_admission.py:9, 27-53` |
| grant | `action_kind`는 `CELL_TRANSFER`만 허용하고 추가 필드를 금지한다. TTL은 15 s다 | `schemas.py:353, 362`, `step_dispatcher.py:58` |
| Action 종류 | `CELL_TRANSFER`(approach·grasp·transfer·release)와 `TRIP`만 있다. phase 이름은 코드에 고정돼 있다 | `step_action_kinds.py:58-75`, `manipulation_plan.py:20`, `pose_plan.py:190` |
| 이동 | 수평 이동은 늘 수직 상승 → `carry_z`에서 이동 → 수직 하강이다. 충돌 장면은 없다 | D-402 §6 |
| owner | 작업대마다 owner 프로세스 하나다. peer는 Fleet 서비스 UID 하나만 허용하고, 정지 출처는 `FLEET`으로 기록한다. 한 명령이 진행 중이면 `busy`다 | D-336 §2, D-403 §8, `omx_cell_owner.py:191-199`, `command_owner.py:487` |
| 관절 상태 | owner가 읽는 스냅샷에는 위치만 있다. hardware description은 Torque Enable과 Hardware Error Status 외의 레지스터 인터페이스를 지운다 | `command_owner.py:150-154`, `deploy/robot/omx/preserved_description.py:61-75` |
| 정지 | 진행 중 목표는 `poll()` → HOLD → 취소로 멈출 수 있다. HOLD는 걸리면 풀리지 않고, 운영자 확인 `recover`가 필요하다 | `command_owner.py:583-612`, D-386 |
| phase gate | 동기 호출이고, False면 기다리지 않고 예외를 낸다. cell owner는 늘 True를 돌려준다 | `pick_place_runner.py:269, 291`, `omx_cell_owner.py:182` |
| 레시피 | `box`가 하나뿐이고, 순서는 "로봇 베이스에서 먼 것부터"다 | `recipe.py:18-19`, `sequence.py:21-23` |

정리하면, 양팔과 도구 사용을 막는 것은 D-281이 아니다. 막는 것은 네 가지다. Job·Step·claim이 팔 하나를 전제하는 원장 모델, `CELL_TRANSFER` 하나뿐인 Action 종류와 `carry_z` 이동 규칙, 위치만 읽는 관절 상태, 그리고 기다릴 수 없는 phase gate다.

## Decision

팔 실행 인스턴스는 지금처럼 팔마다 따로 둔다. 그 위에 **작업대 배치**, **팔별 원장**, **Fleet의 짝 grant**, **작업대 조율자**, **Step 역할**을 더한다. 한 팔 작업대는 이 구조에서 팔이 하나인 경우다.

### 1. 작업대는 팔 하나 또는 둘과 공통 좌표계를 가진다 (D-401 부분 대체)

```yaml
cell_frame: cell
arms:
  - role: left
    instance_id: omx_01_control
    base_in_cell: {calibration_revision: ..., T: [...]}
  - role: right
    instance_id: omx_02_control
    base_in_cell: {calibration_revision: ..., T: [...]}
zones:
  - {zone_id: left_half, polygon: [...]}
  - {zone_id: right_half, polygon: [...]}
  - {zone_id: shared_band, polygon: [...]}
fixtures:
  - {fixture_id: backstop_L, pose: ..., kind: wall}
```

- `left`/`right`는 팔의 물리 위치만 뜻한다. 팔이 할 일은 §6의 Step 역할이 정한다.
- Step 목표는 `cell` 좌표계로 쓴다. 팔로 보낼 때 그 팔의 `base_in_cell`로 바꾼다. 팔이 하나이고 변환이 단위 행렬이면 지금의 `robot_base`와 같다. 기존 팔레트 `frames`는 `cell` 좌표계 안의 좌표계로 남는다.
- `base_in_cell`의 보정 revision이 없거나 만료된 팔은 Step에 배정하지 않는다.
- 양팔 작업대의 두 팔은 같은 호스트에 있어야 한다(D-336 같은 호스트 socket, 공통 시계).

### 2. 작업대 배치를 먼저 정한다

두 팔이 동시에 일하려면 공간이 먼저다. 0.10×0.08 m 팔레트에서는 두 손목과 아래팔이 겹친다. 그러면 팔레트 전체를 잠그는 것과 같다.

- 양팔 작업대의 팔레트는 0.20×0.15 m 이상으로 한다. 두 팔은 마주 보게 두고, 베이스 사이는 약 0.30~0.35 m로 한다. 그러면 팔레트 중심이 각 베이스에서 약 0.15~0.18 m에 온다. 이 값은 추정이며 G1에서 도달성과 함께 확인한다.
- 팔레트는 고정 구역(`left_half`, `right_half`)과 공유 띠(`shared_band`)로 나눈다. 두 팔의 동시 작업은 서로 겹치지 않는 구역에서만 한다. 공유 띠는 예약한 한 팔만 들어간다.
- 팔레트 한 모서리에 L자 뒷판을 고정하고, 모따기한 안내판을 둔다. 버티기와 정렬은 먼저 이 고정구에 맡긴다.
- 한 팔 작업대도 같은 뒷판과 안내판을 쓴다.

### 3. Job은 팔별 진행 상태와 claim을 가진다 (D-403 §4·§5·§8과 1b 보강의 부분 대체)

- Job은 작업대 하나를 가리키고, 그 아래 팔마다 진행 상태(`READY`, `RUNNING`, `HOLD`, `OFFLINE`)를 둔다. 한 팔의 실패나 UNKNOWN은 그 팔과 그 팔이 잡은 claim만 HOLD한다. Job 전체를 HOLD하는 것은 아래 두 경우다.
    - 단단한 결합 Step(§6)에서 한 팔이 실패한 경우
    - 짝 팔이 남은 Step을 혼자 할 수 없는 경우
- claim 종류에 `arm`(팔 하나)과 `zone`(작업대 구역 하나)을 더한다. Step은 쓰는 팔과 구역만 claim한다. 두 팔이 같은 구역을 동시에 claim할 수 없다.
- 협조 Step의 claim은 지금의 savepoint 트랜잭션으로 모두 잡거나 하나도 잡지 않는다.
- Step 원장은 Step 하나에 팔마다 Action을 하나씩 둘 수 있게 한다. 키는 `(mission_id, step_index, arm_role)`이 된다.
- 작업대마다 owner는 팔마다 하나다. D-403 §8의 "작업대마다 owner 하나"는 "팔마다 owner 하나"로 바뀐다.
- claim을 유지하고 해제하는 규칙(HELD·UNKNOWN 유지, 타임아웃으로 풀지 않음)은 D-403 1b 보강을 따른다. 단, 그 범위가 Job 전체가 아니라 팔과 구역이다.

### 4. grant는 Fleet이 팔마다 직접 보낸다 (D-336 §2 보강)

- Fleet은 협조 Step 하나에 팔마다 grant를 하나씩 만들어, 각 owner에게 지금의 Unix socket으로 직접 보낸다. 두 grant는 같은 `authority_epoch`·`dispatch_generation`·`pair_id`를 가지고, 서로의 `instance_id`를 짝으로 적는다.
- **짝 수락 규칙:** 두 owner가 모두 수락해야 짝이 시작된다. 한쪽이 `GRANT_REJECTED`나 `busy`를 돌려주면 Fleet은 수락한 쪽을 취소하고, 그 Step을 재시도 대기로 둔다. 한쪽만 실행되는 상태는 만들지 않는다.
- grant 발급자와 lease 발급자는 계속 Fleet 하나다(D-773 §2). 조율자는 grant를 만들거나 전달하지 않는다.

### 5. 작업대 조율자는 기다림과 정지만 맡는다

작업대 조율자는 양팔 작업대마다 하나 있는 같은 호스트의 프로세스다. 두 owner의 클라이언트이며 관절에 쓰는 writer가 아니다. 소스는 `middleware/devices/omx/agent` 안에 두고, 실행은 native systemd 인스턴스 하나다.

조율자의 권한은 두 가지뿐이다.

- **barrier 해제:** 협조 Step은 역할 짝마다 이름 붙은 barrier 지점을 가진다. 예를 들면 `handover`의 `both_grasped`, `place`+`push`의 `placed_before_push`다. 각 owner는 그 지점에서 `PHASE_WAIT`로 멈추고, 조율자가 두 팔의 도착을 확인하면 `release_phase`로 풀어 준다. 조율자는 owner의 lock 안에서 기다리지 않는다(D-386). 이 상태와 연산은 D-376 §7의 UDS 연산 목록에 더하는 후속 ADR로 정한다(§9).
- **결합 정지:** 조율자는 owner에게 HOLD를 보낼 수 있다. owner는 이 요청을 새 정지 출처 `COORDINATOR`로 기록하고, 조율자의 peer UID를 Fleet과 별도로 허용한다. 조율자는 grant를 보내거나 `preempt`를 쓸 수 없다.

**결합 정지의 범위:**

- **하드웨어 E-stop:** 언제나 두 팔의 서보 전원을 함께 끊는다. 결합 방식과 상관없다(D-281 §3).
- **단단한 결합 구간**(`handover`, `co_carry`, 짝이 잡고 있는 동안의 `push`): 한 팔이 실패, UNKNOWN, 링크 상실 상태가 되면 조율자는 짝 팔에 즉시 HOLD를 보낸다.
- **독립·느슨한 결합 구간:** 멈춘 팔과 그 팔의 구역만 HOLD한다. 다른 팔은 자기 구역에서 계속 간다.
- 어느 경우든 자동으로 재시도하거나 재생하지 않는다.

**한 팔 모드:** 한 팔이 `HOLD`나 `OFFLINE`인 동안 작업대는 한 팔 모드로 내려간다. 계획기는 남은 팔과 고정구만으로 할 수 있는 Step만 낸다. 꽃게가 집게 하나를 잃어도 걷는 다리로 먹는 것과 같다.

### 6. 역할은 Step마다 정하고, 한 팔과 두 팔이 같은 역할 목록을 쓴다

| 역할 | 하는 일 | 한 팔 | 두 팔 | 결합 | 이 ADR에서 |
|---|---|---|---|---|---|
| `place` | 집어서 목표 자세에 놓는다. 핑거가 빈 쪽 면을 잡도록 손목 회전을 고르고, 벽이나 이웃에 붙여 내리면서 구석 쪽으로 살짝 미끄러뜨린다 | 씀 | 각자 다른 구역에서 동시에 | 독립 | 연다 |
| `push` | 고정 밀대 면으로 놓인 물체를 벽이나 줄 쪽으로 민다. 세 면이 막힌 틈에 넣을 때만 쓴다 | 씀 | 씀 | 독립. 짝이 잡고 있으면 단단한 결합 | 방향만 정한다. 실물은 G2.5 통과 뒤 |
| `consolidate` | 흩어진 빈틈을 모으도록 여러 물체를 민다 | 보류 | 보류 | 독립 | 열지 않는다. 물체 여러 개의 결과 자세를 계획과 증거로 표현할 수 없다 |
| `handover` | 공중에서 건네며 잡는 면을 바꾼다 | 받침대에 놓고 다시 잡기로 대신 | 씀 | 단단한 결합 | 방향만 정한다 |
| `brace` | 다음 물체가 놓일 때까지 손목·그리퍼로 짧게 받친다 | 없음 | 보류 | 단단한 결합 | 열지 않는다. 계획기의 "혼자 안정한 자리만" 규칙과 뒷판으로 대신한다. G2에서 실제 무너짐이 보이면 다시 연다 |
| `co_carry` | 길거나 큰 물체를 양 끝에서 함께 든다 | 없음 | L2에서만 | 단단한 결합 | 열지 않는다 |

**도구:**

- 밀기 도구는 손목이나 핑거에 고정한 평평한 밀대 면이다. 폭 40~60 mm, 높이 10~15 mm에 고무 면을 붙인다. 아래 모서리는 바닥에서 3 mm 띄우고 모따기한다.
- 닫은 그리퍼 끝은 점 접촉이라 물체를 돌린다. 그리퍼로 쥔 밀대는 잡은 자리가 미끄러진다. 둘 다 쓰지 않는다.
- 밀대는 1 N 아래에서 물러나는 스프링 또는 이탈식 장착으로 힘을 기계적으로 제한한다.
- 도구와 고정구는 `cell.yaml`의 `fixtures`에 이름과 자세로 적는다.

**밀기의 멈춤 감지:**

- Present Load(XL430) 하나로는 감지하지 않는다.
- 아래 세 가지 가운데 하나라도 걸리면 멈춘다.
    - XL330 손목의 Present Current
    - 관절마다 같은 궤적을 접촉 없이 기록한 기준과 비교한 추종 오차
    - Step에 적은 최대 밀기 거리
- 밀기 속도는 10 mm/s 이하, 한 번에 30 mm 이하로 한다.
- 멈춤은 운영자 확인이 필요한 HOLD가 아니라, 다시 관측한 뒤 계획기가 다음을 정하는 `FAILED` 결과로 끝낸다. 이 결과 종류와 관절 부하·전류 상태 인터페이스는 후속 ADR로 정한다(§9).

**계획기가 Step에 붙이는 것:**

- 역할과 그 역할을 맡을 팔(`arm: left|right`)
- 쓰는 구역(`zone`)과, 후보마다 닿을 수 있는 팔 목록
- 안정 여부. L1에서는 `standalone`(혼자 안정)만 허용한다
- 결합 방식(`independent`, `loose`, `tight`). 조율자의 결합 정지가 이 값을 쓴다
- `push`라면 밀 방향, 최대 거리, 멈춤 한계, 그리고 민 뒤 기대하는 물체 자세

`push` 다음에는 반드시 다시 관측한다. 기대한 자세와 허용 오차 안에서 맞지 않으면 다음 Step을 내지 않는다.

적재 계획기의 알고리즘(후보 생성, 지지 규칙, 점수)과 혼합 레시피 스키마는 이 ADR의 범위가 아니다.

### 7. 협응 수준은 세 단계로 열고, 이 ADR은 L1만 연다

| 수준 | 동작 | 대표 작업 | 이 ADR에서 |
|---|---|---|---|
| L1 phase 동기 | 팔마다 제한된 목표를 받고, 이름 붙은 barrier에서 맞춘다 | 두 팔 동시 적재(구역 분리), 벽에 붙여 놓기, 건네며 면 바꾸기 | 연다 |
| L2 시작 시각 동기 | grant의 phase에 공통 시작 시각을 담는다 | 길거나 큰 물체 함께 옮기기 | 자리만 둔다 |
| L3 양팔 스트리밍 정책 | 학습 정책이 두 팔에 짧은 주기로 함께 명령한다 | 정교한 양손 조작(목표 아님) | 열지 않는다. 필요해지면 별도 ADR(D-496 개정, D-449 바인딩, 독립 Safety 리뷰) |

### 8. 바꾸지 않는 것

- D-281: 팔마다 실행 인스턴스를 두고, 장치 소유를 고정한다. 프로세스를 나눈 것은 안전 경계가 아니다.
- D-282·D-773 §1: actuator마다 단일 writer를 두고, 두 writer를 합치지 않는다.
- D-496: 실물에서는 제한된 목표를 하나씩 보낸다.
- D-773 §2: grant와 lease의 발급자는 Fleet 하나다.
- 한 팔 작업대의 지금 Cell 문서, Job, grant는 팔이 하나인 경우로 그대로 읽힌다.

### 9. 후속 ADR로 정하는 선행 조건

이 ADR이 연 L1을 실제로 쓰려면 아래가 먼저 정해져야 한다. 이 ADR은 각 항목의 방향을 정하고(§1·§3·§4·§5·§6), 스키마·상태·연산의 구체적인 모양은 후속 ADR이 정한다. 후속 ADR은 표의 조항을 부분 대체한다.

| 선행 조건 | 바뀌는 조항 | 필요한 단계 |
|---|---|---|
| 팔별 Job 상태, `arm`·`zone` claim, Step 원장 키 변경 | D-403 §4·§5·§8, 1b 보강 | G1 |
| 혼합 레시피 스키마(`items`)와, 베이스 둘을 아는 놓는 순서 | D-401 §2·§4·§5 | G1 |
| 조율자 peer와 `COORDINATOR` 정지 출처 | D-336 §2 | G1 |
| `PHASE_WAIT` 상태와 `release_phase` UDS 연산 | D-376 §7, D-386 | G1 |
| `handover`용 Action 종류와 phase 집합. 한 Action이 pick+place 한 쌍이라는 규칙의 예외 | D-376 §2, D-327 §5 | G2 |
| `push`용 Action 종류(`CELL_PUSH`), 낮은 높이의 수평 이동, 접촉 이동 | D-402 §6, D-376 §2 | G2.5 |
| 관절 부하·전류 상태 인터페이스와, 운영자 확인 없는 `FAILED` 멈춤 결과 | D-386, `preserved_description.py` 패치 | G2.5 |

## Alternatives

- **두 팔을 ROS 그래프 하나와 MoveIt 하나로 합치기:** 팔 간 충돌 검사와 동기 계획은 공짜로 얻는다. 그러나 장치와 재시작·복구를 팔마다 검증할 수 없다(D-281이 기각한 이유). MoveIt 2 본선은 독립 동시 실행도 지원하지 않는다. 기각한다.
- **Fleet이 직접 동기화하기:** Fleet은 Step을 순차로 실행하고 UDS 왕복 한계가 0.25 s다. barrier와 결합 정지에는 느리고 멀다. 기각한다.
- **조율자가 grant를 대신 받아 전달하기:** owner가 grant의 출처를 Fleet으로 확인할 수 없게 된다(D-336 §2). 기각한다.
- **한 팔을 상시 받침 팔로 두기:** 사람도 그렇게 하지 않고, 적재에서 근거도 없다. 20 g 블록은 받칠 필요가 거의 없고, XL430은 힘을 제한하지 못한다. 기각한다.
- **역할을 팔에 고정하기:** 놓기 좋은 팔이 Step마다 다르다. 기각한다.
- **Present Load만으로 밀기 멈춤 감지:** 신호가 자세에 따른 기준 변화보다 작다. 기각한다.
- **닫은 그리퍼 끝이나 그리퍼로 쥔 밀대로 밀기:** 물체를 돌리거나 밀대가 미끄러진다. 기각한다.
- **팔레트를 기울여 중력으로 모으기:** 블록이 미끄러지려면 tan θ > μ여야 한다. 폼끼리(μ 약 0.5)는 약 27°가 필요하다. 저마찰 바닥 위 첫 층만 효과가 있다. 선택 실험으로만 둔다.
- **팔 하나로만 혼합 팔레타이징하기:** 할 수 있다. 한 팔 작업대는 이 구조의 특수한 경우로 남는다. 두 팔은 처리량, 건네며 면 바꾸기, 한 팔 장애 시의 지속을 더한다.

## Consequences

- `cell.yaml`에 `arms`, `zones`, `fixtures`가 생긴다. Job 저장소, Step 원장, claim 종류, grant 스키마가 팔과 구역 단위로 바뀐다(§9). 팔이 하나일 때의 기본값은 지금 동작과 같다.
- 작업대 조율자라는 새 프로세스가 생긴다. writer가 아니지만 HOLD와 barrier 해제 권한이 있다.
- 단단한 결합 구간에서는 "한 팔이 재시작해도 다른 팔은 계속 간다"는 지금의 검증 기준이 뒤집힌다. 그 밖의 구간과 한 팔 작업대의 검증은 그대로 둔다.
- 손목이나 핑거에 고정 밀대 면을 달아야 한다. 그리퍼 형상이 바뀐다.
- 하드코딩된 루트 토픽(`/joint_states`, `/arm_controller/follow_joint_trajectory`)은 인스턴스 namespace로 받게 바꾼다. 이 일은 양팔 작업보다 먼저 한다.

## Transition / Validation

1. **G0 문서:** `cell.yaml`의 `arms`·`zones`·`fixtures` 스키마와 `cell` 좌표계를 정한다. 지금의 한 팔 Cell 문서가 바뀌지 않고 읽힌다.
2. **G1 SIM 권한과 배치:**
    - 마주 본 두 팔과 0.20×0.15 m 팔레트에서, 두 팔이 모든 구역에 닿는지와 동시 작업 시 휩쓰는 공간이 겹치지 않는지 확인한다.
    - 협조 Step의 claim을 한쪽만 잡는 데 실패하면 아무것도 남지 않는지 확인한다.
    - 짝 grant 한쪽이 거부되면 다른 쪽이 취소되는지 확인한다.
    - 느슨한 구간에서 한 팔에 장애를 주입하면 그 팔과 구역만 HOLD되고 다른 팔이 한 팔 모드로 이어 가는지 확인한다. 단단한 구간에서는 두 팔이 함께 HOLD되는지 확인한다.
3. **G2 SIM 작업:**
    - 한 팔과 두 팔로 벽에 붙여 놓는 혼합 적재를 끝까지 실행한다.
    - 계획기의 "혼자 안정한 자리만" 규칙으로 무너짐이 남는지 잰다. 남으면 `brace`를 다시 검토한다.
    - 밀기 연구는 MuJoCo(비틀림 마찰 condim 4, 타원 마찰 원뿔, μ 0.3~0.8 무작위화)로 한다. Gazebo의 밀기 결과는 실물로 옮겨지지 않는다고 보고, 시뮬에서 멈춤 감지를 "검증됨"으로 부르지 않는다.
4. **G2.5 실물 한 팔 밀기 벤치:**
    - 고정 밀대로 약 50회 밀어 최종 자세와 회전 분포, 멈춤 오검출·미검출 비율을 잰다.
    - 기준을 넘어야 `push`를 실물에서 연다.
5. **G3 DEVICE:**
    - 단일 OMX DEVICE 수용(D-496)과 2개 동시 DEVICE(D-281)를 거친다.
    - 그 뒤 양팔 작업대에서 공유 E-stop을 확인하고 L1을 실물로 실행한다.
6. **L2·L3:** 각각 별도로 수용한다. L3는 별도 ADR이 필요하다.

열린 질문:

- `base_in_cell` 보정 절차와 허용 오차
- 팔 배치와 팔레트 크기의 실제 값(G1에서 확인)
- 밀대 장착 위치와 핑거 개구와의 간섭
- 학습 정책을 양팔 작업대에 붙일 때의 바인딩 모양(작업대와 팔 역할 순서를 가리킬지). D-449의 단일 owner 바인딩과 함께 정한다

**References:** [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-327](D-327-semantic-manipulation-actions-and-device-adapters.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-401](D-401-rosy-cell-application.md), [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md), [D-435](D-435-work-orchestration-fleet-and-device-authority.md), [D-449](D-449-learning-artifact-and-owner-binding-contracts.md), [D-474](D-474-caution-point-zone-grant.md), [D-496](D-496-omx-hardware-arm-control-acceptance.md), [D-770](D-770-fleet-omx-autonomous-imitation-pipeline.md), [D-773](D-773-omx-ai-extension-platform-structure.md), [듀얼 로봇팔 운용 조사](../assessments/2026-10-17-dual-arm-operation-research.md), [적재 계획·양팔 역할 조사](../assessments/2026-10-17-mixed-palletizing-stacking-plan-research.md).
