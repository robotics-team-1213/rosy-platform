# 사이트 차선 관제 + 폰 천장 카메라 — 설계와 실행 계획

**결정:** [D-257](../adr/D-257-site-lane-map-and-overhead-sightings.md) (Proposed).
**상태:** 설계. 코드 0줄. D-257이 Accepted되기 전에는 구현하지 않는다.
**D-210과의 관계:** 별도 트랙이다. 1차 FIELD READY 범위(2대 관제+군집)와 그 게이트를 바꾸지 않는다.

## 1. 문제

관제 화면은 있지만 현장이 쓰는 지도를 모른다.

| 지금 | 필요 |
|---|---|
| Fleet 콘솔은 로봇이 준 Nav2 점유격자를 그린다 (`GET /api/fleet/map`) | 차선 그래프(도로·교차점·회전교차로·주차) 위에 N대 |
| 로봇 위치 = 로봇 자기 보고 pose뿐 | 외부에서 본 위치로 대조 |
| 차선 지도 표면은 Gazebo 디버그 `lane_live_view.py`뿐 (1대, ROS 필요) | 실물 현장에서 쓰는 관제 |

## 2. 구조

```
[폰, 트랙 위 거치]            [현장 PC]                                [현장 PC 또는 같은 LAN]
 IP카메라 앱 ── MJPEG/HTTP ──▶ 관측 어댑터 (cv2, 최신 1장)  ── JSON ──▶ Fleet 서버 (영상 없음)
                               ArUco → 호모그래피 → map m     sightings    ├ lane_graph.yaml 적재
                                                                           ├ 로봇 자기 pose (기존 gather)
                                                                           └ 콘솔: 차선 층 + 두 위치 + 차이 경고
```

- **폰:** 카메라만. 인식 없음. 앱은 MJPEG를 HTTP로 내는 흔한 IP카메라 앱이면 된다.
- **관측 어댑터:** 새 ROS-free 프로세스. 위치 제안: `src/site/overhead/` (이름은 D-231 규칙 확인 후 확정). cv2는 한 파일(`detect.py`)에만. 좌표 변환은 `games.field.homography.fit(src_px, dst_m)`를 import한다 — 이미 입력 좌표계를 가리지 않는다.
- **Fleet:** 위치 JSON만 받는다. cv2·이미지·영상 URL 없음. `test_no_video_relay.py` 녹색 유지.

## 3. 좌표와 보정

- `lane_graph.yaml` 좌표 = ROS `map` 프레임 m. 코너 마커 4개를 트랙 위 **이미 아는 map 좌표**에 붙이고, 그 좌표를 설정에 적는다. 호모그래피가 픽셀 → map m를 직접 낸다. 로봇 쪽 좌표계와 따로 맞출 필요가 없다.
- **마커 평면:** 코너 마커를 로봇 상단 마커와 같은 높이(받침대)에 둔다. 이러면 보정이 필요 없다. 불가능하면 `camera_height_m`, `marker_height_m`를 설정해 시차 보정한다. 오차 ≈ `d·h/H` (`h`=0.12 m, `H`=2 m, `d`=1 m → 6 cm, 차선 허용 40 mm 초과).
- **yaw:** 로봇 마커 1장의 코너 순서(0→1 변)로 정한다. 마커 부착 방향을 로봇 전방과 맞추고, 오프셋은 설정값 `yaw_offset_rad`.

설정 예 (`overhead.yaml`, 주소·토큰은 `private/` 또는 환경변수 — 공개 저장소다):

```yaml
stream_url: ${ROSY_OVERHEAD_STREAM}      # 폰 MJPEG 주소
fleet_url: http://127.0.0.1:8090
lane_graph: src/runtime/sensing/map/map_v2_fleet/lane_graph.yaml
dictionary: DICT_4X4_50
corners:            # marker_id: [x, y] map m — 현장 실측으로 채운다
  30: [-1.40, -0.60]
  31: [ 0.40, -0.60]
  32: [ 0.40,  0.70]
  33: [-1.40,  0.70]
robots:             # marker_id: robot_id
  40: rosy_01
  41: rosy_02
marker_height_m: 0.0   # 코너를 같은 높이에 두면 0
max_fps: 5
```

## 4. Fleet 계약 (초안)

`GET /api/fleet/lanes` → `{map_id, nodes, segments, roundabout, parking}` (`lane_graph.yaml` 그대로 + `map_id`). 파일을 주지 않으면 404 `NO_LANES` — 콘솔은 차선 층 없이 뜬다.

`POST /api/fleet/sightings` (쓰기 전용 어댑터 토큰):

```json
{
  "source": "overhead-1",
  "seq": 1842,
  "captured_at": 1790000000.123,
  "map_id": "lane_graph.yaml:3f9c…",
  "robots": [{"robot_id": "rosy_01", "x": -0.52, "y": 0.17, "yaw": 1.57}]
}
```

