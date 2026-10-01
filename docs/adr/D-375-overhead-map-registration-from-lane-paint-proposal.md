## D-375 천장 카메라→지도 보정도 제안일 뿐이다 — Vision이 알려진 차선 페인트를 영상에 맞춰 homography를 제안하고, 운용자가 확인하기 전에는 어디에도 쓰지 않는다

**Status:** Proposed (2026-09-30). D-360의 부록이다. 제안 위치(Vision), 제안 API, 품질·거부 기준, 가려진 쪽 보고, 관제 화면 표시·브라우저 표시 초안(6항, 2026-10-01 추가)만 정한다. 제안을 `site-cameras.yaml`·`CameraMap`·sighting 좌표에 반영하는 절차는 정하지 않는다. D-257·D-360을 바꾸지 않는다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(sighting은 표시 전용) · [D-261](D-261-overhead-camera-app-skeleton.md) · [D-360](D-360-overhead-field-auto-detection-proposal.md)(경기장 자동 검출은 제안) · [D-374](D-374-app-identity-follows-one-role-name.md)·D-377(패키지 `rosy_vision`, 와이어 이름 유지).

### Context

1. 지금 카메라→지도 보정은 ArUco 모서리 마커 30–33과 `corner_world_m`(자리표시 4.0×2.0 m)이 필요하다. 마커를 붙이고 실측해야 하고, 폰이 밀리면 다시 해야 한다.
2. 현장 트랙 `map_v2_fleet`의 흰 차선 페인트는 CAD(`meshes/road_lines.stl`, 지도 좌표 미터, `lane_graph.yaml`과 같은 좌표계)로 이미 있다. 트랙 외곽은 180° 돌려도 거의 같지만 페인트 배치는 비대칭이라 방향이 정해진다.
3. D-360의 네 모서리 제안은 벽 윤곽만 보므로 지도 좌표·방향을 주지 못한다.

### Decision

1. **Vision이 페인트를 맞춘다.** `src/site/vision/rosy_vision/map_register.py`(ROS 없음, OpenCV CPU): 흰 가는 선 마스크 → 카메라 기울기 가설(pitch·roll 0, ±20°, ±35°, 9개)마다 선 영상을 펴고 주 선 방향을 구한 뒤, 고정 해상도(약 3.3 cm/px) 지도 템플릿에 대해 영상을 배율마다 다시 뽑는 거친 탐색(90° 네 방향 × 배율, 거울은 기울기 0에서만) → 지도 래스터를 템플릿으로 한 ECC homography 정밀화 → 바닥 거리 기준 recall·precision 점수. 정밀화는 최선 후보와 함께 다른 방향(적어도 180° 돌린 것)의 최선 후보도 하므로 방향 차에는 늘 실제 경쟁자가 있다. 결정적이고, 요청 시 한 번 약 1.4–2.7 s(Windows 개발 PC, 부하 없을 때, 1280×720·4032×2268·세로 프레임)다. 다른 작업으로 CPU가 찼을 때는 같은 프레임이 4–10 s까지 걸렸다.
2. **API.** `GET /api/vision/sources/{id}/map-proposal`. D-360 field-proposal과 같은 lease·속도 제한(lease 주체·source마다 초당 1회)·`Cache-Control: no-store`·`nosniff`, 같은 404(프레임 없음·오래됨)/401/422 규칙. 계산은 수신 이벤트 루프와 떨어진 별도 작업 프로세스 하나(spawn, OpenCV 2 스레드, 가능하면 nice +10)에서 모든 source가 나눠 쓴다. source마다 한 번에 하나다. 실행 중에 온 읽기는 그 source의 마지막 성공 결과를 그 결과의 `frame_seq`·`frame_age_ms`와 헤더 `X-Proposal-State: previous`로 `200` 받고(새 결과는 `current`), 성공 결과가 아직 없으면 `429`(`Retry-After: 1`)다. 폰이 다시 붙어 캐시가 비워진 뒤 끝난 옛 연결의 계산은 이전 결과로 남기지 않는다. 다음 계산은 이전 계산이 끝나고 1 s 뒤부터다. 스레드에서 돌리면 GIL 때문에 수신 루프가 몇 초씩 멈춰 폰 hello가 시간 초과되고 프레임 읽기가 10–15 s 걸렸다(2026-10-01 실기 시험). 같은 프레임은 재계산하지 않고, 실패한 계산은 다음 계산 전까지 계속 422다. Vision을 `--map-paint <road_lines.stl>`로 띄우지 않으면 404 `site map paint not configured`.
   - `200` 본문: `{"source", "frame_seq", "frame_age_ms", "image", "map_frame": "map", "accepted", "proposal", "rejected_fit", "reason", "registrar": {"version", "elapsed_ms"}}`.
   - `proposal`(통과했을 때만): `image_to_map`·`map_to_image`(3×3, 전체 해상도 픽셀↔지도 미터), `score`(시야 안 페인트 중 선과 맞은 비율), `precision`(지도 안 흰 선 중 페인트와 맞은 비율), `coverage`(페인트 면적 중 프레임 안 비율), `cut_sides`(`+x`/`-x`/`+y`/`-y`), `cut_directions`(east/west/north/south), `side_outside`, `rotation_deg`(화면에서 지도 +x 방향, 반시계), `mirrored`, `orientation_margin`(비교할 다른 방향이 없으면 `null`).
   - `rejected_fit`(거부됐을 때의 최선 적합): `score`, `precision`, `coverage`, `cut_sides`, `cut_directions`, `side_outside`만. homography는 주지 않는다.
