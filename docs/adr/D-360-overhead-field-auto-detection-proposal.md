## D-360 천장 카메라 경기장 자동 검출은 제안일 뿐이다 — Vision이 네 모서리를 제안하고, 관제는 운용자가 확인한 모서리로 보정·마스킹한 경기장 뷰를 보여 준다

**Status:** Proposed (2026-09-30). 검출 위치(Vision), 제안 API, 설정값과 검출값이 어긋날 때의 표시, 관제 레이어 토글만 정한다. 검출 결과를 사이트 설정(`site-cameras.yaml`)·sighting 좌표·주행에 반영하는 일은 결정하지 않는다. D-257·D-318을 바꾸지 않는다.

**번호:** 처음 D-354로 적었으나 main에 다른 D-354(mDNS 서비스 발견)가 먼저 착지해 2026-09-30 병합 때 D-360으로 옮겼다. 그 전 로그 항목의 "D-354 경기장 제안"은 이 ADR을 가리킨다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(sighting은 표시 전용) · [D-261](D-261-overhead-camera-app-skeleton.md)(폰 → Vision 수신기, Fleet은 영상을 받지 않음) · [D-318](D-318-site-camera-preview-rectification.md)(미리보기 보정, 모서리 직접 조작, 브라우저 로컬 초안) · D-341(천장 카메라 앱 페어링, 브랜치 `docs/d341-overhead-console-pairing`).

### Context

1. 천장 카메라(현장에서는 S21)가 트랙 위에서 source `s21`로 Vision에 JPEG를 보낸다. 운용자는 D-318의 모서리 네 개를 손으로 끌어 경기장 사각형을 맞춘다. 경기장은 회색 카펫 위에 흰 벽과 흰 테이프로 둘러싸여 있어, 이미지에서 경계가 뚜렷하다. 손으로 네 점을 찾는 일은 느리고, 폰 위치가 바뀔 때마다 다시 해야 한다.
2. 관제 화면의 "현장 지도"는 `/api/fleet/site-map`의 설정 W×H(미터)로 사각형을 그린다. 카메라에 보이는 경기장의 가로세로 비와 설정값이 다르면 지도와 영상이 어긋나는데, 지금은 이 차이를 알려 주지 않는다. 설정이 비어 있으면 빈 지도만 보인다.
3. Fleet은 영상을 받지 않는다(D-275, D-293, `test_no_video_relay.py`). 영상 처리는 이미 JPEG를 가진 Vision이 한다(D-318 1항).

### Decision

1. **검출은 Vision에서만 한다.** Vision이 최신 원본 프레임에서 경기장 경계(흰 영역·경계선 → 윤곽 → 사각형 근사 → 볼록성·면적·가로세로 비 검사 → 서브픽셀 정밀화)를 찾는다. Fleet은 영상 바이트도, 검출 결과도 중계하지 않는다. `test_no_video_relay.py`는 계속 통과해야 한다.
2. **API.** `GET /api/vision/sources/{id}/field-proposal`. frame 경로와 같은 단기 미리보기 lease(Bearer), 같은 방식의 요청 속도 제한(제안은 frame과 따로 세는 칸에서 lease 주체·source마다 초당 1회), 같은 `Cache-Control: no-store`·`X-Content-Type-Options: nosniff`를 쓴다. Caddy의 기존 `/api/vision/sources/*` 경로로 same-origin이 되므로 새 프록시 규칙이 없다. 응답은 JSON이다.
   - 경기장을 찾으면 `200` 과 `{"source", "frame_seq", "frame_age_ms", "image": {"width", "height"}, "proposal": {"corners": [[x,y]×4], "corners_normalized": [[u,v]×4], "confidence", "aspect_ratio", "shape": "square"|"rectangle"}, "detector": {"version", "elapsed_ms"}}`.
   - 경기장을 못 찾으면 `200`과 `"proposal": null`, `"reason"`을 준다. 가짜 모서리를 만들지 않는다.
   - 모서리 순서는 이미지 기준 좌상·우상·우하·좌하로 고정한다. D-318의 `corners` 순서와 같다.
   - 프레임이 없거나 오래되면 frame 경로와 같은 `404`, lease가 틀리면 `401`, 프레임을 풀 수 없으면 `422`다. 같은 프레임(seq)에 대한 반복 요청은 검출을 다시 돌리지 않는다.
