## 2026-11-27 · uncommitted · OMX 임시판 층수 기준(판 윗면)·칸 측정 도구(cell_temp_plate)

- 변경: cell_slot_prior 층수 높이 기준을 팔 받침 고리(plate_top)에서 임시판 팔 쪽 평평한 윗면(CAD v12 13.6 mm, 칸 바닥 8 mm)으로, 깊이 3회 촬영 화소별 중앙값(화소 과반). 띠 표본 2/3 미만이 ±4 mm 안이면 층수 모름(사전지식 미적용). 읽기 전용 CLI cell_temp_plate.py: CAD 판 외곽을 상단 영상에 맞춰 slots·slots_fit 출력, 탐색 한계·양쪽 긴 변/팔 쪽 가장자리 부족·카메라 모델 크기 ±3 % 초과·잔차 3 mm/1° 초과는 거절
- 증거: 원격 pytest test_omx_temp_plate_measure.py·test_omx_temp_plate_prior.py(2026-11-27 프레임: 두 팔 모두 긴 변 한쪽 가려 거절). 실물 깊이 띠 측정은 A/B 허브 정지로 미실행
- gate 변화: 없음(±7 mm 층 판정, 모르면 3단, 3 mm/1° 판 맞춤 한계 그대로)
- 결정: 2026-11-27 18:10 셀 측정 후속
- 교훈: 없음(실물 수용 전)
