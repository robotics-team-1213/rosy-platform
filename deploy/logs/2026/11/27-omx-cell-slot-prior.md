## 2026-11-27 · uncommitted · OMX 임시판 칸 사전지식(cell_slot_prior)

- 변경: 사이트 선택 키 slots·slots_fit을 읽어 칸 밖 덩어리 제외, 깊이 층수로 칸 안 재측정·칸 축 맞춤(8 mm/5°/가로 4 mm), 맞춰진 물체에만 사이트 finger_params 적용. 집게 닫기 칸 축 수직 ±3°, 이웃 높이 모르면 3단, SITE_NOT_MEASURED·깊이/측면 반 단 보류. slots 없으면 이전과 같음. 도달 보조 함수는 cell_auto_reach.py로 그대로 옮김
- 증거: 원격 pytest affected 선택 7회(test_omx_temp_plate_prior.py 포함, 2026-11-27 상단 프레임 고정 입력)
- gate 변화: 없음(auto.neighbour_clear_mm·min_jaw_margin_mm·finger_mm 기본값, outside_blocks 그대로)
- 결정: 2026-11-27 임시판 인식 패널 안전 조건
- 교훈: 없음(셀 설정 값·판 기준점 측정·실물 수용 전)
