## D-375 천장 카메라→지도 보정도 제안일 뿐이다 — Vision이 알려진 차선 페인트를 영상에 맞춰 homography를 제안하고, 운용자가 확인하기 전에는 어디에도 쓰지 않는다

**Status:** Proposed (2026-09-30). D-360의 부록이다. 제안 위치(Vision), 제안 API, 품질·거부 기준, 가려진 쪽 보고만 정한다. 제안을 `site-cameras.yaml`·`CameraMap`·sighting 좌표에 반영하는 절차는 정하지 않는다. D-257·D-360을 바꾸지 않는다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(sighting은 표시 전용) · [D-261](D-261-overhead-camera-app-skeleton.md) · [D-360](D-360-overhead-field-auto-detection-proposal.md)(경기장 자동 검출은 제안) · [D-374](D-374-app-identity-follows-one-role-name.md)·D-377(패키지 `rosy_vision`, 와이어 이름 유지).

### Context

1. 지금 카메라→지도 보정은 ArUco 모서리 마커 30–33과 `corner_world_m`(자리표시 4.0×2.0 m)이 필요하다. 마커를 붙이고 실측해야 하고, 폰이 밀리면 다시 해야 한다.
2. 현장 트랙 `map_v2_fleet`의 흰 차선 페인트는 CAD(`meshes/road_lines.stl`, 지도 좌표 미터, `lane_graph.yaml`과 같은 좌표계)로 이미 있다. 트랙 외곽은 180° 돌려도 거의 같지만 페인트 배치는 비대칭이라 방향이 정해진다.
3. D-360의 네 모서리 제안은 벽 윤곽만 보므로 지도 좌표·방향을 주지 못한다.

### Decision

1. **Vision이 페인트를 맞춘다.** `src/site/vision/rosy_vision/map_register.py`(ROS 없음, OpenCV CPU): 흰 가는 선 마스크 → 카메라 기울기 가설(pitch·roll 0, ±20°, ±35°, 9개)마다 선 영상을 펴고 주 선 방향을 구한 뒤, 고정 해상도(약 3.3 cm/px) 지도 템플릿에 대해 영상을 배율마다 다시 뽑는 거친 탐색(90° 네 방향 × 배율, 거울은 기울기 0에서만) → 지도 래스터를 템플릿으로 한 ECC homography 정밀화 → 바닥 거리 기준 recall·precision 점수. 결정적이고, 요청 시 한 번 약 1.2–2 s(Windows 개발 PC)다.
2. **API.** `GET /api/vision/sources/{id}/map-proposal`. D-360 field-proposal과 같은 lease·속도 제한(lease 주체·source마다 초당 1회)·`Cache-Control: no-store`·`nosniff`, 같은 404(프레임 없음·오래됨)/401/422 규칙. source마다 초당 최대 1회만 계산하고 같은 프레임은 재계산하지 않는다. Vision을 `--map-paint <road_lines.stl>`로 띄우지 않으면 404 `site map paint not configured`.
   - `200` 본문: `{"source", "frame_seq", "frame_age_ms", "image", "map_frame": "map", "accepted", "proposal", "rejected_fit", "reason", "registrar": {"version", "elapsed_ms"}}`.
   - `proposal`(통과했을 때만)과 `rejected_fit`(거부됐을 때의 최선 적합)은 같은 모양: `image_to_map`·`map_to_image`(3×3, 전체 해상도 픽셀↔지도 미터), `score`(시야 안 페인트 중 선과 맞은 비율), `precision`(지도 안 흰 선 중 페인트와 맞은 비율), `coverage`(페인트 면적 중 프레임 안 비율), `cut_sides`(`+x`/`-x`/`+y`/`-y`), `cut_directions`(east/west/north/south), `side_outside`, `rotation_deg`(화면에서 지도 +x 방향, 반시계), `mirrored`, `orientation_margin`.
3. **거부는 이유와 함께.** 시야 안 페인트 < 20 %, recall < 0.8, precision < 0.8, 다른 방향과의 상대 점수 차 < 0.1, 거울상 중 하나면 `accepted: false`와 이유를 준다. 가짜 homography를 `proposal`에 넣지 않는다. `rejected_fit`의 coverage·가려진 쪽은 설치 안내("카메라를 서쪽으로")에 쓸 수 있지만 좌표 변환에는 쓰지 않는다.
4. **자동 적용하지 않는다.** 제안·거부 어느 쪽도 sighting 좌표, `CameraMap`, 작업 수락, 주행, `cmd_vel`에 쓰이지 않는다. D-360 3항과 같다.

### Evidence levels

| 등급 | 이 ADR에서 뜻하는 것 |
|------|----------------------|
| SOURCE | CAD 페인트로 그린 합성 프레임(180° 회전·서쪽 잘림, pitch·roll 최대 30° 기울기와 회전·약한 통모양 왜곡, 거울상, 빈 바닥): 자세 오차·coverage·잘린 쪽 단언. 경로 lease·헤더 시험 |
| LOCAL | 저장한 실제 프레임(`private/`에만, 공개 저장소에 커밋하지 않음)과 손으로 맞춘 기준 homography의 재투영 오차 |
| DEVICE | 설치된 폰 실시간 프레임에서 제안의 프레임 간 흔들림 |
| FIELD | 제안 → 운용자 수락 → 실측 점 대비 지도 오차 |

이 ADR은 SOURCE와 LOCAL까지만 주장한다. 2026-09-30 실험실 프레임 6장(180° 회전·서쪽 잘림, 옆 트랙이 보이는 넓은 시야, 약 30° 기울기, 현재 설치 위치 약 2.0 m·23° 기울기 2장)은 모두 수락됐고, 손으로 맞춘 기준 homography 대비 중앙 재투영 오차는 3.6–6.6 px(1280×720, p90 5.9–15.7 px)다. 옆 트랙만 보이는 자른 영상, 로터리만 보이는 영상, 좌우 반전 영상은 모두 거부됐다(잘못된 수락 없음).

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
- 관제 화면 표시·확인 UI.

### Validation

- `python -m pytest src/site/vision/test -q`: `test_map_register.py`, `test_map_proposal_route.py`.
- LOCAL: 실제 프레임과 기준 homography 비교 결과는 `private/validation/`에 둔다.

### References

[D-257](D-257-site-lane-map-and-overhead-sightings.md), [D-261](D-261-overhead-camera-app-skeleton.md), [D-360](D-360-overhead-field-auto-detection-proposal.md), [D-374](D-374-app-identity-follows-one-role-name.md), `src/runtime/sensing/map/map_v2_fleet/README.md`.
