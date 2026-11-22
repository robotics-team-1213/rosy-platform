## 2026-11-20 · uncommitted · feat(omx): D-1057 배치 직후 구역 측정(zone_verification) 생산자

- 변경: `cell_zone_verification.py` 신규(기존 `cell_area_zones` 측정을 새 상부·측면 프레임으로 실행). `cell_auto_pick.py`가 placed 직후 기록하고, 이전에는 attempts 행에 없던 `verify`·`transfer`·`zone_verification`을 행에 싣는다(`cell_task_exec`가 읽는 자리).
- 증거: 로컬 `test/test_omx_cell_zone_verification.py`, `test_omx_cell_task_exec_measured.py`, `test_omx_cell_auto_pick.py` 등. 실물·카메라 미실시.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
