## D-1063 공급암 S 인계 계약 보충: `TRANSFER_DONE`·`RELEASED`는 `top` 카메라 관측으로 정하고, 2단 적재는 짐칸이 빌 때만 놓아 준다

**Status:** Proposed (2026-11-21, 사용자 요청 「보충 ADR로 다시 써서 올려」). 승인: 인계 계약 담당 장원종, OMX 김승용·서정민. 구현·실물 수용은 별도다.

**보충하는 것:** `operations/fleet/fleet/pipeline/cell_fleet_contract.py`의 `rosy.fleet-r-cell-contract.v1`(2026-11-12 `01988565d4`·`ae7a2ed52c`, 이 계약을 정한 ADR은 없다)과 그 셀 쪽 실행 `deploy/robot/omx/cell_fleet_handoff.py`의 `run_contract_handoff_stage`. **관련:** D-797 §4(Proposed, 인계 장벽), D-328 §2·§4(근거 두 가지), D-792(카메라 설정 기준), D-933(공급암 S 카메라 좌표), D-977 Decision 4·5. **대체:** 게시되지 않은 로컬 초안 두 개(2026-11-09 「D-998 판정 성공 뒤 Pinky 자동 출발」, 2026-11-16 「D-1011 컨베이어 끝 인계 관측」, 둘 다 번호가 origin에서 다른 ADR로 쓰여 버렸다). 이 ADR이 그 둘을 대신한다.

### Context

- 계약은 Pinky(AMR)와 셀 사이 단계를 `IDLE → ARRIVED → CLAIMED → ARM_IN_BED_ZONE → (HUMAN_HOLD) → TRANSFER_DONE → RELEASED / ABORTED`로 정한다. `evaluate_handoff_gate`는 영수증 단계가 `IDLE`·`RELEASED`일 때만 `amr_can_depart`다. `CellToFleetRReceipt`에는 `goal_evidence_digest`와 `reason`이 있다.
- 지금 공급암 S 단계 실행(`run_contract_handoff_stage`, origin/main 2026-11-21)은 단계 하나의 계산 수렴(`converged`)만 보고 바로 `RELEASED`를 낸다. 영수증에 `"execution": "model_only"`, `"physical_completion": False`가 붙고, 다이제스트는 `lease`·`stage`·`converged`만 담는다.
  - 실물에서 컨테이너가 실제로 짐칸을 떠났는지, 컨베이어에 놓였는지를 보는 근거가 없다.
  - Pinky가 2단(컨테이너 두 개)을 싣고 오면 첫 단계 뒤에 `RELEASED`가 나와, 아래 컨테이너가 남은 채 Pinky가 떠날 수 있다.
- 공급암 S는 실물에서 지금 Rosy 밖 저장소(`omx-imitation-learning`)의 ACT 정책과 `top` 카메라 판정기로 돈다(2026-11-21 실물 4회 중 3회 성공, 2단 위 컨테이너 3회 모두 성공). 판정기는 시도 전·후 `top` 프레임을 비교해 (a) 짐칸 자리 변화, (b) 컨베이어에 새로 놓인 컨테이너, (c) 시도 중 집게 쥠, (d) 짐칸이 비었는지(2단이면 아래까지)를 내고, 주황·노랑·분홍 컨테이너를 같은 규칙으로 본다.
- Rosy에는 같은 카메라·자리를 쓰는 조각이 이미 있다: `cell_spec_recovery_fsm`의 `pinky_tray`·컨베이어 구역 ROI(`CELL_S_EXTENDED_ZONES`), `cell_fleet_handoff`의 잡기 전 빈자리 확인(`EMPTY_WRIST_OCC_THRESHOLD`), `cell_grasp_judges`의 잡기 판정(`telemetry_judge`). 시도 **뒤** 성공/실패를 정하는 것과 2단 처리는 없다.

### Decision

1. **`TRANSFER_DONE`은 실물 관측 두 가지가 다 있을 때만 낸다(D-328 §2).** 공급암 S가 컨테이너 하나를 옮긴 뒤:
   - (i) 셀의 권위 있는 결과: 그 시도의 잡기 판정(`cell_grasp_judges.telemetry_judge` 또는 같은 의미의 집게 쥠)이 성공이다.
   - (ii) `top` 카메라 관측: 시도 전·후 프레임에서 `pinky_tray` 구역의 그 컨테이너 자리가 바뀌었고, 컨베이어 놓기 구역에 새 컨테이너가 보인다.
   - 둘 중 하나가 없거나 판정이 「알 수 없음」이면 `TRANSFER_DONE`을 내지 않고 `HUMAN_HOLD`로 둔다(motion inhibit 유지). 운영자 확인은 (i)·(ii)를 대신하지 않는다(D-328 §4, D-977 Decision 5).
