## D-564 바닥 장소 마커로 장소를 가르친다 — 천장 카메라가 본 마커 자리와 방향을 초안 장소로

**Status:** Accepted (2026-10-09, 사용자 결정: 사이트 장소에 놓은 바닥 ArUco 마커(DICT_4X4_50)의 천장 카메라 위치와 방향으로 Fleet이 장소를 등록·갱신해, 로봇을 그 자리에 세우지 않아도 되게 한다). SOURCE 변경과 호스트 테스트만이다. 스티커 인쇄·부착, 현장 수용은 이 기록이 하지 않는다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(천장 sighting, source 토큰) · [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md)(천장 마커 우선) · [D-488](D-488-fleet-site-map-address-routes.md)(사이트 지도 장소·초안) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 6항(지도 가르치기) · [D-513](D-513-demo-start-places-fixed-heading.md)(출발 자리는 방향이 필요) · [D-562](D-562-ceiling-marker-id-equals-robot-number.md)(천장 마커 id 배치, 34–38 장소 예약). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

- D-494 6의 `POST /api/fleet/teach/place`는 LOCALIZED 로봇의 지도 자세로 장소를 만든다. 출발 자리(D-513)는 방향이 필요해서, 지금은 로봇을 그 자리에 정확히 세워야 한다.
- 천장 카메라(Vision)는 프레임마다 모든 ArUco 마커를 한 번 검출하고(`rosy_vision/worker.py`), 로봇 마커만 모서리 호모그래피로 지도 좌표에 투영한다(`project.py`).
- D-562가 장소 마커 id 34–38을 예약했다: 34 출발-남, 35 출발-북, 36 충전, 37 주차, 38 정지. 바닥 스티커는 40–55 mm(흰 테두리 1칸, 검정 6/8)다.
- 바닥 마커의 높이는 0이다. 로봇 윗면 마커처럼 높이 보정이 필요하지 않다.

### Decision

1. **설정.** 사이트 카메라 설정(`site-cameras.yaml`)의 source마다 `place_markers: [34, 35, ...]`(정수 id 목록)를 둘 수 있다. id는 0–49, 서로 다르고, `corner_marker_ids`와 `robot_markers` 값과 겹치지 않는다. Vision과 Fleet 두 파서가 같은 검사(`core_common.protocol.place_markers.check_place_marker_ids`)를 쓴다. 없으면 빈 목록이고 아무것도 보내지 않는다.
2. **Vision.** 이미 검출한 마커 가운데 설정된 장소 마커를 로봇 마커와 같은 호모그래피·같은 `heading_edge`로 `(x, y, yaw)`에 투영한다. 장소 스티커는 로봇 스티커와 같은 변을 앞으로 해서 놓는다. 높이 보정은 없다. 0.5 s에 한 번 이하로 `POST /api/fleet/place-markers`에 `PlaceMarkerPayload {map_id, calibration_revision, captured_at, seq, markers[{marker_id, x, y, yaw}]}`를 보낸다. 실패는 로그만 남기고 로봇 sighting과 추적 단계를 막지 않는다.
3. **Fleet 수신.** sighting과 같은 source 토큰으로 인증하고, source 신원은 토큰에서 정한다(본문에 `source_id`를 받지 않는다, D-257). `map_id`·`calibration_revision`이 source 설정과 다르면 409, 설정에 없는 마커 id는 403, 미래 시각·2 s 넘은 것·순서가 뒤인 것은 409다. (source, marker_id)마다 최신 하나만 메모리에 둔다. `GET /api/fleet/place-markers`는 관제 보기 권한으로 `age_ms`·`stale`과 함께 돌려준다.
4. **마커로 가르치기.** `POST /api/fleet/teach/place-from-marker {marker_id, name, kind, place_id?, expected_revision?}`(이름 있는 운영자). 그 마커의 가장 새로운 신선한 관측(2 s 이내, 같은 source·map·calibration revision)이 없으면 409 `PLACE_MARKER_STALE`, 활성 사이트 지도가 있고 `map_id`가 다르면 409 `PLACE_MARKER_MAP_MISMATCH`, 장소 마커 설정이 없으면 503 `PLACE_MARKERS_DISABLED`다. `place_id`가 없으면 `teach.add_place`로 새 장소를, 있으면 그 장소의 x·y·yaw(와 준 경우 이름·종류)를 바꾼다(없는 id는 404 `PLACE_UNKNOWN`, bend는 422 `PLACE_MARKER_BEND`). 결과는 `/teach/place`와 같은 초안 저장(`expected_revision` 규칙)과 `teach_place` 이벤트(`marker_id`, `source_id`)다.
5. **권한.** 표시와 가르치기만이다. 결과는 초안 장소이고 운영자가 다른 가르친 장소처럼 활성화한다. 로봇에 아무것도 보내지 않고, 지도 자세·trip·교통정리는 장소 마커를 읽지 않는다.
6. **관제 화면.** 지도 가르치기 패널에 신선한 장소 마커 목록과 "마커로 등록" 버튼을 둔다. 이름·종류 칸은 기존 "여기에 주소 만들기"와 같이 쓴다.

### 범위 밖

- 활성 장소와 마커 위치가 어긋났을 때의 경보(드리프트 경보)는 하지 않는다. 필요하면 별도 ADR이다.
- 장소 마커로 로봇 위치를 보정하거나 D-457 폴백에 쓰지 않는다.
- 장소 마커 관측은 저장하지 않는다. Fleet을 다시 시작하면 다음 관측을 기다린다.

### 관계

| ADR | 관계 |
|---|---|
| D-257 | 같은 source 토큰·map·calibration 검사와 표시 전용 원칙을 쓴다. sighting 계약(`robot_id` 필수)은 바꾸지 않는다 |
| D-457 | 천장 마커 검출을 같이 쓴다. 로봇 위치 폴백과는 무관하다 |
| D-488 | 결과는 사이트 지도 초안의 장소다. 활성화 규칙은 그대로다 |
| D-494 6 | `/teach/place`의 초안·이벤트 경로를 그대로 쓰고 자세 출처만 마커로 바꾼다 |
| D-513 | 출발 자리에 필요한 방향을 마커가 준다. 로봇을 세우지 않아도 된다 |
| D-562 | 34–38 예약을 이 ADR이 읽고 쓴다 |

### Alternatives

| 대안 | 판단 |
|---|---|
| `/api/fleet/sightings`에 마커를 로봇처럼 보낸다 | 기각. `robot_id` 필수 계약과 지도 자세 입력을 흐린다 |
| Fleet이 마커를 보면 장소를 자동으로 바꾼다 | 기각. 장소 변경은 운영자 초안 저장으로만 한다 |
| 마커 관측을 저장한다 | 보류. 가르치기는 지금 보이는 마커만 쓴다 |

### Consequences

- 출발·충전·주차·정지 자리를 스티커 하나로 가르칠 수 있다. 정확도는 천장 보정과 스티커 크기(D-562 검출률)를 따른다.
- 스티커 방향이 틀리면 장소 방향도 틀린다. 활성화 전에 지도에서 방향을 본다.
- API는 additive(v1.167)다.
