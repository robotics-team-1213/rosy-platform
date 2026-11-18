## D-1046 SLAM이 무너질 때를 위한 사이트 벽 지도 대체 경로

**Status:** Proposed (2026-11-18, 사용자 지시). 첫 착지는 벽 지도 생성·읽기 경로·감지 판정, 두 번째 착지(이 갱신)는 자동 전환이다. **사용자 최종 결정(같은 날): "재시작은 자동으로 재시작해야해. 무조건 자동전환이야."** 사람 승인 단계도 Fleet 문 지기(hold)도 두지 않는다. 두 번째 착지는 안전 경로(`Safety-Review` 꼬리말 필요)이므로 첫 착지와 섞지 않는다.

잇는 결정: [D-144](D-144-runtime-mode-navigation-backend.md)(항법 백엔드는 `slam`/`localization`, 바꾸려면 재시작) · [D-1003](D-1003-nav2-free-goals-in-the-robot-map-frame.md)(사이트 지도로 점유격자를 만들지 않기로 함) · [D-1022](D-1022-robot-map-binding.md)(기체 SLAM 격자와 현장 지도의 결속) · D-395(국소화 후보와 `initialpose` 경로) · D-989(auto-locate).

### Context

2026-11-18 사용자 말: "Nav2 slam 돌릴 때 맵이 흔들리는 거 대비해서, 우리가 만든 벽 있는 맵도 같이 쓰는 fallback 로직 넣어줘. slam 같은 건 계속 무너지는 경향이 있어서 더더욱." 이전에는 "완전 자동으로, 코드로 짠 파이프라인"을 요구했다. 패널 1라운드 기록은 `slam-fallback-panel/`의 `task.md`, `r1-A.md`, `r1-B.md`다.

1. **"맵이 흔들린다"를 잰 기록이 없다.** 저장소에서 찾은 실제 SLAM 실패는 Nav2 composition 미적재(geg6 11-04), LiDAR 0°를 앞으로 읽은 주행 스크립트, 카펫 제자리 회전 때의 odom 오차, 트랙(2.4 x 1.2 m)보다 큰 76x71 칸 지도다. 지도 재저장은 `map_grid_id`를 바꿔 D-1022 결속을 일부러 무효로 만든다. 감지 기준은 모두 제안값이고 실물에서 모은 적이 없다.
2. **D-1003이 사이트 지도 격자를 거절한 근거가 바뀌었다.** 당시 R의 사이트 지도 7개 버전에는 벽이 없고 차선 페인트는 LiDAR에 안 보였다. 지금 활성 지도에는 `SiteWall` 면(벽 면 선분, 10 mm 두께·155 mm 높이)이 있고, 같은 선분으로 만든 시뮬 격자(`map_260905`)가 이미 있다.
3. 사이트 프레임의 벽 지도 위에서 국소화하면 자세가 바로 사이트 좌표로 나와 D-1003·D-1022 결속이 필요 없다.

### Decision

