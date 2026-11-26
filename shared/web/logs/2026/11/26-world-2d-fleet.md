## 2026-11-26 · uncommitted · World 2D 지도가 Fleet 지도 규칙을 따름

- 변경: World 활성·보관 2D 지도가 view_turn_deg(D-513 7)로 돌아가고 N 표지·축척 막대(0.5·1·2 m)를 그린다. 장소는 '이름 (ID)'. 지도 아래 근거 줄 '지도 vN · 수신 HH:MM:SS · 출처'(KST, UTC 원문은 title). 기록 시각도 KST+title. 활성 지도 캔버스에 화살표·Home 키 경로(#856 방식). Isaac·Pinky SIM 신선도는 serve.py가 주는 age_ms·fresh_for_ms로 판정하고 상태 이름은 EVIDENCE_LABEL(최신·지연·정보 없음). World 활성 지도 투영에 표시용 places[].name·view_turn_deg 추가(추가만).
- 증거: node --test applications/world/test/map-rules.test.mjs 5 pass; 원격 pytest·브라우저 결과는 커밋 보고에 기록
- gate 변화: 없음
- 결정: 2026-11-26 UI 지도 패널 추천안 사용자 승인
- 교훈: 없음
