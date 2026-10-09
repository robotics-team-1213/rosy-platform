## D-587 천장 카메라가 이름을 아는 로봇 마커는 sighting이 된다 — 승인 보정으로 투영한 마커 자세가 D-494 지도 자세를 잡는다

**Status:** Proposed (2026-10-10, 사용자 지시: 현장 천장 마커 로봇이 실제 Fleet 지도 자세를 얻어 D-517 권한과 D-525 가상 신호가 정지선에서 세울 수 있게). SOURCE 변경과 호스트 테스트만이다. 사이트 배포, 설정 설치, 현장 주행 수용은 이 기록이 하지 않는다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(sighting 계약, source 토큰) · [D-457](D-457-overhead-marker-priority-and-markerless-fallback.md)(천장 마커 우선, 승인 추론 보정) · [D-484](D-484-field-boundary-auto-calibration.md)(`calibration_source`) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 3항(sighting이 앵커, odom이 다리) · [D-397](D-397-pinky-geometry-urdf-nominal-calibration-refines.md)(URDF 명목, 보정이 다듬음) · [D-560](D-560-rosy-cam-map-plane-fleet-draws-on-it.md)(Vision이 승인 보정으로 편다) · [D-562](D-562-ceiling-marker-id-equals-robot-number.md)(마커 id = 로봇 번호, 40 mm 스티커, 검정 30 mm) · [D-564](D-564-ceiling-place-markers-teach.md)(`heading_edge`, 같은 source 토큰) · [D-575](D-575-ceiling-marker-seen-is-shown.md)(미배정 마커는 `unknown`). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

2026-10-10 00:20 현장(Fleet 이미지 `51f0231`):

- `GET /api/fleet/tracking`은 `rosy_40`, `rosy_41`을 `ceiling_north`의 `MARKER`로 보인다. 보정은 승인 추론 보정 `paint-7b220d432c2a`다.
- `GET /api/fleet/sightings`는 비어 있고, `GET /api/fleet/guide`는 두 대 모두 `POSE_UNKNOWN`이다.

코드에서 확인한 원인:

1. D-494 `MapPoseService`는 `SightingService.accept`가 받은 sighting으로만 앵커를 잡는다. D-457 추적은 입력이 아니다(`fleet/localization/map_pose.py`).
2. Vision의 sighting은 `project.project_frame`만 만든다. 이 함수는 그 프레임에서 잰 호모그래피(모서리 마커 네 개, 또는 D-484 경계 사각형)가 있을 때만 sighting을 낸다. 현장 설정은 `calibration_source: field_boundary`이고, 경계의 먼 쪽이 화면 밖이라(D-560) 그 호모그래피가 없다. Vision 로그에 sighting 거절도 없다. 아예 보내지 않는다.
3. 추적 단계(`track/worker.py`)는 승인 보정으로 로봇 마커 중심을 지도에 투영하고 시차도 보정한다. 그러나 결과는 방향 없는 익명 검출(`OverheadDetection`)뿐이다. `tracking_calibration.py`는 "승인 기록은 sighting 보정이 아니다"라고 적는다.
4. Fleet `SightingService`는 sighting의 `calibration_revision`이 설정 파일의 고정 revision(`map_v2_fleet`)과 같아야 받는다. 승인 기록의 revision(`paint-…`)은 받을 길이 없다.

**실측(2026-10-10 01:15–01:25, 현장 원본 프레임 150장, 로봇 정지).** 저장소 검출기(`detect_markers`)와 승인 보정, 렌즈 hfov 67.8°로 계산했다. 원본 프레임은 저장소 밖 작업 폴더에 있다(공개 저장소).

| 마커 | 읽힘 | 위치 표준편차 | 방향 표준편차(중심→앞 변) | 최대 벗어남 | 짧은 변 | 지도 위 한 변 |
|---|---|---|---|---|---|---|
| 40 | 150/150 | < 0.1 mm | 0.09° | — | 11–12 px | 0.0255–0.0281 m |
| 41 | 148/150 | 0.3 mm | 0.57° | 1.8° | 7–8.5 px | 0.0263–0.0284 m |