1. **벽 지도는 Fleet 활성 사이트 지도의 벽에서 만든다.** `fleet/localization/wall_grid.py`가 `SiteWall.face`를 사이트 프레임의 Nav2 점유격자로 바꾼다(해상도 0.025 m, 벽은 한 칸보다 얇아도 최소 한 칸 두께, 벽 상자 안은 free, 밖은 unknown, `trinary` PGM). 같은 벽이면 같은 바이트와 sha256이 나오고, 파일 이름은 `wall_<map_id>_v<version>`이다. 읽기 경로 `GET /api/fleet/site-map/wall-grid`가 JSON(`map_id`, `version`, `resolution`, `yaml`, `pgm_base64`, `sha256`, `file_stem`)을 준다. 활성 지도가 없거나 벽이 없으면 404(`SITE_MAP_NOT_ACTIVE`, `SITE_MAP_NO_WALLS`).
2. **이번 착지는 감지까지다.** `core_features/localization/slam_health.py`가 표본 흐름을 `ok`/`degraded`/`lost`와 이유로 가른다. 표본은 지도 판정(`tools/capture/map_health.py`, 새 아레나 상자 규칙 포함), 스캔-벽 일치율, `map->odom` 보정 점프, `slam_camera_gap_m`, 이동 중 여부다. lost는 점프 > 0.10 m(명령 없이), 일치율 < 0.7, 간격 > 0.30 m가 각각 3표본 연속일 때, degraded는 지도 판정 fail, 복귀는 좋은 표본 10개 연속, 상태 변경은 60 s 안에 되풀이하지 않는다(lost로 가는 쪽만 기다리지 않는다). 모든 숫자는 실측 전 제안값이고, 판정은 아무것도 멈추거나 바꾸지 않는다.
3. **전환은 항상 자동이다(두 번째 착지에 구현).** 사람 승인·Fleet 문 지기·`fleet.nav.slam_fallback` 설정은 없다. 순서와 한계는 다음과 같고 가드 한계는 하나도 약해지지 않는다.
   - **정지가 먼저다.** CORE의 `SlamFallback` 감독기(ROS 없는 정책, `core_features/localization/slam_fallback.py`; core_features 단위가 10,000줄 한도라 drive의 localization 폴더에 둔다)가 백엔드가 `slam`일 때만 `slam_health`에 표본을 먹인다(다른 백엔드는 감독기가 아무것도 안 한다). `lost`이면 자율 정지(Nav2 목표 취소·line-follow·docking·swarm 정지, 수동 입력 제거)로 명령 관리자의 `cmd_vel`을 0으로 내리고, 오도메트리 속도 0이 2 s 이어지고 목표가 없다는 증거를 파일(`slam-fallback-stop.json`)로 쓴다. 증거는 호스트가 답할 때까지(SWITCHING 동안도) 매 틱 다시 쓰고, 틱마다 수동 입력(teleop)을 지우고 새로 생긴 목표를 취소한다. `degraded`는 보고만 한다.
   - **특권 절반은 Host Agent 뒤에 있다.** `navigation_fallback_host.py`가 `navigation_approval_host.py`와 같은 구조(`SystemOps.commit` = `commit_runtime` + `publish_ready` + PROJECTED 확인, transient unit)로 돈다. `runtime.env`를 손으로 고치지 않는다. 벽 지도가 올려져 있고(sha256 일치·로드 가능), 정지 증거가 신선하고(같은 부팅의 `CLOCK_MONOTONIC` 기준 3 s 이내와 boot id 일치, 속도 0 2 s 이상, 목표 없음; 증거는 CORE 소유의 일반 파일이어야 하고 링크·그룹/전체 쓰기·4 KiB 초과는 이동 중으로 본다), 백엔드가 `slam`이고, 이번 부팅에 시도한 적이 없을 때만 `ROSY_NAVIGATION_BACKEND=localization`, `ROSY_MAP=<벽 지도>`, `ROSY_ENABLE_LOC_ASSIST=true`로 바꾸고 `rosy-navigation`만 재시작한다. 재시작이 실패하면(또는 활성이 안 되면) 이전 값으로 되돌린다(되돌릴 `runtime.env` 원본은 0600 백업 파일에 두고 상태 파일에는 해시만 둔다; 상태 파일도 0600). 성공이든 되돌림이든 호스트 거절(REFUSED)이든 부팅당 한 번이다(거절도 시도로 기록한다). 다른 부팅에서 남은 SWITCHING이나 유닛이 죽은 SWITCHING은 FAILED로 읽고 "실행 중"으로 막지 않는다. 다시 허용하는 것은 root의 `reset`뿐이다.
   - **Host Agent 등급은 `machine`이다.** 사람의 로그인(`operator`·`administrator`)이 아니라 CORE 감독기의 자기 신원이다. `machine`은 읽기와 `navigation_fallback.*`만 보낼 수 있고 반대로 사람은 `machine` 명령을 못 보낸다. 경로를 받는 파라미터는 없다(사유 코드 `reason`만). 벽 지도 파일은 CORE가 spool 폴더에 두고 호스트가 sha256과 PGM 형식을 다시 확인해 `/var/lib/rosy/maps/wall_<id>_v<n>.{pgm,yaml}`로 설치한다(yaml은 호스트가 숫자로 직접 만든다, `site.yaml`은 건드리지 않는다, 직전 것 하나를 남긴다).
   - **벽 지도 전달은 Fleet이 민다.** Fleet은 CORE의 외부 클라이언트이므로 `slam_fallback` 블록이 있는 기체에 활성 지도의 벽 격자를 한 번 `POST /api/v1/navigation/slam-fallback/wall-map`로 보낸다(sha256이 다르면 다시, 실패하면 60 s 뒤).
   - **재시작 뒤에는 LOCALIZED 전에 목표를 받지 않는다.** 감독기가 `LocalizationAssist.hold`로 정지·전환·대기·실패 동안 어떤 LOCALIZED 보고도 UNKNOWN으로 읽게 해 목표·도킹을 거절하고(자율 정지 경로도 같이 돈다; CANDIDATES 등 나머지 상태는 Fleet이 답할 수 있게 그대로 보인다), 준비 게이트의 필수 구성요소를 localization 프로필로 바꾼다. 대기는 재시작 **뒤에 받은** LOCALIZED(map) 보고(`assist.reports` 증가) 하나로만 끝나며 감독기만 hold를 푼다.
   - **첫 자세는 loc_assist 후보다.** `nav2_params.yaml`의 `set_initial_pose`는 `false`가 목표다(사용자가 승인한 D-1022 고정 결정). 다만 loc_assist가 꺼진 기체는 첫 자세를 잃으므로 이 변경은 loc_assist 기본 켬(11-18 사용자 결정, `fix/pinky-loc-assist-switch` 뒤)과 같은 착지로 넣는다. 그때까지 폴백 전환은 `ROSY_ENABLE_LOC_ASSIST=true`로 loc_assist를 켜고, AMCL의 (0, 0, 0) 첫 자세는 loc_assist 후보가 덮는다. 후보는 Fleet 중재기가 고른다. 후보 둘이 약 180° 거울 관계이고 스캔 단서가 못 가르면 천장 카메라 위치가 가깝고 분명한 쪽을 고른다(`wall_tiebreak.py`: 둘이 1 m 이상 떨어져 있어 표시 전용 보정 오차 0.33 m로 충분, 2 s 같은 쪽을 유지, `source: overhead`로 직접 자세). 결정이 없으면 기체는 정지 상태를 유지하고 CORE가 180 s 뒤 경보(`slam_fallback.alert`)를 올린다.
   - **자동으로 SLAM으로 되돌아가지 않는다.** 되돌리는 명령도 경로도 없다. 새 지도 작성·재저장·D-1022 재승인은 사람이 하고 IDLE에서 새 부팅·새 런타임 설정으로만 돌아간다.
   - `slam_fallback` 상태 블록(`phase`, `fallback_active`, `reason`, `since`, `health`, `wall_map`, `alert`)이 `StateSnapshot`에 덧붙는다(null이면 감독기가 꺼진 기체). Fleet은 이 블록으로 전환 여부를 안다.

