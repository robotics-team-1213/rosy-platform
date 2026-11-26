## 2026-11-26 · uncommitted · World·Fleet 2D 지도 규칙 사본을 /common/map-rules.js 하나로

- 변경: shared/web/map-rules.js(viewTurnOf·placeText·scaleBar·stamp·mapEvidence)를 /common 자산으로 추가. World map-rules.js 사본(#922)을 지우고 World 고유 simFreshness는 sim-freshness.js로 옮김, World 번들 COMMON_FILES에 map-rules.js. Fleet site-map-model의 viewTurnOf·근거 줄 시각 형식, map-view 축척 단위 선택, site-map·zone-blueprint 장소 표기를 공용으로 바꿈(Fleet 근거 줄 함수는 activeMapEvidence로 이름 바꿈). 축척 단위는 Fleet 0.5·1·2 m 우선, 칸을 넘으면 1·0.5·0.2·0.1·0.05 m(0.02·0.01 m 삭제). Fleet 근거 줄은 날짜가 다르면 MM-DD를 붙이고 시각 없음은 '확인되지 않음'. test_shared_dedupe HELPERS에 scaleBar 행(World 화면 포함)
- 증거: node --test shared/web/test/map-rules.test.mjs, applications/world/test, operations/fleet/test/web 로컬 통과; World 사본을 되살리면 dedupe 시험 빨강(5곳) 확인; 원격 pytest는 갈래 보고에 기록
- gate 변화: 없음
- 결정: 2026-11-26 지도 패널 추천안
- 교훈: 없음