3. **거부는 이유와 함께.** 이 순서로 처음 걸리는 것: 시야 안 페인트 < 20 %, recall < 0.8, precision < 0.8, recall×precision < 0.75, 다른 방향과의 상대 점수 차 < 0.1 또는 비교 대상 없음, 거울상(잘 맞고 방향이 분명할 때만). 하나라도 걸리면 `accepted: false`와 이유를 준다. 가짜 homography를 `proposal`에 넣지 않는다. `rejected_fit`의 coverage·가려진 쪽은 설치 안내("카메라를 서쪽으로")에 쓸 수 있지만 좌표 변환에는 쓰지 않는다.
4. **hello 시간 초과는 재시도할 수 있는 닫힘이다.** 수신기는 hello를 기다린 시간을 루프가 실제로 응답하던 시간만 센다(0.25 s 단위, 한 단위를 최대 두 배로만 센다). 그래도 5 s 안에 hello가 없으면 1013(try again later)으로 닫는다. 앱은 4400·4409가 아닌 닫힘에서 백오프로 다시 붙는다. 4400은 hello가 실제로 틀렸을 때만 쓴다. 공유 프로토콜 벡터 `close_codes.hello_timeout`에 적었다.
5. **자동 적용하지 않는다.** 제안·거부 어느 쪽도 sighting 좌표, `CameraMap`, 작업 수락, 주행, `cmd_vel`에 쓰이지 않는다. D-360 3항과 같다.
6. **관제 화면은 보여 주고, 수락은 브라우저 표시 초안일 뿐이다.** Fleet은 `GET /api/fleet/site-lanes`(읽기 권한, 영상 없음, `--site-lane-graph`/`--site-lane-paint [MAP_ID=]PATH`, 시작할 때 한 번 만들고 `ETag`·`Cache-Control: private, no-cache`)로 `lane_graph.yaml` 중심선과 `road_lines.stl` 페인트 삼각형을 지도 좌표로 준다. 콘솔 "맵 자동 맞춤"은 같은 preview lease로 Vision 제안을 읽어 원본 위에 페인트·중심선을 겹치고, 영상을 지도 좌표 평면으로 펴 보여 준다. `429`와 `previous`는 오류가 아니라 "맞추는 중"이다. `previous`는 "이전 결과 · N s 전"으로 보여 주되 수락할 수 없고 최신 결과까지 다시 묻는다. 수락은 `current`이고 통과한 제안만 되며, source별 브라우저 `localStorage` 표시 초안(`map_id`·lane/paint 해시 포함)이 된다. 프레임 가로세로 비가 1 %를 넘게 다르거나 지도가 바뀐 초안은 늘여 맞추지 않고 쓰지 않는다. 경기장 자동 찾기(D-360)가 실패하고 수락한 초안이 있으면 경기장 뷰는 지도 사각형을 그 전체 homography로 편다(모서리가 프레임 밖이어도 된다, 0–100 % 모서리 조정값을 거치지 않는다). 초안도 5항처럼 어디에도 적용하지 않는다.

### Evidence levels