### 다시 여는 것

- **D-1003의 "사이트 지도 점유격자는 만들지 않는다"**: 벽이 생겼으므로 여기서만(대체 경로 한정) 뒤집는다. 차선 페인트는 여전히 LiDAR에 안 보이므로 차로 지도를 격자로 만들지는 않는다.
- **D-1022의 "AMCL 첫 자세 고정"**: 사용자가 2026-11-18에 승인해 `set_initial_pose: false`로 바꾸기로 했다(loc_assist 기본 켬과 같은 착지). 모든 기체에서 Nav2가 (0, 0, 0)을 첫 자세로 지어내지 않는다. 첫 자세는 loc_assist 후보와 Fleet 중재(D-395)에서만 온다. 실물 Pinky는 `enable_loc_assist`가 기본 꺼짐이었으므로, 이 결정이 기체 전체에 적용되려면 loc_assist 활성화가 따로 착지해야 한다(미해결, 보고서 참조). 이번 착지는 폴백 전환 때만 `ROSY_ENABLE_LOC_ASSIST=true`를 켠다.

### Consequences

- 벽 지도와 SLAM 지도는 프레임이 다르다. 전환 때 기체 프레임에 캐시된 목표(D-1003 변환, trip 목표)는 버려야 한다.
- 벽 안에 특징이 없어 벽 하나를 따라 서 있을 때 그 방향 제약이 약하다(측정 전). 짐칸 아래 낮은 물체는 스캔 면에 안 보인다.
- 천장 카메라 보정은 표시 전용이고 낡았다(0.33 m / 5.6°). 카메라 자세를 Nav2에 먹이는 대체 경로는 승인된 보정(D-595 방식) 전에는 후보도 아니다.
- R은 main보다 뒤처진 손 패치 코드를 돌리고 있어, Fleet이 내는 읽기 경로는 게시 경로를 거쳐야 현장에 닿는다.

### 사용자가 정한 것 (2026-11-18)

1. 감지만 하는 shadow 단계는 두지 않고 정지·전환까지 간다.
2. 전환·재시작은 항상 자동이다(`hold` 설정·사람 승인 없음).
3. D-395 후보 경로로 첫 자세를 주고 `set_initial_pose`는 `false`다.
4. `nav2_params.yaml`의 `set_initial_pose`를 `false`로 바꾼다 — loc_assist 기본 켬과 함께(이번 착지에는 없음).

### 남은 것

- 부팅당 한 번 제한의 root `reset` 절차와 Fleet 화면의 `slam_fallback` 표시·경보 문구는 정해지지 않았다.
- Fleet이 `slam_camera_gap_m`·스캔 일치율·지도 판정을 CORE의 `POST /api/v1/navigation/slam-fallback/evidence`로 먹이는 쪽은 아직 없다(CORE의 `map->odom` 점프만 현재 입력이다).

