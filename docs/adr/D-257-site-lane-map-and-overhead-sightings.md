## D-257 사이트 관제 지도는 차선 그래프다 — 로봇 위치는 폰 천장 카메라가 보고, 영상은 Fleet 밖에서만 처리한다

**Status:** Proposed (2026-09-26). 설계 방향이다. 구현 GO나 DEVICE 승격이 아니다.

잇는 결정: [D-12](../reference/ROSY%20ADR%20Log.md) · [D-94](D-94-rosy-games-opencv-d-41.md) · [D-95](D-95-device-observer-hold.md) · [D-100](D-100-aruco-m.md) · [D-136](D-136-.md) 3·5항 · [D-152](D-152-core-1-preview.md) 4항 · [D-210](D-210-field-ready-scope-2robot-console-follow.md) · [D-249](D-249-fieldmap-spec-no-extraction.md).

**Context (실측):**

1. Fleet 콘솔(`src/site/fleet/fleet/server/`)의 지도는 로봇이 준 Nav2 점유격자다(`GET /api/fleet/map`, `console.js` `paintGrid`). 목표는 map 좌표 `(x, y, yaw)` 클릭이다.
2. 현장이 쓰는 지도는 차선 네트워크 `src/runtime/sensing/map/map_v2_fleet/lane_graph.yaml`(교차점·도로·회전교차로·주차)이다. 좌표는 ROS `map` 프레임 m다(`lane_rules.yaml` 머리말). Fleet 생산 코드는 이 파일을 읽지 않는다.
3. 차선 지도를 그리는 표면은 `src/sim/gz_sim/scripts/lane_live_view.py` 하나다. Gazebo 전용, 1대, ROS 필요, 관측 전용 디버그 도구다.
4. 차선 경로는 기동 인자(`map_v2_fleet_lane.launch.py`의 `route:=[...]`, `route_start`)로만 정해진다. CORE에 실행 중 차선 미션을 받는 API는 없다(`/api/v1/line-follow`는 `GET` + `PUT /mode`뿐).
5. 천장 카메라 → ArUco → 호모그래피 → 로봇 m 좌표 경로는 `rosy_games`에 이미 있다(`games/host/overhead.py`, 순수 기하 `games/field/homography.py`). cv2는 그 한 파일에만 산다(D-94).
6. Fleet은 영상을 다루지 않는다. `src/site/fleet/test/test_no_video_relay.py`가 cv2/sensor_msgs/PIL import와 `video|stream|camera|preview|proxy|relay|mjpeg|jpeg|image` 라우트를 막는다(D-136 3항).
7. 사용자 결정(2026-09-26): 스마트폰은 **천장(외부) 카메라 센서**로 쓴다. 처리는 **현장 PC**에서 한다.

**Decision (초안):**

