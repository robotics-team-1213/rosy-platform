## 2026-11-20 · uncommitted · fix(omx): D-1057 접힘 기준을 plan 파일 home으로, 구역 판정을 실제 설정 형태에 맞춤

- 변경: `cell_task_exec`가 config의 `plan_path` 파일에서 `home`을 읽고(설정 JSON에는 plan이 없다) 몸 관절 5개만 비교. `cell_zone_verification`은 tier를 확장된 사이트의 `tier`에서 읽고, col/row가 설정에 없으면 이유를 적어 unverified. 실제 설정 모양으로 축약한 시험 추가.
- 증거: 로컬 `test/test_omx_cell_zone_verification.py`, `test_omx_cell_task_exec_measured.py`. 실물 미실시.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
