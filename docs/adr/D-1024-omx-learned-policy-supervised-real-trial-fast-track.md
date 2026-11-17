## D-1024 OMX 학습 정책의 실물 입회 시험을 하루 안에 연다 — D-793 단계를 줄이되 장치 한계·정지·두 사람 확인은 그대로 둔다

**Status:** Accepted (2026-11-14, 사용자 지시). D-793을 보완한다. 구현·원격 시험·실물 수용은 별도이고, 이 결정 시점에 학습 정책의 실물 실행은 0회다.

## Context

2026-11-14 02:40 사용자 지시는 이렇다. 시뮬레이션에서 학습하고, 3층 적재 등을 빨리 하기 위한 최적의 모델을 만든다. 시뮬레이션에서 루프로 반복하고, 현실에서 빠르게 수정한다. 기한은 내일(11-15) 오전이다.

같은 날 사용자는 두 경로 중 하나를 골랐다. 하나는 시뮬에서 최적화한 운반 값으로 기존 IK 운반을 실물에 쓰는 경로다(D-793 안에서 가능). 다른 하나는 학습 정책을 실물에서 실행하는 경로다. 사용자는 앞의 것을 주 경로로 골랐다. 이어서 "adr에는 2번째 실물 적용도 바로 내일 처리하도록"이라고 지시했다.

D-793은 학습 정책이 실물을 움직이기 전에 L1 오프라인 → L2 shadow → L3 입회 → G4 제한 사용 단계를 요구한다. 또 그 전에 확인 요청 API, 승인 창, 실행 lease 발급기, shadow 실행기(5절 D)를 구현하라고 한다. 2026-11-14 현재 상태는 다음과 같다.

| 항목 | 현재 |
|---|---|
| 시뮬 학습 정책 | ACT·SmolVLA 라운드가 90%에 못 미쳤다(2026-11-09 sub-skill 라운드). 등록된 적층 checkpoint가 없다 |
| 실물 데이터 | arm_b 감독 시도 70회 중 놓기 2회 |
| 실행 경로 | `OwnerPolicySession`(lease·fence·HOLD)은 있다. 승인 API, lease 발급기, shadow 실행기, AI PC 정책 실행기(D-854)는 없다 |
| 실물 owner | `allowed_owners=("rule_based",)`(D-785), 추적 설정의 `learned_policy` 금지(D-442) |

D-793의 단계를 그대로 밟으면 일정이 며칠 걸린다. 그래서 일정만 줄인다. 파손을 막는 장치 쪽 한계와 사람 확인은 줄이지 않는다.

## Decision

### 1. 하루 안에 L3 입회 시험까지 열 수 있다

| D-793 단계 | 이 결정의 조건 (11-15 한정 아님, 이후에도 같은 조건) |
|---|---|
| L1 오프라인 통과 | 실물 held-out이 부족하면 **시뮬 평가로 대신한다.** 조건 세 가지: 같은 과제(`stack-t1..t3`)를 셀 보정값(`cell_physics.yaml`에서 승격된 sysid 후보)과 도메인 무작위화로 평가한다. 정책 성공률이 같은 조건의 scripted teacher 이상이어야 한다. 기록은 checkpoint sha256과 함께 registry L1 근거로 남긴다 |
| L2 shadow | 실물 teacher(`rule_based`) 운반 중 같은 관측으로 추론하고 명령은 보내지 않는다. **층마다 teacher 운반 1회 이상**을 shadow한다. 위험 출력(변화량 상한 초과, 범위 밖, 비유한값)이 한 번이라도 나오면 그 층의 L3를 열지 않는다 |
| L3 입회 시험 | D-793 2절 승인 창(기본 15분, 상한 30분)과 실행 lease(1초, 상한 2초)를 그대로 쓴다. 제안자와 승인자는 다른 사람이어야 한다. D-911 감독자가 전원 스위치 옆에 있어야 한다 |
| G4 제한 사용 | 바꾸지 않는다. teacher·learner 각 10회 이상 독립 평가가 있어야 한다 |

### 2. 시험 범위를 좁힌다

- 대상: arm_b 한 대, 과제 `stack-t1` → `stack-t2` → `stack-t3` 순서. 1층이 성공해야 2층, 2층이 성공해야 3층을 연다.
- 속도와 관절 범위: 같은 과제의 scripted 운반에서 실측한 값보다 크지 않게 한다. 손목 `wrist_flex`는 출력 손목 받침의 실측 한계(현재 약 45–58)를 지킨다.
- 하중: D-935의 선언 무게 상한 안에서만 시험한다.
- 실패하면 HOLD하고, 원인을 기록하고, 사람이 확인한다. 자동 재시도는 없다(D-793 3절). 실패와 중단도 `attempts.jsonl` 분모에 남긴다(D-911 7).

### 3. 줄이지 않는 것

- owner가 유일한 관절 writer다. 관절 범위·속도·가속도·step 변화량·그리퍼 전류 상한은 장치와 owner에서 강제한다(D-793 4절).
- 위험 출력은 거부하고 HOLD한다. HOLD는 API로만 푼다(D-793 3절).
- 추적 설정의 `learned_policy` 금지(D-442)는 유지한다. 실행 허용은 승인 창과 lease로만 연다.
- 시뮬 결과는 실물 근거가 아니다(D-911 4). 시뮬 평가는 L1을 대신할 뿐, L2·L3를 대신하지 않는다.
- D-430 safety 경로이므로 구현 커밋에는 `Safety-Review:` trailer와 독립 검토가 필요하다.

