## 2026-11-20 · uncommitted · fix(pipeline): D-1057 검토 반영 — owner 등록 주체, 실제 정차 지점, bed 영구 무효, 저장소 상한

- 변경: `pipeline_evidence.py`: 정지 표본은 속도 채널이 표본마다 신선하고 navigation·Fleet 목표가 없을 때만, owner-evidence는 `ROSY_FLEET_CELL_OWNERS` 등록 서비스 주체만(/complete는 저장 주체와 같아야 함), 활성 지도 ID와 지도 속 정차 지점이 없으면 None, bed-confirm은 이름 있는 운영자·지도 ID 저장·영구 무효·재전송 무갱신, measured_at 60 s·장치 시각 2 s 대조, 본문 64 KB·종료/만료 기록 제거. `pipeline_camera_routes.py`에 완료 주체 확인 한 블록(가드 검사는 그대로).
- 증거: 로컬 `operations/fleet/test/test_pipeline_evidence.py` 외 관련 4개 파일.
- gate 변화: SOURCE.
- 결정: 없음
- 교훈: 없음
