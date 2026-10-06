## D-484 관제(Fleet)가 현장 지도의 주소·방향 있는 길로 경로를 잡아 로봇을 보낸다 — 위치는 Rosy Cam이 주, 지도는 주행으로 가르치고 콘솔에서 확정한다

**Status:** Proposed (2026-10-06, 사용자 결정 4건: 위치 = Rosy Cam 주·로봇 odom 보조, 주행 = 로봇별 차선/Nav2 선택, 지도 = 주행으로 가르치고 콘솔 확정, 지시 = 주소와 좌표 둘 다). 기능 범위와 단계의 결정이다. 실차 수용·G4/G5 봉인·D-257/D-395 수용을 뜻하지 않는다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md)(사이트 관제 지도는 차선 그래프, sighting은 표시용 — 5항을 이 ADR이 범위를 정해 개정) · [D-463](D-463-fleet-lane-route.md)(간선 폴리라인의 다음 짧은 점) · [D-395](D-395-fleet-assisted-localization.md)(Fleet 보조 위치 중재) · [D-472](D-472-rosy-cam-map-and-lamp-identity.md)(영상은 지도의 자동 수정본이 아니다) · [D-375](D-375-overhead-map-registration-from-lane-paint-proposal.md)(천장 카메라 맞춤은 제안) · [D-407](D-407-lane-stuck-recovery-console-then-local.md)·[D-468](D-468-local-lane-departure-return.md)(차선 이탈·막힘) · [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md)(사이트 평면 vs 장치 파이프라인)

### Context

1. **사용자 요청(2026-10-06).** "Fleet으로 지도 기반 주행. Rosy Cam으로 보면서 위치를 잡고, 하나하나 지도로 만들어, 지도 데이터로 길을 잡아 주행한다. 각 로봇의 방향 등을 지정해 path를 잡는 route 기능." 운전자는 지도 주소로 로봇을 보낸다.
2. **지금 있는 것.** `POST /api/fleet/robots/{id}/route`(D-463)는 간선 id 1–8개를 받아 0.20 m 앞 점을 로봇 Nav2 goal로 보낸다. 로봇 스냅샷이 `LOCALIZED`·`pose_frame=map`일 때만 보낸다. 점 목표 `POST /goal {x,y,yaw}`도 있다. Rosy Cam → Vision(`operations/vision/rosy_vision`) → `POST /api/fleet/sightings` 파이프라인은 SOURCE/LOCAL GO다.
3. **비어 있는 것.** 경로 그래프는 Gazebo 트랙 파일(`middleware/perception/map/map_v2_fleet/lane_graph.yaml`)을 `fleet/meet/place.py` `default_graph()`가 하드코딩한다. 주소(장소 이름), 간선의 통행 방향 편집, 지도 저장·버전, 관측으로 간선을 만드는 도구가 없다. D-257 5항은 sighting을 위치 추정에 쓰지 못하게 한다. 실차 9dfk(릴리스 043)는 motor 벤치 모드로 LiDAR·Nav2가 꺼져 있어 `/goal`·`/route`가 실차에서 돌지 않는다. 코너·로봇 마커가 붙어 있지 않아 실제 sighting은 0건이다.

### Decision

1. **현장 지도는 Fleet이 소유하는 하나의 문서다.** 사이트마다 `site-map`(스키마 `rosy.site_map/1`)을 Fleet 데이터 저장소에 버전과 함께 둔다. 구성은 다음과 같다.
   - **장소(주소)**: id, 사람이 읽는 이름(예: `주차-1`, `충전`, `A동 입구`), 지도 좌표 `x, y`(m), 도착 방향 `yaw`(선택), 종류(`park`/`charge`/`stop`/`junction`).
   - **길(간선)**: id, `from`·`to` 장소, 폴리라인(m), **통행 방향**(`one_way` 기본 / `two_way`), 차로 폭, 속도 상한(m/s), **주행 방식**(`lane` = 바닥 차선 따라가기 / `free` = 지도 좌표 추종), 사용할 수 있는 로봇 종류.
   - **좌표계**: 지도 프레임 하나. Rosy Cam 맞춤(D-375 확인 뒤 homography)이 영상 → 지도 변환을 준다.
   - 기존 `lane_graph.yaml`은 같은 스키마로 읽어 들이는 첫 지도다(하드코딩 제거, 사이트 설정 경로). 바뀐 지도는 운영자 확인 뒤에만 활성 버전이 된다. 활성 버전 교체는 진행 중인 경로가 없을 때만 한다.
