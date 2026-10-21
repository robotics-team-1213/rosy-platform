# 양팔 작업대 G1 SIM (프로세스 안) — 2026-10-17

[D-778](../../adr/D-778-bimanual-workcell-foundation.md) G1(권한과 배치), [D-779](../../adr/D-779-per-arm-cell-job-ledger-and-arm-zone-claims.md) 시험 1~6 가운데 3~5, [D-780](../../adr/D-780-workcell-coordinator-peer-stop-source-and-named-barriers.md) G1, [D-781](../../adr/D-781-mixed-item-recipe-and-two-base-placement-order.md) G1(한 팔·두 팔)을 ROS·Gazebo·실험실 PC 없이 할 수 있는 만큼 옮긴 기록이다. ADR 파일은 아직 `docs/bimanual-workcell-adr` 브랜치에만 있다.

```
ROS-SIM: HOLD      Gazebo·ROS goal·물리 접촉을 쓰지 않았다
DEVICE: PARKED     실물 OMX 두 대, 공유 E-stop, 실제 서비스 UID를 쓰지 않았다
IN-PROCESS ONLY    Fleet·두 owner·조율자가 한 Python 프로세스 안에 있다
```

## 기준과 명령

- 소스: `feat/bimanual-g1-sim` 브랜치, 기준 `c733c6628`(feat/mixed-cell-compile + feat/multi-arm-goal-evidence 병합) 위의 이 기록을 담은 커밋 하나.
- 이 노트북에서 실행한 것(pytest 아님, 순수 계산): `python test/g1_layout.py` → [evidence/layout-report.json](evidence/layout-report.json). 2026-10-17, Windows, Python 3.12.10, 약 64 s.
- pytest: **실행하지 못함 — 실험실 시험 PC 모두 닿지 않음**(이 커밋 뒤 `tools/remote/remote_pytest.py`를 한 번 시도). 아래 시험의 통과·실패, 프로세스 안 RTT·barrier 대기·조율자 정지 지연의 측정값은 아직 없다. 다시 돌릴 명령:

```bash
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/g1-sim -- ROSY_G1_EVIDENCE_DIR=/tmp/g1-evidence \
  test/test_platform_g1_layout.py test/test_platform_g1_sim.py test/test_platform_g1_timing.py
python test/known_failures.py X:/DevTemp/g1-sim/run-1.txt
```

`ROSY_G1_EVIDENCE_DIR`를 주면 시험이 `e2e-*.json`, `timing-*.json`을 남긴다. 그 값은 새 날짜의 기록으로 옮긴다(이 기록은 고치지 않는다).

## 무엇을 만들었나

| 파일 | 역할 |
|---|---|
| `integrations/robots/omx/src/rosy/integrations/robots/omx/mixed_reach.py` | `mixed_cell.Reach` 모양의 D-402 IK reach(`IkReach`, `ik_reach_from_profile`). 팔 base 좌표로 옮겨 top-down IK를 푼다. 팔레타이징은 어댑터를 import하지 않는다(D-413) |
| `test/g1_layout.py` | 도달성 감사, owner 계획기 궤적, capsule 휩쓸림 간격, 일정 모델, 적재 규칙 재검사. `python test/g1_layout.py`가 위 JSON을 낸다 |
| `test/g1_sim_harness.py` | Fleet `CellJobDispatcher` → 실제 `build_cell_owner` 두 개 + `WorkcellCoordinator`. 무엇을 대체했는지 파일 머리에 적었다(아래 표) |
| `test/test_platform_g1_layout.py` | 배치·도달성·간격·일정·적재 시험 |
| `test/test_platform_g1_sim.py` | 끝까지 실행과 D-778/D-779 장애 주입 |
| `test/test_platform_g1_timing.py` | barrier 대기·조율자 연락 간격·RTT, 조율자 죽음·짝 실패 정지, Linux 실제 UDS RTT |
| `test/fixtures/g1_sim/cell_g1.yaml` | G1 작업대: 컴파일 fixture와 같고 home x만 0.12 → 0.08 m |
| `test/fixtures/g1_sim/recipe_4sku.yaml` | 물체 4종 14개(D-781 G1의 3~4종) |

### 프로세스 안 연결에서 대체한 것

