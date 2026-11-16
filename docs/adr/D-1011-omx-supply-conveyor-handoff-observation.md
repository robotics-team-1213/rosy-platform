## D-1011 공급암 S와 적재 셀(A·B) 사이 컨베이어 끝 인계는 Fleet이 관측으로 판단한다

**Status:** Proposed (2026-11-16, 사용자 요청 「ADR 작성해서 올려」). 사용자 방향: 「판정기 자체도 Rosy에 붙여야」, 「Rosy 쪽 완료 신호를 받으면 옮긴다」, 「과부하·양팔 처리 시나리오는 사람이 일을 넣으니 팔 쪽에는 필요 없다」. 최종 승인은 관제·셀 담당(장원종)이 한다. 승인과 구현 전에는 지금 규칙(사람 확인)이 그대로다.

**관련:** D-797 §4·§5(Proposed, 인계 장벽·`camera_item_pose`) · D-977(부분 Accepted, `operator_attested`) · D-856 §3 · D-328 §1·§4 · D-792(카메라 설정 기준) · D-778(다팔, Proposed) · D-998(로컬 Proposed, 게시 전: 판정 성공 뒤 Pinky 자동 출발)

### Context

- 흐름은 셋이다. Pinky가 컨테이너를 싣고 온다. 공급암 S가 Pinky 적재판에서 컨테이너를 하나씩(2단이면 위부터) 꺼내 컨베이어 끝에 놓는다. 적재 셀의 팔 A·B가 컨베이어 끝에서 집어 배 판에 쌓는다.
- 공급암 S는 지금 Rosy 밖 저장소(`omx-imitation-learning`)의 ACT 정책과 카메라 성공 판정기로 돈다. 판정기는 시도마다 `top` 카메라의 시작·끝 화면, 관절, 집게 값으로 Pinky 칸 비움 · 컨베이어에 새로 놓임 · 팔 복귀 · 집게 쥠을 보고 success/failure/unknown을 낸다.
  - 판정 결과를 Fleet이 받는 계약은 없다.
  - 2단 적재에서 위 컨테이너만 빼면 아래 컨테이너가 같은 자리에 남아 「실패」로 나온다(2026-11-10 확인).
- 셀 쪽 완료 신호(origin/main 83cc2292af 코드 확인):
  - 단계(approach·grasp·transfer·release)는 궤적 goal 하나씩이고 `status == 4 and result_code == 0`일 때만 성공이다(`middleware/devices/omx/adapter/omx_adapter/pick_place/pick_place_runner.py:542`).
  - Fleet은 owner 영수증에서 `state`·`journal_event_id`·`observed_at`·`device_reason`만 남긴다(`operations/fleet/fleet/server/step_dispatcher.py:320`). 단계별 요약(grasp 성공 등)은 남지 않는다. 기록되는 이벤트는 `CELL_STEP_ACTION_{outcome}`이다(`operations/fleet/fleet/server/cell/cell_arm_store.py:312`).
  - 목표 증거 출처는 `sim_model_pose`뿐이다(`contracts/foundation/core_common/protocol/cell_goal_evidence.py:26`).
  - 셀 owner는 「Simulation only; not a device entrypoint」(`deploy/robot/omx/run_cell_owner.py:5`), 하드웨어 owner는 `goals_enabled: False`(`middleware/devices/omx/agent/src/rosy_agent/omx_hardware_owner.py:134`)다.
  - 실물 팔 스크립트 `deploy/robot/omx/cell_auto_pick.py`의 결과는 `attempts.jsonl`(`rosy.omx-cell-attempt.v1`, `deploy/robot/omx/cell_attempts.py:12`)과 표준 출력뿐이다.
  - 그래서 「컨테이너가 컨베이어 끝을 떠났다(셀이 집었다)」를 바깥에 알리는 경로가 없다.
- 컨베이어 끝은 한 번에 한 개만 놓는다고 본다. 앞의 것이 남아 있는데 다음 것을 놓으면 겹친다.

### Decision

