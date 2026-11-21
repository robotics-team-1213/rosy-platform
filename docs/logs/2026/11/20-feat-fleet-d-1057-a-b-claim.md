## 2026-11-20 · uncommitted · feat(fleet): D-1057 셀 A/B claim 게이트 (깊이 판정 수용 전)

- 변경: `claim`이 `cell_ab` 작업을 `ROSY_FLEET_CELL_AB_RELEASE_ENABLED`(기본 꺼짐)가 켜져 있지 않으면 `CELL_AB_EVIDENCE_NOT_ENABLED`로 `_ready_amr` 앞에서 거부, 원장 불변. 셀 S 무영향. ADR 2-3절. origin/main(#263 홈 복귀 안전) 병합은 별도 커밋.
- 증거: 로컬 `test_pipeline_evidence.py`(꺼짐 5값·켜짐·셀 S), `test_pipeline_orchestrator.py` 외 관련 Fleet 시험.
- gate 변화: 셀 A/B 는 켜기 전까지 claim 불가.
- 결정: 없음
- 교훈: 없음