거절: 모르는 `robot_id`, `map_id` 불일치, `seq` 역행, `captured_at`이 1 s보다 오래됨, 콘솔 토큰(goal 권한)으로 호출. 저장은 출처별 최신 1건. 스냅샷(`/api/fleet/state`)의 로봇마다 `sighting: {x, y, yaw, age_s, fresh}`와 `divergence_m`(자기 pose와의 거리)을 붙인다.

## 5. 콘솔 화면

- 차선 층: 도로 폴리라인, 교차점, 회전교차로 방향 표시, 주차 자리. D-249 spec 3항(y 뒤집기, 토큰 색, 그리는 것만 legend).
- 로봇마다 두 표시: 자기 pose(기존)와 sighting(속 빈 원 등 구별되는 모양). `age_s` > 1 s면 회색.
- `divergence_m` > 임계(초기 0.15 m, 실측 후 조정)면 로봇 카드에 경고. 문구는 "카메라와 로봇 위치가 다름"처럼 사실만.
- 목표 클릭은 기존 좌표 방식 그대로. 차선 단위 지시는 범위 밖(§7).

## 6. 실행 단계

각 단계는 TDD. 합성 통과는 LOCAL이고 DEVICE가 아니다(D-95).

**Stage 1 — Fleet 차선 층 (영상 무관)**
1. `rosy_fleet console --lanes <lane_graph.yaml>` 옵션, `map_id` 계산, `GET /api/fleet/lanes`. 시험: 파일 없음 → 404, 체크섬 안정성.
2. `console.js` 차선 층. 시험: 기존 지도 시험 녹색, 차선 층 좌표가 lane_graph 점과 일치.
3. 확인: Gazebo `map_v2_fleet_lane` 2대로 로봇 pose가 도로 위에 그려지는지(ROS-SIM).

**Stage 2 — 관측 어댑터 (LOCAL)**
1. `detect.py`(cv2 유일): 프레임 → `{marker_id: 코너 4점}`.
2. `project.py`(순수): 코너 4점 → 호모그래피 → 로봇 `x, y, yaw`, 시차 보정. 코너 하나라도 없으면 빈 결과.
3. `run.py`: 스트림에서 최신 프레임만 읽고(버퍼 비움), `max_fps` 이하로 sightings POST. 스트림 끊김 → 재연결, 그동안 POST 없음.
4. 시험: `cv2.aruco.generateImageMarker`로 만든 합성 장면에서 위치 오차 ≤ 10 mm, yaw ≤ 2°. 코너 누락 → 무출력. 경계 시험: cv2는 `detect.py`에만.

**Stage 3 — Fleet 수신과 대조 표시**
1. `POST /api/fleet/sightings`, 어댑터 토큰 분리, 거절 규칙(§4), lease.
2. 스냅샷에 `sighting`, `divergence_m`. 콘솔 두 표시 + 경고.
3. 시험: 거절 규칙 각각, stale 회색, `test_no_video_relay.py` 녹색.

**Stage 4 — DEVICE (실물)**
1. 폰 거치, 코너 마커 실측 좌표 기입, 로봇 상단 마커 부착.
2. 로봇을 알려진 위치 5곳(주차 자리, 교차점 4곳)에 두고 sighting 오차 기록. 합격 초안: 위치 ≤ 30 mm, yaw ≤ 5°.
3. 로봇 1대 차선 주행 중 `divergence_m` 기록, 대역 사용량 측정(D-136 상한 안).
4. 기록을 `docs/validation/`에 남기고 D-257 Accepted 여부를 판정.

## 7. 범위 밖과 다음 결정

| 항목 | 막힌 이유 | 다음 |
|---|---|---|
| 차선 단위 지시("P1로", "전 차선 순회") | CORE가 실행 중 경로를 받는 API가 없다. 경로는 기동 인자 `route:=[...]`뿐 | CORE 원자 액션 설계 → 별도 ADR (D-12: 미션은 Fleet, 로봇은 원자 액션) |
| 구간 예약식 교통정리 | 차선 지시가 먼저 있어야 한다 | 위 ADR 뒤 |
| 폰 브라우저 내 인식 | HTTPS 인증서, JS 이식 | 폰 여러 대 또는 PC 없는 현장이 필요해질 때 |
| 폰을 관제 화면으로 | 이번 결정은 센서 역할 | 콘솔 모바일 레이아웃 점검(뷰포트·`@media`는 이미 있음) |
| sighting으로 로봇 위치 보정 | 안전·정책 경계를 바꾼다 | 실측 오차 데이터가 쌓인 뒤 ADR |

## 8. 열린 질문

1. 폰 거치 높이와 화각으로 트랙 전체가 한 화면에 들어오는가? (들어오지 않으면 폰 2대 → 출처 2개, 겹침 규칙 필요)
2. 로봇 상단에 마커를 붙일 평면 공간이 있는가? 크기는 몇 cm인가? (5 cm 미만이면 2 m에서 검출이 불안정할 수 있다 — 실측)
3. 현장 조명(백색 벽, 카펫 — 실물 카메라 조건)에서 ArUco 검출률은?
4. 어댑터 패키지 이름과 위치 (`src/site/overhead/`) — D-231 계층 규칙과 맞는가?