2. **지시는 주소와 좌표 둘 다 받는다.** 새 `POST /api/fleet/robots/{id}/trip` 본문 `{to: 장소 id | {x,y,yaw}, via?: [장소 id], arrive_yaw?, speed_cap?}`. 주소로 보내면 Fleet이 방향 있는 그래프에서 최단 경로(거리 + 회전 비용, 통행 방향·로봇 종류·막힌 간선 제외)를 잡는다. 좌표로 보내면 가장 가까운 간선 위 점에 붙여 같은 방식으로 잡고, 붙일 간선이 차로 폭의 두 배 안에 없으면 `TRIP_OFF_MAP`으로 거절한다(지도 밖 자유 주행은 기존 `/goal`, 관리자·시험용). 결과 경로(간선 순서·장소 순서·예상 길이)를 응답과 콘솔에 보이고, 실행은 운영자가 확인한 뒤 시작한다. 기존 `/route`(간선 id 직접 지정)는 그대로 둔다.
3. **위치는 Rosy Cam이 주, 로봇 odom이 보조다(D-257 5항 개정, 범위 한정).** Fleet 위치 중재기(D-395 `operations/fleet/fleet/localization/`)가 신선한 sighting(≤ 300 ms, 신원 확인된 마커, 맞춤 확인된 카메라)을 지도 자세의 기준으로 쓰고, sighting 사이와 시야 밖 구간은 로봇 odom 증분으로 잇는다. odom만으로 이은 거리가 `max_dead_reckon_m`(기본 1.5 m)을 넘거나 sighting과 odom 예측이 `max_jump_m`(기본 0.15 m)보다 어긋나면 위치 상태를 `DEGRADED`로 내리고 그 로봇의 trip을 다음 장소에서 멈춘다. 이 개정은 **trip 실행의 위치 판정**에만 적용한다. sighting은 여전히 로봇의 최종 `cmd_vel`·안전 정지·로봇 자체 위치 추정(AMCL)에 직접 들어가지 않는다. 위치 상태 `LOCALIZED`는 "Fleet 중재 자세가 신선하고 일관"을 뜻하도록 D-463 4항의 판정 입력을 넓힌다.
4. **주행 방식은 로봇별·간선별로 고른다.**
   - **`lane`(차선 따라가기)**: 로봇은 기존 line-follow로 간선을 간다. Fleet은 위치로 다음 교차 장소를 알고, 도착 전에 그 교차로에서 할 일(`straight`/`left`/`right`/`stop`)과 정지 거리를 로봇에 준다. 로봇 쪽은 D-468/D-476의 route hint 확정점을 쓴다(새 CORE 경로가 필요하면 API Ref에 한 행으로 더한다). Nav2가 없는 지금의 9dfk가 이 방식으로 첫 실차를 간다.
   - **`free`(지도 좌표 추종)**: D-463 방식 그대로, 간선 폴리라인의 다음 짧은 점을 로봇 Nav2 goal로 보낸다. Nav2·지도·G4/G5 봉인이 있는 로봇만 쓴다.
   - 로봇 능력(`lane`·`free` 지원)은 로봇 스냅샷의 능력 필드로 Fleet이 안다. 경로 계획은 그 로봇이 갈 수 없는 간선을 빼고 잡는다.