2. **`RELEASED`는 짐칸이 빈 것을 카메라로 본 뒤에만 낸다.** `TRANSFER_DONE` 뒤 `top` 카메라가 `pinky_tray` 구역에 컨테이너가 남지 않았음을 보면 `RELEASED`다. 남아 있으면(2단의 아래 컨테이너) 단계는 `CLAIMED`로 돌아가 다음 컨테이너를 옮긴다. `RELEASED` 전에는 `amr_can_depart`가 거짓이다(`evaluate_handoff_gate`는 바꾸지 않는다).
3. **영수증에 관측을 묶는다.** `goal_evidence_digest`는 시도 전·후 `top` 프레임의 해시, 판정 결과·사유, 카메라 설정 기준 revision(D-792)을 함께 담는다. `physical_completion`은 1(i)·(ii)를 다 본 실물 단계에서만 참이고, 계산만 한 단계(`model_only`)는 지금처럼 거짓으로 남는다. 계약 이름·필드는 바꾸지 않는다(`rosy.fleet-r-cell-contract.v1` 그대로). 다른 셀(A·B)은 이 ADR의 범위가 아니다.
4. **겹치는 부분은 Rosy 것을 쓰고, 판정 규칙만 옮긴다.** 구역은 `cell_spec_recovery_fsm`의 ROI를, 집게 쥠은 `cell_grasp_judges`를 그대로 쓴다. Rosy 조각이 실물 프레임에서 맞지 않으면 그 조각을 고친다(새 사본을 만들지 않는다). 새로 옮기는 것은 시도 전·후 비교, 컨베이어 놓임 검출, 짐칸 빈 판정(2단), 세 색 컨테이너 검출이다. 위치는 `deploy/robot/omx/`의 공급암 S 셀 코드 옆이다(D-427·D-429, 새 최상위 폴더 없음).
5. **Pinky 출발과 다음 하역은 Fleet이 정한다.** 판정 코드나 정책 실행기는 Pinky goal이나 팔 Action을 직접 내지 않는다. 판정은 영수증 단계와 다이제스트로만 나간다(로컬 초안 D-998의 「판정 성공 뒤 자동 출발」은 고르지 않는다).

### 일부러 하지 않는 것

- 계약 버전 올리기·새 Fleet API. 지금 필드로 충분하다.
- 다른 셀(A·B) 팔레트 적재의 완료 근거.
- 실물 OMX goal 수용 경로 열기(D-977 Decision 4).

### 열린 항목

- 「알 수 없음」의 기준(프레임 품질, 팔이 시작 자세로 돌아오지 않은 채 끝난 시도). 지금 판정기는 놓는 순간 끝낸 시도를 「알 수 없음」으로 낸다(2026-11-21 확인).
- 카메라 맞추기: `cell_spec_recovery_fsm`의 `pinky_tray` ROI(`top_roi_px` (10, 40, 260, 240))는 Rosy 셀의 `arm_s_top` 화면 기준이고, 지금 판정기는 공급암 S 녹화 노트북의 `top` 카메라로 맞춰 왔다. 두 화면이 같은지, ROI가 실제 정차 위치 퍼짐을 덮는지 맞춘다(노트북 `top` 기준 2026-11-16 실물 시도에서 컨테이너 중심이 세로 184~303 px까지 나왔다).
- `top` 카메라가 움직였을 때의 처리(D-933 마커 기준 재보정과의 관계).

### Consequences

- 실물에서 Pinky가 짐칸이 빈 뒤에만 떠난다. 2단 적재에서 아래 컨테이너를 싣고 떠나는 일이 막힌다.
- 시뮬 단계의 동작은 그대로다(`model_only` 영수증).
- 구현 전까지는 지금 규칙(사람 입회)이 유지된다.

### Validation

- SOURCE: `run_contract_handoff_stage`의 공급암 S 경로 시험 — 관측 두 가지가 다 있을 때만 `TRANSFER_DONE`, 2단에서 첫 컨테이너 뒤 `CLAIMED`·둘째 뒤 `RELEASED`, 「알 수 없음」은 `HUMAN_HOLD`, `model_only` 영수증은 변화 없음. 판정 규칙은 녹화된 실물 에피소드(2026-11-10~21)로 맞춘다.
- DEVICE: 실물 공급암 S로 2단 인계 3회 연속(D-797 §8 형식), 기록은 `docs/validation/`.

**References:** D-328, D-427, D-429, D-792, D-797, D-933, D-977.