### 리뷰 반영 (2026-11-18, 독립 안전 리뷰 D-430 후)

- **CORE 재시작 뒤에도 대기가 이어진다(F1).** 감독기는 SWITCHED를 본 순간 `slam-fallback-state.json`(CORE 상태 폴더, 사유와 시각만)을 쓴다. 이후 CORE가 `backend=localization`으로 다시 뜨면 이 표식이 있는 기체는 WAITING_LOCALIZATION으로 시작해(hold 즉시 켜짐) 첫 틱에 호스트 `navigation_fallback.status`로 SWITCHED인지 확인하고, 호스트가 답하지 않으면 그대로 정지·경보(180 s)를 유지한다(fail closed). 호스트가 SWITCHED가 아니라고 하면(사람이 reset·수동 변경) 표식을 지우고 감독기를 끈다. SLAM 백엔드로 뜬 기체의 남은 표식은 지운다.
- **지도 설치(F2)**: `stage`는 `runtime.env`의 `ROSY_MAP`이 가리키는 지도와 포인터의 지도는 지우지 않고, 전환(SWITCHING)이 도는 동안은 거절하며(CORE API는 409 `SWITCH_RUNNING`), 파일마다 임시 이름 + `os.replace`로 쓴다. 같은 이름에 바이트가 같으면 아무것도 쓰지 않고, 실행 중인 지도 이름에 다른 바이트는 거절한다. 스풀은 심볼릭 링크·비정규 파일·크기 초과(메타 4 KiB, 이미지 한도)를 거절한다. 스풀 이미지 파일명은 `wall-map.pgm`이다.
- **hold가 이긴다(F3)**: STOPPING·SWITCHING·WAITING·FAILED 동안 LOCALIZED 보고는 UNKNOWN으로 읽는다. 대기 종료는 재시작 뒤에 받은 보고만 인정한다.
- **정지 증거(F4)**: 호스트가 답할 때까지 매 틱 갱신하고, `CLOCK_MONOTONIC`(같은 부팅 안 프로세스 간 공유)과 boot id로 비교한다(벽시계 점프에 안 흔들림). 호스트는 증거 파일을 `O_NOFOLLOW`로 열어 정규 파일·CORE 소유·그룹/전체 쓰기 없음·크기 상한을 확인한다. teleop은 STOPPING·SWITCHING의 매 틱(1 s) 지운다 — 명령 관리자에 teleop 거절 문(gate)을 따로 두지는 않았으므로 지우기 사이 최대 약 1 s의 teleop 입력은 속도 증거를 깨서 호스트가 거절하게 만든다(남은 위험). 속도의 유일한 출처는 오도메트리이므로 바퀴 미끄러짐은 증거가 못 잡는다.
- **카메라 동점 처리(F5)**: 서비스는 로봇의 `slam_fallback.phase`가 WAITING_LOCALIZATION일 때만 허용하고(ACTIVE 뒤에는 안 함), 최고 `scan_fit`이 0.85(loc_assist 자체 검증 하한) 이상이어야 한다. 천장 카메라 시야 yaw와의 일치 검사는 하지 않았다(남은 것). D-395 §7 "overhead는 단독 결정 못 한다"의 이 한정된 예외의 소유자는 SLAM 폴백이며, Fleet `localization/AGENTS.md`에 한계와 함께 적었다.
- **호스트 상태(F6·F8)**: 다른 부팅이 남긴 SWITCHING·유닛이 죽은 SWITCHING은 FAILED로 읽는다. 호스트 거절(REFUSED)도 `attempt_boot_id`를 기록한다. 상태 파일은 0600이고 `runtime.env` 전문을 담지 않는다(0600 백업 파일 + 해시).
- **지도 숫자(F7)**: 해상도 0.01~0.1 m, 원점은 유한한 ±1000 m 안. CORE API(`allow_inf_nan=False`)와 호스트 두 곳에서 거절한다. 지도를 Fleet 키로 서명하는 것과 `map_id`를 현장 지도 id에 묶는 것은 하지 않았다(남은 것).
- **호스트 인자(F9)**: 전환 유닛 인자 앞에 `--`를 붙이고, `reason`은 `^[a-z][a-z0-9_]{0,63}## D-1046 SLAM이 무너질 때를 위한 사이트 벽 지도 대체 경로

**Status:** Proposed (2026-11-18, 사용자 지시). 첫 착지는 벽 지도 생성·읽기 경로·감지 판정, 두 번째 착지(이 갱신)는 자동 전환이다. **사용자 최종 결정(같은 날): "재시작은 자동으로 재시작해야해. 무조건 자동전환이야."** 사람 승인 단계도 Fleet 문 지기(hold)도 두지 않는다. 두 번째 착지는 안전 경로(`Safety-Review` 꼬리말 필요)이므로 첫 착지와 섞지 않는다.

잇는 결정: [D-144](D-144-runtime-mode-navigation-backend.md)(항법 백엔드는 `slam`/`localization`, 바꾸려면 재시작) · [D-1003](D-1003-nav2-free-goals-in-the-robot-map-frame.md)(사이트 지도로 점유격자를 만들지 않기로 함) · [D-1022](D-1022-robot-map-binding.md)(기체 SLAM 격자와 현장 지도의 결속) · D-395(국소화 후보와 `initialpose` 경로) · D-989(auto-locate).

### Context

2026-11-18 사용자 말: "Nav2 slam 돌릴 때 맵이 흔들리는 거 대비해서, 우리가 만든 벽 있는 맵도 같이 쓰는 fallback 로직 넣어줘. slam 같은 건 계속 무너지는 경향이 있어서 더더욱." 이전에는 "완전 자동으로, 코드로 짠 파이프라인"을 요구했다. 패널 1라운드 기록은 `slam-fallback-panel/`의 `task.md`, `r1-A.md`, `r1-B.md`다.

1. **"맵이 흔들린다"를 잰 기록이 없다.** 저장소에서 찾은 실제 SLAM 실패는 Nav2 composition 미적재(geg6 11-04), LiDAR 0°를 앞으로 읽은 주행 스크립트, 카펫 제자리 회전 때의 odom 오차, 트랙(2.4 x 1.2 m)보다 큰 76x71 칸 지도다. 지도 재저장은 `map_grid_id`를 바꿔 D-1022 결속을 일부러 무효로 만든다. 감지 기준은 모두 제안값이고 실물에서 모은 적이 없다.
2. **D-1003이 사이트 지도 격자를 거절한 근거가 바뀌었다.** 당시 R의 사이트 지도 7개 버전에는 벽이 없고 차선 페인트는 LiDAR에 안 보였다. 지금 활성 지도에는 `SiteWall` 면(벽 면 선분, 10 mm 두께·155 mm 높이)이 있고, 같은 선분으로 만든 시뮬 격자(`map_260905`)가 이미 있다.
3. 사이트 프레임의 벽 지도 위에서 국소화하면 자세가 바로 사이트 좌표로 나와 D-1003·D-1022 결속이 필요 없다.

### Decision

1. **벽 지도는 Fleet 활성 사이트 지도의 벽에서 만든다.** `fleet/localization/wall_grid.py`가 `SiteWall.face`를 사이트 프레임의 Nav2 점유격자로 바꾼다(해상도 0.025 m, 벽은 한 칸보다 얇아도 최소 한 칸 두께, 벽 상자 안은 free, 밖은 unknown, `trinary` PGM). 같은 벽이면 같은 바이트와 sha256이 나오고, 파일 이름은 `wall_<map_id>_v<version>`이다. 읽기 경로 `GET /api/fleet/site-map/wall-grid`가 JSON(`map_id`, `version`, `resolution`, `yaml`, `pgm_base64`, `sha256`, `file_stem`)을 준다. 활성 지도가 없거나 벽이 없으면 404(`SITE_MAP_NOT_ACTIVE`, `SITE_MAP_NO_WALLS`).
2. **이번 착지는 감지까지다.** `core_features/localization/slam_health.py`가 표본 흐름을 `ok`/`degraded`/`lost`와 이유로 가른다. 표본은 지도 판정(`tools/capture/map_health.py`, 새 아레나 상자 규칙 포함), 스캔-벽 일치율, `map->odom` 보정 점프, `slam_camera_gap_m`, 이동 중 여부다. lost는 점프 > 0.10 m(명령 없이), 일치율 < 0.7, 간격 > 0.30 m가 각각 3표본 연속일 때, degraded는 지도 판정 fail, 복귀는 좋은 표본 10개 연속, 상태 변경은 60 s 안에 되풀이하지 않는다(lost로 가는 쪽만 기다리지 않는다). 모든 숫자는 실측 전 제안값이고, 판정은 아무것도 멈추거나 바꾸지 않는다.
3. **전환은 항상 자동이다(두 번째 착지에 구현).** 사람 승인·Fleet 문 지기·`fleet.nav.slam_fallback` 설정은 없다. 순서와 한계는 다음과 같고 가드 한계는 하나도 약해지지 않는다.
   - **정지가 먼저다.** CORE의 `SlamFallback` 감독기(ROS 없는 정책, `core_features/localization/slam_fallback.py`; core_features 단위가 10,000줄 한도라 drive의 localization 폴더에 둔다)가 백엔드가 `slam`일 때만 `slam_health`에 표본을 먹인다(다른 백엔드는 감독기가 아무것도 안 한다). `lost`이면 자율 정지(Nav2 목표 취소·line-follow·docking·swarm 정지, 수동 입력 제거)로 명령 관리자의 `cmd_vel`을 0으로 내리고, 오도메트리 속도 0이 2 s 이어지고 목표가 없다는 증거를 파일(`slam-fallback-stop.json`)로 쓴다. 증거는 호스트가 답할 때까지(SWITCHING 동안도) 매 틱 다시 쓰고, 틱마다 수동 입력(teleop)을 지우고 새로 생긴 목표를 취소한다. `degraded`는 보고만 한다.
   - **특권 절반은 Host Agent 뒤에 있다.** `navigation_fallback_host.py`가 `navigation_approval_host.py`와 같은 구조(`SystemOps.commit` = `commit_runtime` + `publish_ready` + PROJECTED 확인, transient unit)로 돈다. `runtime.env`를 손으로 고치지 않는다. 벽 지도가 올려져 있고(sha256 일치·로드 가능), 정지 증거가 신선하고(같은 부팅의 `CLOCK_MONOTONIC` 기준 3 s 이내와 boot id 일치, 속도 0 2 s 이상, 목표 없음; 증거는 CORE 소유의 일반 파일이어야 하고 링크·그룹/전체 쓰기·4 KiB 초과는 이동 중으로 본다), 백엔드가 `slam`이고, 이번 부팅에 시도한 적이 없을 때만 `ROSY_NAVIGATION_BACKEND=localization`, `ROSY_MAP=<벽 지도>`, `ROSY_ENABLE_LOC_ASSIST=true`로 바꾸고 `rosy-navigation`만 재시작한다. 재시작이 실패하면(또는 활성이 안 되면) 이전 값으로 되돌린다(되돌릴 `runtime.env` 원본은 0600 백업 파일에 두고 상태 파일에는 해시만 둔다; 상태 파일도 0600). 성공이든 되돌림이든 호스트 거절(REFUSED)이든 부팅당 한 번이다(거절도 시도로 기록한다). 다른 부팅에서 남은 SWITCHING이나 유닛이 죽은 SWITCHING은 FAILED로 읽고 "실행 중"으로 막지 않는다. 다시 허용하는 것은 root의 `reset`뿐이다.
   - **Host Agent 등급은 `machine`이다.** 사람의 로그인(`operator`·`administrator`)이 아니라 CORE 감독기의 자기 신원이다. `machine`은 읽기와 `navigation_fallback.*`만 보낼 수 있고 반대로 사람은 `machine` 명령을 못 보낸다. 경로를 받는 파라미터는 없다(사유 코드 `reason`만). 벽 지도 파일은 CORE가 spool 폴더에 두고 호스트가 sha256과 PGM 형식을 다시 확인해 `/var/lib/rosy/maps/wall_<id>_v<n>.{pgm,yaml}`로 설치한다(yaml은 호스트가 숫자로 직접 만든다, `site.yaml`은 건드리지 않는다, 직전 것 하나를 남긴다).
   - **벽 지도 전달은 Fleet이 민다.** Fleet은 CORE의 외부 클라이언트이므로 `slam_fallback` 블록이 있는 기체에 활성 지도의 벽 격자를 한 번 `POST /api/v1/navigation/slam-fallback/wall-map`로 보낸다(sha256이 다르면 다시, 실패하면 60 s 뒤).
   - **재시작 뒤에는 LOCALIZED 전에 목표를 받지 않는다.** 감독기가 `LocalizationAssist.hold`로 정지·전환·대기·실패 동안 어떤 LOCALIZED 보고도 UNKNOWN으로 읽게 해 목표·도킹을 거절하고(자율 정지 경로도 같이 돈다; CANDIDATES 등 나머지 상태는 Fleet이 답할 수 있게 그대로 보인다), 준비 게이트의 필수 구성요소를 localization 프로필로 바꾼다. 대기는 재시작 **뒤에 받은** LOCALIZED(map) 보고(`assist.reports` 증가) 하나로만 끝나며 감독기만 hold를 푼다.
   - **첫 자세는 loc_assist 후보다.** `nav2_params.yaml`의 `set_initial_pose`는 `false`가 목표다(사용자가 승인한 D-1022 고정 결정). 다만 loc_assist가 꺼진 기체는 첫 자세를 잃으므로 이 변경은 loc_assist 기본 켬(11-18 사용자 결정, `fix/pinky-loc-assist-switch` 뒤)과 같은 착지로 넣는다. 그때까지 폴백 전환은 `ROSY_ENABLE_LOC_ASSIST=true`로 loc_assist를 켜고, AMCL의 (0, 0, 0) 첫 자세는 loc_assist 후보가 덮는다. 후보는 Fleet 중재기가 고른다. 후보 둘이 약 180° 거울 관계이고 스캔 단서가 못 가르면 천장 카메라 위치가 가깝고 분명한 쪽을 고른다(`wall_tiebreak.py`: 둘이 1 m 이상 떨어져 있어 표시 전용 보정 오차 0.33 m로 충분, 2 s 같은 쪽을 유지, `source: overhead`로 직접 자세). 결정이 없으면 기체는 정지 상태를 유지하고 CORE가 180 s 뒤 경보(`slam_fallback.alert`)를 올린다.
   - **자동으로 SLAM으로 되돌아가지 않는다.** 되돌리는 명령도 경로도 없다. 새 지도 작성·재저장·D-1022 재승인은 사람이 하고 IDLE에서 새 부팅·새 런타임 설정으로만 돌아간다.
   - `slam_fallback` 상태 블록(`phase`, `fallback_active`, `reason`, `since`, `health`, `wall_map`, `alert`)이 `StateSnapshot`에 덧붙는다(null이면 감독기가 꺼진 기체). Fleet은 이 블록으로 전환 여부를 안다.

### 다시 여는 것

- **D-1003의 "사이트 지도 점유격자는 만들지 않는다"**: 벽이 생겼으므로 여기서만(대체 경로 한정) 뒤집는다. 차선 페인트는 여전히 LiDAR에 안 보이므로 차로 지도를 격자로 만들지는 않는다.
- **D-1022의 "AMCL 첫 자세 고정"**: 사용자가 2026-11-18에 승인해 `set_initial_pose: false`로 바꾸기로 했다(loc_assist 기본 켬과 같은 착지). 모든 기체에서 Nav2가 (0, 0, 0)을 첫 자세로 지어내지 않는다. 첫 자세는 loc_assist 후보와 Fleet 중재(D-395)에서만 온다. 실물 Pinky는 `enable_loc_assist`가 기본 꺼짐이었으므로, 이 결정이 기체 전체에 적용되려면 loc_assist 활성화가 따로 착지해야 한다(미해결, 보고서 참조). 이번 착지는 폴백 전환 때만 `ROSY_ENABLE_LOC_ASSIST=true`를 켠다.

### Consequences

- 벽 지도와 SLAM 지도는 프레임이 다르다. 전환 때 기체 프레임에 캐시된 목표(D-1003 변환, trip 목표)는 버려야 한다.
- 벽 안에 특징이 없어 벽 하나를 따라 서 있을 때 그 방향 제약이 약하다(측정 전). 짐칸 아래 낮은 물체는 스캔 면에 안 보인다.
- 천장 카메라 보정은 표시 전용이고 낡았다(0.33 m / 5.6°). 카메라 자세를 Nav2에 먹이는 대체 경로는 승인된 보정(D-595 방식) 전에는 후보도 아니다.
- R은 main보다 뒤처진 손 패치 코드를 돌리고 있어, Fleet이 내는 읽기 경로는 게시 경로를 거쳐야 현장에 닿는다.

### 사용자가 정한 것 (2026-11-18)

1. 감지만 하는 shadow 단계는 두지 않고 정지·전환까지 간다.
2. 전환·재시작은 항상 자동이다(`hold` 설정·사람 승인 없음).
3. D-395 후보 경로로 첫 자세를 주고 `set_initial_pose`는 `false`다.
4. `nav2_params.yaml`의 `set_initial_pose`를 `false`로 바꾼다 — loc_assist 기본 켬과 함께(이번 착지에는 없음).

### 남은 것

- 부팅당 한 번 제한의 root `reset` 절차와 Fleet 화면의 `slam_fallback` 표시·경보 문구는 정해지지 않았다.
- Fleet이 `slam_camera_gap_m`·스캔 일치율·지도 판정을 CORE의 `POST /api/v1/navigation/slam-fallback/evidence`로 먹이는 쪽은 아직 없다(CORE의 `map->odom` 점프만 현재 입력이다).

이 아니면 거절한다(Host Agent도 식별자 형식을 이미 강제한다). `machine` 등급 주장은 Host Agent 소켓이 SO_PEERCRED로 CORE 서비스 uid만 받아들이므로 그 uid의 프로세스만 낼 수 있다(`host_agent_server.check_peer_credentials`): 새 신뢰 경계 없음.
- **CORE 안전성**: 감독기 배선 가져오기·생성이 실패해도 CORE는 뜬다(`services._build_slam_fallback`이 로그만 남기고 감독기 없이 진행; slam 백엔드 기체는 그때 폴백이 없다는 경보 로그). 종료 때 감독기 스레드를 먼저 멈추고 어댑터를 닫는다.

### 2차 리뷰 반영 (2026-11-18)

- **표식은 전환 요청 전에 쓴다(R1).** STOPPING에서 호스트에 `switch`를 요청하기 직전에 표식(`phase: SWITCHING`)을 쓰고, 쓰지 못하면 요청하지 않고 정지·경보를 유지한다(R6). 호스트가 거절·되돌림(ROLLED_BACK/REFUSED)으로 끝나면 표식을 지운다. 호스트 FAILED(되돌림 실패)나 시간 초과는 표식을 남긴다. 읽을 수 없거나 깨진 표식은 "있음"으로 본다(hold).
- **재시작 복구는 호스트 단계가 정한다(R2).** 표식이 있으면 백엔드가 slam이든 localization이든 WAITING(hold)으로 시작한다. SWITCHED면 확인 시점 **이후**에 받은 LOCALIZED(map)를 기다리고(slam 설정으로 뜬 CORE는 준비 게이트도 바꾼다), SWITCHING·FAILED·알 수 없음·읽을 수 없음은 계속 hold하며 다시 묻고 180 s 뒤 경보한다. 호스트가 FAILED/ROLLED_BACK/REFUSED/IDLE이고 `backend=slam`으로 확인될 때만 표식을 지우고 감시(slam 설정) 또는 비활성(localization 설정)으로 돌아간다.
- **hold는 늦은 SWITCHED로도 안 풀린다(R3).** 90 s 시간 초과로 FAILED가 된 뒤에도 5 s마다 호스트를 묻고, 늦은 SWITCHED면 WAITING으로 간다. `reset()`은 호스트가 `backend=slam`이고 SWITCHED가 아닐 때만 허용한다. hold가 켜진 동안 Fleet의 자세 답은 line-follow 재개(`on_pose_answered`)를 부르지 않고 요청도 닫지 않는다.
- **배선 실패(R4)**: 감독기를 못 만들어도 CORE는 뜨되, 표식이 있거나 확인할 수 없으면 `assist.hold = slam_fallback_unavailable`로 목표를 거절한다.
- **R5**: 전환 중 호스트 상태 호출을 먼저 하고 정지 증거를 그 뒤에 쓴다. 전환 재시작 중 teleop은 틱(1 s)마다 지울 뿐 거절 문은 없다 — 이 한 틱 안의 입력은 허용된 위험이다.
- **R7**: 표식은 ACTIVE가 된 뒤에도 지우지 않는다. 이후 모든 CORE 재시작·재부팅은 호스트가 SWITCHED를 말하는 동안(root `reset` 전까지) 다시 WAITING_LOCALIZATION을 거치고, 그동안 Fleet 벽 동점 처리(`wall_tiebreak`)도 켜진다. 안전한 쪽이지만 평범한 재시작에도 그렇다.

### 검증 (Validation / Transition)

- 호스트(원격): `operations/fleet/test/test_wall_grid.py`(격자 규칙·결정성·실제 지도 왕복·읽기 경로), `tools/capture/test/test_map_health.py`(아레나 상자), `middleware/core/services/test/test_slam_health.py`(판정과 히스테리시스).
- 두 번째 착지: `test/test_navigation_fallback_host.py`(정지 먼저 거절·sha 불일치 거절·`commit_runtime` 경로·재시작 실패 되돌림·부팅당 한 번), `test/test_host_agent.py`(`machine` 등급, 허용 목록·계약 문서 일치), `middleware/core/services/test/test_slam_fallback.py`(감독기 정책·SLAM으로 안 돌아감), `middleware/core/gateway/test/test_slam_fallback_wiring.py`(어댑터·hold·준비 게이트 교체·상태 블록·경로), `operations/fleet/test/test_wall_fallback_fleet.py`(카메라 동점 처리·벽 격자 밀기).
- 아직 없는 것: 감지 기준값 실측(일부러 지도를 다시 저장한 SLAM 실행·납치 시험), 벽 지도 AMCL 정확도(LiDAR-벽 자세 도구와 비교), 거울 복구, 재시작 시간, 정지-0 속도 증명의 실물 확인, 호스트 에이전트 샌드박스에서 `/var/lib/rosy/maps` 쓰기, 안전 경로 분리 착지와 API 버전 선점. 기체·현장 수용은 없다.