1. **판단은 Fleet이 하고, 공급암 S 판정기는 관측 생산자다.** 판정기는 결정을 내리지 않고 사실만 Fleet에 낸다.
   - (a) Pinky 적재 칸에 남은 컨테이너(없음 포함).
   - (b) 컨베이어 끝에 새로 놓인 컨테이너(위치, 프레임 시각).
   - (c) 시도별 집게 쥠, 팔 복귀.
   - 출처, 카메라 설정 기준 revision(D-792), 프레임 시각을 붙인다.
   - Pinky 출발과 공급암 S의 다음 하역 지시는 Fleet이 이 관측으로 정한다. D-998이 제안한 「판정기가 직접 Pinky goal을 보낸다」는 이 결정이 대체한다.
2. **컨베이어 끝은 D-797 §4의 인계 장벽 자리다.** 1(b)의 관측을 적재 셀 step 0의 원본 관측으로 쓴다. D-797 §4의 `POST /api/fleet/cell-source-observations`(Proposed)와 같은 계약이며, 새 경로를 만들지 않는다.
3. **셀이 원본에서 집은 사실을 Fleet이 남기고, 하역은 그 뒤에만 한다.**
   - Fleet은 owner 영수증의 grasp 단계 성공을 버리지 않고 이벤트로 남긴다. 이 이벤트가 「컨베이어 끝이 비었다」의 근거다.
   - 공급암 S의 다음 하역 지시는 이 이벤트 뒤에만 나간다.
   - 이벤트 이름과 wire는 구현 때 D-18에 따라 API Reference·schema·생산자/소비자 시험과 같이 정한다.
4. **실물 셀 증거가 생기기 전의 대체 근거.** 셀 owner가 실물에서 단계 영수증을 내지 못하는 동안(D-797 §5 이전)은 `top` 카메라가 컨베이어 끝 영역이 빈 것을 관측한 사실을 대체 근거로 쓴다. 출처를 카메라 관측으로 구분해 기록한다. 기명 운영자 확인(D-977 `operator_attested`)과 섞지 않는다(D-328 §4).
5. **판정기 코드는 Rosy로 옮긴다.** 위치는 D-226과 `tools/harness/platform_parts.yaml`에 따라 따로 정한다. 녹화 앱과 정책 실행기는 이 결정 범위 밖이다.

### D-427·D-429·D-430과의 관계

| ADR | 관계 |
|---|---|
| D-427 | 새 최상위 폴더를 만들지 않는다. 판정기 위치는 기존 root 안에서 후속으로 정한다. |
| D-429 | 소스 이전 대상이 아니다. 옮길 때 `platform_parts.yaml`의 `d427_target`을 따른다. |
| D-430 | safety 태그 경로를 바꾸지 않는다. 실물 하달 안전 결정은 D-797 §7·D-977 Decision 4가 맡는다. |

### 일부러 하지 않는 것

- 과부하·양팔 협응 배정. 사람이 일을 넣는다(D-778 몫).
- 판정기나 정책 실행기가 Pinky goal이나 팔 Action을 직접 내는 것.
- 운영자 확인을 동작 성공 증거로 쓰는 것(D-328 §4, D-977 Decision 5).

### 열린 항목

- 관측 wire(경로·필드·허용오차), 컨베이어 끝의 좌표계와 `robot_base` 변환. D-797 §5 `camera_item_pose`와 같이 정한다.
- 2단 적재의 판정 규칙: 위 컨테이너만 빠졌을 때 「한 개 남음」으로 보는 기준.
- 판정기 코드의 Rosy 안 위치와 소유 모듈.
- D-998(로컬, 게시 전)의 처리. 이 ADR이 승인되면 철회하거나 Superseded로 표시한다.

### Consequences

- Pinky 출발과 다음 하역이 Fleet의 판단으로 모인다. 컨베이어 끝에 컨테이너가 겹쳐 놓이는 일을 막는다.
- 셀이 실물 영수증을 내기 전에도 카메라 대체 근거로 같은 흐름을 시험할 수 있다.
- 구현 전까지는 지금 규칙(사람 확인)이 유지된다.

### Validation

- SOURCE: 관측 수신·거절 시험, grasp 단계 이벤트 기록 시험, 하역 지시가 그 이벤트를 기다리는 시험.
- DEVICE: 실물 공급암 S와 적재 셀 A·B로 인계 3회 연속(D-797 §8 형식), 기록은 `docs/validation/`.

**References:** D-18, D-226, D-328, D-427, D-429, D-430, D-778, D-792, D-797, D-856, D-977, D-998.
