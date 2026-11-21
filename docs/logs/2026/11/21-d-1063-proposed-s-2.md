## 2026-11-21 · uncommitted · D-1063 Proposed: 공급암 S 인계 계약 보충(카메라 근거·2단 적재)

- 변경: docs/adr/D-1063-arm-s-handoff-contract-camera-evidence-two-tier.md 신규(Proposed). rosy.fleet-r-cell-contract.v1의 공급암 S TRANSFER_DONE·RELEASED를 top 카메라 관측과 짐칸 빈 판정으로 정한다. 게시되지 않은 로컬 초안 D-1011(판정기 관측)·D-998(자동 출발)을 대신한다(두 번호는 origin에서 다른 ADR로 쓰였다)
- 증거: 인용 코드 위치를 origin/main(2026-11-21)에서 확인: cell_fleet_contract.py:62 evaluate_handoff_gate, cell_fleet_handoff.py:143-215 run_contract_handoff_stage(model_only, physical_completion False, 단계 하나 뒤 RELEASED), cell_spec_recovery_fsm.py:22-23, cell_grasp_judges.py:70
- gate 변화: 없음
- 결정: D-1063 Proposed
- 교훈: 로컬 main이 origin보다 크게 뒤처진 채 ADR 번호를 잡으면 게시 전에 번호가 다른 ADR로 쓰인다: 게시 PR이 닫히면 번호부터 다시 확인