- 카메라는 바닥에서 약 1.94 m, 바로 아래 점은 지도 (1.05, −0.44)다(승인 보정과 렌즈에서 계산).
- 네 변을 모두 쓰는 방향 추정은 표준편차가 0.37°/0.71°로 오히려 컸다. 그래서 중심→앞 변 중점을 쓴다(D-564와 같은 식).

### Decision

1. **이름을 아는 로봇 마커만 sighting이 된다.** Vision 추적 단계가 승인 보정(D-457 1)으로 프레임을 투영했으면, 그 프레임에서 읽힌 마커 가운데 `robot_markers`에 있고 `marker_yaw_offset_deg`가 설치된 로봇의 마커마다 `SiteSightingPayload`를 하나 만든다(4항). 기존 sighting 경로(`POST /api/fleet/sightings`, source 토큰, map·revision 검사, 1 s lease, 순서)를 그대로 쓴다. 새 자세 채널은 만들지 않는다.
   - 배정 안 된 마커(D-575 40–49 미배정), 익명 덩어리, 장소·모서리 마커는 sighting이 되지 않는다. 로봇 이름은 여전히 `robot_markers` 대응으로만 정한다(D-457 2).
   - 같은 프레임에서 `project_frame`이 이미 그 로봇의 sighting을 Fleet에 보냈으면(모서리 마커·경계 사각형 측정) 추적 단계는 그 로봇을 다시 보내지 않는다. 보내기에 실패한 것은 추적 단계가 보낸다.
   - 어느 보정을 썼는지는 추적 단계가 고른 갈래로 정한다. 모서리 마커 측정이면 보내지 않는다(`project_frame` 몫). revision 문자열 비교로 정하지 않는다.
   - sighting은 추적 검출 전송보다 먼저 보낸다. 검출 전송이 늦어도 sighting이 Fleet의 1 s lease 안에 닿게 하기 위해서다. sighting 실패는 로그만 남기고 검출 전송을 막지 않는다.
2. **새 `calibration_source: "approved_record"`.** 이 sighting은 `corner_marker_ids: null`, `calibration_source: "approved_record"`, `calibration_revision`에 승인 기록의 revision을 싣는다. Fleet은 그 revision이 지금 그 source의 승인 기록(같은 `map_id`)과 같을 때만 받는다. 다르거나 기록이 없으면 409 `CALIBRATION_MISMATCH`다. 다른 `calibration_source` 값의 검사는 그대로다. D-457 1과 `tracking_calibration.py`의 "기록은 sighting 보정이 아니다"는 이 항목만큼 고친다. 익명 검출은 여전히 sighting이 아니다.
3. **마커 자세.**
   - 마커의 네 모서리를 승인 보정으로 지도에 투영한다. 그다음 마커 높이만큼 카메라 바로 아래 점 쪽으로 당긴다(D-457 3의 시차 보정, `geometry.parallax_correct`).
   - 마커 높이는 따로 둔 상수 `MARKER_HEIGHT_M`(`rosy_vision/project.py`)이다. 명목은 `geometry.yaml` `lidar.height_m`이고 드리프트 시험이 묶는다. 덩어리 실루엣용 `ROBOT_TOP_HEIGHT_M`(`track/model.py`)과 나누어, 잰 스티커 높이로 이것만 다듬을 수 있다.
   - 위치는 네 점의 평균이다. 방향은 중심에서 `heading_edge` 중점으로 가는 방향이다(D-564와 같은 식, D-562 스티커 윗변 = 로봇 앞).
   - 렌즈 hfov가 없거나 카메라 자세를 풀 수 없으면 시차를 보정할 수 없다. 그 프레임은 sighting을 내지 않는다. 표시용 추적 검출은 지금처럼 나간다.