5. **지도는 주행으로 가르치고 콘솔에서 확정한다.** 콘솔 "지도 가르치기" 모드에서 운영자가 로봇 하나를 고르고 시작하면, Fleet은 그 로봇의 중재 자세 궤적(sighting + odom)을 기록한다. 운전자는 Pilot으로 로봇을 몬다. 멈추면 콘솔이 궤적을 단순화한 폴리라인 초안을 보이고, 운영자가 시작·끝 장소(기존 장소에 붙이거나 새 주소 이름), 통행 방향, 주행 방식, 속도 상한을 정해 **확정**해야 지도 초안에 간선이 생긴다. 초안은 "활성화"를 눌러야 trip에 쓰인다. 자동 수정·자동 활성화는 없다(D-472 2항 유지). 장소는 같은 방식으로 로봇을 세운 자리에서 "여기에 주소 만들기"로 만든다.
6. **안전 경계는 그대로다.** trip은 로봇의 기존 모드 게이트·seat·E-stop·속도 상한 안에서만 움직인다. Fleet은 최종 `cmd_vel`을 내지 않는다(CORE가 유일한 최종 발행자). 위치 `DEGRADED`·통신 끊김·sighting 실종 시 Fleet은 새 지시를 멈추고 로봇의 deadman이 최종 정지를 맡는다. 동시 trip의 간선 충돌은 기존 교통정리(양보·bay)를 그대로 쓰고, 첫 단계는 한 번에 로봇 한 대만 trip을 허용한다.
7. **단계.**
   - **M1(SOURCE/LOCAL)**: `rosy.site_map/1` 스키마·저장·버전·활성화, `lane_graph.yaml` 가져오기, 하드코딩 제거, 방향 있는 그래프 경로 계획, `POST /trip` 계획 응답(실행 없음), 콘솔 지도 보기·장소/간선 편집·경로 미리보기.
   - **M2**: 위치 중재기의 Rosy Cam 주 + odom 보조, `DEGRADED` 판정, 가르치기 모드 기록·초안 확정.
   - **M3(SIM)**: Gazebo에서 `free`·`lane` 두 방식으로 주소 trip 완주.
   - **M4(DEVICE)**: 마커 부착·맞춤 확인 뒤 9dfk `lane` 방식으로 한 간선 → 한 바퀴. 실차 이동은 사용자 승인과 동료 세션 확인 뒤에만.

### 범위 밖

- 여러 로봇 동시 trip의 교차로 예약(첫 단계는 한 대). 지도 자동 생성. 실외·다층. sighting을 로봇 내부 AMCL에 넣는 일.

### 검토한 대안

- **주소만, 좌표 경로 제거.** 사용자가 둘 다 받기로 했다. 좌표 지시도 지도 위로 붙여 같은 계획기를 탄다.
- **로봇 Nav2 AMCL을 주 위치로.** G4 재봉인·G5 SLAM 지도가 먼저 필요하고 현재 9dfk에서 바로 못 간다. 로봇별 `free` 방식으로 남긴다.
- **콘솔 영상 위에 그려서 지도 만들기.** 시야 밖 구간(서쪽 1/3)과 바닥 높이 시차 때문에 실제로 갈 수 있는 궤적이 아니다. 주행 궤적으로 가르친다.

### Consequences

- Fleet: 지도 저장소·스키마·편집 API, 경로 계획기, `/trip`, 가르치기 기록, 위치 중재 개정, 콘솔 지도 화면. Vision/Rosy Cam: 맞춤 확인과 신원 마커가 실차 전제다.
- 로봇: `lane` 방식의 교차로 지시 입력(D-468/D-476 확정점 사용 또는 API Ref 한 행). `free` 방식은 기존 그대로.
- D-257 5항은 3항의 범위에서 개정된다. D-463 4항의 `LOCALIZED` 판정 입력이 Fleet 중재 자세를 포함한다.
- 수용 기준: M1 — 스키마 왕복, 활성화 규칙, 경로 계획(통행 방향·로봇 종류·막힌 간선), 좌표 붙이기·`TRIP_OFF_MAP`, 하드코딩 제거 회귀. M2 — sighting 끊김·점프에서 `DEGRADED`·다음 장소 정지. M3 — 두 방식 Gazebo 완주. M4 — 9dfk 실차 한 간선·한 바퀴, 위치 오차 기록(줄자 대비).
