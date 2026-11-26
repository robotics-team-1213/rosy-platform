## 2026-11-26 · 7aa1fe40b4 · station-zone areas that overlap a lane or each other are refused on save

- 변경: `PUT /api/fleet/pipeline/station-zones`가 활성 지도 차로를 `save_station_zones_yaml`에 넘기고, 영역끼리 부분 겹침·차로 표준 폭 2 cm 초과 진입·볼록하지 않은 영역은 쓰기 전에 422로 거절한다. 경로 파일은 두 줄만 바뀐다(`fleet/fleet/server/sitemap` 단위가 한도에 있어서). 차로 수집과 404 `NO_ACTIVE_MAP` 처리는 `fleet.pipeline.station_zones.active_lanes`에 있고, 활성 지도가 없으면 예전대로 차로 검사 없이 저장한다.
- 증거: 독립 읽기 전용 검토(`D:/DevTemp/zone-blueprint-map-20261126/review-r4.md`). 원격 2차 `7aa1fe40b4` 네 묶음 exit 0, known_failures NEW 0. 시험은 `operations/fleet/test/test_station_zones_zone_map.py`다.
- gate 변화: 없음. 로봇 명령 경로는 바뀌지 않았고 거절은 YAML 쓰기만 막는다.
- 결정: 없음
- 교훈: 해당 없음 — 윗 항목의 교훈에 같이 남는다.