4. **로봇 자세 = 마커 자세 ∘ 부착 오프셋.**
   - 명목 부착은 URDF다(D-397). 스티커 중심은 로봇 윗면의 LiDAR 위(`geometry.yaml` `lidar.x_m` −0.017, `y_m` 0), 높이는 3항의 `MARKER_HEIGHT_M` 0.125 m다.
   - 방향 오프셋은 로봇마다 `site-cameras.yaml` source의 `marker_yaw_offset_deg: {rosy_41: 180}`으로 설치한다. 값은 로봇 앞 기준으로 잰 스티커 윗변 방향이다(반시계 +, 도). 키는 그 source `robot_ids`의 로봇이어야 하고(D-580 `robot_ids: enrolled`이면 아무 로봇 id), 값은 유한하며 절댓값 360 이하다. Vision과 Fleet이 같은 검사(`core_common.protocol.sightings.check_marker_yaw_offsets`)를 쓴다.
   - **오프셋이 설치되지 않은 로봇은 `approved_record` sighting을 내지 않는다.** 재지 않은 스티커는 90°나 180° 틀려도 매 프레임 똑같이 틀리므로 D-494의 20° 점프 문턱이 잡지 못한다. 0°도 잰 값으로 설치해야 한다. `project_frame` 경로는 지금처럼 0°를 기본으로 쓴다.
   - 로봇 방향 = 마커 방향 − 오프셋이다. 로봇 위치 = 마커 위치 − R(로봇 방향)·(−0.017, 0)이다.
   - 위치 오프셋은 로봇별로 받지 않는다. 명목에서 어긋나도 스티커가 윗면(반지름 약 0.03 m) 안에 있으니 오차는 그 크기다. 필요하면 별도 ADR에서 제자리 회전 원 맞추기로 다룬다.
   - 같은 오프셋과 부착은 `project_frame` 경로(모서리 마커·경계 사각형)에도 적용한다. 로봇 자세의 정의를 하나로 두기 위해서다. 그 경로는 렌즈를 몰라 시차 보정이 없고, 6항 품질 문턱도 걸지 않는다. 이것은 지금 그대로다.
5. **보정 단계(방향 오프셋).** `tools/calibration/ceiling_marker_yaw.py`를 쓴다. sighting 없이 시작할 수 있어야 하므로(4항) 원본 프레임에서 직접 잰다.
   - 운영자는 로봇을 앞으로 곧게 0.3 m 이상 몬다(관제 수동 주행 또는 CORE 대시보드).
   - 도구는 그동안 viewer lease로 원본 프레임을 읽고, 그 로봇 마커를 검출해 승인 기록과 sighting과 같은 시차·품질 문턱(`track.marker_sightings.marker_pose`)으로 마커 자세를 낸다. 마커 위치들의 주축과 시간 순서로 진행 방향을 정하고, 마커 방향과의 원형 평균 차이를 낸다. 그 차이가 곧 오프셋이다.
   - Vision 컨테이너 안(`docker exec -i … python3 - … < ceiling_marker_yaw.py`)이나 저장소의 Vision 경로를 `PYTHONPATH`에 둔 PC에서 돈다. 토큰은 `ROSY_FLEET_TOKEN`이다.
   - 출력은 `marker_yaw_offset_deg`에 넣을 값(0.1°)과 가장 가까운 90° 배수다.
   - 거절 조건: 이동이 0.25 m 미만, 직선에서 벗어남 0.02 m 초과, 방향 흩어짐 5° 초과, 표본 5개 미만.
   - 기준은 odom 방향이 아니라 진행 방향이다. odom 방향은 odom 좌표계 기준이라 지도 방향과의 차이를 모른다. 앞으로 곧게 가는 동안 진행 방향이 곧 로봇 앞이다.
   - 결과는 사이트 설정에 저장한다. 로봇의 D-47 보정 저장소는 로봇에 달린 센서의 기록이고, 스티커는 사이트 카메라가 읽으므로 사이트 설정이 그 주인이다.
6. **품질 문턱.** 다음을 모두 통과한 마커만 보낸다. 통과한 sighting의 `quality`는 `null`이다.
   - 네 모서리가 유한하고 볼록하다.
   - 영상에서 가장 짧은 변이 6 px 이상이다. 실측 41은 7 px까지 내려갔고 방향 흩어짐은 0.6°였다.
   - 시차 보정 뒤 지도 위 한 변 평균이 D-562 검정 30 mm의 0.6–1.4배다. 실측은 0.91배다.
   - 마주 보는 두 변 쌍의 길이 비가 0.75–1.33이다.
   - 위치가 승인 보정의 `track_bounds_m` 안이다.