3. **제안은 자동 적용되지 않는다.** 관제는 제안을 D-318 모서리 핸들에 "제안"으로 싣고, 운용자가 확인(수락)해야 초안이 된다. 수락한 모서리도 D-318처럼 브라우저 로컬 초안이다. 제안·수락 어느 쪽도 sighting 좌표, `CameraMap` homography, 작업 수락, 주행, `cmd_vel`에 쓰이지 않는다.
4. **보정·마스킹한 경기장 뷰.** 관제는 확인했거나 제안된 모서리로 원본 미리보기를 캔버스에서 위에서 본 모양으로 펴고(원근 변환), 경기장 밖은 가린다. 이 뷰는 표시 전용이며 "미리보기 조정" 표시를 유지한다(D-318 3항).
5. **설정값과 검출값의 불일치.** 관제는 `/api/fleet/site-map`의 설정 W×H 비와 검출된 가로세로 비를 비교한다. 차이가 허용치(초기값 10%)를 넘거나 설정이 비어 있으면, 빈 지도 대신 "설정 W×H와 카메라에 보이는 경기장 비가 다르다"는 안내를 두 값과 함께 보여 준다. 관제는 설정을 고치지 않는다.
6. **운용자 W×H 입력.** 운용자는 표시 축척용으로 경기장 W×H(미터)를 입력할 수 있다. 값은 D-318처럼 source별 브라우저 로컬에만 저장한다. `site-cameras.yaml`이나 사이트 설정을 다시 쓰지 않는다.
7. **레이어 토글.** 관제 카메라 패널은 원본 카메라, 보정 경기장, 사이트 사각형, 격자, 카메라 sighting, CORE 로봇 자세를 켜고 끌 수 있다. 상태는 localStorage에 저장하되 읽기·쓰기를 try/catch로 감싸고, 저장소가 없어도 기본값으로 동작한다. 인라인 스크립트는 쓰지 않는다(CSP).

### Evidence levels

등급은 이 ADR 안에서 정한다. 다른 브랜치의 ADR을 인용하지 않는다.

| 등급 | 이 ADR에서 뜻하는 것 |
|------|----------------------|
| SOURCE | 합성 이미지 시험(원근 사각형, 잡음, 부분 가림, 경기장 없음), API lease·헤더 시험, 순수 JS 도우미 Node 시험, Fleet 무영상 시험 |
| LOCAL | 저장된 실제 프레임을 수신기 프로토콜로 재생해 Vision·Fleet·관제를 로컬에서 돌린 결과. 실제 프레임은 공개 저장소에 커밋하지 않고 `private/`에만 둔다 |
| DEVICE | 설치된 폰이 실시간으로 보내는 프레임에서 제안이 안정적인지(프레임 간 모서리 흔들림, 조명 변화) |
| FIELD | 제안 → 운용자 수락 → 실측 경기장 치수와의 오차 측정 |

이 ADR의 첫 구현은 SOURCE와 LOCAL까지만 주장한다.

### Alternatives

- **Fleet에서 검출한다.** 거부한다. Fleet이 영상을 받아야 하므로 D-275·D-293과 `test_no_video_relay.py`가 깨진다.
- **브라우저에서 검출한다.** 거부한다. 관제 화면마다 OpenCV급 처리가 필요하고, 결과가 화면마다 달라진다. 다만 표시용 원근 변환(4항)은 브라우저 캔버스에서 한다. 변환 행렬 계산만 하고 영상 분석은 하지 않는다.
- **검출 결과를 바로 적용한다.** 거부한다. 흰 물체·반사·사람 발에 속은 제안이 운용자 확인 없이 지도에 들어가면 안 된다. D-257의 표시 전용 원칙과도 맞지 않는다.
- **ArUco 마커 네 개로 경기장을 잡는다.** 지금은 보류한다. 마커 설치가 필요하고, 흰 벽이라는 현장 특성을 쓰면 설치물 없이 된다. 정밀 보정 단계에서 다시 볼 수 있다.

### Consequences

- 운용자는 모서리를 처음부터 찾지 않고, 제안을 확인하고 조금 고치면 된다.
- Vision에 요청당 CPU 비용이 생긴다. 관제는 제안을 운용자가 요청할 때나 드물게만 부른다. 같은 lease 속도 제한이 걸린다.
- 설정 불일치가 화면에 드러나므로, 설정 W×H를 실측해 고치는 절차가 따로 필요해진다(아래 "정하지 않은 것").

### Not decided

- 검출된 모서리를 버전 있는 사이트 보정 프로필로 올리는 절차와 그 권한.
- 제안을 sighting 좌표 변환이나 `CameraMap`에 쓰는 일. 쓰려면 별도 ADR과 FIELD 증거가 필요하다.
- 설정 W×H 불일치 허용치의 최종값, 설정을 고치는 주체와 절차.
- 여러 카메라가 한 경기장을 나눠 볼 때의 제안 병합.
- 렌즈 왜곡이 큰 카메라에서 곡선 경계를 다루는 방법. 지금은 사각형 근사가 실패하면 제안하지 않는다.
- 주기적 자동 재검출(카메라가 밀렸을 때 경고)을 할지 여부.

### Validation

- `python -m pytest src/site/overhead/test -q`: 합성 이미지 검출 시험과 field-proposal 경로 lease·헤더 시험.
- `src/site/fleet/test`: `test_no_video_relay.py` 통과, 관제 순수 도우미 Node 시험.
- LOCAL: 저장된 실제 프레임 재생으로 모서리·신뢰도·처리 시간을 기록한다. 증거는 `private/validation/`에 둔다.

### References

[D-257](D-257-site-lane-map-and-overhead-sightings.md), [D-261](D-261-overhead-camera-app-skeleton.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-293](D-293-site-fleet-intent-api-contracts.md), [D-318](D-318-site-camera-preview-rectification.md), D-341.