| 실제 | 대체 |
|---|---|
| Fleet multi-arm dispatcher, 원장, claim, pair 규칙, 한 팔 모드, goal evidence 판정 | — (실제 코드) |
| 두 owner의 ActionApi·ActionRunner·정지 latch·D-402 계획기·phase runner·barrier supervisor·조율자 peer API, `WorkcellCoordinator` | — (실제 코드) |
| UDS | `UnixLocalActionTransport._exchange`를 `ActionApi.dispatch` 직접 호출로 바꿨다(JSON 왕복). SO_PEERCRED는 확인하지 않고 UID를 넘긴다. 실제 소켓은 Linux 전용 RTT 시험 하나만 쓴다 |
| ROS goal | `SimGoalPort`: 모든 goal을 받고 `duration_s × time_scale` 뒤 끝내며 관절 상태를 마지막 점으로 둔다. 그리퍼 readback은 표시된 sim 규칙 |
| owner의 recipe/3·cell/3 수락 | owner의 실제 검증기는 recipe/1만 안다. `MixedDocumentValidator`로 바꿨다. 선로의 물체는 `box` 하나라 모든 sku를 첫 sku의 잡기 치수로 계획한다(mixed_submission의 후속 과제) |
| goal 증거 생산자 | 그 팔의 transfer goal 마지막 관절의 FK + sku 중심 높이. 판정은 Fleet 실제 코드 |
| step의 goal predicate | mixed resolver는 아직 붙이지 않는다. 시험이 첫 주 팔 좌표로 sku별로 붙인다 |

## 관측값 (노트북, 순수 계산)

### 배치 (D-778 §2)

G1 작업대: base 0.33 m, 마주 봄, 0.20×0.15 m 팔레트 중심 (0.165, 0), 각 base에서 0.165 m.

### 도달성 (D-402 IK, sim 프로파일 한계)

| 경우 | 확인한 자세 | 실패 |
|---|---|---|
| 2종 12개, fixture 작업대 (주 팔+대체 팔 × pick/접근/carry, place/접근/carry, home) | 105 | 0 |
| 2종 12개, G1 작업대 | 105 | 0 |
| 4종 14개, G1 작업대 | 140 | 0 |
| 한 팔 작업대(left base, 같은 팔레트), 2종 / 4종 | 84 / 98 | 0 / 0 |
| base 0.30·0.33·0.35 m × home 0.08·0.12 m × 2종·4종 | 12 경우 | 모두 0 |

두 팔 fixture 계획(annulus로 만든 것)은 IK로 전부 닿는다. **발견:** 계획기에 `IkReach`를 넣으면 첫 입력 점검 "no arm reaches any pick station"에서 거절된다. 그 점검이 TCP를 station 표면 z 0에 두고 묻는데, 프로파일 작업공간 바닥이 z 0.005 m다. 실제 pick 자세(z = 표면 + 높이 − 잡는 깊이)는 모두 닿는다. 계획기 수정은 이 기록에 넣지 않았다(시험은 이 거절만 허용한다).

### 동시 작업의 휩쓸림 간격 (capsule, 보수적)

팔을 owner 계획기 궤적의 모든 표본에서 shoulder→elbow→wrist→fingertip capsule(링크 반경 25 mm, wrist·그리퍼 30 mm, 표본 솎음 +5 mm)과 잡은 물체 capsule로 본다. 서로 기다리지 않고 구역이 다른 두 Step(그리고 한 Step과 home에 선 다른 팔)을 시간 무시하고 모든 표본끼리 비교한다.

| 작업대 | 동시 쌍 | 최소 간격 | 가장 가까운 쌍 |
|---|---|---|---|
| fixture(home x 0.12), 2종 | 30 | **−31.8 mm(겹침)** | left_half Step ↔ shared_band Step 4. home에 선 왼팔 손목이 오른팔의 공유 띠 작업 안에 있다 |
| G1(home x 0.08), 2종 | 30 | +2.5 mm | step 0 ↔ step 4 |
| G1(home x 0.08), 4종 | 39 | +2.2 mm | step 0 ↔ step 4 |
| base 0.30 m, home 0.08 | — | −8.8 / −10.8 mm | left_half ↔ shared_band |
| base 0.35 m, home 0.08 | — | +3.3 / +3.6 mm | left_half ↔ shared_band |
| base 0.30·0.33·0.35, home 0.12 | — | −44 ~ −23 mm | left_half ↔ shared_band |

결론: 이 모델로는 **base 0.33~0.35 m, home x 0.08 m**에서만 동시 작업이 분리된다. 0.30 m와 pilot home 0.12 m는 겹친다. 여유는 2~4 mm로 작다. capsule은 mesh가 아닌 외곽 근사이며 시간 겹침을 무시하므로 보수적이다. 반대로 실제 그리퍼 치수·보정 오차는 반영하지 않았다.

### 적재와 시간 (D-781 G1)

