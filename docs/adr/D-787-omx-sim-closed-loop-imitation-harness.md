## D-787 OMX 시뮬레이션 모방학습 폐루프: 고정 목표 도달 과제, 시뮬레이션 전용 lease, 실물 차단

**Status:** Proposed

## Context

2026-10-17 사용자 지시: "파이프라인을 아예 완성". 같은 날 조사한 결과는 다음과 같다.

**이미 한 번씩 돌려 본 단계**

- 수집: Pilot sim 기록(2026-10-01, 10-04)
- 변환: `lerobot_export.py`
- 학습: `act_job.py`. 두 번 학습했고 두 번 모두 reject였다.

**없었던 것**

- 학습된 ACT 정책이 owner를 거쳐 Gazebo 팔을 반복 구동하는 실행기. `OwnerPolicySession`은 있지만 provider·issuer·scheduler가 없다.
- 사람 없이 많은 시연을 만드는 교사
- Gazebo ground truth 성공 판정. Pilot world에는 판정할 물체가 없다.

**기존 제약**

- D-770은 SIM 자료를 형식·연결 시험용으로만 인정한다.
- D-773 §2는 실물 학습 정책 lease를 Fleet이 발급한다고 정했다.
- `test_omx_policy_config.py`는 장치·배포 폴더가 `learned_policy`를 선언하지 못하게 한다.
- D-782는 Gazebo 파지 접촉이 실제와 달라, Gazebo 데이터로 먼저 학습하는 것을 파이프라인 시험 외에는 기각했다.

## Decision

### 1. 과제는 물체 없는 고정 목표 도달이다

`rosy.omx-sim-reach-task.v1`은 다음을 정한다.

- 고정 목표 관절 자세
- 관절별 허용오차. 그리퍼는 확인하지 않는다.
- seed가 있는 시작 자세 표본 범위
- 고정 jog 크기와 시간
- 최대 step

목표가 고정이므로 영상과 관절 상태만으로 학습 가능한 과제다. 성공은 Gazebo 관절 readback으로 판정한다(`judge: sim_joint_readback`). 파지·배치 과제는 카메라가 있는 물체 world를 만든 뒤 후속으로 다룬다.

### 2. 단계와 산출물

| 단계 | 구현 | 산출 |
|---|---|---|
| 교사 | `deploy/robot/omx/sim_reach_teacher.py` | Pilot HTTP로 시작 자세 복귀(기록 안 함), 기록, 목표 쪽 탐욕 jog, 자동 결과. 교사 결과는 기준선을 겸한다 |
| 변환 | `learning/curation/omx/sim_batch_export.py` | 완료·성공 episode만 `lerobot_export`. seed로 eval을 정하는 batch manifest |
| 학습 | 기존 `act_job.py` | 기존 출력과 offline 판정 |
| 설치 | `learning/evaluation/omx/sim_policy_install.py` | 원본을 두고 sim 전용 재봉인본·receipt를 쓴다. owner binding·카메라 identity·sim 시간 예산을 맞춘다 |
| 폐루프 | `learning/evaluation/omx/sim_closed_loop.py` | episode마다 `OwnerPolicySession` 하나. capture→추론→후보→submit→종단 대기 순서다. 활성 중에는 submit하지 않는다 |
| 판정 | `learning/evaluation/omx/sim_reach_eval.py` | 성공률, 교사 기준선 비교 |

### 3. 시뮬레이션 전용 lease와 reset은 실물에서 열리지 않는다

폐루프 실행기의 policy lease는 로컬 발급이다. owner identity가 `simulation: true`가 아니면 시작하지 않는다.

episode 시작 자세 복귀(SIM RESET)는 owner 세션 밖의 짧은 trajectory client다. 이 client도 simulation identity에서만 동작한다.

실물 학습 정책은 D-773 §2의 Fleet lease와 D-770 G4 뒤에만 연다. 이 ADR은 그것을 대신하지 않는다.

`learned_policy`는 `learning/evaluation/omx/`에만 둔다. 장치·배포 폴더 guard는 그대로다.

### 4. 실행 호스트

실행은 모델 PC native Gazebo에서 한다. 노트북과 현장 PC에서는 시뮬레이션을 돌리지 않는다(D-571, D-584). 실행 규칙은 다음과 같다.

- 작업 폴더는 `~/rosy-test/` 아래에 따로 둔다.
- `~/rosy-jobs` 잠금을 잡는다.
- 고유 `GZ_PARTITION`을 쓰고 localhost discovery만 허용한다.
- CPU를 제한한다.

### 5. 결과의 의미

sim 성공률은 파이프라인 연결과 정책 형식의 증거일 뿐이다. 실물 과제 성공, 학습 데이터 완료(D-770), 장치 수용이 아니다. `source_mode`는 `simulation`으로 기록하고, native 자료와 섞지 않는다.

## Alternatives

- **CELL_TRANSFER 실행을 시연으로 쓰기**: cell world에 카메라가 없고 phase가 v1 goal 시간 한도를 넘어서 기각했다.
- **Fleet lease를 sim에도 요구하기**: 연결 시험에 G2 격리 실행이 먼저 필요해서 기각했다. sim lease는 simulation identity 검사로 대신한다.

## Consequences

SOURCE와 host 시험, 모델 PC ROS-SIM 실행 증거는 `docs/validation/`에 따로 남긴다. 실물 경로는 바뀌지 않는다.

## References

D-403, D-570, D-571, D-584, D-770, D-773 §2, D-782, D-785.
