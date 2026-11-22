## 2026-11-20 · uncommitted · feat(pipeline): D-1057 셀 작업 허가 증거 공급자와 bed·owner 증거 경로

- 변경: `server/sitemap/pipeline_evidence.py` 신규(`amr_evidence`, `omx_owner_evidence`, `StillTracker`, `POST .../bed-confirm`, `POST .../owner-evidence`). `site_map_routes.py`·`charge_bay_routes.py`가 두 공급자를 `install_pipeline_routes`에 넘긴다. `_ready_amr`와 `complete_cell_task`의 한계값·거부 코드는 그대로다. 시험 `test_pipeline_evidence.py` 신규, `test_pipeline_mutation_guards.py`는 owner-evidence를 service 허용 목록에 추가.
- 증거: 로컬 `python -m pytest operations/fleet/test/test_pipeline_evidence.py` 외 관련 5개 파일 통과(Windows, 2026-11-20). 원격 시험은 조정 세션.
- gate 변화: SOURCE. 실물 인터록(브레이크·bed 센서·명령 속도)은 없어 대용 측정이다(D-1057). 공급자가 없는 값은 None이라 기존 거부가 난다.
- 결정: 없음
- 교훈: 없음