1. **사이트 관제 지도의 기준은 `lane_graph.yaml`이다.** Fleet은 기동 시 이 파일을 읽어 `GET /api/fleet/lanes`로 내준다. `map_id`는 파일명 + 콘텐츠 체크섬이다(D-13). 점유격자는 배경 층으로 남는다. 새 차선 층은 D-249 FieldMap spec 3항을 지킨다.
2. **폰은 카메라만 한다.** 전용 안드로이드 앱이 JPEG 프레임을 지정된 어댑터 주소로 **밀어 보낸다**(WebSocket, `rosy-overhead/1`, 최신 1장). 속도·해상도는 어댑터가 정해 내려보낸다. 폰에서 인식하지 않는다(브라우저 `getUserMedia`는 HTTPS를 요구해 현장 인증서 문제가 생긴다 — 후속 ADR로 미룬다). 기성 IP카메라 앱(MJPEG 끌어오기)은 시험용 대체 입력으로만 남긴다. 앱 구조: [`docs/plans/2026-09-26-overhead-camera-android-app-design.md`](../plans/2026-09-26-overhead-camera-android-app-design.md). *(2026-09-26 개정: 처음 초안은 기성 IP카메라 앱 끌어오기였다.)*
3. **영상은 별도 현장 관측 어댑터가 처리한다.** 어댑터는 Fleet 밖의 프로세스이며, 가장 최신 프레임 1장만 읽는다(큐 없음, D-136 6항). ArUco로 코너와 로봇 마커를 찾고, 호모그래피로 **`map` 프레임 m 좌표**를 낸다. cv2는 어댑터의 한 파일에만 산다(D-94 방식). 순수 기하는 `games.field.homography`를 import해 재사용하고 뽑지 않는다(D-249 2항과 같은 이유 — 소비자 둘).
4. **Fleet은 위치만 받는다.** 어댑터가 `POST /api/fleet/sightings`로 JSON(로봇별 `x, y, yaw`, `captured_at`, `seq`, `map_id`, 출처)을 보낸다. 이미지 바이트, 영상 URL, 썸네일은 싣지 않는다. 라우트 이름은 `test_no_video_relay.py` 정규식에 걸리지 않는다. 쓰기 전용 어댑터 토큰을 따로 두어 이 토큰으로는 goal/e-stop을 못 부른다.
5. **관측(sighting)은 표시·대조용이다.** Fleet은 최신 1건만 보관하고 1 s lease가 지나면 표시에서 회색 처리, 판단 입력에서 제외한다. 판단 입력(교통정리 등, 후속)은 신선도 ≤ 300 ms만 쓴다(D-136 5항). 로봇 자기 pose와의 차이가 임계를 넘으면 콘솔이 경고한다. **sighting은 로봇 위치 추정, 정책, 최종 `cmd_vel`에 들어가지 않는다.**
6. **코너 마커 4개가 한 프레임에 모두 보여야 한다.** 하나라도 없으면 그 프레임은 sighting을 내지 않는다. 지난 호모그래피로 추측하지 않는다(D-100 정신).
7. **마커 평면을 맞춘다.** 코너 마커를 로봇 상단 마커와 같은 높이에 둬서 호모그래피 평면을 마커 평면에 일치시킨다. 그것이 불가능한 현장만 카메라 높이 `H`와 마커 높이 `h`로 시차를 보정한다(오차 ≈ `d·h/H`, `d`는 카메라 바로 아래 점에서의 수평 거리 — 예: `h`=0.12 m, `H`=2 m, `d`=1 m면 6 cm로 차선 허용 40 mm보다 크다).
8. **마커 ID는 사이트 설정이다.** 사전은 games와 같은 `DICT_4X4_50`이다. 기본 범위는 코너 30–33, 로봇 40–49로 games(로봇 1–2, 코너 10–13, 골 20/21)와 겹치지 않게 한다. `robot_id ↔ marker_id` 표는 설정 파일에 둔다.

**범위 밖(이 ADR이 열지 않는다):** 차선 단위 지시(CORE 실행 중 경로 API 필요 — D-12에 따라 별도 ADR), 구간 예약식 교통정리, 폰 브라우저 내 인식, 폰을 관제 화면으로 쓰는 모바일 UI, sighting을 로봇 위치 보정에 쓰는 것, D-210 1차 FIELD READY 범위 확장.

**Alternatives:**
- *Fleet 안에서 영상 처리* — D-136 3항과 `test_no_video_relay.py` 위반. 기각.
- *폰 브라우저에서 인식(OpenCV.js 등)* — 영상이 네트워크에 안 나가는 장점은 크지만 HTTPS 인증서, JS 이식, 폰 발열이 첫 단계 비용으로 크다. 후속으로 미룸.
- *`rosy_games` overhead에 관제 모드 추가* — 게임 호스트에 사이트 관제를 섞는다(D-90). 기각.
- *로봇 자기 pose만 쓰기* — 로봇이 위치를 잃으면 관제도 같이 잃고, 오차를 외부에서 잡을 방법이 없다.

**Consequences:** 관제 화면이 차선 지도 위에 N대를 자기 pose와 외부 관측 두 가지로 보여준다. 폰 스트림 1개가 현장 무선 대역을 쓴다(640×480 MJPEG 5 fps ≈ 1.5–3 Mbps, D-136 영상+벌크 상한 8 Mbps에 포함). 어댑터가 새 프로세스로 늘어난다. 폰 거치·마커 부착이라는 현장 물리 작업이 생긴다.

**Validation / Transition:** LOCAL — 합성 프레임(ArUco 생성 이미지)으로 좌표 오차, 코너 누락 시 무출력, stale 거절, `map_id` 불일치 거절을 시험한다. `test_no_video_relay.py`는 그대로 녹색이어야 한다. 합성 통과는 DEVICE가 아니다(D-95). DEVICE — 실제 폰을 실제 트랙 위에 두고, 알려진 위치에 놓은 로봇으로 오차를 측정한 기록만 인정한다. 실행 계획: [`docs/plans/2026-09-26-site-overhead-lane-console-design.md`](../plans/2026-09-26-site-overhead-lane-console-design.md).

**References:** D-12, D-13, D-90, D-94, D-95, D-100, D-136, D-152, D-210, D-249.

---