### 4. 11-15 오전까지 필요한 구현 (D-793 5절 D를 최소로)

2026-11-15 현재 이 브랜치의 상태다. 이 절의 표는 상태 갱신이며 결정을 바꾸지 않는다.

| 순서 | 내용 | 있는 것 | L3를 아직 막는 것 |
|---|---|---|---|
| 1 | AI PC 정책 실행기(D-854) 최소판: ACT adapter 하나, CORE arm-policy HTTP target, `max_chunk=1` | `integrations/robots/omx/src/rosy/integrations/robots/omx/policy_run.py`(시험 `test/test_omx_policy_run.py`) | 실행기가 내는 값은 lerobot 정규화 단위이고 rad로 바꾸는 변환이 없다 |
| 2 | shadow 모드: 같은 실행기가 명령을 보내지 않고 출력과 teacher 행동 차이만 기록한다 | `policy_run.py`의 shadow 경로. L2 shadow는 완료했다 | 실물 owner가 `learned_policy`를 받지 않는다: `deploy/robot/omx/run_hardware_owner.py:82`가 `allowed_owners=("rule_based",)`를 강제한다(시뮬 owner 전용). 실물 owner 프로필이 없다 |
| 3 | 승인 창과 실행 lease 발급: Fleet에서 제안자·승인자 이름을 받고, 창 안에서만 1초 lease를 갱신한다 | 승인 창 `operations/fleet/fleet/server/auth/policy_approval.py`·`policy_approval_routes.py`, 전달 `policy_delivery.py`, 로컬 push `middleware/robot_execution/local/src/rosy/execution/local/policy_lease_push.py`. lease 전달은 D-430 독립 검토 4라운드를 거쳤다 | 수신기가 운영에 연결되어 있지 않다. 위 owner 제한과 실물 owner 프로필이 없어 lease를 받아도 실행할 owner가 없다 |
| 4 | 시뮬 L1 평가 기록: 과제·보정 후보·무작위화 범위·성공률·checkpoint sha256 | 이 항목은 이 상태 갱신에서 확인하지 않았다 | 등록된 적층 checkpoint가 없다(위 현재 상태 표) |

L3를 막는 것은 요약하면 셋이다. owner가 시뮬 전용이다(`allowed_owners=("rule_based",)`). lerobot_norm→rad 변환이 없다. 실물 owner 프로필이 없다. 이 셋과 수신기 연결이 끝나기 전에는 실물 시험을 하지 않으며, 구현·실물 수용·Safety review는 여전히 별도다.

이 중 하나라도 착지하지 않으면 학습 정책의 실물 시험은 하지 않는다. 그때는 D-793 안의 주 경로(시뮬 최적화 운반 값을 `cell_choices` 후보로 실물에 쓰는 방식)만 진행한다.

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-793 | L1 근거에 시뮬 평가를 더하고, L2 최소 횟수를 정한다. 승인 창·lease·HOLD·두 사람 확인·G4는 그대로다 |
| D-854 | 정책 실행기의 첫 최소판을 이 일정으로 당긴다. 구조는 바꾸지 않는다 |
| D-911 | 감독자 입회, 실패 분모, 시뮬은 실물 근거 아님을 그대로 따른다 |
| D-442, D-785 | 추적 설정 금지와 rule_based 기본값을 유지한다 |
| D-935 | 하중 상한 안에서만 시험한다 |
| D-932 | 현장 실행은 착지된 한 revision에서만 한다 |

## Alternatives

| 접근 | 판단 |
|---|---|
| D-793 단계를 그대로 밟는다 | 일정이 며칠 걸려 사용자 기한(11-15 오전)에 맞지 않는다 |
| 승인·lease 없이 학습 정책을 실물에 바로 연결한다 | 기각. 네트워크·Fleet 정지가 장치 정지로 이어지지 않고, 사용자 2026-10-18 지시(위험하면 멈추고 확인)와 반대다 |
| 시뮬 평가만으로 L3를 연다 | 기각. 시뮬-실물 차이(TCP, FK 약 8 mm, 미끄러짐)가 아직 측정 중이다. 실물 shadow가 마지막 확인이다 |

## Consequences

학습 정책은 같은 날 L3 입회 시험까지 갈 수 있다. 다만 실행기·shadow·승인 창·lease가 착지되어야 하고, 층마다 실물 shadow와 두 사람 확인이 필요하다. 구현이 늦으면 학습 정책 시험은 미루고, 시뮬 최적화 운반 값 경로만 진행한다. 이 ADR은 구현·실물 수용·Safety review를 뜻하지 않는다.

## References

- [D-793 학습 정책 실물 실행 승인 관문](D-793-omx-learned-policy-execution-approval-gate.md)
- [D-854 정책 실행기](D-854-omx-policy-runner-and-action-space.md)
- [D-911 검증된 작업 범위](D-911-omx-native-reviewed-operating-envelope.md)