| 레시피 | 두 팔 makespan(모델) | 같은 Step 직렬 합 | 한 팔 작업대 직렬 | 한 팔 대비 | 부피 적재율 | 바닥 덮음(두 팔/한 팔) | 정적 규칙 위반 |
|---|---|---|---|---|---|---|---|
| 2종 12개 | 304.1 s | 460.9 s | 476.7 s | ×1.57 | 0.160 | 0.36 / 0.40 | 0 |
| 4종 14개 | 317.8 s | 552.4 s | 546.6 s | ×1.72 | 0.139 | 0.347 / 0.407 | 0 |

- 시간은 owner 계획기의 trapezoid 시간(Step당 35~42 s)에 Fleet 준비 규칙(의존 Step 완료, 팔·구역 비어 있음, 공유 띠 한 Step씩)을 적용한 일정 모델이다. goal 확인 시간은 0으로 두었다. Gazebo나 실물 시간이 아니다.
- 적재율 기준선은 팔레트 면적 × `max_stack_height` 0.07 m 대비 부피다. "무너짐 0"은 계획기의 정적 규칙(support_ratio_v1, 하중)을 최종 적재에 다시 적용해 위반 0이라는 뜻이다. 물리 시뮬레이션의 무너짐은 측정하지 않았다(ROS-SIM: HOLD). py3dbp 비교(D-781 4)는 하지 않았다.

### barrier 도착 차이(계획 시간)

두 팔용으로 컴파일된 공유 띠 Step(2종 3개, 4종 6개)을 두 팔이 각자 계획했을 때: grasp 뒤 도착 차이 최대 0.099 s, transfer 뒤 최대 0.914 s. Fleet의 두 grant 송신 차이와 owner 계획 시간(이 노트북에서 계획 1건 16~22 ms)은 따로 더해진다.

## 제안하는 시작 값 (D-780 §3·§4)

| 값 | 제안 | 근거 |
|---|---|---|
| `coordinator_liveness_s` | **1.0 s** (지금 기본 2.0 s, 하한 0.5 s) | UDS 한계 0.25 s의 4배. 건강한 owner의 연락 간격 최악 = 조율 주기 0.1 s + 아픈 쪽 GetBarrier 시간 초과 0.25 s + 해제 두 번 0.5 s ≈ 0.85 s < 1.0 s. 조율자가 죽으면 owner는 `liveness + owner tick` 안에 HOLD한다(시험 범위: 0.85~1.25 s) |
| 조율자 주기 | 0.1 s | liveness의 1/10. 짝 실패에서 짝 정지까지 ≤ 주기 + 0.25 s |
| `max_wait_s`, 첫 phase 전(`both_ready`) | **10 s** | 움직이기 전이라 시간 초과는 FAILED(HOLD 아님). Fleet 송신 차이 + owner 계획(수십 ms) 대비 크게 |
| `max_wait_s`, grasp 뒤(`both_grasped`) | **45 s** | 짝의 approach 상한 40 s + grasp 4 s + 1 s(`phase_max_duration_s`). 그보다 늦게 오는 짝은 phase 상한을 넘긴 것이다. 계획 도착 차이 최대 0.1 s |
| `max_wait_s`, transfer 뒤(`placed_before_push`) | **85 s** | 40 + 4 + 40 + 1 s. 계획 도착 차이 최대 0.91 s |

일반 규칙: 컴파일러는 barrier까지 짝 팔 phase 상한의 합 + 1 s를 쓴다. 이 값은 프로세스 안 측정(`test_platform_g1_timing.py`)으로 확인할 예정이었고 그 측정은 아직 없다. 실제 서비스 UID·systemd·SQLite FULL 동기화 디스크에서 UDS RTT를 다시 재야 한다([cell-fleet-uds-2026-10-03](../cell-fleet-uds-2026-10-03/README.md)에 SQLite 처리 중 0.5 s 제한 초과 사례가 있다).

## 시험이 확인하도록 만든 것 (실행 전)