| 등급 | 이 ADR에서 뜻하는 것 |
|------|----------------------|
| SOURCE | CAD 페인트로 그린 합성 프레임(180° 회전·서쪽 잘림, pitch·roll 최대 30° 기울기와 회전·약한 통모양 왜곡, 거울상, 빈 바닥): 자세 오차·coverage·잘린 쪽 단언. 경로 lease·헤더 시험 |
| LOCAL | 저장한 실제 프레임(`private/`에만, 공개 저장소에 커밋하지 않음)과 기준 homography의 재투영 오차. 기준은 손으로 초기값을 준 ECC를 같은 페인트 템플릿에 맞춘 것이라 독립 측정이 아니다. 실측 점과의 비교는 FIELD다 |
| DEVICE | 설치된 폰 실시간 프레임에서 제안의 프레임 간 흔들림 |
| FIELD | 제안 → 운용자 수락 → 실측 점 대비 지도 오차 |

이 ADR은 SOURCE와 LOCAL까지만 주장한다. 2026-09-30 실험실 프레임 6장(180° 회전·서쪽 잘림, 옆 트랙이 보이는 넓은 시야, 약 30° 기울기, 현재 설치 위치 약 2.0 m·23° 기울기 2장)과 렌즈 비교 촬영 2장(표준·광각)은 모두 수락됐고, 기준 homography 대비 중앙 재투영 오차는 4.4–7.6 px(1280×720, p90 6.6–16.5 px)다. 같은 프레임을 잘라 만든 부분 시야 45장 중 26장이 수락됐고 중앙 오차는 최대 19 px로, 부분 시야는 약 5 cm까지 어긋날 수 있다(17–21 px). 옆 트랙만 보이는 자른 영상, 로터리만 보이는 영상, 좌우 반전 영상, 무작위 선 25장은 모두 거부됐다(잘못된 수락 없음). 합성 시험은 각 거부 기준을 끄면 실패한다. 실기 프레임(`rx_live7`, 2°)은 원본·JPEG 품질 40·30·20으로 다시 인코딩해도 수락되지만, 품질 30에서 recall 0.807·곱 0.763으로 기준(0.8·0.75)에 가깝다. 부분 시야의 5 cm 오차를 숫자로 알리는 잔차 필드는 아직 없다.

### Alternatives

- **ArUco 모서리 마커 유지.** 정밀 보정용으로 남긴다. 설치·실측이 필요해 설치 안내용 첫 보정에는 무겁다.
- **D-360 네 모서리로 homography.** 벽 윤곽의 180° 대칭 때문에 방향을 정할 수 없고 지도 좌표 원점도 없다.
- **ECC만으로 맞춤.** 초기값이 가까울 때만 수렴한다. 방향·배율을 찾는 거친 탐색이 먼저 필요하다.
- **특징점(ORB 등) 매칭.** 흰 선 도면에는 반복 구조가 많아 대응이 불안정하다.

### Not decided

- 제안을 버전 있는 사이트 보정 프로필로 올리는 절차·권한, `CameraMap` 반영.
- 35°를 넘는 기울기, 트랙 일부(예: 동쪽 루프만)만 보이는 시야에서의 수락. 지금은 방향 차 부족으로 거부한다.
- 렌즈 왜곡 보정 모델. 지금은 homography가 흡수할 수 있는 약한 왜곡만 다룬다.
- 실제 트랙과 CAD의 국소 차이(루프 모양 등 수 cm)를 지도 쪽에서 고칠지.
- 브라우저 표시 초안을 여러 운용자·브라우저가 나눠 쓰는 방법(지금은 브라우저마다 따로다).

### Validation

- `python -m pytest src/site/vision/test -q`: `test_map_register.py`, `test_map_proposal_route.py`.
- `python -m pytest src/site/fleet/test -q`: `test_site_lanes_api.py`; `node --test src/site/fleet/test/web/*.test.mjs`: `map-fit.test.mjs`(수락 조건·이전 결과·해상도/지도 변경·부호). `test/test_site_map_fit_deploy.py`(이미지·compose·빌드 컨텍스트).
- LOCAL: 실제 프레임과 기준 homography 비교 결과는 `private/validation/`에 둔다.

### References

[D-257](D-257-site-lane-map-and-overhead-sightings.md), [D-261](D-261-overhead-camera-app-skeleton.md), [D-360](D-360-overhead-field-auto-detection-proposal.md), [D-374](D-374-app-identity-follows-one-role-name.md), `src/runtime/sensing/map/map_v2_fleet/README.md`.