7. **권한과 수명.** sighting은 D-257·D-494 그대로 쓰인다. 표시와 D-494 지도 자세 앵커다. trip·D-517 권한·D-525 신호는 그 지도 자세를 읽는다. Vision은 로봇에 아무것도 보내지 않는다. 마커가 프레임에서 빠지면 D-494의 odom 다리와 앵커 나이 한도가 그대로 적용된다.

### 오차 한도

- **스티커 높이.** 명목 0.125 m는 LiDAR 주사면 높이다. 스티커가 LiDAR 덮개 위면 실제로는 약 0.02–0.03 m 높다. 수평 오차는 (카메라 바로 아래 점에서 거리) × Δh / 카메라 높이다. 현장 값(높이 1.94 m)이면 바로 아래 점에서 1 m일 때 약 1.5 cm이고, 지도 가장 먼 모서리(약 2.7 m)에서 약 4 cm다. 높이 보정을 아예 하지 않으면 1 m에서 6.4 cm다.
- **승인 보정.** 위치 정확도는 승인 추론 보정(D-457 1, `fit_score` 0.827)의 정확도를 넘지 못한다. 보정이 바뀌면 revision이 바뀌고, 옛 revision의 sighting은 409다.
- **렌즈 왜곡.** D-515와 같이 모델로 다루지 않는다.
- D-494 `max_jump_m` 0.15 m, `max_jump_deg` 20°는 위 오차와 실측 흩어짐보다 크다.
- **불확실도.** D-494는 sighting마다의 시그마를 받지 않는다. `quality`는 `null`이다. 최악 위치 오차는 스티커 높이 약 4 cm에 승인 보정의 페인트 맞춤 잔차(중앙값 0, p90 18 mm, rosy-dd 측정)를 더한 약 6 cm다. 이것은 `max_jump_m` 0.15 m보다 작다. 시그마를 계약에 싣는 일은 소비자(D-494 추적기)가 그것을 쓸 때 별도 ADR로 한다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 익명 추적 검출(`OverheadDetection`)을 D-494 앵커로 쓴다 | 기각. 이름과 방향이 없다. D-457 5는 이름을 지도 자세로 대조하는데, 앵커가 그 자세를 만들면 순환이다 |
| 새 마커 자세 경로(`/api/fleet/marker-poses` 등) | 기각(사용자). 인증·revision·lease·순서를 다시 만든다 |
| 설정의 `calibration_revision`을 승인 기록 revision으로 손으로 맞춘다 | 기각. 보정을 다시 승인할 때마다 설정 설치가 필요하고, `field_boundary` 검사와 섞인다 |
| 네 변 평균 방향 | 기각. 실측 흩어짐이 중심→앞 변보다 컸다 |
| odom 방향과 마커 방향을 바로 비교하는 보정 | 기각. odom 좌표계와 지도의 방향 차이를 모른다. 진행 방향을 쓴다 |
| 로봇별 위치 오프셋 설정 | 보류. 오차가 윗면 크기 안이다 |

### Consequences

- 승인 보정이 있는 현장에서는 마커가 읽히는 동안 로봇마다 약 2.7 Hz(현장 추적 fps)로 sighting이 나간다. D-494 `RECOVER_AFTER` 2개를 지나면 지도 자세가 `LOCALIZED`가 된다.
- 스티커가 90°나 180° 돌아 붙어 있으면 지도 방향도 그만큼 틀린다. 첫 주행 전에 5항 보정을 하고 `marker_yaw_offset_deg`를 설치한다. 그 전까지 trip을 열지 않는다.
- `site-cameras.yaml`의 새 키는 이 변경이 든 Vision·Fleet만 읽는다. 옛 이미지는 모르는 키라며 시작을 거절한다. 릴리스를 먼저 하고 설정을 설치한다.
- API는 additive다(`calibration_source` 값 하나).
- 검증: `operations/vision/test/test_marker_sightings.py`(투영, 시차, 오프셋, 품질 문턱, 미배정 미전송, 이중 전송 없음), `operations/fleet/test/test_sightings_api.py`(승인 revision 수락과 409), `tools/calibration/test/test_ceiling_marker_yaw.py`(진행 방향 추정과 거절).