- `test_platform_g1_sim.py`: 2종·4종 Job이 Fleet 컴파일 → 두 owner → goal 증거로 모든 Step GOAL_CONFIRMED; 다른 구역 Step의 시간 겹침이 있음; 공유 띠 Step 구간이 겹치지 않고 표본마다 공유 띠에 움직이는 팔이 하나 이하; makespan과 직렬 합은 기록만 한다(goal이 수 ms라 부하가 큰 호스트에서는 Step 사이 dispatch 시간이 겹침 이득보다 클 수 있다). 장애: 짝 Step의 claim 한쪽 실패 → CLAIM_BUSY, arm/zone claim 0개, Action 0개(D-778 G1, D-779 4); 짝 grant 한쪽 거부 → 받은 쪽에 `PAIR_PARTNER_NOT_ACCEPTED` 취소, 그 팔 approach goal 취소(D-778 §4); 독립 Step 실패 → 그 팔·구역만 HELD/UNKNOWN, 다른 팔의 독립 Step 전부 확인(D-779 3); tight 짝 실패 → 두 팔 HOLD(`TIGHT_PARTNER_HELD`), 새 Step 없음; 오른팔 OFFLINE → 공유 띠 Step을 왼팔이 자기 base로 계획해 성공, `CELL_STEP_ALTERNATE_ARM` 기록, 그 팔 좌표의 predicate로 GOAL_CONFIRMED(D-779 5, D-781 §5).
- `test_platform_g1_timing.py`: 두 barrier 짝 실행과 대기·연락 간격·RTT 기록(연락 간격 p99 < liveness/2, RTT p99 < 0.25 s); tight 구간에서 조율자를 멈추면 두 팔 모두 `COORDINATOR`/`PARTNER_LINK_LOST`로 HOLD, 걸린 시간 ∈ [liveness − 주기 − 0.05, liveness + 0.25]; 한 팔 transfer 실패 → 짝이 `COORDINATOR` 정지로 HOLD, 실패한 팔은 결합 정지를 받지 않음; Linux에서 실제 UDS로 GetOwnerIdentity·SubmitAction·GetAction RTT.

## 한계와 열린 일

- 시험 미실행. 실행 전에는 위 항목을 통과로 부르지 않는다.
- Fleet 경로의 tight 짝은 payload에 barrier가 없어(컴파일러가 아직 만들지 않음) owner 수준 결합 정지가 일어나지 않는다. 원장 수준 두 팔 HOLD만 확인한다. owner 수준 결합 정지와 조율자 생존은 Fleet 밖에서 barrier grant를 직접 보낸 짝으로 확인한다. `place`+`push`(D-781 `allow_push: false`)는 실행하지 않았다. 짝 실행은 handover 모양(`both_ready`, `both_grasped`)이다.
- 대체 팔로 실행한 Step의 goal 증거는 그 팔 좌표의 predicate(`goal_predicates`)로 판정한다. 팔별 predicate가 없으면 `CELL_GOAL_PREDICATE_MISSING`으로 거절된다(fail closed).
- owner의 cell/3 수락은 후속 과제다(이 기록은 시험에서 대체했다). sku별 물체 정보(`item_key` `box:<sku>`)와 팔별 goal predicate는 recipe/3 후속 작업으로 들어갔고, 이 시험은 그 키와 같은 모양을 쓴다.
- 계획기 station 점검(z 0)이 IK reach를 거절한다. pilot home 0.12 m와 base 0.30 m는 보수적 간격 검사에서 겹친다. 컴파일 fixture(`operations/processes/palletizing/test/fixtures/mixed_two_arm/cell.yaml`)의 home은 바꾸지 않았다.
- G2(ROS-SIM 혼합 적재, MuJoCo 밀기), 물리 무너짐, py3dbp 비교, 실제 UID/systemd 조율자, 공유 E-stop은 하지 않았다.

## 2026-10-21 · CI 연락 간격 집계 보정

source commit a4e40b8cbbfc의 [CI](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39588488804)에서 G1 연락 간격 p99가 0.536276 s로 0.5 s 기준을 넘었다. 같은 SHA의 별도 CI에서는 해당 root shard가 통과했다. 기존 집계는 완료한 짝의 마지막 연락과 다음 짝의 첫 연락을 연결해, 그 사이의 동기 계획·DB 준비 시간도 포함했다. 원래 실패 표본의 양 끝 시각은 남지 않아 그 표본이 짝 경계였다고 단정하지 않는다.

짝마다 시작 인덱스부터의 연락 간격을 모으고 전체 원시 시각·짝별 Action ID/인덱스·전체 간격도 진단 근거로 보존한다. 회귀 시험은 짝 사이의 4.9 s를 분리하면서 짝 내부의 0.9 s 지연은 그대로 남기는지 확인한다. 0.5 s·UDS RTT·watchdog·barrier 상한과 실제 UDS 시험은 바꾸지 않았다. source commit 0279cfe66e3e의 원격 회귀 시험은 시작 인덱스 미지원으로 실패했다. 수정 SHA의 실제 타이밍·전체 CI는 별도로 확인하며 이 보정으로 장치나 현장 수용을 올리지 않는다.
