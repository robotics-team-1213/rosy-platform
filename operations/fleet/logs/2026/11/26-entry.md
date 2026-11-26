## 2026-11-26 · uncommitted · 측량 도로선을 지도 기록 필드로 서버가 냄

- 변경: fleet/site_map.py: SiteEdge에 추가 필드 display_polyline + display_source(kind survey, surveyed_at, plane, anchors, stored_until, note)와 FLOOR_SURVEYS(world_261026, ceiling_north, 2026-11-26) 표, with_floor_surveys. GET /api/fleet/site-map/active가 기록에 없는 간선에만 끝점 1 mm 일치 시 덧붙임(저장 본문·sha256 그대로). 콘솔 site-layer.js floorSurvey 상수 삭제
- 증거: test_site_map_survey.py(덧붙임·불일치·짝·유한·라우트) 원격; 브라우저 test_site_map_interaction_browser·test_traffic_view_browser가 with_floor_surveys 응답으로 소비자 경로 확인
- gate 변화: 없음
- 결정: 2026-11-26 지도 패널 결정 1 (가) 서버 지도 기록 정본(사용자 승인)
- 교훈: 없음
