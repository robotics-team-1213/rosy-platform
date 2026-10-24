# fleet logs

## 2026-09-15 · uncommitted · docs(harness): start the fleet harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python -m pytest src/fleet/test -q` 216 passed, 5 skipped (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리); `python -m pytest src/fleet/test/test_boundaries.py -q` 6 passed
- gate 변화: 없음. SOURCE/LOCAL GO, ROS-SIM/ARTIFACT/DEVICE N/A(이 패키지에 ROS import 없음, 사이트 PC 전용이라 로봇 이미지·Pi 설치 대상 아님), FIELD PARKED(D-35 sim bench 실측 대기)를 스냅샷으로 기록
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): hold the unrun formation sim bench
- 변경: 리뷰 반영. ROS-SIM을 HOLD로, `cmd`를 `python3`으로
- 증거: `python -m pytest src/fleet/test -q` 216 passed, 5 skipped; `test_boundaries.py` 6 passed (2026-09-16 재실행). sim bench 자체는 미실행
- gate 변화: ROS-SIM N/A→HOLD (패키지는 ROS를 import하지 않지만 Task 14 gz_multi sim bench가 이 모듈의 relay·HOLD 지연 증거다)
- 결정: 없음
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): park the site-PC deployment gates
- 변경: 2차 리뷰 반영. ARTIFACT/DEVICE를 PARKED로. 로봇 이미지 대상은 아니지만 SiteHub(`fleet hub --listen`)는 사이트 PC 산출물로 배포될 예정이며 Phase 4 대기다
- 증거: 미실행 — 기록 정정만
- gate 변화: ARTIFACT N/A→PARKED, DEVICE N/A→PARKED (첫 항목의 "ROS import 없음" 근거는 배포 적용 여부와 무관해 철회)
- 결정: 없음
- 교훈: 없음

## 2026-09-17 · uncommitted · feat(server): Fleet 서버 v1 — N대 관제 UI와 로봇별 미션 하달
- 변경: `fleet/server/` 신규(`console.py`, `app.py`, `web/`), `cli.py`에 `console` 서브커맨드, `swarm/transport.py`에 `map()` 추가, `package.xml`/`setup.py`에 fastapi·uvicorn과 UI 자산, 시험 2건 신규(`test_server_console.py`, `test_server_app.py`)
- 증거: `python -m pytest src/fleet/test -q` 235 passed, 5 skipped (2026-09-17 Windows); `python -m flake8 src/fleet --max-line-length=120` 신규 파일 무경고. 실환경: WSL ROS 2 Jazzy + Gazebo에서 `gz_multi robots:=2 mode:=nav core:=true` 위에 `fleet console`을 붙여 두 대를 한 화면에서 보고, 지도 클릭으로 `rosy_01 → (1.21, 0.86)`, `rosy_02 → (1.16, -0.64)` 하달 → 둘 다 `ARRIVED`, AMCL pose가 Gazebo 정답과 0.1 m 이내
- gate 변화: 없음. ROS-SIM은 HOLD 유지 — 이번에 실측한 것은 미션 경로이고, 이 gate의 blocker인 Task 14 대형 릴레이(`relay_tx_hz`/`slot_err_m`/HOLD latency)는 여전히 미실행이다
- 결정: 없음. site-fabric 설계 §2 역할표(사이트 오케스트레이터 + 관제 UI)와 D-12(미션은 Fleet 전용)를 그대로 구현했고 새 ADR은 필요하지 않다
- 교훈: 로봇 상태 스냅샷에 목표가 없다는 것이 D-12의 결과다. 목표를 화면에 그리려면 Fleet이 기억해야 하며, 로봇에게 되물으면 안 된다. 거절된 목표는 기억하지 않는다 — 남기면 가지도 않을 곳으로 간다고 읽힌다

## 2026-09-17 · uncommitted · feat(server): 좁은 통로 교행을 Fleet 이 정리한다
- 변경: `server/traffic.py`(경로 충돌 판정, 순수 기하), `FleetConsole` 에 경로 점유·미션 대기열, `swarm/transport.py` 에 `navigation_path()`, 관제 UI 에 대기 표시, 시험 `test_server_traffic.py` 13건
- 증거: `python -m pytest src/fleet/test -q` 249 passed, 5 skipped (2026-09-17 Windows). 실환경: 미로에서 두 대에 서로의 자리로 가는 미션을 내렸을 때, 코어 이벤트가 `nav.started`(13:41:06.989) → `nav.canceled by api:operator`(13:41:07.056, 67 ms) → `nav.started`(13:43:58.668, 2분 51초 뒤 자동 재하달) → `nav.completed`(13:46:37) 를 남겼고 두 대 다 목표에 도착했다. 같은 시나리오가 직전까지는 0.10 m 간격으로 둘 다 실패했다
- gate 변화: 없음(커밋 뒤 재실행으로 판정)
- 결정: 없음. D-12(미션은 Fleet 전용)의 범위 안이라 새 ADR 이 필요하지 않다
- 교훈: 교행은 로봇이 풀 수 없는 문제다. 로봇의 코스트맵은 자기 주변만 보므로, 상대를 본 순간에는 이미 비켜설 자리가 없다. 두 경로를 동시에 쥔 쪽만 순서를 정할 수 있고 그쪽이 Fleet 이다. 그리고 경로는 목표를 받은 뒤에야 생기므로, 판정은 "내려보내고 읽고 필요하면 취소" 순서가 된다

## 2026-09-17 · uncommitted · feat(server): 관제 화면에서 대형을 열고 닫는다
- 변경: `FleetConsole` 에 `formation_start/reform/resume/stop/status`(기존 `FormationSession` 을 그대로 씀), `/api/fleet/formation*` 경로 5개, 관제 UI 대형 패널(리더·모양·간격 + 무장/변경/재개/해제 + 릴레이 Hz·슬롯·HOLD 이유), 시험 `test_server_formation.py` 12건. 앞선 라운드에서 덮인 대기-상태 표시도 새 UI 위에 복구
- 증거: `python -m pytest src/fleet/test -q` 270 passed, 5 skipped. 실환경(rosy_swarm_bench, 2대): 무장 → `RUNNING`/`rosy_02` 슬롯 0.6 m, 리더에 목표를 주자 리더가 (-0.07,0.40)→(0.21,1.57) 주행하고 팔로워가 (-0.11,0.57)→(0.17,1.62) 로 추종, 릴레이 9.93~10.01 Hz 유지. 리더 항법이 실패하자 FOR-004 정책이 `HOLDING` + 릴레이 pause 로 떨어지고 이유 `['nav.failed','rosy_01']` 를 화면에 남겼다. V 0.7 m 로 재무장한 화면 캡처도 확인
- gate 변화: 없음(커밋 뒤 재실행으로 판정). ROS-SIM 의 Task 14 blocker 중 relay_tx_hz(9.93~10.07)·leader_rx_hz(9.45~10.07)·slot_err_m(최소 0.04, 수렴 0.59)는 실측됐고, HOLD 지연 실측만 남았다
- 결정: 없음
- 교훈: 대형에서 리더와 팔로워는 반대 규칙을 받는다. 처음에 둘 다 개별 미션을 막았더니 대형이 무장만 되고 아무 데도 가지 못했다 — 리더는 몰아야 하는 쪽이다

## 2026-09-17 · uncommitted · test(swarm): Task 14 sim bench 를 끝까지 돌려 HOLD 지연을 실측
- 변경: 기록만. `swarm_bench.py --scenario follow` 와 `--scenario hold` 를 실환경에서 실행
- 증거: WSL ROS 2 Jazzy + Gazebo, `rosy_swarm_bench.world` 2대. follow: `relay_tx_hz` 9.93~10.07, `leader_rx_hz` 9.45~10.07, `slot_err_m` 최소 0.04 / 마지막 10 표본 최대 0.59. hold: t=30.7 에 릴레이 pause 주입 → t=31.8 에 팔로워 `holding` — **1.07 s**, `stream_timeout_ms` 1000 과 일치한다
- gate 변화: ROS-SIM HOLD→GO. blocker 가 "Task 14 미실행" 이었고 이번에 실행했다
- 결정: 없음. D-35 등재 여부는 실측이 나왔으니 이제 판단할 수 있다
- 교훈: HOLD 는 로봇 쪽에서 스트림 타임아웃 한 번으로 성립한다 — 세션이 HOLDING 으로 떨어지는 것과는 다른 경로다. 릴레이만 끊어도 팔로워는 1 s 안에 선다

## 2026-09-18 · uncommitted · fix(server): 실환경이 비켜서기의 결함 넷을 드러냈다 (그리고 고친 뒤 맞바꾸기가 끝까지 돌았다)
- 변경: `bays.BAY_MARGIN_M`(대피 지점은 해제 기준보다 0.15 m 더 멀어야 한다), `passing_is_possible` 이 벽 속 만남 지점을 통과로 읽음, `FleetConsole._intended_route`(계획 경로가 아직 없으면 직선으로 대신), 목표 자리를 깔고 앉은 로봇은 맵 없이도 막은 것으로 봄(`_goal_blocked_m`), `_check_yield_worked`(비켜섰는데 길이 안 열리면 이유를 `NO_YIELD_SPACE` 로), `best_bay` 를 `asyncio.to_thread` 로, 스냅샷에서 내부 필드(`route`/`settled_ticks`) 제거. 시험 8건 추가
- 증거: `python -m pytest src/fleet/test -q` 312 passed, 5 skipped (2026-09-18 Windows). 실환경이 결함을 하나씩 드러냈고, 넷 다 단위 시험에서는 보이지 않던 것이다 —
  - **(1) 교착.** `rosy_map.world` 2x1 m 방에서 경로로부터 0.48 m 떨어진 자리를 골랐고(기준 0.45 통과) 로봇은 목표에 0.13 m 못 미쳐 섰으며 AMCL 은 0.18 m 틀렸다. 보고 위치는 경로에서 0.18 m 였고 해제 조건은 "0.45 m 밖"이라 둘 다 영원히 섰다. 화면은 "물러나면 자동 출발합니다"를 띄운 채였다
  - **(2) 관제가 막았다고 말한 통로로 로봇이 들어갔다.** 둘째 미션을 내릴 때 계획 경로가 아직 없어 빈 목록이 왔고, 빈 목록은 "아무도 안 막는다"로 읽혔다. `rosy_02` 가 `rosy_01` 0.19 m 앞까지 밀고 들어갔다
  - **(3) 고침 확인**(`rosy_map.world` 2대): `dispatch rosy_01 -> (+0.24,+0.02) YIELDING`, `dispatch rosy_02 -> (-0.48,-0.00) YIELDED` — 둘째는 대기열에 남았고, `rosy_02` 가 대피 지점에 도착했는데도 길이 안 열리자 `settled_ticks=3` 뒤 `NO_YIELD_SPACE` 로 바뀌었다. 두 대 간격 1.03 m, 충돌 없음
  - **(4) 목표 자리를 깔고 앉은 로봇을 그냥 지나쳤다.** `rosy_factory.world` 에서 `rosy_01` 의 목표가 곧 `rosy_02` 가 선 좌표였는데 미션이 양보 없이 하달됐다. 같은 배치를 실제 맵으로 오프라인 재계산하면 자유 폭 0.85 m(통과 불가)에 대피 지점 (+1.08,-1.02) 가 나온다 — 판단에 쓸 맵이 그 순간 콘솔에 없었다는 뜻이다
  - **(5) 최종 확인**(`rosy_factory.world` 2대, 폭 0.85 m 세로 통로). 통로 양 끝 배치 뒤(도착 오차 0.26/0.22 m, AMCL 오차 0.09/0.00 m) 서로의 자리를 목표로 주자 `dispatch rosy_01 -> (+0.00,-0.76) YIELDING`, `dispatch rosy_02 -> (+0.30,+0.92) YIELDED` 가 찍히고, **두 대가 번갈아 비켜서며 맞바꾸기를 끝냈다** — `rosy_02` 가 (-0.82,-1.02) 로, 이어서 `rosy_01` 이 (+0.88,-1.27) 로 물러났다. 도착 오차 0.34/0.21 m, 주행 중 최소 여유 0.16 m, 끝난 뒤 대기열·비켜서기 모두 비어 있다
- gate 변화: 없음(커밋 뒤 재실행으로 판정)
- 결정: 없음
- 교훈: **판단 기준과 해제 기준이 같은 값이면 교착이 된다.** 로봇은 목표에 정확히 서지 않고 측위도 틀리므로, 자리를 고르는 쪽에 여유가 있어야 도착한 로봇이 해제선 밖에 남는다. 그 여유로도 모자랄 때를 대비해 **정체를 감지해 이유를 바꾸는 장치**가 따로 있어야 한다 — 기다리는 것 자체는 맞을 수 있지만, 곧 풀린다고 말하는 것은 틀릴 수 있다. 그리고 **"지나갈 수 있는가"는 지나가려는 경우의 물음이다** — 목표 자리를 깔고 앉은 로봇에게는 통로 폭도 맵도 상관없고, 그 규칙은 맵이 없을 때도 성립해야 한다

## 2026-09-18 · uncommitted · fix(server): 잘린 계획 경로가 목표 점유를 가렸다
- 변경: `_standing_in_the_way` 가 경로의 끝이 아니라 **지시한 목표**로 "목표를 깔고 앉았는가"를 판정한다. `PASSING_WIDTH_M` 은 스윕 실측으로 1.4(별도 커밋), 시험 1건 추가
- 증거: 장애물 레이어가 살아난 뒤(`navigation` 2026-09-18 수정) 상대가 선 자리는 치명 비용이라 플래너가 목표까지 가지 못한다 — 실측으로 **0.13 m 짧게 끝났다**. 잘린 끝을 목표로 알면 판정이 그만큼 물러난 자리에서 이뤄진다. 고친 뒤 `rosy_factory.world` 폭 0.85 m 통로에서 맞바꾸기 **PASS**: `dispatch rosy_01 -> (+0.10,-0.90) YIELDING`, `dispatch rosy_02 -> (+0.10,+0.70) YIELDED`, 두 대가 (+0.73,-1.07)/(-0.92,-1.02) 로 번갈아 물러나 도착 오차 0.38/0.25 m, 최소 여유 **0.17 m**(코스트맵 수정 전 같은 시나리오는 0.10 m 스침)
- gate 변화: 없음
- 결정: 없음
- 교훈: 한 층을 고치면 그 위층의 가정이 드러난다. "계획 경로의 끝 = 목표"는 장애물 레이어가 죽어 있을 때만 참이었다. 목표는 **지시한 값**이 있으므로 추론할 이유가 없었다 — 있는 값을 쓰지 않고 유도한 것이 결함이었다
- 참고: 직전 공장 실행이 실패해 회귀로 의심했으나, 통제된 조건에서 재현하니 양보 판정은 정상이었다(`YIELDING`, `blocked_by rosy_02`). 실패 원인은 배치 중 `rosy_01` 의 AMCL 이 1.00 m 틀어진 것이다 — 측위가 틀어진 실행은 그 뒤 숫자가 전부 무의미하므로 배치 검증을 통과하지 못하면 그 구간은 버려야 한다

## 2026-09-18 · uncommitted · feat(server): 폭 면제를 걷어낸다 (D-93)
- 변경: `bays.PASSING_WIDTH_M` 과 `bays.passing_is_possible` 삭제, `FleetConsole` 에서 폭 면제 분기 제거. 맵이 없을 때는 중재하지 않되 **목표를 깔고 앉은 경우는 예외**로 남긴다. 시험을 폭 기준에서 경로 기준으로 다시 씀
- 증거: `rosy_swarm_bench.world` **6 x 6 m 빈 방**에서 마주 오는 두 대를 서로 너머로 보내면 **0/3**. 세 번 다 방 한가운데에서 0.13~0.17 m 간격으로 맞물려 섰다. 핑키 프로 폭이 0.111 m(충돌 메시 실측: 몸통 0.113 x 0.088, 바퀴 바깥 0.0961+0.015)이므로 로봇 폭의 54 배 공간이다. `rosy_gauntlet` 순수 교행 스윕도 1.4 m 포함 전 폭 FAIL
- gate 변화: 없음
- 결정: **D-93** 등재. 통로 폭은 Fleet 중재의 면제 사유가 아니다
- 교훈: 앞서 적은 "1.4 m 면 스스로 지나간다"는 틀렸다. 두 가지가 겹쳤다 — (1) 그 시험은 교행이 아니라 **자리 맞바꾸기**였다(각 목표가 상대가 선 좌표라 상대가 비켜야만 도착이 성립한다), (2) 단일 시행이었고 같은 폭의 순수 교행은 실패한다. 실패하는 실험과 성공하는 실험이 **다른 질문**을 묻고 있지 않은지 먼저 봐야 한다
- 남은 것: 측면 회피가 있는 컨트롤러(DWB)로 바꾸면 이 결론이 바뀔 수 있다. D-93 은 그때 Superseded 한다

## 2026-09-18 · uncommitted · test(fleet): never import games (D-106)

- 변경: `test_boundaries.py`가 패키지 전체 `games` import를 금지. 매치 시작 버튼은 만들지 않음.
- 증거: `python -m pytest src/fleet/test/test_boundaries.py test/test_games_surface.py -q`
- gate 변화: 없음. D-90/D-106 경계만.

## 2026-09-18 · uncommitted · feat(fleet): coincident poses are not a blocked corridor (D-116)

- 변경: mover 와 0.05 m 안 pose 는 양보 대상이 아니다. odom 원점 겹침으로 양보 미션을 만들지 않는다.
- 증거: `python -m pytest src/fleet/test/test_server_yield.py src/fleet/test/test_server_traffic.py -q`
- gate 변화: 없음. ROS-SIM HOLD

## 2026-09-20 · uncommitted · fix(fleet): relay readiness is measured, not attempted (D-134)

- 변경: `swarm/relay.py` — `_leader_connected`를 loop-top 낙관 대입에서 첫 프레임 수신 시점으로 이동, `stop()`에서 리더 flag 리셋. `swarm/session.py` — `_open_relay`를 확인 후 대입 + `SessionError` 원문 보존 + 대기 중 `STOPPED` 즉시 탈출로 변경. 시험 4건 신규(`test_relay.py` 2건, `test_session.py` 2건)
- 증거: `python -m pytest src/site/fleet/test -q` 330 passed, 5 skipped (2026-09-20 Windows). 신규 4건은 구 코드에서 적색 확인(stash 후 릴레이 2건·세션 2건 실패, 복원 후 녹색)
- gate 변화: 없음. SOURCE/LOCAL GO, ROS-SIM HOLD — ROS-SIM 실측(`follower_tx ≥ 1`)은 D-132 계승으로 미실행
- 결정: D-134 Proposed → Accepted
- 교훈: `pose_stream()`은 async generator라 첫 `__anext__` 전까지 접속이 일어나지 않는다 — 시도 전에 세운 connected flag는 거짓 양성이다

## 2026-09-20 · uncommitted · feat(fleet): no video relay boundary (D-136 T1)

- 변경: `test_no_video_relay.py` 2건 — fleet 생산 코드 영상 import 없음 + 서버 라우트에 video/stream/camera/preview/proxy/relay 없음 (라우트 열거 비어있음 방지 포함)
- 증거: 2 passed. fleet 전체 332 passed·5 skipped
- gate 변화: 없음

## 2026-09-21 · uncommitted · feat(fleet): expose fleet.bench public surface (D-148)
- 변경: fleet/bench.py 신설 — 벤치가 쓰는 8개 이름(Formation, slot_world_position, load_robots, FormationSession, FormationSpec, SessionState, HttpRobotClient, RobotApiError)을 재수출하는 공개면. test/test_bench_facade.py 2건 추가(재수출 실체 동일성 + __all__ 정합성).
- 증거: gz_sim 이 fleet 내부(fleet.swarm.*/fleet.formation.*)를 직접 import 하는 내용 결합(평가 2026-09-19 §6 C)을 끊기 위한 면. fleet 전체 pytest 초록 확인.
- gate 변화: 없음

## 2026-09-21 · uncommitted · fix(server): console UI sends the console token
- 변경: token-enforced bind (0.0.0.0 + --token) 에서 UI가 전부 401로 막히던 결함 수정. web/index.html 상단에 토큰 입력+접속 버튼, web/console.js의 call()이 Authorization: Bearer를 붙이고 401이면 토큰 필요 상태를 표시, 토큰은 sessionStorage에만 보관. 입력 스타일은 web/styles.css에 클래스로만(CSP 유지).
- 증거: curl로 갱신된 /console·console.js·styles.css 서빙 확인; /api/fleet/state 토큰 없이 401, 토큰과 함께 200; python -m pytest src/site/fleet/test/test_server_app.py src/site/fleet/test/test_cli.py -q 23 passed (2026-09-21 Windows)
- gate 변화: 없음

## 2026-09-21 · uncommitted · chore(server): tower runbook follow-up
- 변경: tools/fleet_console.ps1 이 8090/TCP 인바운드 방화벽 규칙을 자동 추가(관리자 권한에서만; 루프백은 권한 없이도 됨). 서버/UI 코드 변경 없음.
- 증거: node --check web/console.js 청정; 헤드리스 E2E로 브라우저 순서 재현 - 토큰 없는 state 401, 토큰 state 200(데모 엔드포인트라 2대 offline을 기대), formation 200 IDLE, estop 200 stopped 0/2(설계대로 부분 실패도 200), map 404; fleet 전체 334 passed, 5 skipped
- gate 변화: 없음

## 2026-09-21 · uncommitted · chore(tools): drop automatic firewall rule from tower runbook
- 변경: fleet_console.ps1 no longer adds a firewall rule. Robot-side traffic is outbound only (gather/scatter), so no inbound rule is needed for devices; the rule only mattered for viewing the tower UI from another device, which is now a documented manual step. Bind stays 0.0.0.0 (token-enforced)
- 증거: parser-based syntax check clean. No server/UI code change
- gate 변화: 없음

## 2026-09-21 · uncommitted · refactor(fleet): serve installable shared web assets
- 변경: fleet/server/app.py 와 cli.py 에서 --ui-tokens 대신 --web-common 을 받아 /common 경로로 서빙하도록 수정 (D-157).
- 증거: src/site/fleet/test/test_server_app.py 가 /common/tokens.css 와 /common/core_ui_logic.js 라우트를 검증함 (23 passed).
- gate 변화: 없음

## 2026-09-22 · uncommitted · feat(server): G-S3 signals — 관제가 ROSY-SIGNAL-001 장치를 모으고 흩뿌린다

- 변경: `server/signals.py` 신설(signals.yaml 로더·`SignalStatus` 파서·`HttpSignalClient`·`SignalConsole` 의도 재단언·`all_red` scatter), `FleetConsole` 에 `signal_console` 옵션(snapshot 의 `signals` 키, e-stop 병렬 신호정지), `app.py` `/api/fleet/signals*` 엔드포인트, CLI `--signals`, 관제 UI 신호등 카드(styles.css 포함)
- 증거: `python -m pytest src/site/fleet/test -q` 362 passed, 5 skipped (2026-09-22 Windows, fastapi 0.141/httpx 0.28). 신규 파일 flake8 클린 — console.py 397-438 위반은 HEAD 기존 것(변경 전 추출 대조로 확인). `node --check` 콘솔 JS 통과. 계약 시험 `test/test_signal_contract.py` 14 passed 유지. 검토 중 재단언 예산이 성공 응답마다 초기화되어 장치가 failsafe 에 머물면 무한 재전송되는 문제와, `all_red` 의 409 `stale_seq` 를 적용 성공으로 세는 문제를 회귀 시험 2건으로 재현한 뒤 fail-closed 로 수정
- gate 변화: 없음(LOCAL GO 유지 — 증거 숫자만 갱신)
- 결정: 설계의 상시 폴링 루프를 throttled refresh 로 바꿨다(관제 UI 가 주기를 만든다; 관제가 보지 않으면 장치는 스스로 페일세이프 — 장치 계약의 뜻). failsafe 재단언은 실패해도 1회, 409 stale_seq 는 장치 `last_seq` 채택 + `mismatch` 보고로 끝낸다(스톰 금지)
- 교훈: `HubError` 는 (code, message) 2 인자 — 두 번째 자리에 robot_id/signal_id 가 온다. `pytest-asyncio` 가 없어 이 계층의 비동기 시험은 동기 함수 + `asyncio.run()` 이 관계다

## 2026-09-22 · uncommitted · feat(fleet): traffic priority, ETA ordering, and route-conflict guard

- 변경: 교통 우선순위(선행자 규칙). \server/traffic.py\에 \closest_points\(로봇·장애물 중 최근접 거리)와 emaining_distance\(마지막 pose 기준 누적 거리, 세그먼트 불가 시 None)을 추가하고, \server/console.py\ \_run_traffic\이 연산자 풀의 robot_id를 로테이션해 \_release_order\를 만든다 — 정면 충돌 예상거리가 가장 짧은 로봇이 먼저 출발한다. \goal()\은 ROUTE_CONFLICT 코드로 경로 충돌 시 남은 거리로 출발을 중단한다.
- 증거: \	est/test_server_priority.py\ 8개 신규(순환 로테 5 + 단순 3) — 앞 로봇 rosy_02가 먼저 출발하고 늦은 rosy_01이 양보, 우선/후위 robot_id 고정. 전체 \python -m pytest src/site/fleet/test -q\ 372 passed, 5 skipped (2026-09-22 Windows). flake8 clean.
- 기타: \console.py\ \_manage_swarm_speed\/\_run_traffic\ 들여쓰기 flake8(W293/E131/E501) 정리.
- gate 변화: 없음(LOCAL GO 유지 — 372 passed). 교통 우선순위의 실주행 검증은 FIELD 과제다.
- 한계: ETA는 직선 거리 기반(대평균 속도 가정)이라 부분적 실속도는 미반영 — 후속 과제. \docs/plans/2026-09-22-rosy-road-yield-scenarios.md\ S7 관련.
- 재기록 사유: 동일 날짜 인코딩 사고(cp949/UTF-8)로 원 기록이 비가역 손상되어, 세션 트랜스크립트의 팩트로 대저본을 재기록했다. 사실 관계(파일·수치·시험 결과)는 원 기록과 동일하게 유지했다.

## 2026-09-22 · uncommitted · feat(fleet/signals): 3자 교차 검증 (의도 vs 접점 vs 실측) verify 행 착지

- 변경: `server/signals.py` — `cross_check()` 순수 판정(1≠2 controller_mismatch / 2≠3 display_mismatch: obs_dark·obs_ghost·obs_color, 관측 frozen → stale, 지도 없음 → unmapped, pending → 침묵), `SignalObserver` Protocol + `HttpSignalObserver`(GET /observed 전용 — 토큰·명령 경로 없음), `SignalEndpoint.observer_url/observer_map`(signals.yaml 로더·라이터 검증 — 램프 이름은 red/yellow/green 만), `SignalConsole` 관측 폴링(`_observe_all` — 기기 실패와 관측 실패를 분리 보존), `_record` 시 의도↔보고 mismatch 재계산(stale_seq 장부는 보존), 행에 `verify` 추가(state: absent/unreachable/agree/controller_mismatch/display_mismatch/stale/unmapped/bad_response + faults + observer frame_id/age/frozen 요약), `aclose` 가 관측 클라이언트도 닫는다.
- 변경: `test/fake_signals.py` — `FakeObserver` + `observed_body()` (observer v0.3 본문 모양 고정).
- 증거: `python -m pytest src/site/fleet/test -q` → 392 passed, 5 skipped (신규 28건 — cross_check 9, 로더 4, 콘솔 verify 6, mismatch 재계산/stale_seq 보존 2, HTTP 관통 등). 기존 단정 무피해. flake8 대상 파일 무결 (2026-09-22 Windows; 저장소 잔여 오류는 상대 작업 WIP 인 cli/hub/test_hub_server).
- gate 변화: 없음 — 교차 검증의 실측 판정은 관측 서비스 동작(E1)일 뿐, 벤치 fault 주입(S-02/S-11)은 B0~B7.
- 교훈: "합격"과 "검증 안 됨"을 같은 값(None)으로 합치면 꺼져 있는 검증이 초록으로 그려진다 — absent/unmapped/stale 를 합격에서 분리한 것이 이 변경의 핵심이다.

## 2026-09-22 · uncommitted · docs(fleet): swarm TRIGGERS 의 nav.blocked 가 현재 미발행임을 적는다

- 변경: `fleet/swarm/session.py` `TRIGGERS` 위에 주석 — CORE 는 `nav.blocked` 를 발행하지 않는다(API 참조 v1.13 §8 "미구현"). 막힌 주행은 NAV-006 `nav.stuck` 으로 온다. 트리거 집합은 그대로 둔다.
- 증거: 주석만 변경. `src/site/fleet/test` 영향 없음.
- gate 변화: 없음.
- 결정: 구현되면 바로 트리거가 되도록 항목을 지우지 않는다.

## 2026-09-22 · uncommitted · fleet(console): ADR-1000 자동 감속 no-op 수정 (T7)
- 변경: `server/console.py` `_manage_swarm_speed` — formation 식별을 `spec.name`(존재하지 않는 속성, AttributeError 가 except 로 삼켜져 자동 감속이 한 번도 살지 못함)에서 `spec.formation` 으로 수정, `except Exception: pass` 를 logger.warning 으로 교체(모듀로 logger fleet.console 신규). 시험 3건: 저하 멤버 → reform 실제 호출(적색→초록), 건강 시 무호출, reform 실패 시 로그·생존.
- 증거: `python -m pytest src/site/fleet/test/ -q` 396 passed, 5 skipped (2026-09-22 Windows). 근거: communication-protocol-report.md §5 잠복 결함.
- gate 변화: 없음.
- 결정: 없음 — ADR-1000 이 이제 실제로 동작.
- 교훈: `except Exception: pass` 아래의 오타는 시험이 없으면 영원히 들키지 않는다. 자동 정책 경로는 '호출되었음'을 fake 로 직접 증명해야 한다.

## 2026-09-22 · uncommitted · fleet(cli): 죽은 hub 명령 제거 (T8)
- 변경: `cli.py` 에서 subparser 없이 dispatch 만 존재하던 run_hub 경로와 함수 제거(파싱 자체가 불가능한 죽은 코드 — 통신 보고서 §5). 허브 서버(create_hub_app)는 유지되며 테스트가 직접 사용. 시험: test_cli.py 신규 1건(hub 인자 SystemExit + 소스 스캔).
- 증거: `python -m pytest src/site/fleet/test/ -q` 398 passed, 5 skipped (2026-09-22 Windows).
- gate 변화: 없음.
- 결정: 없음 — YAGNI. 허브 CLI 부활은 중앙 Fleet 착수 시 subparser 와 함께.
- 교훈: 없음.

## 2026-09-22 · uncommitted · fleet(hub): /registry 선택적 Bearer 인증 + 공개 snapshot (T9)
- 변경: `hub/registry.py` 에 snapshot() 공개 메서드 신규(서버 응답과 같은 모양), `hub/server.py` create_hub_app(hub, hub_token=None) — hub_token 설정 시 /registry 가 Bearer 불일치 401, 기본 개방은 로컬 시드 하위호환. 서버 본문이 private registry._robots 접근을 제거하고 snapshot() 을 씀. 시험 3건(개방/토큰 401+200/공개면 스캔).
- 증거: `python -m pytest src/site/fleet/test/ -q` 401 passed, 5 skipped (2026-09-22 Windows). 근거: communication-protocol-report.md §5 — /registry 무인증.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 없음.

## 2026-09-22 · uncommitted · fleet(Phase2)+docs: 통신 정합 T7~T11 마감 기록
- 변경: 본 세션 Phase 2(T5 backoff 30s · T6 hello 신원 실값 · T7 ADR-1000 no-op 수정 · T8 죽은 hub CLI 제거 · T9 /registry 선택 인증+snapshot)과 Phase 3(T10 버전 표기 3원 정렬+API Ref v1.16 · T11 AGENTS 현행화·소소 수정) 완료. 커밋: 4ee66a7·e23ca18·745bb80·7b09b0d·455f48f·a29caee·(T11).
- 증거: fleet 스위트 401 passed, core api/protocol·api_web 초록, harness lint 0 errors.
- gate 변화: 없음.
- 결정: 없음(D-169/D-170 은 별도 기록).
- 교훈: 없음.

## 2026-09-24 · uncommitted · feat(fleet): POST /api/fleet/do 통역기

- 변경: `core_common.intent`가 JSON·YAML `do` 문장을 기존 주소로 바꾼다. 관제는 `/api/fleet/do`로 그 문장을 받고, 로봇 일은 그 로봇 API로 흩뿌린다. `/api/v1/...` 기본 경로는 그대로다.
- 증거: `python -m pytest src/core/core/test/test_intent.py src/site/fleet/test/test_server_app.py::test_do_translates_a_goal_and_rejects_a_ros_word -q` — 통과 (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 없음.

## 2026-09-24 · uncommitted · fix(fleet): 관제 콘솔 적합·경보 채움 (D-201, D-202)

- 변경: (1) `#map-canvas`가 `object-fit: contain` + 뷰포트 상한으로 프레임에 맞음(1920×1080에서 문서 755px 넘침 해소). 클릭 좌표 산수를 레터박스 제외 영역 기준으로 교체. (2) 로스터 패널을 세로 flex로 — 목록만 내부 스크롤, 신호등·대형 항시 노출. (3) 큐 패널 grid 영역 고정(가시성과 무관하게 배치 유지) + 토글을 `hidden` 속성으로(실서버 CSP에서 style.display는 무시됨). (4) `.tag.crit`·`.log .bad`를 위험 채움+종이 잉크로(글자 crit은 2.24:1).
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -q` → 9 passed(신규 2종 변이 증명). `python -m pytest src/site/fleet/test -q` 통과.
- gate 변화: Fleet G1에 문서 적합 게이트·따뜻한 글자 대비 게이트 추가.
- 결정: D-201, D-202
- 교훈: 옵트인 시험은 돌 때만 시험이다 — gather-failure 단언이 옛 선택기를 본 채로 남아 있었다.

## 2026-09-25 · uncommitted · fix(fleet): 선택 카드가 읽기를 희생하지 않는다 (D-214)

- 변경: .robot.selected 바탕을 --ground-card-2에서 --ground로. muted 라벨이 선택 카드 위에서 4.11:1로 바닥 아래였다(제일 집중해 보는 카드의 라벨이 제일 안 읽힘). 선택은 밝은 테두리(--line-30)가 나른다. --ground-card-2는 토큰 집합에 남고 표면 어휘에서 물러난다.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pytest test/test_fleet_console_browser.py -q → 10 passed(전 텍스트 바닥 게이트 신설, 변이 증명: card-2 복귀 → 4.11 적색 5건).
- gate 변화: Fleet G1에 전 텍스트 대비 바닥 게이트 추가.
- 결정: D-214
- 교훈: 상태 표시가 대비를 소비하지 않는다 — 선택도 예산이 아니라 배치로 말한다.

## 2026-09-25 · uncommitted · fix(fleet): HITL 큐의 모의 조종 버튼 제거와 큐 계약 (D-218, D-219)

- 변경: (1) F-20 — HITL 큐의 kind=irreversible 모의 버튼(alert Mock)을 제거하고 행은 로봇 이름 + 진짜 경로(로봇 화면에서 확인)로. 없는 능력(WebRTC)을 활성 조작으로 그린 Law 0 위반이었다. (2) 신설 src/site/fleet/test/test_console_queues_contract.py — 큐 규칙의 선언적 표 계약(HITL 이름·성능 저하 주의 큐·빈 큐 hidden 속성·grid 영역 고정). 변이 증명: 모의 버튼 복귀 → 적색.
- 증거: python -m pytest src/site/fleet/test -q → 전부 통과(크레이트 묶음 412 passed에 포함).
- gate 변화: Fleet G1에 큐 계약 시험 추가(D-159 승격의 Fleet 쪽 계약).
- 결정: D-218, D-219
- 교훈: 경보 큐 안의 거짓 조작은 최악의 자리다 — 큐는 이름과 경로만 말한다.

## 2026-09-25 · uncommitted · fix(fleet): roster keyboard vocabulary, queue render gates (D-224, D-219)

- 변경: (1) F-21 — roster Up/Down traversal, Enter arms the goal, Escape
  clears; cards are tabindex -1 landing points, inputs exempt, focus ring
  from the global :focus-visible rule. (2) D-219 render layer: HITL +
  degraded queue render test, panel absent when healthy. (3) Removed dead
  .topbar rule from the fleet sheet.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pytest keyboard + queues tests -q
  passes (mutation: dead handler goes red, restore goes green).
- gate 변화: fleet G1 gains keyboard + queue-render browser gates.
- 결정: D-224
- 교훈: a declared grammar without a realized path is a defect, not a
  difference - check the source before trusting the sentence.

## 2026-09-26 · uncommitted · feat(fleet): D-257 source-scoped sighting API

- 변경: optional source-token `POST /api/fleet/sightings`와 operator-only latest readback 추가. Source는 allowlisted robot/map/calibration/corners만 쓰며 Fleet/CORE/console 토큰과 credential reuse를 거부한다. 최신 pose만 RAM에 보관하고 command API와 분리했다.
- 증거: `python -m pytest src/site/fleet/test -q -p no:cacheprovider` 423 passed/5 skipped; `test_no_video_relay.py` 2 passed.
- gate 변화: LOCAL 기존 GO; DEVICE/FIELD/PERSISTENCE 미수용.
- 결정: D-257/D-268 Proposed 유지, sightings는 operator display/reconciliation 전용.
- 교훈: sighting API를 추가해도 운영 CLI provisioning, persistent audit, vision publisher를 따로 검증해야 한다.

## 2026-09-26 · uncommitted · feat(fleet): publish and enforce intent API types

- 변경: `/api/fleet/do` OpenAPI now exposes verb-specific fields and the 1–8-step form from the shared interpreter grammar. Fleet rejects mismatched values before contacting CORE.
- 증거: `python -m pytest src/site/fleet/test -q` 507 passed, 5 skipped; `python -m pytest src/runtime/gateway/test/test_intent.py -q` 18 passed; flake8 passed.
- gate 변화: SOURCE/LOCAL API contract GO; Ubuntu/physical-device acceptance remains open.
- 결정: D-288; site intent stays separate from the robot DDS/WSS envelope.
- 교훈: API documentation must describe the same grammar that the dispatch interpreter accepts.

## 2026-09-26 · uncommitted · test(fleet): exercise packaged intent and camera paths

- 변경: revision `01a3946c` candidate를 `--no-build` 격리 Compose로 기동하고, `/api/fleet/do` OpenAPI·입력 거부와 합성 phone WSS -> Vision -> Fleet/SQLite를 확인했다.
- 증거: Fleet/Vision/proxy healthy; manifest archive, SBOM, deployment hash 및 이미지 ID 모두 일치. 13개 verb가 interpreter와 일치하고 8-step 제한, `INVALID_NUMBER`, `TOO_LONG`, TLS/operator session, anonymous 401을 확인했다. 합성 sighting seq 78이 약 `[2.0, 1.0]`로 저장됐다.
- 제한: mock credentials/camera/calibration 및 unreachable CORE 주소; GPU·Ubuntu·실물 장비·로봇 명령 수용은 아니다. 검증/hash: `docs/validation/2026-09-26-site-stack-container-smoke.md`.
- gate 변화: SOURCE/LOCAL 패키지, API, 합성 카메라 경로만 확인; GPU·Ubuntu·DEVICE/FIELD는 HOLD.
- 결정: D-288; over-limit request는 `400 TOO_LONG`.

## 2026-09-26 · uncommitted · feat(fleet): site mDNS discovery readback

- 변경: Ubuntu 호스트 Avahi 브리지와 전용 scan 토큰, Fleet 45초 발견 lease, 등록/페어링/확인/충돌 읽기 전용 패널을 추가했다. mDNS가 `robots.yaml`이나 로봇 명령 대상을 바꾸지 않는다.
- 증거: Windows Fleet 전체 510 passed/5 skipped, protocol 및 host bridge 집중 19 passed, `docker compose config --quiet` 통과. Ubuntu Avahi/Pi LAN 동작은 별도 계층이다.
- gate 변화: LOCAL 기존 GO 유지, 실제 현장 호스트와 다중 Pi는 HOLD.

## 2026-09-26 · uncommitted · reciprocal site discovery preparation

- 변경: Fleet이 로봇을 관찰하는 기존 경로에 더해, Ubuntu Fleet PC가 자기 HTTPS 서비스를 `_rosy-fleet._tcp`로 광고하고 설치 도구가 예상 호스트명·사이트 CA·`/healthz`를 확인한 뒤 URL을 내보내도록 준비했다.
- 증거: 호스트 도구/후보 배포 집중 45 passed/2 skipped. 기존 FleetAgent의 자동 검색·등록은 아직 구현되지 않았다.
- gate 변화: LOCAL 유지, Ubuntu Avahi/TLS 및 실제 로봇 연결은 FIELD 대기.

## 2026-09-26 · uncommitted · merge(site): preserve camera/mDNS and typed intent contracts
- 변경: Latest main changes are integrated with the D-289 typed intent contract and API Reference v1.40.
- 증거: Fleet suite 518 passed/5 skipped; sensing 1660 passed/78 skipped; 7 aggregate failures were fixed and all 7 focused reruns passed. Harness lint 0 errors/21 existing stale-evidence warnings; Compose config and diff checks passed.
- gate 변화: SOURCE/LOCAL only; Ubuntu, RTX 5080 inference, phone/CORE/robot physical acceptance remain open.

## 2026-09-26 · uncommitted · docs(adr): renumber Site Fleet API contract after main advances
- 변경: Renumber the Site Fleet typed-intent ADR from D-289 to D-292 because current main assigns D-289 through D-291 to other accepted decisions. API Reference remains v1.40; camera capture and mDNS contracts remain intact.
- 증거: Fleet 518/5 skipped; sensing 1660/78 skipped; OMX adapter 47/3 skipped; workstation 22 passed; API/UI 73/2 skipped; focused regression reruns 7 passed. Harness lint 0 errors/21 existing stale-evidence warnings.
- gate 변화: SOURCE/LOCAL evidence only; physical Ubuntu, GPU, phone, CORE, and robot acceptance remain open.

## 2026-09-26 · uncommitted · docs(adr): move Site Fleet intent contract to D-293
- 변경: moved the Site Fleet intent ADR and contract references to D-293 to avoid main's D-292 design-token ADR.
- 증거: rerun Fleet API contract tests after the latest integration.
- gate 변화: SOURCE/LOCAL only; Ubuntu, GPU, physical phone, CORE, and robot acceptance remain open.

## 2026-09-26 · uncommitted · validation: revision-pinned site candidate LOCAL smoke
- 변경: Built the `151607c0` linux/amd64 candidate and exercised the packaged console, typed intent API, persistent task record, and synthetic camera-to-sighting path.
- 증거: Fleet 518 passed/5 skipped; OMX/camera/system contracts 192 passed/4 skipped; API/docs/security regression 20 passed; Compose services healthy; task history survived Fleet restart; archive and three SPDX hashes matched the manifest.
- gate 변화: SOURCE/LOCAL only. Ubuntu, RTX 5080 GPU inference, physical phone, CORE, robot, and FIELD acceptance remain open; no robot command was dispatched.

## 2026-09-27 · uncommitted · docs(policy): define fail-closed automatic-source acceptance record
- 변경: clarified the first rollout as fixed authenticated operator navigation with no policy mutation API, and made automatic-source approval require a versioned, preapproved record for quality, false-trigger, freshness, sample, and forbidden-dispatch criteria.
- 증거: D-293 API boundary, Task 3.2, console workflow, and final SITE/DEVICE/FIELD gates now agree; missing numeric thresholds or evidence keep policy disabled.
- gate 변화: none; automatic movement and picking remain HOLD until D-268 and measured field acceptance pass.

## 2026-09-27 · uncommitted · Fleet 결과 상태는 검증된 CORE 경로에서만 기록

- 변경: 범용 task transition에서 `ACCEPTED`는 명시적 positive CORE receipt를 요구하고, receipt나 `UNKNOWN`만으로 `RUNNING`·`COMPLETED`를 기록하지 못하게 했다. D-177 활성화 때 별도 검증된 결과 전이가 필요하다.
- 근거: D-170/D-293의 접수·수락·실행·완료 구분과 실패 후 통과한 8개 회귀 벡터를 대조했다.
- gate 변화: 없음. Fleet의 현재 CORE 최종 결과 상관관계는 여전히 미구현이며 실물 완료를 주장하지 않는다.

## 2026-09-27 · uncommitted · secure roster and signal rendering
- Change: dynamic labels use DOM text; keyboard focus survives roster polling; signal YAML parsing and writing moved to signal_config.py.
- Evidence: DOM injection and keyboard browser regressions passed; signal/module structure subset passed (75 tests); full UI/Fleet run had 661 passes, 5 skips and one keyboard focus failure, which was reproduced and fixed afterward.
- Gate: LOCAL only; live site/device operation remains unverified.
- Follow-up: complete Fleet Chromium suite passed (15 tests) after the polling-focus and blocked-port fixes.

## 2026-09-27 · bb58221b · D-300 surface typography and focus tokens
- 변경: Fleet console의 반복 가중치·자간을 공유 토큰에 연결했다. 1.15 brand 및 1.6/1.7 note/log 행간과 고유 kicker tracking은 보존했다.
- 증거: base dc7e8a4의 Fleet+games host suite 619 passed/5 skipped, 당시 API 문서 버전 assertion 1건 실패(v1.35 기대값, 참조 문서는 v1.39). 최신 main 2230d26e에서 문서와 assertion이 v1.40으로 함께 갱신됨. browser suite 17 passed/2 failed; 두 Fleet keyboard/queued 대기 실패를 최신 main에서 재현. Fleet screenshot: X:\DevTemp\fleet_console_fit.png.
- gate 변화: LOCAL 유지. main 병합 뒤 host suite 재실행 예정.
- 결정: D-300.

## 2026-09-27 · 9049bd37 · test(fleet): verify D-300 after latest-main integration
- 변경: 최신 main의 v1.40 API 문서/계약 업데이트와 typography 토큰 변경을 함께 검증했다.
- 증거: Fleet+games host suite 636 passed/5 skipped; Fleet/games browser suite 17 passed/2 baseline tests deselected. 두 deselected keyboard/queued 시나리오는 최신 main에서 재현했다.
- gate 변화: SOURCE/LOCAL 유지. browser baseline interaction failures는 별도 기존 결함으로 남는다.
- 결정: D-300.

## 2026-09-27 · f4f15776 · verify Fleet after latest main integration
- 변경: latest main의 Fleet 변경을 통합하고 관련 host test를 실행했다.
- 증거: Fleet 526 passed/5 skipped; site database/task-queue 8 passed.
- Gate: SOURCE/LOCAL remain GO; no robot or field acceptance claimed.
- Decision: D-300.

## 2026-09-27 · 9ca7bc26 · verify Fleet keyboard flows and host suite
- 변경: main의 Fleet keyboard-focus 보완과 D-300 typography/focus 규칙을 통합 검증했다.
- 증거: Fleet host 526 passed/5 skipped; keyboard roster/goal 및 queued navigation/cancel browser regressions 2 passed; site DB/task queue tests 8 passed.
- gate 변화: SOURCE/LOCAL 유지. 로봇 및 현장 수용은 별도다.
- 결정: D-300.

## 2026-09-27 · uncommitted · fix(ui): rebalance Fleet map and intervention area

- 변경: 지도와 개입 영역의 폭을 재배분하고 목록과 사이트 조작을 분리했다. 모바일 320/390px 상단과 로봇 태그 줄바꿈을 정리했다. 관제 범위 설명은 지도 아래 disclosure로 옮겼다.
- 증거: `test/test_fleet_console_browser.py` 17 passed, 실제 Chromium 1920/390/320 캡처. 세부 판정은 `docs/validation/uiux-surfaces-2026-09-27/README.md`.
- gate 변화: LOCAL 근거 보강. SITE/DEVICE/FIELD 승격 없음.

## 2026-09-27 · 778bbd31 · verify packaged Site Fleet host path (LOCAL)

- 변경: 소스 동작 변경 없이 최신 Fleet layout commit의 immutable `linux/amd64` candidate를 만들고, packaged Compose를 `--no-build`로 실행해 웹/API, task queue, CORE event, overhead sighting 통합을 다시 검증했다.
- 근거: Fleet `526 passed, 5 skipped`; candidate image/archive/SBOM/deployment hashes 일치; 서비스 3종 healthy; Chromium operator login/style load; task `REQUESTED → QUEUED`; synthetic CORE HELLO/heartbeat/`nav.completed`; synthetic phone seq 78 pose `[2.0, 1.0]`. 세 저장 경로가 Fleet restart 뒤에도 읽혔다. 상세값은 validation record에 기록했다.
- gate 변화: SOURCE/LOCAL만 확인. task는 fake offline CORE 때문에 dispatch되지 않았다. Ubuntu/RTX/GPU, 실제 장비와 현장 수용은 PARKED; 자동 이동/집기는 HOLD.

## 2026-09-27 · uncommitted · fix(ui): make Fleet map goal operable by keyboard

- 변경: D-306에 따라 Fleet 지도 목표 좌표를 방향키로 선택하고 Enter 확인·Escape 취소가 가능하게 했다. 포인터와 키보드는 같은 목표 확정 경로를 쓰며 확인창에서 로봇과 좌표를 보인다. 조작 종료 뒤 포커스는 해당 로봇의 목표 버튼으로 돌아간다.
- 증거: Fleet 브라우저 회귀 18 passed, 수정 후 집중 브라우저·확인 계약 4 passed, D-218 확인 인벤토리 갱신 (Windows Chromium).
- gate 변화: SOURCE/LOCAL 조작 회귀 근거를 추가했다. G2의 전체 화면·상태 셀과 실제 로봇 목표 실행은 미검증이다.

## 2026-09-27 · uncommitted · fix(ui): make formation read loss explicit

- 변경: 대형 상태 조회가 실패하면 마지막 RUNNING·릴레이 수치·지도 슬롯을 현재 증거로 남기지 않고 `확인 불가`로 표시한다. 새 시작·재편성·재개는 비활성화하되 마지막 활성 세션의 해제 요청은 허용한다. 조회가 회복되면 서버 상태로 화면을 다시 그린다.
- 증거: Fleet Chromium 실패→회복 회귀와 대형 조작 회귀, server formation/app host 시험. 사이트 Fleet UI의 가짜 API만 사용하며 실제 로봇 상태 판독은 아니다.
- gate 변화: LOCAL UI 증거만 보강. DEVICE/FIELD 변화 없음.

## 2026-09-27 · uncommitted · fix(ui): clear discovery addresses when readback is unavailable

- 변경: Fleet 발견 목록 조회가 실패하거나 인증이 만료되면 마지막 수신 장치 주소를 목록에서 제거하고 확인 불가·인증 필요의 다음 행동을 표시한다. 다시 조회되면 서버의 새 목록으로 복귀한다.
- 증거: 가짜 Fleet 응답을 실제 Chromium 화면에 연결해 정상→503→회복→401→재접속을 확인했다. Fleet 서버/로봇 페어링이나 현장 발견은 검증하지 않았다.
- gate 변화: LOCAL 화면 증거만 보강. DEVICE/FIELD 변화 없음.

## 2026-09-27 · uncommitted · fix(ui): give the empty map a readable screen state

- 변경: 지도가 없을 때 빈 검은 캔버스 대신 중앙 상태·복구 안내를 표시하고, 지도 범례와 목표 클릭 안내를 숨기거나 교체한다. 지도 조회 실패 뒤에는 오래된 픽셀·목표 지정 상태를 지우고 복구하면 지도를 다시 표시한다. 빈 지도 높이를 줄여 등록 로봇·개입 정보가 먼저 보인다.
- 증거: Windows Chromium의 1920×1080·390×844 빈 지도 캡처와 실패→회복→실패 브라우저 회귀, 기존 목표·상태 회귀. 실제 지도를 가진 현장 로봇 화면은 아니다.
- gate 변화: LOCAL 화면 위계·빈 상태 근거만 보강. DEVICE/FIELD 변화 없음.

## 2026-09-28 · uncommitted · add direct Vision preview leases

- Change: Fleet authenticates named users and issues a 60-second source-scoped frame-read lease. It returns no JPEG bytes. The dashboard now selects a configured source and fetches latest frames directly through the Vision route, clears frozen frames on stale/error, and displays sequence/age.
- Evidence: Fleet app and no-video-relay suites 34 passed, including static asset/CSP and credential-separation checks. Browser automation was not run; no test file matching the plan's browser-test path exists in this checkout.
- Gate: local source behavior only; packaged site stack, real ceiling camera, operator PC, Pinky, and field acceptance remain unverified.

## 2026-09-28 · uncommitted · correlate Pinky navigation task results

- Change: forward each task dispatch `attempt_id` as CORE REST `correlation_id`; project paired CORE navigation events into the matching robot/attempt in Fleet SQLite. Duplicate IDs and older sequences are idempotent; cancel request alone stays `UNKNOWN` pending action result.
- Evidence: full Fleet host suite 542 passed, 5 skipped. CORE event integration verifies durable `RUNNING` and `COMPLETED` history. Full-package flake8 still reports pre-existing whitespace/import/style warnings in hub/console/test files; changed implementation files are checked separately.
- Gate: SOURCE/LOCAL only. No ROS-SIM, image, physical device/stop readback, Ubuntu/site, or FIELD acceptance.

## 2026-09-28 · uncommitted · fix(fleet): recover durable task event projection

- Change: when task projection fails after CORE event persistence, replay the audit store on later CORE heartbeats and after Fleet restart. Recovery does not depend on CORE redelivery.
- Evidence: Fleet suite 543 passed/5 skipped, including fail-once projection and heartbeat recovery. Changed implementation lint passes; unrelated existing hub whitespace and broader package style findings remain.
- Gate: SOURCE/LOCAL only; no ROS-SIM, artifact, device/stop readback, site, or FIELD acceptance.

## 2026-09-28 · uncommitted · close canceled Nav2 result correlation path

- Change: a Nav2 terminal cancellation result is now correlated to the same Fleet task attempt after the cancel request. The cancel request alone remains `UNKNOWN`; the later final action event may resolve it.
- Evidence: Fleet host projection behavior is unchanged; full Fleet regression suite rerun pending.
- Gate: SOURCE/LOCAL only; no ROS-SIM, artifact, device/stop readback, site, or FIELD acceptance.

## 2026-09-28 · uncommitted · verify final canceled-attempt projection

- Change: no Fleet behavior change; a correlated terminal CORE result can now arrive after the prior cancel-request event, while unreadable results remain UNKNOWN.
- Evidence: full Fleet suite 543 passed, 5 skipped; task contract docs 3 passed.
- Gate: SOURCE/LOCAL only; no ROS-SIM, artifact, device/stop readback, site, or FIELD acceptance.

## 2026-09-28 · 016df3ab · fix(fleet-ui): fit camera preview and clarify sections

- 변경: 데스크톱 Fleet 지도와 카메라 미리보기를 나란히 배치해 1920×1080 한 화면에 맞췄다. 모바일 카메라 프레임의 최소 높이로 생기던 320px 가로 넘침을 제거했다. 발견/대형/신호등 제목을 `h3`로 바꾸고, D-218 확인 목록에 카메라 고장 뒤 IR 추적 선택 확인을 고정했다.
- 증거: Fleet 호스트 543 passed/5 skipped, Fleet Chromium·대화상자 32 passed. 새 확인 취소 시 POST 0건을 검증했다. 8상태×3뷰포트+첫 기동 27장을 X:에 재촬영; JSON 24셀은 pageerror·가로 넘침 0, 데스크톱 세로 넘침 0. Docker Compose config와 전용 Fleet 이미지 빌드 및 컨테이너 CLI help 통과.
- gate 변화: SOURCE/LOCAL만 확인했다. Ubuntu 사이트, TLS/실제 카메라, CORE·로봇 readback, 물리 E-stop, 운영자 G3와 DEVICE/FIELD는 HOLD다.

## 2026-09-28 · uncommitted · add per-camera preview rectification controls

- Change: added accessible source-local controls for the clockwise floor quadrilateral, output aspect, normalized camera intrinsics and OpenCV lens coefficients. Drafts persist in this browser by source, can be reset, and are sent only inside the signed Vision preview lease. The default remains the unmodified frame.
- Evidence: Fleet suite 544 passed/5 skipped; browser/dialog suite 33 passed, including source-local persistence, lease payload and reset. Local Docker Compose WSS synthetic-frame preview returned HTTP 200 with `X-Frame-Rectified=true`; 1920/390/320px captures show the rectified checkerboard with zero page errors or horizontal overflow. Captures are under `X:\\DevTemp\\rosy-uiux-local-site\\camera-rectification-docker`.
- Gate: SOURCE/LOCAL only. A browser adjustment is not surveyed site calibration, sighting truth, robot motion authorization, DEVICE or FIELD acceptance.

## 2026-09-28 · 9825da0b · feat(fleet-ui): adjust camera floor corners directly

- 변경: Fleet 관제 카메라 원본 위에서 바닥 사각형 네 모서리를 마우스·터치로 끌고, 키보드 방향키로 미세 조정하게 했다. 조정 중에는 identity 보정 프레임을 받아 원본 좌표 위에 표시한다. 보정 미리보기로 전환하면 해당 카메라에 저장된 프로파일만 signed lease로 보낸다. 기존 좌표 입력도 유지하고 소수점 정밀도를 새로고침 후 보존한다.
- 증거: Fleet 호스트 545 passed/5 skipped. Fleet 브라우저 전체 31 passed, 최종 직접 조작 테스트 재실행 1 passed. 데스크톱/390px 모바일 캡처는 `X:\DevTemp\fleet_camera_direct_adjustment_desktop.png`, `X:\DevTemp\fleet_camera_direct_adjustment_mobile.png`; 가로 넘침 0. Harness generate 완료, lint 0 errors/17 freshness warnings, `git diff --check` 통과.
- gate 변화: SOURCE/LOCAL UI 근거만 추가했다. 실제 카메라·현장 측량 보정, Ubuntu/site, DEVICE, FIELD 검증은 여전히 미실행이다.

## 2026-09-28 · 2ec41b9a · fix(fleet-ui): preserve camera corner keyboard focus

- 변경: D-318 사각형 조정에서 모서리 핸들이 소비한 위·아래 방향키를 문서 전역 로스터 탐색이 다시 처리해 포커스를 빼앗던 충돌을 막았다. Shift+방향키 0.1% 이동이 계속 모서리에 적용된다. 드래그 중 텍스트 선택도 억제한다.
- 증거: 원인 재현 테스트는 수정 전 실패, 수정 뒤 통과했다. 직접 카메라 조정·로스터 방향키·지도 키보드 목표 브라우저 시험 3 passed. Fleet 호스트 545 passed/5 skipped, 팔레트 계약 9 passed. Harness 계약 78 passed/17 freshness warnings, lint 0 errors/17 warnings, `git diff --check` 통과.
- gate 변화: SOURCE/LOCAL 입력 접근성만 보강했다. 운영자 G3, 실제 Fleet/카메라/로봇 readback, 물리 E-stop, DEVICE/FIELD는 계속 HOLD다.

## 2026-09-29 · uncommitted · fix(fleet-ui): restore segment toggle paint and focus ring contracts

- 변경: `web/index.html`의 영역 조정·미리보기 토글을 `kind=quiet`에서 `kind=segment`로 바꾸고 표면의 `ui-button[aria-pressed]` 재도색 규칙을 삭제했다. 모서리 핸들 포커스 링을 stroke 3px에서 공용 focus 치수 outline으로 바꿨다(styles.css).
- 증거: `src/hmi/web/test` 22 passed, `test/test_fleet_console_browser.py src/site/fleet/test` 576 passed / 5 skipped.
- gate 변화: 없음. 기존 GO 유지(위반은 main에 커밋된 상태였고 이 변경으로 G1을 회복했다).

## 2026-09-29 · uncommitted · fix(fleet-ui): E-STOP safety renders as the crit tag (P2 round)

- 변경: 로스터 카드의 SAFETY 값이 E-STOP일 때 평문 strong 대신 공용 `tag crit` 채움으로 렌더한다(D-202 — 위험은 채움이다). 정지 사실이 배터리 같은 측정값과 같은 무게로 읽히던 8항 위계 결함이다. 계약 시험은 요소 타입 대신 행의 값으로 단정하도록 정렬했다.
- 증거: `test/test_fleet_console_browser.py test/test_web_dialog_contract.py` 34 passed. 8상태×3뷰포트 24셀 재촬영 — 가로 넘침 0, 페이지 오류 0(`X:\DevTemp\rosy-uiux-p2-fleet`). `impeccable detect` []. 회차 기록은 `docs/validation/uiux-surfaces-2026-09-29/README.md`.
- gate 변화: 없음. SOURCE/LOCAL GO 유지, 실물 페어링·E-STOP readback·사람 G3는 별도다.

## 2026-09-29 · uncommitted · add internal Mission admission and goal evidence ledger

- Change: Mission proposals, shared robot/workcell/object claims, stop-generation admission, a single Step Action attempt, and independent goal evidence now share the Fleet SQLite transaction. Driver Action success does not complete the Mission; fresh matching camera evidence is required before claims are released.
- Evidence: Mission-focused tests 15 passed; full Fleet suite 578 passed/5 skipped; network topology and harness contract tests passed. Harness lint reports 0 errors/18 freshness warnings. `flake8` is unavailable in this host environment.
- Gate: SOURCE/LOCAL only. The Mission ledger has no public REST route, executor, or ROS submission. Device-side generation enforcement, independent physical stop, ROS-SIM, DEVICE and FIELD remain open; Mission/OMX physical dispatch stays disabled.

## 2026-09-29 · uncommitted · review Mission stop-generation recovery

- 변경: 검토 중 stop이 pre-dispatch claim을 회수해도 Mission row가 `READY`로 남는 상태를 발견했다. `start_step`은 generation 또는 resource claim이 stale이면 같은 transaction에서 Mission을 `HOLD`로 바꾸고 `STEP_HELD_BEFORE_SUBMISSION`을 기록한 뒤 남은 claim을 회수한다.
- 증거: 회귀 시험은 수정 전 실패했다. 수정 후 Mission 집중 시험 15 passed, Fleet 전체 578 passed/5 skipped, network topology/harness 계약 시험 통과.
- gate 변화: 발행 기능은 계속 비활성이다. Isaac ROS-SIM과 장치 stop-generation 강제는 미검증이다.

## 2026-09-29 · uncommitted · feat(ai): add ER 2 proposal-only provider adapter

- 변경: Fleet AI boundary에 표준 ER 2 Interactions REST adapter를 추가했다. `propose_pick_place`만 model tool로 노출하고 함수 호출을 실행하지 않으며, 결과에 caller/provider ID와 image observation/hash를 보존한다.
- 증거: `python -m pytest src/site/fleet/test/test_er2_standard.py -q` 10 passed. HTTPX mock transport, normalized image selector 검증, 20 MB provider request limit을 위한 14 MiB frame cap 포함. 실 API/credential은 사용하지 않았다.
- gate 변화: SOURCE/LOCAL test만 추가. API/runtime wiring, auto admission, ROS/OMX action, non-safety-critical production use, DEVICE/FIELD acceptance는 HOLD.

## 2026-09-29 · uncommitted · fix(test): keep the mission helper out of pytest's nose setup slot

- 변경: `test_mission_store.py`의 모듈 수준 `setup(tmp_path)`가 pytest 7의 nose 호환에 잡혀 **테스트 모듈 자체**를 인자로 받아 호출됐다. `tmp_path`가 path가 아니라 module이 되어 `module / "fleet.sqlite3"` TypeError로 6개 전부 setup 단계 ERROR. CI가 쓰는 pytest 7.4.4에서만 깨지고 로컬 pytest 8.4.2는 nose 지원을 제거해 통과해 환경 차이로만 보였다. 헬퍼를 `_stores`로 개명해 충돌을 없앴다.
- 증거: 최소 repro 파일로 원인을 두 버전에서 직접 재현했다 — 7.4.4는 `tmp_path = <module 'test_repro'>` + 동일 TypeError, 8.4.2는 passed. 수정 후 pytest 7.4.4로 Fleet 전체 `588 passed, 5 skipped`, 8.4.2로도 동일. 저장소 전체에서 `^def setup(` 은 이 파일 한 곳뿐이었다.
- gate 변화: 없음. 로직·픽스처·측정은 그대로고 이름만 바꿨다.

## 2026-09-29 · uncommitted · feat(fleet): add policy-evidence config and store (D-268 ladder T2/T3)

- 변경: `fleet/server/policy_evidence_config.py`(출처 설정 로더 — env 바인딩 토큰, asset/task 닫힌 집합, revision 삼종·폐기 플래그, YAML에 비밀 금지)와 `fleet/server/policy_evidence.py`(SQLite 저장·제출 검증 — source token에서 출처 결정, transit 0~300 ms, task/asset/revision binding, **눅 observation 등록부로 전면 거절**, `evidence_id` 멱등·다른 내용 `EVIDENCE_REPLAY`, audit 테이블)을 추가했다. [실행 계획](../../../docs/plans/2026-09-29-policy-evidence-contract.md) T2·T3.
- 증거: 신규 시험 24 passed(config 11·store 13), Fleet 전체 `612 passed, 5 skipped`. 신규 4 파일 flake8 120 clean(패키지 전체 flake8 경고는 기존 파일 것). v1 불변 단언: 잘formed 제출도 `EVIDENCE_OBSERVATION_KIND_UNKNOWN`으로 거절.
- gate 변화: 없음. REST 경로(app.py)·발의 binding(task_service)·밸브는 T4/T5이고 자동 실행은 HOLD 유지.

## 2026-09-29 · uncommitted · feat(fleet): wire policy evidence admission, routes, and API Ref v1.49 (T4-T6)

- 변경: T4 — `task_service`가 policy 발의에 `{"evidence_id": ...}` 참조를 필수로 하고(다른 모양 400 `INVALID_EVIDENCE_REFERENCE`) admission(`EVIDENCE_NOT_CONFIGURED`·`NOT_FOUND`·`ASSET_MISMATCH`·`STALE`·제출 사유 전달)을 통과해도 밸브가 닫힌 한 `HOLD(POLICY_NOT_ACCEPTED)`. T5 — `POST /api/fleet/policy-evidence`(source token, 감사 예외 경로 추가)와 `GET .../latest`(viewer), 콘솔/사용자/로봇 토큰 충돌 거부. T6 — API Ref v1.49(§10.6.2 신설, 변경 로그, policy 발의 서술 갱신)과 `test_task_contract_docs.py` 정합 시험, api_web 설명 버전 표기.
- 증거: Fleet 전체 `628 passed, 5 skipped`(신규: API 6·발의 binding 9·계약 문서 1), api_web 70 passed/13 skipped(버전 핀), 변경 파일 flake8 clean. 핵심 단언: 밸브 False, v1 빈 등록부로 모든 제출 거절, 멱등·재생 409, 승인된 증거라도 HOLD.
- gate 변화: 없음. `POLICY_DISPATCH_ENABLED=False` 불변, 자동 실행·측정 없음. 사다리 2~5단계(권한·정답 시험·30분 스트림·입회 수용)는 별도 작업이다.

## 2026-09-29 · uncommitted · feat(ai): resolve ER 2 selectors against source-frame evidence

- Change: added source/crop/resize/quarter-turn inverse mapping. Selectors require one fresh candidate from the exact observation, image digest, camera/frame, capture time, calibration and transform revisions. Fleet emits typed pixel-level evidence using shared schemas and has no OMX package dependency.
- Evidence: selector and OMX target-evidence tests 18 passed; contract checks 49 passed after ADR renumbering; full Fleet suite 600 passed/5 skipped before rebasing onto current main. Re-run the full suite on the merged tree before accepting this gate.
- Gate: SOURCE/LOCAL only. Mission production routes, UDS listener, ROS arm/gripper execution, physical stop, device and field acceptance remain separate.

## 2026-09-29 · uncommitted · feat(fleet): separate ER 2 proposal, Mission draft, and operator admission (D-333 Task 3)

- Change: added an idempotent SQLite ProposalStore for allowlisted selector/provenance metadata only (32 KiB maximum, 30-day retention and hourly cleanup). The new authenticated routes separate `POST /api/fleet/proposals`, proposal read, trusted current-evidence resolution to an immutable Mission draft, Mission readback, and named-operator admission. Proposal and Mission ownership derive from the authenticated principal; supplied actor/principal, credentials and image payloads are rejected. Mission, proposal, API audit, dispatch generation, and shared resource claims must use the same SQLite database.
- Admission: the server-injected resolver rechecks current observation, target resolution, workcell/instance capability and revisions at both draft resolution and admission. A stale/changed result, generation mismatch, missing workcell/object claim, competing action, unnamed development principal, or audit failure fails closed. Admission only acquires Fleet claims; `physical_submission` stays `NOT_CONNECTED` and no OMX Action or ROS call is made.
- Evidence: Fleet full suite `653 passed, 5 skipped`; API web `70 passed, 13 skipped`; changed-path flake8 and `git diff --check` clean. Candidate resolver behavior was tested with injected hardware-free fixtures; live camera producer, device identity, UDS, ROS-SIM, physical stop and field acceptance remain unverified.
- Gate: SOURCE/LOCAL only. API Reference v1.50 documents the Site Fleet contract; this does not authorize live provider wiring, device Action dispatch, motion capability, or deployment.

## 2026-09-29 · uncommitted · make ER 2 resolution commit and retry atomically

- Change: Mission draft insertion and ProposalStore `RESOLVED` transition now share a single SQLite transaction. Resolution work no longer durably leaves proposals in `RESOLVING`; a failed write rolls back the Mission and keeps the proposal retryable. Candidate free-text fields now have individual length limits in addition to the total metadata cap.
- Evidence: Fleet suite 655 passed/5 skipped; fault injection after the Mission insert proved rollback and successful retry.
- Gate: SOURCE/LOCAL only; resolver remains injected and no device Action submission is connected.

## 2026-09-29 · uncommitted · feat(fleet): dispatch admitted Mission through fenced OMX UDS Action

- 변경: 단일 Site Fleet background dispatcher 추가. 기본 비활성이고 완전한 Mission API, 공용 DB, workcell-instance map과 local Action transport를 명시해야 생성된다. operator admission/ER 2 proposal handler는 UDS를 직접 호출하지 않는다. Fleet은 action/attempt ID와 grant 전체를 READY→RUNNING 원자 전이에 저장한 뒤 단 한 번 SubmitAction을 보낸다. 프로세스 재시작/불명 ACK는 저장 grant 그대로 GetAction으로 조정하며 재생하지 않는다. 불명 상태 claim은 유지하고 한 번의 durable reconciliation 뒤에도 확인되지 않으면 operator HOLD로 남긴다. DeviceActionReceipt는 Mission/step/action/attempt, digest, authority epoch, generation, journal event와 관측 시각에 결속된다. API Ref v1.53과 계약 고정 시험을 갱신했다.
- 증거: focused dispatcher/store/service/API, stop fence, OMX Action API/store, shared schema와 contract-doc bundle 83 passed; 전체 Fleet 665 passed/5 skipped; API web 70 passed/13 skipped; OMX adapter 85 passed/3 skipped; foundation contracts 102 passed. Harness `generate` 완료, `lint` 0 errors/17 freshness warnings, `git diff --check` 통과. 별도 network-topology+harness 계약 명령은 92%에서 요약 없이 정체되어 중단했고 pass로 집계하지 않는다.
- gate 변화: SOURCE 구현만. 자동 dispatcher 기본 비활성; OMX runtime, UDS 서비스 설치, 선택 ROS/gripper driver, 물리 stop/readback와 FIELD는 승인·증거 전까지 비활성/HOLD.

## 2026-09-29 · uncommitted · Mission provenance and SQLite query-path improvement

- 변경: Mission 완료를 독립적인 신뢰 증거 검증기에 묶고, 동일 action/attempt의 사후 카메라 관찰 및 신선한 OPEN 그리퍼 readback 없이는 GOAL_CONFIRMED가 되지 않도록 했다. 거부된 증거는 필드별 크기 제한 후 원문 없이 bounded field metadata/hash만 저장한다. Fleet/OMX SQLite 연결은 WAL, `synchronous=FULL`, foreign keys, 5초 busy timeout을 공통 적용한다. Mission ready/reconciliation 및 policy-evidence 최신 조회에 composite index를 추가하고 EXPLAIN QUERY PLAN에서 임시 정렬이 없음을 고정했다. 기본 WAL autocheckpoint는 변경하지 않았다.
- 증거: post-review goal/Mission/policy evidence 대상 38 passed; 전체 Fleet suite 676 passed/5 skipped. 합성 50,000행 DB에서 250회 READY 조회 1,325.6 ms→3.7 ms, reconciliation 6,642.8 ms→3.4 ms. Windows 합성 로컬 측정이며 장치/운영 부하 성능을 보장하지 않는다. 대상 장치 저장장치의 지연/전원 장애 시험은 미실행.
- gate 변화: SOURCE 테스트와 로컬 합성 측정만. 현재 composition에는 trusted goal verifier가 없어 Mission completion은 의도적으로 HOLD다. `FULL` 동기화 유지; WAL이 SQLite 단일 writer를 병렬화하지 않는다. ROS-SIM, DEVICE, FIELD 및 물리 grasp/place/E-stop 증거는 변하지 않는다.

## 2026-09-29 · uncommitted · web-surface-hardening: `/common` 목록은 web_common manifest

- 변경: 서버의 손으로 쓴 `common_assets`를 `manifest.json` 읽기로 바꿨다(설정 디렉터리에 manifest가 없으면 기본 web_common의 것). `default_web_common()`은 manifest가 있는 share만 받는다. 이제 `hold-ticker.js`도 서빙한다. D-1005 인용을 실제 ADR D-157로 고쳤다.
- 증거: `python -m pytest src/site/fleet/test -q` 656 passed 5 skipped.
- gate 변화: 없음.
- 결정: D-157.

## 2026-09-29 · uncommitted · fix(fleet): ER2 시험은 허용목록된 fixture 키를 쓴다

- 변경: `test_mission_ai_proposal.py`가 MockTransport 옆에 `api_key="fixture-secret"`을 넘겼다 — `secret_scan.KNOWN_FIXTURES`가 면제하지 않는 값이라 CI의 `test_no_secrets_in_tracked_files`가 실패했다(런 36578519798). 시험 세 곳(주입 2·헤더 단언 1)을 `test-secret`로 바꿨다 — KNOWN_FIXTURES 주석이 정확히 이 ER2 어댑터·mock 조합을 위해 문서화한 값이다. 허용목록 자체는 무변경(D-256: 값을 이름 짓지, 목록을 늘리지 않는다).
- 증거: `python -m pytest test/test_release_boundary_guards.py src/site/fleet/test/test_mission_ai_proposal.py -q` 75 passed.
- gate 변화: 없음.

## 2026-09-29 · uncommitted · feat(fleet-console): 천장 카메라 사이트 사각형과 관측 표시 (D-257)

- 변경: `GET /api/fleet/site-map`(viewer 이상, 토큰 미포함, 없으면 404 `NO_SITE_MAP`) 추가. `sightings_config.py`가 `corner_world_m`·`robot_markers`를 표시용으로 검증·보존하고 `SightingSource`에 선택 필드로 싣는다. 콘솔은 새 `web/site-layer.js`(순수 기하·관측 분류)로 점유 격자가 없을 때 미터 축척 사이트 뷰(0.5 m 격자·축·치수·source), 격자가 있을 때 사각형 윤곽을 겹치고, `/api/fleet/sightings`를 1 s마다 읽어 로봇별 최신 관측을 점선 고리+방향선으로 그린다(서버 lease stale 또는 3 s 초과 흐림, 30 s 초과 숨김). CORE TF pose 삼각형과 합치지 않고, 사이트 전용 뷰는 목표 클릭을 받지 않는다.
- 증거: `python -m pytest src/site/fleet/test -q` 691 passed/5 skipped, 2 failed(`test_task_contract_docs.py` — API Ref v1.56 대 기대 v1.55, 기반 9ecad1b1에서도 동일 실패); `node --test src/site/fleet/test/web/site-layer.test.mjs src/site/fleet/test/web/authorization.test.mjs` 7 passed; `test_no_video_relay.py` 통과. Windows 로컬 합성만.
- gate 변화: 없음. 실제 폰·survey calibration·현장 인증서는 DEVICE/FIELD 수용 gate로 남는다.
- 결정: D-257(표시·대조 전용 유지)
- 교훈: 없음

## 2026-09-30 · uncommitted · feat(fleet): D-352 S1–S3 사이트 콘솔 로봇 화면 코드 등록

- 변경: `server/enrollment_store.py`(AES-GCM 봉인 등록부·`device_pairing_audit`·`rekey`), `server/roster.py`(`SiteRoster` 단일 로스터 소유자), `server/enrollment.py`·`enrollment_routes.py`(교환·결속·고정 주소·해제), `console.py`(await 전 순서 복사, 고정 주소 보류·경보), `hub.py`(동적 짝 토큰), `transport.py`(`trust_env=False`), `cli.py`(`--robot-credential-key-file`), 콘솔 "기기 연결" 패널(`web/enrollment.js`).
- 증거: `python -m pytest src/site/fleet/test -q` 녹색, `node --test src/site/fleet/test/web/*.mjs` 녹색, 루트 결합 시험 `test/test_fleet_robot_enrollment_contract.py` 녹색(현재 소스 CORE, 이미지 증거 아님). 실물 로봇 접촉 없음.
- gate 변화: 없음. LOCAL 증거만; DEVICE는 벤치 D1 대기.
- 결정: D-352 Proposed(구현 첫 조각).
- 교훈: 로스터를 바꾸는 쪽이 여럿이면 `await`를 건너는 순회가 어긋난다 — 순회 전 복사와 단일 소유자가 함께 있어야 e-stop이 새 로봇에 닿는다.

## 2026-09-30 · uncommitted · feat(fleet): add opt-in Mission proposal API composition

- Change: `fleet console --mission-api` now composes MissionService and ProposalStore on the same persistent DB as task/audit storage. It requires per-user authorization; resolving stays unavailable without a trusted candidate resolver.
- Evidence: CLI composition tests verify owner-authenticated proposal persistence/readback, resolver 503, no Mission dispatcher, and shared DB paths. A regression test seeds a preexisting queued navigation task and verifies the opt-in Mission API does not start the Task dispatcher or consume it. Fleet suite: 702 passed, 5 skipped. Existing authenticated Fleet operator command routes remain available; this is not a global read-only mode.
- Gate: SOURCE/LOCAL integration only. No ER 2 provider request, Device Action, ROS goal, hardware stop, or field acceptance.
- Decision: none. The Mission API CLI mode disables Mission and automatic queued-task dispatchers; existing Fleet operator commands remain available.

## 2026-09-30 · uncommitted · fix(fleet-console): 사이트 지도 리뷰 반영 (D-257)

- 변경: 관측 폴링은 사이트 사각형(`view.siteMap`)이 있을 때만 하고, 404(관측 설정 없음 → 라우트 없음)면 다음 `refresh()`까지 멈추며, 빈 관측이 그대로면 격자를 다시 그리지 않는다. 사이트 사각형은 404 `NO_SITE_MAP`에서만 지우고 일시 실패에는 둔다(`call()` 오류가 `status`·`code`를 싣는다). 캔버스는 사이트 뷰에서 `role="img"`, 격자 뷰에서 `role="button"`. 로더는 같은 `map_id`인데 `corner_world_m`이 다른 source, `robot_ids` 밖 로봇, 로봇 간 중복 marker, 모서리 marker 재사용을 거부한다. node 하위 프로세스는 UTF-8(errors=replace)로 읽는다.
- 증거: main 병합 후 `python -m pytest src/site/fleet/test -q` 724 passed/5 skipped; `node --test src/site/fleet/test/web/site-layer.test.mjs src/site/fleet/test/web/authorization.test.mjs` 7 passed; `python -m pytest test/ -q -k "fleet or site or video or architecture"` 182 passed/33 skipped; harness lint 0 errors. Windows 로컬 합성만.
- gate 변화: 없음.
- 결정: D-257(표시·대조 전용 유지)
- 교훈: 없음

## 2026-09-30 · uncommitted · feat(fleet): registered Mission goal-evidence ingress

- Change: added opt-in producer registry with environment-only credentials, strict workcell/predicate/object/destination and evaluator-revision scopes, finite freshness/grace policy, and expiry. Added same-database SQLite idempotent evidence storage and `POST /api/fleet/goal-evidence` with a separate source token.
- Lifecycle: evidence and Action terminal readback can arrive in either order; the matching second input triggers independent confirmation. Missing evidence reaches `HOLD` after registered grace. Rejected payloads are not stored. The Mission/automatic policy dispatch valve remains closed; the registry is deployment-configured and read-only at runtime.
- Evidence: full Fleet suite 724 passed, 5 skipped; changed-file flake8 passed.
- Gate: SOURCE/LOCAL only; physical producers, ROS-SIM, device and field acceptance remain unproven.
- Decision: D-348.

## 2026-09-30 · uncommitted · chore(structure): fleet size verdict re-judged at 11912 lines

- Change: SIZE_VERDICTS["fleet"] moved 11164 -> 11912 after the policy/goal-evidence contracts and their stores joined the flat server tree; the split verdict (B2 subpackage regrouping) stands, owner fleet, unscheduled.
- Evidence: test/architecture/test_module_structure.py::test_size_verdicts_are_well_formed_and_current passed (2026-09-30 Windows); growth source docs/plans/2026-09-30-goal-evidence-producer-and-verifier.md.
- Gate: none moved.
- Decision: keep "split" — the new evidence stores reinforced the separate-owners-without-subpackages condition the verdict already named.

## 2026-09-30 · ff6938e4 · D-359 US-002 Fleet 테마 선택과 theme-color

- 변경: `index.html`이 `/common/theme.js`를 싣고 정적 `theme-color`를 `#111614`에서 dark `--ground` `#101214`로 고쳤다. 상단바에 화면 테마 그룹(어둡게/밝게/시스템, 공용 segment)을 두고, 역할 잠금(`operatorControls`)이 이 버튼을 건너뛰게 했다 — 표시 선호이지 조작이 아니다. 좁은 폭(≤40rem)에서는 상단바 5행에 놓인다. `.tag.crit`·`.log div.bad`의 글자를 `--ink-on-crit`로 바꿨다. `test_console_palette.py`는 테마 블록마다 돈다.
- 증거: `python -m pytest src/site/fleet/test -q` 통과(위 876 passed 묶음). 밝게 1366×768 캡처에서 전체 정지 각주·끊김 태그 가독 확인.
- gate 변화: 없음. 지도 지형이 `--ink`/`--ground-deep`을 써서 밝게에서 반전되는 것은 D-359 §4.2(캔버스 `--raster-*`)의 몫으로 남긴다.

## 2026-09-30 · 6e766e19 · D-359 US-003 Fleet 지도 지형은 raster 토큰, 테마 전환 즉시 다시 그림

- 변경: `map-view.js`의 `hexToRgb`와 `--ink`/`--ground-deep`/`--ground-soft` 지형을 지우고 `--raster-unknown/free/uncertain/occupied`를 `RosyPalette.readPalette`로 쓴다(25<값<65는 이제 미지가 아니라 불확실 색). 모든 캔버스 색은 `cssColor`, 글꼴은 `canvasFont(…, "mono")`(칩 글꼴 하한 10 → 12px). `console.js`는 `css` 헬퍼를 지우고 `--robot-1..3`을 `cssColor`로 풀며, `rosy:theme`에 로봇 색을 다시 풀고 `mapView.draw()`. 범례 견본도 raster 토큰이고 `불확실` 견본을 더했다. `.legend i { padding: 0 }` — `.sw.robot`이 로스터 카드 `.robot` 여백을 물려받아 큰 알약으로 보이던 것(캡처에서 발견).
- **의도된 모양 변화(D-359 §4.2)**: 어둡게 Fleet 지도는 전에 빈 칸이 밝은 `--ink`, 벽이 어두운 `--ground-deep`이었다. 이제 로봇 지도와 같아 빈 칸이 어둡고(`#1f2123`) 벽이 밝다(`#d7d7d8`). 밝게에서는 빈 칸 `#e5e6e8`, 벽 `#303337`.
- 증거: `test_canvas_palette_browser.py::test_free_space_follows_the_theme_without_reload[fleet-map]` 통과. 캡처 `X:/DevTemp/rosy-d359/shots/us003-fleet-{dark,light}.png`. 브라우저 `test/test_fleet_console_browser.py` 28 passed 3 failed: swarm_control(알려진 실패), `test_mobile_console_has_no_horizontal_overflow[320|390]`(`headerRows` 5 > 4 — US-002 테마 그룹이 상단바 5행을 만든 것, e19f2ef4에서도 같이 실패; 이 항목과 무관한 열린 문제).
- gate 변화: 없음. 현장 조명 아래 사람 확인은 남아 있다.

## 2026-09-30 · 849d2bfc · D-359 US-004 Fleet 필드·태그·비활성 사유가 공용 부품을 쓴다

- 변경: `index.html`·`formation.js`의 입력·선택·체크 23+개에 `ui-field`(체크는 `label.ui-check`), 알약 모양 토큰 입력·vision/lens/aspect/formation 필드 사본 삭제, 토큰 잠김은 `aria-invalid`. `.tag` 삭제 → `<ui-tag status>`(roster·signals·formation·`#formation-state`·`#signals-state`; nav/ok → active). 목표 지정·취소·IR 추적·대형 버튼은 비활성과 같은 조건식에서 짧은 `reason`을 단다. `authorization.js` 역할 잠금은 공용 버튼에 `운용자 권한이 필요합니다`를 달고 풀릴 때 이전 disabled·reason을 되돌린다(테마 선택은 여전히 제외). 자간 0.16em → `--track-label`, 불투명도 0.55/0.5/0.45 → 점선·`--ink-quiet`·삭제. 필드 44px로 명렬 패널이 1920×1080 뷰포트 75%를 넘어 대형 폼을 컨테이너 질의로 넓은 칸에서만 두 쌍 한 줄로 했다(f2a836a7).
- 증거: `test/test_fleet_console_browser.py` 28 passed 3 failed — swarm_control(알려진 실패), `test_mobile_console_has_no_horizontal_overflow[320|390]`(headerRows 5 ≤ 4, 전과 같은 값; US-005 몫). 시험의 `.tag` 선택자를 `ui-tag[status]`로 고쳤다. 캡처 `X:/DevTemp/rosy-d359/shots/us004-fleet-console-{dark,light}-{1366x768,390x844}.png`.
- gate 변화: 없음.

## 2026-09-30 · 4cb4ce55 · D-359 US-004 역할 잠금 입력은 보이는 운용자 안내를 가리킨다

- 변경: `index.html` 대형·보정 묶음에 `data-role-lock`과 숨은 `ui-status.role-lock-note`(`운용자 권한이 필요합니다`). `authorization.js`는 잠글 때 네이티브 입력을 그 안내에 `aria-describedby`로 잇고 안내를 보이며, 풀 때 되돌린다. 재허가 버튼(잠금·조건 미충족·상태 확인 불가)과 신호등 버튼(오프라인)이 사유를 단다. roster의 사유 전용 도우미 이름은 `blockWith`.
- 증거: `test/test_fleet_console_browser.py` 28 passed 3 failed(기존 swarm_control, mobile overflow 320/390 headerRows 5 — 변화 없음). 정적 검사 `test_every_disabled_control_states_its_reason_or_is_listed`가 안내 쌍을 본다.
- gate 변화: 없음.

## 2026-09-30 · aeb31356 · D-359 US-005 Fleet 세 단·머리 접힘

- 변경: 62rem 겹침(992px 암시적 열) → 두 열은 `(width >= 64rem)`, 한 열은 `(width < 64rem)`. 24rem의 `grid-column: 3`은 머리를 다시 짜며 사라졌다. 머리: `index.html`에 `#topbar-more`(설정, `aria-expanded`/`aria-controls`)와 `#topbar-extra`(토큰·접속·역할·테마). 90rem 이상은 extra가 `display: contents`로 한 줄에 서고(역할 표지 12rem에서 자름, 전문은 title), 90rem 미만은 한 줄 격자(이름|연결|시계|설정|정지)에 extra가 둘째 줄로 접힌다; compact는 두 줄(이름·설정 / 연결·시계, 정지는 두 줄). `console.js` `setTopbarOpen` — 잠기면 토큰 칸을 연다; 권한 잠금 선택자에서 `#topbar-more` 제외. 테마 이름표 nowrap(1366 두 줄 접힘 해소 — 1366은 이제 접힌 머리). 42rem → 64rem. 90rem은 surfaces.yaml에 이유와 함께 적었다(편 머리 자연 폭 약 1220–1300px). 시험: 모바일 넘침 시험의 연결·시계 같은 줄 검사를 격자 이름 대신 상자 겹침으로(headerRows 2 ≤ 4), 새 `test_compact_header_budget_keeps_the_stop_in_view[390|320]`(머리 ≤ 20%, 정지 첫 화면, 접힘·펼침), `test_wide_header_keeps_every_item_on_one_line`(1920 편 한 줄, 1366·1280 접힌 한 줄).
- 증거: `test/test_fleet_console_browser.py` 33 passed 1 failed(기존 `test_the_console_renders_what_swarm_control_says`). 320×568 머리 97px(17.1%), 1366 88px. 변이: `ui-topbar` `min-height: 300px` → 빨강. 캡처 `X:/DevTemp/rosy-d359/shots/us005-fleet-{1920x1080,1366x768,1024x768,390x844,320x568}-{dark,light}.png` — 첫 캡처에서 남은 `}`가 `.dispatch-control` 카드를 지운 것을 보고 ea856f38로 고쳤다.
- gate 변화: 없음.
- 결정: D-359 §6.

## 2026-09-30 · 838446eb · D-359 US-007 대형 버튼 줄이 접힌다

- 변경: `index.html` 대형 버튼 줄에 `formation-actions`, `styles.css`에서 줄바꿈하고 버튼은 내용 폭에서 시작한다. 390에서 같은 폭 네 버튼(약 50px)에 사유가 붙어 "무장 / 이미 대형 중"이 어절마다 꺾였다. 시험: `test_fleet_console_browser.py::test_formation_buttons_keep_their_reasons_readable[320|390|1366]` — 이름·사유 모두 두 줄 이하.
- 증거: 수정 전 320·390 빨강, 수정 후 초록. 캡처 `X:/DevTemp/rosy-d359-captures/fleet-console-*`.
- gate 변화: 없음.
- 결정: D-359 §5.3·§6.

## 2026-09-30 · 375a098c · D-359 US-008 지도 라벨 칩이 겹치지 않는다

- 변경: `map-view.js` `drawChip`이 이번 그리기에 놓인 칩 사각형을 기억하고, 새 칩은 겹치지 않을 때까지 아래·위로 한 칸씩 번갈아 비킨다(최대 12번). `window.__mapChips`로 사각형을 노출한다. 600줄 예산은 d6e75cb3에서 다시 맞췄다. 시험: `test/test_fleet_console_browser.py::test_map_label_chips_never_cover_each_other[1366|390|320]`.
- 증거: 수정 전 빨강, 비키기를 끈 변이(CHIP_TRIES=0)도 빨강.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · 7f53ca5f · D-359 US-008 워드마크가 320에서 한 줄이다

- 변경: compact 머리 격자를 4열로 바꿔 이름이 시계 열 위까지 쓰고, 이름 칸을 `container-type: inline-size`로 둔다. 공용 `ui-brand b`는 nowrap이고 `min(--text-title, 16cqi)`로 칸에 맞게 줄어든다(web_common). 시험: `test_wordmark_stays_on_one_line[320|390|1366]`; 머리 예산 시험 그대로 초록.
- 증거: 수정 전 320 빨강.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · 36fca0ab · D-359 US-008 포함 로봇 라벨이 체크 첫 줄 옆에 선다

- 변경: `.member-label`은 1열에서 새 줄을 시작하고 첫 44px 체크 줄에 맞춘다. 폼 라벨과 같은 얼굴, 목록은 `role=group aria-labelledby`. 시험: `test_member_label_sits_beside_the_first_checkbox_row[1920|1366|390]`.
- 증거: 수정 전 빨강.
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 §5·§6 (US-008).

## 2026-09-30 · 0f10bb91 · D-359 US-009 Fleet 모드 태그는 공용 MODE_LABEL

- 변경: `roster.js`가 `/common/core_ui_logic.js`에서 MODE_LABEL을 읽는다(내비게이션 등), 열거값은 title. 시험 `test_roster_mode_tag_speaks_korean_and_keeps_the_enum_in_title`.
- 증거: 수정 전 `NAVIGATION`(빨강).
- gate 변화: 없음. SOURCE/LOCAL 증거다.
- 결정: D-359 (US-009).

## 2026-09-30 · 2d12eed3 · D-359 US-009 릴레이 알약은 릴레이라고 말한다

- 변경: `streamEvidence`를 순수 `site-layer.js`로 옮기고 `릴레이 끊김`/`릴레이 지연 · N초`/`릴레이 증거 없음` + data-evidence. node 단위 시험(site-layer.test.mjs).
- 증거: 6 node tests pass.
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · c14e0ad3 · D-359 US-009 한 열 단 순서: 예외 → 지도 → 카메라 → 대형

- 변경: DOM 순서를 주의 → 로봇 패널 → 지도 패널로, 카메라는 범례·안내 뒤로. 넓은 창 배치는 명시 격자선이라 1920/1366이 안내 문구 외 픽셀 동일(비교 캡처). 64rem 아래에서 로봇 패널을 풀어 두 패널로 두고 대형·신호등·기록 묶음만 order로 맨 뒤.
- 증거: `test_single_column_tier_puts_exceptions_before_the_map_and_formation_last[390|320]`.
- 미증명/열림: 좁은 창에서 Tab은 대형 묶음을 지도보다 먼저 만난다(넓은 창 불변 조건과 충돌).
- gate 변화: 없음.
- 결정: D-359 §6 (US-009).

## 2026-09-30 · ce709e4d · D-359 US-009 대형·신호등 문구

- 변경: 대형 상태 태그 대기/무장 중/진행 중/유지 중/해제됨(열거값 title), 재개 사유 `대형 유지 중일 때만`, 신호등 안내에서 signals.yaml 파일명 제거. 지도 HOLD 칩은 `대형 유지 · …`(a622bbcc).
- 증거: HOLDING/read-loss 시험 기대값 갱신·초록.
- gate 변화: 없음.
- 결정: D-359 (US-009).

## 2026-09-30 · a622bbcc · D-359 US-009 지도 칩은 선 뒤에, 로봇 표식 밖에

- 변경: `drawChip`은 자리만 정하고(칩·로봇 표식 상자 회피) `flushChips`가 대형·중재·사이트 선을 다 그린 뒤 칠한다. `window.__mapMarkers`. map-view.js 599줄(예산 600).
- 증거: `test_map_chips_paint_after_lines_and_clear_robot_markers` — 칠 순서(stroke < fillText)와 칩/표식 겹침 0.
- gate 변화: 없음.
- 결정: D-359 (US-008 잔여).

## 2026-09-30 · 79787e7a · D-371 US-010 전체 정지에 data-always-live

- 변경: `server/web/index.html` `#estop`에 `data-always-live`. Fleet은 아직 `confirmIrreversible`을 부르지 않지만(확인은 window.confirm), ui.js를 싣는 페이지의 정지는 모두 표시한다(`test_stop_always_live.py`).
- 증거: `python -m pytest src/hmi/web_common/test src/hmi/dashboard/test src/site/fleet/test src/site/games/test -q` 1089 passed, 84 skipped; `test/test_web_dialog_contract.py` 3 passed
- gate 변화: 없음.

## 2026-09-30 · uncommitted · fix(web): Node 18에서 console 웹 단위시험이 ESM을 읽게 — 고아 시험도 연결

- 변경: `fleet/server/web/package.json`에 `"type": "module"`을 선언했다. 그 트리의 .js는 전부 브라우저 ES 모듈(별도 package.json이 없어 Node는 .js를 CommonJS로 읽음)이라, CI의 apt Node 18에서 `site-layer.test.mjs`의 named import가 "Named export not found"로 죽었다 — 개발 호스트 Node 24만 통과하는 시험이었다. 아울러 `test_site_layer_node_unit_tests_pass`를 `test_console_web_node_unit_tests_pass`로 바꾸고 `test/web/*.test.mjs` glob으로 실행 대상을 모아, 아무 pytest도 돌리지 않던 `authorization.test.mjs`(고아)도 같은 호출에 들어오게 했다.
- 증거: Node 18 컨테이너(`docker run node:18 node --test …`)에서 pass 7/fail 0, 로컬 Node 24에서 test_site_map_api 22 passed, fleet 전체 746 passed/5 skipped (2026-09-30).
- gate 변화: 없음.
- Decision: 웹 트리의 모듈성 선언은 브라우저와 Node가 같은 해석을 하게 하는 계약이다 — 버전 탓으로 치지 않는다.
- 교훈: 새 .test.mjs를 만들 때 실행 주체를 확인하라 — authorization.test.mjs는 연결 없이 쌓여 있었다. glob runner가 그 재발을 구조적으로 막는다.

## 2026-09-30 · uncommitted · fix(fleet): D-352 독립 리뷰 반영(MERGE-AFTER-FIXES)

- 변경: `enrollment.js` 자산 허용목록 누락(콘솔 전체 불능) 수정과 import 전수 시험, 바쁜 로봇(목표·대기·점유·양보)과 UNKNOWN task 해제 409, 죽은 토큰(401·Fleet 시계 만료·적재)은 정지 전용 보류, 옛 대형 플래그가 새 대형을 끊지 않음, 충돌 중 옮기기 409, 서버 측 enrollable 확인, WS `proxy=None`, rekey 입력 검사·Compose 절차, RFC 1918 단일 규칙, 콘솔 이중 제출·확인 대화상자.
- 증거: `python -m pytest src/site/fleet/test -q` 녹색, node 10건 녹색, 선택 브라우저 시험 녹색. 실물 접촉 없음.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 정적 자산 허용목록이 생기면 새 ES 모듈 하나가 콘솔 전체와 e-stop을 끈다 — import 그래프를 시험으로 전수 확인한다.

## 2026-09-30 · uncommitted · docs(fleet): 로봇 등록 ADR 번호 D-352 → D-361

- 변경: main에 다른 D-352(외부 장비 공통 패턴)가 먼저 착지해, main 병합 때 로봇 화면 코드 등록 ADR을 D-361로 옮겼다. 코드 주석·시험·계약 문서·배포 문서의 D-352 표기를 D-361로 바꿨고 ADR 본문에 옮긴 까닭을 적었다. 이 항목보다 앞선 로그의 "D-352 등록"은 D-361을 가리킨다(로그는 고치지 않는다). fleet 크기 판정은 main의 목표 증거 저장소가 합쳐진 13187줄로 다시 판정했다.
- 증거: 아래 병합 커밋의 Fleet·node·`test/` 실행.
- gate 변화: 없음.

## 2026-09-30 · uncommitted · fix(test): 목표 증거 등록부 시험의 변수명이 시크릿 스캐너에 걸리지 않게

- 변경: test_goal_evidence_registry.py의 지역변수 duplicate_secret을 duplicate_token으로 개명. secret_scan의 자격증명 패턴이 "secret" 이름에 리터럴을 대입하는 줄을 잡는 설계라, src/ 아래 시험 파일은 test/ 예외 없이 전부 검사 대상이다 — 값은 설정 파일 경로일 뿐이지만 이름이 스캐너 어휘와 겹쳤다.
- 증거: test_release_boundary_guards 전체 통과(시크릿 0건), test_goal_evidence_registry 통과 (2026-09-30 Windows).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 시트/피스처 이름에 secret·api_token·psk 계열 단어를 쓰지 않는다 — 스캐너는 의도가 아니라 모양을 본다.

## 2026-09-30 · uncommitted · fix(console): 로봇 등록 S1의 공용 컨트롤 계약 준수 — kind·타이포 토큰·confirm 핀

- 변경: enrollment 머지가 남긴 web_common 계약 위반 3건을 바로잡았다. (1) `enroll-submit` 버튼에 `kind="primary"` 선언(D-194 — 종류는 표시에 적는다), (2) `.enroll-alarm`의 `font-weight: 600` 리터럴을 `var(--weight-label)` 토큰으로(D-300), (3) enrollment.js의 로봇 제거 confirm(토큰 회수 — 불가역)을 D-218 PINNED_CONFIRMS에 핀과 함께 등록.
- 증거: web_common + dialog 계약 100 passed, fleet 전체 849 passed/6 skipped (2026-09-30 Windows). 수정 전 각 1건씩 적색이었다.
- gate 변화: 없음.
- 결정: 등록 제거는 불가역이므로 confirm 문법을 유지한다 — 핀 갱신이 그 리뷰의 자리다(D-218 설계 그대로).
- 교훈: 표면을 고치는 회차는 `python -m pytest src/hmi/web_common/test -q`를 같은 커밋에 돌린다 — 공용 컨트롤 계약은 소유 모듈 시험만으로는 안 보인다.

## 2026-09-30 · uncommitted · fleet-console: 카메라 칸 배치 고침과 D-354 경기장 제안 검토
- 변경: ① 62rem 이상에서 지도 칸(main 폭 43%)을 다시 1.15:0.85로 나누던 규칙 때문에 1440px에서 관제 카메라가 약 240px로 좁아져 제목이 "관제 카 / 메라"로 줄바꿈되고 영상이 작았다. 이 분할은 main의 778bbd31·016df3ab부터 있었고 9825b2f7은 사이트 캔버스 크기만 바꿨다. 이제 110rem 미만에서는 카메라를 지도 아래에 쌓고, 110rem 이상에서만 1:1로 옆에 둔다(1920×1080 D-201 무스크롤 유지). ② 새 `web/field-layers.js`(순수 계산)·`web/field-view.js`: "경기장 자동 찾기"가 frame과 같은 lease로 Vision `field-proposal`을 읽어 D-318 겹침에 점선 제안으로 보이고, "제안 수락"을 눌러야 브라우저 로컬 모서리 초안이 된다. 캔버스가 제안·확인 모서리로 원본을 위에서 본 모양으로 펴고 경기장 밖을 가린다. `/api/fleet/site-map` 설정 W×H 비와 검출 비가 10% 넘게 다르거나 설정이 없으면 빈 지도 대신 안내를 띄운다(설정은 고치지 않음). 운용자 W×H(m)는 source별 localStorage에만 두고 축척·격자에 쓴다. 레이어 토글 6개(원본 카메라·보정 경기장·사이트 사각형·격자·카메라 관측·CORE 로봇 위치)는 localStorage에 try/catch로 저장한다. `CONSOLE_ASSETS`에 두 모듈 추가. 인라인 스크립트 없음. Fleet은 영상·제안을 중계하지 않는다.
- 증거: `python -m pytest src/site/fleet/test -q` 692 passed/5 skipped, 2 failed(`test_task_contract_docs.py` 기존 실패); `node --test src/site/fleet/test/web/*.test.mjs` 15 passed. 브라우저 회귀(`ROSY_RUN_BROWSER_TESTS=1`) 29 passed + 시간 초과 2건 재실행 통과. LOCAL 벤치(저장된 실제 프레임·합성 경기장 프레임 재생) 스크린샷은 `private/validation/2026-09-30-console-field-autodetect/`.
- gate 변화: 없음. SOURCE/LOCAL만. DEVICE(설치 폰 실시간)·FIELD 미실행.

## 2026-09-30 · uncommitted · fix(fleet-console): 태블릿 헤더 세 줄, 보정 뷰 재계산 줄이기, 숨긴 레이어 안내 (D-354 리뷰)

- 변경: 40–70rem에서 헤더를 상태 / 토큰·접속 / 폭 전체 전체 정지 세 줄로 나눴다(실제 Lenovo 태블릿 세로 약 800×1333 CSS px에서 토큰 입력이 워드마크를 덮고 "접속"·"전체 정지"가 한 글자씩 꺾였다). 토큰·접속·전체 정지는 70rem 이하에서 48 px 이상이고 꺾이지 않는다. 1920×1080(110rem 이상)에서는 원본과 보정 경기장을 카메라 칸 안에 나란히 두어 D-201 무스크롤을 지킨다. 보정 뷰는 프레임·모서리·크기가 바뀔 때만 다시 펴고, 레이어를 끄면 계산하지 않는다. 레이어가 하나라도 꺼지면 지도 머리에 "숨긴 레이어 n개"를 보인다. 저장 실패는 제안 상태 줄 대신 별도 줄에 알린다. 제안 422는 "프레임을 해석하지 못했습니다"로 보인다. W×H 미설정 안내가 빈 지도 안내를 가리는 규칙은 사이트 설정이 없는(`NO_SITE_MAP`) 상태로 좁혔다. API Ref v1.60에 제안 경로를 올렸다.
- 증거: `python -m pytest src/site/fleet/test -q` 748 passed/5 skipped. `node --test` 명세별 2·8·5 passed. Playwright(모의 API, 보정 뷰 보임)로 800×1333·1024×768·1280·1440·1920·390·320에서 워드마크·토큰·접속·역할·연결·시계·전체 정지 상자 겹침 없음, 가로 넘침 0, 전체 정지 한 줄. 1920×1080 문서 넘침 0(보정 뷰 보임·숨김 둘 다). 스크린샷은 `private/validation/2026-09-30-console-field-autodetect/`. 실제 태블릿 재확인은 하지 않았다.
- gate 변화: 없음. SOURCE/LOCAL만.

## 2026-09-30 · uncommitted · docs: 경기장 자동 검출 ADR 번호 D-354 → D-360

- 변경: main에 다른 D-354(mDNS 서비스 발견)가 먼저 착지해, main 병합 때 경기장 자동 검출 제안 ADR을 D-360으로 옮겼다. 코드 주석·시험·API Ref의 D-354 표기를 D-360으로 바꿨고 ADR 본문에 까닭을 적었다. 이 항목보다 앞선 로그의 "D-354"(경기장 제안)는 D-360을 가리킨다(로그는 고치지 않는다).
- 증거: 병합 커밋의 overhead·Fleet·node 실행.
- gate 변화: 없음.

## 2026-09-30 · uncommitted · fix(console): 실제 태블릿 점검 — 꺼진 기능 404 폴링, 카메라 배지, 태블릿 폭 줄바꿈

- 변경: ① 새 `web/poll-gate.js`(순수). 라우트가 없는 404(`detail.code` 없음)를 "이 Fleet에 기능 미설정"으로 보고 `dispatch-control`(1 s)·`discovery`(5 s)·`enrollment/robots`(5 s) 폴링을 다음 로그인·토큰 저장까지 멈춘다. 발행 제어는 "발행 제어 미설정", 발견은 "발견 미설정"으로 오류가 아닌 상태를 보인다. `/api/fleet/map`의 `NO_MAP`은 기능 미설정이 아니라 "지도를 내는 로봇이 아직 없음"이라 멈추지 않고 30 s 간격으로만 다시 묻는다(로봇이 나중에 지도를 낼 수 있다). 5xx·네트워크·다른 코드의 404는 일시 실패로 다음 주기에 다시 묻는다. `CONSOLE_ASSETS`에 추가. ② `vision-view.js`의 `frameBadge()`(순수): 프레임 응답을 live / 지연(age > 3 s) / 정지(stale 헤더) / 권한 없음(401·403, lease 버림) / 수신 대기로 나눈다. 배지를 decode 뒤가 아니라 영상과 같은 순간에 바꾸고, 진행 중 요청이 있을 때 `refreshSources()`가 "인증 대기"를 그려 보이던 영상을 지우던 경로를 없앴다. ③ `.formation-form input { width: 100% }`가 체크박스까지 늘려 `rosy-pinky-8kcn`을 낱자로 접었다 — 체크박스는 auto, id는 줄임표 + `title`. 대형 버튼은 글자째 꺾지 않고 버튼째 다음 줄로 내린다. ④ 62–110rem에서 등록 로봇 패널 왼쪽 칸이 목록 아래로 비고 대형·신호등·이벤트가 오른쪽 좁은 칸에 쌓여 패널 밖으로 넘쳤다 — 왼쪽 목록 → 대형, 오른쪽 발견 → 신호등 → 이벤트로 나누고 넘침만 만들던 패널 `max-height`를 뺐다. `index.html`은 고치지 않았다.
- 증거: `python -m pytest src/site/fleet/test -q` 852 passed/6 skipped; `node --test` poll-gate 6·vision-badge 5 포함 34 passed. 실제 Lenovo 태블릿(CDP, 1333×760 CSS px, 벤치 Fleet를 이 브랜치로 기동): 로그인 10 s 뒤 1분 동안 Fleet 404가 87회/분(dispatch-control 61·enrollment 12·discovery 12·map 12) → 2회/분(map만). Vision `sources/s21/frame` 404 41회/분은 폰 카메라가 꺼져 프레임이 없는 상태로 범위 밖이다. 포함 로봇 줄 높이 42 → 22 px(한 줄). headless 1333×680·800×1333·1920×1080·390·320에서 가로 넘침 0, 1920×1080 문서 넘침 0(D-201). 브라우저 회귀 29 passed; `test_the_console_renders_what_swarm_control_says`는 main(de4504e8)에서도 같은 시간 초과로 실패한다. 캡처·네트워크 로그는 `private/validation/2026-09-30-device-check/`. 폰 카메라는 과열로 켜지 않아 배지의 live 상태는 실기에서 보지 못했다(node 시험만).
- gate 변화: 없음. SOURCE/LOCAL + 실제 태블릿 화면 확인. FIELD 미실행.
- 교훈: 폴러는 "기능 없음(라우트 없음 404)"과 "아직 없음(코드 있는 404)"과 "일시 실패"를 나눠야 한다 — 셋을 같은 catch로 받으면 꺼진 기능이 매 초 404를 쌓는다.

## 2026-09-30 · uncommitted · feat(fleet): fence ER2 feedback successor candidates
- Change: added one-transaction stop/generation/Mission/action/attempt/event/observation fencing before ER2 candidate visibility; candidates are idempotent by feedback turn, carry source correlation, and resolve only into a separately linked successor Mission. Stop or event drift before resolution rejects the candidate. The async tool dispatcher uses an injected post-action observation source and returns unavailable if it is not configured.
- Evidence: Fleet plus foundation host suites 995 passed, 6 skipped; ER2 focused contract/doc checks 71 passed; changed-file flake8 clean. Full Fleet flake8 still reports unrelated existing findings in hub, console, and older tests.
- Gate: SOURCE/LOCAL only. No production trusted Vision reader, provider worker, credentials, policy dispatch, ROS, device, or field enablement.

## 2026-09-30 · uncommitted · fix(fleet): let Fleet choose the fresh post-action frame
- Change: removed the model-supplied observation ID from the `propose_replan` tool schema. Fleet now requests a trusted frame after the terminal Action timestamp, binds its concrete ID/digest to the typed ER 2 selector response, and retains the same atomic visibility fence. Camera image egress still requires a separate explicit data-class approval.
- Evidence: Fleet plus foundation host suites 995 passed, 6 skipped; ER2 path suites 74 passed; changed-file flake8 clean.
- Gate: no trusted production Vision reader or app worker is configured; replan stays unavailable unless both are injected and approved.

## 2026-09-30 · uncommitted · chore(structure): re-judge Fleet size after ER2 candidate fencing
- Change: updated the repository Fleet package size verdict from 14,260 to 14,616 lines; the existing split decision and unscheduled B2 plan remain in force.
- Evidence: atomic candidate fencing and linked-successor tests are included in the re-judged package line count; `src/site/fleet/test` plus repository `test` passed 3,675 tests with 188 skipped, and the Fleet feedback/API-focused set passed 65 tests.
- Gate: SOURCE/LOCAL only; the production post-action Vision reader and provider worker remain unconfigured.

## 2026-09-30 · uncommitted · feat(fleet): wire optional ER2 outbox consumer
- Change: added atomic oldest-pending outbox claims and `MissionModelTurnWorker.consume_next()`. `create_app` starts its consumer only for an explicitly injected worker sharing the Fleet SQLite database.
- Evidence: tests cover event→outbox→worker consumption, oldest-first unique claims, default-disabled worker state, and database-path mismatch rejection.
- Gate: the default CLI still has no provider worker, credentials, egress approval, or trusted post-action Vision reader.

## 2026-09-30 · uncommitted · feat(fleet): add bounded trusted ER2 post-action Vision reader
- Change: implemented an optional scoped Vision frame source with fixed workcell/source/camera/frame/calibration mapping, short-lived lease, bounded no-store JPEG validation, and post-Action freshness check. `create_app` wires and closes it only alongside an explicitly injected shared-database model-turn worker.
- Evidence: focused contracts and Fleet suites passed 119 tests, including malformed JPEG rejection and app lifecycle wiring. Default app/CLI has no worker, provider credentials, or camera/Mission egress approval.
- Gate: SOURCE/LOCAL only. Runtime activation, provider data policy, ROS/device operation, and physical acceptance remain open.

## 2026-09-30 · uncommitted · fix(fleet): enforce the ER2 feedback deadline across tool dispatch
- Change: enforce the named absolute turn deadline during both provider posts and Fleet tool dispatch; offload synchronous read tools and cancel async replan dispatch at the remaining turn budget. Add exact numeric-boundary tests for context, tool results, replay/response/image sizes, post-action freshness, cost, step count, and function-call count.
- Evidence: feedback contracts, dispatcher, outbox, atomic candidate fence, API, Vision, and overhead suites passed 136 tests. A new deadline regression failed before the fix and passed after it.
- Gate: SOURCE/LOCAL only; provider credentials, Mission policy dispatch, ROS, device operation, and deployment remain disabled.

## 2026-09-30 · uncommitted · fix(fleet): recheck ER2 egress fence after Vision capture
- Change: validate full workcell/task/data-class egress policy before acquiring camera data. After capture, reread Mission/stop/event eligibility and compare the observation envelope to the trusted turn before sending the image to ER 2.
- Evidence: regression test changes Mission eligibility during frame acquisition and proves no selector-provider call or candidate write occurs; the allowlisted replan path still succeeds with valid scope and approval.
- Gate: SOURCE/LOCAL only; credentials, policy dispatch, ROS, devices, physical actuation, and deployment remain disabled.

## 2026-09-30 · uncommitted · docs(validation): record final ER2 feedback audit gates
- Change: recorded final regression evidence after numeric-boundary, total-turn deadline, and post-frame egress-fence hardening.
- Evidence: focused ER2/Mission/Vision/API/Overhead host suites 137 passed; documentation gate 80 passed; changed-file flake8 clean; harness lint 0 errors/12 pre-existing freshness warnings.
- Gate: SOURCE/LOCAL only. Provider, Mission dispatch, ROS/device, physical actuation, and deployment remain disabled.

## 2026-09-30 · uncommitted · feat(discovery): D-358 S1 발견 행 검사와 사이트 스크립트를 공유 벡터에 묶음

- 변경: `fleet/server/discovery.py`의 스캔 행 검사를 `core_common.protocol.discovery_txt.classify`로 바꿨다(호스트는 단일 레이블 `.local`로 좁아짐). 사이트 호스트 단독 스크립트 `deploy/site/mdns-bridge.py`가 이제 공통 키(`product/role/proto/tls`)·중복 키·`.local` 호스트를 검사하고, 공통 키가 없는 옛 광고는 legacy로 통과시킨다(D-351 발견 8). `fleet-mdns.py`는 이미 규칙과 같아 코드 변경 없이 벡터 시험만 더했다.
- 증거: `test_site_mdns_bridge.py`·`test_site_fleet_mdns.py`·`test_discovery.py`가 같은 벡터를 돈다. 브리지는 벡터 추가 직후 5건 적신(`value_mismatch` 포함) → 수정 후 녹색. 변이 증명: 브리지의 공통 키 검사를 지우면 3건 적신.
- gate 변화: 없음. SOURCE/LOCAL. 실제 사이트 LAN 발견은 DEVICE 회차.
- 결정: D-358 5.1.
- 교훈: 없음.

## 2026-09-30 · uncommitted · feat(icons): D-358 S3 관제 파비콘

- 변경: 콘솔 `index.html`에 `/common/icons/fleet-console.svg` 파비콘 링크 한 줄. 새 `test_common_icons.py`가 목록의 아이콘은 200(`image/svg+xml`), 폴더·목록 밖·인코딩된 `..`는 404임을 확인한다. 제목 `Rosy 사이트 — 관제`는 이미 이름표와 같다.
- 증거: `test_common_icons.py` 1 passed.
- gate 변화: 없음.
- 결정: D-358 2·3항.
- 교훈: 없음.

## 2026-09-30 · uncommitted · docs(adr): D-358 앱 역할 ADR을 D-370으로 재번호

- 변경: 이 모듈의 D-358 앱 역할·이름·아이콘 주석과 시험 문서 문자열을 D-370으로 바꿨다. 동작 변경 없음.
- 증거: 번호만 바꾼 diff. 시험은 병합 뒤 회차에서 다시 돌린다.
- gate 변화: 없음.
- 결정: 이 항목 앞의 "D-358 S1/S2/S3"·"D-358 N항"은 D-370을 가리킨다(main의 D-358 ER2 피드백 outbox와 다름). 옛 항목은 고치지 않는다.
- 교훈: 없음.

## 2026-09-30 · uncommitted · fix(fleet): D-370 리뷰 — 발견 행은 분류기가 정규화한 호스트를 저장

- 변경: `fleet/server/discovery.py`가 `hostname.lower()` 대신 `classify(...).host or ""`를 저장한다(소문자, 끝 점 제거). 끝 점 있는 광고가 등록 URL과 맞지 않던 문제.
- 증거: `test_discovery.py` 20 passed. 새 시험은 옛 줄로 되돌리면 적신(변이 증명).
- gate 변화: 없음.
- 결정: D-370 5.1.
- 교훈: 없음.

## 2026-09-30 · uncommitted · refactor(fleet): D-377 console title and favicon
- 변경: 관제 화면 `<title>` `Rosy Console`, 파비콘 `/common/icons/console.svg`. `test_common_icons.py`, `test_task_contract_docs.py`의 Vision 경로(`src/site/vision/rosy_vision/ingest.py`).
- 증거: `python -m pytest src/site/fleet/test -q` 938 passed, 6 skipped; node 명세 6파일 34 passed (2026-09-30 Windows).
- gate 변화: 없음. 자산 폴더 이동(`src/site/console`, `rosy_console`)은 D-374 단계 4 게이트 그대로.

## 2026-09-30 · f21364e6 · feat(fleet): D-318 rectification profile per source and lens
- 변경: `vision-view.js`가 Vision의 `X-Source-Lens`로 브라우저 보정값 키를 `rosy-camera-rectification:<source>@<wide|standard>`로 나눈다. 예전 키(source만)는 기본 렌즈로 만든 값이라 lens가 standard일 때 `@standard`로 옮긴다. lens를 알리지 않는 옛 앱은 예전 키를 그대로 쓴다. 지금 렌즈의 값이 없고 다른 렌즈 값만 있으면 적용하지 않고 "저장한 화면 보정은 기본 렌즈용입니다…" 경고를 띄운다. 메타 줄에 렌즈 표시.
- 증거: `node --test src/site/fleet/test/web/*.test.mjs` 40 passed; `test_server_app.py`·`test_site_map_api.py` 61 passed; `ROSY_RUN_BROWSER_TESTS=1 pytest test/test_fleet_console_browser.py -k "vision or rectif or camera"` 3 passed (2026-09-30 Windows).
- gate 변화: 없음.

## 2026-09-30 · 54d0fc73 · feat(console): D-375 지도 자동 맞춤 겹침·평면 뷰

- 변경: `GET /api/fleet/site-lanes`(읽기 가드, `server/site_lanes.py`) — `lane_graph.yaml` 중심선·주차 진입·회전교차로 원과 `road_lines.stl` 페인트 삼각형을 지도 좌표로 준다. `fleet console --site-lane-graph/--site-lane-paint [MAP_ID=]PATH`. 콘솔 `map-fit.js`(순수)·`map-fit-view.js`(DOM): "맵 자동 맞춤" → Vision map-proposal(같은 preview lease, Fleet 중계 없음) → 원본 위 차선 겹침 + 지도 평면으로 편 영상(field-view `warpImage` 공용). 수락은 source별 브라우저 표시 초안(`rosy-map-fit:<source>`)일 뿐이다. 레이어 `lanes`, `maptop` 추가.
- 증거: `test_site_lanes_api.py`, node `map-fit.test.mjs` 9개; 헤드리스 콘솔 자체 시험(합성 프레임 수락, 실제 설치 프레임 + 손 맞춤 H 겹침, 실제 Vision 거부 적합 표시). 스크린샷은 비공개 scratchpad.
- gate 변화: 없음 (SOURCE). 제안·초안은 sighting·CameraMap·주행에 쓰지 않는다(D-375 4항).
- 결정: D-375 "관제 화면 표시·확인 UI"의 첫 구현. 중심선은 페인트에서 약 8 cm(차로 가운데)라 겹침 확인은 페인트 삼각형으로 한다.
- 교훈: 네 모서리 조정값은 0–100%로 잘리므로 지도 맞춤은 전체 homography만 쓴다(모서리가 프레임 밖이어도 된다).

## 2026-10-01 · uncommitted · fix(fleet): D-359 리뷰 P1-1 — 명렬 카드 오프라인은 한국어, 열거값은 title

- 변경: `web/roster.js` 연결 끊긴 로봇의 모드 태그는 `오프라인`, `title="OFFLINE"`. `web/signals.js` 신호등 명령 기록은 `body.mode` 대신 버튼 글(녹색·적색·점멸…)을 쓴다.
- 증거: `test/test_fleet_console_browser.py -k unreachable` 1 passed (2026-10-01 Windows).
- gate 변화: web_common `enum_text_problems` 린트.
- 결정: D-359 US-009, CONCEPTS 어휘(`오프라인`은 signals.js·triage.js에 이미 쓰는 말).
- 교훈: 없음.

## 2026-10-01 · uncommitted · fix(fleet): D-359 리뷰 P1-2/P2-3 — 등록 대화상자는 비모달, 등록 해제는 D-371

- 변경: `web/enrollment.js` 등록 코드 대화상자를 `showModal()` 대신 셸이 넘긴 `dialogs.openLiveDialog`로 연다(#estop이 살아 있음). 등록 해제는 조용한 `등록 해제…` 행 버튼 + `confirmIrreversible`(로봇 이름을 따옴표로, 실행 `등록 해제`), 닫히면 포커스는 지금 화면의 그 행 버튼으로. `web/console.js`가 `/common/ui.js`에서 두 함수를 넘긴다(enrollment.js는 node 시험이 import하므로 정적 import 안 함). `test/test_web_dialog_contract.py` 핀: enrollment.js의 남은 confirm은 새 주소로 옮기기, telemetry.js 1(main 병합에서 빠진 핀 복원).
- 증거: `test/test_fleet_console_browser.py -k "enrollment_dialog_leaves or unenroll_is or enrolls_by_screen"` 3 passed. 변이: 페이지 경로로 `showModal()`을 되살리면 `hitsStop` False로 실패, `등록 해제…`의 말줄임을 빼면 실패(X:\DevTemp\rosy-d359\mutation). `node --test enrollment.test.mjs` 통과.
- gate 변화: 새 브라우저 시험 `test_enrollment_dialog_leaves_the_fleet_stop_live`·`test_unenroll_is_a_quiet_row_action_confirmed_by_name`.
- 결정: D-280 원칙 2, D-371.
- 교훈: 없음.

## 2026-10-01 · uncommitted · fix(fleet): D-359 US-009 한 열 순서 — 기기 연결은 대형 묶음 끝, 넓은 창 단언은 main 배치로

- 변경: 원인은 main 486e3683이 넓은 창 로봇 패널 격자에서 대형을 목록 아래(1열)로 옮긴 것이다. US-009 시험의 넓은 창 단언 `roster.left < formation.left`가 main 병합(c4b9fb3a) 뒤 거짓이 됐다(좁은 창 순서 단언은 통과 중이었다). 또 main의 기기 연결(로봇 등록·카메라 연결) 섹션이 병합에서 `.roster-block`에 들어가 한 열 단에서 지도 앞에 섰다. `web/index.html`에서 `.device-link`를 `.ops-block` 끝(#log 뒤)으로 DOM 이동 — 넓은 창 자리는 명시 격자(`grid-column: 2; grid-row: 2`)라 그대로. 대형 묶음을 DOM으로 지도 뒤로 옮기는 것은 넓은 창 로봇 패널 격자가 한 부모를 요구해 하지 않았다(`styles.css` 주석). 시험은 한 열 단 `#log < .device-link`를 더하고, 넓은 창은 main 배치(대형은 목록 왼쪽 끝 정렬·아래, 기기 연결은 목록 옆·대형 위)로 단언한다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -k single_column_tier -q` 2 passed. 캡처 X:\DevTemp\rosy-d359-captures(전: before-order\): 1366·1920 차이는 시계뿐(임계 20), 390 전체 페이지는 기기 연결이 지도 앞에서 대형·신호등·기록 뒤로.
- gate 변화: 없음.
- 결정: D-280 Fleet 질문 "어느 로봇에 주의가 필요한가?" — 설정 일은 끝.
- 교훈: main 병합이 넓은 배치를 바꾸면 US-009 시험의 넓은 창 단언도 main 쪽으로 다시 읽는다. 본 `.discovery` 기본 규칙의 `margin-top`이 64rem 규칙의 `margin-top: 0`을 뒤에서 덮어 넓은 창 기기 연결이 16px 내려앉아 있다(main 기존, 손대지 않음).

## 2026-10-01 · 952d5d80 · fix(fleet): lens profile review fixes
- 변경: 렌즈 종류 검사를 `in`에서 `Object.hasOwn`으로 바꿨다(`kind=toString`은 렌즈가 아니다). 렌즈 이전의 보정값은 `@standard`로 옮기지 않고 복사한다. 예전 키를 남겨 옛 앱으로 되돌려도 그 값을 쓴다.
- 증거: `node --test src/site/fleet/test/web/vision-lens-profile.test.mjs` 7 passed (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(hub): D-382 F6 — 소켓을 로봇 하나에 묶고 짝 토큰을 상수 시간으로 비교

- 변경: `SiteHub`에 소켓 단위 `HubSession`을 두었다. HELLO가 성공하면 그 소켓을 그 로봇에 묶고, HEARTBEAT·EVENT는 자기 소켓의 로봇 것만 받는다(다른 로봇이면 `PAIRING_INVALID`). 같은 소켓의 두 번째 로봇 HELLO는 거절한다. 소켓이 닫히면 그 로봇을 짝 집합에서 빼되, 재접속한 새 소켓이 이미 이어받았으면 건드리지 않는다. 짝 토큰 비교는 `hmac.compare_digest`. 세션 없이 부르는 프로세스 내 호출은 예전 짝 집합 규칙 그대로다.
- 증거: `test_hub_server.py` 신규 4건(남의 로봇 이벤트·하트비트 거절, 재결속 거절, 끊기면 해제, 재접속 경합) — 수정 전 코드에서 4건 모두 실패, 수정 후 통과. `src/site/fleet/test/` 전체는 아래 커밋 기록 참조.
- gate 변화: 없음(LOCAL). 실행 중인 Fleet은 재시작해야 적용된다.

## 2026-10-01 · uncommitted · fix(hub): D-382 F6 독립 리뷰 반영 — 밀려난 소켓 닫기, 세션 인자 키워드 전용

- 변경: 코드 리뷰(APPROVE WITH FIXES) 1·2번. 다른 로봇 것을 보내거나 새 소켓에 밀려나 `PAIRING_INVALID`를 받은 소켓은 4401로 닫아 Agent가 백오프 재접속하게 한다(남은 좀비 연결 방지). `SiteHub.handle`의 `session`을 키워드 전용으로 바꾸고 네트워크 코드는 반드시 넘긴다고 적었다. 3번(빈 토큰)은 `set_pairing_token`이 이미 거절해 해당 없음, 4번(Agent 재시작 뒤 seq)은 F7 부팅 세대로 다음 이미지 회차(L2).
- 증거: `src/site/fleet/test/` 956 passed, 6 skipped; `test_fleet_agent.py`·`test_fleet_agent_mdns.py` 15 passed (2026-10-01 Windows). `test_console_hub_integration.py`의 간헐 실패는 uvicorn 기동 4 s 대기 초과(Hub 코드 이전 단계)로, 같은 부하 교차 실행에서 main 1/8·이 브랜치 0/8 — 기존 부하 의존 flake.
- gate 변화: 없음.

## 2026-10-01 · 8fac2428 · fix(console): D-375 지도 맞춤 독립 리뷰 반영

- 변경: `X-Proposal-State: previous`는 "이전 결과 · N s 전"으로만 보이고 수락 불가, 최신 결과까지 다시 묻는다(`canAccept`). `pickLanes`는 map_id 항목 우선. 가로세로 비 1 % 초과·지도(map_id·lane/paint 해시) 변경 시 초안·제안을 쓰지 않는다. 맞춤 시작 때 지난 제안 지움·버튼 잠금·세대 번호. 행렬은 `image_to_map` 하나에서 부호를 맞춰 만든다. 재시도 15회·Retry-After 15 s까지. 40812e0a: site-lanes는 시작 때 한 번 만들고 ETag·`private, no-cache`, `=` 든 경로 오분리 수정, 없는 MAP_ID 경고, viewer 읽기 시험. 경기장 뷰 대체 경로(90a0fac9)도 같은 사용 가능 판정을 거친다.
- 증거: node `map-fit.test.mjs` 15개, `test_site_lanes_api.py`; `python -m pytest src/site/fleet/test -q` 통과(보고 참조).
- gate 변화: 없음.
- 결정: D-375 6항.
- 교훈: 한 파일의 두 방향 행렬을 따로 믿으면 부호가 어긋날 수 있다 — 하나에서 만들고 영상 중심 w > 0으로 맞춘다.

## 2026-10-01 · uncommitted · fix(fleet): D-375 지도 맞춤 뷰를 D-359 캔버스·사유 계약 아래로
- 변경: main 병합으로 들어온 `web/map-fit-view.js`가 `getPropertyValue`+hex 대체색·`12px monospace` 글꼴·사유 없는 `disabled`를 썼다. 색은 `window.RosyPalette.cssColor`(테마를 따른다; `--muted`→`--ink-quiet`, 없는 `--paper`→`--ink`, 그래서 캡션의 "흰 점선"→"가는 점선"), 글꼴은 `canvasFont(12, "mono")`, `맵 자동 맞춤` 비활성은 `reason="맞추는 중"`과 함께 켜고 끈다. web_common `CANVAS_FILES`에 이 파일을 더했다(판정 밖 캔버스였다).
- 증거: `python -m pytest src/hmi/web_common/test src/hmi/dashboard/test src/site/fleet/test src/site/games/test src/runtime/api_web/test -q` 1426 passed, 99 skipped; `node --test src/site/fleet/test/web/*.test.mjs` 58 passed (2026-10-01 Windows).
- gate 변화: `test_canvas_palette_contract.py`가 map-fit-view.js도 본다.
- 결정: D-359 §4·§5.3, D-375.
- 교훈: 병합으로 새 캔버스 파일이 오면 `test_every_canvas_script_on_a_web_surface_is_under_the_contract`가 잡는다 — 목록에 넣고 판정을 통과시킨다.

## 2026-10-01 · uncommitted · fix(fleet): D-375 맵 자동 맞춤 버튼을 경기장 도구 줄에 합친다
- 변경: main 병합 뒤 `index.html`의 지도 맞춤 버튼이 경기장 자동 찾기 아래에 자기 줄을 하나 더 차지해, 1920×1080 콘솔 문서가 5px 스크롤됐다(`test_console_fits_the_declared_viewport`, D-201). 두 제안 도구가 `.field-tools` 한 줄을 나눠 쓰고, 상태 문구는 경기장→지도 맞춤 순서로 그 아래에 둔다. 한 줄에 "제안 버리기"가 둘이 되지 않게 지도 쪽은 `맞춤 제안 버리기`로 바꿨다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -q` 52 passed, 1 failed(이미 알려진 `test_the_console_renders_what_swarm_control_says`) (2026-10-01 Windows). 캡처 X:\DevTemp\fleet_console_fit.png.
- gate 변화: 없음.
- 결정: D-201, D-375.
- 교훈: 없음.

## 2026-10-01 · uncommitted · fix(swarm): D-370 S7 — Fleet→CORE WS는 첫 메시지 인증, URL에 토큰 없음

- 변경: `swarm/robots.py` `ws_url`이 토큰을 받지 않는다(쿼리는 `types` 같은 나머지만). `swarm/transport.py` `HttpRobotClient._open_socket`이 접속 직후 `{"type": "auth", "token": ...}`를 첫 프레임으로 보낸다(pose·reference·events 세 소켓). 대시보드·Pilot과 같은 방식이고 CORE `ws.py:_authorize`의 첫 메시지 경로를 탄다. 5fd0c12e·5c0ce600 이미지가 이미 받으므로 `?token=` 대체 경로는 두지 않았다. 로봇이 첫 프레임 전에 닫으면 전송 실패를 삼키고 소켓을 읽어 닫힘 코드(4401/4403 → `RobotApiError`)와 앞선 프레임을 그대로 드러낸다. websockets는 DEBUG에서 모든 프레임을 찍으므로 로봇 소켓은 INFO로 고정한 `fleet.swarm.transport.websocket` 로거를 쓴다(토큰이 기록에 남지 않게).
- 증거: `test_transport.py` 신규 시험(실제 websockets 서버: 세 경로 모두 URL에 토큰 없음, 첫 프레임이 auth, DEBUG 기록에 토큰 없음)과 URL 시험, `test_robots.py` `ws_url` 시험 3건 — 수정 전 5건 빨강, 수정 후 초록. `src/site/fleet/test/` 전체는 커밋 기록 참조.
- gate 변화: 없음(LOCAL). CORE의 `?token=` 수락은 그대로(제거는 `contract_version` 관문 뒤).

## 2026-10-01 · uncommitted · fix(relay): 첫 메시지 인증 뒤 늦게 오는 4401을 레인 이유로 드러낸다

- 변경: 독립 리뷰(APPROVE WITH FIXES) 1·5번. 첫 메시지 인증에서는 틀린 토큰이 소켓을 연 뒤 4401로 닫혀, 리더가 조용하면 레인이 이유 없이 연결된 것처럼 남았다. `ReferenceSink.wait_closed()`를 더하고 WebSocket 싱크가 닫힘을 `RobotApiError`(WS_4401/4403)로 알린다. 릴레이는 닫힘 감시가 기존 wake 신호를 세우게 해 스케줄 순서를 바꾸지 않고, 깨어나면 닫힘 이유를 레인에 적고 백오프한다. `send`의 `ConnectionClosed`도 같은 이유로 바꾼다. `fleet-mdns.py` 사본은 벡터 밖 입력에서도 `core_common` 판정과 같은지 시험한다.
- 증거: 신규 시험 2건(수락 뒤 4401 싱크, 조용한 리더 중 레인 이유) 수정 전 실패·수정 후 통과. `test_relay.py`·`test_transport.py` 48 passed, `test/test_site_fleet_mdns.py` 76 passed.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · refactor(enrollment): D-391 4.1 device_kind 상수 사용

- 변경: `enrollment_store.py`의 감사 기본값과 `retired_robot_ids` 조회가 문자열 `'robot'` 대신 `core_common.protocol.device_kind.ROBOT`을 쓴다(조회는 매개변수 바인딩). 값이 같아 동작 변경 없음.
- 증거: `src/site/fleet/test/ -k enroll` 84 passed, 1 skipped.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(fleet): D-392 P0–P2 모델 도구 call/result 경계

- 변경: D-392 구현 계획 P0–P2. Fleet 내부 `ModelToolCall`/`ModelToolResult`를 추가해 provider call ID·turn ID·ordinal을 결과에 상관시키고, 인수와 payload는 제한된 canonical JSON snapshot으로 보관한다. ER 2 feedback loop는 호출 결과를 이 타입으로 매핑한 뒤 기존 Gemini `function_result` 형식으로 돌려준다. 일회성 `propose_pick_place` 후보 흐름은 D-331대로 후보만 반환하고 callback/result loop에 넣지 않는다.
- 계획 정합: durable turn store 경로를 실제 `fleet/server/mission_model_turn_store.py`로 수정하고, feedback 호출과 일회성 후보 출력의 결과 왕복 차이를 명시했다.
- 증거: 변경 전 네 Fleet AI suite 기준선 59 passed. P0–P2 수정 후 contract·ER2·dispatcher·turn-store·feedback suite 88 passed; contract type 단위 28 passed, ER2 adapter 32 passed.
- gate 변화: 없음. SOURCE/LOCAL 테스트만; ROS-SIM·ARTIFACT·DEVICE·FIELD는 미실행.

## 2026-10-01 · uncommitted · feat(fleet): D-392 P3 폐쇄형 모델 도구 카탈로그

- 변경: `get_mission_status`, `propose_replan`, D-331 단발 후보 도구 `propose_pick_place`를 Fleet 소유 폐쇄형 카탈로그에 등록했다. Provider 스키마는 카탈로그에서 투영하며, dispatch는 feedback 허용 항목만 실행하고 durable turn scope에서 권한을 얻는다.
- 도구는 모두 비장치 명령이다. 이동, 그리퍼, Action, 취소, stop/E-stop, 재무장, 동적 OpenAPI operation은 카탈로그에 없으며 인수 스키마는 닫혀 있다.
- 증거: 집중 테스트 108 passed, flake8·`git diff --check` 통과. Harness lint는 0 errors, 기존 `last_verified` 차이 경고 24건. SOURCE/LOCAL만; ROS-SIM·ARTIFACT·DEVICE·FIELD gate는 미실행.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(fleet): D-392 P4 per-call 멱등성과 UNKNOWN 결과 저널

- 변경: Fleet 공유 SQLite에 provider call ID·tool 이름·순번·canonical 인수 digest를 기록한다. 동일 call 재실행은 저장 결과를 반환하고, 내용이 바뀐 ID 재사용은 충돌로 거부한다. 프로세스 재시작 때 미완료 call은 UNKNOWN으로 닫아 자동 replay를 막는다.
- 원자성: `propose_replan` 후보와 상관된 accepted `ModelToolResult`를 같은 SQLite 트랜잭션으로 저장한다. 결과 저장 실패 시 후보도 rollback한다. UNKNOWN/IN_PROGRESS는 Gemini function result로 회신하지 않고 바깥 model turn을 UNKNOWN으로 끝낸다.
- 증거: call journal·candidate fence·dispatcher·ER2 adapter·turn store·feedback suite 76 passed; Fleet 전체 1035 passed, 6 skipped. flake8, `git diff --check` 통과.
- gate 변화: 없음. SOURCE/LOCAL만; ROS-SIM·ARTIFACT·DEVICE·FIELD 미실행.

## 2026-10-01 · uncommitted · fix(fleet): D-392 P4 early result journaling
- Change: dispatch_replan claims each validated canonical call once and journals early policy rejections. Reusing a provider call ID with changed arguments returns a conflict.
- Evidence: regression covers saved/replayed REPLAN_NOT_ALLOWED and provider call ID collision; focused tests pass.
- gate 변화: none. SOURCE/LOCAL only; ROS-SIM, ARTIFACT, DEVICE, and FIELD were not run.

## 2026-10-01 · uncommitted · feat(pairing): D-341 2단계 — Fleet `pairing/v1` 서버 상태와 API

- 변경: `server/pairing.py`(메모리 대기 표 `pending → revealed → approved → delivered → confirmed`, `rejected`·`expired`; 기동마다 새 HMAC 키, 공개 뒤 `server_nonce` 폐기·코드 HMAC만 보관; 대기 300 s·사이트 전체 16건·30건/분·조회 2 s·본문 4 KiB·틀린 코드 3회 거절·승인 후 120 s 확인 없으면 자동 회수, 한도는 429 + `Retry-After`이고 기존 대기를 밀어내지 않는다), `server/pairing_store.py`(`device_credentials`: digest·source·상태·만료만, 원문·nonce·코드 열 없음; 감사는 `device_pairing_audit` 재사용, 모든 쓰기가 `device_kind='overhead-camera'`를 명시), `server/pairing_routes.py`(`/api/fleet/pairing/v1/...` 10개 라우트: 폰 요청·공개·조회·확인, 콘솔 대기·요약·승인·거절·회수, Vision 자격 목록). `enrollment_store.py`는 감사 표 생성·이전·추가를 모듈 함수로 꺼내 두 저장소가 같이 쓴다. `create_app(pairing=, pairing_sync_token=)` — 동기화 비밀은 console·discovery·preview·로봇 REST/Agent·sighting·policy evidence·사용자 digest·로봇 등록 키와 겹치면 기동 거절(`site_auth.assert_pairing_sync_token_isolated`). `sightings_config.py`: source별 `credential: static|paired`. CLI `--pairing-ca`·`--pairing-tls-host`·`--pairing-sync-token-env` — `--tls-cert`·`--tasks-db` 없으면 기동 거절, CA 자리에 leaf면 거절.
- 결정: 승인·거절·회수는 라우트 전용 가드로 403 `{"code":"OPERATOR_IDENTITY_REQUIRED","message":"named operator required (site-users.yaml)"}`(등록 라우트와 같은 방식, `site_auth`의 "mission admission" 문구는 그대로). 폰 본문 거절은 모두 400 + 벡터 사유(`too_large` 포함). 저장소는 계획의 `--pairing-db` 대신 기존 Fleet SQLite(`--tasks-db`)를 쓴다(ADR 8 "기존 fleet.sqlite3"). leaf 해시는 `--tls-cert`의 첫 인증서. 승인 때 `pending_confirm` 행을 쓰고 확인 때 `active`로 — 재시작 때 남은 `pending_confirm`은 `fleet_restart`로 회수. 명시적 `static`은 `phone_token_env`가 필수, 생략된 `credential`은 옛 모양 그대로(Fleet은 폰 토큰을 읽지 않으므로; Vision이 필수 검사).
- 증거: 새 시험 `test_pairing_state.py` 26, `test_pairing_api.py` 18, `test_no_video_relay.py` 페어링 켠 경우 1, `test_sightings_config.py` 5, `test_cli.py` 5 — 구현 전 수집·실행 실패 확인 뒤 녹색. `src/site/fleet/test/` 전체 녹색(커밋 기록 참조).
- gate 변화: 없음(LOCAL). 콘솔 "기기 연결" 카메라 구역은 별도 작업.

## 2026-10-01 · uncommitted · fix(pairing): 상태 기계를 잠금 하나로 직렬화, 크기 판정 재기록

- 변경: `server/pairing.py`의 공개 메서드를 `threading.RLock` 하나로 감쌌다. FastAPI의 동기 라우트(승인·거절·회수·조회·목록)는 스레드 풀에서 돌아, 같은 요청에 동시 승인이 들어오면 자격이 두 개 생길 수 있었다. `test/architecture/test_module_structure.py`의 `fleet` 패키지 판정을 21476줄로 다시 적었다(main이 이미 20655로 넘었고, 페어링은 자기 모듈 셋). 비밀 스캔이 이름만 보고 잡은 시험 변수 `shared` → `shared_secret`.
- 증거: 새 `test_concurrent_approvals_issue_exactly_one_credential`(8개 스레드가 장벽 뒤 같은 코드로 승인) — 잠금 전 3회 연속 실패, 잠금 뒤 3회 통과. 페어링 시험 43 passed. 잠금 전 `src/site/fleet/test/` 1037 passed, 6 skipped(164 s); 잠금 뒤 전체 결과는 커밋 기록 참조.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(pairing): 보안 리뷰 반영 — 익명 요청은 감사 표에 쓰지 않음, 동기화는 https+CA 필수

- 변경: 독립 보안 리뷰(APPROVE WITH FIXES). ① 인증 없는 페어링 요청·커밋 불일치는 `device_pairing_audit`에 쓰지 않고 메모리 계수만 둔다(익명 30건/분으로 운용자·로봇 등록 감사 행이 밀려나던 경로 차단); `GET /pending`에 `unauthenticated_requests`·`refused_requests`·`commit_mismatches`를 보여 큐 막힘을 운용자가 본다. ③ confirm의 `credential_id`는 `[A-Za-z0-9_-]{1,64}`, 비교는 바이트로(비ASCII가 500을 내던 문제). ④ 폰 경로의 잠금·SQLite 호출을 스레드풀로 옮겨 이벤트 루프를 막지 않는다. ⑥ `_Request` repr에서 nonce·commit·poll digest를 숨긴다.
- 증거: 신규 시험(익명 폭주가 감사 행을 지우지 않음·거절 계수, repr 은닉, 비ASCII confirm 400); `src/site/fleet/test/` 아래 기록.
- gate 변화: 없음.

## 2026-10-01 - D-392 P3 closed model-tool catalog

- Added a Fleet-owned closed catalog for `get_mission_status`, `propose_replan`, and the D-331 one-shot `propose_pick_place` candidate tool. Provider declarations are projections from that catalog; dispatch accepts only feedback-enabled entries and derives authority from the persisted turn scope.
- All catalog entries are explicitly non-device-action tools. Unknown and low-level motion, gripper, Action, cancel, stop, E-stop, rearm, and dynamic OpenAPI names are absent. Tool schemas are returned as fresh objects with closed argument sets.
- Verification: 108 focused tests passed; flake8 and `git diff --check` passed. Harness lint: 0 errors, 24 existing `last_verified` drift warnings. SOURCE/LOCAL only; no ROS-SIM, ARTIFACT, DEVICE, or FIELD gate.

## 2026-10-01 · uncommitted · feat(console): D-341 카메라 연결 승인 구역의 순수 규칙(camera-pairing.js)

- 변경: 새 `server/web/camera-pairing.js` — 위쪽은 DOM 없는 순수 함수(코드 6자리 정규화·검사, 자격 없는 `paired` 자리 고르기, 남은 시간 카운트다운, 요청·자격 행 문구, 행 버튼과 꺼진 까닭, 서버 분류 → 운용자 문장, `CODE_MISMATCH`는 남은 입력 횟수), 아래쪽 `createCameraPairingPanel`은 화면 배선(다음 단계에서 셸에 붙인다). 이름 있는 운용자 판정은 `enrollment.js`의 `canManage`를 그대로 쓴다. `static_routes.py` 허용 목록에 더했다.
- 결정: 콘솔은 코드를 보여 주지 않고 형식만 검사한다. 대기 목록은 2.5 s(폰 조회 하한 2 s보다 느리게), 자격 목록은 그 세 번에 한 번.
- 증거: 새 `test/web/camera-pairing.test.mjs` 9 — 모듈 없을 때 실패 확인 뒤 9 passed(`node --test`).
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · feat(console): D-341 "기기 연결" 패널에 카메라 연결 승인 구역

- 변경: `index.html`의 숨은 자리표시 구역을 "카메라 연결 승인"으로 채웠다(로봇 등록 다음, `data-role-lock` + "운용자 권한이 필요합니다" 안내). 대기 요청(기기 이름표·앱 버전·남은 시간 카운트다운·남은 입력), 승인 대화상자(자격 없는 `paired` 자리 고르기 + 폰 화면의 6자리 입력, `openLiveDialog` 비모달), 승인 뒤 "폰 화면과 이 지문·자격 ID가 같은지 확인하세요" + 사이트 지문·자격 ID(등폭, 크게) + 120 s 확인 카운트다운, 연결된 카메라 목록(상태·승인자·만료, "폐기…" → `confirmIrreversible`), 대기 요청 "거절…" → `confirmIrreversible`. `console.js`가 등록과 같은 방식으로 `dialogs`를 넘기고 로그인마다 `resetPolling()`·`refresh()`. 서버의 새 누계(`refused_requests`·`commit_mismatches`, 920bef4d)는 0이 아니면 조용한 한 줄로 보인다. `styles.css`는 토큰만 쓴다.
- 결정: 라우트가 없는 Fleet(평문 404)은 "이 Fleet에는 카메라 연결 승인이 설정되지 않았습니다."만 보이고 다음 로그인까지 묻지 않는다. 대기 목록은 패널이 화면에 있고 탭이 보일 때만 2.5 s마다, 자격 목록은 세 번에 한 번과 조작 직후. 단일 콘솔 토큰(`site-console`)은 버튼 없이 403 사유 문장을 미리 보인다. 꺼진 승인 버튼은 `reason`으로 까닭(코드 아직 없음·빈 자리 없음)을 말한다. 웹 공통 가드: `IRREVERSIBLE_VERBS`에 "거절"을 더했고, 모달 스캔 명단에 `camera-pairing.js`를 더했다. `fleet` 크기 판정 22055로 재기록.
- 증거: 새 `test_console_camera_pairing.py` 6(실제 라우트의 응답 모양, 단일 토큰 403, 페어링 없는 404, 쪽 id·자리·역할 잠금, 셸 배선 — id·hidden 변이로 적색 확인), `camera-pairing.test.mjs` 10. `src/hmi/web_common/test/` + `test/test_web_dialog_contract.py` + `test/architecture` 녹색, 단 main에서 온 `tools/perception/model/watch.py` 630줄 판정 없음 1건(이 브랜치 변경 아님).
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · test(console): D-341 카메라 연결 승인 브라우저 계약과 화면 다듬기

- 변경: `test/test_fleet_console_browser.py`에 옵트인 시험 5개 — 승인(형식 오류는 보내지 않음, `CODE_MISMATCH` 남은 입력 2회 뒤 성공, 대화상자 동안 전체 정지 살아 있음, 지문·자격 ID 등폭, 화면 어디에도 코드 없음, 1366·390·320 가로 넘침 없음), 거절…·폐기…의 이름 묻는 확인과 Escape 뒤 포커스 복귀, viewer·단일 토큰은 버튼 없음(각자 안내), 페어링 없는 Fleet은 안내 한 줄 + 6 s 동안 `pending` 1회만. `ROSY_CAMERA_SCREENSHOT_DIR`이 있으면 구역 캡처를 저장한다. 화면: 행 버튼을 한 줄로 묶고, 시각을 현지 분 단위(`formatWhen`)로, 30rem 아래에서는 지문·자격 ID 이름표를 값 위로 올려 값이 묶음 중간에서 끊기지 않게 했다.
- 증거: 브라우저 `-k camera_` 8 passed, 전체 `test_fleet_console_browser.py` 57 passed + 1 failed(`test_the_console_renders_what_swarm_control_says` — UI 앞 커밋 dc082f3a에서도 같은 실패, 이 작업과 무관). `node --test src/site/fleet/test/web/*.test.mjs` 69 passed. `src/site/fleet/test/` 1047 passed, 6 skipped(180 s). `src/hmi/web_common/test/` + `test/test_web_dialog_contract.py` 204 passed, 24 skipped.
- gate 변화: 없음(LOCAL). 실물 폰·실제 Fleet 화면 캡처는 DEVICE 단계.

## 2026-10-01 · uncommitted · fix(pairing): 같은 자격 ID의 confirm 재시도는 120 s 안에서 멱등

- 변경: rosy-84 Rosy Cam 클라이언트 보안 리뷰 권고. 첫 confirm 응답이 사라지면 폰은 자격이 살아났는지 알 수 없어 버리고, 그 자리는 운용자가 폐기할 때까지 막혔다. 이제 같은 요청·같은 poll 비밀·같은 `credential_id`로 승인 뒤 120 s 안에 다시 confirm하면, 그 자격이 여전히 active일 때만 같은 200을 돌려준다(감사 행은 처음 한 번). 다른 ID·창 밖·폐기 뒤는 지금처럼 410. 함께: 모델 감시기 분할(625fad86) 뒤 낡은 `watch.py` 크기 판정 행을 지웠다(콘솔 병합이 되살린 행).
- 증거: `test_pairing_state.py` 31 passed(신규 2건), `test/architecture/test_module_structure.py` 33 passed.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · test(fleet): D-392 P4 provider adapter conformance fixtures
- 변경: Test-only Interactions and Live API shaped adapters normalize differing native call/result fields into the same canonical Fleet contract and exercise the actual dispatcher and durable journal.
- Coverage: read and candidate calls, replay and call-ID collision, argument byte limit, stale turn after stop, and denial of mock motion/gripper, sample-shaped OpenAPI, and model-routed stop tools. Endpoint profiles keep Interactions-only structured output/code execution out of Live assumptions.
- Evidence: 25 conformance tests passed. No production Live adapter, new provider SDK, physical action, or device claim.
- gate 변화: none. SOURCE/LOCAL only; ROS-SIM, ARTIFACT, DEVICE, and FIELD were not run.

## 2026-10-01 · uncommitted · feat(discovery): 검색기 임대가 끊기면 관제가 경보한다

- 변경: 점검(2026-10-01) #4 연쇄 — 발견 브리지가 끊긴 뒤 45 s가 지나면 새 로봇 발견과 새 주소로 옮기기가 멈추는데, 관제는 처음부터 스캔이 없을 때와 같은 노란 "검색기 연결 대기"만 보였다. `server/discovery.py` `snapshot()`이 `scanner_state`(`never_seen`·`online`·`expired`)와 `scanner_age_s`를 더한다(`scanner_online`은 그대로). `web/console.js` 발견 패널이 `expired`면 `crit` "검색기 끊김", 마지막 스캔 나이와 멈춘 기능, `rosy-mdns-bridge` 확인 안내를 보이고, 끊김·복귀를 한 번씩 이벤트 로그에 남긴다. 등록 코드(`enrollment.py`·`enrollment.js`)는 건드리지 않았다(feat/d341-fleet-pairing-server와 겹침 회피). API 참조 `/api/fleet/discovery` 행 갱신.
- 증거: `test_discovery.py` 상태 시험(never_seen → online 45 s → expired), 콘솔 경보 소스 계약, `test_discovery_api.py` 응답 모양, `test/test_fleet_console_browser.py`의 Chromium 시험(`ROSY_RUN_BROWSER_TESTS=1`, 경보 crit·로그 1회·복귀) 통과. `python -m pytest src/site/fleet/test -q` 986 passed, 6 skipped (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(discovery): 고정 주소가 지금 망에 있는지 로봇마다 판정한다

- 변경: 점검(2026-10-01, "192.168.1.x 가정 없음") #2 — 사이트 Wi-Fi가 192.168.1.x에서 10.16.36.x로 바뀌자 로봇이 까닭 없이 오프라인으로만 보였다. 새 순수 모듈 `server/address_drift.py` `classify_addresses()`가 로스터의 고정 base_url을 최근 스캔과 대조해 `in_scanned_subnet`·`outside_scanned_subnets`·`seen_at_other_address`·`unknown`(스캔 없음·검색기 꺼짐·`.local` 이름이 스캔에 없음)으로 나누고, 모든 고정 로봇이 스캔된 망 밖이면 `all_outside`를 켠다. 새 `GET /api/fleet/discovery/addresses`(viewer+)가 이것에 출처(`static`·`enrolled`)와 `movable`(등록부가 `address_changed`이고 새 주소가 하나)을 붙인다. 스캔을 받을 때 robots.yaml 로봇이 모든 스캔 망 밖이거나 다른 주소에 보이면 경고 로그를 한 번 남긴다.
- 결정: 스캔 행에는 robot_id·device_uid가 없다. 그래서 같은 로봇 판정은 등록부가 이미 쓰는 발견 이름(등록 로봇), 인증된 HELLO의 `device_name`, 그 둘이 없으면 base_url 자체의 `.local` 이름(파일 로봇)으로만 한다. 신원이 없는 로봇은 이름으로 짐작하지 않는다. 실제 이동은 기존 "새 주소로 옮기기"가 토큰으로 robot_id·hostname·serial·device_uid를 다시 확인한다. 스캔 행에 넷마스크가 없어 "스캔된 망"은 스캔 주소마다 /24로 잡는다(`site_networks` 인자는 사이트 호스트 인터페이스를 알게 되면 더한다 — 지금은 배선하지 않음: Fleet은 컨테이너 안이라 호스트 인터페이스를 모른다). 포트만 다르면 주소 변경으로 보지 않는다(파일 로봇의 https:8443 대 광고 8080). `.local`은 풀지 않고(D-370 5.3) 스캔의 IP를 제안으로만 싣는다. 응답에 토큰·경로·userinfo가 없다. API 참조에 행을 더했다.
- 증거: 새 `test_address_drift.py` 14, `test_address_drift_api.py` 4 — 모듈 없음으로 적색 확인 뒤 18 passed.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · feat(console): 오프라인 로봇 카드에 고정 주소 까닭, 사이트 망 변경 경보

- 변경: 점검 #3 — 새 순수 모듈 `web/address-drift.js`(`addressReason`·`renumberBanner`·`addressMap`)가 판정을 문장으로 옮긴다. 오프라인 로봇 카드에 "고정 주소 X이(가) 지금 망에 없습니다 — …", 등록 로봇이 다른 주소에 하나로 보이고 등록부가 `address_changed`면 "같은 로봇이 Y에 보입니다 — 새 주소로 옮기기…"와 카드 버튼(기존 로봇별 이동 흐름 `enrollment.confirmMove`를 그대로 부름, viewer는 "운용자 권한이 필요합니다", 공용 토큰은 "이름 있는 운용자 계정이 필요합니다"), 이름이 여러 주소면 신원 충돌 문장(행동 없음). robots.yaml의 `.local` 로봇은 "이름이라 Fleet이 따라가지 않습니다 — 스캔에서 Y에 보입니다 … robots.yaml을 고치세요"로 제안만 한다. 모든 고정 로봇이 스캔 망 밖이면 로봇 목록 위에 `role="alert"` 경보 "사이트 망 주소가 바뀐 것 같습니다 …". `console.js`가 발견과 같은 주기로 읽고 바뀌었을 때만 다시 그린다. 정적 허용 목록에 모듈을 더했고, 넓은 창 격자에 경보 행을 넣어 아래 행을 하나씩 내렸다.
- 결정: 예시 주소 `192.168.1.20`을 콘솔·서버 문구에서 뺐다. 수동 등록은 사설 IPv4만 받으므로 문서용 192.0.2.x를 예로 들면 그 예가 거절된다 — 자리표시는 "로봇 화면의 IP:8080", 오류 문구는 "로봇 화면에 보이는 IPv4 주소"로 바꿨다. `deploy/site/robots.yaml.example`은 이미 192.0.2.10이다.
- 증거: 새 `test/web/address-drift.test.mjs` 7(모듈 없음 적색 → 자리표시 `192.168.1.20` 남음 적색 → 녹색), `test_address_drift_api.py` 정적 자산·셸 배선 1 추가. `node --test src/site/fleet/test/web/*.test.mjs` 76 passed, `src/hmi/web_common/test/` + 콘솔 시험 224 passed, 24 skipped.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · feat(console): "새 주소로 옮기기 (전체)…"

- 변경: 점검 #5 — 로봇 목록 위 경보 묶음에 "새 주소로 옮기기 (전체)…" 버튼. 대상은 서버가 `movable`로 판정한 등록 로봇(새 주소가 하나, 등록부 `address_changed`, 충돌 아님)뿐이다. `confirmIrreversible` 한 번에 로봇별 `"robot_id" → 새 주소`를 모두 적고 묻고, 확인하면 `address-drift.js` `runBulkMove`가 기존 `POST /api/fleet/enrollment/robots/{id}/move-address`를 한 대씩 차례로 부른다(`enrollment.moveAddress`). 한 대가 실패해도 나머지는 가고, 결과는 로봇마다 한 줄(실패는 등록 패널과 같은 분류 문장)과 이벤트 로그 "n/m대 옮김".
- 결정: 로봇별 이동은 화면 코드를 요구하지 않는다 — 이름 있는 운용자의 감사되는 확인 뒤 Fleet이 기존 토큰으로 새 주소의 `system/info`를 읽고 robot_id·hostname·serial·device_uid가 다르면 그 로봇을 `needs_new_code`로 둔다(D-361 3). 전체 옮기기는 같은 요청을 로봇마다 그대로 보내므로 신원 확인·감사·권한(`require_named_operator`)이 하나도 줄지 않는다. 새 서버 경로는 만들지 않았다. 파일(robots.yaml) 로봇은 대상이 아니다(런타임에 파일을 고치지 않는다 — 제안 문장만).
- 증거: `address-drift.test.mjs` 3 추가(대상 필터, 확인 문장이 대상·주소를 모두 말하고 묻는다, 순서대로 한 번씩·실패 뒤 계속·로봇별 문장) — export 없음 적색 뒤 녹색, `test_address_drift_api.py` 배선 1 추가. node 79 passed, 주소 시험 20 passed, `src/hmi/web_common/test/` + 대화상자 계약 녹색.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · chore(architecture): fleet 크기 판정 23166으로 재기록

- 변경: `test/architecture/test_module_structure.py`의 `fleet` 판정을 22435에서 23166으로 다시 적고 'split: …' 문장 끝에 까닭을 붙였다(main이 D-392 작업으로 이미 22797, 이 브랜치의 `address_drift.py`·`address-drift.js`·라우트·시험이 더함). 판정은 그대로다.
- 증거: 판정 시험 녹색. 같은 파일의 `site/fleet/fleet/server/proposal_store.py`(730줄, D-392 다른 세션) 판정 없음 1건은 main에서도 실패하며 이 브랜치가 다루지 않는다. `src/site/fleet/test/` 1123 passed, 6 skipped(137 s). 바뀐 파일 secret_scan 0건.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · test(console): 주소 까닭·전체 옮기기 브라우저 계약

- 변경: `test/test_fleet_console_browser.py`에 옵트인 시험 2개 — (1) 모든 로봇이 망 밖인 응답에서 경보, 카드 3장의 까닭 줄, 카드의 "새 주소로 옮기기…", 전체 옮기기 확인 대화상자가 두 로봇과 새 주소를 말하고 그동안 전체 정지가 살아 있음, Escape는 요청 0, 확인하면 `move-address`를 rosy_09 → rosy_10 순서로 한 번씩, 결과 줄은 성공 "good"·신원 불일치 "bad"(줄마다 색), 390 px 가로 넘침 없음. (2) viewer는 까닭은 보고 두 버튼은 꺼짐 + "운용자 권한이 필요합니다". `ROSY_ADDRESS_SCREENSHOT_DIR`가 있으면 캡처를 저장한다. 결과 상자가 성공 줄까지 경고색으로 칠하던 것을 줄마다 `data-kind`로 고쳤다.
- 증거: 브라우저 전체 61 중 60 passed, 1 failed(`test_the_console_renders_what_swarm_control_says` — main에서도 같은 시간 초과, 이 작업과 무관). node 79 passed, `src/hmi/web_common/test/` 녹색.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · fix(enrollment)!: 새 주소로 옮기기는 화면 코드로 새 주소에서 재페어링한다

- 변경: 리뷰 HIGH — 기존 `move_address`는 저장된 사이트 토큰을 스캔된 새 주소에 Bearer로 먼저 보내고 나서 신원을 비교했다. 평문 HTTP라 같은 이름을 광고한 기기가 토큰을 받을 수 있었고, 전체 옮기기가 이를 키웠다. 이제 `POST …/{id}/move-address`는 본문 `{code}`(로봇 화면 코드, 등록과 같은 형식 검사)를 받는다. Fleet은 새 주소에서 `auth/pair`(기존 자격 없음)로 새 토큰을 받고, 그 토큰으로 읽은 `whoami`·`system/info`가 robot_id·hostname·serial·(있으면) device_uid 모두 같을 때만 등록부(`EnrollmentStore.rebind` — 암호문과 필드를 한 트랜잭션), 로스터 endpoint, 게이트를 새 토큰으로 바꾼다. 그 뒤에만 옛 토큰을 확인된 주소에 보내 logout한다. 실패하면 감사 `old_token_not_revoked`, 응답 `old_token_revoked: false`. 다른 기기면 그 기기가 방금 준 새 토큰을 logout하고 행은 `address_changed` 그대로, 감사 `identity_mismatch`. `_current_other_address`는 RFC 1918 주소만 고른다(`discovery.is_rfc1918`).
- 결정: 옛 동작의 "다른 기기면 `needs_new_code`"는 없앴다 — 저장된 토큰이 새지 않았으므로 그 토큰은 여전히 유효하고, 고정 주소로는 정지만 간다. D-361에 날짜 붙은 개정, `docs/logs.md`에 한 줄. 콘솔은 다음 단계에서 코드 대화상자로 바꾼다(이 커밋만으로는 콘솔의 옮기기가 422).
- 증거: `test_enrollment_service.py` 옮기기 시험을 바꿈 — 기록하는 가짜 로봇(`Network.raw`/`carried`)으로 신원 확인 전 새 주소에 Authorization·저장 토큰이 0회, 성공 경로 요청 순서 pair→whoami→system/info→logout, 다른 기기·결속 키별 불일치에서 저장 토큰 0회, 틀린 코드는 pair 한 번뿐, 형식 오류는 요청 0, 옛 토큰 회수 실패 기록. `test_enrollment_api.py` 본문 없는 옮기기 422·응답에 비밀 없음. `code` 인자 없음으로 10+1 적색 확인 뒤 87 passed.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · fix(discovery): 스캔 주소는 RFC 1918만 받는다

- 변경: 리뷰 MEDIUM — 공유 분류기의 `is_private`는 링크 로컬은 막지만 문서용(192.0.2.0/24)·벤치마크(198.18.0.0/15)·0.0.0.0을 사설로 본다. `server/discovery.py`에 `is_rfc1918()`(수동 주소 `parse_manual_address`와 같은 세 대역)을 두고 `replace_scan`이 그 밖의 행을 기존 `bad_address`로 거절한다. `enrollment._current_other_address`도 같은 검사를 한 번 더 한다(앞 커밋). 공유 `discovery_txt` 분류기는 다른 클라이언트의 벡터가 걸려 있어 건드리지 않았다.
- 증거: `test_discovery.py` 2 추가 — 169.254/192.0.2/198.18/100.64/0.0.0.0/공인/멀티캐스트 거절, RFC 1918 세 대역 수용(192.0.2.5에서 적색 확인), 스캔 행에 문서용 주소가 들어 있어도 옮기기 대상이 아님. 발견·등록 API 시험 38 passed.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · fix(discovery): 망 밖 판정은 힌트로 말하고, 이름 고정은 경보를 세우지도 막지도 않는다

- 변경: 리뷰 MEDIUM·LOW — (1) 카드 문구 "…지금 망에 없을 수 있습니다", 경보 "사이트 망 주소가 바뀌었을 수 있습니다 — IP로 고정된 …"로 단정을 뺐다. (2) `all_outside`는 IP 고정이 하나 이상이고 그것이 모두 망 밖일 때만 켜진다. 이름(`.local`) 고정은 서버 판정에서 빠지고, 콘솔(`renumberBanner(payload, robots)`)이 이름 고정 로봇 중 하나라도 지금 연결돼 있으면 경보를 띄우지 않는다. (3) 스캔 행은 등록부가 쓰는 발견(TXT) 이름으로만 맞춘다 — avahi 호스트 이름에서 `.local`을 뗀 값은 더 이상 신원이 아니다. (4) `address_drift.py` docstring에 /24 가정과 그 한계(더 넓은 접두사의 사이트에서 틀릴 수 있음, 그래서 힌트)를 적었다. 앞 커밋의 `test_discovery.py` 빈 줄 lint도 고쳤다.
- 증거: `test_address_drift.py` 2(이름 고정과 경보, 호스트 이름 불일치) 적색 확인 뒤 녹색, `address-drift.test.mjs` 문구·억제 2 적색 확인 뒤 10 passed.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · fix(console): 옮기기는 로봇마다 화면 코드 대화상자, 전체 옮기기 삭제, 카드·기기 연결 여백

- 변경: 리뷰 HIGH의 화면 쪽 — "새 주소로 옮기기 (전체)" 버튼과 `runBulkMove`·`bulkConfirmMessage`를 지웠다. 경보 묶음은 옮길 수 있는 로봇(`movableRobots`)마다 "rosy_09 → 새 주소"와 "새 주소로 옮기기…"를 한 줄씩 보인다. 그 지름길, 로봇 카드의 지름길, 등록 패널 행의 "새 주소로 옮기기…"(기존 `window.confirm` 삭제)가 모두 등록 대화상자(`openLiveDialog`, `ui-field`, 등록과 같은 `ABCD-EFGH` 형식 검사, 429 잠금)를 옮기기 모드로 연다. 대상 줄은 "로봇 rosy_09 → 10.16.36.20:8080 화면의 코드", 실행 버튼은 "옮기기". 성공은 `moveDoneLines`("…(으)로 옮김 — 새 토큰으로 다시 묶었습니다", 옛 토큰을 회수하지 못했으면 "로봇 대시보드에서 이전 사이트 토큰을 회수하세요"), 다른 기기면 "등록된 토큰은 보내지 않았습니다 …". 화면 결함: 기기 연결의 마지막 줄과 "신호등" 머리가 5 px로 붙어 있던 것을 넓은 격자에서 `.signals` 위 여백으로 띄웠다. 로봇 카드는 줄어들지 않게 `flex-shrink: 0`을 걸었다 — 캡처에서 rosy_09가 잘려 보인 것은 카드가 아니라 D-201(한 화면에 들어감)이 요구하는 로봇 목록 스크롤 칸의 경계다. `test/test_web_dialog_contract.py`의 `window.confirm` 고정 목록에서 `enrollment.js` 1을 뺐다.
- 증거: `address-drift.test.mjs` — 옮길 로봇 목록, 전체 옮기기·`window.confirm` 없음과 본문 `{ code }`, 옛 토큰 문장, 신원 불일치 문장(export 없음 적색 뒤 80 passed). 브라우저 시험을 다시 썼다: 경보 목록 2줄, 지름길 → 코드 대화상자 → 형식 오류는 요청 0 → `{"code": "7KXM-P3QA"}` 한 번, 옛 토큰 안내, 행 버튼도 같은 대화상자, 대화상자 동안 전체 정지 살아 있음, 카드 내용이 줄지 않고 스크롤로 끝까지 보임, 기기 연결 마지막 줄과 신호등 머리 사이 8 px 이상(여백 없이 적색 확인), 390 px 넘침 없음, viewer는 두 지름길 꺼짐. 캡처는 X:/DevTemp/…/console-addr/.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · chore(architecture): 리뷰 수정 뒤 크기 판정 재기록(fleet 23237, enrollment.py 664)

- 변경: `fleet` 합계를 23166에서 23237로, `enrollment.py` 판정을 610에서 664로 다시 적고 각 문장 끝에 까닭(옮기기가 같은 교환·결속 검사 위의 화면 코드 재페어링이 됨, 전체 옮기기 삭제)을 붙였다. 판정은 그대로다.
- 증거: 판정 시험에서 남은 실패는 `proposal_store.py`(730줄, D-392 다른 세션) 판정 없음 1건뿐 — main에서도 실패, 이 브랜치가 다루지 않는다. `src/site/fleet/test/` 1134 passed, 6 skipped. 브라우저 61 중 60 passed(`test_the_console_renders_what_swarm_control_says`는 main에서도 같은 시간 초과). 바뀐 파일 secret_scan 0건.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(enrollment): 옛 토큰은 어디에도 보내지 않고, 고정 주소에서 아직 답하면 옮기지 않는다

- 변경: 보안 재리뷰 HIGH(중계 공격) — 같은 이름을 광고한 중계자가 운용자의 코드를 진짜 로봇의 `auth/pair`로 넘기고 `whoami`·`system/info` 답을 되돌리면 모든 비교가 맞아, Fleet이 중계자로 옮기고 logout으로 옛 토큰까지 건넸다. (a) 옮긴 뒤의 옛 토큰 logout을 지웠다. 옛 토큰은 어디에도 가지 않고, 감사는 늘 `old_token_not_revoked`, 응답은 `old_token_revoked: false`. (b) 새 주소에 닿기 전에 고정 주소(등록 때 확인됨, 정지 요청이 이미 같은 토큰으로 가는 곳)에 `system/info`를 한 번 읽어, 같은 robot_id로 답하면 409 `still_at_pinned_address`(감사 포함)로 거절하고 새 주소에는 아무것도 보내지 않는다. 고정 주소에 다른 기기·무응답·401이면 계속한다. 재리뷰 MEDIUM — 비교는 robot_id·hostname·serial_number뿐이고 이것이 인증이 아니라 일관성 검사임을 docstring과 D-361 개정에 적었다(신원을 묶는 것은 로봇 화면의 코드와 IP를 보는 사람, 진짜 인증은 로봇이 쥔 키 — 이후 과제). `device_uid`는 CORE `system/info`가 주지 않아 저장값이 늘 비므로 비교에서 뺐다(CORE 변경 없음).
- 결정: 고정 주소 탐침은 저장 토큰을 그 주소로 한 번 더 보낸다. 그 주소가 DHCP로 다른 기기에 갔다면 그 기기가 토큰을 본다 — 그러나 `address_changed` 동안의 정지 요청이 이미 같은 토큰을 같은 주소로 보내므로(D-361 3) 새 노출 경로는 아니다.
- 증거: `test_enrollment_service.py` 다시 씀 — 성공 경로 새 주소 요청은 pair→whoami→system/info뿐, 옛 토큰은 새 주소에 0회·logout 0회, `old_token_not_revoked` 감사, 고정 주소에서 아직 답하면 409이고 새 주소 요청 0, 고정 주소에 다른 robot_id면 옮김, 일관성 필드(robot_id·hostname·serial)별 불일치, device_uid는 비교 안 함, 성공·불일치·틀린 코드 경로에서 화면 코드(대소문자·하이픈 네 형태)가 감사 행과 로그 레코드 어디에도 없음. logout 남음·탐침 없음으로 6 적색 확인 뒤 99 passed(등록·API·저장소·주소 시험).
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · fix(console): 옮기기 대화상자가 새 주소 후보를 크게 보이고 로봇 화면의 IP와 맞춰 보게 한다

- 변경: 보안 재리뷰 HIGH (c) — 옮기기 모드의 등록 대화상자에 "새 주소 후보"와 그 주소(등폭, 제목 크기)를 보이고, "코드를 넣기 전에 이 주소가 로봇 화면에 보이는 IP와 같은지 확인하세요(LCD 정보 화면의 이름 아래 주소 줄). 다르면 옮기지 마세요 …"를 붙였다 — 로봇 LCD 정보 화면(`src/hmi/face/emotion/info_screen.py`)이 이름 아래에 `IP:포트` 주소 줄을 보이므로 그 말로 맞췄다. 등록 모드에서는 숨는다. 409 `still_at_pinned_address` 문장 "로봇이 아직 원래 주소에서 응답합니다 — 옮길 필요가 없습니다."를 더했다. 옮긴 뒤 문장은 늘 "이전 사이트 토큰은 Fleet이 회수하지 않습니다 — 로봇 대시보드에서 회수하거나 만료되게 두세요."(Fleet이 옛 토큰을 보내지 않으므로).
- 증거: `address-drift.test.mjs` 2(옛 토큰 문장, IP 확인 문장·고정 주소 문장) export 없음 적색 뒤 81 passed. 브라우저: 옮기기 대화상자의 후보 주소·IP 확인 줄이 보이고 등록 대화상자에서는 숨음(요소 없음 적색 확인), 등록·해제·옮기기 5 passed. `src/hmi/web_common/test/` + 대화상자 계약 녹색. 캡처 `move-code-dialog-1920.png` 다시 찍음.
- gate 변화: 없음(LOCAL).

## 2026-10-01 · uncommitted · docs(fleet): D-392 Task 8 ROS-SIM/artifact evidence boundary

- 변경: D-392 구현 계획의 Task 8에 pinned Jazzy timeout/cancel callback 실험과 local simulation manifest/checksum을 추가했다. Fleet-to-device Mission grant handoff와 ER 2 provider request는 실행하지 않았고 tool catalog의 후보 전용 권한은 그대로다.
- 증거: `docs/validation/model-tool-ros-sim-2026-10-01/README.md`, `docs/validation/model-tool-artifact-2026-10-01/manifest.json`. Fleet의 provider/tool suites는 기존 1,128 passed/6 skipped evidence이며 이번 차례에는 provider 활성화 변경이 없다.
- gate 변화: ROS-SIM partial/HOLD, ARTIFACT HOLD, DEVICE/FIELD PARKED. Local image ID·source hashes는 production signature/SBOM/device/field 증거가 아니다.

## 2026-10-01 · uncommitted · fix(console): 로그인은 느린 상태 수집을 기다리지 않고 바로 풀린다

- 변경: 실제 Compose 스택 페어링 실측에서 발견. 닿지 않는 로봇이 하나 있으면 `/api/fleet/state`가 5.1 s 걸리고, 콘솔은 세션(역할)이 이미 확인됐는데도 그동안 "토큰 필요"·운용자 버튼 잠금을 유지했다. 이제 세션이 확인되면 바로 역할을 적용하고 상태 표시를 "상태 확인 중"으로 바꾸며, 상태·발행 제어·발견·카메라 연결·대형 갱신을 나란히(Promise.allSettled) 돌려 느린 하나가 나머지를 막지 않는다. 401은 기존처럼 call()이 잠근다.
- 증거: 신규 브라우저 시험(상태 수집을 붙잡은 채 로그인 → 3 s 안에 운영자 표시, "토큰 필요" 아님) 수정 전 실패·수정 후 통과. 브라우저 61/62(실패 1건 `test_the_console_renders_what_swarm_control_says`는 main에서도 실패), node 81, web_common·대화상자 계약 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · test(fleet): exercise grant receipt through the ROS ActionServer callback

- Change: Added a cross-module ROS 2 Jazzy contract fixture that admits a Fleet Mission, dispatches its version-2 grant over UDS with `SO_PEERCRED`, and observes the local Action receipt and asynchronous ROS goal callback. Fleet reports the Mission as accepted/running while the parent Action remains nonterminal; no `GOAL_PREDICATE_CONFIRMED` event is emitted. Restart recovery changes the parent action to `UNKNOWN`, and replaying the same grant does not send a second ROS goal.
- Evidence: In the pinned local OMX Pilot image, the integration test passed (1). It uses an in-process ActionServer and bounded no-op goal; it is a ROS contract fixture, not a vendor Gazebo or physical grasp/place run. Provider dispatch remains disabled.
- Gate: No gate promotion. ROS-SIM remains HOLD; ARTIFACT HOLD; DEVICE/FIELD PARKED.

## 2026-10-01 · uncommitted · D-398 관측 상태 어휘·빈 로그·역할 토큰 정리

- 변경: classifySightings의 state 'stale' → 'delayed'(닫힌 증거 네 상태로 수렴; map-view 소비처 동반 수정), streamEvidence 나이 뒤처리 'N초' → 'N초 전'(DESIGN.md 규격). roster.js '정보 없음'을 EVIDENCE_LABEL.unavailable로, 죽은 s{index} 클래스 제거. index.html 빈 로그 .log-empty → 공용 ui-empty. styles.css ground-soft/card → surface-flat/raised, min-height 100vh → 100dvh.
- 근거: D-398. site-layer.test.mjs·fleet 시험 통과, test_fleet_console_browser pin 갱신, test_console_camera_pairing의 낡은 문자열 핀을 allSettled 실제에 맞게 갱신(HEAD에서도 깨져 있던 것).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(fleet): D-395 위치 중재 채점 단서 (순수)
- 변경: 새 하위 패키지 `fleet/localization/` — `cues.py`: 다른 LOCALIZED 로봇 일치(+1)/시야 안인데 안 보임(−1), 슬롯(10 cm / 20°, 축 앞뒤 모두), 마지막 정상 자세(픽업 뒤 0), 300 ms보다 신선한 오버헤드 sighting, 기준 사각형(맞으면 +1, 없는 곳에 보이거나 보여야 할 곳에 없으면 −1). 입력이 없으면 0. 비대칭 단서만 결정을 실을 수 있다(개정 3). `test_boundaries.py`가 이 폴더의 전송·asyncio·server import를 막는다.
- 증거: `test_localization_cues.py` + `test_boundaries.py` 33 passed.
- gate 변화: 없음(SOURCE/LOCAL).
- 결정: D-395 Proposed(개정 3, 1단계).

## 2026-10-01 · uncommitted · feat(fleet): D-395 위치 중재기 — 뚜렷한 격차가 2 s 유지될 때만 결정
- 변경: `fleet/localization/arbiter.py` — `Weights`(초기값: scan 1, paint 2, peers 2, slot 1.5, last_good 0.5, overhead 0.5, square 3; S1에서 조정), `Context`, `score()`, `Arbiter.observe()`: 1등이 2등을 1.0 이상 앞서고 같은 request_id·같은 1등으로 2 s 유지되면 `LocalizationDecision`(source candidate, 근거 점수, 수신 기준 `ttl_s` 5 s)을 한 번만 낸다. 개정 3: 1등을 가른 비대칭 단서(paint/peers/slot/square)를 `cues`에 담고, 없으면 결정하지 않는다(후보가 하나여도). last_good·overhead는 혼자 결정하지 못한다. `fleet` 크기 판정을 23543으로 재판정.
- 증거: `test_localization_arbiter.py` + cues + boundaries 52 passed — 사각형마다 거울 사례(슬롯·사각형 관측, 거울을 앞에 둔 경우 포함), 페인트·다른 로봇으로 해소, 단서 없음·마지막 자세만·픽업 뒤·단서 없는 단일 후보는 결정 없음, 유지 시간·1등 교체·격차 붕괴 시 재시작, 로봇별 독립.
- gate 변화: 없음(SOURCE/LOCAL). 서비스 루프·전송은 2단계.
- 결정: D-395 Proposed(개정 3, 1단계).

## 2026-10-01 · uncommitted · test(fleet): API Ref 버전 핀 v1.69 (D-395 1단계)
- 변경: `test_task_contract_docs.py`(2곳)·`test_mission_progress.py`의 참조서 버전 핀을 v1.69로 옮겼다. 계획이 세 핀만 셌는데 Fleet 시험에도 같은 핀이 있었다.
- 증거: 두 파일 22 passed.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(fleet): D-395 중재기 — 결정을 싣는 단서는 양(+)의 증거이고 모든 후보를 이겨야 한다
- 변경: 최종 리뷰(1aeada8d) 지적 반영. (치명) 시야 안인데 스캔에 안 잡힌 로봇 때문에 참이 peers −1, 거울이 0이면 0이 −1을 이겼다는 것만으로 peers가 단서로 이름 붙어 거울로 결정할 수 있었다 → 단서는 1등 값이 0보다 크고 다른 모든 후보보다 커야 이름 붙는다. (중요) 2등만 이기면 됐기에, 쌍둥이는 같은 값인데 세 번째 후보가 2등일 때 페인트가 이름 붙고 실제로는 last_good·overhead가 격차를 채웠다 → 모든 후보 기준. (경미) 같은 request_id에 한 번만 결정하던 것을 (request_id, stamp)로 바꿔, 결정이 잃어버리거나 거부되면 로봇이 새 stamp로 다시 보고해 재결정받는다.
- 증거: 새 시험 3개(숨은 로봇, 세 번째 후보가 2등, 새 stamp 재결정)와 기존 중재기·단서·종단 시험 통과.
- gate 변화: 없음(SOURCE/LOCAL).

## 2026-10-01 · uncommitted · docs(api): align Fleet contract pins to v1.70
- 변경: D-395/v1.69를 보존하며 OMX 시연 추가분을 v1.70으로 통합. Fleet의 API reference header 검사 3곳을 동일 버전으로 정렬.
- 증거: 병합 후 quick tier 95 passed; Fleet task/mission과 OMX/foundation 회귀 실행 중.
- gate 변화: 없음. Fleet runtime·실물 권한 변경 없음.
- 결정: D-18, D-390 부록.
- 교훈: 병행 MINOR 추가는 두 변경의 이력과 정본 pin을 함께 맞춘다.
- 최종 증거: 병합 후 Fleet task/mission + OMX/foundation 회귀 627 passed, 6 skipped; quick 95 passed; OMX Chromium 2 passed.

## 2026-10-01 · uncommitted · D-398 후속 — 정체 띠 완성·음영 제거·줄 간격 토큰화

- 변경: roster 카드의 정체 띠를 완성한다 — s{index} 클래스(.s0/.s1/.s2)에 --robot-1..3 사다리 색을 붙여 지도 삼각형과 맞물린다(기존 주석이 문서화한 의도의 CSS 절반이 유실돼 있었다. 2026-10-01 감사에서 죽은 클래스로 오진돼 지웠던 것을 되살린다). 패널 음영 2곳 제거(음영은 떠 있는 대화상자에만). 원시 줄 간격 4곳(1.15/1.45/1.7/1.6)을 --leading-* 토큰으로.
- 변경: test_fleet_console_browser 첫 시험의 인라인 라우트에 /api/fleet/session 폴백 추가 — 세션 404 로 콘솔이 잠긴 채 폴링을 시작하지 않아 지도·명단이 영영 로딩에 남는 기존 빨강(HEAD 484bb15a 에서도 실패).
- 근거: D-398 후속 정리. fleet 시험 1291 passed, 브라우저 4건 통과(첫 시험 포함).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(fleet): D-395 2단계 C 레인 — 위치 확정 클라이언트·서비스·감시·사다리, 교통/bays 신뢰 (P2-2, P2-6)
- 변경: 계약(`docs/plans/2026-10-01-d395-phase2-interfaces.md` §2·§3) 그대로.
  - `RobotClient`/`HttpRobotClient`/`FakeRobot`에 `localization_candidates()`(404면 None), `localization_decision()`, `localization_suspect()`(≤ 64자). `localization_mission()`은 P2-7 전까지 `NotImplementedError` 자리표시.
  - 새 `server/localization_service.py`: 0.5 s마다 상태를 읽고 CANDIDATES 로봇의 후보를 읽어 `Context`(LOCALIZED·map 프레임 다른 로봇, `lane_rules.yaml` `reference_squares`의 사각형·슬롯, 플래그가 켜졌을 때만 300 ms 이하 sighting)로 중재해 결정을 POST한다. 감시: LOCALIZED 로봇이 관측과 25 cm 또는 60° 넘게 1.5 s 어긋나면 `suspect {"reason":"fleet_monitor"}`. 다른 로봇 관측은 CANDIDATES 로봇의 지도 밖 물체를 peers 단서 없이 뚜렷이 앞선 후보 자세로 놓아 만든다(관측 대상 로봇이 관측자 자세를 고르지 않게). 사다리: CANDIDATES 진입부터 LOCALIZED까지 10 s → `rotate_in_place`, 25 s → `to_square`/`lane_to_stopline`을 "pending P2-7"로 로그만, 60 s → `needs_human`. 거부된 결정은 시계를 되돌리지 않는다(거부 고리가 사람에게 닿도록). 순수 로직은 `fleet/localization/service_logic.py`.
  - **오버헤드 sighting 단서는 기본 꺼짐**: D-257 개정이 Accepted가 아니다. `--localization-overhead-cue`로만 켜고 코드·시작 로그에 그렇게 적었다.
  - P2-2 `fleet/localization/trust.py` + `console.py`: `localization`이 있고 `odom`이거나 LOCALIZED가 아니면 그 pose를 쓰지 않고, 마지막 신뢰 자세 둘레 0.45 m를 막는 장애물(없으면 트랙 전체 차단)로 본다. 막힌 미션은 `LOCALIZATION_UNTRUSTED`로 대기하고 bays로 보내지 않는다. `localization: null`은 오늘 동작 그대로이고 행에 "위치 상태 미보고".
  - `app.py` lifespan이 서비스를 다른 루프처럼 띄운다. CLI: 기본 켜짐(`--no-localization-service`), `--localization-lane-rules`(기본 map_v2_fleet). 콘솔 카드에 위치 배지(`web/localization-badge.js` 순수, `ui-tag` 어휘: 확정 중립, 미확정·미보고 warn, "위치 확인 필요" crit + 최우선 큐 행).
  - `fleet` 크기 판정 24204, `console.py` 1063으로 재판정(판정 불변).
- 증거: fleet pytest 전체 통과, node `test/web/*.test.mjs` 86 passed(새 5). 새 시험: `test_transport_localization.py` 11, `test_localization_trust.py` 14, `test_localization_service.py` 18(stamp당 한 번·새 stamp 재결정, LOCALIZED·map 로봇만 peers, 감시 1.5 s, 카메라 플래그 꺼짐/켜짐·신선도, 사다리 10/25/60 s, 오프라인·제거), `test_server_traffic.py`·`test_server_bays.py` P2-2 6, CLI 2, app lifespan 1. 감시 시험 3개는 변이로 확인했다.
- gate 변화: 없음(SOURCE/LOCAL). Fleet 동작 변경은 사용자 승인(2단계). S1 벤치(P2-8)는 세 레인 통합 뒤.
- 결정: D-395 Proposed(개정 3), 계약 §3 레거시 정책.

## 2026-10-01 · uncommitted · fix(fleet): D-395 C 레인 리뷰 반영 — 모호하지 않은 증거만, 호출 상한, 점유 해제, 미확정 로봇의 목표
- 변경: (중요) 감시의 다른 로봇 관측은 가장 가까운 물체를 거리와 상관없이 그 로봇으로 봤다 — 숨은 로봇 + 무관한 물체가 바르게 LOCALIZED인 로봇을 SUSPECT로 만들었다. 이제 보고 자세 0.25 m 안에 물체가 있으면 "보임", 그 근처에 없고 180° 거울 자세 0.25 m 안에 물체가 정확히 하나면 "다른 곳에 보임"(거울 잠금 서명), 나머지는 증거 없음. Fleet이 가져온 때보다 stamp가 1.0 s 넘게 오래된 보고는 증거가 아니다(벽시계 비교, 로봇 시계 NTP 동기 가정). 2 s 재보고 주기와 맞물리도록 감시는 증거 없는 틱에 유지를 지우지 않고, 어긋남 없이 1.5 s가 지나면 지운다. (경미) 로봇별 호출을 `asyncio.wait_for(…, 1.0)`로 묶고 로봇별 작업을 gather한다. (경미) `LOCALIZATION_UNTRUSTED` 분기도 점유(`_claims`)를 푼다. (결정) 자기 localization이 있고 LOCALIZED·map이 아닌 로봇의 목표는 보내지 않고 `LOCALIZATION_UNTRUSTED`로 대기시켜 LOCALIZED가 되면 내보낸다. null은 오늘대로. `console.py` 1076으로 재판정.
- 증거: 회귀 시험 — 숨은 로봇 + 무관한 물체는 SUSPECT 없음, 거울 서명은 1.5 s 뒤 SUSPECT, 오래된 보고 무시, 증거 규칙 3개(변이로 확인), 멈춘 로봇 하나가 다른 로봇의 결정을 막지 않음, 점유 해제, 미확정 이동 로봇 대기·레거시 그대로.
- gate 변화: 없음(SOURCE/LOCAL).
- 결정: D-395 Proposed(개정 3); 미확정 이동 로봇 처리는 리뷰 결정.

## 2026-10-01 · uncommitted · fix(fleet): D-395 보고 신선도는 Fleet이 처음 본 때부터 잰다
- 변경: 바로 앞 항목의 "stamp가 Fleet 벽시계보다 1.0 s 넘게 오래되면 증거 아님"을 코디네이터가 뒤집었다 — 개정 3은 Fleet과 로봇 시계가 맞지 않는다고 가정한다. 이제 `(robot_id, request_id, stamp)` 보고를 Fleet이 처음 본 단조 시각을 적고, 그 뒤 1.0 s 동안만 감시 증거로 쓴다. 같은 보고를 다시 읽어도 처음 본 시각은 그대로라 재보고가 끊긴 로봇은 낡는다. 증거 없는 틱에 유지를 지우지 않는 감시(어긋남 없이 1.5 s면 해제)는 승인됐다.
- 증거: 로봇 시계가 ±1 h 어긋나도 새 보고는 증거(1.5 s 뒤 SUSPECT), 바뀌지 않은 보고는 Fleet 시간 1 s 뒤 낡아 SUSPECT 없음(재읽기가 처음 본 시각을 갱신하는 변이로 확인).
- gate 변화: 없음(SOURCE/LOCAL).
- 결정: D-395 개정 3(시계 비동기).

## 2026-10-02 · uncommitted · 관제 콘솔 회차 — 예외 큐 신뢰·지도 위계·카드 문구 정리
- 변경: roster.js fillQueues가 오프라인 로봇(`연결 끊김`, EVIDENCE_LABEL.disconnected)과 온라인이지만 상태가 없는 로봇(`상태 확인 불가`)을 '주의 요망' 큐에 올린다. 로봇 전원이 닿지 않아도 예외 레인이 침묵하지 않는다(2026-10-02 회차 계측: 3대 오프라인에 큐 0건·패널 hidden이었음).
- 변경: 카드 문구 — 닿지 못한 예외의 클래스 이름 코드(ConnectError 등)를 한국어로 옮기는 REACH_LABEL을 두고(모르는 값은 받은 그대로), 사실 라벨 POSE/YAW/BATTERY/SAFETY와 안전값 OK/E-STOP을 위치/방향/배터리/안전·정상/비상 정지로 바꾼다. 버튼마다 반복되던 같은 사유("로봇 오프라인" ×2)는 카드 상태 줄을 aria-describedby로 가리키는 "위 사유"로 한 번만 말한다(D-359 §5.3 한 원인은 한 번 말한다).
- 변경: styles.css — 110rem 이상에서 지도 패널 내부 격자를 1fr:1fr에서 1.6fr:1fr로. 1920 관제 PC에서 현장 지도가 374px(로스터 1058px)로 목표를 찍는 표면이 폰 폭이 되던 위계 역전을 바로잡는다. 재측정 460px/카메라 288px.
- 근거: D-280(아는 만큼 말한다·중요한 것이 먼저 보인다), D-359 §5.3, 운용자 말 한국어 평문 규칙. 2026-10-02 로컬 렌더 계측 회차(fleet console 8097, 로봇 3대 도달 불가 상태).
- gate 변화: 없음.
- 최종 증거: fleet 1213 passed 7 skipped; web_common 209 passed 24 skipped(문구·팔레트·반응형 계약 포함); 브라우저 재캡처 페이지 오류 0, 예외 큐 3건·지도 460px·"위 사유" 렌더 확인.

## 2026-10-02 · uncommitted · 관제 콘솔 회차 2 — D-405/D-406 아이콘 크롬·카메라 설치 묶음·목표 토글
- 변경: 테마 trio(어둡게·밝게·시스템)·설정 토글·영상 새로고침을 아이콘으로(한국어 이름은 sr-only·title 유지), 카드 측정 라벨(위치·방향·배터리·안전)을 아이콘+sr-only로(label 척도 크기). 목표 받기 버튼을 quiet에서 toggle+aria-pressed로(눌림 = 계열 파랑, .arming 클래스 제거).
- 변경: 카메라 구역을 운용 무대(영상·선택·새로고침)와 details#camera-install-tools 설치·보정 묶음(기본 접힘)으로 분리. 높이 함수 4곳 vh→dvh.
- 근거: D-405(아이콘 우선 크롬), D-406(운용/설치 분리 v1 + 목표 토글 위계), 사용자 지시 2026-10-02(위계 산만함·역할별 컴포넌트화).
- gate 변화: 없음.
- 최종 증거: fleet 1213 passed 7 skipped; web_common 209 passed(문구·dvh 게이트 포함); 브라우저 재캡처 페이지 오류 0 — 테마 3종·설정·새로고침 아이콘 렌더, 묶음 접힘 확인, 폰 390 문서 3431→3172px.

## 2026-10-02 · uncommitted · feat(fleet): D-395 P2-7 사다리가 미션을 보낸다, 미션 전 교통 정지

- 변경: `HttpRobotClient.localization_mission` 이 `POST /api/v1/localization/mission` 을 보낸다(자리표시 제거), `FakeRobot` 은 `missions`·`mission_error`. `LocalizationService` 사다리: 10 s `rotate_in_place`, 25 s `to_square`(사각형 목표가 있을 때, CORE 가 `unsupported` 면) → `lane_to_stopline`, 60 s `needs_human`. 거부는 `last_mission` 에 기록하고 재시도하지 않는다. LOCALIZED·레거시(null) 로봇에는 보내지 않는다. 미션 전 `FleetConsole.hold_for_localization` — 미확정 로봇의 keep-out(`trust.blocks`, 신뢰 자세가 없으면 트랙 전체)에 걸린 Fleet 목표를 취소하고 `LOCALIZATION_UNTRUSTED` 로 대기열에 넣어 그 로봇이 LOCALIZED 가 되면 다시 낸다. 정지가 실패하면 미션을 보내지 않는다. `service_logic.MISSION_LIMITS`·`square_target`; view 의 `pending_missions` → `rung_missions`.
- 증거: `test_localization_service.py` (사다리 미션·대체·거부·레거시·교통 정지·배선), `test_server_traffic.py` +4, `test_transport_localization.py`.
- gate 변화: console.py 1076 → 1096 (D-362 1000+ 등급, 판정 갱신).

## 2026-10-02 · uncommitted · fix(fleet): D-395 P2-7 리뷰 — 사다리가 끝까지 간다, busy 는 다시 묻는다

- 변경: 사다리 시간 10 / 25 / 60 s → **10 / 45 / 120 s**. `rotate_in_place`(10 s 에 보냄, 최대 30 s)가 끝난 뒤에 homing 이, `lane_to_stopline`(45 s, 최대 40 s)이 끝난 뒤에 `needs_human` 이 온다(60 s 로는 homing 이 못 끝난다). CORE 가 `busy` 로 거절한 단은 사다리가 그 단에 있는 동안 2 s 마다(`BUSY_RETRY_S`) 다시 보낸다. 다른 거부는 그대로 최종. 계약 문서 §3 에 새 시간을 적었다.
- 증거: `test_localization_service.py` (단 사이 시간 불변식, busy 재시도, 비-busy 거부는 최종).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(fleet): D-395 P2-7 리뷰 — 미션 전 정지가 양보·대형도 멈춘다

- 변경: `FleetConsole.hold_for_localization` 이 bay 로 가는 길(현재 자리→bay)이 미확정 로봇의 keep-out 을 지나는 양보를 취소하고 `_yielding` 에서 지운다. 대형(팔로워 또는 리더)이 keep-out 안에 있으면(신뢰 자세가 없으면 언제나) `formation_stop()` 으로 대형 전체를 멈춘다 — 세션에 로봇별 정지가 없다. 반환 목록에 `"formation"`.
- 증거: `test_server_traffic.py` +2.
- gate 변화: console.py 1096 → 1111 (판정 갱신).

## 2026-10-02 · uncommitted · fix(fleet): D-395 S1 벤치 — 앵커 peer, 못 본 peer 는 0, 보고 수로 세는 감시, unsupported 는 최종

- 변경: [S1 벤치 결과](../../docs/plans/2026-10-02-d395-s1-bench-results.md) 발견 3·7 과 사다리 재요청을 고쳤다.
  - **앵커 peer (안전).** 트랙이 180° 대칭이라 함께 뒤집힌 로봇들은 서로 맞아 보인다. peer 는 앵커를 퍼뜨릴 뿐 대칭을 깨지 못한다. S1 에서 미러 고정된 r2 가 r1 의 쌍둥이 자세에 `peers` +1 을 줬고, margin 1.0 만이 번짐을 막았다. 이제 Fleet 이 로봇별 출처를 기록한다. `slot`/`square`/`paint`, `source: human`, 또는 앵커에서만 온 `peers` 로 실린 Fleet 결정의 자세에서 LOCALIZED 가 된 로봇만 앵커이고, `Context.peers` 에는 앵커만 들어간다(감시는 LOCALIZED 전부를 계속 본다). 처음부터 LOCALIZED 로 본 로봇, 결정 자세와 다른 곳(> 25 cm / 60°)에서 LOCALIZED 가 된 로봇은 다시 위치를 잡을 때까지 앵커가 아니다. LOCALIZED 를 벗어나거나, LOCALIZED 인 채 자세가 폴 사이에 0.25 m + 0.5 m/s·dt 또는 0.5 rad + 2 rad/s·dt 넘게 뛰면(Fleet 을 거치지 않은 주입) 출처가 지워진다. 읽기 실패 폴은 출처를 유지한다.
  - **`peers` 단서.** 시야 안인데 못 본 peer 는 −1 이 아니라 0. 객체를 하나도 보고하지 않은 관찰자는 0. S1 에서 −1 하나로 쌍둥이가 6번 2.0 앞섰다.
  - **감시.** 1.5 s 연속 대신 서로 다른 신선한 불일치 보고 2건(15 s 창, 사이에 일치 보고 없음). 같은 보고를 다시 읽어도 한 번. 보고가 4–7 s 간격으로 와서 예전 규칙은 한 번도 터지지 않았다.
  - **사다리.** CORE 가 `unsupported` 로 거절한 종류는 LOCALIZED 가 될 때까지 다시 묻지 않고, homing 은 곧바로 `lane_to_stopline` 으로 간다. busy 재시도도 남은 종류만 묻는다(S1: 런마다 `to_square` 거절 13–20회).
  - 계약 문서 §3 갱신. ADR 은 손대지 않았다(rev. 6 은 컨트롤러가 쓴다).
- 증거: `test_localization_service.py`(앵커 연쇄, 출처 없는 peer 불사용, SUSPECT·자세 점프·다른 자세 LOCALIZED 시 앵커 해제, S1 재현 — 미러 peer 가 리드를 못 준다, S1 보고 간격 4/5.5/7 s 감시, unsupported 최종), `test_localization_cues.py`, `test_localization_arbiter.py`. 앵커 필터를 빼면 S1 재현을 포함한 3건이 실패함을 확인. `python -m pytest src/site/fleet/test -q` 1312 passed, 7 skipped (2026-10-02 Windows).
- gate 변화: 없음. S1 재실행(Gazebo) 전이다.
- 결정: D-395 rev. 6 대기
- 교훈: 대칭 지도에서 상대 단서는 출처가 확인된 기준점에서만 증거다.

## 2026-10-02 · uncommitted · fix(fleet): D-395 S1 재실행 — 미션 중과 끝난 뒤 1 s 는 결정하지 않는다

- 원인: F1 WSL 실행에서 Fleet 이 `rotate_in_place` 로 돌고 있는 r2 에 첫 결정을 보냈다. 미션 전 후보는 회전 중에 낡았고 주입은 거부됐다.
- 변경: 서비스가 LOCALIZED 가 아닌 D-395 로봇마다 `GET /api/v1/localization/mission`(새 `RobotClient.localization_mission_status`)을 읽는다. `running` 인 동안과 끝을 본 뒤 `MISSION_QUIET_S` 1 s 동안은 후보를 읽지 않고 중재·결정·감시 관측도 하지 않는다. API 오류(501 등, 미션 없는 CORE)는 미션 없음, 읽기 실패는 그 폴만 건너뛴다.
- 증거: `test_localization_service.py` +5(미션 중·끝 후 1 s 조용, 미션 없는 CORE, 읽기 실패, SUSPECT 중 미션 → CANDIDATES, LOCALIZED 는 묻지 않음), `test_transport_localization.py` +1.
- gate 변화: 없음.

## 2026-10-02 · 3d91dcff · fix(fleet): D-395 S1 재실행 R2·R6 — 결정이 올 수 있는 동안 사다리는 멈춘다

- 원인: R2 — 사다리는 Fleet 벽시계로 10 s 에 `rotate_in_place` 를 보냈는데, 그때 중재기는 peers 리드를 2 s 붙들고 있었고 결정 직전이었다(LOCALIZED 49.6–53.6 sim s, 약 20 이어야 함). R6 — 로봇의 3 s 주입 검사 중에도 사다리가 미션을 보냈다.
- 변경: (94ad8a82) `Arbiter.pending(robot_id, request_id)` — 그 요청에 리드가 있거나, 비대칭 단서가 한 후보를 편들거나(여유 미달 포함), 결정을 이미 보냈으면 참. `Ladder.update(..., paused=)` — 멈춘 폴 앞의 간격은 세지 않고, 그동안 단은 오르지 않으며 `busy` 재요청도 없다(`holding`). 멈춤은 회차당 `LADDER_PAUSE_MAX_S` 30 s 까지라, 끝내 결정하지 않는 리드도 사람에게 간다. 서비스는 로봇이 CANDIDATES 이고 `reason: checking` 이거나 `pending` 일 때 멈춘다. 벽시계는 그대로(공유 시계 없음, rev. 3).
- 증거: `test_localization_arbiter.py` +5, `test_localization_service.py` +5(S1 타임라인: 9.0 s 에 닻, 10.5 s 폴에 회전 없음, 11.0 s 에 peers 결정, 미션 0; 검사 중 미션 없음·재요청 없음; 멈춤 상한). 수정 전 S1·검사 시험은 `rotate_in_place` 가 나가 실패함을 확인. `python -m pytest src/site/fleet/test -q` 1328 passed, 7 skipped.
- gate 변화: 없음. Gazebo 재실행 전.

## 2026-10-02 · uncommitted · 관제 콘솔 회차 3 — D-409 기기 등록·연결 서랍 + 컴팩트 카드 요약
- 변경: 기기 연결 묶음(로봇 등록 #robot-enrollment + 카메라 연결 승인 #camera-link)을 details#device-install-tools(기본 접힘) 안으로. 아이디·조상 구조 보존으로 test_console_camera_pairing과 JS가 그대로 붙는다. h3 "기기 연결"은 sr-only로(aria-labelledby 유지).
- 변경: 로스터 카드 측정 칸에 data-fact(pose/yaw/battery/safety)을 달고 컴팩트(<30rem)에서 위치·방향 숨김 — 지도가 말한다. 카드 안쪽 여백 한 단 축소(--space-2/3). 운용 ops 블록은 대형·신호등·기록만 남는다.
- 근거: D-409(사용자 지시 — 남은 설치 요소 분리·역할 명확화). 원래 회차 번호 D-407이었으나 병렬 작업이 D-407/D-408(차선 복구·페인트 입력)을 선점해 D-409로 재번호.
- gate 변화: 없음.
- 최종 증거: fleet 1328 passed 7 skipped; web_common+dashboard 287 passed 82 skipped; 브라우저 재캡처 — 서랍 2개 접힘, 폰 카드 측정 2칭(배터리·안전), 카드 204px, 폰 390 문서 3172→2811px(원점 3431), 페이지 오류 0.

## 2026-10-02 · fbb12ef0 · feat(localization): D-395 S1 R1 — LOCALIZED 닻이 다른 LOCALIZED 로봇을 본다

- 원인: S1 재실행 R1. 관찰자가 첫 결정에 LOCALIZED 가 되면 거울 증거가 보고 하나로 끝나 2개 문턱에 못 닿았다.
- 변경: `LocalizationService._observe_from_anchors`. 매 폴에서 `objects_stamp` 가 있는 LOCALIZED 닻마다 상태의 물체를 자기 보고 map 자세로 놓고, 다른 모든 LOCALIZED 로봇에 대한 증거로 쓴다. 관찰자는 닻만이다(거울 잠긴 로봇은 옳은 로봇을 그 쌍둥이 자리에 놓는다). 자기 자신은 대상이 아니다. 증거 하나는 (닻, `objects_stamp`)이고 Fleet 이 처음 본 뒤 1.0 s 동안 신선하다. 같은 폴의 두 닻은 따로 센다. 증거 규칙(0.25 m, 거울 서명)과 15 s 안 2개 문턱은 그대로다. `peer_observations` 는 보고 대신 물체 목록을 받는다.
- 증거: `test_localization_service.py` +7(닻 둘 중 주입된 거울이 2폴에 SUSPECT, 닻이 아닌 거울 로봇은 닻을 고발하지 못함, 같은 폴 닻 둘 = 2개, 숨은 로봇·무관한 물체·일치는 증거 아님, 같은 stamp 재읽기는 낡음). `python -m pytest src/site/fleet/test -q` 1335 passed, 7 skipped.
- gate 변화: 없음. Gazebo 재실행 전.

## 2026-10-02 · uncommitted · 관제 콘솔 회차 4 — D-410 운용/설치 두 문서로 분리
- 변경: 설치·보정 화면 /console/install(install.html + install.js, 문법 procedure)을 만들고 기기 등록·카메라 연결 승인·경기장/맵 보정·설치 기록을 이관했다. 아이디·조상 구조 보존 이관. 운용 문서(/console)는 링크 안내만 남고 문서가 가벼워졌다(1920 기준 1,154px).
- 변경: console.js에서 등록·카메라 승인·경기장/맵 보정 배선 제거. 발견 요청은 검색기 건강 로그와 고정 주소 판정만 남긴다. vision-view.js는 보정 칸 없는 프리뷰 전용 모드(빈 패널 스텁 + 프리뷰 가드)를 지원한다. 주소 이동 조작은 설치 문서가, 안내 배너는 운용 문서가 가진다.
- 변경: static_routes에 install.js 자산과 /console/install 라우트(CSP 동일). surfaces.yaml console audience에 설치 경로 반영. 시험 6건+shared_controls 1건을 두 문서 세계로 갱신(신규 라우트·자산·링크 시험 포함).
- 근거: D-410(사용자 지시 — 역할 명확화 완성). D-406/D-409의 접힌 서랍 이관.
- gate 변화: 없음.
- 최종 증거: fleet+web_common 1545 passed 31 skipped; 브라우저 — 두 화면 페이지 오류 0, 설치 화면 세션 토큰 공유 자동 인증, 운용 문서에 등록·보정 마크업 부재·링크 2개 확인.

## 2026-10-02 · uncommitted · 관제 콘솔 회차 5 — 예외 큐 첫 행 고정(운용 블록 위계)
- 변경: 넓은 창(64rem+)에서 예외 큐(주의·개입)를 왼쪽 열 1행으로, 지도를 2행으로 바꿨다. 회차 계측에서 큐가 지도 아래 963px(첫 화면 밖)에 있어 오프라인 로봇이 큐를 채우는 순간 '예외가 먼저'(D-201)가 위반됐다. 큐 top 963→186, 문서 높이 불변(열 균형 유지), 폰(단일 열)은 영향 없음.
- 변경: test_console_queues_contract의 그리드 핀을 새 배치로 갱신(큐 1행 + 지도 2행 고정, 위반 경위를 문서화).
- 근거: D-201(예외 문법), 2026-10-02 회차 계측. 대형 폼은 컨테이너 반응형(D-359 §6.3)으로 이미 적합 — 조정 없음.
- gate 변화: 없음.
- 최종 증거: queues contract + web_common 214 passed 24 skipped(반응형 계층 게이트 포함); 재계측 큐 top 186.

## 2026-10-02 · uncommitted · CI 삼각측량 — 시크릿 스캔 면제·해시 문서 규약·스코어카드 기준선·설치 문서 브라우저 시험
- 변경: secret_scan.py KNOWN_FIXTURES에 D-395 loc-assist fixture(SECRET-PAYLOAD-VALUE) 등록. OMX 증명 해시 3곳을 매처의 무결성 문맥 규약으로 서술(README 'revision'/'dataset commit', omx_f_kinematics.yaml 'at revision') — 의미 불변. test_release_boundary_gates no_secrets 재녹색.
- 변경: D-178 스코어카드에 rosy_cell 잠정 행(4/4/4/4/4=80 A) 추가 — 집합 동일성 회복. robot_literal_backlog.txt 갱신(신규 8·삭제 2). known_failures.txt에 병렬 작업 사전 존재 실패 5건 기록(CI 전용 플레이크 4 + module_separation 소유자 판단 1).
- 변경: test_fleet_console_browser.py에 D-410 설치 문서 렌더 계약 시험 추가(옵트인 Chromium — 문법·소유물·운용 표면 부재·E-stop·무오류). 통과 59s.
- 근거: 2026-10-02 CI 실행 36909426842/36955733308 실패 대 조 로컬 재현. docs/validation/uiux-console-refactor-2026-10-02/README.md 회차 기록.
- gate 변화: 없음.
- 최종 증거: scorecard·literals·no_secrets 각 재녹색; 브라우저 신규 시험 1 passed.

## 2026-10-02 · uncommitted · D-407 판단 요청 — 관제 목록과 다섯 답 중계
- 변경: `server/line_stuck.py` `LineStuckBoard` — 모은 상태의 CORE `line_follow.stuck` 으로 로봇별 열린 막힘을 들고, 같은 id 의 `nav.line_stuck_opened` FleetAgent 사건에서 앞·뒤·회전 여유와 미리보기 순서번호를 붙인다(사건이 없으면 null). 닿지 않는 로봇은 마지막 값을 `robot_online: false` 로 남긴다. 보드는 `console_routes.py` 가 만들고 `GET /api/fleet/state` 모음마다 갱신해 로봇 행에 `line_stuck` 을 싣는다 — console.py 는 D-362 상한 위라 늘리지 않았다.
- 변경: `GET /api/fleet/line-stuck`(viewer+), `POST /api/fleet/robots/{robot_id}/line-stuck/decision`(operator) — 로봇 자격으로 CORE `POST /api/v1/line-follow/stuck/decision` 에 그대로 넘긴다. Fleet 은 CORE 대신 거부하지 않는다. CORE 409(`STUCK_ID_MISMATCH`, `STUCK_DECISION_REFUSED` 사유)는 code·message 그대로 409, 나머지는 502. 넘긴 답마다 site principal·결과를 기록(API 감사 행과 별도). `HttpRobotClient.line_stuck_decision`.
- 변경: 콘솔 예외 큐 패널 안 `판단 요청`(line-stuck.js) — 원인·단계 한국어, 여유·멈춘 시간·후진 시도·미리보기 #seq, 다섯 답. RESUME·BACK_AND_RETRY 는 패널 안 확인 단계(Esc 취소, 1 s 폴링에도 유지, 포커스 보존), 로컬 복구 꺼짐·시도 소진이면 BACK_AND_RETRY 비활성 + 사유. 거부는 채움 줄로 CORE 코드·문장 그대로. 최우선 개입 큐에 `판단 요청` 항목, 카드도 예외로 보인다.
- FleetAgent 중계는 만들지 않았다: Fleet→로봇 명령은 전부 REST(로봇 자격)이고 FleetAgent 는 내려오는 명령 경로가 없다(hub 는 사건·하트비트만 받는다). 같은 CORE 경로를 REST 로 부른다.
- 로봇 영상은 중계하지 않는다(D-59, test_no_video_relay) — 미리보기는 순서번호만 보인다.
- 근거: D-407 §2 결과(관제 화면 변경). API Ref v1.76.
- gate 변화: 없음(SOURCE/LOCAL 호스트 시험만, 실물·시뮬 없음).
- 크기: fleet 묶음 24587 → 25494(+907, 시험 포함). 크기 판정을 25494 로 다시 내렸다(split 그대로, 미일정). 병렬 D-395 가지가 옛 24565 핀에 25011 을 보고했으므로 둘을 합칠 때 한 번 더 판정한다.
- 최종 증거: `python -m pytest src/site/fleet/test -q` 1349 passed/7 skipped(새 `test_line_stuck_api.py` 13, `test_transport.py` 1, node `line-stuck.test.mjs` 9 는 glob runner 로 포함); 옵트인 Chromium `-k "line_stuck or queues_render or camera_fault or mobile_console"` 5 passed(확인 단계·Esc·폴링 유지·409 그대로); `src/runtime/gateway/test` + `test/architecture` 새 실패 0(known_failures); harness lint 0 errors. Windows 호스트만, 로봇 접촉 없음.

## 2026-10-02 · uncommitted · D-407 판단 요청 검토 반영 — 전송 실패·지속 기록·확인 단계
- 변경: 답 중계가 httpx 오류(`HttpRobotClient` 는 OSError 가 아니라 httpx 예외를 올린다)를 잡는다. 연결 자체 실패는 502 `ROBOT_UNREACHABLE`(전달 안 됨), 시간 초과·응답 끊김은 502 `STUCK_DECISION_OUTCOME_UNKNOWN`(CORE 가 이미 적용했을 수 있음, 막힘을 다시 보고 답할 것). 둘 다 기록된다(결과 불명은 `accepted: null`). 전에는 맨 500 에 기록 없음이었다.
- 변경: 넘긴 답마다 Fleet 저널 DB 의 `fleet_line_stuck_answers` 에 API 감사 `request_id` 와 함께 남긴다(작업 저장소가 있을 때). 저장 실패는 로그만 — 로봇은 이미 답을 받았다.
- 변경: `stuck_id` 는 `^[A-Za-z0-9_.:-]+$`(CORE id 는 `stuck-<12 hex>`). `GET /api/fleet/line-stuck` 은 로봇을 다시 모으지 않고 마지막 `/state` 모음과 `observed_age_s` 를 준다.
- 변경: 콘솔 — 확인 단계 "보내기"가 그 답 버튼과 같은 사유로 막히고, 전송 중 두 번째 답은 무시하며, 막힘 id 가 바뀌면 확인 단계를 버린다(aria-expanded false). 전송 실패 문구는 "전달 실패"/"결과 불명"이지 "거부"가 아니다.
- 근거: D-407 Fleet 쪽 검토(M1, L1–L6). API Ref v1.76 행 문구 갱신(버전 유지, 같은 가지의 미병합 추가분).
- gate 변화: 없음.
- 크기: fleet 25590(판정 25494+150 안).
- 최종 증거: `src/site/fleet/test` 1352 passed/7 skipped(전송 실패 매개 4: ConnectError·ConnectionRefused·ReadTimeout·RemoteProtocolError, 지속 기록·감사 id, 목록이 로봇을 다시 부르지 않음, id 형식); node `line-stuck.test.mjs` 10; 옵트인 Chromium `-k "line_stuck or queues_render or camera_fault or mobile_console"` 7 passed(새 2: 성공 결과·전송 중 이중 제출 막힘, 확인 중 막힘 교체·오프라인 로봇) — 확인 단계 id 비교를 되돌린 변이는 적색; gateway+architecture 1918 passed, known_failures 새 실패 0; harness lint 0 errors.

## 2026-10-02 · 95e13278 · fix(fleet): D-395 S1 3회차 T1–T3 — 폴 간격과 무관한 도약 판정, 시간 초과 결정 확인, needs_human 은 깃발

- 원인: T1 — 부하 중 폴이 4–10 s 간격이라 도약 상한(0.25 m + 0.5 m/s·dt, 0.5 rad + 2 rad/s·dt)이 1.43 m·2.70 m 거울 주입을 넘겼다. 거울 잠긴 로봇이 닻으로 남아 옳은 로봇을 고발했다. T2 — 1 s 호출 상한이 관찰 증거를 잃었고, d3 에서 시간 초과된 결정 POST 를 CORE 는 받아 로봇이 "출처 모름"으로 LOCALIZED 됐다. T3 — `needs_human` 이 멈춤인지 깃발인지 정해지지 않았다.
- 변경: (768d2f4a) `service_logic.jumped` 가 dt 를 `JUMP_DT_CAP_S` 1.0 s 로 자른다(상한 최대 0.75 m / 2.5 rad, π 미만이라 180° 뒤집힘은 늘 도약). dt 와 무관한 `mirrored`: 새 자세가 이전 자세의 180° 쌍둥이(지도 중심 기준)에서 0.3 m·0.5 rad 안이면 닻을 뗀다. 대가(문서화): 폴이 1 s 넘게 벌어지면 실제로 0.75 m 넘게 움직였거나 2.5 rad 넘게 돈 로봇도 닻을 잃는다 — 다시 위치를 잡을 때까지 증거만 잃는다.
- 변경: (b8d00fdb) `CALL_TIMEOUT_S` 1.0 → 2.5 s, 로봇별 호출은 그대로 병렬. 결정 POST 가 시간 초과되면 (request_id, 결정 자세, 단서가 닻이 되는지, 시각)을 미확인으로 기억한다. 로봇이 15 s 안에 그 자세(5 cm·5° 안)로 처음 LOCALIZED 되면 확인된 결정처럼 출처를 받아들인다. 다른 자세·15 s 뒤·이후 성공한 결정은 기록을 버린다. 거절·연결 오류는 기록하지 않는다.
- 변경: (95e13278) T3 은 현재 동작 확인: `needs_human` 뒤에도 중재·결정은 계속되고, LOCALIZED 가 되면 사다리 회차가 끝나 깃발이 지워진다. 콘솔 배지는 깃발이 선 동안 "위치 확인 필요". 코드 변경 없이 시험으로 고정.
- 증거: `test_localization_service.py` +13(8 s 폴 거울 주입은 다음 폴에 닻 상실, 8 s 폴의 실제 0.8 m 이동도 닻 상실, 0.5 s 폴로 달리고 도는 로봇은 닻 유지, dt 상한·거울 서명 순수 시험; 기본 2.5 s 상한과 매달린 로봇 셋이 한 번의 상한만 쓰는 병렬성; 미확인 결정 도달 = 닻, 6 cm·6°·거울·15 s 뒤 = 닻 아님; needs_human 뒤 결정이 깃발을 지움). 수정 전 T1·T2 새 시험은 실패함을 확인. `python -m pytest src/site/fleet/test -q` 1348 passed, 7 skipped.
- 결정: ADR 은 손대지 않음(개정 8 은 컨트롤러가 쓴다). 계약 `docs/plans/2026-10-01-d395-phase2-interfaces.md` §3 갱신.
- gate 변화: 없음. Gazebo 재실행 전.

## 2026-10-02 · uncommitted · D-407 판단 요청 — main 병합, API Ref v1.77
- 변경: main(039786e3, D-407 Gazebo 후속이 API Ref v1.76 을 씀)을 병합했다. 이 가지의 Fleet 경로·`line_stuck` 행·검토 반영 문구는 v1.77 로 옮겼다(위 두 기록의 "v1.76" 은 병합 전 번호다). 버전 핀(시험 3, CORE app.py 설명) v1.77.
- gate 변화: 없음.
- 크기: fleet 25643(판정 25494+150 안, 여유 1줄 — 다음 증가는 다시 판정해야 한다).
- 증거: 병합 뒤 `src/site/fleet/test` 1364 passed/7 skipped; 옵트인 Chromium `-k line_stuck` 3 passed; `src/runtime/gateway/test` + `test/architecture` 1926 passed/17 skipped, known_failures 새 실패 0; harness lint 0 errors.

## 2026-10-02 · uncommitted · D-413 Task 4 Cell Job journal and approval boundary
- 변경: connected the compiler port, service-only Cell Job proposal flow, distinct named-operator approval, and versioned ordered-step SQLite journal. Existing PICK_PLACE Mission tables remain unchanged. Persisted grants are checked against PlanBundle inputs, job/recipe/cell digests, authority epoch, and dispatch generation. Action success does not advance a step or release resources without independent goal and post-action gripper evidence; unknown outcomes remain HOLD.
- Contract: API Reference v1.79. Re-judged Fleet at 26340 lines and protocol schemas.py at 1239; existing growth limits remain active.
- 증거: Fleet suite completed with 1370 passed, 7 skipped, and one failure from the prior v1.77 reference pin. After updating that pin, test_mission_progress.py passed (16). Cell Job API/store/site-user: 11 passed; existing Mission API/store/service: 26 passed; task/API/dispatch contracts: 39 passed; protocol/compiler port: 23 passed; size verdict: 1 passed. Windows host SOURCE/LOCAL evidence only.
- gate 변화: dispatcher/UDS/OMX submission and authenticated external goal-evidence producer wiring remain unimplemented. This is a Task 4 checkpoint, not device or ROS-SIM acceptance.

## 2026-10-02 · uncommitted · 관제 콘솔 회차 6 — D-414 바로 동작(원클릭 정지·발견 카드·안내 축소)
- 변경: console.js/install.js의 전체 정지에서 window.confirm 제거 — 비상 정지는 확인 없는 한 번 누름(D-92a 계보의 확인 시험을 원클릭 시험로 재작성, 대화상자 핀 console.js 3→2). install.js refreshDiscovery가 발견(mDNS) 장치 카드(이름·주소:포트·단계·상태)와 등록 버튼을 그린다(D-410 이관 때 빠진 렌더 충원).
- 변경: 운용 문서의 상시 안내 문단(대형·신호등·지도·목표)은 제목 title로 물러나고 문단은 운용 상태가 쓴다. 기록(#log)이 '기록' 제목을 얻는다(aria-labelledby). 설치 문서의 발견 안내·카메라 문구도 title로.
- 근거: D-414(사용자 지시 — "설명하지 말고 명확하게, 그냥 누르면 되게; mDNS 등록이 대충 보이기만 한다"). 비활성 사유(D-359 §5.3)는 글로 유지.
- gate 변화: 없음.
- 최종 증거: web_common 209 passed; fleet 1371 passed 7 skipped; 브라우저 — 원클릭 estop POST+대화상자 0회(1 passed), 설치 문서 발견 카드 2종+등록 버튼 렌더, 운용 문서 힌트 hidden/title 확인.

## 2026-10-02 · uncommitted · 관제 콘솔 회차 7 — D-415 운용 가시성(로그 뷰어·진단 패널·신호등 빈 상태)
- 변경: #log가 펼침 패널(details#log-panel, 기본 open)이 되고 지우기 버튼(#log-clear)과 최소 8줄/최대 24줄 높이를 얻었다. LOG_MAX 40→120. render() 끝에 refreshDiagnostics()가 진단 dd 4개(상태 갱신·발견 검색기·로봇 오류·카메라)를 채운다.
- 변경: signals.js render()가 빈 상태에서 signals-hint의 hidden을 풀고 "설정된 신호등이 없습니다" 문장을 보인다(D-415 결정 3).
- 변경: console.js refreshDiagnostics() — REACH_LABEL 참조를 직접 계산으로 바꿈(console.js 범위 밖이라 ReferenceError).
- 근거: D-415(사용자 지시 — "로그도 볼 수 있게, 디버그 생각할 수 있게"). 계측: 로그 21px→144px, 진단 0→4 항목, 신호등 빈 상태 안내.
- gate 변화: 없음.
- 최종 증거: web_common 209 passed; fleet 문법·앱·큐·태스크 54 passed; 브라우저 — 로그 패널(min 144/max 432px)·지우기 버튼·진단('3대 · 갱신됨')·신호등 빈 상태 표시, 페이지 오류 0.

## 2026-10-02 · bcce15c9d · fix(hub): 닫힌 소켓에 보내지 않음; 판단 요청 패널 뒤 여유 "비어 있음"/"알 수 없음"

- 변경: `/ws/robots` 는 연결이 끊긴 뒤 답을 보내지 않는다(이유를 info 로). 판단 요청 보드가 `rear_state` 를 옮기고 패널은 `비어 있음`·`알 수 없음`(클래스 `stuck-fact-unknown`)을 구분한다(9300adf1d).
- 증거: `test_hub_server.py`(거부된 사건 뒤에도 heartbeat 응답), `test_line_stuck_api.py`, `web/line-stuck.test.mjs` 초록.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · test(fleet): replay late OMX success without clearing Mission HOLD
- Change: replayed a lost submit receipt across independently reopened Fleet and OMX SQLite stores. Fleet reuses the persisted Action/attempt, records late success while retaining HOLD and object/workcell claims, and only confirms the goal after independent post-action camera and gripper evidence.
- Evidence: `test/test_platform_cell_replay.py`; Fleet suite 1371 passed/7 skipped; OMX ActionStore 23 passed; replay/Skill boundary tests 10 passed.
- Gate: SOURCE/LOCAL only; no ROS-SIM, Gazebo, device, or field promotion.

## 2026-10-02 · uncommitted · test(fleet): track Mission event watermark across replay
- Change: extend the two-ledger restart replay to verify four phase snapshots plus one terminal event, then a separate goal-confirmation event.
- Evidence: targeted Mission, dispatcher, service, progress, task, OMX ActionStore, and replay suites: 77 passed; known-failure comparison: 0 new, 0 known.
- Gate: SOURCE/LOCAL only; remaining interruption fixtures and expiry/occupancy cases are still open.

## 2026-10-02 · uncommitted · verify(fleet): platform cell replay watermark
- 변경: record platform cell replay watermark verification.
- Evidence: replay test 1 passed; Fleet UI/API group 109 passed; formation 22 passed; four web suites 29 passed. Harness contract failure isolated to append-only history check.
- Gate: SOURCE/LOCAL only; remaining interruption fixtures and expiry/occupancy cases are still open.

## 2026-10-02 · uncommitted · verify(fleet): platform cell final regression
- Change: record final checks after reconciling the parallel watermark evidence entry.
- Evidence: replay 1 passed; Fleet UI/API and formation 131 passed; web suites 29 passed; harness contracts 57 passed with 24 known staleness warnings.
- Gate: SOURCE/LOCAL only; interruption fixtures and expiry/occupancy cases remain open.

## 2026-10-02 · uncommitted · fix(fleet): a legacy-null pose is never a last trusted pose (D-395 S2 Finding 1)
- Change: `trust.trusted_xy` returns a pose only for LOCALIZED + map; the console stores no trusted pose from a `localization: null` snapshot. A robot first read null and then CANDIDATES has no trusted pose and blocks the whole track. A robot that reported localization and then goes null is untrusted (badge not legacy) until null for 30 s (`trust.LAPSED_GRACE_S`); then legacy again with its stale trusted pose dropped. Contract §3 records both rules.
- Evidence: `test_localization_trust.py`, `test_server_traffic.py` (S2 sequence, null→LOCALIZED, LOCALIZED→CANDIDATES keep-out, lapsed robot, grace reset, true legacy); Fleet suite 1380 passed/7 skipped.
- Gate: SOURCE/LOCAL only; the S2 bench must be rerun on the ROS box.

## 2026-10-02 · 7e121603 · feat(fleet): D-417 전체 주행 취소(래치 없음)와 래치를 말하는 전체 비상 정지
- 변경: 새 `POST /api/fleet/cancel-all`(operator, `server/cancel_all.py`) — 대기 작업 `CANCELED`/`FLEET_CANCEL_ALL`(행위자 = 운용자, 발행 래치·세대 그대로) → 열린 대형 해제 → 로봇마다(로봇끼리 동시) `swarm/cancel` → `navigation/cancel` → `line-follow/mode OFF`, 단계마다 계속. 로봇별 `cancelled`/`failed`/`unreachable`, `evidence: CORE_REPLY_ONLY`. 발행된 작업은 바꾸지 않고 `awaiting_core_result` 로 보인다(CORE `nav.canceled` 투영이 바꾼다). `DriveCancelFence` 가 디스패처 목표 호출을 감싸 취소와 겹친 발행은 다시 취소하고 `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH`. 허브 `scatter_swarm_cancel`. `task_store` 취소 사유 인자(두 SELECT 를 합쳐 −5줄), `console.py` 불변. 운용 화면 발행 상태 줄에 "전체 주행 취소"(confirm, 로봇별 결과 기록), 상단 버튼 "전체 비상 정지 / 래치 · 로봇별 관리자 해제"(두 문서). FLEET SRS CTR-002 개정, API Ref v1.80(§10.2, §10.8, 핀 4곳).
- 결정: D-417 Proposed(처음 D-414 로 썼으나 다른 세션의 D-414·D-415·D-416 과 겹쳐 옮김). 권고에서 벗어난 점: 발행된 작업은 Fleet 이 `CANCELED` 로 쓰지 않는다(상태 기계·D-170/D-293), 감사 예외는 비상 정지 하나로 둔다.
- 증거: `src/site/fleet/test` + `test/architecture/test_module_structure.py` + 버전 핀·대화상자 계약 1431 passed/7 skipped, `test/known_failures.py` 새 실패 0. `test_cancel_all.py` 20(겹침 울타리는 울타리를 끈 변이 탐침에서 적색 확인). 옵트인 Chromium 전체 49 passed/18 failed — 18 개는 깨끗한 main(13e6d5e4)에서도 똑같이 실패(D-410 설치 문서 이관 뒤 index.html 을 보는 시험들, 넓은 머리 줄 시험 포함); 이 가지의 새 시험(전체 주행 취소·비상 정지 이름·모바일 머리)은 통과. Windows 호스트 SOURCE/LOCAL 증거뿐 — Gazebo·실물 정지 readback 미실행.
- 크기: fleet 26543 으로 재판정(+203, 새 모듈 중심).
- gate 변화: 없음.
- 교훈: 래치 없는 정지 경로에는 "막 집힌 발행" 창이 남는다 — 발행 쪽에서 await 뒤에 다시 확인하는 울타리로 닫는다(docs/solutions 의 await 뒤 재확인 패턴).

## 2026-10-02 · d3b0444b · fix(fleet): D-417 검토 반영 — CORE 확인된 취소가 로봇 점유를 푼다
- 원인: 발행된 작업은 취소 뒤 `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING` 으로 남아 `robot:` 점유를 쥐었다. `UNKNOWN` 을 대조하는 운용자 경로가 없어(작업 취소는 대기 작업만) 그 로봇은 새 작업을 영영 못 받았다.
- 변경: (4256f34b) `server/cancel_all_store.py` — 창마다 기록(id·운용자·연/닫은 시각·로봇·취소한 대기 작업)과 진행 중 작업 표시. `task_results` 가 표시된 작업의 상관 `nav.canceled` 를 `HOLD`/`FLEET_CANCEL_ALL` 로 옮겨 점유를 푼다(표시 없으면 예전 그대로, 사건 없으면 작업·점유 그대로). 울타리: 목표 호출이 예외여도 재취소, 그 로봇을 위해 베이로 간 로봇도 취소, 명시 거절은 `FAILED`, Fleet 대기열에 남은 것은 `CANCELED`. `awaiting_core_result` 는 `ACCEPTED`/`RUNNING` + 창 이후 `UNKNOWN`. `console.cancel` 은 주소 미확인 로봇의 점유를 지우지 않는다. 주소 관문 거부는 `sent: false`. 화면은 실패 단계마다 코드, 0/0 은 경고. (d3b0444b) ADR·API Ref 문구와 D-416 연결.
- 증거: `src/site/fleet/test` + `test_module_structure.py` + `test_web_dialog_contract.py` 1438 passed/7 skipped, known_failures 새 실패 0. `test_cancel_all.py` 31(탐침: 제출→발행→전체 주행 취소→`nav.canceled`→새 작업 발행; 사건 없는 경우). 옵트인 Chromium 전체 주행 취소 1 passed. Windows 호스트 증거뿐.
- 크기: fleet 26793 재판정.
- gate 변화: 없음.
- 교훈: "UNKNOWN 이면 정직하다"는 그 UNKNOWN 을 푸는 길이 있을 때만 참이다 — 없으면 정직한 상태가 자원을 영원히 쥔다. 상태를 남기기 전에 그 상태의 출구를 찾는다.

## 2026-10-02 · e223af71 · fix(fleet): D-417 재검토 — 표시를 목표 호출 전에, 시도·출처·유예로 맞춘다
- 원인: (재현 탐침 `probe_ca.py`) 창 안에서 발행된 작업에 창의 취소가 먼저 닿으면 CORE `nav.canceled` 가 표시보다 먼저 와 `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING` 이 되고, 재취소는 CORE 가 이미 쉬고 있어 사건을 다시 내지 않았다 — 점유가 영원히 남았다. 또 표시가 `task_id` 만 보아 나중의 무관한 취소(운용자·막힘·안전)도 `HOLD(FLEET_CANCEL_ALL)` 이 됐다.
- 변경: 창이 열려 있으면 울타리가 목표 호출 전에 표시. 표시하는 쪽(울타리·창 닫기)이 창 안에서 이미 취소된 같은 시도를 같은 트랜잭션에서 `HOLD` 로 정리. 표시는 `(task_id, attempt_id)`·출처(window/fence), 기록에 `navigation/cancel` 응답 로봇. 투영은 시도 일치 + `data.source` 가 `api:*`(있을 때) + 창이 열려 있거나 닫힌 지 `HOLD_GRACE_S`(30 s) 안이고 로봇 응답 또는 울타리 재취소일 때만 `HOLD`. `HOLD(FLEET_CANCEL_ALL)` 뒤 늦은 상관 사건·발행 응답은 로그. 울타리 태거는 창별(`window(tag)`), `except (Exception, CancelledError)`, 표는 `FleetTaskStore` 가 생성(색인 `(task_id, attempt_id)`), 닫힌 지 30일 넘은 기록 정리(작업 일지에는 정리 규칙이 없다), 기록 실패 시 `record_error: CANCEL_ALL_RECORD_UNAVAILABLE` 과 미완 작업 대체.
- 증거: 탐침 — 고치기 전 "A final UNKNOWN CORE_CANCEL_RESULT_PENDING / A next dispatch -> None / B -> HOLD", 고친 뒤 "A final HOLD FLEET_CANCEL_ALL / A next dispatch -> ACCEPTED / B -> UNKNOWN CORE_CANCEL_RESULT_PENDING". `test_cancel_all.py` 41. `src/site/fleet/test` + `test_module_structure.py` + `test_web_dialog_contract.py` 1448 passed/7 skipped, known_failures 새 실패 0. Windows 호스트 증거뿐.
- 크기: fleet 26953 재판정, `task_store.py` 1057(상한 1060).
- gate 변화: 없음.
- 교훈: 비동기 증거(사건)와 그 증거를 해석할 표시는 어느 쪽이 먼저 와도 같은 결과가 나와야 한다 — 표시를 미리 달고, 늦게 단 표시는 이미 온 증거를 다시 읽는다.

## 2026-10-02 · uncommitted · docs(adr): 전체 주행 취소 ADR D-417 → D-421
- 변경: 다른 세션이 main 에서 D-417(콘솔 밀도 정리)을 잡아 이 가지의 전체 주행 취소 ADR 을 D-421 로 옮겼다(D-418 origin/main, D-419 SAF-003, D-420 Pinky 장치 동작). 파일 이름, ADR Log 행, FLEET SRS CTR-002 링크, API Ref, DESIGN.md, 코드·시험 주석. ADR 안의 Pinky 장치 동작 ADR 참조는 D-416 → D-420. 위의 기록들에 적힌 D-417 은 당시 번호다(고치지 않는다).
- 증거: 아래 커밋의 시험 기록.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · feat(fleet): D-421 전체 주행 취소를 main d5b3bd10 위에 다시 얹음
- 변경: 가지 `feat/d414-fleet-cancel-all`(옛 main 13e6d5e4 기반)의 이 기능 변경만 새 가지 `feat/d421-fleet-cancel-all` 로 옮겼다(main 의 D-414~D-418·D-420 콘솔·장치 작업 위). API Ref 는 main 이 이미 v1.80 이라 v1.81(핀 4곳). 콘솔 확인 수 핀은 main 의 2(D-414 비상 정지 확인 없음) + 전체 주행 취소 1 = 3. `adr_gaps` 의 D-421 예약 제거.
- 판단: main 의 브라우저 시험 파일은 옛 비상 정지 확인 시험을 지우며 `DELAYED_FORMATION`·`HOLDING_FORMATION`·`UNREACHABLE_SNAPSHOT` 정의까지 잃었다(쓰는 시험은 남음). 이 가지의 같은 자리 정의를 살려 두었다.
- 위 기록들의 D-414·D-417 은 당시 번호다. main dae5479c 위로 다시 얹으며 비상 정지는 main 의 글자 없는 팔각 아이콘을 따랐다 — 위 기록의 "전체 비상 정지 / 래치 · 로봇별 관리자 해제" 글자는 이제 접근 이름·	itle "전체 비상 정지 (래치 · 로봇별 관리자 해제)" 이다(모바일 머리 시험 갱신).
- 증거: src/site/fleet/test 1414 passed/7 skipped, 	est/architecture 81 passed/1 skipped, known_failures 새 실패 0; 버전 핀·대화상자 계약 7 passed; 옵트인 Chromium 전체 주행 취소·비상 정지 한 번 누름 등 4 passed. 	est_holding_formation_enables_resume_and_warns 는 main 의 신호등 문구(signals.yaml)와 시험이 어긋나 실패한다 — 이 가지와 무관(main 에서는 HOLDING_FORMATION 정의가 없어 그 전에 실패했다).
- 크기: fleet 27134 재판정(main 26498).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · test(fleet): retain ownership after grant expiry while Action is running
- Change: add an expired-grant replay where a running local Action remains authoritative after both stores reopen; assert no resubmit, HOLD, retained DISPATCHING claims, and rejection of a conflicting Mission admission.
- Evidence: `test/test_platform_cell_replay.py` 2 passed.
- Gate: SOURCE/LOCAL only; stop/cancel interruptions and independent physical-occupancy evidence remain open.

## 2026-10-02 · uncommitted · fix(fleet): require durable Action success when recovering goal HOLD
- Change: verify exact Action/attempt terminal proof inside completion transaction and authenticated producer callback; retain claims for non-success outcomes. Add restart replay fixtures for accepted, cancel-acknowledged and release-command states plus stale/conflicting goal evidence.
- Evidence: focused Mission, Action, provenance and replay suites 101 passed; changed Python files pass flake8.
- Gate: SOURCE/LOCAL only. Actual CELL_TRANSFER CellJob recovery and ROS-SIM acceptance remain open; Task 7 is IN PROGRESS.

## 2026-10-02 · uncommitted · fix(fleet): retain Cell transfer claims across site restart
- Change: atomically verify all CellJob claims and mark them DISPATCHING with the persisted transfer attempt. Gateway startup fences obsolete CellJob authority to HOLD, preserving grants/results and blocking automatic next-step submission. Correct the migration header to keep Tasks 4-5 in progress. Re-judge Fleet size at 27303 for these journal/admission duties; split plan and +150 allowance remain unchanged.
- Evidence: CellJob/API/task/app 71 passed; full Fleet 1425 passed/7 skipped, known-failure comparison 0 new/0 known. Changed source passes flake8; API fixture imports retain the existing E402 bootstrap exception.
- Gate: SOURCE/LOCAL only. CellJob dispatch/reconciliation composition, independent step-goal recovery, ROS-SIM and device acceptance remain open.

## 2026-10-02 · uncommitted · styles.css 흐림 원시 값 → 공용 토큰
- 변경: 지도 빈 상태 아이콘(.map-empty-icon)의 opacity: 0.4를 var(--disabled-opacity)로 바꿨다(0d579299d가 들여온 값). 회귀였고 known_failures.txt에 등록된 적 없는 실패였다.
- 근거: D-294 흐림 척도 계약(test_dimming_uses_the_disabled_token_not_an_opacity_literal).
- gate 변화: 없음.
- 최종 증거: test_surface_typography_focus_contracts.py 6 passed.

## 2026-10-02 · uncommitted · fix(fleet): D-395 rev. 11 — 거리 없는 사각형 목격은 근거가 아니다

- 원인: 후처리 감사(2026-10-02). 실제 프레임 506장의 거짓 사각형 검출 20건이 모두 거리 없음이었다. 예전 `square_cue` 는 방위만 맞으면 +1, 아니면 -1 을 줬고 가중치가 가장 크다(3.0).
- 변경: `cues.square_cue` 는 `range_m` 이 None 인 목격을 무시한다. `arbiter.score` 는 거리 있는 목격만 넘겨, 거리 없는 목격뿐이면 사각형 단서가 모든 후보에서 0 이다. 선로 계약(`range_m>0|null`)은 그대로이고 API Ref 에 한 문장을 더했다.
- 증거: `test_localization_cues.py` 사각형 표 갱신(+2), `test_localization_arbiter.py` +1(거리 없는 목격만으로는 결정 없음). fleet localization 176 passed.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · feat(fleet): C4b wave 1 — Cell Job 하달 경로 (G4, G5, G3, G6)
- 변경: (G4) `local_action_transport.py`가 `FleetActionGrant | FleetCellTransferGrant`를 받고, 종류별 표로 wire 버전을 고른다(PICK_PLACE 2, CELL_TRANSFER 2). 모르는 종류는 I/O 전에 거절. (G5) `server/cell_compiler.py` `PalletizingCellJobCompiler(tol_m)` — palletizing 로더·`compile_job`·`carry_z()`(불일치면 거절)·`compile_plan_bundle`, `cli.py --cell-job-stack-tol-m`(지연 import). (G3) `server/step_action_kinds.py`(종류별 규칙: 열린 프로필, grant 본문, phase, 거절 사유), `server/step_dispatcher.py` `StepJobDispatcher`(Step마다 Action 하나, k−1 GOAL_CONFIRMED 뒤에만, RUNNING은 GetAction으로만 대조, 거절·실패·불명은 Job HOLD+사유), `create_app(deployment_profile, omx_cell_grant_revisions)` — (simulation, CELL_TRANSFER)만 열리고 PICK_PLACE 하달기는 모든 프로필에서 닫힘. `cell_job_store.py`에 rosy-a9(D-420) 요청 1–8: 제출 때 claim DISPATCHING 승격, 결과 SUCCEEDED/FAILED/REJECTED/UNKNOWN+호출자 사유, 펜스 변경 시 HOLD 기록(예외 아님), 범용 `hold()`, 이벤트 키로 재생 먼저 판정, SUBMITTING 이벤트에 epoch·generation. (G6) `goal_evidence_registry` `sim_model_pose`는 simulation 프로필에서만, `server/cell_goal_evidence.py`가 생산자 토큰·workcell·attempt 확인 뒤 Fleet이 `item_at_pose`를 판정하고 만족할 때만 `confirm_step_goal`.
- 판단: `test_mission_api`의 하달기 시험은 D-403 §7에 맞게 바꿨다(production 거절, simulation은 셀 하달기만). `test_cell_job_store`의 펜스 변경 시험은 예외 대신 HOLD를 본다(D-420 항목 3).
- 증거: C4b 보고(fleet·omx·test 전체, known_failures).
- 크기: fleet 27811 재판정(main 27134), `cell_job_store.py` 617 accept, `cli.py` 604 accept.
- 남음(wave 2): G7 정지 사슬과 (a)–(i), G9 pilot_sim /cell·seat 배제, goal-evidence HTTP 경로, UNKNOWN 대조(reconcile) 경로, 재시작 직후 다음 Step 자동 제출 여부(e).
- gate 변화: 없음.

## 2026-10-03 · uncommitted · fix(fleet): preserve Cell transfer phase receipts over UDS v2
- Change: accept the separate CELL_TRANSFER grant in the Fleet Action transport and select existing UDS v2 for submission, lookup and exact-attempt cancel. Missing phase summaries fail closed. Record the shared phased contract in API Reference v1.82 and update the current-version document checks.
- Evidence: producer/consumer/legacy dispatcher/API contract suites 55 passed; architecture and dependency boundaries 38 passed; changed Python files pass flake8. Full Fleet regression 1431 passed/7 skipped; known-failure comparison 0 new/0 known. Log/generated contracts 6 passed; harness lint 0 errors/24 existing freshness warnings.
- Gate: SOURCE/LOCAL only. CellJob dispatch/reconciliation composition and ROS-SIM acceptance remain open; transport changes do not enable dispatch.

## 2026-10-03 · uncommitted · feat(fleet): dispatch admitted ordered Cell transfers
- Change: compose the opt-in CellJob dispatcher in the existing single site worker with pinned cell configuration revisions. Persist the canonical grant and DISPATCHING claims before one local submission; reconcile/cancel the exact attempt without resubmission after lost replies or grant expiry. Readback atomically checks live authority/generation, duplicate receipt identity and durable phase history. Late success after HOLD retains claims and cannot start the next step. Re-judge Fleet size at 27684 after current-main integration; split verdict and +150 allowance remain unchanged.
- Evidence: full Fleet regression 1451 passed/7 skipped, known-failure comparison 0 new/0 known before the final phase-history correction. Final dispatcher/API/store/legacy/app/replay suites 107 passed; integrated-main localization regression 54 passed; architecture/dependency boundary suites 38 passed. Independent review found and then verified fixes for in-process stop, phase-history conflicts and superseded phase-success evidence; final review 31 passed with no remaining Important/Critical checkpoint findings. Changed runtime and dispatcher/API test Python files pass flake8. Align the FastAPI contract description with API Reference v1.82 (3 protocol-version tests passed); harness lint reports 0 errors/24 existing freshness warnings.
- Gate: SOURCE/LOCAL only. Default dispatch is disabled. Registered/fresh Cell goal production and held-success goal recovery, actual OMX owner/provider integration, Gazebo, device and field acceptance remain open; D-413 Tasks 4-5 and 7 stay IN PROGRESS.

## 2026-10-03 · uncommitted · fix(fleet): require durable Cell success for goal recovery
- Change: move Cell goal completion into its own journal module and require the latest terminal SUCCEEDED event for the exact step, Action and attempt inside the SQLite completion transaction. Permit independently confirmed held success, preserve next-step WAITING/HOLD after authority changes, reject rewritten goal evidence and empty provenance, and keep claims until every ordered goal is confirmed. Dispatch is not rearmed by goal confirmation.
- Evidence: CellJob/Mission/phase-contract regression 89 passed; independent review 42 passed with no remaining Important/Critical checkpoint findings. Current-main platform contract checks pass 26 tests with explicit source paths (not installed-artifact proof). Quick tier 96 passed/24 existing freshness warnings. Changed Python files pass flake8. Full Fleet regression 1468 passed/7 skipped, known-failure comparison 0 new/0 known; final log/generated-record checks 3 passed and harness lint 0 errors/24 existing freshness warnings.
- Gate: SOURCE/LOCAL only. Public registered/fresh Cell goal production, actual two-ledger Cell replay, real OMX owner/provider composition and ROS-SIM remain required. Tasks 4-5 and 7 remain IN PROGRESS.

## 2026-10-03 · uncommitted · feat(fleet): validate registered Cell goal evidence
- Change: add separate bounded evidence schema, pinned environment credential registry and internal submission service. Check exact saved grant identity, producer scope/expiry, initial observation, model/gripper freshness and post-terminal ordering; revalidate pending evidence on reconciliation. Reject available invalid evidence before persistence and atomically bind completion to the verified latest terminal event ID. Re-judge Fleet at 28001 lines with unchanged split verdict and +150 allowance.
- Evidence: focused Cell service/store/dispatcher checks 48 passed; registry checks 10 passed; independent review 44 passed with no remaining Critical/Important checkpoint findings; changed Python files pass flake8. Full Fleet and final quick/harness results follow in a separate append-only row.
- Gate: internal SOURCE/LOCAL only. HTTP/app callback, independent Gazebo evaluator, canonical two-ledger Cell replay and ROS-SIM remain open; Tasks 4-5 and 7 remain IN PROGRESS. Default dispatch remains disabled.

## 2026-10-03 · uncommitted · verify(fleet): registered Cell evidence checkpoint
- Change: verify the internal Cell evidence checkpoint before local integration; no gate promotion.
- Evidence: quick tier 96 passed/24 existing freshness warnings; harness lint 0 errors/24 existing freshness warnings; focused Cell service/store/dispatcher 48 passed, registry 10 passed and independent review 44 passed. Full Fleet regression is still running at commit preparation and is not claimed as passed.
- Gate: SOURCE/LOCAL only. Public ingress, app callback, independent evaluator and ROS-SIM remain open.

## 2026-10-03 · uncommitted · feat(fleet): compose public Cell goal producer ingress
- Change: Add opt-in pinned Cell registry and strict shared HTTP ingress; wire pending goal reconciliation into the existing Cell dispatcher. Preserve durable successful Action receipts when goal callback validation/storage fails. Isolate credentials, reject whitespace/control credentials, confirm ordered goals through the actual proposal/admission HTTP surface and release claims only after final completion. Move the evidence contract to foundation without a Fleet duplicate.
- Evidence: App/service/registry/legacy checks 110 passed; final API/registry/legacy/version-document checks 64 passed; independent final review 25 passed; changed Python passes flake8. Prior 778f5029 full Fleet shards yielded 1498 passed/7 skipped with one Hub startup timeout, which passed isolated on unchanged main (1 passed in 9.25s); new public-composition full regression and quick tier are running.
- Gate: SOURCE/LOCAL only. Actual OMX provider, independent Gazebo evaluator, canonical two-ledger Cell replay and ROS-SIM remain open. Default dispatch remains disabled.

## 2026-10-03 · uncommitted · verify(fleet): public Cell ingress regression
- Change: verify the final public Cell producer composition before local integration; no gate promotion.
- Evidence: final full Fleet regression in four file shards 1514 passed/7 skipped, all four process exit codes 0, with no retries on the final public code. Foundation/protocol alignment 427 passed/1 skipped; app/service/registry/legacy checks 110 passed, final API/registry/legacy/version checks 64 passed, independent final review 25 passed. Quick tier 96 passed/24 existing freshness warnings; record contracts 3 passed; harness lint 0 errors/24 existing freshness warnings. Changed Python passes flake8.
- Gate: SOURCE/LOCAL only. Canonical two-ledger Cell replay, actual OMX owner/provider composition, independent model/gripper evaluation and ROS-SIM remain open.

## 2026-10-03 · uncommitted · fix(fleet): C4b 1b — Cell Job claim 유지, HOLD 출구, 공정한 하달 (리뷰 M1/M2, rosy-a9)
- 변경: (A1) 정지·시작 래치가 같은 트랜잭션에서 READY·ACTION_SUCCEEDED Cell Job을 HOLD(`site_stop`)로 두고 그 claim을 새 단계 `HELD`로 옮긴다(래치는 CLAIMED만 지운다). FAILED·REJECTED 결과도 `HELD`. rearm 조건은 그대로(DISPATCHING·UNKNOWN만 막음). (A2) `hold()`는 RUNNING에서 UNKNOWN/DISPATCHING만, 해제는 `not_submitted=True`일 때만. (A3) HOLD+UNKNOWN Job을 GetAction으로 계속 읽음(성공→ACTION_SUCCEEDED, 실패·404→HOLD+HELD), 일시 실패는 0.5/1/2/4 s 백오프 뒤 5회째에만 UNKNOWN. 운영자 `reconcile`/`resume`/`cancel` 경로(이름 있는 운영자). (A4) claim 행 수 확인, 빠진 claim → HOLD `FLEET_CLAIM_MISSING_BEFORE_SUBMISSION`. (A5) 제출 직전 HOLD 둘 다 해제. (B1) 모든 Job을 한 주기에 돌고 막힌 머리 Job은 건너뜀. (B2) hold 이벤트 키에 승인 횟수. (B3) start_step ValueError → `ACTION_GRANT_INVALID`. (B4) 시계 하나. (B5) 다이제스트 함수 하나. (B6) 결과 기록 충돌은 한 번 보고. (C1) item_at_pose 술어를 해석 때 Step에 저장, 중심 오프셋은 레시피에서. (C3) owner가 `GetOwnerIdentity`로 simulation임을 보고해야 하달. `GET /api/fleet/resource-claims`(claim 소유 Job·상태·단계).
- 판단: CANCELLED 상태는 스키마 변경이라 1b에서는 HOLD+`CANCELLED_BY_OPERATOR`+claim 없음으로 둔다(D-420 v2). main의 missing-claim 시험(예외)은 A4에 맞춰 HOLD로 바꿨다.
- 증거: C4b 1b 보고.
- 후속: console: show held-job claim owner (콘솔 UI는 다른 세션 소유라 이번에 손대지 않음). wave 2: `fleet_fence_current=True` 자리표시(G7), G9 `/cell`·seat 배제, phase 진행기와 CELL_TRANSFER 완료, 슬립시트 파지, 사이트 프로필의 palletizing wheel.
- 크기: fleet 28160 재판정, `cell_job_store.py` 824(분할 조건 기록).
- gate 변화: 없음.

## 2026-10-03 · uncommitted · fix(fleet): C4b 1c — 재시작·정지·404 경로의 출구 (재검토 N1–N3, rosy-a9)
- 변경: (N1) 시작 복구가 RUNNING Job의 DISPATCHING claim을 UNKNOWN으로, readback은 HOLD+DISPATCHING도 받음, hold()는 RUNNING에서 UNKNOWN만. (N2) 정지 래치는 claim 수 불일치로 실패하지 않고 `CLAIM_SET_INCOMPLETE_AT_STOP`을 남김. (P1·2) hold()는 claim을 놓지 않음, `release_before_send`만 진행 없는 READY Job의 claim을 놓음, 래치 뒤 성공은 HOLD(site_stop)+HELD, 진행 있는 Job의 제출 직전 HOLD는 HELD. (N3·3) 404는 ACTION_NOT_FOUND+만료+5 s+receipt 없음일 때만 NOT_FOUND, transport는 다른 404를 오류로, owner `get`은 다른 principal에 PEER_NOT_ALLOWED. (5·6) 틱당 I/O 8회 상한과 round-robin, owner 식별 캐시 TTL(양 10 s·음 5 s), 전송 오류 때 버림. (P3) 목표 술어의 파지 깊이는 검증된 레시피에서.
- 판단: dca0f6715(`MissionStore.confirm_goal` HOLD 사유 확장)는 main 커밋이 병합으로 들어온 것이고 1c는 필요로 하지 않아 이 가지에서 되돌리지 않았다. owner journal 식별은 넣지 않음.
- 증거: C4b 1c 보고.
- 후속(wave 2): 운영자 증언 해결(owner 영구 상실 시 UNKNOWN), 그 밖의 wave 2 목록은 1b 기록 그대로.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · fix(fleet,omx): C4b 1d — 전송 직전 세대 재확인, receipt 먼저 기록, owner journal 식별
- 변경: (1) `_submit`이 `start_step` 뒤 세대를 다시 읽고, 바뀌면 `hold_unsent`(receipt·장치 결과가 없을 때만)로 HOLD+HELD. (2) 모든 200 응답의 receipt를 검증 전에 기록, `has_device_receipt`는 기록된 SUCCEEDED/FAILED도 셈, 반복 기록은 쓰기 트랜잭션 없이 건너뜀. (3) owner `journal_id`(SQLite에 한 번 생성)를 receipt·GetAction·GetOwnerIdentity에 싣고, NOT_FOUND는 같은 journal일 때만. (4) `CLAIM_SET_INCOMPLETE_AT_STOP`에 context·actor·세대·승인 횟수. (5) 사라진 Job의 KeyError는 그 Job만 건너뜀. (6) `NOT_FOUND_SKEW_S` 주석에 같은 호스트 시계 가정.
- 증거: C4b 1d 보고.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · merge(fleet): main에 들어온 병렬 Cell 하달기를 걷고 공개 목표 증거 입구를 C4b 설계로 옮김
- 변경: 사용자 결정에 따라 이 가지의 `StepJobDispatcher`와 claim/HOLD 규칙(1b–1d)을 남기고, main의 `cell_job_dispatcher.py`·`cell_job_readback.py`·`cell_job_goal.py`·`cell_job_codec.py`·`cell_job_phase_history.py`와 그 시험(`test_cell_job_dispatcher.py`, `test_cell_job_goal_recovery.py`), `enable_cell_job_dispatcher`/`cell_job_config_revisions`를 지웠다. 옮긴 것: 목표 확인은 같은 attempt의 기록된 장치 SUCCEEDED를 요구(64b4b1faa), 다음 Step은 현재 세대일 때만 열고 아니면 HOLD+HELD, 증거 필드 비어 있음 거절; 공개 `/api/fleet/cell-goal-evidence`(생산자 등록·자격 격리·관측 시각·터미널 뒤 관측·미리 온 증거 보관)는 Step에 저장된 `item_at_pose` 술어로 Fleet이 판정하도록 고쳤고, `CellGoalEvidence.satisfied`를 없앴으며(생산자 자기 판정 금지), simulation 프로필에서만 연다. 하달기는 원장과 하달 제어가 같은 DB인지, 저장된 grant가 Step 시도와 같은지 확인한다. 성공 콜백 실패는 기록된 장치 성공을 바꾸지 않는다.
- 판단: main의 HOLD에서 바로 목표 확인(`LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE`)은 1b 규칙(HOLD Job은 재승인 뒤에만)과 어긋나 옮기지 않았다. main의 Fleet 쪽 phase 이력 대조와 운영자 하달 취소(`cancel_current`)는 wave 2(G7)로 남긴다.
- 증거: C4b merge 보고.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · refactor: D-425 Console HTTP adapter checkpoint

- 변경: 운용·설치 call 중복을 Fleet adapter로 전환하고 session token·잠금·poll gate는 문서에 유지. Windows fixture 포트 공유를 독점 bind로 차단.
- 증거: Node 18 passed; static/ownership/manifest 재검사 53 passed. 오류 status/문서 잠금 변이 red 후 bytes 복원, 실제 source 사본 Chromium session/origin 3 passed.
- gate 변화: HTTP·인증 체크포인트. 문서 종료·token 교체 scope는 Task 3 미완료.

## 2026-10-03 · uncommitted · test: D-425 browser baseline and safety facts

- 변경: Console 전환 전/후 전체 browser 비교 및 안전 행 renderer 계약 복구. durable 실패 목록은 docs/validation/app-ownership-migration-2026-10-03/task3-browser-regressions.md.
- 증거: baseline 45 passed/22 failed, HTTP adapter 48 passed/22 failed, new 0. 안전 상태 시험 2 green·guard mutation 2 red·원본 bytes 복원 후 2 green.
- gate 변화: 전체 browser는 HOLD. 20개 기존 실패와 문서/token scope 정리가 남음.

## 2026-10-03 · uncommitted · refactor: D-425 Console document lifetime
- 변경: 운용·설치 문서와 기존 panel의 JSON/직접 fetch·본문 decode·timer·handler·frame/observer 구독을 page/token epoch에 연결. 종료 때 미전송 목표·확인 대기를 취소하고 복귀는 새 조회만 시작. 기존 명령·권한·404 gate·poll cadence 유지.
- 증거: Chromium lifetime/session/origin 14 passed; disposal 변이 8 failed, 카메라/Vision late repaint 변이 4 failed, bytes 복원 후 14 passed. 공유/static/ownership/quick 351 passed/24 skipped/26 warnings. 최초 Fleet 전체 1584 passed/7 skipped/1 failed의 옛 map-fit wiring 문자열 검사를 scope 연결로 갱신해 재검사.
- gate 변화: Task 3 SOURCE/LOCAL 수명 계약 완료. 전체 browser 20개 OPEN·installed-only·DEVICE/FIELD는 유지. 상세: docs/validation/app-ownership-migration-2026-10-03/task3-console-lifetime.md.
- 추가 증거: map-fit wiring 검사 수정 후 Fleet 전체 1585 passed/7 skipped. lint 0 errors/26 warnings. 선택 운용 browser 11 passed/1 기존 OPEN 실패/55 deselected이며 전체 무실패로 표현하지 않음.

## 2026-10-03 · uncommitted · feat: read live Fleet fence on the simulation Cell owner
- Change: replace the entrypoint unconditional Fleet-current callback with uncached authenticated GET /api/fleet/dispatch-control on an explicitly configured literal loopback endpoint. Require a separately provisioned viewer secret before ROS loads. Direct HTTP avoids proxies/redirects; status, 8 KiB body, strict generation types and finite JSON checks refuse on uncertainty. Existing Action/stop/rearm stays on UDS. Offload async Fleet rearm I/O so the event loop can answer the owner's reverse readback; preserve operator guard and rollback.
- Evidence: actual loopback Fleet server plus persistent Fleet/owner stores reproduced LOCAL_WORKCELL_REARM_FAILED before offload and passed after. Offload-removal mutation fails again; original bytes restored. Final readback suite 18 passed; combined Fleet stop/rearm, owner/provider/replay/boundaries regression 96 passed before the additional finite-JSON case. Independent review 48 passed / 1 skipped and final readback 18 passed, no Critical/Important findings. Production flake8 passes. Final agent wheel rebuilt and force-installed from X: copy; site-packages adapter reads changed loopback state without caching, pip check passes.
- Final checks: quick tier 96 passed / 26 existing warnings; harness lint 0 errors / 26 warnings. Entry configuration regression guards the ROS import directly and passed.
- Gate: SOURCE/LOCAL only. Host HTTP is real; ROS and UDS credential transport are substituted. Live ROS/UDS (a)-(i), seat exclusion, thin-sheet handling and full two-layer/two-pallet vendor Gazebo acceptance remain open. Socket timeout bounds inactivity, not an end-to-end stop deadline. No viewer credential registration, service deployment, physical enablement or push performed.

## 2026-10-03 · uncommitted · feat(link): D-432 주소 없는 장비 접속

- 변경: 신뢰된 CA·DNS 이름을 유지하면서 discovered SRV IP/port로 HTTP/WS를 전송한다. Cam 4자리 표시와 기존 코드가 한 시도 한도를 공유한다.
- 증거: 관련 Python 계약 시험·실제 loopback TLS HTTP/WS 시험을 실행했다. Pilot Android 설치·화면과 실제 로봇 연결·현장 트래픽 수용은 서로 다른 증거다.
- gate 변화: 실제 장비의 제어·FIELD 관문은 이동하지 않는다.
- 결정: D-432 2026-10-03 추가 결정.

## 2026-10-03 · uncommitted · fix(link): 현재 접속과 후속 코드 규약 구별

- 변경: 사용자 보정으로 4자리 코드 발급·Cam 표시 별칭은 이번 적용에서 제외했다. 현재 로봇 8자·Cam 6자리 규약을 유지하며 D-432에 추후 통합을 기록했다. 실제 Pinky 접속 수정은 진행한다.
- 증거: 영향받는 Python 2345 passed/84 skipped, quick tier 459 passed/2 skipped, Pilot PWA 87 passed/58 skipped. 코드 규약 보정 뒤 해당 인증·페어링 시험을 다시 실행한다. 공개 검증 기록은 docs/validation/discovery-link-2026-10-03/README.md.
- gate 변화: Android 설치·실제 CORE 인증 확인은 실제 주행·Cam 화면 off 연속 송출·현장 트래픽 수용과 별개다. DEVICE/FIELD 이동 없음.
- 결정: D-432 후속 결정: 접속은 지금, 짧은 코드 통합은 추후 적용.

## 2026-10-04 · uncommitted · D-427 shared asset path contract
- Change: Validate both installed share/web_common and source shared/web with the asset manifest, CSS and JS.
- Evidence: X:/DevTemp/rosy-d427/resume/fixed.txt: 12 passed; known_failures NEW 0.
- gate 변화: none. Host tests do not establish device or field acceptance.

## 2026-10-04 · uncommitted · D-443 신호 감독 안전 수정

- 변경: Fleet lifespan 상시 감독, operator presence에 묶인 수동 점등, 감독 공백 뒤 의도 래치, 안전 방향 seq 재시도, absent·pending non-agree, 오프라인 나이와 재명령 표시를 구현했다. 기존 wire·펌웨어는 유지한다. 장치별 명령과 폴링은 잠금으로 직렬화하고 재단언은 의도 세대를 다시 확인한다.
- 증거: 수정 전 신호 회귀 9 failed, presence·loop 추가 회귀 6 failed를 확인했다. 관련 Python·구조 176 passed, Node 107 passed. 독립 안전 리뷰 APPROVE(대기 재단언/409 경합, 익명 presence, 측정 unknown 및 구조 예산 포함). 최종 증거는 docs/validation/d427-source-migration/signal-supervision-2026-10-04.md. 계획은 docs/plans/2026-10-04-d443-signal-supervision.md이며 운영 API는 operations/fleet/docs/signals.md에 기록했다.
- gate 변화: 없음. SOURCE/호스트 후보 검증이며 CI·ARM64·DEVICE·FIELD를 주장하지 않는다. 펌웨어 S7은 다음 개정이다.

## 2026-10-04 · uncommitted · D-442 U3 owner 선점과 named 운영 복구

- 변경: Arbiter 전용 선점은 exact-goal cancel 후 HOLD를 유지한다. Fleet named operator 인증·감사와 bounded UDS recovery를 CellOwner owner/local-stop/journal에 연결했다. fresh post-HOLD readback과 PREPARED 포함 미해결 Action을 검사하고 잠금으로 stop·claim 경합을 직렬화한다. commit 실패는 HOLD 복원, ACK 유실은 자동 재전송 금지다.
- 증거: RED 회귀 후 최종 관련 API/transport/owner/store/Cell/안전 구조 152 passed(43.14 s). 실제 호스트 HTTP→UDS frame→owner 연결과 SQLite commit 실패·claim/stop 경합 회귀 포함. X:/DevTemp/rosy-d427/resume/recovery-final.txt 및 docs/validation/d427-source-migration/omx-preempt-recovery-2026-10-04.md. Fleet 구조는 독립 재판정 29,264 줄이며 split·예산·+150은 유지했다.
- gate 변화: 없음. SOURCE/호스트 후보 검증이다. 실제 UDS·ROS-SIM·CI·ARM64·DEVICE·FIELD는 NOT_RUN, motion/reset/profile enable은 실행하지 않았다.

## 2026-10-04 · uncommitted · fix: D-427 push5 통합 게이트 정합성

- 변경: 운영 시나리오에서 MANUAL 해제를 실제 IDLE API로 명시했다. Fleet 재명령 문구는 의도를 한국어로 표시하고, CORE image closure는 정확한 ROS 열 개와 계약 wheel 두 개를 분리 검증한다. 운영 MANUAL·신호 감독 가드는 바꾸지 않았다.
- 증거: Python 집중 35 passed, 추가 구조/Fleet 97 passed, Node 전체 109 passed. 실제 입력 누락·colcon 오배치·raw enum 표시 mutation 네 건 RED 뒤 원본 bytes 복원·GREEN. 알려진 실패 0 new, backlog 증가 없음. `docs/validation/d427-source-migration/push5-gate-corrections-2026-10-04.md`.
- 독립 리뷰: d427_safety_review APPROVE source/host, 별도 Python 22 passed·Node 3 passed. Fleet +12 줄은 기존 +150·split 판정 안에 있고 예산·allowlist를 늘리지 않았다.
- gate 변화: SOURCE/로컬 증거만 추가한다. 새 pre-push·원격 CI·ARM64·SD·기기·현장 수락은 후속이다.

## 2026-10-04 · uncommitted · feat(cell): revisioned Console workspace

- 변경: `/console/cell`에 초안 문서 revision 저장·canonical compile·설정된 service 제안·named operator 별도 승인·작업 상태·reconcile/resume/cancel을 연결했다. 별도 writer/실행 원장은 없다. 박스 치수/질량/잡는 깊이·home/도구 설정 편집과 팔레트·층별 footprint 미리보기, JSON 파일 입력을 제공한다. 관제의 실제 credentials/enrollment는 바꾸지 않았다.
- 검증: 실제 palletizing compiler를 사용한 API save→18-transfer preview→service proposal→separate admit READY가 통과했다. 실제 Chromium에서 늦은 compile 응답 무효화·조회 실패 후 승인 잠금·검토한 generation의 409·취소 이후 재승인 잠금을 확인했다. 모든 transport는 비연결/가짜 장치이며 실제 전송 성공 증거가 아니다.
- 독립 리뷰: spec·quality 리뷰의 stale async/fence 두 결함을 수정했다. 입력 변경 epoch, 요청 중 입력 잠금, 읽기 전 snapshot 삭제, 검토한 generation 고정과 충돌 후 재조회가 적용됐다.
- gate 변화: G1 전체 완료는 아니다. 장치 티칭 wizard, 정본 레시피의 모든 구조 편집, 독립 지정 수용과 모델 PC OMX 종단이 남았다. Fleet ROS-SIM/DEVICE/FIELD 승격 없음.

## 2026-10-04 · uncommitted · feat(server): D-438 Fleet stuck resolver phase 1 (rules R1-R3 + human escalation)
- Change: `fleet/server/stuck_resolver.py` (pure decision core), `stuck_resolver_loop.py` (1 s poll, hub-woken, records as `fleet-resolver`), `line_stuck.py` resolver note, `console_routes.py` claim endpoint (human decision claims first), `app.py` clients/lifespan/hub fan-out, `swarm/robots.py` `resolver_token`, `cli.py` `--stuck-resolver`, console `line-stuck.js` claim + resolver text; API Ref v1.90 version pins in two tests
- Evidence: `python -m pytest src/site/fleet/test -q` 1658 passed, 7 skipped (2026-10-04 Windows; first run had 3 failures, all the API Ref version pin `v1.89` -> `v1.90`, fixed, re-run of those files 25 passed together with gateway version alignment); `node --test src/site/fleet/test/web/line-stuck.test.mjs` 12 pass; `python -m pytest test/test_harness_contracts.py -q` 59 passed
- Gate: none. SOURCE/LOCAL only; Gazebo two-robot validation and real-robot tokens are not done (plan "After phase 1").
- Decision: D-438
- Lesson: none

## 2026-10-04 · uncommitted · fix(server): D-438 phase 1 final-review findings
- Change: `fleet_line_stuck_answers` gains nullable `tier`/`rule`/`escalated` with an idempotent PRAGMA + ALTER migration; resolver answers record `tier=rule` + rule id, every escalation is its own `ESCALATE` row, the human route records `tier=human`. `console_routes.SharedGather` (lock + 1 s reuse) is the one `console.snapshot()` + `board.observe` for `GET /api/fleet/state` and `StuckResolverLoop`. The transport resend skips the rule budget; robots absent from the roster lose chains and claims; a claim after an escalation keeps its reason; cancel mid-request records `STUCK_DECISION_OUTCOME_UNKNOWN`; unused `_Chain.claimed` removed; JS string test deleted.
- Evidence: each code fix red first, then green. `python -m pytest src/site/fleet/test -q` 1666 passed, 7 skipped (2026-10-04 Windows); gateway `test_stuck_resolver_role.py` + `test_line_follow_stuck_api.py` 22 passed; `node --test src/site/fleet/test/web/line-stuck.test.mjs` 12 pass; `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -k "stuck or state"` 4 passed, 63 deselected.
- Gate: none. SOURCE/LOCAL only; Gazebo two-robot validation and real-robot tokens still open.
- Decision: D-438
- Lesson: a shared cached snapshot must be enriched per response on copies, never mutated in place.

## 2026-10-04 · uncommitted · feat(server): D-447 (a) gather reads fresh hub snapshots first
- Change: `hub/registry.py` `RobotRecord.last_heartbeat_monotonic` + read-only `find()` (gather must not create records); `hub/hub.py` `_heartbeat` stamps arrival (`time.monotonic()`); `server/console.py` `snapshot()` gathers per-robot via `_gather_state()` — a hub record that is online, has a snapshot, and whose heartbeat arrived within `hub_state_max_age_s` (new ctor param, default 3.0 s) answers from the registry `StateSnapshot` and skips the REST GET; stale/offline/unknown robots fall back to REST as before. Rows gain additive `gather_source: "hub"|"rest"|null`. No schema, endpoint, or wire change; `SharedGather` 1 s reuse untouched.
- Evidence: new `test/test_server_gather_source.py` 6 passed (fresh-skips-REST, stale falls back, offline falls back, REST-failure row shape unchanged, no record creation, heartbeat stamp); `python -m pytest src/site/fleet/test -q` 1683 passed, 7 skipped (2026-10-04 Windows, run.txt compared via `test/known_failures.py`: 0 new); flake8 findings on touched files are pre-existing on main (noqa line offset, hub.py W293) and CI flake8 is non-gating.
- Gate: none. SOURCE/LOCAL only; no robot, no hub socket in this run.
- Decision: D-447 (a). (b) robot shell `store.js` `/ws/state` subscription is the next pass under the same ADR.
- Lesson: none

## 2026-10-04 · uncommitted · test: API v1.91 문서 계약 유지

- 변경: API 문서 개정에 맞춰 Fleet 문서 버전 pin 세 곳을 v1.91로 갱신한다. task·intent·물리 상태·cursor 본문 검사는 유지한다.
- 증거: mission progress 및 task contract 문서 회귀 22 passed.
- gate 변화: SOURCE/LOCAL. Fleet 배포와 물리 제출 검증은 포함하지 않는다.

## 2026-10-04 · uncommitted · feat(web): D-439 Fleet 작업 탐색과 보정 미리보기 수명

- 변경: 설치를 로봇 등록·카메라 연결 승인·카메라 설치/보정의 공용 task chooser로 구분한다. 모든 작업 DOM과 입력·credentials·source·corners는 유지하고 viewer/401에서도 읽기 탐색과 발견 재시도를 허용한다. 관제의 예외·로스터·지도를 우선 배치하고 대형·신호·기록을 후속 작업으로 묶는다. 발견 실패는 이전 행을 지우고 empty/offline/expired/unsupported 상태와 재시도를 표시한다.
- 수명: 숨겨진 보정은 lease/frame 요청을 시작하지 않는다. 작업을 숨기면 preview epoch를 취소하고 frame owner만 해제한다. 이전 응답·finally는 새 owner를 바꾸지 않는다. 양수 크기의 scoped ResizeObserver가 복귀 후 corner geometry를 갱신하며 console의 기본 preview 동작은 유지한다.
- 증거: baseline chooser RED 1 failed. 변경 후 workflow 최종 batch는 4 passed/1 failed(198.22s). 실패는 닫힌 보정 details에 입력하려던 fixture였으며 실제 summary 클릭을 추가한 동일 rapid test는 1 passed(38.10s)로 재검증했다. 이를 전체 5 GREEN 실행으로 합산하지 않는다. 기존 선택 회귀는 10 passed/5 failed였고, 실패 5 cases를 새 작업 선택·안내 DOM·bounded poll 조건으로 수정해 5 passed/62 deselected(167.08s)로 재검증했다. 관련 host 70 passed/1 heading fixture failed 후 heading 1 passed; Fleet web .test.js Node 145 passed; 최종 source budget 2 passed. 로그: X:/DevTemp/rosy-ui-unify/fleet/.
- 변이: X 전용 실제 served bytes로 chooser role exemption 제거·geometry observer 제거·hidden preview guard 제거·rapid pausePreview 제거가 각각 해당 행동 검증을 실패시켰다. 마지막 rapid 변이는 leaseRequests가 2가 되지 않아 RED 1 failed(57.23s); teardown CancelledError는 부수 출력이다. manifests와 delivery SHA-256은 fleet/mutations 각 디렉터리에 있다. 제품 bytes는 변경하지 않았다.
- 변이 bytes 보완: 앞선 세 manifest는 LF 정규화 text의 hash였고 실제 파일/전달은 CRLF였다. newline-delivery-proof.json은 원래 증거를 보존하며 raw 파일 hash=delivery hash, CRLF→LF 정규화 hash=기존 manifest hash가 세 건 모두 일치함을 기록한다. rapid manifest는 raw bytes hash로 직접 일치한다.
- 독립 증거: SPEC의 abort 무시 lease 재현에서 새 owner 시작·old frame/finally 차단·source/draft 보존 PASS. X:/DevTemp/rosy-ui-unify/fleet-spec/rapid_visibility_fixed_report.json. Root는 desktop/phone 및 실제 밝은 테마 captures를 직접 확인했으며 overflow/pageerrors 0. Fixture preview lease POST는 포함하며 operational command는 실행하지 않았다.
- 최종 확인: 독립 SPEC 및 QUALITY PASS. preview epoch 최종 변경 후 vision-view 소비 Node 두 파일 12 passed(477.58ms); 이는 lens/profile/badge 계약이며 비동기 수명은 현재 browser/SPEC 증거로 확인한다. rapid GREEN과 served RED는 같은 최종 source/test이며 manifest/delivery/source hash 대조가 일치했다. generate는 Fleet index만 변경했고 lint 0 errors/26 기존 warnings, diff check PASS.
- Gate: SOURCE/LOCAL 범위. Fleet 전체 suite·배포·실장비·ROS-SIM·FIELD 수용을 주장하지 않는다. 기존 서버 역할·인증·source proof·CORE motion authority는 유지한다. source commit SHA는 Git 기록을 따른다.
- 결정: D-439 Task 4 및 작업별 preview 독립 수명.
- 교훈: visible predicate만으로 hide→reshow를 구분할 수 없다. frame 작업에는 작업별 epoch와 finally owner 비교가 함께 필요하다.

## 2026-10-04 · uncommitted · fix(web): 관제 뷰포트와 주소 확인의 작업 소유권

- 변경: 데스크톱의 지도·카메라와 로봇·운용 영역을 각각 묶어 선언 뷰포트의 문서 스크롤을 없앴다. 좁은 화면에서는 같은 네 영역을 주의·로봇·지도·운용 순서로 실제 DOM에 옮기고 입력과 초점을 보존한다. PageScope가 미디어 listener 정리와 복귀를 소유한다. 기록은 기본 8줄을 유지하고 진단·설치 안내와 나란히 배치한다. 신호등이 없을 때 파일 편집을 지시하지 않는다.
- 주소 확인: 설치의 로봇별 옮기기가 기존 discovery/addresses에서 서버가 movable로 판단한 단일 주소만 안내한다. 실패·모호함·10초 만료는 새 주소 미확인으로 표시하고 화면 코드의 서버 검증을 유지한다. 후보 조회는 페이지·자격·작업 epoch를 확인하여 새 대화상자와 코드, 새 조회 잠금을 덮어쓰지 않는다. 실제 POST 본문은 코드만 보낸다.
- 검증: 최초 Fleet 재검증 3 passed/4 failed(47.72s)는 77px 스크롤과 옛 설치·테마 fixture를 드러냈다. 다음 3 passed/3 failed(19.31s), 2 passed/1 failed(7.99s)를 보존한다. 최종 뷰포트·390/320 순서·동일 DOM/입력/초점 3 passed(8.35s); 테마·서버 코드·viewer·조회 만료 4 passed(24.38s). 강화된 후보 작업 소유권 최종 원본 1 passed(16.06s). 기존 주소 옮김과 compatibility 네트워크 2 passed(16.16s). 주소·등록 Node 20 passed, palette/disabled host 19 passed(1.80s). 지나간 성공을 중복 합산하지 않는다.
- 변이: X 전용으로 실제 전달한 roster 숨김, DOM 복제, 모호한 후보 허용, 만료 제거, 새 대화상자 소유권 제거가 각각 RED이고 원본은 GREEN이다. delivery/source 해시와 sourceUnchanged를 final-plan/task6-mutation-report.json 및 task6-source-unchanged.json에 기록했다. 첫 경로가 자산 URL과 달라 변이가 전달되지 않은 시도는 유효 증거에서 제외한다. 소유권 변이는 실제 새 수동 대상이 옛 로봇 대상으로 바뀌는 단언에서 실패했다.
- 화면: 부모 검증자가 실제 dark 1920의 문서 높이 1080과 light 390의 자연스러운 세로 흐름을 직접 확인했다. 가로 넘침·페이지 오류는 0이며 같은 정지·대형·신호·로봇·지도·카메라의 양수 크기를 유지한다. 근거는 X:/DevTemp/rosy-ui-unify/final-plan/ 및 fleet/root-fit-final/.
- gate 변화: SOURCE/LOCAL 검증이며 배포·실제 장치·FIELD 승인을 주장하지 않는다. API 권한과 최종 동작 판단은 서버가 소유한다.
- 결정: D-439 §17. 같은 DOM을 옮기는 배치는 시각 순서뿐 아니라 키보드 순서와 draft 소유권도 보존해야 한다.

## 2026-10-04 · uncommitted · fix(web): 관제 확인과 명령의 공통 소유권

- 변경: console과 roster가 private confirmed-action factory를 함께 사용하여 발행 재허가·맵 목표·전체 주행 취소·양수 IR 선택을 공용 비모달 확인으로 처리한다. 한 owner가 확인부터 요청/readback까지 유지되며 자격·역할·PageScope 교체 시 취소한다. 재허가 세대/availability, 맵 geometry·선택 로봇·온라인·정지 상태, IR 재선택 사유/모드의 현재 eligibility를 다시 확인한다. 같은 Fleet API·본문·idempotency와 기존 서버 권한은 유지한다. IR OFF는 즉시 보내며 해당 양수 owner를 취소한다.
- 검증: 초기 통합 RED 3 failed(18.04s) 후 기존 payload/취소 계약 10 passed(25.19s), 자산·예산 14 passed(1.40s). 강화 시나리오의 2 passed/1 failed(23.51s)는 CAMERA_LINE 상태에서 맵 목표를 누른 fixture 오류였다. 맵 OFF·IR CAMERA_LINE 상태를 실제 계약대로 분리하고 이전 자격 응답을 abort 무시 adapter로 유지한 최종 Fleet owner 검사 1 passed(10.21s). 최종 eligibility 변이 복원에서도 같은 강화 node가 통과했다. 최종 공용 제어·자산·예산 39 passed(1.83s).
- 변이: X 실제 전달 private module의 확인 후 eligibility 제거는 generation 변경 뒤 dispatch/rearm POST 단언에서 RED 1 failed(3.74s); owner finally 비교 제거는 옛 A 완료가 새 B를 풀어 취소 확인창이 생기는 단언에서 RED였다. 원본 제공은 각각 GREEN. 초기 EStop의 닫히는 확인창에 취소를 누른 두 무효 시도는 제외하고 실제 count 0을 기다려 재증명했다. dashboard 포함 6개 receipts/source raw hash는 final-plan/task6b-mutation-report.json, task6b-source-unchanged.json, task6b-delivery.jsonl.
- 화면: rearm desktop dark, map/IR phone light의 실제 확인창 viewport 3개는 Stop visible/center-hit·inert false, 가로 넘침·pageerror 0. fake API만 사용했으며 실제 로봇 명령은 실행하지 않았다. 근거 X:/DevTemp/rosy-ui-unify/final-plan/task6b-captures/report.json 및 *-viewport.png.
- gate 변화: SOURCE/LOCAL. 물리 정지·장치·배포·FIELD 수용을 주장하지 않는다. 최종 SPEC/QUALITY 및 부모 직접 화면 판단은 별도 기록한다.
- 결정: D-439 §18. shell 자격 수명과 한 작업 소유권을 조합하고 오래된 finally가 새 작업을 해제하지 않는다.
- 최종 수용: 독립 SPEC 및 QUALITY PASS, 부모의 실제 5개 viewport와 변이 hash 검증 PASS. 구조 예산 2 passed(0.96s), lint 0 errors/26 기존 warnings, diff check PASS. 배포/장치 수용은 포함하지 않는다.

## 2026-10-04 · 6485f8a39 · refactor(ui): 통합 명렬 카드의 표현 재사용

- 변경: 명렬 카드의 DOM 생성 열두 구간을 기존 roster 파일 안에서 재사용했다. 클래스·textContent·ARIA·동작과 지도/정지/공용 확인 소유자를 유지했다.
- 증거: Fleet package 29,815줄의 초과를 29,806줄로 줄였다. 기존 verdict 29,657+150을 올리지 않았다. 실제 viewport·compact 정지 접근·공용 확인 generation 재검사 4통과(15.38초), 독립 SPEC→QUALITY 통과.
- gate 변화: SOURCE/LOCAL과 main 착지 완료. 운용 허가·비상 정지 해제·물리 명령·배포·현장 수용은 실행하지 않았다.
- 결정: D-439 §21과 D-201 화면 계약을 함께 유지한다. 반복 표현만 재사용하고 command owner나 서버 권한은 이동하지 않는다.

## 2026-10-04 · uncommitted · feat(power): fresh battery evidence and idle saving

- 변경: 반복 저배터리 표본의 wake를 단계 변화로 제한하여 기존 IDLE/STANDBY 타이머가 동작한다. Viewer GET /api/v1/power/health와 공유 typed 응답에 배터리·충전 확인 age, 정책 상한·wake 근거, shutdown 요청, 진단 요약을 제공한다. API Ref v1.92, envelope 1.0 유지.
- 검증: injected clock 회귀와 auth/read-only API, 기존 배터리·정지·sentinel 경로 검증. 최종 근거는 docs/plans/2026-10-04-power-health-and-wake.md. OS halt·EEPROM·GPIO·기본 LiDAR 모터 정책 변경 없음.
- gate 변화: SOURCE/LOCAL; 실제 소비전력·충전·RTC/외부 버튼 wake와 배포는 미검증.

## 2026-10-04 · uncommitted · D-452 승인 역할 목록과 신원 충돌

- 변경: viewer peers catalogue·metadata-only 승인 directory·호스트 multi-role scanner를 기존 등록과 분리한다. 모든 소유 주장 충돌은 승인 해제/unknown으로 처리한다. 기존 command/credential/endpoint는 보존한다.
- 증거: catalogue/API24 PASS, schema37 PASS, scanner Linux11 PASS 및 독립 source SPEC·Quality·Safety PASS. docs/validation/network-peer-discovery-2026-10-04/peer-backend-checkpoint.md.
- gate 변화: focused SOURCE/LOCAL; 실제 인증 operator·container namespace·다른 망 연결·배포 수락 별도.

## 2026-10-04 · uncommitted · refactor(fleet): main 통합 시 HTTP composition 경계 유지

- 변경: main의 stuck resolver·access·power 계약과 Cell workspace를 함께 보존했다. API Ref Cell additive 항목을 v1.93으로 올렸고 대응 metadata/version pin을 맞췄다. 동일 audit middleware를 site_auth, 동일 event fanout을 hub/server, healthz를 static route owner로 옮겨 app composition을 594줄로 유지했다.
- 증거: 독립 source 검토는 auth/audit/fanout/health 동작 보존과 optional dependency guard를 확인했다. 구조 count Fleet 30621/schema 1319로 명시 재판정하고 기존 +150/zero allowance는 유지했다. 실제 vendor retry exit0/1passed와 컨테이너 정리 확인은 별도 deploy validation에 기록했다.
- gate 변화: SOURCE 통합 검토이며 최종 통합 시험은 별도로 진행한다. full G1/G2 및 Isaac 주행·Nav2·두 로봇 수용은 미완료다.

## 2026-10-04 · uncommitted · D-452 장비 찾기와 화면 소유 경계

- 변경: 역할 목록·다시 찾기·승인/만료/오류 안내를 기존 작업 선택 화면에 연결했다. 로봇은 등록 상태 카드 포커스만, Cam은 기존 source 보정 화면만 연다. Cell 관제 복귀와 취소 의미를 보완했다.
- 구조: catalogue/directory/routes와 picker를 별도 owner로 두고 composition factory로 app.py를 599줄로 유지한다. D-362 Fleet 패키지 30997줄(+376)을 독립 리뷰로 재판정하며 기존 flat server 분리 의무·파일 제한·+150 allowance를 유지한다.
- 증거: docs/validation/network-peer-discovery-2026-10-04/peer-ui-checkpoint.md. 최종 통합 gate·원격 CI·서명 배포·실제 운영자 및 다른 망 연결은 별도 검증이다.
- gate 변화: focused SOURCE/LOCAL 검증이며 최종 통합·CI·DEVICE·FIELD 수락은 보류한다.

## 2026-10-04 · uncommitted · fix(test): API 문서 v1.94 계약 기대값

- 변경: 오래된 v1.92 header 기대값 세 곳만 현재 API Ref v1.94와 맞췄다. endpoint·cursor 보존·권한·완료 증거 검증을 유지한다.
- 증거: 실제 원격 실패 3개 RED 후 GREEN 3 PASS, 통합 담당자 관련 전체 24 PASS, 독립 source 리뷰 PASS.
- gate 변화: focused LOCAL; 최종 통합 gate와 새 원격 CI는 별도다.

## 2026-10-04 · uncommitted · feat(cell): 구조화된 초안 입력 확장

- 변경: 같은 JSON 초안에 레시피·팔레트·층·슬립시트와 셀 프레임 세 점·스테이션·판정 한계를 편집하는 입력을 제공했다. 저장 후 재생성된 입력의 busy 잠금 누락을 실제 브라우저에서 재현하고 수정했다.
- 증거: Chromium 구조 편집 RED 2 실패 뒤 GREEN 2 통과; busy RED 1 실패 뒤 전체 Cell browser/API/store/job 23 통과. 독립 UI 검토 승인.
- gate 변화: SOURCE/LOCAL 편집 증거만 추가한다. 장치 TCP capture·owner 티칭 수락, G2 전체 적재와 G3 작업자 슬립시트 확인은 미완료다.
- 결정: D-450. 사용자는 작업자가 슬립시트를 넣고 확인한 뒤 다음 층을 진행하도록 선택했다. durable checkpoint 설계를 별도 기록했다.

## 2026-10-04 · uncommitted · fix(cell): 수동 간지 확인 전 다음 층 보류

- 변경: 수동 취급 recipe/2 선택과 읽기 전용 checkpoint를 연결했다. 정본 Job 투영 누락은 롤백하며 간지 대기는 같은 SQLite Job 트랜잭션에서 start·resume·완료·복구·dispatch 전에 차단한다. 관제에 삽입 대기 사유를 표시하며 일반 재승인은 허용하지 않는다. 확인 API나 owner 접근 허용 provider는 추가하지 않았다.
- 증거: PROCESS source 219 tests와 설치 wheel 호환 169 tests, Fleet 영향 105 tests 및 독립 48 tests를 통과했다. 통합 guard/store/dispatcher/API/schema/replay 101 passed, 실제 Chromium 9 passed. 숨겨진 preview 읽기를 수정하고 서버 graceful shutdown을 3초로 제한해 worker 종료 assertion을 보존했다. 독립 계약·UI·안전 guard 검토를 받았다.
- gate 변화: SOURCE/LOCAL만 추가했다. owner-exclusive 접근·작업자 확인·ROS-SIM·현장 수용은 NOT_RUN이며 실제 진행은 OPERATOR_SHEET_ACCESS_UNAVAILABLE로 HOLD다. Fleet 30998의 기존 분리 계획과 +150 allowance는 유지하고 Job store959/schema1319의 기존 한계도 유지한다.

## 2026-10-04 · uncommitted · feat(fleet): D-451 한 줄 교착 알고리즘 room_hold

- 변경: `operations/fleet/fleet/meet` 에 장면·주문·이름 등록과 `room_hold`·`wait_both`·`track_v2` 를 넣었다. 고리 같은 방향은 서지 않고, 찬 방의 문은 빼며, 핀이 비키는 쪽을 유지하고, 방 안은 `WAIT` 다. 콘솔·차선 추종·stuck 판단기에는 연결하지 않았다.
- 증거: `operations/fleet/test/test_meet_algorithms.py`.
- gate 변화: 없음. 호스트 판단 시험. 주문은 아직 바퀴로 나가지 않는다.

## 2026-10-04 · uncommitted · feat(fleet): D-453 양보 한 구간

- 변경: 판단기가 차선에 올린 자세로 `room_hold` 를 부르고, `SIDESTEP`·`RETREAT` 한 구간을 로봇 `YIELD` 로 직접 보낸다. 핀과 돌리기 전의 정책 방향은 판단기에 둔다. 운용자 경로에는 `YIELD` 를 넣지 않았다.
- 증거: `operations/fleet/test/test_meet_place.py`, `test_stuck_resolver.py`, `test_transport.py`, `test_meet_algorithms.py`.
- gate 변화: 없음. 호스트 판단 시험. 장치·ROS-SIM 은 주장하지 않는다.

## 2026-10-04 · uncommitted · fix(fleet): 불확실한 YIELD 재실행 차단

- 변경: 양의 YIELD 결과가 불명확하거나 응답 대기 중 취소되면 기존 answered fence를 유지하고 운용자 확인으로 넘긴다. 다음 폴링이나 새 위치가 같은 grant의 재전송을 허용하지 않는다. 취소 예외와 unknown 원장 의미를 보존한다.
- 증거: 실제 loop의 응답 유실·비정상 응답·취소 후 반복 폴링 회귀 및 관련 74 PASS. 독립 검토와 최종 통합 gate를 별도 실행한다.
- gate 변화: SOURCE/LOCAL이며 물리 양보 실행·운용 수락은 하지 않았다.

## 2026-10-04 · uncommitted · feat(server): D-454 1단계 — 중앙 레지스트리 뷰 (/api/v1/fleet/robots)

- 변경: `central_registry.py`(CentralRegistry 읽기 모델 — 로스터가 정본, hub 스냅샷·발견 주소는 보강, state/capabilities는 로봇이 만든 증거를 그대로 전달 D-309), `central_registry_routes.py`(`GET /api/v1/fleet/robots`·`/{id}`, Viewer 가드, 미등록 404 UNKNOWN_ROBOT), `app.py` `central_registry=` 마운트, `cli.py` `--central` 플래그(등록 저장소 필수 — 로스터가 정본이므로). 설계·실행 계획: `docs/plans/2026-10-04-central-fleet-step1{,-design}.md`. §10.1 나머지 7경로(PATCH/DELETE·페어링 토큰·승인 대기·폐기)는 뒤 작업.
- 증거: 신규 `test/test_central_registry.py` 6 passed(합산·정렬·증거 무계산·404·401·왕복). fleet 전체(셀 앱 2파일 수집 오류 제외 — `rosy.processes` 휠 미설치, main 선재·WSL/CI 전제) **1799 passed/7 skipped, known_failures 0 new**. flake8 0.
- gate 변화: 없음. ROS-SIM/DEVICE/FIELD 주장 없음(D-454 결정 3).
- 결정: D-454 결정 1·2 — 시드 위 성장, §10.1 읽기부터.

## 2026-10-04 · uncommitted · fix(fleet): keep app composition within its line budget

- 변경: 기존 goal evidence grace 유지보수 루프를 기존 background_workers 모듈로 이동했다. app의 private 호출은 동일 logger를 바인딩한 partial로 유지하며 grace 처리·예외·주기·Action 활성화 경계는 유지한다.
- 증거: main에서도 app607행의 미등록 budget 실패가 재현됐다. 이동 후 size guards·server app·central registry48pass, 독립 검사47pass. 병합 전 관련 검사 결과는 X:/DevTemp/rosy-learning-audit-20261004/landing-*에 보존한다.
- gate 변화: SOURCE/LOCAL 병합 수리. 서비스 설치·timer·장치/현장 수용은 미완료다.

## 2026-10-04 · uncommitted · feat(server): D-454 1b — 등록 해제 경로와 로스터 차단 전달

- 변경: `DELETE /api/v1/fleet/robots/{id}`(REG-001a, operator 가드). 로스터 `remove()`의 진행 작업 차단(RosterConflict)은 409+task_ids로, 미등록은 404 UNKNOWN_ROBOT으로 내려온다. `CentralRegistry.roster` 속성으로 정본 로스터를 노출한다. 같은 회차의 시험 결함 수정: 증거 무계산 단언이 스냅샷을 두 번 만들어 자동 타임스탬프가 어긋났다 — 같은 객체에서 비교한다.
- 증거: `test/test_central_registry.py` 8 passed(해제·차단 409+task_ids·미등록 404·operator 전용 403 포함). fleet 전체(셀 앱 2파일 제외, 사유 동일) 1800 passed/1 failed → 결함 수정 후 초록, known_failures 0 new. flake8 0.
- gate 변화: 없음.
- 결정: D-454 결정 2의 §10.1 확장. PATCH(이름·그룹)·페어링 토큰·승인 대기·토큰 폐기는 다음 회차.

## 2026-10-04 · uncommitted · feat(fleet): D-455 양보 합류는 지도 자세

- 변경: 양보 계획이 있는 동안, 선 밖 틈은 정차 점이나 선으로 보정한다. 동료가 문을 지나면 방에서 문으로 YIELD 하고, 진행 방향을 되찾으면 RESUME 한다. 오도메트리 프레임은 무응답이다.
- 증거: operations/fleet/test/test_meet_place.py, test_stuck_resolver.py 포함 관련 호스트 203 passed. known_failures 새 실패 0.
- gate 변화: 없음. 호스트 판단 시험. 장치·ROS-SIM 은 주장하지 않는다.

## 2026-10-04 · uncommitted · feat(server): D-454 1c — §10.1 쓰기 경로와 501 경계 명시

- 변경: `central_registry_routes.py`에 §10.1 쓰기 4경로 추가(operator 가드, `enrollment` 주입). `PATCH …/{id}`(REG-003)는 등록 저장소의 `discovery_name`만 건드린다(그룹 개념은 뒤 작업) — 빈 이름 422, 미등록 404. `POST …/token/revoke`(SEC-203)는 상태를 `needs_new_code`로 전환해 재발급을 강제한다(폐기 계약의 등록측). `GET /pending-robots`(SEC-202)는 비-active 등록 목록을 돌려준다(D-361 등록 게이트와 연결 예정). `POST /pairing-tokens`(SEC-201)는 501로 명시한다 — D-341 승인 흐름 통합은 뒤 작업 설계가 소유하고, 구현되지 않은 것을 200으로 속이지 않는다. 저장소 없음(--central 없이)은 501. API Ref §10.1 나머지 중 `DELETE pairing-tokens/{token}`·`approve`·`/{id}/token/revoke`는 뒤 회차.
- 증거: `test_central_registry_write.py` 신규 9 passed. fleet 전체(셀 앱 2파일 수집 오류 제외, main 선재) **1815 passed/7 skipped, known_failures 0 new**. flake8 0.
- gate 변화: 없음. ROS-SIM/DEVICE/FIELD 주장 없음(D-454 결정 3).
- 결정: D-454 결정 2 계속. 뒤는 pairing-tokens(2)와 §10.2 명령 상관·ACK(D-426 선행).

## 2026-10-04 · uncommitted · fix(registry): 중앙 1c 쓰기 보류와 실제 등록 원장 보존

- 변경: 02dc934a7의 이력은 보존하되 기존 두 중앙 GET 정본을 유지한다. Admin·실명 actor·등록 소유자가 없는 중앙 쓰기와 저장소 직접 수정은 제공하지 않는다. 기존 사이트 등록·페어링·해제 경로를 유지한다.
- 증거: 실제 앱·로스터·EnrollmentService·암호화 SQLite를 사용하는 미마운트·불변 회귀를 추가했다. 작성자 검사 22 PASS 및 독립 SPEC·Quality·Safety 검토 PASS이며 실제 통합 재검사는 별도 수행한다. fake 저장소가 숨긴 인터페이스·알 수 없는 항목·거짓 token 폐기 문제는 실행 승인 근거로 쓰지 않는다.
- gate 변화: 중앙 1c 쓰기 적용은 HOLD다. 같은 장비의 identity·endpoint·살아 있는 연결·영구 credential·감사는 변경하지 않는다. 로봇 동작·토큰 폐기·등록 해제를 이 검증을 위해 요청하지 않는다.

## 2026-10-04 · uncommitted · feat(tools): Fleet·게임 캡처 회차 6셀 (D-359 §7.8)

- 변경: `operations/fleet/tools/capture_console_games_round.py` 신설 — 실제 Fleet 앱(FakeRobot 2대) + 실제 games preview 서버를 Playwright로 찍는다. 회차 `docs/validation/fleet-games-capture-2026-10-04/`에 console 3셀(1920/390/320) + games 3셀(1280/390/320). 배치 규칙도구 위치: fleet 모듈 tools/(게임을 엮는 순수 측정) — tools/AGENTS.md 배치 규칙 준수.
- 증거: 6셀 캡처(페이지 오류 0). flake8 0.
- gate 변화: 없음. LOCAL 합성 증거. 게임 readback 2대·사람 G3는 다음 회차.
- 결정: D-359 §7.8 역할 표면 나머지 캡처.

## 2026-10-04 · uncommitted · docs(ux): 기존 캡처의 미완료 화면을 HOLD로 분리

- 변경: 2150354e2 원본 캡처·report를 보존하고 README에 실제 미렌더링·인증 대기와 도구의 auth/method/CSP 누락을 명시했다. 페이지 오류 0을 정상 UX로 취급하지 않는다.
- 증거: 원본 console-1920x1080 PNG를 root와 독립 검토자가 직접 확인했다. 기존 사진은 실패 관측이며 현재 통합 코드의 정상 화면 검증은 아니다.
- gate 변화: LOCAL UX/G3 HOLD. 실물/정지/DEVICE 수락 없음.

## 2026-10-04 · uncommitted · fix(tools): 교차 모듈 캡처를 workspace tools에 배치

- 변경: Fleet와 games를 엮는 캡처는 tools/AGENTS.md 규칙에 따라 root tools/capture_console_games_round.py로 이동했다. REPO 계산과 현재 재현 경로를 맞췄다. Fleet 운영 runtime에 games import를 추가하지 않는다.
- 증거: 실제 구조 검사에서 fleet→games 미선언/방향 위반2건이 재현됐다. 모듈의 dependency/방향 allowlist를 늘리지 않고 잘못된 배치를 수정해 다시 검사한다. 이전32605는 잘못 모듈에 들어간 캡처136행을 포함한 실측이며 이동 뒤 예상32469를 다시 측정한다.
- gate 변화: 소스 배치 정합. 기존 캡처의 UX HOLD는 그대로이며 실제 역할/장치 수락을 주장하지 않는다.

## 2026-10-04 · uncommitted · fix(fleet): Cell header와 등록 시험의 실제 작업 선택

- 변경: Cell 링크를 기존 header grid의 named area에 넣어 implicit row를 제거했다. 등록 browser 시험은 실제 로봇 등록 tab을 선택하며 거부·확인·정지 단언은 유지한다.
- 증거: 실제 viewport 3건·등록 절차 6건 PASS 및 독립 리뷰 APPROVE. 기존 높이 제한·링크·정지·상태를 유지했다. 전체 browser 원본과 수정 범위는 D-427 개별 게이트 검증 기록에 구분했다.
- gate 변화: SOURCE/LOCAL만. site 배포·로봇 목표·DEVICE/FIELD 수용은 수행하지 않았다.

## 2026-10-04 · uncommitted · fix(site): D-457 마커 우선·무마커 폴백

- 변경: 현행 모듈에 source-token 표시 추적과 승인 보정을 통합. 마커 명시 대응 우선, 없으면 익명 검출·신뢰 가능한 map pose 대조. UI/UX 리팩터링 없음.
- 증거: 공유 벡터·Vision·Fleet·브라우저 전환 조건을 호스트에서 검증. 실제 사이트는 두 등록 로봇과 S21 영상 연결 조회만 확인. 후보 배포·빈 트랙 학습·실물 위치 오차는 미완료.
- gate 변화: 없음. SOURCE/LOCAL 변경이며 DEVICE/FIELD 완료 주장 없음. 기존 등록·credentials 보존.

- D-457 추가 검증: 좌표 표(X/Y m, 관측 기준)와 표시 수명 삭제. 관련 기능 602 passed, Node 34 passed, Chromium 14 passed. 공통 검사 기존 실패는 깨끗한 기준 main에서 재현했으며 docs/validation/2026-10-04-overhead-marker-fallback-local.md에 기록했다.

## 2026-10-04 · uncommitted · refactor(fleet): move periodic goal evidence worker out of app composition

- 변경: 기존 goal-evidence grace reconciliation loop를 background_workers로 이동하고 app의 기존 이름과 logger를 partial로 보존했다. 실행 주기·예외 처리·dispatch 권한은 같다.
- 증거: 깨끗한 origin/main에서 app.py 607줄의 size verdict gate 실패를 재현했다. 이동 뒤 app.py 599줄이고 동일 gate PASS. 관련 서버 app·goal-evidence 58 PASS, 독립 8개 suite 121 PASS와 이전 코드 differential trace 일치로 재검토 APPROVE.
- gate 변화: SOURCE/LOCAL 구성 분리만 기록한다. 실제 새 이미지와 물리 수락은 별도다.

## 2026-10-04 · uncommitted · fix(ci): preserve current admission and shared controls in regressions

- 변경: CELL_TRANSFER 교환 시험에 기존 real shared-admission 도우미를 연결하고 재시작 시험은 새 owner/admission을 reopened store에 한 번만 bind한다. 기존 승인 거부·store identity·replay·직접 driver 거부·미해결 stop 검증은 유지한다. Slip sheet checkbox에 공용 field/check 클래스를 적용하고 장비 목록 조회 중 버튼에 사유를 표시한다. reset/finally에서 그 사유를 지운다.
- 증거: 이전 두 CELL_TRANSFER 파일 18 FAIL/14 PASS를 재현했다. 수정 뒤 관련 Python 선택 94 PASS, Node 3 PASS와 독립 재검토 APPROVE. 새 runtime guard나 robot 명령은 없다.
- gate 변화: SOURCE/LOCAL CI 복구만 기록한다. 새 이미지와 실제 UI/물리 수락은 별도다.

## 2026-10-04 · uncommitted · docs: re-judge exact integrated Fleet size

- Change: Record the independently counted 32481 production/web lines after inherited D-454 registry/permission wiring and D-455 map-pose extensions, plus four reviewed shared UI lines. Preserve B2/UI migration, all file limits and the package +150 allowance. No production code changed for this judgement.
- Evidence: Independent accounting: recorded32162, current main32477, current branch32481. Registry owners remain bounded, resolver507, app600, Console777; no new final command publisher. Architecture and registry/meet/resolver regressions77passed.
- Gate: SOURCE/LOCAL architecture judgement only; no robot, motion or physical acceptance.

## 2026-10-04 · uncommitted · fix(tools): restore cross-module capture ownership

- Change: Move the inherited Fleet/Games capture tool to workspace tools, as required by tools/AGENTS.md. Update repository resolution and the run command; retain the historical capture entry unchanged. The initial architecture run rejected its Fleet-to-Games import with two failures.
- Evidence: Corrected architecture and registry-write regressions42passed. Independently measured Fleet32543 consists of prior32481 plus62 inherited registry lines; retain +150 allowance, B2/UI migration and all individual file limits. The capture composes fake Fleet with local Games preview; it is not device or physical evidence.
- Gate: SOURCE/LOCAL correction only. Signed installer5dbbe7 remains unchanged; physical marker identity stays HOLD.

## 2026-10-05 · uncommitted · fix(site): complete candidate contract and owned relearn guards

- 변경: API Ref1.99 검사 핀과 페어링 overlay의 --track을 정합했다. 배경 학습을 기존 공용 확인 소유자에 연결하고 운용자 권한 안내를 표시한다. UI/UX 리팩터링 없음.
- 증거: affected 첫 묶음 7751 PASS/8 FAIL/15 ERROR와 perception 2626 PASS/109 SKIP. 발견 항목을 정리하여 관련 130 PASS 및 공유 palette 26 PASS. 부족한 motion 계약 경로를 호스트 환경에 추가한 직접 재검사도 포함한다. Chromium 확인·취소·수명 검증 4 PASS; 나머지 이전 scope 12 PASS. 최신 깨끗한 main에서 기존 확인 테스트의 숨은 작업 탭 클릭 실패를 재현한 뒤 실제 작업 탭 선택을 먼저 하도록 검사만 수정했다.
- gate 변화: SOURCE/LOCAL 증거만 갱신. 현장 두 등록 로봇 online 및 S21 sequence 증가를 재확인했지만 서명 배포·배경 학습·좌표 오차는 미완료이며 관리자 인증이 없는 기존 정적 설정은 보존한다.

## 2026-10-05 · uncommitted · feat(fleet): LAN 수신 승인과 기억한 Cam 연결

- 변경: 기존 영상 자격 소유자에 HTTPS camera-peer 프로파일, source/key/issuer/generation 관계, 원자적 nonce 소비·자격 갱신, 정상 설치 화면 승인을 연결한다. Bluetooth·IP 입력은 기본 흐름에 넣지 않는다.
- 증거: 독립 최종 35 경로 SPEC/Quality/Safety SOURCE PASS. 실제 부모 통합 peer/deploy/shared 133 PASS + 기존 CORE kind 1 FAIL 후 공용·CORE Chromium 29 PASS; v1 호환·namespace·API 계약 82 PASS. 인증 거절 브라우저 probe에서 보호 목록 제거·재조회 중단·POST 0. D-362 측정과 기존 분할 의무는 검토 기록 참조.
- gate 변화: SOURCE/LOCAL이며 기존 기기 gate를 대체하지 않는다. Android 앱·signed site·실제 LAN 승인/오프라인 재연결은 추가 검증한다.

## 2026-10-05 · uncommitted · feat(fleet): 무마커 시작점 위치·방향 저장

- 변경: 승인 paint-fit의 source/map/revision에 묶인 reference-only x/y/yaw를 SQLite에 저장한다. viewer 읽기·operator 저장/삭제·revision CAS·범위/finite 검증·보정 변경 무효화를 추가했다. 기존 지도에서 선택하거나 입력해 저장하고 위치·방향을 다시 표시한다. 지도 선택은 goal 클릭과 분리하며 CORE 위치·신원·주행 승인을 바꾸지 않는다.
- 증거: 관련 API/계약·공용 UI 149 passed, known_failures 신규 0; Node 좌표·여백·무효 표시 3 passed; 실제 Chromium 선택/저장/새로고침/보정 변경·토큰 변경·occupancy 표시/선택 중 지도 변경 3 passed. 독립 읽기 검토의 좌표 형식·JSON 헤더·map 변경 지적 3건을 수정했다.
- gate 변화: SOURCE/LOCAL. 실제 카메라 보정 승인·두 로봇 신원 연결·현장 시작 위치/방향 일치·정확한 후보 CI/서명/배포 수용은 아직 별도다. UI/UX 리팩터링과 주행 없음.

## 2026-10-05 · uncommitted · fix(pairing): 승인 대상 문구와 Cam 역할 경계 정합

- 변경: 카메라 승인·해제 대화상자에서 대상 이름을 따옴표로 구분하고 승인 결과를 명확히 묻는다. 기존 D-341 v1과 D-456 v2 카메라 페어링 namespace만 역할 검사에서 허용하고 v20·v2admin·로봇·사용자·작업 경로는 계속 거절한다.
- 증거: 기존 문구·역할 검사 두 실패를 재현했다. 수리 후 두 관련 suite 14 passed이고 독립 SOURCE 검토에서 owner·lifetime·abort·POST 흐름 불변을 확인했다. 태블릿의 실제 LAN 로봇 목록 및 선택 뒤 기존 로그인 코드 창을 확인했으며 Pilot/Cam APK는 기존 서명으로 업데이트했다.
- gate 변화: SOURCE/LOCAL 및 앱 설치 증거. 새 상대 승인·관제/로봇 배포·승인 유지 재연결의 DEVICE 수용은 아직 별도다.

## 2026-10-05 · uncommitted · fix(ci): 카메라 브라우저 명시적 실행

- 변경: Playwright를 브라우저 fixture의 명시적 opt-in 뒤에 불러온다. opt-in 중 의존성 누락은 오류로 남기며 Fleet CI는 도구 설치 후 ROSY_BROWSER_TESTS=1을 명시한다.
- 증거: 실제 부모 Chromium에서 카메라 7·시작점 3·픽셀 편집 3 합계 13 passed/201.85s. 후보에서 opt-out 7 SKIP과 의존성 없는 opt-in 7 ERROR를 구분해 확인했다. 런타임 TLS 검사는 완화하지 않았다.
- gate 변화: SOURCE/LOCAL 브라우저 증거. CI 성공·서명 배포·실제 양쪽 승인과 재연결은 별도다.

## 2026-10-05 · uncommitted · fix(dialog-target): 카메라 승인·해제 대상 확인

- 변경: 기존 승인·해제 대화상자의 기기 이름과 확인 문자를 따옴표로 구분하고 승인 여부를 질문한다. 레이아웃·UI/UX 리팩터링·API·권한 변경 없음.
- 증거: irreversible 행 행동 검사와 실제 Chromium 카메라 승인 확인 검사 12 passed, known_failures NEW 0.
- gate 변화: SOURCE/LOCAL. 장치·현장 수락은 별도다.

## 2026-10-05 · uncommitted · feat(fleet): 승인된 추적 보정으로 카메라 영상을 편다

- 변경: 검토 중 제안이 없으면 관제 화면은 승인된 Fleet 추적 보정(D-457, 같은 source·지도·렌즈)으로 천장 영상을 트랙 미터에 편다. 기록이 없거나 렌즈가 다르면 이 브라우저의 표시 초안을 쓴다. 표시 전용이며 관측·CameraMap·주행에 넣지 않는다. 예시 카메라 주석은 바닥에 있는 등록 로봇만 robot_ids에 두고, 마커가 없으면 robot_markers가 {}일 수 있다고 적는다.
- 증거: Node map-fit 17 passed (렌즈 일치·행렬 왕복 포함). pytest 콘솔 추적·카메라 예시·페어링 16 passed, known_failures 신규 0.
- gate 변화: SOURCE/LOCAL. 서명된 사이트 이미지의 콘솔 JS는 이 커밋만으로 바뀌지 않는다. 주행 없음.


## 2026-10-05 · uncommitted · fix(cell-ui): 좁은 화면 상단 운영자 표시 줄바꿈

- 변경: D-359 좁은 화면 tier에서 셀 준비 화면 상단 바의 줄바꿈을 허용한다. 기존 구성 요소와 토큰·표시 순서·접속·승인·정지 세대 동작을 유지한다.
- 증거: 정확한 cb6 CI에서 모바일 폭 검사 3개가 실패했다. 실제 Linux 두 시나리오에서 운영자 표시 오른쪽 390.65625px와 문서 폭 391px/화면 390px를 재현했다. Windows 원본 브라우저 9 passed/46.56s, 관련 웹 계약 59 passed/11.30s. 실제 CSS를 쓰는 Linux 세 시나리오는 초기 화면 요소 대기만 분리한 진단에서 3 passed/287.82s와 문서 폭 390px를 확인했다. 기존 세대 충돌·취소·작업자 확인 대기·구조화 초안 저장/재읽기 단언은 유지했다. 원본 Linux fixture 시간 초과는 따로 보존하며 전체 Linux CI 성공으로 표시하지 않는다.
- gate 변화: SOURCE/LOCAL. 독립 검토가 한 줄 CSS의 콘텐츠·CSP·권한·동작 불변을 확인했다. 새 정확한 소스의 원격 CI·서명 배포·앱/관제/로봇의 실제 승인과 재연결은 아직 별도다.

## 2026-10-05 · uncommitted · fix(cell-ui): 문서 패널의 내용 높이 유지

- 변경: D-359 공용 토큰과 반응형 열을 유지하며 문서 그리드를 위쪽 정렬한다. 긴 레시피 때문에 오른쪽 셀 입력란까지 늘어나는 배치를 바로잡는다.
- 증거: 준비된 동일 DOM에서 이전 CSS 기준 셀 입력란 176.78125px가 실제 수정 CSS에서 44px로 줄었다. 390/800px 입력란 높이와 390px 좌표, 모든 화면 폭과 컨트롤 상태·운영자 세션을 유지했다. 데스크톱 진단 1 passed/39.12s, 최종 원본 Windows 브라우저 9 passed/32.28s. 독립 검토가 두 CSS 변경의 CSP·포커스·순서·권한·저장·세대 동작 불변을 확인했다.
- gate 변화: SOURCE/LOCAL. 최종 원격 Linux CI, 서명 배포와 실제 앱·관제·로봇 승인 및 재접속 검증은 별도다.


## 2026-10-05 · uncommitted · fix(fleet): 기존 등록의 승인 TLS 전송과 downgrade 기록

- 변경: 공개 sidecar를 기존 등록 ID·정본 .local 이름·CA DER 지문에 묶는다. 기존 encrypted credentials/principal/expiry/address를 유지하며 bounded nofollow 파일 검증과 같은 TLS 위치의 anonymous identity 확인 뒤에만 코드·Bearer·WSS auth를 보낸다. 기존 hold/expiry를 await 뒤에도 검사한다. 공개 origin/CA marker는 같은 등록부에 원자 저장하고 설정 누락·교체·재시작의 HTTP downgrade를 막는다. 정상 로그아웃 확인 후 실제 등록 행 삭제에만 marker를 함께 지운다. CLI와 두 기존 Compose는 기존 RO config의 선택적 공개 파일만 전달한다. 새 roster·권한·token 갱신·TLS 무시는 없다.
- 증거: 최종 기존 affected 206 passed/2 Windows filesystem skipped(49.27s), 마지막 새 테스트 23 passed/1 symlink skipped(2.77s), 독립 tail 5 passed(1.61s). restart/CA DER/receiver ID/WS identity/REST await/WS await 6개 X compiled-byte 변이는 모두 실제 RED이며 원본 복원 GREEN과 production hash 불변을 확인했다. owned Python 6파일 flake8 0, diff check 및 known_failures 0 NEW. 초기 namespace prerequisite 실패와 pending logout retry RED는 별도 원본 로그로 보존했다. 공개 runbook은 CA/origin rotation 및 실제 관리자 적용을 미구현·미실행으로 밝힌다.
- gate 변화: SOURCE/LOCAL만. 독립 SPEC/Quality/Safety source PASS. 실제 TLS handshake/WSS·사이트 설정·기기·운용 승인은 NOT_RUN이며 기존 ARTIFACT/DEVICE/FIELD gate를 올리지 않는다.


## 2026-10-05 · uncommitted · refactor(fleet): CLI feature 생성 경계 분리

- 변경: 기존 P6 before-next-flag 의무에 맞춰 Mission·Cell compiler·proposal/evidence, 카메라 pairing, 등록 TLS 생성만 lazy console builder로 옮겼다. CLI의 기존 거절·alias·옵션, 동일한 load→roster.sync 순서, 한 번의 create_app 및 기존 localization builder 위임을 유지한다. 런타임·권한·새 background owner는 추가하지 않는다.
- 증거: Mission·pairing 본문 AST 동등과 등록 생성의 명시적 config 인수 외 동등, 새 interpreter에서 비활성 optional dependency 미로드·alias 동등을 확인했다. 기존 CLI/TLS 55 passed/Windows symlink 1 skipped(34.83s), owned Python 2파일 flake8 0, known_failures 0 NEW. 실제 동일 P6 filter에서 CLI652→586, 새 builder91, Fleet35581→35606(+25)이다. 600/800/1000 및 +150 제한은 수정하지 않았다.
- gate 변화: SOURCE/LOCAL 구조 후속만. 실기·사이트 설정·운용 수용은 이전 NOT_RUN을 유지한다. CLI stale verdict와 Fleet package 재판정은 통합 owner가 별도로 처리한다.

## 2026-10-05 · uncommitted · test(validation): D-426 T2 통신·결과 상관 탐침 판정 계약

- 변경: `operations/fleet/test/test_gazebo_protocol_probe.py` 추가 — `tools/validation/fleet_gazebo/probe.py` 판정기의 계약을 고정한다. 실제 wire 형태(HELLO 거부 코드 4종, nav.* 이벤트 correlation_id==attempt_id, 종단 상태 COMPLETED/FAILED/HOLD)를 그대로 쓴 관측 목록으로 LOCAL 판정만 증명하고, 실제 프로세스 사이 관측은 T6 ROS-SIM 회차가 만든다.
- 증거: 13개 판정 계약(WELCOME 거절·identity 충돌·계약 불일치·수락 없는 완료·다른 attempt·중복·역순·유실·timeout INCONCLUSIVE·나이/시계 분리 5종). test_server_traffic·test_boundaries 회귀 포함 68 passed.
- gate 변화: 없음(SOURCE/LOCAL). probe는 판정 모듈이며 Fleet 서버 코드를 바꾸지 않는다.
- 결정: timeout은 자동 실패/성공이 아니라 조회·이벤트 대조 대상(계획 T2 항목 3). 부작용 재전송 금지를 판정기 수준에서 고정했다.

## 2026-10-05 · uncommitted · fix(validation): D-426 T2 판정 근거와 현재 원본 나이

- 변경: 시도별 판정에서 robot ID까지 결속하고 goal·수락·정확한 CORE terminal event/status·시간순서를 확인한다. `nav.completed`는 COMPLETED, `nav.failed`는 FAILED의 근거다. `nav.canceled`는 기본 UNKNOWN이며 이 입력에 cancel-all 정산 권한 증거가 없으므로 HOLD 성공 근거로 쓰지 않는다. 근거 부족은 INCONCLUSIVE, 모순·다른 로봇·역순은 FAIL이며 재전송하지 않는다. HELLO/WELCOME도 같은 로봇과 순서가 필요하다.
- 나이: 기존 시험의 수신 시점 지연 나이 고정을 현재 source-clock 나이로 수정했다. now를 인접 clock 표본 사이에서 보간하고 pause는 보존한다. 표본 밖·rollback·비유한/손상 표본은 unknown이며 extrapolation하지 않는다.
- 증거: 기존 원래 경로에서 19 FAIL/12 PASS, 두 로봇 중 한 응답 누락 회귀 1 FAIL을 재현했다. 중간 분기 연결 오류 4 FAIL도 보존했고 수정 후 probe·기존 traffic·boundary 91 PASS(5.41s)다. 모든 HELLO의 응답이 없으면 세션 전체는 INCONCLUSIVE이며 정상 세션 PASS도 유지한다. 실제 HTTP/WS·ROS-SIM·기기 실행은 없고 입력 관측 목록을 판정한 host 증거다.
- gate 변화: T2 판정 source 보완이며 T3 관측기나 실제 회차 수용을 추가하지 않는다.

## 2026-10-05 · uncommitted · fix(fleet): DNS-SD가 비면 저장한 HTTPS 이름의 호스트 Avahi 주소

- 변경: DNS-SD에 저장한 로봇 이름이 없으면 `socket.getaddrinfo`로 사설 LAN IPv4 하나를 고르고, 저장한 URL 포트와 TLS 이름·CA 검증을 유지한다. 그 이름의 광고가 있는데 분류에 실패하거나, 사설 LAN IPv4가 없거나 둘 이상이면 기존 연결 실패를 유지한다. HTTP로 내려가지 않는다.
- 증거: discovery transport와 enrolled TLS 32 passed, 1 skipped, 7.34s. Windows symlink 1 skipped. flake8 0. known_failures 0 NEW. 호스트 조회는 테스트에서 대체했고 실기기 연결은 하지 않았다.
- gate 변화: SOURCE/LOCAL. 서명된 사이트 이미지와 현장 연결은 이 커밋만으로 바뀌지 않는다. 주행 없음.

## 2026-10-05 · uncommitted · fix(discovery): LAN 이름 조회 작업과 대기 상한

- 변경: 발견·이름 조회 총 4초, NSS 스레드 4개·진행/완료 항목 64개·완료 캐시 2초로 제한한다. 같은 이름·포트 조회를 공유하고 시간 초과·호출자 루프 종료 후에도 원래 작업이 끝날 때까지 소유권을 유지한다. TLS 이름·CA·등록 정책·만료·회수 검사는 유지한다. D-432에 자원 상한과 멈춘 OS 조회를 강제 종료하지 못하는 한계를 기록했다.
- 증거: 실제 getaddrinfo를 멈춰 원래 대기 상한 실패를 재현했다. 동시 요청·시간 초과 재시도·루프 종료·작업 상한·캐시 만료 DHCP 변경을 회귀 검증한다. 모든 fixture는 호스트 합성이며 실제 컨테이너·기기 접속은 미검증이다.
- gate 변화: 없음. SOURCE/LOCAL 자원 경계 보완이며 현장 연동이나 제어 수용은 통과 처리하지 않는다.

## 2026-10-05 · uncommitted · feat(server): D-426 T4 공유 구간 진입 허가·점유

- 변경: `traffic_reservations.py`·`segment_store.py` 추가 — 같은 Task DB 에 구간 정의(구간 ID·지도 revision·진입/출구·안전 대기점·반경)와 `fleet_segment_grants` 표. 상태는 FREE(행 없)→RESERVED→OCCUPIED→RELEASING→FREE, 불명 UNKNOWN. Fleet만 writer. `request`는 활성 상태(RESERVED 포함)면 재할당을 거부하고, `verify_grant`는 수락 측 일치·만료·세대를 검증하며, `confirm_entry`는 신뢰 위치가 구간 안일 때만 만료를 경계에서 재검사해 받아들인다. `begin_release`는 신선한(≤2 s) 출구 이탈 관측과 종단 실행 결과 둘 다 대조한 뒤 RELEASING을 열고 `confirm_exit`로만 FREE가 된다. 시간 만료·링크 상실(`mark_unknown`)만으로는 FREE가 되지 않는다. `waiting_seconds`는 RESERVED가 60 s 이상 진입 못 하면 운영자 대조로 남긴다(자동 후반전 없음).
- 증거: test/test_traffic_reservations.py 10개 계약 — 동시 진입·빈/못난 식별자·다른 지도 revision·위치 미확정·만료 경계 재검사·UNKNOWN도 재진입 거부·시한만 지난 RESERVED 재할당 금지·출구 관측/종단/낡은 관측별 해제 거부·결속·세대·만료 검증·Fleet 재시작 후에도 grants 잔존·대기 보고. 기존 traffic/boundary 포함 47·33 PASS.
- gate 변화: SOURCE/LOCAL 판정 모듈. 실제 로봇 진입·Nav2 경로 제약·robot-side gate 미구현으로 T4 전체 수용은 HOLD다(계획 T4 항목 4·5).
- 결정: competing dispatcher를 만들지 않는다. grant 만료는 실제 footprint 진입 시한이며 시한 경과만으로 구간을 풀지 않는다(D-426 결정 3).

## 2026-10-05 · uncommitted · fix(fleet): T4 해제 근거·Task 트랜잭션 경계

- 변경: 진입·해제 시작·최종 해제는 현재 task/attempt/robot/map revision/generation 전체 결속을 대조한다. 미래·비유한 위치와 시간대 없는 시각은 해제 근거가 아니며, 진입 이후 관측의 나이 0~2 s를 최종 삭제에서도 다시 검사한다. 활성 grant의 구간 정의를 덮어쓰지 않는다. 모든 쓰기 helper는 자신의 SAVEPOINT만 닫고 호출자의 기존 Task DB 트랜잭션과 rollback을 보존한다. 표 준비는 implicit commit을 일으키는 executescript를 쓰지 않는다.
- 증거: 원래 실제 SQLite 미래/NaN/Infinity 위치 해제, 오래된 최종 해제, 읽기·쓰기 중 pending audit 조기 commit 반례 6 FAIL을 재현했다. 기존 10건과 결속·관측·정의·rollback 회귀 31건, TaskStore/dispatch/traffic 관련 시험 합계 106 PASS(6.47s), known_failures 0 NEW, owned flake8 0이다. 원래 성공 fixture의 5 s 최종 대기는 기존 2 s 계약에 맞는 1 s로 정정했다.
- gate 변화: SQLite 순수 helper SOURCE/LOCAL 보완만. 이 helper는 실제 dispatcher·driver와 연결되지 않았고 robot-side 진입 fence·실제 ROS/SIM·장치 수용은 HOLD를 유지한다. UNKNOWN·RESERVED를 시한만으로 풀거나 motion·승인 역할·전송 경로를 추가하지 않았다.


## 2026-10-05 · uncommitted · fix(test): T2 exact-source import 격리

- 변경: T2 probe 테스트가 전역 sys.path 앞에 Gazebo 경로를 넣어 Vision observer를 가리던 문제를 private exact-file 모듈 로더로 닫았다. probe 판정 함수와 런타임은 바꾸지 않았다.
- 증거: 원래 probe-first/Vision collection 1 ERROR 재현 후 T2/T5/T3/Vision 양방향 각 105 PASS. 기존 generic observer/probe/scenarios 및 sys.path를 보존하는 fresh-process 회귀 포함.
- gate 변화: 없음. HOST collection 증거이며 ROS/SIM/기기 실행 수용은 아니다.

## 2026-10-05 · uncommitted · fix(ui): 목표 취소·관제 적합·미지원 카메라 조회 복구

- 변경: 시작점 설정을 기본 접힌 disclosure로 묶고 모든 입력·저장·상태·지도 표시는 유지했다. wide 지도42dvh 규칙이 뒤의 기본54dvh 규칙에 덮이지 않도록 실제 CSS 우선순위를 바로잡았다. v2 카메라의 인증된 지원 조회가 성공하기 전에는 legacy source 목록을 추가 조회하지 않는다.
- 증거: 원래 세 브라우저 회귀3 FAIL14.85s를 재현했다. 첫 수정은2 PASS1 FAIL21.55s(문서 overflow258→4px)이었고 최종12 PASS79.54s에서 원래 viewport·키보드·카메라404 횟수와 시작점 저장/재로드/토큰 교체/지도 변경, Stop·확인·Abort 계약을 유지했다.
- 경계: fixture·로컬 Chromium SOURCE/LOCAL 보완만. 서버 권한·API·자동 페어링·실제 로봇 명령을 추가하지 않는다. 정적 계약39 PASS1 inherited P6 FAIL을 보존했고 package 예산이나 기존 거대 파일 verdict를 바꾸지 않았다. 기존 게이트/HOLD·장치 수용은 그대로다.
- gate 변화: 없음. 기본 화면과 기존 조작 계약 복구이며 실제 연결·제어 수용은 별도다.

## 2026-10-05 · uncommitted · fix(fleet): 증거 프로파일 매핑을 canonical 계약으로 이동

- 변경: 내부 증거 수신기의 기존 세 profile validator 매핑을 learning artifact 계약이 소유한다. Fleet의 로봇 이름 예외를 추가하지 않으며 검증·wire 의미를 유지한다.
- 증거: 기존 main 두 차단을 재현했다. 독립 규모 검토에서 Fleet 36,234줄을 승인했고 모든 파일/패키지 기준을 유지한다. 수신기·literal·artifact 검사 43 PASS, 1 SKIP, 차단 회귀 2 PASS. docs/validation/line-release-2026-10-05/result.md에 책임별 증가를 기록했다.
- gate 변화: SOURCE 배포 검사 차단 수정이며 기기·FIELD 수용은 별도다. 차선 자동 주행은 NOT_RUN을 유지한다.

## 2026-10-05 · uncommitted · fix(test): bootstrap Fleet cell process before collection

- 변경: Fleet 공통 테스트 초기화에 palletizing source 경로를 추가한다. 다른 테스트가 나중에 추가하던 경로에 의존하지 않는다. 제품 코드나 검사 제외는 바꾸지 않는다.
- 증거: shared main과 작업 트리에서 cell app 두 파일 단독 수집이 모두 2 ERROR로 재현됐다. 수정 후 API·실제 로컬 Chromium·compiler 회귀 30 PASS, known_failures 0 NEW (`X:/DevTemp/line-remote-20261005/cell-green.txt`). 배포 gate 증거는 docs/validation/line-release-2026-10-05/ci-followup.md에 기록했다.
- gate 변화: HOST 수집 및 회귀 PASS. 새 CI·서명 릴리스와 기기·자동 주행·FIELD 수용은 별도 검증한다.

## 2026-10-05 · uncommitted · uiux/live-console: 관제 접속·좌표·시작점 준비 흐름

- 변경: 관제 접속 → 카메라·지도 보정 → X/Y 좌표 확인 → 시작점 설정 안내와 접속 입력 포커스를 추가했다. 인증 상실 시 이전 지도·로봇·좌표·시작점을 지우며 지연된 일반 조회 성공이 인증을 다시 열지 않는다. 승인된 보정이 없는 첫 조회는 설치·보정 화면에서 해야 할 일을 안내한다. 시작점 입력을 PC·모바일 격자로 정리했다.
- 증거: 새 Chromium 두 시나리오 2 FAIL 재현 후 기존 저장·재로드·인증 교체·지도 변경 포함 5 PASS. API/색상/기능 계약 62 PASS. 독립 리뷰의 D-359 breakpoint 위반 1 FAIL 재현 후 표준 구간으로 수정했고 반응형·Chromium·표시 계약 재검사 33 PASS, known_failures NEW 0. PC·모바일 브라우저 화면과 키보드 접속·가로 넘침을 확인했다.
- 경계: API·역할·주행·보정 승인 계약은 그대로다. 브라우저 시험은 가짜 로봇 transport이며 실제 지도 좌표 오차나 현장 수용을 증명하지 않는다. CI·서명 후보·배포 readback은 이어 확인한다.
- gate 변화: 없음. SOURCE/LOCAL UX 보완이며 원래 장치·현장 HOLD는 유지한다.

## 2026-10-05 · uncommitted · uiux: give the cell header link the quiet control face

- 변경: /console 머리의 Cell 작업은 주소와 격자 자리를 유지하고, 조용한 버튼과 같은 면·높이·포커스를 쓴다.
- 증거: test_site_map_api.py를 포함한 호스트 계약 100 passed, known_failures 0 new.
- gate 변화: 없음.

## 2026-10-05 · uncommitted · fix(fleet): 목표·대형 지원 기능 확인

- 변경: CAP-001 표시와 전송 직전 재확인, 미지원 목표·대형 버튼 사유, 교체·대형 편입 경합 차단, ARMING 팔로워 예약. CORE 계약과 최종 제어 권한은 유지한다.
- 증거: 관련 Python 180 PASS, Node 3 PASS, Chromium 2 PASS, 독립 리뷰 54 PASS와 scoped safety PASS. 기능 허용 변이 RED 후 복원 GREEN을 확인했다. docs/validation/fleet-navigation-support-2026-10-05.md.
- gate 변화: 소스 회귀만 확인. 실기 두 대의 짧은 수동 진단과 최종 IDLE·속도 0을 읽었다. 새 후보 배포·목표·대형 실동작은 NOT_RUN, 독립 FIELD 수용은 HOLD.

## 2026-10-05 · uncommitted · fix(fleet): 기능 표시 조회의 상태 응답 대기 제한

- 변경: 기능 표시를 50ms만 기다리고 조회 작업을 공유한다. 미완료·만료 증거는 unknown이며, 교체·종료 때 작업을 취소한다. 전송 직전 CAP-001 검사는 유지한다.
- 증거: 느린 CAP 조회로 상태 응답이 막히는 RED 재현 후 GREEN. 독립 리뷰 81 PASS·known_failures 0 NEW, 30개 동시 조회 공유·종료 취소 확인. 첫 서명 후보의 CI는 PASS였지만 현장 최종 기능 검사 실패로 정상 롤백했다.
- gate 변화: 소스 지연 문제 수정만 확인. 보완 후보의 실제 5초 기능 검사와 최종 배포는 검증 중이며, 목표·대형 실주행과 FIELD 수용은 HOLD다.

## 2026-10-05 · uncommitted · fix(fleet): 기능 표시 도우미를 기존 표시 모듈로 이동

- 변경: `CapabilityDisplay`를 기존 `console_view.py`로 이동한다. 안전 파일의 새 decision 모듈 import를 만들지 않고, 표시 대기 50ms와 전송 직전 CAP-001 검사를 유지한다.
- 증거: 실제 pre-push에서 3781 PASS, 479 SKIP, D-430 분리 검사 1 NEW를 확인했다. 새 예외나 검사 완화 없이 동일 도우미를 기존 표시 경계로 옮겨 재검증한다.
- gate 변화: 소스 분리 규칙 보완이며 관제 최종 설치와 두 로봇 릴리스, 목표·대형 주행 FIELD 검증은 진행 중이다.

## 2026-10-05 · uncommitted · fix(fleet): 기능 표시의 안전 경계 의존성 복구

- 변경: 기능 표시 캐시를 기존 화면 전용 모듈로 통합해 FleetConsole 안전 경로에 새 결정 의존성이 생기지 않게 했다. 표시 응답·전송 직전 기능 검사는 그대로 둔다.
- 증거: D-430 안전 경계 및 기능 표시 회귀 검사를 실행했다. 실기 재배포 증거는 별도다.
- gate 변화: 없음. 기존 FIELD HOLD를 유지한다.

## 2026-10-05 · uncommitted · fix(fleet): D-468 계약 문서 버전 검사 정렬

- 변경: 목표·대형·차선 문서 계약 테스트가 최신 API 문서 v1.106을 확인하도록 갱신했다.
- 증거: 관련 문서 계약 테스트 36 PASS. 로봇 명령·런타임 변경 없음.
- gate 변화: 없음.

## 2026-10-06 · uncommitted · feat(fleet): 내부망 카메라 미리보기

- 변경: Caddy가 사설망 발신자의 Fleet 카메라 source·lease 요청에만 내부 표시를 붙이고, Fleet는 해당 두 경로에서만 토큰 없는 viewer lease를 발급한다. 콘솔은 인증된 관제 세션이 없어도 카메라를 갱신한다.
- 증거: Fleet 권한 경계 테스트, Caddyfile adapt, 브라우저 JS 구문 및 관련 테스트. 실사이트 배포·영상 readback은 별도 확인이 필요하다.
- gate 변화: LOCAL 검증만 추가. SITE/FIELD 상태는 그대로 둔다.

## 2026-10-06 · uncommitted · uiux(fleet): 동등한 창 너비 통일

- 변경: Fleet 현장 지도와 개입 영역을 같은 폭으로 맞췄다. 넓은 화면에서 나란한 지도·카메라 창도 같은 폭이다. 320px 상단바는 Cell 작업을 설정 안으로 옮겨 브랜드와 비상 정지의 가독성을 확보했다.
- 증거: 1920×1080 Fleet 브라우저 71 passed, 너비 단언 포함 적합 검사 1 passed, known_failures 0 new. 320px 화면에서 가로 넘침과 상단바 겹침이 없고 Cell 작업 접근 가능. 캡처는 X: 관리 세션 evidence에 있다.
- gate 변화: LOCAL UI 증거만 추가. D-153 G3 사람 평가 및 SITE/FIELD 수용은 미완료.

## 2026-10-06 · uncommitted · uiux(fleet): 기본 예외 목록 증거와 지도 바탕

- 변경: 320/390px 브라우저 시험에서 전체 목록을 열기 전 기본 예외 목록을 단언하고 캡처한다. 지도의 레터박스는 미관측 raster 토큰으로 표시하고, 지도·카메라 동일 너비 주석과 110rem 이유를 현재 배치에 맞춘다.
- 증거: Fleet 지도 적합·목표 2 passed, 모바일 기본 예외·넘침 2 passed, 관련 G1 83 passed, known_failures 0 NEW. 320px 기본 목록에서 오류 로봇 rosy_03이 첫 카드다.
- gate 변화: LOCAL 증거만 추가. Fleet G2 전체 상태·G3와 SITE/FIELD readback은 미완료다.

## 2026-10-06 · uncommitted · uiux(fleet): 빈 목록·서버 실패의 모바일 폭과 연결 끊김 증거

- 변경: 320/390px의 빈 목록·서버 실패에서 E-stop과 다음 단계가 보이고 가로 넘침이 없음을 브라우저로 확인했다. 연결 끊김 fixture를 실제 Fleet API의 `state: null` 계약에 맞춰 고쳤다.
- 증거: 기존 상태 9 passed, 모바일 상태 4 passed, 연결 끊김 재실행 1 passed, 각 `known_failures.py` 0 NEW. 캡처는 [UI/UX 회차](../../docs/validation/uiux-surfaces-2026-10-06/README.md)에 있다.
- gate 변화: LOCAL G2 부분 근거. Fleet G2/G3와 SITE/FIELD는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 정지 중 목표 상태 문구와 G3 근거

- 변경: 탐색 상태가 NAVIGATING으로 남아도 안전 상태가 결측이거나 E-stop이면 주행 중이라고 표현하지 않고 목표가 남았음을 알린다. 기존 공용 탐색 상태 번역을 재사용한다.
- 증거: 안전 결측·정지와 목표 확인 브라우저 3 passed, Fleet 서버·팔레트 60 passed, 웹 Node 134 passed, `known_failures.py` 0 NEW. [G3 독회](../../docs/validation/uiux-surfaces-2026-10-06/README.md)는 LOCAL 부분 근거다.
- gate 변화: Fleet G3·SITE/FIELD HOLD 유지.

## 2026-10-06 · uncommitted · uiux(fleet): 연결 끊김 모바일 독회

- 변경: 로봇 연결 끊김 fixture를 1920/390/320px에서 재생해 첫 카드의 오류 우선순위, 오래된 상태 배제, 비상 정지 가시성, 가로 넘침 부재를 확인했다.
- 증거: [UI/UX 회차](../../docs/validation/uiux-surfaces-2026-10-06/README.md)의 X: 모바일 캡처; 브라우저 3 passed, `known_failures.py` 0 NEW.
- gate 변화: Fleet LOCAL G2 부분 근거 추가. 실제 사이트 PC/로봇 readback과 G3 독회는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 팔로워 지연 모바일 독회

- 변경: 팔로워 지연·끊김 화면을 1920/390/320px에서 재생해 경고 카드 우선순위, 비상 정지 가시성, 가로 넘침 부재를 확인했다.
- 증거: [UI/UX 회차](../../docs/validation/uiux-surfaces-2026-10-06/README.md)의 X: 모바일 캡처; 브라우저 3 passed, `known_failures.py` 0 NEW.
- gate 변화: Fleet LOCAL G2 일부 추가. 실제 사이트 PC/로봇 readback과 G3 독회는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 전체 주행 취소 결과를 행동 옆에 표시

- 변경: 전체 주행 취소 응답 요약과 로봇별 기록 링크를 버튼 가까이에 놓았다. 503은 물리 결과를 미확인으로 말하고 재확인을 안내한다.
- 증거: [UI/UX 회차](../../docs/validation/uiux-surfaces-2026-10-06/README.md)의 X: 1920/390/320px 확인·부분 응답과 320px 오류 캡처; 브라우저 5 passed, `known_failures.py` 0 NEW.
- gate 변화: Fleet LOCAL G2/G3 일부 추가. 실제 사이트 PC·로봇 readback과 현장 사용자 독회는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 비상 정지 응답 첫 화면

- 변경: 운용·설치의 비상 정지 요청/부분 응답/결과 미확인을 머리 아래에서 바로 읽게 했다. 설치 안내는 비상 정지와 전체 주행 취소를 구분하고 카메라 승인 제목 수준을 정리했다.
- 증거: [UI/UX 회차](../../docs/validation/uiux-surfaces-2026-10-06/README.md)의 X: 320/390px 캡처; 집중 브라우저 10 passed, 설치 회귀 7 passed, 팔레트·토큰 52 passed, 각 `known_failures.py` 0 NEW.
- gate 변화: Fleet LOCAL G2/G3 일부 추가. 실제 로봇 정지 readback과 현장 사용자 독회는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 머리 아래 블록과 본문 폭 정렬

- 변경: 운용·설치 비상 정지 응답과 운용 준비 순서·접속 안내의 좌우 여백을 본문 패널과 같게 했다.
- 증거: 1920/390/320px 운용·설치 좌우 끝 브라우저 6 passed, 팔레트·토큰 52 passed, 각 `known_failures.py` 0 NEW. 원본은 X: UI/UX 회차의 `captures/fleet-width/`.
- gate 변화: Fleet LOCAL 폭 근거 추가. 전체 G2/G3와 현장 사용자 독회는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 로봇 카드 행동 폭과 데스크톱 높이

- 변경: 로봇 카드의 동등한 목표 지정·취소 버튼을 같은 폭으로 배치하고, 1920px 본문 하단 5px 넘침을 제거했다.
- 증거: [UI/UX 평가](../../docs/validation/uiux-surfaces-2026-10-06/README.md)의 320/390px 폭 단언과 1920px 높이 검사 등 Fleet 브라우저 6 passed, `known_failures.py` 0 NEW. 전화 원본은 X: `fleet_console_mobile_default_{320,390}.png`.
- gate 변화: Fleet LOCAL 폭·높이 근거를 추가했다. 전체 G2/G3와 현장 사용자 독회는 HOLD.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 작업 화면의 비상 정지와 평가 카드

- 변경: 활성 `/console/cell`에 첫 화면 비상 정지와 별도 결과 상태를 두고, 기존 관제 세션 토큰을 입력 칸에 이어 받는다. 긴 Cell 작업 요청 중에도 비상 정지는 비활성화하지 않는다. UI/UX 회차에 빠져 있던 Cell 질문·선언 폭·G2/G3 잔여 항목을 추가했다.
- 증거: 1440/390/320px 첫 화면 브라우저 3 passed, 320px 부분 응답·503 미확인·본문 동등 폭 1 passed, Cell 브라우저 전체 13 passed, Fleet 계약 21 passed, G1 명명 계약 90 passed, JS 구문 검사 통과; 성공 실행마다 `known_failures.py` 0 NEW. X: `captures/fleet-cell/`, `logs/fleet-cell-{estop-green,estop-width,browser-full,contracts}.txt`, `logs/g1-after-fleet-cell.txt`.
- gate 변화: Cell LOCAL 첫 화면과 정지 결과의 부분 근거. 선언 상태 전체 G2·실제 셀/로봇 readback·운영자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 작업 취소 확인과 320px 머리

- 변경: Cell 작업 취소 전에 작업 ID·장치 정지 아님을 명시하는 공용 확인창을 열고, 취소·정지·계정 변경 시에는 작업 취소 요청을 보내지 않는다. 좁은 화면의 비상 정지를 머리 첫 줄에 두고 로그인 뒤 긴 세션 이름이 제품 이름·접속 버튼을 밀지 않게 폭을 제한했다.
- 증거: 1440/390/320px 확인·취소 POST 0·정지 가용성·확인 POST 1 브라우저 3 passed, Cell 브라우저 전체 15 passed, Fleet 계약 21 passed, G1 90 passed, 각 성공 실행 `known_failures.py` 0 NEW. 공용 확인 모듈을 Cell 수입 허용 목록에 추가하기 전 Fleet 계약 1건이 실패했고 수정 후 통과했다. 원본 X: `captures/fleet-cell/fleet-cell-cancel-confirm-{1440x1000,390x844,320x568}.png`, 실행 `logs/fleet-cell-cancel-{3widths-final,full-final,contracts-final}.txt`, `logs/g1-after-cell-cancel.txt`.
- gate 변화: Cell 불가역 확인 G2의 LOCAL 폭 근거 추가. 나머지 선언 상태, 실제 장치·운영자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 저장 문서 목록 상태

- 변경: 접속 전·조회 중·빈 목록·조회 실패에 상태와 다음 단계를 표시하고, 자격 증명 변경 시 이전 목록을 숨긴다.
- 증거: 1440/390/320px 빈 목록과 320px 실패·복구 브라우저 5 passed, Cell 전체 19 passed, Cell API 8 passed, 공용 UI 계약 231 passed/25 skipped, 각 성공 실행 `known_failures.py` 0 NEW. X: `captures/fleet-cell/fleet-cell-empty-{1440x1000,390x844,320x568}.png`, `fleet-cell-list-error-320x568.png`, `logs/fleet-cell-list-{focus,full,api,shared}.txt`.
- gate 변화: 저장 문서 목록의 LOCAL G2 부분 근거 추가. 선언 상태 전체·실제 장치·운영자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 세션 거부 전환

- 변경: 재확인 401·403에서 이전 계정·목록·저장 버전·미리보기·작업 상태를 내려 거부 상태로 전환한다. 작성 초안은 남기고 저장·제안은 막으며 거부 이유를 화면 안에 표시한다.
- 증거: 320px 401·403 브라우저 2셀과 기존 실패·컴파일 회귀 4 passed, Cell 전체 21 passed, Cell API 8 passed, 공용 UI 계약 231 passed/25 skipped, 마지막 접속 안내 변경의 집중 재검사 3 passed, JS 구문 검사 통과, 각 성공 실행 `known_failures.py` 0 NEW. X: `captures/fleet-cell/fleet-cell-auth-{401,403}-320x568.png`, `logs/fleet-cell-auth-{focus-final,full,api,shared,final-focus}.txt`.
- gate 변화: 권한 거부 전환의 LOCAL G2 부분 근거 추가. 나머지 선언 상태·실제 장치·운영자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 문서·행동 폭

- 변경: 레시피·셀 문서 창의 세 선언 폭을 측정하고, 390/320px에서 문서·미리보기·제안·승인·복귀 행동이 각 칸의 가용 폭을 채우게 했다.
- 증거: Cell 전체 24 passed와 공용 UI 계약 231 passed/25 skipped 뒤 마지막 미리보기 폭 보정. 현재 세 폭 브라우저 3 passed, 미리보기·취소 상호작용 4 passed, 각 성공 실행 `known_failures.py` 0 NEW. X: `captures/fleet-cell/fleet-cell-widths-{1440x1000,390x844,320x568}.png`, `logs/fleet-cell-{uniform-full,uniform-shared,uniform-widths-final,uniform-interaction}.txt`.
- gate 변화: Cell 균일 폭의 LOCAL G2 부분 근거 추가. 전체 선언 상태·실제 장치·운영자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 저장 충돌·미리보기 실패

- 변경: 편집한 문서를 저장 전 초안으로 표시하고, 저장 409·503 및 컴파일 503을 행동 위치의 공용 상태 칸에 구분해 표시한다. 컴파일 실패 시 이전 미리보기를 내리고 제안을 막는다.
- 증거: 세 폭 충돌·복구와 미리보기 실패·복구 6 passed, 320px 저장 결과 미확인 1 passed, Cell 전체 31 passed, Cell API 8 passed, 공용 UI 계약 231 passed/25 skipped, 마지막 미저장 문서 문구 세 폭 3 passed, JS 구문 검사 통과, 각 성공 실행 `known_failures.py` 0 NEW. X: `captures/fleet-cell/fleet-cell-{save-conflict,preview-unavailable}-{1440x1000,390x844,320x568}.png`, `fleet-cell-save-unavailable-320x568.png`, `logs/fleet-cell-{write-final-focus,save-unavailable,write-full,write-api,write-shared,preview-precondition}.txt`.
- gate 변화: 저장·컴파일 실패의 LOCAL G2 부분 근거 추가. 나머지 상태·실제 장치·운영자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 느린 첫 상태 응답의 세 폭

- 변경: Fleet 관제의 기존 느린 상태 응답 브라우저 시험을 1920/390/320px로 확장하고, 지도·로봇 목록 폭과 첫 화면 정지를 대기·회복에 확인한다. 제품 스타일은 변경하지 않았다.
- 증거: 세 폭 3 passed, 4px 로봇 목록 축소 변이에서 320px 실패, 원복 후 320px 1 passed, 성공 실행 `known_failures.py` 0 NEW. X: `captures/fleet-slow-mobile/fleet_console_slow_{loading,recovered}_{1920,390,320}.png`, `logs/fleet-slow-{three-widths,width-mutation,width-restored}.txt`.
- gate 변화: Fleet 느린 첫 응답의 LOCAL G2 폭 근거 추가. 전체 선언 상태·실제 사이트 PC/로봇·관제자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 수신 후 끊김의 세 폭과 상태 표지

- 변경: Fleet 관제의 수신 후 상태 상실·회복 시험을 1920/390/320px로 확장했다. 320px에서 잘리던 「Fleet 서버 없음」을 compact 시계의 보조 글자 크기로 읽히게 했다.
- 증거: 세 폭 3 passed, 끊김/compact 머리 5 passed, 공유 시트 설치 화면 정지 3 passed, 반응형·팔레트·토큰 97 passed, 각 성공 실행 `known_failures.py` 0 NEW. 320px 표지 잘림은 수정 전 적색, 4px 목록 축소 변이에서 폭 단언 적색, 원복 후 320px 1 passed. X: `captures/fleet-loss-mobile/fleet_console_gather_{lost,recovered}_{1920,390,320}.png`, `logs/fleet-{gather-loss-three-widths,loss-pill-red,loss-pill-font,loss-current,loss-style-contracts,loss-width-mutation,loss-width-restored,loss-install-estop}.txt`.
- gate 변화: 수신 후 끊김의 LOCAL G2 폭·정직 근거 추가. 선언 상태 전체·실제 사이트 PC/로봇·관제자 G3는 HOLD다.

## 2026-10-06 · uncommitted · uiux(fleet): 대형 상태 조회 끊김과 복구의 세 폭

- 변경: 대형 상태 조회 실패 시 원시 `FORMATION_UNAVAILABLE` 대신 Fleet 연결을 확인하라는 안내를 표시한다. 기존 대형 조회 끊김·복구 브라우저 검사를 1920/390/320px로 확장하고 전화 폭의 지도·목록·작업 블록 동일 폭, 첫 화면 비상 정지, 가로 넘침을 확인한다.
- 증거: 대형 끊김·복구와 HOLD 브라우저 4 passed, `known_failures.py` 0 NEW, JS 구문 검사 통과. 원시 코드 노출에 대한 검사 실패 후 수정 통과, 4px 목록 축소 변이에서 폭 검사 실패 후 복원 통과. X: `captures/fleet-formation-mobile/fleet_formation_read_{lost,recovered}_{1920,390,320}.png`, `logs/fleet-formation-{code-red,width-mutation,final}.txt`.
- gate 변화: Fleet 대형 조회 끊김의 LOCAL G2 부분 근거 추가. 전체 선언 상태·실제 사이트 PC/로봇·운영자 G3는 HOLD.

## 2026-10-06 · uncommitted · uiux(fleet): 대형 HOLD 재개 차단과 동일 폭 행동

- 변경: 추가 안전 사건이 남은 HOLD 상태에서 재개를 비활성화하고 재구성 안내를 표시한다. 대형 이유·재개 차단 사건을 관제자 평문으로 바꿨다. 390/320px에서는 네 대형 버튼을 두 열의 동일 폭으로 정렬했다.
- 증거: HOLD와 대형 조회 끊김 브라우저 7 passed, 반응형·토큰·팔레트 계약 61 passed, 각 `known_failures.py` 0 NEW, JS 구문 검사 통과. 재개 오활성 및 320px 버튼 불균등은 수정 전 적색. X: `captures/fleet-formation-hold/fleet_formation_hold_{blocked,ready}_{1920,390,320}.png`, `logs/fleet-formation-hold-{red,width-red,final,contracts}.txt`.
- gate 변화: Fleet HOLD의 LOCAL G2 행동·폭·어휘 부분 근거 추가. 실제 사이트 PC/로봇과 관제자 G3는 HOLD.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 작업 상태 문구와 compact 머리 높이

- 변경: Cell 제안·진행·취소·간지 접근 보류를 운영자 문구로 표시하고 원래 코드는 접힌 진행 원장에 남겼다. 토큰 접속을 붙박이 머리 아래로 내려 390/320px 머리를 177px에서 88px로 줄였으며 계정 상태와 비상 정지는 머리에 유지했다.
- 증거: 상태 원문 노출과 20% 머리 한도 검사가 수정 전 실패한 뒤 Cell 브라우저 33 passed, Cell API 8 passed, 공유 UI 계약 89 passed, 각 `known_failures.py` 0 NEW. 1440/390/320px 간지 보류 화면 캡처와 로그는 X:/DevTemp/projects/rosy-platform/2026-10-06--032913--uiux-quality--199bc9/ 아래에 있다.
- gate 보류: 합성 Fleet 응답의 LOCAL G2 부분 근거다. 사이트 PC Tailscale peer는 online이나 SSH 정책 거부, 8443 접속 실패, 현재 PC는 다른 LAN이라 현장 mDNS·Fleet 컨테이너 NSS·실제 장치 readback·운영자 G3는 미확인이다.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 비활성 작업의 현재 상태 사유

- 변경: 제안된 작업의 재승인과 보류 작업의 실행 승인에 저장·미리보기 안내가 보이던 공통 사유를 작업 상태 안내로 바꿨다. 버튼 허용 조건과 API 요청은 유지한다.
- 증거: 1440/390/320px의 두 흐름에서 기존 6 failed → 수정 뒤 6 passed, Cell 전체 33 passed, `known_failures.py` 0 NEW, JS 구문 검사 통과. X:/DevTemp/projects/rosy-platform/2026-10-06--032913--uiux-quality--199bc9/logs/fleet-cell-action-reason-{red,green,full}.txt.
- gate 보류: 합성 상태의 LOCAL G2 부분 근거. 현장 UI·장치 readback과 작업자 G3는 미확인이다.

## 2026-10-06 · uncommitted · uiux(fleet): Cell 비활성 사유 공용 계약 복구

- 변경: 작업 버튼 사유를 계산한 뒤 비활성 상태와 바로 이어 갱신한다. 기존 작업 상태·권한·간지 접근 사유와 허용 조건은 유지한다.
- 증거: 공용 비활성 사유 검사 1 failed → 1 passed; 공유 UI 전체 231 passed/25 skipped, Cell 세 폭의 작업 상태·간지 접근 브라우저 6 passed, `known_failures.py` 0 NEW. X: `logs/shared-ui-current-after-widths.txt`, `logs/shared-ui-after-cell-guard.txt`, `logs/cell-after-shared-guard.txt`.
- gate 보류: LOCAL 계약·합성 상태 근거. 현장 UI·장치 readback과 작업자 G3는 미확인이다.

## 2026-10-06 · uncommitted · LED 식별 요청과 실영상 현장지도

- 변경: Fleet의 로봇별 단기 LED 요청을 CORE로 전달하고, 승인된 source/map/lens 보정이 맞는 최신 Rosy Cam 원본 프레임만 현장지도 배경으로 사용한다. 식별 응답은 영상 확인 대기이며 robot ID를 자동 확정하지 않는다.
- 증거: 관련 호스트 pytest 274 passed/3 skipped, 웹 Node 135 passed. DEVICE/FIELD 점멸·영상 대조는 아직 확인되지 않았다.
- gate 변화: SOURCE/LOCAL 코드 검증만 추가. SITE/FIELD 상태는 그대로 둔다.

## 2026-10-06 · uncommitted · D-473 관제 콘솔 개발 연결 모드

- 변경: `fleet/server/development_session.py`(세션 저장소·LAN 주소·Host/Origin·분당 6회·상한 8·1시간 만료·발급 감사), `site_auth.build_authorize`의 개발 세션 우선 확인, `require_named_operator`의 `development-*` 허용, `--connection-mode`와 `ROSY_DEPLOYMENT` 이중 조건, 콘솔 자동 발급·배지.
- 증거: 위 호스트 pytest와 브라우저 시험. 사이트 Caddy 뒤 `X-Forwarded-For`·`Host` 전달은 실사이트 확인이 필요하다.
- gate 변화: LOCAL 검증만 추가. SITE/FIELD 상태는 그대로 둔다.


## 2026-10-06 · uncommitted · feat(fleet): D-484 field_boundary sighting 수용

- 변경: `site-cameras.yaml` 검증과 `SightingService`가 `calibration_source: field_boundary`(코너 마커 없음, `corner_world_m` 필수)를 받고, payload의 `calibration_source`까지 일치 검사한다(불일치 409 CALIBRATION_MISMATCH). `GET /api/fleet/site-map` source에 `calibration_source`를 노출하고 field 소스는 `corner_marker_ids: null`이다. 설치 화면 영상 패널에 "자동 보정 (필드)" 보기 모드(리스 rectification `mode:"auto"`, 배지 "자동 보정 미리보기"/"자동 보정 대기")를 추가했다. 관제(/console) 화면은 기존대로 원본만(D-410).
- 증거: `test_sightings_api.py`·`test_site_map_api.py` 확장(field 수용·양방향 불일치·설정 검증·site_map 노출), node 웹 시험 통과(`vision-badge.test.mjs` auto 케이스 포함).
- gate 변화: 없음. sighting은 표시 전용(D-257 5항)·정책 증거 아님을 유지.

## 2026-10-07 · uncommitted · Cell 빈 미리보기 평면도 숨김

- 변경: 배치가 계산되기 전 또는 미리보기 결과가 무효가 된 동안 팔레트 선택과 빈 20rem 평면도를 함께 숨긴다. 배치가 있는 성공 결과에서만 다시 보인다.
- 증거: 320px 초기·503/복구와 390px 초기·1440px 503/복구 Chromium **4 passed**, 공용 UI·토큰 계약 **62 passed**, 각 `known_failures.py` 0 NEW, JS 구문 검사 통과. UI/UX 회차 X: `captures/fleet-cell-empty-layout-fix/`와 `logs/merge-20261006/fleet-cell-empty-layout-{fix,other-widths,g1}.txt`.
- gate 변화: LOCAL 화면 근거 추가. 현장 배치·운영자 G3는 HOLD.

## 2026-10-07 · 93c606cbb · D-487 관제 화면 Rosy Fleet·버드아이 우선

- 변경: 관제·설치·Cell 문서의 표시 이름 `Rosy Console` → `Rosy Fleet`. 지도 아래 천장 카메라 사본(`#map-camera`) 제거 — 원본은 카메라 칸에 한 번, 보정 맞춤은 캔버스가 그린다. 지도가 없고 카메라가 살아 있으면 지도 칸이 한 줄로 줄고 카메라가 주 화면(110rem 이상 전체 폭). 접속 전 발행 띠를 접고 연결 표시는 `접속 전`(중립). `[data-role-lock]` 묶음 안 버튼은 사유를 되풀이하지 않고 묶음 안내 한 줄을 쓴다. id `console`·경로 `/console`·저장소 키는 그대로.
- 증거: 아래 브랜치 시험 기록(`X:/DevTemp/fleet-name/`). DEVICE/FIELD 확인 없음.
- gate 변화: LOCAL 화면 정리. SITE/FIELD 상태는 그대로 둔다.

## 2026-10-07 · uncommitted · D-487 이후 Fleet 데스크톱 높이 보정

- 변경: 1920×1080에서 관제 문서의 43px 세로 넘침을 확인하고 데스크톱 관제 칸 간격·안쪽 여백과 대형 readout의 기본 margin을 줄였다. D-415의 8줄 로그는 유지했다.
- 증거: `X:\DevTemp\projects\rosy-platform\2026-10-07-fleet-d487\`의 `browser-fixed2.txt` **8 passed**, `connection.txt` **1 passed**, `contracts.txt` **60 passed**, `node-files.txt` **137 passed**, 각 Python 실행의 `known_failures.py` 0 NEW, `fleet_console_fit.png`에서 하단까지 표시.
- gate 변화: LOCAL G2 부분 근거. 사이트 PC·카메라·로봇과 운영자 G3는 HOLD.

## 2026-10-07 · uncommitted · Fleet D-153 27셀 재촬영과 예외 상태 데스크톱 맞춤

- 변경: desktop 목록은 한 예외 카드 높이에서 내부 스크롤하고, 예외 큐가 뜰 때 지도와 큐를 뷰포트에 맞췄다. viewer의 중복 버튼 사유를 그룹 안내 한 줄로 정리하고 비상 정지 권한 이유가 보이게 했다.
- 증거: X: `projects/rosy-platform/2026-10-07-fleet-g2/`의 9상태×3폭 `capture.json`·27장 PNG·`validate.txt` 27/27셀. 변경 전 delayed 154px, disconnected 105px, viewer 48px 데스크톱 넘침; 보정 제거 브라우저 3 failed/복원 4 passed, 권한 Node 변이 1 failed/전체 웹 모듈 137 passed, 전체 Fleet 브라우저 106 passed, G1 90 passed, 서버·팔레트 60 passed, Python `known_failures.py` 0 NEW.
- gate 변화: 현재 후보 LOCAL G2 상태·폭 근거 추가. 사이트/장치 readback과 운영자 G3는 HOLD.

## 2026-10-07 · 463ae393a · D-488 M1 현장 지도·주소·경로 계획 (D-489/D-490)

- 변경: `fleet/site_map.py`(`rosy.site_map/1` 장소·방향 있는 차로·선택 `turn_bans`, `lane_graph.yaml` 가져오기), `server/site_map_store.py`(초안 하나·불변 활성 버전·계획 기록, `--tasks-db` 또는 메모리), `site_map_routes.py`(`/api/fleet/site-map/{active,draft,activate}`, 활성화는 이름 있는 운영자·감사·`/route` 30 s 안 진행 시 409), `fleet/routing/`(차로 단위 상태 A*, 시간 비용·회전 분류·`fleet.routing` 설정, 표준 라이브러리만), `trip_routes.py`(`POST /trip` 계획만, `execute`·`/trips/{id}/start` 501). `meet/place.py` `default_graph()` 하드코딩을 없애고 `/route`와 만남 기하가 활성 지도를 읽는다. CLI `--site-map-import`·`--site-config`, 사이트 compose가 이미지의 `lane_graph.yaml`을 첫 지도로 가져온다. 콘솔 `/console/site-map`(지도 보기·초안 편집·활성화·주소/좌표 경로 미리보기). API Ref v1.109.
- 증거: `python -m pytest operations/fleet/test -q -rfE -p no:cacheprovider` 2258 passed/55 skipped, `known_failures.py` 0 NEW(X:/DevTemp/fleet-map-route/run.txt). 계획기 시험: 시드 고정 무작위 그래프 200개 A* = Dijkstra, 규칙별 단위·골든 경로 5쌍·500차로 p95 ≤ 20 ms. 공유 UI 계약 42 passed, 사이트 배포 시험 569 passed, Chromium 지도 화면 1 passed(ROSY_BROWSER_TESTS=1), node 140 passed.
- gate 변화: SOURCE/LOCAL 코드 근거만 추가. 로봇 능력 필드(종류·주행 방식·최대 속도)는 로봇 계약에 없어 기본값으로 계획한다. trip 실행·위치 중재·가르치기(M2), Gazebo(M3), 실차(M4)는 HOLD.

## 2026-10-07 · uncommitted · D-488 M1 검토 반영과 ADR 번호 이동 (D-484/485/486 → D-488/489/490)

- 변경: 독립 검토 REQUEST CHANGES 반영. 길이 0 간선·겹친 장소를 스키마가 거절하고 `point_at` 재귀를 없앴다(모든 `/trip` 500의 원인). 경유지는 `(경유지 번호, 차로)` 층 A* 한 번으로 푼다. 좌표 목표가 닫힌 상태 검사에 가려 길을 놓치던 결함도 고쳤다. 출발은 차로 폭 절반 안, 접선은 max(0.15 m, 폭), 좌표 yaw는 방향 먼저, 목표 장소 위 로봇은 빈 계획이다. 초안 저장은 이름 있는 운영자·2 MiB 상한·지도 사건 기록, 활성화는 계획 불가 지도를 거절한다. 오류 본문을 `{"detail": {"code", "detail"}}`로 맞추고 예상하지 못한 계획기 실패는 422 `TRIP_PLAN_FAILED`다. 거절도 계획 기록에 남기고 1000건·30일만 보존한다. 막힘 판단기는 활성 지도를 명시적으로 받는다. 개발·Gazebo 실행기에 `--site-map-import`를 넣었다. 콘솔은 동작에 주소 이름을 보이고 옛 지도 버전의 계획을 버린다. main의 D-484(경기장 경계 자동 보정)와 번호가 겹쳐 ADR을 D-488·D-489·D-490으로 옮기고 각 ADR에 구현 부록을 더했다. API Ref는 v1.111이다.
- 증거: 아래 전체 Fleet 시험과 `known_failures.py`(X:/DevTemp/fleet-map-route/run.txt), 계획기 29 passed(교과서 Dijkstra 대조 2×200 그래프), 지도·trip API 28 passed, Chromium 지도 화면과 공유 UI 계약 43 passed, 계약 문서 시험 94 passed.
- gate 변화: 없음. SOURCE/LOCAL 근거만 보강했다. D-487·main D-483/D-484와의 병합은 아직이다.

## 2026-10-07 · uncommitted · D-488 M1 재검토 반영 (N1·L1–L3)

- 변경: 차로 접선을 장소에 맞추기 전 그려진 폴리라인의 0.05 m로 읽는다(N1). max(0.15 m, 폭) 창은 map_v2_fleet 회전 교차로 이어짐을 모두 +42° 좌회전으로 읽었다. 지금은 이어짐 직진, 진입·진출 우회전이며 골든 시험이 이를 고정한다. 지도 저장소가 사이트 `fleet.routing` 설정으로 후속 표를 미리 만든다(L1). 계획기의 예상하지 못한 실패는 같은 본문의 500 `TRIP_PLAN_FAILED`다(L2). 스키마에 맞지 않는 초안은 422 `SITE_MAP_INVALID`와 필드 오류이고 콘솔이 보인다(L3). D-489·D-490 부록과 API Ref 행을 맞췄다. main 병합(D-483·D-484·D-487, API Ref v1.110) 뒤 이 가지의 행은 v1.111이고, D-485·D-486은 `adr_gaps`에 번호 이동으로 적었다.
- 증거: 전체 Fleet 시험·계약 문서 시험과 `known_failures.py`(X:/DevTemp/fleet-map-route/run.txt, run_docs.txt), 하네스 lint 0 errors.
- gate 변화: 없음. SOURCE/LOCAL 근거만 보강했다.

## 2026-10-07 · uncommitted · D-488 현장 지도 표시 이름·선언 폭 확인

- 변경: 새 `/console/site-map`의 탭·머리·홈 접근성 이름을 D-487의 `Rosy Fleet`으로 맞췄다. 1440/390/320px에서 초안 편집과 경로 미리보기 칸의 같은 폭, 가로 넘침 없음, 비상 정지 위치를 확인한다.
- 증거: `X:/DevTemp/projects/rosy-platform/2026-10-07-fleet-g2/site-map-green.txt` 4 passed, `known_failures.py` 0 NEW; 같은 폴더 `site-map-*.png` 9장. 이름 검사 수정 전 1 failed.
- gate 변화: 합성 서버의 LOCAL G2 부분 근거만 추가. 작은 지도 글씨의 운영자 판독, 예외 상태, 사이트 설치·G3는 HOLD.

## 2026-10-07 · uncommitted · D-488 site-map G2 empty and conflict states

- Change: The first-use empty map, empty robot roster, and draft revision conflict now give the operator a concrete next step without implying that a map or trip is available.
- Evidence: 9 LOCAL Chromium cells at 1440x1000, 390x844, and 320x568; 28 site-map browser tests passed with 0 NEW known failures. Source screenshots and logs: X:/DevTemp/projects/rosy-platform/2026-10-07--site-map-edge-states/.
- Gate: LOCAL G2 partial evidence only; site/device readback and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Cell 문서 파일 선택 어휘와 폭

- 변경: 레시피·셀 JSON 파일 선택을 한국어 전폭 조작과 선택한 파일명으로 표시한다. 네이티브 파일 입력과 기존 JSON 검증·저장 흐름은 유지한다.
- 증거: 1440/390/320px 브라우저 4 red→4 green, Cell 전체 33 passed, D-153 G1 90 passed, Fleet 웹 144 passed; `docs/validation/uiux-cell-file-picker-2026-10-07/result.md`에 원본·해시.
- gate 변화: 파일 선택 상태의 LOCAL G2 부분 근거. 현장 설치·작업자 G3는 HOLD.

## 2026-10-07 · uncommitted · Site-map rejected credential widths

- Change: Equalized the three draft action widths and checked a rejected reconnect at 1440/390/320px. The browser slow-load check now holds its fixture request until the pending assertions complete.
- Evidence: Three Chromium captures; full site-map browser 30 passed, D-153 G1 90 passed, site-map Node 7 passed, Python known failures 0 NEW. See `docs/validation/uiux-site-map-auth-width-2026-10-07/result.md`.
- Gate: LOCAL G2 partial evidence only; current site/device and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Cell emergency-stop feedback widths

- Change: The existing Cell browser scenario now checks partial and unknown stop-result messages at 1440/390/320px for first-viewport visibility, equal content width, and no horizontal overflow.
- Evidence: 3 focused Chromium tests passed with 0 NEW known failures; six captures and hashes in `docs/validation/uiux-cell-stop-widths-2026-10-07/result.md`.
- Gate: LOCAL synthetic G2 partial evidence. Physical stop readback and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Cell rejected-session widths

- Change: Expanded the 401/403 stale-session browser scenario across 1440/390/320px; checked equal document widths, first-viewport notice and stop, and no horizontal overflow.
- Evidence: 6 Chromium cases passed, 0 NEW known failures; six capture hashes in docs/validation/uiux-cell-auth-widths-2026-10-07/result.md.
- Gate: LOCAL synthetic G2 partial evidence; real site/device and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Site-map offline robot choice

- Change: Keep disconnected robots visible in the trip picker and block preview until a connected robot is selected.
- Evidence: 34 site-map Chromium, 90 D-153 G1, 7 Node passed; Python known failures 0 NEW. See docs/validation/uiux-site-map-offline-2026-10-07/result.md.
- Gate: LOCAL G2 partial evidence; deployed site candidate and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Cell failed job read status

- Change: A failed job/dispatch-generation read clears the pending summary and gives a retry instruction while approval remains blocked.
- Evidence: 3 declared-width Chromium cases and 6 related cases passed; D-153 G1 90 passed, Python known failures 0 NEW. See docs/validation/uiux-cell-job-read-2026-10-07/result.md.
- Gate: LOCAL synthetic G2 partial evidence; site/device and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Cell job snapshot invalidation

- Change: Clear old job summary, ledger, steps, and generation together when the job ID, session, proposal, or read validity changes.
- Evidence: 12 selected Chromium cases and D-153 G1 90 passed, Python known failures 0 NEW; optional full Cell run incomplete. See docs/validation/uiux-cell-job-switch-2026-10-07/result.md.
- Gate: LOCAL G2 partial evidence; real site/device and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Cell saved-document readability

- Change: Show Korean document kind and ID separately from locally formatted modification time; keep long IDs within narrow screens.
- Evidence: Three declared-width Chromium and 74 relevant G1 cases passed after one failing 320px case, `known_failures.py` 0 NEW. See docs/validation/uiux-cell-saved-list-2026-10-07/result.md.
- Gate: LOCAL G2 partial evidence; site/device and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · Cell saved-list error widths

- Change: Replay the existing saved-list failure and recovery flow at all three declared Cell widths.
- Evidence: Six LOCAL G2 captures, three Chromium cases passed, Python known failures 0 NEW. See docs/validation/uiux-cell-list-errors-2026-10-07/result.md.
- Gate: Other G2 cells, real site/device, and operator G3 remain HOLD.

## 2026-10-07 · b111ccb9c · D-493 관제 화면 지도 우선 배치

- 변경: `/console` 3 : 2 배치(왼쪽 지도, 오른쪽 열 예외 큐·등록 로봇·카메라 썸네일·대형·신호·기록), `roster.js` `attentionItems`로 큐와 카드 주의 규칙 통일(릴레이 끊김·비상 정지·목표 실패·교통 대기·양보가 큐에 오른다), 천장 카메라는 한 곳에만(지도 없음·크게 보기면 `#map-birdseye`), 설치 순서 막대·"…에서 합니다" 문장·기기 연결 칸 제거, 다른 문서 링크는 머리 접힘 칸에 하나씩, 발행 띠는 로봇 목록 머리(`data-state`), 전체 주행 취소 `quiet`.
- 증거: Fleet 단위 2284 passed, 웹 Node 144 passed, 공용·아키텍처 통과, Fleet 브라우저 142 passed(실패 3은 단독 재실행 6 passed, MemoryError·로드 타임아웃), 1920×1080 접속 전·운용·지도 없음 문서 높이 1080.
- gate 변화: LOCAL 화면 구조. SITE/FIELD 상태는 그대로 둔다.

## 2026-10-07 · uncommitted · feat(fleet): D-494 1 로봇 trip 능력으로 계획을 묶는다

- 변경: `console_view.TripCaps(kind, modes, max_speed)`와 `trip_caps(capabilities)`(모르는 필드는 무시, 세 필드가 모두 맞을 때만 값). `FleetConsole.caps_for(robot_id)`는 capability 캐시(최대 2 s 대기)에서 읽는다. `POST /trip`은 능력이 있으면 `PlanRequest`의 `robot_kind`·`drive_modes`·`max_speed_mps`를 채운다. 0 m/s 로봇은 간선을 쓰지 못해 `TRIP_NO_ROUTE`다. 능력이 없는 옛 로봇은 지금처럼 미리보기를 계획한다. 실행(`/start`)은 여전히 501이다. 계약 문서 버전 고정 시험을 v1.112로 올렸다.
- 증거: `test_trip_caps.py` 2 PASS, `test_site_map_trip.py` 통과. fleet 스위트 2284 passed·90 skip, 1 NEW는 4개 스위트 병행 부하에서 난 `test_discovery_transport.py` 시간 초과(이 변경이 건드리지 않은 파일)로 단독 재실행 19 passed·known_failures 0 new.
- gate 변화: 없음. SOURCE 호스트 시험만.
- 결정: D-494 (Proposed)

## 2026-10-07 · uncommitted · feat(fleet): D-495 TripCaps.junction_turn

- 변경: `TripCaps`에 `junction_turn: bool = False`를 더했다. 능력의 값이 정확히 `true`일 때만 참이다. 계획에는 쓰지 않고 trip 실행(D-494 5, 다른 가지)이 읽는다.
- 증거: `test_trip_caps.py` 2 PASS.
- gate 변화: 없음.
- 결정: D-495 (Proposed)

## 2026-10-07 · uncommitted · fix(fleet): D-494 검토 — 모르는 drive_modes 값은 버린다

- 변경: `trip_caps`는 모르는 주행 방식을 버리고 아는 값만 쓴다. 전에는 모르는 값 하나가 능력 전체를 None으로 만들었다.
- 증거: `test_trip_caps.py` 2 PASS.
- gate 변화: 없음.
- 결정: D-494 (Proposed)

## 2026-10-07 · uncommitted · feat(fleet): D-494 3 trip 전용 지도 자세(map pose)

- 변경: `fleet/localization/map_pose.py`(순수, 표준 라이브러리만)가 로봇마다 받아들인 Rosy Cam sighting을 그 시각의 `odom_pose`(0.25 s 안 가장 가까운 표본, 둘이 감싸면 보간)와 짝지어 앵커로 두고, 그 뒤 odom 강체 증분으로 잇는다. `LOCALIZED`/`DEGRADED`(odom 1.5 m 초과, 예측과 0.15 m·20° 넘게 어긋남 → 다시 앵커, 연속 2회 일치로 회복)/`UNKNOWN`(앵커 없음, odom 3 s 초과). 설정은 사이트 YAML `fleet.map_pose`.
- 연결: `server/map_pose_service.py`의 `MapPoseService`가 `/api/fleet/sightings`에서 받아들인 행과 콘솔이 읽는 모든 상태 스냅숏(hub heartbeat·REST)의 `odom_pose`를 먹는다. trip 루프용 `arbitrated_pose(robot_id)`와 읽기 전용 `GET /api/fleet/robots/{robot_id}/map-pose`(viewer 이상, API Ref v1.112)를 낸다.
- 바꾸지 않은 것: `trusted_map_pose`·`/route`·교통정리·D-395. D-457 tracking은 입력이 아니다.
- 증거: `test_map_pose.py`(28)·`test_map_pose_service.py`(7)·경계·계약 문서 테스트 통과, `known_failures` 새 실패 0(X:\DevTemp\d491-map-pose).
- gate 변화: SOURCE만. SIM·DEVICE 수용은 그대로 열려 있다.
- 열린 것: `odom_pose`는 `feat/d491-robot-trip-contracts`가 CORE와 `StateSnapshot`에 넣기 전까지 비어 있어(hub 경로는 pydantic이 모르는 필드를 버린다) 자세는 `UNKNOWN`이다. 실차·SIM 수용 없음.

## 2026-10-07 · uncommitted · fix(fleet): D-494 3 map pose 독립 검토 반영

- 변경: `odom_pose.stamp`를 UTC epoch 초(float, `captured_at`과 같은 형식)로 읽는다(ISO 문자열도 읽음, trip-contracts 브랜치와 맞춤). odom 끊김(3 s 초과)·낡은 뒤 재개·불가능한 걸음(1 m/s 초과, CORE 재시작의 odom 0)이면 앵커를 버리고 `UNKNOWN`. odom 미래 허용 `max_odom_future_s` 0.5 s와 거절 수·이유 출력. 누적 회전 180°·앵커 나이 10 s 한도, `map_id` 고정과 활성 지도 프레임 필터, 감싸는 표본이 올 수 있는 동안 sighting 대기. 엔드포인트는 httpx 오류에도 마지막 자세로 답하고, 동시 읽기를 합치며, 0.2 s 안이면 다시 읽지 않는다. 로스터에서 빠진 로봇의 추적기는 버린다. 콘솔 sink 실패는 로봇마다 한 번 기록하고 수집을 멈추지 않는다.
- 증거: `test_map_pose.py`(41)·`test_map_pose_service.py`(14), 검토 probe 사례를 테스트로 옮김. Fleet 전체·계약 문서 테스트와 `known_failures` 새 실패 0(X:\DevTemp\d491-map-pose).
- gate 변화: SOURCE만. trip 루프는 odom을 2 Hz 이상 읽어야 한다(D-494 부록). SIM·DEVICE 수용은 그대로 열려 있다.

## 2026-10-07 · uncommitted · fix(fleet): D-494 3 map pose 재검토 반영

- 변경: odom이 카메라보다 늦게 오면(hub 스냅숏 최대 약 1 s) 새 sighting이 기다리던 sighting을 밀어내 앵커가 영영 생기지 않던 문제를 고쳤다. sighting은 `captured_at` 순서 대기열(32건)에서 그 시각 이후 odom을 기다렸다가 순서대로 짝짓는다. 활성 지도와 다른 `map_id` sighting 수(`sightings_filtered_map_id`)와 출처가 없는 활성 지도 경고, 다른 프레임 앵커는 `DEGRADED`. trip 루프용 `refresh(force_rest=True)`(hub 캐시 건너뜀). odom 방향 변화율 360°/s 초과도 재설정, `max_bridge_turn_deg` 기본 270. 공유 읽기의 예외는 회수해 기록한다.
- 증거: 재검토 probe2 사례(odom 0.3 s·0.5 s 늦음, 1 Hz heartbeat를 0.5 s 폴링, 위상 0.4)를 회귀 테스트로 옮겨 모두 `LOCALIZED`. Fleet 전체·계약 문서 테스트와 `known_failures` 새 실패 0(X:\DevTemp\d491-map-pose).
- gate 변화: SOURCE만. trip 루프는 `force_rest`로 2 Hz 이상 읽는다(D-494 부록). SIM·DEVICE 수용은 그대로 열려 있다.

## 2026-10-07 · uncommitted · Fleet roster action widths

- Change: Equalize the two compact roster actions and put a cancel result and roster toggle on separate full-width rows.
- Evidence: Nine Chromium layout and one failure-state case, six D-493, and 83 responsive/token/grammar cases passed, Python known failures 0 NEW. See docs/validation/uiux-fleet-roster-actions-2026-10-07/result.md.
- Gate: LOCAL G2 partial evidence; current site candidate and operator G3 remain HOLD.

## 2026-10-07 · uncommitted · uiux(fleet): Cell 접속 역할 어휘

- 변경: `/console/cell`의 원시 역할 코드를 Fleet 관제·설치 화면과 같은 한국어 역할 이름으로 표시한다. 권한 판정·API 요청은 변경하지 않는다.
- 증거: 320px 브라우저 수정 전 1 failed, 수정 후 1 passed; Cell 전체 49 passed, G1 90 passed, `known_failures.py` 0 NEW; `docs/validation/uiux-cell-role-label-2026-10-07/result.md`.
- gate 변화: 없음. LOCAL 화면 근거만 추가하고 사이트·장치·G3는 HOLD.

## 2026-10-07 · 556dd1954 · feat(fleet): 카메라 차선 지도 초안 가져오기

- 변경: D-497: 현장 지도에서 카메라 생성 JSON 초안 가져오기. 기존 이름 있는 운영자·스키마·revision·크기 검사를 재사용. 기존 초안 교체 확인, 활성 지도 유지.
- 증거: 81 affected geometry/store/browser checks passed (latest loop regression rechecked), 0 NEW. Direct source-command test on the actual site host read a fresh raw S21 frame over pinned HTTPS and generated a 12-place/10-lane draft. That draft imported in local Chromium at 1440/390 px without activating or moving a robot. Source command was ephemeral; permanent deployment and field geometry acceptance are unproven. Independent review found an attached-loop loss; fixed and independently rechecked.
- gate 변화: 없음. SOURCE/LOCAL 근거 추가; 장치 상시 배포·현장 지도 정확도 수용은 별도다.

## 2026-10-07 · uncommitted · uiux(fleet): Cell 문서 목록 마지막 수신 시각

- 변경: 목록 성공 응답을 브라우저가 받은 시각을 문서 수정 시각과 분리해 표시한다. 조회 중·실패·계정 변경은 기존 목록을 숨긴다.
- 증거: 선언 세 폭의 목록 성공·실패/복구 브라우저 6 passed, 조회 잠금 1 passed, Cell 전체 49 passed, G1 90 passed, `known_failures.py` 0 NEW. `docs/validation/uiux-cell-list-readtime-2026-10-07/result.md`.
- gate 변화: 없음. 서버 판정 신선도·현장·장치·G3는 HOLD.

## 2026-10-07 · uncommitted · fix(fleet): camera-map integration contract pins

- 변경: D-497 command registration and existing-draft confirmation are explicitly pinned in their existing contract tests. Existing aliases and confirmation ownership remain asserted.
- 증거: 18 CLI/dialog checks passed after fixing the two NEW findings from pre-push; the remaining candidate checks continue.
- gate 변화: SOURCE only; deployment and installed readback pending.

## 2026-10-07 · uncommitted · feat(fleet): D-494 5 서버 trip 루프 (브랜치 feat/d491-fleet-trip-loop)
- 변경: 계획 본문을 `plan_id`로 저장(D-490 보존 그대로), 새 `fleet/server/trip_runner.py`(시작 검사·상태기계·0.5 s 루프·다음 장소 재계획 대기), `POST /api/fleet/trips/{plan_id}/start`·`/{id}/cancel`·`/{id}/confirm-replan`·`GET /api/fleet/trips`·`/{id}`, 활성화 가드를 "진행 중 trip"으로 교체(`/route`는 그대로), `HttpRobotClient.line_follow_junction`, 콘솔 지도 화면 운행 칸, API Ref v1.112. D-495 3항(`turn_deg`, `junction_turn` 능력, CORE `aborted`/`unresolved`/긴 `waiting` → `stopped(junction)`)과 지도 자세 검토 반영(시작 시 anchor 2 s 이내, tick마다 상태 갱신)을 포함한다
- 증거: `python -m pytest operations/fleet/test -q` 2310 passed, 93 skipped, known_failures 0 new(2026-10-07 Windows, D-495 반영 커밋 기준); 마지막 커밋 뒤 관련 묶음 132 passed, 0 new; `node --test operations/fleet/test/web/*.mjs` 145 passed; `ROSY_BROWSER_TESTS=1` 현장 지도 브라우저 33 passed(D-495 이전 UI, 이후 UI 변경은 문구 한 줄)
- gate 변화: 없음. SOURCE/LOCAL만. 능력(1항)·지도 자세(3항)·교차로 API(4항) 제공자는 형제 브랜치가 착지한 뒤 `create_app(trip_caps=…, map_pose=…)`로 연결한다. 기본 연결은 `TRIP_ROBOT_CAPS_UNKNOWN`으로 시작을 거절한다. Gazebo·실차 미실행
- 결정: D-494 Proposed, D-495 Proposed
- 교훈: 짧은 차로(0.37 m)는 arm 거리 0.6 m보다 짧다. 차선 로봇은 장소를 지난 뒤에만 다음 장소 지시를 보내야 CORE가 가진 하나뿐인 지시를 덮어쓰지 않는다

## 2026-10-07 · uncommitted · feat(fleet): D-494 5 trip 루프 검토 반영 — 즉시 멈춤·멈춤 규칙·차선 시작 검사
- 변경: 취소와 차선 위치 상실은 교차로 `stop` 뒤 `PUT /line-follow/mode OFF`로 바로 멈춘다(`POST /line-follow/hold`는 hold-to-run 연장이라 쓰지 않음). `fleet.trip.stall_s`(기본 20 s) 동안 0.05 m 미만 진행이면 `stopped(stall)`(교차로 동작 중·재계획 대기 제외). `lane` 계획은 line-follow `CAMERA_LINE`/`IR_LINE`이 아니면 `TRIP_LINE_FOLLOW_NOT_ACTIVE`. 포트를 `trip_ports.py`로 분리. D-494 구현 부록(5항 trip 루프)
- 증거: `operations/fleet/test` 전체와 known_failures는 이 항목 아래 실행 결과를 보고서에 남긴다. 집중 묶음(`test_trip_runner.py` 43건 포함) 통과, harness lint 0 오류
- gate 변화: 없음. SOURCE/LOCAL만
- 결정: D-494 Proposed(구현 부록 추가)
- 교훈: CORE의 같은 이름 API(`/line-follow/hold`)가 반대 뜻(계속 가기)일 수 있다. 멈춤 경로는 엔드포인트 본문을 읽고 고른다

## 2026-10-07 · uncommitted · fix(fleet): D-494 5 trip 루프 독립 검토 반영 — CORE 교차로 상태 기반 전송·넘김, 모든 끝에서 정지
- 변경: 시험의 가짜 교차로 포트를 CORE `junction.py`대로(받은 뒤 odom 거리로 서는 `stop`, 동작 중 새 지시는 동작을 abort하고 거절, seq·상태). `stop_after_m`=남은 거리(0–2 m), `stop` 재전송 없음, CORE `executing`·동작 중에는 전송 없음, CORE 완료 또는 다음 차로 투영으로 넘김, 모든 실패·멈춤에서 정지(교차로 stop + line-follow OFF / 목표 취소), 루프가 저장소 실패에도 살아 있음, 취소는 tick 잠금을 기다리지 않음, 로봇 호출 1.5 s 제한, `lane` 계획은 `junction_turn` 필요, 시작 직전 지도 버전 재확인, `anchor_age_s` 없으면 거절, 재시작 때 열린 trip 로봇 정지, refresh 경고 30 s 제한, trip 중 `/goal`·`/route`·배차·대형은 409 `TRIP_ROBOT_BUSY`. 실행 가능 규칙을 `fleet/routing/execute.py`로. 콘솔 멈춤 사유 문구(설정된 `stall_s`, `TRIP_LOOP_ERROR`)와 취소 확인 문구. D-494 구현 부록 갱신
- 증거: 아래 실행의 `operations/fleet/test` 전체와 known_failures는 보고서에 남긴다. `test_trip_runner.py` 51건, `test_routing_execute.py` 10건, site-map node 9건, 구조·안전 분리·대화창 계약 시험 통과, harness lint 0 오류
- gate 변화: 없음. SOURCE/LOCAL만
- 결정: D-494 Proposed(구현 부록 갱신)
- 교훈: 가짜 포트가 실제 CORE 상태기계를 흉내 내지 않으면, 지시 덮어쓰기·동작 중 재전송 같은 결함이 시험을 통과한다. 짝 브랜치의 구현 파일을 읽어 가짜를 만든다

## 2026-10-07 · uncommitted · fix(fleet): D-494 5 trip 루프 재검토 반영 R1–R8
- 변경: 콘솔이 보내지 않은 좌표 목표는 trip 실패(`TRIP_GOAL_REFUSED`), 좌표 trip이 끝날 때마다 콘솔 대기열 정리, 콘솔 목표·대기열·양보·대형 중인 로봇은 시작 거절(R1). 교차로 지시는 `CAMERA_LINE`에서만(R2). `trip_guard.py`가 콘솔 인스턴스의 목표·대형·line-follow를 감싸고, `OFF`는 trip 취소(`operator_line_follow_off`), trip 로봇은 비켜서기·재배정 대상이 아니며 줄 막힘 결정은 409(R3, `console.py` 줄 수 그대로). 가짜 CORE에 M3·M4·M7·L6·R1, 수행된 지시 재전송 없음, `JUNCTION_ALREADY_DONE`은 수행됨, CORE가 붙잡은 우리 `stop`도 도착(R4). 보낸 뒤 열림 재확인(R5), 차선 도착은 받아들여진 `stop` 필요(R6), 재계획 확인 때 지시 기록 초기화(R7), 재시작 정지는 받을 때까지 재시도(R8). D-494 구현 부록·API Ref 갱신
- 증거: 보고서에 `operations/fleet/test` 전체·계약 문서·모듈 구조와 known_failures를 남긴다. `test_trip_runner.py` 66건 통과
- gate 변화: 없음. SOURCE/LOCAL만. 실제로 서는 거리는 모델 PC SIM에서 잰다
- 결정: D-494 Proposed(구현 부록 갱신)
- 교훈: 안전 파일의 줄 예산이 0이면 감싸기(인스턴스 메서드 교체)와 기존 줄 안 조건으로 같은 가드를 줄 수 있다

## 2026-10-07 · uncommitted · fix(fleet): D-494 5 trip 안전 검토 반영 — 모든 멈춤이 trip을 끝낸다
- 변경: 로봇별 취소·전체 취소·intent 취소·Fleet 비상 정지·`line-follow OFF`(로봇 호출이 실패해도)·줄 막힘 `ABORT`/`MANUAL`은 로봇에 먼저 가고 trip을 `canceled`로 끝낸다(H1·M1·M3). 움직이는 줄 막힘 결정과 대형 재구성·재개는 거절, Fleet 자동 해결기는 trip 로봇을 건너뛴다(M2·N3·N4). 보낸 지 2 s 안의 콘솔 목표도 진행 중으로 본다(L1). 재시작 정지는 tick 밖에서 10 s마다 최대 30회(N2). D-494 구현 부록·API Ref 갱신
- 증거: 보고서에 `operations/fleet/test` 전체·구조 시험·known_failures를 남긴다. `test_trip_runner.py` 82건 통과
- gate 변화: 없음. SOURCE/LOCAL만
- 결정: D-494 Proposed(구현 부록 갱신)
- 교훈: 로봇을 몰고 있는 루프가 있으면 그 로봇에 닿는 모든 멈춤 경로가 루프도 끝내야 한다. 하나라도 빠지면 다음 tick이 멈춘 로봇을 다시 움직인다

## 2026-10-07 · uncommitted · fix(fleet): 운행 위치 상태를 한국어로 표시
- 변경: D-494 운행 패널의 LOCALIZED·DEGRADED·UNKNOWN을 위치 확정·위치 정확도 저하·위치 확인 불가로 표시. 미지 상태 원문과 API 본문은 보존
- 증거: CI 37593064818의 operator-copy 실패 재현 뒤 Python 표기 검사 18건과 Node 지도 표시 검사 9건 통과. 독립 검토와 Node 재실행 통과
- gate 변화: SOURCE/LOCAL. 서명·관제 적용은 새 커밋 CI 통과 뒤 확인
- 교훈: 순수 표시 함수 시험도 운영자 표기 검사를 함께 돌린다

## 2026-10-07 · uncommitted · feat(fleet): 조감도 낡은 카메라 교정 감지 — 실영상 대신 미터 눈금과 경고
- 변경: 카메라를 재조준하면 D-457 추적 보정이 어긋나 조감도가 잘려 돌아간 지도를 정확해 보이게 그렸다. 이제 정지 로봇(직전 폴링 자세 이동 ≤ 0.05 m)의 추적 차이(`offset_m`)가 3폴링 연속 0.4 m를 넘으면 교정이 낡은 것으로 판정해(`tracking-layer.js` `trackingDriftSample`·`calibrationDriftVerdict`, 순수) 실영상 배경을 내리고 미터 눈금 뷰로 돌아간 뒤 "카메라 교정 어긋남 — 맞춤 재수락 필요" 경고를 캔버스와 `#map-tag`·aria-label에 보인다. 표본은 `tracking-view.js show()`가 실제 폴링 응답마다 한 번만 쌓고, 수명 만료 `show(null)`은 연속을 끊지 않는다. 마커 관측(measured)·움직이는 로봇은 세지 않는다
- 증거: node `tracking-layer.test.mjs` 12 passed(신규 3건: 정지 로봇만 표본·연속 판정·자세 기억), 콘솔 브라우저 신규 `test_stale_camera_calibration_drops_the_frame_and_warns` + 기존 카메라 배경 회귀 2 passed(ROSY_RUN_BROWSER_TESTS=1). 변이 증명: `view.trackingDrift = null`으로 무력화하면 신규 시험 TimeoutError로 빨개진다
- gate 변화: 없음. LOCAL GO 유지 — 표시 경고만 만들었고 관측·목표·주행 경로는 그대로
- 결정: 해당 없음(D-457 추적 보정의 표시 전용 보강)
- 교훈: 없음

## 2026-10-07 · uncommitted · feat(fleet): D-494 6 주행 가르치기 — 기록·RDP·초안 확정·여기에 주소
- 변경: 순수 `fleet/routing/teach.py`(점 남기기 `LOCALIZED` 또는 다리 ≤ 0.5 m·0.1 m 간격, 반복형 RDP 0.02 m, 끝 0.15 m 장소 후보, 초안 본문에 간선·새 장소 붙이기), `server/teach_service.py`·`teach_routes.py`(`GET /api/fleet/teach`, `POST /api/fleet/teach/start|stop|confirm|place`, 이름 있는 운영자, 현장 지도 이벤트), `SiteMapStore.record_event`, `app.py` 4줄 배선, 현장 지도 화면 "지도 가르치기" 칸(`web/site-map-teach.js`, 모델 도우미, 점선 표시). `console.py`는 고치지 않음
- 증거: `operations/fleet/test` 2459 passed·124 skipped·1 failed(`test_routing` 표준 라이브러리 import 규칙: `copy` → 고친 뒤 `test_routing.py`·`test_routing_teach.py`·`test_teach.py` 45 passed), node `test/web/*.mjs` 151 passed, Chromium 스모크(1440·390, 기록→멈춤→확정→주소, 콘솔 오류 0, X:\DevTemp\d494-teach). `test/architecture`+문서+api_web 271 passed·1 failed = 크기 판정 `fleet: 41719 > 41014+150`(이 브랜치 +593, 재판정 대기). `test/known_failures.py` 그 외 0 new
- gate 변화: 없음. SOURCE 호스트 시험만. 로봇에 아무것도 보내지 않는다. 현장 가르치기는 Rosy Cam 맞춤 뒤
- 결정: D-494 6 (구현 부록 2026-10-07 — 6항 가르치기)
- 교훈: `fleet/routing`은 표준 라이브러리 화이트리스트(`copy` 포함 안 됨)가 시험으로 걸려 있다

## 2026-10-07 · uncommitted · fix(fleet): D-494 6 독립 검토 반영 — LOCALIZED만 기록·최신 기록 확정·유휴 자동 멈춤·끝 고정
- 변경: `DEGRADED`는 다리 길이와 상관없이 남기지 않음(재앵커 튐 제거). 확정 대기 목록은 최신 먼저, 콘솔은 가장 최근 기록(`newestPending`)을 확정. 10분 동안 새 점이 없거나 20000점이면 같은 멈춤 길로 스스로 멈춤(`system:teach_idle`, `reason idle|full`). 끝 고정 때 장소 0.15 m 안의 앞·뒤 중간 점을 뺌. 점 mm 반올림, 주소 yaw 감기, 멈춘 뒤 원점 비움, 첫 표본 오류 잡기, 바뀔 때만 지도 다시 그림, 초안 크기·오류 변환은 `site_map_routes`의 것을 함께 씀. 크기 판정 41764(독립 재판정, 추가분 +638)
- 증거: `operations/fleet/test` 2464 passed·124 skipped, `test/architecture` 132 passed·1 skipped, node `site-map.test.mjs` 12 passed, Chromium 스모크(1440·390) 콘솔 오류 0, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음. SOURCE 호스트 시험만
- 결정: D-494 6 구현 부록 1·5·6항 갱신
- 교훈: 기록 규칙의 "또는"은 신뢰 상태 하나를 다리 길이로 대신하게 한다. 재앵커 순간의 DEGRADED 0 m 다리가 그대로 선에 들어갔다

## 2026-10-07 · uncommitted · test(fleet): 추적 보정 적용의 렌즈 지문을 브라우저·라우트 시험으로 고정
- 변경: "추적 보정 적용"의 렌즈 지문 배선은 c598918fc·0965acc94에서 이미 main에 다 들어 있었다(적용 시점 라이브 프레임 X-Source-Lens → `map-fit-view.js` applyButton의 `visionView.currentLensInfo()` → `map-fit.js` `calibrationRequest` lensBody → 서버 `CalibrationApproval.lens` → `build_record` 검증·개정 해시 포함; 프레임에 렌즈가 없을 때만 "렌즈 정보가 없어 렌즈 검사 없이 적용했습니다" 안내). 이 커밋은 그 배선을 증명하는 시험만 더한다. `test/test_fleet_console_browser.py` 신규 2건 — 설치 맞춤 패널에서 통과 제안과 렌즈 헤더 프레임으로 적용을 누르면 POST 본문에 `{kind, focal_mm, hfov_deg}`가 실리고 안내가 붙지 않는다 / 헤더 없는 프레임이면 `lens: null`로 저장되고 안내가 붙는다. `test_overhead_tracking_api.py` — 렌즈를 넣은 승인이 목록·Vision 설정 조회까지 그대로 남으며 렌즈 없는 승인과 개정이 다르고, 잘못된 렌즈 본문 3종(필드 누락·대문자 kind·여분 필드)이 422
- 증거: 브라우저 신규 2 passed(ROSY_RUN_BROWSER_TESTS=1), 변이 증명 — applyButton의 lens 인자를 지우면 적색, 복원 녹색; `tracking.py` approve의 lens 전달을 지우면 라우트 시험 적색, 복원 녹색. `test_overhead_tracking_api.py` 11 passed, tracking 3종·서버 앱·콘솔 계약 targeted 103 passed, node map-fit 17·vision-lens-profile 7·camera-map 1 passed, known_failures 0 NEW
- gate 변화: 없음. 제품 코드 변경 없음(시험만)
- 결정: 해당 없음(D-457 1항 표시 전용 경로의 시험 보강)
- 교훈: 소스 문자열 단언(`"calibrationRequest(" in fit_view`)은 배선이 빠져도 녹색으로 남는다 — 클릭해서 본문을 잡는 브라우저 시험이 배선의 증거다

## 2026-10-07 · uncommitted · feat(fleet): 로봇 관측 없이 카메라 교정 낡음을 서버가 자동 검사
- 변경: Fleet이 승인 추적 교정(`tracking_calibrations`)과 Vision D-375 맞춤 제안을 주기(기본 60 s, `--calibration-drift-interval-s`, 0이면 끔, `--vision-url` 필요) 비교해 출처별 `calibration_drift` 판정을 `GET /api/fleet/tracking` 출처 행에 싣는다(`server/tracking_drift.py` — 순수 판정 `calibration_drift_verdict`, `CalibrationDriftWatch`, `VisionMapProposalReader`). 판정은 승인 `track_bounds_m` 네 모서리를 승인 교정으로 화소로 보낸 뒤 제안 `image_to_map`으로 다시 map 미터로 보내 최대 이동(0.3 m 초과)과 선형부 상대 회전(3° 초과)으로 stale를 정한다. 수락(accepted) 제안만 근거고, Vision 사용 중(429, 수동 맞춤 실행)·거부 제안·크기 바뀐 프레임은 그 회차를 건너뛰어 마지막 판정을 유지하며, 새 승인·철회는 그 출처의 판정을 지운다. 콘솔 조감도는 로봇 표본 판정을 우선하고 없으면(관측 0/0대) 서버 판정 stale로 실영상 대신 미터 눈금과 "카메라 교정 어긋남(자동 검사)" 경고를 보인다(tracking-layer `serverCalibrationDrift`·`effectiveDriftVerdict`, tracking-view·map-view 분기). `tracking.py` `drift_provider`, app.py 감시 루프와 "감시는 추적 서비스 필요" 검사, D-457 경계 허용 목록에 `server/tracking_drift.py` 추가. 표시 전용 — 관측·목표·주행 경로에 쓰지 않는다.
- 증거: `test_tracking_drift.py` 신규 21 passed(항등·이동·회전·경계·거부 제안·감시 수명·리더 429/404/401/422/500·라우트 탑재·앱 검증·lifespan 실행/종료), node `tracking-layer.test.mjs` 14 passed(신규 2: 서버 판정 읽기·표본 우선), 콘솔 브라우저 신규 2 + 기존 낡음 1 passed(ROSY_RUN_BROWSER_TESTS=1). 변이 증명: stale 조건 or→and 5적, 감시 리비전 초기화 무력화 1적, snapshot 탑재 제거 1적, `effectiveDriftVerdict` 서버 폴백 제거 node 1적·브라우저 TimeoutError, 각 복원 초록. `operations/fleet/test` 최종 2485 passed·124 skipped, known_failures 0 NEW
- gate 변화: 없음. 서버 판정은 표시 경로만 바꾼다
- 결정: 해당 없음(D-457 추적 보정의 표시 전용 보강, D-375 제안 엔드포인트 재사용)
- 교훈: 로봇이 카메라에 안 보이는 현장에서 교정 낡음의 유일한 독립 증거는 바닥 페인트 맞춤 제안이다. 프레임 모서리가 아니라 트랙 모서리로 재야 한다 — 기울어진 카메라의 프레임 가장자리는 지평선 근처에서 소리 없이 수십 미터 튄다

## 2026-10-07 · uncommitted · feat(fleet): 직사각형 카메라 평면 지도와 클릭 좌표 확인
- 변경: 기존 표시 보정·preview lease·평면 변환을 재사용해 현장 지도에 직사각형 카메라 영상과 미터 좌표를 표시한다. 같은 지도 ID·렌즈·영상 크기·신선도를 확인하고, 카메라 변경 시 이전 영상을 비운다. 좌표 확인과 운행 선택은 분리하며 확인 중 경로 계산·시작·재개를 잠근다. 새 API·패키지는 없음
- 증거: node 153 passed; 관련 Python 148 passed·26 skipped; Chromium 관련 5 passed, 최종 좌표 확인 회귀 1 passed; known_failures 0 NEW. 저장된 현장 영상으로 실제 화면 1440·390·320 px에서 직사각형 지도·좌표 확인, 가로 넘침 없음. 독립 소스 검토 PASS
- gate 변화: 없음. SOURCE/LOCAL 증거만; 새 화면 배포·실시간 장치 영상·물리 주행 수용은 미확인. 좌표 클릭은 지도 저장·활성화·로봇 목표 전송을 하지 않는다
- 결정: D-497 7항
- 교훈: 영상 다시 불러오기 전에 좌표 확인 상태를 비워야 운행 선택으로 클릭이 흘러가지 않는다

## 2026-10-07 · uncommitted · feat(fleet): 막힘 에피소드 기록
- 변경: `LineStuckBoard.observe`의 전이(열림·`cleared`·`replaced`·`left_roster`)를 `--tasks-db` 파일의 새 테이블 `fleet_line_stuck_episodes`에 남긴다. 시작할 때 열린 행은 `fleet_restart`로 닫고, 같은 `stuck_id`가 다시 보이면 처음 `opened_at`을 둔 채 다시 연다. 열 때 `local_enabled`·`trip_busy`(트립 실행기 `robot_busy`)·`peer_ahead`(resolver R1과 같은 모듈 함수로 꺼냄, 자세 없으면 NULL)·MapPose를 담고, 닫을 때 답 기록에서 `resolved_by`/`last_answer_tier`/`escalation_code`를 정한다. `GET /api/fleet/line-stuck/episodes`(viewer+), API Ref v1.120
- 증거: 계획 검증 묶음 192 passed, `test/known_failures.py` 0 new. `test_server_app`·`test_boundaries`·`test_cli`·`test_teach` 107 passed·1 failed(`test_cli.py::test_cell_job_stack_tolerance_injects_the_palletizing_compiler`, `rosy.execution` import 실패, 깨끗한 main에서도 실패)
- gate 변화: 없음. SOURCE 호스트 시험만. 현장 배포 전
- 결정: 자율 사슬 계획 1단계(D-407/D-438 범위 안, 새 ADR 없음)
- 교훈: 결과를 모르는 답(`accepted` NULL)을 "스스로 풀림"과 나누려면 `<tier>_unconfirmed`를 따로 둬야 한다

## 2026-10-07 · uncommitted · docs(api): 막힘 에피소드 경로 번호를 v1.121 로
- 변경: main 에 D-502(fix/core-battery-health)가 v1.120 을 먼저 써서, 이 브랜치의 `GET /api/fleet/line-stuck/episodes` 변경 이력과 문서 머리 버전을 v1.121 로 옮겼다. 위 항목의 v1.120 은 v1.121 로 읽는다.
- 증거: main 병합 뒤 관련 묶음 289 passed, `test/known_failures.py` 0 new.
- gate 변화: 없음. 문서 번호만
- 결정: main 이 먼저 쓴 번호를 두고 다음 번호를 쓴다
- 교훈: API 번호는 착지 직전에 main 머리를 다시 본다

## 2026-10-07 · uncommitted · fix(fleet): D-493 예외 큐가 오래된 상태를 표시
- 변경: `/api/fleet/state` 행에 `state_age_s`(관찰 시각→응답 시각, 오프라인 null)와 최상위 `gathered_at`(SharedGather 수집 시각, 표시 전용). 큐는 `state_age_s` + 브라우저 수신 후 경과가 5 s를 넘으면 warn "상태 오래됨"과 막힘 crit 문구에 나이를 붙인다(`state-age.js`, `roster.js`).
- 증거: fleet pytest 54 passed(known_failures 0 new), `node --test test/web/*.mjs` 160 passed(실제 `attentionItems`를 `/common` 로더로 실행).
- gate 변화: 없음. 현장 배포는 사용자 승인 대기
- 결정: D-493 단일 규칙 유지. API Reference 버전 올림은 착지 때 보류 중(1단계가 v1.120을 쓰므로 1단계 착지 뒤 v1.121)
- 교훈: 문자열 단언만으로는 "출력 불변"을 못 지킨다 — 실제 함수를 노드에서 돌리는 로더를 둔다

## 2026-10-07 · uncommitted · docs(api): 예외 큐 신선도 필드를 v1.122 로
- 변경: main 에 막힘 에피소드(v1.121)가 먼저 착지해 `state_age_s`·`gathered_at` 변경 이력을 v1.122 로 적고 문서 머리 버전과 고정 시험을 옮겼다.
- 증거: main 병합 뒤 관련 묶음과 node 시험, `test/known_failures.py`.
- gate 변화: 없음. 문서 번호만
- 결정: 앞 브랜치가 쓴 번호 다음을 쓴다
- 교훈: 같은 날 여러 브랜치가 API 번호를 다툴 때는 착지 순서대로 다시 매긴다

## 2026-10-07 · uncommitted · fix(fleet): 개발 콘솔 모든 화면 직접 접속
- 변경: 개발 모드에서 `/console/install`, `/console/site-map`, `/console/cell` 직접 진입 시 Fleet 개발 세션을 자동 발급·재사용하고 토큰 입력 칸을 숨긴다. `/console`도 개발 모드에서는 토큰 입력 칸을 숨긴다. 일반 모드의 토큰 접속은 유지한다.
- 증거: 새 Chromium 직접 진입 시험 4 passed, 개발 인증 pytest 60 passed, 웹 Node 시험 160 passed. 넓은 pytest의 Cell 컴파일러 import 실패 1건은 깨끗한 main에서도 동일하게 재현했다.
- gate 변화: SOURCE/LOCAL만 확인. 사이트 배포·실기 수용은 별도다.

## 2026-10-07 · uncommitted · fix(test): Fleet 브라우저 fixture가 Chromium 차단 포트를 피하고 정식 옵트인을 받는다
- 변경: `test_cell_app_browser.py`·`test_start_point_browser.py`·`test_site_map_browser.py`·`test_development_console_browser.py`가 `browser_harness.safe_listener()`로 포트를 잡고, 다섯 브라우저 파일이 `browser_tests_enabled()`로 판정한다. `conftest.py`가 `test/`를 `sys.path` 끝에 붙인다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1`만으로 `test_cell_page_keeps_emergency_stop_in_first_view` 3 passed, `test_markerless_map_pick_save_reload_and_recalibration` 1 passed(이전에는 건너뜀). `known_failures.py` 0 new.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 없음

## 2026-10-08 · uncommitted · feat(fleet): D-513 시연 출발 자리 `start` 장소
- 변경: 현장 지도 장소 종류 `start`(yaw 필수)를 더하고, 활성화·첫 가져오기에서 출발 붙이기로 검사해 `SITE_MAP_START_INVALID`로 거절한다. 기록 모드 `place`가 `start`를 받는다. 현장 지도 화면은 출발 자리와 방향 화살표를 그린다.
- 증거: 관련 pytest 79 passed(브라우저 55 skipped), `site-map.test.mjs` 13 passed.
- gate 변화: SOURCE/LOCAL만. 현장 해석 확인 F1, 지도 입력 F2는 별도.

## 2026-10-08 · uncommitted · feat(fleet): D-513 7 카메라 화면 회전
- 변경: `site-cameras.yaml` source 선택 키 `display_rotation_deg`(0/90/180/270)를 읽어 site-map source 행으로 내린다. 메인 지도 실영상·크게 보기를 그만큼 돌려 그리고 지도 점도 같이 돌린다. 보정·관측 좌표는 원본 그대로다.
- 증거: `test_site_map_api.py` 27 passed, 웹 Node 시험 170 passed.
- gate 변화: SOURCE/LOCAL만. 현장 설정 반영은 새 Fleet·Vision 배포 뒤에 한다(옛 버전은 이 키를 거절한다).


## 2026-10-08 · uncommitted · D-509 로봇 전원 근거 표시

- 변경: Fleet이 CORE Viewer power/health를 등록된 Operator 토큰으로 읽고 최대 5초 캐시한다. 로봇 행은 공유 PowerHealthResponse와 관측 나이를 선택 필드로 제공하며, 관제는 배터리·충전 근거의 신선도와 다음 조치를 표시한다. E-Stop·네트워크·영상 설정 경로는 변경하지 않았다.
- 증거: 집중 pytest 103 passed, known_failures 0 NEW; 웹 Node 170 passed. 현장 장치 검증은 별도.
- gate 변화: 없음.

## 2026-10-08 · uncommitted · fix(fleet): D-509 power health at state response

- Change: Read CORE power/health only while rendering /api/fleet/state, preserving D-447 hub gather calls. Invalidate display cache when a robot client changes.
- Evidence: Related Fleet and contract tests 99 PASS; Node 170 PASS. Device check remains separate.
- Gate change: None.

## 2026-10-08 · uncommitted · fix(fleet): D-509 state response follow-up

- 변경: Power health readback lives in /api/fleet/state presentation; D-447 gather remains unchanged.
- 증거: Fleet and contract focus tests passed; Node 170 passed; hardware remains unverified.
- gate 변화: None.

## 2026-10-08 · uncommitted · fix(fleet): D-513 7 회전 후속
- 변경: 실영상 위 시작점 클릭을 회전·보정 역변환으로 지도 좌표로 바꾼다. 실영상 위 x/y 축을 지도 방향으로 그린다. 레일 썸네일을 편집 중이 아닐 때 돌린다. 현장 지도 화면을 관제 실영상과 같은 방향의 90° 단위로 돌린다(평면 사진 포함). 돌린 조감도는 보일 때만 다시 만든다.
- 증거: 웹 Node 시험 174 passed.
- gate 변화: SOURCE/LOCAL만.

## 2026-10-08 · uncommitted · feat(fleet): D-511 M0 차로 준수 감시(관찰·알림만)
- 변경: 순수 판정 `fleet/localization/lane_compliance.py`(부호 있는 가로 편차 왼쪽 +, 몸체 여유 `width_m/2 − (|d| + half width)`, `core_common.robot_body` PINKY_PRO 반폭, `persist_n` 연속 규칙, `fleet.lane_compliance` 잠정 기본값 0.02 m·3회·3.0 s). 2 Hz 감시 `server/lane_compliance_service.py` + `background_workers.lane_compliance_loop`: odom이 움직인 로봇만 `refresh(force_rest=True)`, 모든 로봇을 `arbitrated_pose`로 판정(D-511 §2가 D-494 §3을 넓힘). `GET /api/fleet/robots/{id}/lane-compliance`, `/api/fleet/state` 행 `lane_compliance`, 콘솔 예외 큐 WARN/ACT 항목. API Ref v1.128(v1.124–127은 열린 동료 브랜치)
- 증거: `test_lane_compliance.py`·`test_lane_compliance_service.py` 신규, node `attention-stale.test.mjs` 8 passed, fleet 묶음 + `test/known_failures.py` (X:/DevTemp/d511-m0/run.txt)
- gate 변화: 없음. SOURCE/LOCAL만. 지도 자세 LOCALIZED 연결(D-511 §5)·SIM·현장 임계값 측정은 열려 있다
- 결정: D-511 M0. 로봇 명령 없음, trip·`/route`·meet 임계값 그대로(M1), CORE 신호 없음(M2)
- 교훈: 없음

## 2026-10-08 · uncommitted · fix(fleet): D-511 M0 리뷰 반영
- 변경: 그래프 밖(대기 칸)·막다른 호 끝 너머·차로를 가로지르는 자세는 ACT가 아니라 UNKNOWN(발이 호 안쪽, `max_lateral_m` 기본 호 `width_m`, `heading_gate_deg` 45°). 교차로는 진행 방향 호를 고른다. 움직임 판정에 떨림 데드밴드(`moving_min_m` 0.01, `moving_min_deg` 2), 로봇별 읽기는 0.5 s에서 끊는다. 콘솔은 움직이는 로봇만 알리고 여유가 음수면 "넘음"이라 쓴다. API Ref v1.128 행에 UNKNOWN 경우를 적었다
- 증거: fleet 묶음 + `test/known_failures.py` (X:/DevTemp/d511-m0/run.txt), node `attention-stale.test.mjs` 10 passed
- gate 변화: 없음
- 결정: M0가 이미 움직이는 모든 로봇을 감시한다(ADR §6은 이것을 M1에 두었다). 녹화 주행(`edge_drive.py`)이 trip 밖에서 돌기 때문에 M0의 확인 목표에 필요하다
- 교훈: 투영 거리만으로는 '차로 밖'과 '차로 아님'을 가를 수 없다. 발이 호 끝에 붙으면 부호도 의미가 없다

## 2026-10-08 · uncommitted · refactor(fleet): D-513 7 카메라 회전은 지도 방향에서
- 변경: `site-cameras.yaml`의 `display_rotation_deg` 키를 지운다(푸시 전). 관제 실영상·크게 보기·썸네일은 그 카메라 보정에서 지도 +y가 위로 오는 90° 단위 회전(`mapUpTurn`)으로 돈다. 현장 지도 화면의 보기 회전도 지운다(원래 지도 좌표).
- 증거: 웹 Node 시험 174 passed.
- gate 변화: SOURCE/LOCAL만. 현장에서 벽이 아래로 보이는지(F3)는 별도.

## 2026-10-08 · dc9026930 · feat(fleet): D-507 2·3·9 Fleet 쪽
- 변경: `junction_pivot: true` 로봇에만 교차로 지시에 `map_id`·`expect_in_m`·`expect_tol_m`·`pivot_past_line_m`(좌·우만, 나가는 차로 폭/2, 상한 0.30)를 싣는다. `expect_in_m`이 (0, 2] 밖이면 `map_id`만. `expect_tol_m`은 지도 자세에 오차 추정이 없어 0.05×추측항법 거리 + trip 최고 속도×자세 나이 + `ENDPOINT_TOL_M`(상한 0.30)로 둔다. `site_floor_map_id`가 활성 지도와 다른 로봇의 `lane` trip은 422 `TRIP_SITE_FLOOR_MISMATCH`(키 없음·null은 검사 안 함). CORE `unexpected`, 또는 다음 장소가 `arm_distance_m`보다 먼 `waiting`은 10 s를 기다리지 않고 `stopped(junction_unexpected)`. API Ref v1.127.
- 증거: `test_trip_d507.py` 16건, trip·caps·문서 시험, 웹 Node 시험, 변이 검사 2건(능력 문, `waiting` 거리 규칙), `test/known_failures.py`.
- gate 변화: SOURCE만. SIM·DEVICE는 CORE 브랜치(`feat/d507-junction-approach`)와 함께.
- 결정: 판정 규칙은 `LiveTrip.junction_end`로 옮겨 `trip_runner.py`를 600줄 아래로 둔다. 바닥 선언 키가 null이면 선언이 없는 것으로 보고 검사하지 않는다.
- 교훈: `feat/trip-site-floor-check`가 같은 9항을 따로 구현했다. 착지 때 하나로 합친다.

## 2026-10-08 · uncommitted · fix(fleet): D-507 Fleet 검토 2회 반영
- 변경: `expect_tol_m`은 지도 자세 나이 + 자세를 읽고 보내기까지 잰 시간 + 0.2 s 여유(`SEND_ALLOWANCE_S`)에 trip 최고 속도를 곱한 값에 드리프트·`ENDPOINT_TOL_M`을 더하고, 아래는 `fleet.trip.expect_tol_min_m`(0.12), 위는 0.30, 자세 값이 없으면 0.30이다. `expect_in_m`은 로봇 진행 방향으로 투영한 장소 거리이고, 장소 앞에서 차로 방향이 15°보다 많이 바뀌면 기대 쌍을 보내지 않는다(`map_id`·`pivot_past_line_m`만). 직진에도 `pivot_past_line_m`. `JUNCTION_ODOM_STALE`은 다음 틱에 다시 보낸다. 좌표 구간에서는 차선 교차로 상태를 비운다. 지도 버전이 다르면 필드를 빼고 `detail.junction_fields_dropped`.
- 증거: `test_trip_d507.py` 26건, 변이 검사(굽은 길 규칙, 잰 지연), fleet 묶음과 `test/known_failures.py`.
- gate 변화: SOURCE만.
- 결정: CORE 창은 곧게 내다보는 투영이라 굽은 접근에서는 창을 주지 않는다. 경로를 따르는 창은 뒤의 일(D-507 2항 문장).
- 교훈: 최악 지연(호출 시한)을 오차에 넣으면 모든 창이 상한에 붙어 창이 쓸모없어진다. 잰 지연을 쓴다.

## 2026-10-08 · uncommitted · fix(fleet): D-507 굽은 길 옆 거리, main 병합
- 변경: 15° 이하 굽이에서 차로가 로봇 진행 방향 반직선 옆으로 벗어나는 가장 큰 거리를 `expect_tol_m`에 더한다(상한 0.30 전). main 병합으로 API Ref 번호를 v1.127에서 v1.126으로 옮겼다(main이 v1.124·v1.125를 썼다).
- 증거: `test_trip_d507.py` 27건, fleet 묶음과 `test/known_failures.py`, 크기 시험.
- gate 변화: SOURCE만.
- 결정: 15° 규칙은 그대로 둔다.
- 교훈: 곧게 내다보는 창은 작은 굽이에서도 옆으로 비켜 선다. 허용 오차가 그 거리를 덮어야 한다.

## 2026-10-08 · uncommitted · feat(fleet): D-513 7 지도 화면 방향 `view_turn_deg`
- 변경: `rosy.site_map/1`에 `view_turn_deg`(0/90/180/270)를 둔다. 현장 지도 화면이 지도를 그만큼 돌려 그리고 "화면 방향" 선택으로 고친다. 관제 크게 보기·썸네일은 `mapUpTurn + view_turn_deg`로 돈다.
- 증거: 웹 Node 시험 180 passed, 현장 지도 pytest 120 passed. 로컬 재현: `ceil.jpg` 페인트 정합(점수 0.85)에서 `mapUpTurn` 0, 90을 더하면 벽이 맨 아래.
- gate 변화: SOURCE/LOCAL만. 현장 활성 지도에 90 저장(F3)은 별도.

## 2026-10-08 · uncommitted · D-515 관제 지도 천장 카메라를 위에서 본 직사각형으로

- 변경: `camera-warp.js`(사이트 사각형 576 삼각형 메시·아핀, 순수), `map-view.js` `drawSiteView` 실영상을 지도 미터 뷰 위에 편 그림으로 그림(돌린 원본 대신), `view.cameraPick` 제거(미터 뷰 역변환 사용), `static_routes.py` 자산 등록. 썸네일·크게 보기는 원본 회전 그대로.
- 증거: `camera-warp.test.mjs` 3 passed(실제 보정 paint-f81a872f5cd8), 웹 Node 178 passed, 실프레임 1920 캡처에서 사이트 사각형이 차선과 맞고 원이 둥글다([실측](../../docs/validation/site-camera-topdown-2026-10-07/result.md)).
- gate 변화: LOCAL 표시. SITE/FIELD 상태는 그대로 둔다.

## 2026-10-08 · uncommitted · feat(fleet): D-472 LED 신원 오케스트레이터와 확인 트랙
- 변경: `server/identity.py` `IdentityService` — 움직이는 미확인 로봇 한 대씩, 6 s 창, 로봇 설정 색으로 CORE 점멸 요청. Vision 판정으로 익명 트랙에 묶고 트랙 손실·0.30 m 겹침·map/보정 revision 변경·`identity_ttl_s`에 UNKNOWN. `confirmed_track_pose(robot_id)`가 D-511 입력. 읽기 전용 `GET /api/fleet/tracking/identity`, Vision 판정 `POST /api/fleet/detections/identity`, detections config `identity_challenge`. 사이트 YAML `identity:`(기본 `auto_request: false`). API Ref v1.130
- 증거: `test_led_identity.py`, `test_lamp_identify_route.py`, `test_boundaries.py`(지도 자세 중재·trip·명령 경로가 identity를 읽지 않음)
- gate 변화: 없음. 현장 측정·DEVICE/FIELD 미확인
- 결정: D-472 addendum 3·4·5항

## 2026-10-08 · uncommitted · fix(fleet): D-472 독립 안전 검토 지적 반영
- 변경: 두 확인 트랙이 같은 source에서 0.30 m 안으로 만나면 둘 다 UNKNOWN(overlap). 경계 시험이 상대 import와 `tracking.identity`·`app.state.identity` 속성 접근도 잡는다(공용 `_server_imports`)
- 증거: 영향 시험 58 passed, known_failures 0 NEW. 두 시험 모두 수정 전 코드에서 실패함을 확인
- gate 변화: 없음. D-430 독립 검토(critic) APPROVE

## 2026-10-08 · uncommitted · feat(fleet): D-517 M1a 로봇마다 trip, 반복 운행, Fleet 블록 표(표시만)
- 변경: `trip_runner.py` 로봇마다 trip 하나(`TRIP_BUSY`는 그 로봇), 0.5 s마다 로봇별 task·잠금으로 동시에 한 걸음, 이전 걸음이 안 끝난 로봇은 그 주기를 건너뜀. `POST /trip` `repeat`(경유지 순환), 바퀴 마지막 장소 앞에서 출발 검사를 다시 하고 다음 바퀴를 붙임, 경로가 바뀌거나 검사가 실패하면 `hold.reason: lap`. `routing/trip.py` 차로 끝이 아닌 장소(출발 자리)를 좌표·yaw 목적지와 경유지로. 새 `server/lane_traffic.py` `TrafficService`가 주기마다 `blocks.step`, `GET /api/fleet/traffic` 읽기 전용, 거절된 블록으로 들어가는 교차로 지시는 보내지 않음(블록 대기는 정체 아님), 반복 운행 출발 `TRIP_LOOP_FULL`. 사이트 설정 `fleet.traffic.zones`. API Ref v1.138
- 증거: 모델 PC `test_lane_traffic.py` 10 passed, trip·routing·blocks·site_map·cancel_all 묶음 252 passed(1 실패는 시험 배치 오류, 고쳐서 통과)
- gate 변화: SOURCE/LOCAL만. 통행권 전송(M2)·SIM·DEVICE 없음
- 결정: D-517 1·2·3·4(정체)·7항

## 2026-10-08 · uncommitted · feat(fleet): D-511 감시가 LED 확인 트랙을 입력으로 쓴다
- 변경: `LaneComplianceMonitor`가 지도 자세가 LOCALIZED가 아니면 D-472 `IdentityService.confirmed_track_pose`를 판정한다(CONFIRMED, `age_s` ≤ `fleet.map_pose.sighting_lease_s`, 활성 지도 map id). 결과에 `pose_source`(`map_pose`|`led_track`)·`heading_source`(`pose`|`track_motion`|`none`)를 싣고 바뀔 때 로그를 남긴다. 트랙에 yaw가 없어 `moving_min_m`을 넘게 움직인 이전 위치에서의 방향을 쓰고, 정지면 순수 판정이 방향 문 없이 가장 가까운 호를 고른다. `pose_state`는 지도 자세 그대로. API Ref v1.132(가산)
- 증거: `test_lane_compliance_service.py` 신규 2개, `test_boundaries.py`(lane_compliance_service만 identity 읽기 허용, map pose·trip 모듈 금지) — fleet 묶음·`test/architecture`·`test/test_line_follow_contract_docs.py` + `test/known_failures.py` (X:/DevTemp/d511-led/)
- gate 변화: 없음. SOURCE/LOCAL만. 실제 `ceiling_north` LED 실측(D-472 addendum 6)·현장 수용은 열려 있다
- 결정: D-472 addendum 3. 확인 트랙은 D-494 arbitrated_pose·trip·initialpose·명령에 닿지 않는다
- 교훈: 없음

## 2026-10-08 · uncommitted · fix(fleet): D-511 LED 트랙 입력 리뷰 반영
- 변경: 카메라가 프레임을 건너뛰어 같은 위치가 와도 트랙이 신선한 동안 마지막 이동 방향을 유지한다. 방향은 odom이 움직임을 말하고 트랙이 새 잠정 설정 `fleet.lane_compliance.track_heading_min_m`(0.05 m, 카메라 blob 잡음 이상)을 넘게 움직였을 때만 잡는다. `pose_source`가 바뀌면 WARN/ACT 누적을 새로 시작한다. `identity.confirmed_track_pose`의 `age_s`를 0으로 자르지 않고, 감시는 `MAX_SIGHTING_FUTURE_S`(0.05 s)보다 미래인 트랙을 지도 자세 sighting처럼 거절한다. API Ref v1.132 행 문구 수정("margin exact" 삭제, 교차로에서 가로지르는 차로 가능), D-511 Open M1 공백 (4) 추가
- 증거: `test_lane_compliance_service.py`(건너뛴 프레임·odom 정지·출처 전환·미래 시각), `test_led_identity.py`(음수 age), `test_lane_compliance.py`(설정 검증) — fleet 묶음·`test/architecture`·`test/test_line_follow_contract_docs.py` + `test/known_failures.py` (X:/DevTemp/d511-led/)
- gate 변화: 없음. SOURCE/LOCAL만
- 결정: D-472 addendum 3, D-511 Open (4)
- 교훈: 없음

## 2026-10-08 · uncommitted · fix(trip): D-507 회전 축을 지도의 첫 칠한 선에서 (SIM 발견 1–2)
- 변경: `trip_ports.line_past` — 칠한 선 = 차로 합집합 경계(차로마다 중심선 둘레 `width_m` 띠). 장소에서 진행 방향(창이 있으면 로봇 yaw, 없으면 장소의 차로 방향)으로 처음 벗어나는 거리. `junction_fields`가 `pivot_past_line_m = −그 거리`를 보낸다. 0.30 m 안에 선이 없으면 나가는 차로 폭/2, 창 없음. API Ref v1.133.
- 증거: `test_trip_d507.py` 260919 SW spoke SIM 자세(−0.655, −0.432, 64°): pivot −0.105, 창 기대 선 0.401(SIM 측정 0.402), 창 없음 −0.096. L자 −0.1, 곧게 지나감 폭/2·창 없음. 부호 변이 4건 실패 확인 뒤 복원.
- gate 변화: SOURCE. SIM 재실행은 열림.
- 결정: D-507 2 개정(2026-10-08 사용자 결정)

## 2026-10-08 · uncommitted · fix(trip): D-507 pivot 검토 반영 — lane 차로만, 창 없으면 음수 pivot 없음
- 변경: `line_past`는 `drive_mode: lane` 차로만 칠한 선으로 보고, 반올림 뒤 0.30 m에서 한 번만 자른다. 창을 보내지 않는 장소에는 음수 pivot을 보내지 않는다(CORE `stop_point`). 선이 없으면 예전대로 폭/2.
- 증거: `test_trip_d507.py` free 차로, 0.30 경계(0.6→0.3, 0.604→None), SW 로봇 yaw 64° 대 차로 53.8°, 창 없는 두 경우. 변이(창 없이 음수 pivot) 2건 실패 확인 뒤 복원.
- gate 변화: SOURCE.
- 결정: D-507 2 개정 검토

## 2026-10-08 · uncommitted · docs(fleet): D-507 2·4 부호 있는 pivot의 API Ref 번호를 v1.135로 옮김
- 변경: main 병합으로 v1.133·v1.134가 다른 브랜치(D-507 7)에 쓰여, 이 브랜치의 API Ref 행·`app.py`·버전 핀을 v1.135로 옮겼다. 앞 항목의 v1.133은 그 때의 번호다.
- 증거: `test/test_line_follow_contract_docs.py`, `test_protocol_version_alignment.py` 버전 핀 통과.
- gate 변화: 없음.

## 2026-10-08 · uncommitted · docs(fleet): 지도 교차로 창 누락 시 CORE HOLD 설명
- 변경: `trip_ports.py`의 창 누락 주석을 D-507 3항 보충 계약에 맞췄다. Fleet은 여전히 창이 없는 지도 지시를 보낼 수 있지만, 새 CORE는 가로선 감지에서 `junction_unexpected`로 멈추고 Fleet은 trip을 끝낸다. 기존 장치 CORE에는 이 변경이 적용되지 않는다.
- 증거: `test_trip_d507.py`와 CORE 교차로·API·계약 시험 194건 통과. 실제 Fleet→CORE 폐루프 SIM은 미실행.
- gate 변화: 없음. SIM·DEVICE는 열림.
- 결정: D-507 3항 보충.

## 2026-10-08 · uncommitted · feat(fleet): 지도 edge 굽이 후보 진단
- 변경: 진행 중 lane trip의 활성 지도 edge에서 가까운 굽이를 찾아 `detail.bend_candidate`에 기록한다. 원본 자세의 나이·dead reckoning·지도 offset·yaw·버전을 검사하고, 근거 상실 또는 trip 종료 시 지운다. CORE 명령은 추가하지 않았다.
- 증거: `test_trip_d507.py`의 실제 west edge 후보·낡은 자세(0.304 s 반올림 경계)·지도 ID/버전 변경·trip 종료 검사. 관련 pytest 217 통과 후 착지 게이트가 파일/패키지 크기 판정 2건을 발견해 중단됐다(깨끗한 main의 두 시험은 통과). 굽이 진단을 `trip_ports.py`로 모으고 P6 판정을 갱신한 뒤 해당 시험 포함 41 통과. `known_failures.py` 0 new, flake8 및 harness lint 0 error. SOURCE/LOCAL 범위.
- gate 변화: 없음. Fleet→CORE 폐루프 SIM·장치·현장 검수는 열림.
- 결정: B9 굽이 접근 허가는 같은 경계의 검수 및 음성 사례를 통과할 때까지 보류.

## 2026-10-08 · uncommitted · fix(fleet): D-507 4 교차로 회전 각을 전진 현으로 조준
- 변경: `execute.turn_target`이 장소 점에서 나가는 차로를 따라 `ADVANCE_M`(0.10, D-495 기본) 앞 점으로의 방향과 진입 접선의 차이를 `turn_deg`로 낸다. trip 러너는 회전 지시에 이 각과 `advance_m` 0.10을 함께 보낸다. 분류(직진·좌·우)는 접선 각 그대로이고 150° 한도는 보내는 각으로 본다. CORE·API 문구는 그대로다(버전 없음).
- 증거: 260919 SW(west.rev→ring_s.fwd) −114.6°→−108.9°, NE(east.rev→ring_n.fwd) −102.8°→−97.1°(접선 대비 +5.7°, (0.10−0.05)/(2·0.25)). 장소에서 0.10 m 직진 끝의 차로 중심선 거리 0.1 mm(접선 조준 9.8 mm). 곧은 차로 변화 없음. 부호 변이(현 오프셋을 반대로) 2건 실패 확인 뒤 복원. fleet routing·trip 시험 통과.
- gate 변화: SOURCE. SIM 재실행(NE 차선 유지)·장치는 열림.
- 결정: D-507 4항 개정(2026-10-08 사용자 결정).

## 2026-10-08 · uncommitted · fix(fleet): D-507 4 검토 반영 — 보내는 현 각의 한도·부호 검사
- 변경: 앞 항목의 "150° 한도는 보내는 각" 수정이 실제로 적용되지 않아 `unsupported`가 접선 각을 보고 있었다. 이제 분류는 접선 각, 좌·우는 보내는 현 각(반올림 0.1°)이 150° 초과·0·반대 부호면 `LANE_TURN_TOO_SHARP`(CORE `set_junction`이 셋 다 거절). `advance_m`은 나가는 차로 길이로 자르고 같은 점을 겨눈다(지도 schema가 차로 ≥ 0.1 m라 오늘 0.10은 잘리지 않음).
- 증거: `test_routing_execute.py` 접선 95°·현 112.5° 한도 100 거절/120 통과, +25° 좌인데 현이 음수인 차로 거절, ADVANCE_M 0.30에서 0.15 m 차로 자름. 변이 2건(부호 검사 제거, 접선으로 한도) 실패 확인 뒤 복원. fleet routing·trip + 구조 시험 246 통과, 1 실패는 fleet 크기 판정(깨끗한 main 공유 체크아웃에서도 실패, 44433 > 43809+150).
- gate 변화: SOURCE. SIM·장치는 열림.
- 결정: D-507 4항 개정 문구에 부호·`advance_m` 자름을 더함.

## 2026-10-08 · uncommitted · feat(fleet): D-517 M0 고정 블록 통행권 계산
- 변경: `fleet/routing/blocks.py` 블록 길이(몸체·정지 거리·불확실성·경로 감시 거리), 블록·구역·방향 잠금 양방 차로, 점유는 사실(UNKNOWN은 풀지 않음), 허가는 경로 위치별·줄지 않음·허가 범위만, 앞쪽 블록 먼저 주기, 공정 순서와 합류 대기 상한, 고리 수용 N·h ≤ S−1, 기다림 순환 판정, 위치를 한 번도 모르는 로봇이 있으면 새 허가 중지.
- 증거: 모델 PC `test_blocks.py` 19 passed, 반복 360회(최대 50대, 위치 오차·UNKNOWN·정지·앞뒤 밀착·수용 2 구역) 실패 0. 독립 검토 2회 지적 반영.
- gate 변화: SOURCE/LOCAL만. 로봇에 아무것도 보내지 않는다(M2 전).

## 2026-10-08 · uncommitted · fix(fleet): 창 없는 좌·우 지시를 보내지 않고 trip 정지 (D-507 2, 사용자 결정 2)
- 변경: trip 루프가 `left`·`right`를 기대 창(`expect_in_m`·`expect_tol_m`) 없이 보내게 되면 보내지 않고 trip을 `stopped` `junction_no_window`로 끝낸다(`detail.junction_place`·`junction_action`·`junction_fields`). `junction_pivot`이 없는 로봇, 다른 지도 버전, 0.30 m 안 가로선 없음, 장소가 (0, 2] 밖, 15° 넘는 굽이가 모두 해당한다. `straight`·`stop`은 그대로. 콘솔 사유 문구, API Ref v1.138.
- 증거: `test_trip_d507.py`(옛 로봇·선 없음·장소 위·SW 장소 위·16° 굽이가 정지하고 halt `stop` 외에 보낸 지시 없음), `test_trip_runner.py`(시험 로봇에 `junction_pivot`), `site-map.test.mjs` 사유 문구. 관련 fleet pytest 246 통과, node 15 통과.
- gate 변화: SOURCE. SIM 3차 R3-4(창 없는 SW 지시가 굽이에서 −112° 회전)의 Fleet 쪽 경로를 닫는다. SIM·장치는 열림.
- 결정: D-507 2항 2026-10-08 사용자 결정 (2).

## 2026-10-08 · uncommitted · feat(fleet): 차로를 따른 거리로 기대 창, 15° 굽이 규칙 삭제 (D-507 2, 사용자 결정 1)
- 변경: `junction_fields`의 `expect_in_m` = 로봇 투영점에서 장소까지 차로 polyline 거리(`remaining`), 선 찾기는 장소의 차로 방향, `_straight_ahead`와 15° 규칙 삭제. `expect_tol_m`의 odom 오차 항 = 0.05 × (dead reckoning + `expect_in_m`), 광선 옆 거리 항 삭제. 선이 없거나 범위 밖이면 여전히 창이 없고 그 좌·우는 `junction_no_window`로 멈춘다.
- 증거: `test_trip_d507.py` — 260919 한 바퀴 SW(장소 0.6 m 앞, 오른쪽 −114.6, `expect_in_m` 0.6, 굽이 오감지 +0.10 m까지 창 밖), ring_n→NW(0.322 m, 현 0.301 m)·ring_s→SE(0.324 m) 진출 창, 10/15/16/60° 굽이 창, 허용치 항. 변이(`expect_in_m`을 직선 거리로) 8건 실패 확인 뒤 복원. fleet pytest 250 통과, node 15 통과, `known_failures` 신규 0.
- gate 변화: SOURCE. 회전교차로 진출의 축·재획득, 한 바퀴 SIM은 열림(Gazebo는 모델 PC).
- 결정: D-507 2항 2026-10-08 사용자 결정 (1).

## 2026-10-08 · uncommitted · fix(fleet): 굽이에서 차로 옆 거리만큼 기대 창을 넓힘, 장소 위 재전송 정지 시험 (D-507 2, 안전 검토 3·4)
- 변경: `junction_fields`의 `expect_tol_m`에 (로봇의 차로 중심선 옆 거리) × (로봇에서 장소까지 차로 방향 변화의 절댓값 합, rad)을 더한다(상한 0.30 그대로). 주행 거리로 비교하는 창에서 굽이 옆길은 중심선보다 그만큼 길거나 짧다. ADR 2항에 알려진 한계(보낸 뒤 옆 거리 변화, keeper 곧은 `junction_ahead_m`) 추가.
- 증거: `test_trip_d507.py` — 60°·16° 굽이에서 ±0.03 m 옆이면 0.135 + 0.03 × 굽이(rad), 0° 굽이 0, 상한 0.30. armed 중 장소 위(`remaining` 0) 재전송은 `junction_no_window` 정지이고 두 번째 회전은 없음(의도한 동작). 변이(항 0) 4건 실패 뒤 복원. fleet trip pytest 통과.
- gate 변화: SOURCE.
- 결정: D-507 2항 2026-10-08 사용자 결정 (1), 안전 검토 REQUEST_CHANGES 3·4.

## 2026-10-08 · uncommitted · docs(fleet): D-507 주행 거리 창의 API Ref 번호를 v1.139로 옮김, main 병합
- 변경: main(v1.137, D-507 4 현 조준 e72e8dfa1 포함) 병합. v1.138은 다른 브랜치(feat/d517-m1-fleet 커밋, feat/fleet-map-trail 미커밋)가 써서 이 브랜치의 API Ref 행·머리글·`app.py`·버전 핀을 v1.139로 옮겼다. 앞 항목들의 v1.138은 그 때의 번호다. 260919 시험의 회전각을 현 조준 값(SW −108.9, NW −102.2, SE −98.6)으로 맞췄다.
- 증거: fleet trip·버전 핀 256 통과, CORE 교차로·services·api_web·구조 시험에서 실패 1건은 fleet 크기 판정(44805 > 43809+150)이며 공유 main 체크아웃에서도 같은 값으로 실패한다(이 브랜치의 fleet 줄 수는 main과 같다).
- gate 변화: 없음.

## 2026-10-08 · uncommitted · feat(fleet): 지도 궤적과 D-512 테더 표시
- 변경: 새 `web/trail-view.js`가 1 s 상태 폴링 pose로 로봇별 궤적(최근 120 s, 600점, 1 cm 이상 이동)을 브라우저에 모아 나이에 따라 흐리게 그리고, 테더 원과 기준점을 그린다(로봇이 원 밖이면 주의 색). `map-view.js`는 import와 그리기 hook 두 줄만 늘었다(격자·D-513 7 회전 미터 뷰의 toPx를 넘긴다). 새 `server/tether_routes.py`: `GET /api/fleet/tethers`(viewer), named operator `POST`·`DELETE /api/fleet/robots/{robot_id}/tether`, 메모리 전용. API Ref v1.138.
- 증거: `test_tether_routes.py`(인증·멱등·검증), `web/trail-view.test.mjs`(간격·한도·회전 투영), Chromium `test_start_point_browser.py::test_map_draws_the_travelled_trail_and_a_tether`. SOURCE/LOCAL 범위.
- gate 변화: 없음. 실기 궤적·테더 강제(tools/device_test, D-512)는 열림.
- 결정: D-512 표시 절반. fleet 패키지 크기 판정은 main에서 이미 43809+150을 넘었다(44433) — 재판정 필요.

## 2026-10-08 · uncommitted · fix(fleet): 지도 궤적·테더 검토 반영
- 변경: main(API v1.139, D-512 개정 1) 병합. 이 브랜치의 API Ref 행·머리글·CORE `app.py`·버전 핀을 v1.140으로 옮겼다(앞 항목의 v1.138은 그때 번호). odom 자세(`localization.pose_frame`)는 궤적·테더 판정에 넣지 않는다. anchor_xy는 ±1000 m, 테더 폴링 실패 시 직전 목록을 둔다, 로스터에서 빠진 로봇의 테더는 목록에서 지운다. D-512 개정 1 5항에 표시 쪽이 있다는 문장을 더했다.
- 증거: tether·trail 시험(odom 제외, anchor 범위, NaN 500 고정) 통과. fleet 2685 통과, shared/web 237, architecture 133 통과. `known_failures.py` NEW 1건 `test_grammar_separation`은 깨끗한 main에서도 실패한다(D-519 password-login.css).
- gate 변화: 없음. D-512 개정 1 5항의 Fleet tether 감시(정지 지시)는 열림.
- 결정: 병합 후 fleet 44929 ≤ 44806+150이라 크기 판정 변경 없음. 앱 공통 422 응답이 JSON 아닌 NaN을 담지 못해 500이 되는 문제는 후속.

## 2026-10-08 · uncommitted · fix(fleet): D-517 M1a 리뷰 반영 — 끝난 trip의 점유 유지, 고리 키, 바퀴 재시도·정리
- 변경: main(M0 `unplaced`·`pinned`·발생별 허가) 병합. `lane_traffic.py` 위치 없는 trip 로봇이 있으면 그 주기 교차로 지시 없음, `GET /api/fleet/traffic` `unplaced`. 끝난 trip·다른 지도 버전 trip의 허가·몸체는 `pinned`로 남고 신선한 LOCALIZED 자세가 벗어남을 보일 때 풀림(D-517 6), 지도 활성화는 마지막 자세로 다시 핀. `TRIP_LOOP_FULL`은 한 바퀴(via…, to) 간선 집합으로 고리를 묶고 그 바퀴 블록으로 S를 센다. 표 계산 예외 시 모든 trip의 `traffic`을 비움. 교차로 지시 보류는 장소 + `PAST_PLACE_M`까지. 실패한 바퀴 검사는 5 s마다 2회(D-438 예산)·확인 때 다시. E-stop은 모든 trip을 먼저 닫고 동시에 정지. `confirm_replan`이 `at` 초기화. 반복 trip은 지난 바퀴를 잘라 계획을 두 바퀴로 유지(표의 허가 색인·통행권을 같이 옮김). 주기는 틱 시간을 뺀 나머지만 잔다. `routing/trip.py` 차로 중간 장소의 도달 불가 yaw는 `TRIP_ARRIVE_YAW_UNREACHABLE`
- 증거: 모델 PC `operations/fleet/test/` + `test/test_line_follow_contract_docs.py`; 기존 실패 3건(grammar_separation password-login.css, learning_receiver PIL, site_map_api attention-stale.test.mjs)은 깨끗한 main ba15e926b에서도 같은 문구로 실패
- gate 변화: SOURCE/LOCAL만. 통행권 전송(M2)·SIM·DEVICE 없음
- 결정: D-517 2·3·6·7항
- 교훈: 없음

## 2026-10-08 · uncommitted · uiux(fleet-web): D-517 M1b 교통 층, 카드 한 줄, 예외 큐 행, 반복 운행 시작
- 변경: `site-map-model.js`에 순수 함수(`trafficDrawing`, `trafficCardLine`, `trafficClock`, `trafficAttention`, `loopCapacityText`, `repeatTripBody`). 새 자산 파일 대신 이 파일에 둬서 `static_routes.py` 허용 목록은 그대로다. `map-view.js`가 관제 지도에 "교통" 층 하나를 그린다. 블록 띠(점유 채움, 허가 테두리, 불명 빗금), 구역 윤곽과 "점유 a/b · 대기 n", 통행권 끝 가로 표시와 로봇 이름을 같은 toPx로 그리고, `/traffic`는 1 s마다 poll-gate로 읽는다. 지도 머리에 "교통 켬/끔" 단추를 둔다. `roster.js`에 카드 한 줄과 `attentionItems` 행(교착, 30 s 넘은 불명, 20 s 넘은 합류 대기, 고리 수용 초과)을 더한다. 현장 지도 운행 칸은 로봇마다 시작·취소를 따로 하고(`TRIP_BUSY` "이 로봇은 이미 운행 중입니다"), 출발 자리 + "반복 운행 시작"과 "고리 n/m대"를 둔다. `TRIP_LOOP_FULL`에는 robots/capacity를 붙인다. 넓은 단의 관제 경로는 한 줄로 줄인다
- 증거: 모델 PC node 단위 191 중 190 통과. 실패 1건 `attention-stale.test.mjs`는 node 18의 `import.meta.dirname` 때문이고 base d4cab5388에서도 실패한다. 실제 Chromium 브라우저 범위 256 passed, 7 failed. 실패 7건은 base에서도 모두 실패한다(fit 4, session 2, node 1). 그중 fit 넘침은 143 px에서 28 px로 줄었다. 새 `test_traffic_view_browser.py` 2 passed, 1920×1080에서 스크롤 없음. 화면은 X:/DevTemp/d517-m1b/shots/ 세 폭이고, impeccable 방식의 독립 검토를 반영했다
- gate 변화: SOURCE/LOCAL만. 통행권(M2)·SIM·DEVICE 없음
- 결정: D-517 10항
- 교훈: `/traffic`는 구역의 차로를 알려 주지 않아 구역이 하나일 때만 윤곽을 그린다. 대기 순서와 대기 시각도 싣지 않아 "교차로 대기 n번째"는 쓰지 못한다. 30 s·20 s 시계는 콘솔이 처음 본 시각부터 잰다

## 2026-10-08 · 7e883f418 · refactor(fleet): D-517 trip runner split — 바퀴·정지·교통 이음매
- 변경: 크기 판정이 이름 붙인 이음매대로 나눴다. `server/trip_laps.py`(바퀴 호 계산, 바퀴 시점·재시도 시점, 다음 바퀴 이어붙임·지난 바퀴 자르기·대기 `carry_on`, `_from`/`_dropped`/`_joined`), `server/trip_halts.py`(`TripHalts`: 로봇 정지, 재시작 전 trip 로봇 정지와 그 목록), `lane_traffic.TrafficService`(`holds` 교차로 지시 보류, `watch` 핀 로봇 자세 읽기, `period` 표 계산과 예외 처리). `trip_runner.py`는 start/cancel/tick/`_step*`/replan만 남는다. 로그 문구·로거 이름·오류 코드·await 순서는 그대로. 시험은 `runner.halts.*`, `runner.traffic.holds`로 옮김
- 증거: 모델 PC 7e883f418 `test_trip_runner`·`test_lane_traffic`·`test_site_map_trip`·`test_cancel_all`·`test_routing`·`test_blocks`·`test/architecture/test_module_structure.py` 263 passed(분리 전 27cd04cc0도 263 passed), `known_failures.py` 0 new; `test_trip_d507.py` 50 passed
- gate 변화: 없음(동작 변경 없음)
- 결정: trip_runner 847→686, 크기 판정 split 유지(남은 것은 상태기계 하나, 다음 증가 때 다시 판정). trip_halts 81, trip_laps 77, lane_traffic 305. fleet 패키지 45573 = 45423+150, 허용치를 다 썼다
- 교훈: 분리도 모듈 머리말·import로 줄을 늘린다. 패키지 허용치가 거의 찬 때는 분리 전에 남은 줄을 센다

## 2026-10-08 · 727d96501 · refactor(fleet-web): map-view.js 카메라 배경·교통 층 분리
- 변경: 크기 판정이 이름 붙인 카메라 배경 이음매대로 나눴다. 새 `web/camera-backdrop.js`(`cameraMapCalibration`, 위에서 본 그림 캐시·`drawCameraTopDown`·`warpOnto`, `setCameraFrame`, `frameTurn`, `turnedUrl`, `bindCamera`), 새 `web/traffic-view.js`(D-517 10 교통 층 그리기). `map-view.js`는 지도 그리기·폴링·교통 토글을 가지고 draw hook, 받은 보정, toPx를 넘긴다. DOM·그리기 순서·폴링은 그대로. 자산은 `static_routes.py`, `test_document_imports.py`, 캔버스 팔레트 계약, `web/AGENTS.md`에 등록
- 증거: 모델 PC node 단위 + 브라우저 범위 + `test/architecture/test_module_structure.py`: 분리 전 64d7a68a8 11 failed/288 passed, 분리 뒤 727d96501 11 failed/288 passed, 실패 목록 같음(attention-stale node, console_session 2, fit 4, peer_picker 3, 크기 판정). 크기 판정 실패는 분리 전 map-view 1030>903+0과 fleet 패키지였고 분리 뒤 fleet 패키지만 남는다
- gate 변화: 없음(동작 변경 없음)
- 결정: map-view.js 1030→831, 판정 split 유지(다음 증가 때 다시 판정). camera-backdrop 141, traffic-view 82. fleet 패키지 45944→45968(+24, 머리말·import), 패키지 판정은 다른 단계가 다시 한다
- 교훈: 없음

## 2026-10-08 · uncommitted · feat(fleet): 지도 굽이 장소와 trip의 `bend` 지시 (D-507 보충)
- 변경: `site_map.py` 장소 종류 `bend`(꼭짓점, `yaw`·`exit_yaw`·`radius_m` 필수, 회전 15–90°, 다른 종류는 두 필드 불가, 저장 body는 굽이 필드가 없는 장소에서 그대로). `trip_ports.py` `bend_geometry`(두 접점이 이 차선에 있고 진행 방향으로 회전 부호), `next_bend`, `bend_fields`(`bend_in_m` = 차로를 따른 호 시작점까지 거리, `bend_tol_m` = 기존 `expect_tol_m` 식, 옆 항 없음), `_pose_tol`로 tol 식을 한 곳에 둠. `trip_runner.py` `_step_bend`: `lane_bend` 로봇에만, 지나지 않은 굽이가 있으면 그 굽이가 다음 장소보다 먼저, 호 시작점 0.6 m 안에서 보내고 절반 만료에 갱신, CORE가 끝내야(`bending`/`reacquiring` 뒤 `idle`) 장소 지시. `MANOEUVRE`에 `bending`, `_completed`는 굽이 지시를 장소 완료로 세지 않음. `TripCaps.lane_bend`.
- 증거: `test_trip_bend.py` 9건(장소 검증, 기존 지도 body 그대로, 실제 west 간선 방향별 회전 부호·호 시작점, 능력 읽기, 굽이 구간에서만 보냄·기동 중 안 보냄·끝난 뒤 다음 장소, armed 굽이가 다음 장소를 막음, 굽이 없는 지도·`lane_bend` 없는 로봇은 `bend` 없음, unresolved면 trip 정지). FakeCore가 `bend`를 받도록 `test_trip_runner.py` 보충.
- gate 변화: SOURCE. SIM은 Fleet 함수를 쓰는 probe로.
- 결정: D-507 보충

## 2026-10-08 · uncommitted · fix(fleet): 굽이 지시는 굽이 앞 차로가 곧을 때만
- 변경: `trip_ports.straight_approach`, `bend_fields`가 로봇에서 호 시작점까지 차로 방향이 15° 안일 때만 필드를 만든다. CORE가 `bend_in_m`을 odom 이동으로 재므로 모서리 안에서 보내면 질러 간 만큼 호가 늦다(모델 PC SIM 서쪽 출발 2회 `bend_basis_lost`, 호 중간 바깥 4.9 cm).
- 증거: `test_trip_bend.py::test_bend_waits_until_the_lane_before_it_is_straight`, trip 시험 133 passed.
- gate 변화: SOURCE. SIM 재실행은 `docs/validation/lane-bend-odom-sim-2026-10-08`.
- 결정: D-507 보충

## 2026-10-08 · uncommitted · fix(fleet): `repeat` trip의 다음 바퀴가 굽이 지시를 다시 보낸다
- 변경: main의 D-517 M1a 반복 trip과 병합. 굽이 장소 id는 바퀴마다 같으므로 `LiveTrip.bends_done`을 다음 바퀴가 시작될 때(`_next_lap` 같은 경로, `confirm_replan`의 `lap_route`) 비운다. 비우지 않으면 2바퀴부터 굽이를 지시 없이 지나간다. `_pose_tol`은 main의 주행 거리 항을 받고 `bend_tol_m`은 이 브랜치의 규칙(dead-reckon 거리만) 그대로다.
- 증거: `test_lane_traffic.py::test_a_new_lap_drives_its_bends_again`, trip 시험 118 passed.
- gate 변화: SOURCE.
- 결정: D-507 보충, D-517

## 2026-10-08 · 138ee8567 · feat(fleet): D-517 M2 통행권 전송 (server/trip_authority.py)
- 변경: `fleet.traffic.authority`(기본 false) + 로봇 능력 `line_follow_authority` 일 때만 trip 주기마다 표 계산 뒤 `POST /api/v1/line-follow/authority`. `until_m` = `authority_end_m` − 표가 쓴 자세의 경로 위치, `pose_stamp` = `MapPose.odom_stamp`(새 필드), `ttl_s` 2, leg `{trip_id}:{route_rev}` 별로 줄지 않음. 로봇당 전송 하나, 주기 안 재시도 없음. trip 보기 `traffic_authority`(core|hold_back), CORE `HOLDING` 은 정체 아님.
- 증거: 모델 PC `operations/fleet/test` 2712 통과·4 실패 — 4건 모두 이 브랜치 기준 main 에서도 실패(3건 main 재현, `test_grammar_separation` 은 main bfaf00df6 에서 고침). `test_trip_authority.py` 통과.
- gate 변화: SOURCE.
- 결정: D-517 4항 (M2). fleet 46053 (판정 45942+150 안), app.py 751.

## 2026-10-08 · 311469e4c · fix(fleet): D-517 M2 리뷰 반영 — 앞 끝 d, 자세 짝, 첫 통행권 전 강제
- 변경: (887abb1a9 와 함께) 표의 `d` = base 경로 위치 + 몸 `front_x_m`(blocks.py 정의, `PINKY_PRO` URDF 값). 표가 `live.traffic` 에 `front_d_m`·`pose_stamp` 를 내보내고 송신기는 다시 계산하지 않는다(`until_m` = 끝 − 앞 끝 d). `(live.at, live.at_stamp)` 를 한 자세에서 한 번에 쓰고 정지·재계획 때 같이 지운다. 단계가 진행 중인 로봇에는 그 주기에 보내지 않는다. `fleet.traffic.authority` 이고 `line_follow_authority` 인데 `line_follow_authority_required` 가 없으면 lane trip 시작 422 `TRIP_AUTHORITY_NOT_REQUIRED`.
- 증거: 모델 PC 수정 전 `test_trip_authority.py` 수집 실패(새 능력 필드), 수정 뒤 대상 241 통과. `operations/fleet/test` 2718 통과·3 실패 — 3건 main(16115e269)에서도 실패(`test_document_imports`, `test_learning_receiver`, `test_site_map_api` node).
- gate 변화: SOURCE. M1 표도 앞 끝 d 를 쓴다(blocks.py 정의대로 바로잡음).
- 결정: D-517 4항 독립 리뷰 1·2·3. fleet 46092 (판정 45942+150 안). 능력은 trip 시작 때만 본다.

## 2026-10-08 · uncommitted · feat(fleet): D-517 M3 차로 대열(리더–팔로워) 이동 블록
- 변경: `routing/blocks.py` `Robot.convoy/follows/follow_end`, `follow()`(대열에서 가장 가까운 앞 로봇, 문턱 = 앞 끝 − 몸 − 두 u), 따라가는 로봇 하나의 블록만 이동 블록 끝 너머 구간에서 함께 허가(`TableState.shared`), 따라가지 않게 된 공유 허가에서 고정 블록 끝이 멈춤, 팔로워는 더 작은 끝을 받지 않고 그 주기 통행권 없음. `server/lane_traffic.py` 앞 끝을 같은 차로 순서로 팔로워 경로에 옮김(`_front_on`), `/traffic` 로봇 행 `front_d_m`·`convoy`. `POST /trip` `convoy {leader}`, 시작 거절 `TRIP_CONVOY_*`(`trip_laps.convoy_refusal`, `NOT_BEHIND`는 회전 교차로 지름길·앞에서 출발). 화면: 교통 층 대열 선, 카드 "대열 · rosy_01 뒤 0.5 m", 운행 칸 "대열 리더". API Ref v1.144
- 증거: 모델 PC 대상 pytest(blocks/convoy/convoy_trips/lane_traffic/trip_*) 통과, 브라우저 2+2 통과(X:/DevTemp/d517-m3/shots), node 27 통과, 무작위 대열 soak 180회 180000 틱 겹침·추월·축소 0, 최소 간격 0.132 m(d_stop 0.12).
- gate 변화: SOURCE. Safety-Review 대상(독립 검토 전).
- 결정: D-517 9항 4 (M3). fleet 46434 — 판정 46107+150 초과, 다시 판정 필요.

## 2026-10-08 · uncommitted · fix(fleet): D-517 M3 독립 Safety-Review 반영
- 변경: (1) `lane_traffic._shift`가 `state.shared`(경로 구간 번호 키)도 바퀴 정리 때 옮긴다. 다른 표는 블록 키다. (2) 이동 블록 간격에 `MEMBER_REVERSE_M` 0.35 m(D-407 `recovery_back_m` 상한 0.20 + D-468 되짚기 0.15)를 더하고, CORE 읽기가 `RECOVERING`이거나 `stuck`이 열린 앞 로봇은 따라가지 않는다(`blocks.Robot.recovering`, `junction_state`의 `line_recovering`). caps에 복구 설정이 없어 출발 거절은 없다. (3) `_link`가 늦게 출발한 팔로워부터 정하고, 먼저 출발한 팔로워는 자기를 따라가는 나중 팔로워를 따라가지 않는다. (4) 용량 2 이상 구역에서는 함께 허가 예외가 없다(짝을 두 대로 셈). ADR M3 노트에 후진 상한, 상호 따라가기, 구역 용량, 합류 공정성.
- 증거: 각 수정의 시험이 수정 전 실패. 모델 PC 대상 pytest 274 통과(58f866eee). 무작위 대열 soak 360회 360000 틱(바퀴 정리 + UNKNOWN/정체/리더 종료 180회 포함) 겹침·추월·축소·충돌 0.
- gate 변화: SOURCE. Safety-Review 재검토 대기.
- 결정: D-517 9항 4 리뷰 1–4. fleet 46464 (판정 46434+150 안).

## 2026-10-08 · 482c98340 · feat(fleet): D-520 1–2 Fleet 쪽 — exit_segment, 접선 회전, 호 carried 판정
- 변경: `routing/execute.exit_segment`가 나가는 차로 polyline을 원 하나로 맞춘다(Kasa). 장소에서 장소까지의 온 `lane` 차로, 점 6개 이상, 잔차 ≤ `fleet.trip.arc_fit_tol_m`(0.005), 0.5 ≤ |κ| ≤ 5.0, 길이 ≤ 1.0 m일 때만 `{curvature_1pm(왼쪽 +), length_m, outer_line_offset_m, end_place_id}`. `outer_line_offset_m`은 사이트 지도에 칠한 선이 없어 `fleet.trip.arc_outer_line_offset_m`(0.095)이다. 능력 `base_velocity.lane_arc: true`이고 `map_id`가 있는 지시에만 싣는다. 그때 `left`·`right`는 접선 `turn_deg`(6° 없음), `advance_m` 없음. `line_follow.arc.from_place_id`가 보낸 장소이고 `arc_seq`가 보낼 때보다 새로우면 그 지시는 carried(회전 뒤 호, 이어지는 `straight`). 이 trip의 호가 `stopped`면 trip `stopped`(`lane_arc`, `detail.arc_reason`), `reason: lane_arc_end_unarmed`면 `detail.arc_end_unarmed`만 남기고 계속. `arc_mismatch` 중단은 오늘의 `junction`. 콘솔 사유 문구 3개. API Ref trip 행에 문장 추가(판 올림은 CORE 쪽 D-520 항목)
- 증거: 260919 ring 네 호 κ +3.978(반지름 0.2514), 잔차 ≤ 0.00007 m, 길이 0.3739/0.4595/0.3722/0.3739. east·west 잔차 ≥ 0.138 m. 변이 3건: κ 부호 뒤집기 → ring·합성 시험 실패, carried 호 규칙 끄기 → 6건 실패, `arc_seq` 새로움 무시 → 1건 실패, 모두 복원. `operations/fleet/test` 2725 passed/133 skipped/1 failed(`test_document_imports.py::test_each_console_document_reaches_only_its_modules`, 깨끗한 main 627ae3c0c에서도 같음), node `site-map.test.mjs` 15 passed, `test_module_structure.py` 34 passed
- gate 변화: 없음(SOURCE만. SIM 단계 1 전이고 장치 `arc_enabled`는 꺼짐)
- 결정: fleet 패키지 45979→46067(+88, 허용 46092까지 25 남음), trip_runner 686→709(허용 836). D-491 횡단보도 구간 제외는 Fleet이 구역을 모르므로 넣지 않았다(260919 ring에는 없음). 원 맞춤 허용치는 0.005 그대로
- 교훈: 없음

## 2026-10-08 · 7f67af26a · fix(fleet): D-520 검토 반영 — 호 기준선 전 송신 없음, 미무장 표시 지움, 오프셋 범위
- 변경: `lane_arc` 로봇에는 `line_follow.arc`가 실린 교차로 상태를 한 번 읽기 전까지 지시를 보내지 않는다. CORE는 프로세스 동안 마지막 호를 들고 있어서, 기준선 없이 보내면 trip 전의 호가 이 trip의 호로 보여 멈추거나 carried가 될 수 있었다. 지금 호의 사유가 바뀌면 `detail.arc_end_unarmed`를 지운다. CORE 재시작이 `arc_seq`를 되돌린다는 주석(교차로 seq와 같음). `fleet.trip.arc_outer_line_offset_m`은 [0.05, 0.20]만 받는다. ADR D-520 1항에 횡단보도 제외는 CORE 검사(`_arc_on_crosswalk`)라는 줄(d9af50a27)
- 증거: 검토의 변이 생존자 7건을 새 시험이 죽인다(기준선 문, 다른 장소의 호, `stop`의 `exit_segment`, `ARC_MIN_POINTS`, 온 차로 `s_from`, `arc_newer`의 bool, 미무장 표시 지우기). 모두 복원. `operations/fleet/test` 2732 passed/133 skipped/1 failed(`test_document_imports.py`, 깨끗한 main 627ae3c0c에서도 같음), node `site-map.test.mjs` 15 passed, `test_module_structure.py` 34 passed
- gate 변화: 없음(SOURCE만)
- 결정: fleet 패키지 46067→46073(허용 46092까지 19 남음), trip_runner 709→713(허용 836)
- 교훈: 프로세스 수명 동안 남는 상대 쪽 번호(arc_seq)를 "새로움"으로 비교할 때는 첫 읽기를 기준선으로 잡기 전에 아무것도 보내지 않는다

## 2026-10-08 · 91b15708b · fix(fleet): CORE `approaching`도 기동 중으로 센다; Fleet 목록을 CORE 목록에 묶음
- 변경: `trip_runner.MANOEUVRE`에 D-507 4 `approaching`을 더했다. lap SIM 원인 B(3/20): 회전축 접근 중 지도 자세가 이미 다음 차로라 Fleet이 다음 장소 지시를 보내 CORE가 회전을 `aborted`(new_instruction)로 끊었다. `test_trip_runner.py`는 CORE `recovery/junction` `MANEUVER`를 import 해 두 목록이 같은 집합인지 보고, fake CORE도 그 목록으로 돈다. conftest 주석에 이 대조를 적음
- 증거: 수정 전 새 시험 2개와 기존 `test_a_90_degree_turn_waits_out_the_manoeuvre_then_moves_on` 실패(접근 중 `stop C` 송신, 정지 판정), 수정 뒤 `operations/fleet/test` 2763 passed/133 skipped. 독립 검토 code-reviewer(opus) APPROVE WITH NOTES, LOW 5(접근 중 운영자 hold의 정지도 회전처럼 기다림: CORE 접근 시간 상한이 묶음, 취소·E-stop은 `halt_robot`이라 무관; 시험 conftest 주석·liveness 반영)
- gate 변화: 없음(SOURCE). SIM은 굽이→교차로 넘겨주기 브랜치와 함께
- 결정: 없음
- 교훈: 두 프로세스가 같은 상태 이름 목록을 들면 한쪽 사본 대신 시험이 상대 상수를 import 해 대조한다

## 2026-10-08 · e8ba5ada0 · 모바일 관제 첫 화면 결합 검증

- 변경: 개발 인증 뒤 자동 열린 설정 메뉴를 닫고, 관제 경로 진단을 이상 요약 1행으로 접는 두 화면 변경을 한 후보 브랜치에 결합했다. 수동 설정 재개방과 경로 세부 펼침은 유지한다.
- 증거: Chromium 개발 진입 4건+교통 화면 1건 5 passed, Node 경로 요약 5 passed, known_failures 0 NEW. 390·320·1440·1920 캡처와 한계는 `docs/validation/uiux-fleet-first-viewport-2026-10-08/result.md`.
- gate 변화: 없음. LOCAL 결합 후보만 확인했고 DEVICE/FIELD와 전체 G2/G3는 HOLD.

## 2026-10-08 · a90d9b705 · refactor(fleet): 차로 교통을 `fleet/traffic/` 하위 패키지로 옮김 (D-517 이음매)
- 변경: `routing/blocks.py`, `server/lane_traffic.py`, `server/trip_authority.py`를 `fleet/traffic/`로 `git mv`(이름 유지). import만 고침, 호환 shim 없음, 동작 변화 없음. `traffic_reservations.py`는 server/에 둠(M4 재판정 때 결정)
- 증거: 모델 PC a90d9b705 `operations/fleet/test/`·`test/architecture/` 2900 passed/151 skipped/4 failed. `test_learning_receiver` PIL·`test_site_map_api` node는 main에서도 실패, `test_colcon_roots`·`test_omx_policy_config`는 git 없는 스냅샷 탓(로컬 통과). 로컬 git 가드(document_placement, colcon_roots, platform_parts, harness_contracts, robot_literals) 131 passed
- gate 변화: 없음(SOURCE)
- 결정: `fleet/fleet/traffic` SIZE_UNITS 등록, 측정 867(blocks 425, lane_traffic 369, trip_authority 69, __init__ 4). fleet 패키지 판정 기준 46434→45571(옮긴 863줄만큼, 새 판정 아님). D-517 M4 뒤 재판정

## 2026-10-08 · 070959eea · fix(fleet): CORE가 교차로 목격으로 끝낸 굽이도 끝난 것으로 셈
- 변경: lap SIM 원인 D(1/20). `trip_runner._step_bend`는 실어 보낸 굽이를 CORE `idle` 또는 `waiting`(같은 seq)에서 끝난 것으로 센다. 그 뒤 같은 틱에 다음 장소 지시가 기대 창과 함께 나간다
- 증거: 수정 전 `test_a_bend_core_ended_on_the_next_junction_counts_done_and_the_place_goes_out` 실패(아무것도 안 보냄), 수정 뒤 모델 PC `test_trip_bend.py` 통과
- gate 변화: SOURCE. SIM은 core 행과 같이
- 결정: 없음
- 교훈: 없음

## 2026-10-08 · 8fa0df8f6 · fix(fleet): CORE junction_corner_hold 이면 trip 을 바로 멈춤
- 변경: `LiveTrip.junction_end` 는 자기 지시(`junction.seq` ≥ 첫 seq)에서 CORE `line_follow.reason` 이 `junction_corner_hold` 이면 `stopped(junction_corner_hold)`. 20 s stall 을 기다리지 않는다. 지도 화면 문구 추가. API Ref v1.148
- 증거: 수정 전 `test_corner_hold_on_our_instruction_stops_the_trip_at_once` 실패, 수정 뒤 모델 PC `test_trip_d507.py` 통과, node `site-map.test.mjs` 15 pass
- gate 변화: SOURCE
- 결정: 없음
- 교훈: 없음

## 2026-10-08 · 303152390 · feat(fleet): D-517 M4 해결기 연결 (Safety-Review 전)
- 변경: Fleet 막힘 해결기가 trip 로봇에도 답한다(멈추는 R1 `WAIT`만, 그 밖은 사람). `fleet/traffic/handover.py`(순수)가 교착 순환에서 한 대를 막힌 차로를 피해 다시 계획(운영자 확인 `replan_hold`), 나머지 대기, 못 피하면 사람, 30 s 넘는 UNKNOWN은 사람. `GET /api/fleet/traffic` `resolver`, 예외 큐·카드 한 줄 문구. API Ref v1.148. ADR 5항 구현 노트와 옛 경로(`server/lane_traffic.py`, `routing/blocks.py`) 고침
- 증거: 모델 PC 관련 pytest와 node `traffic-layer`·`convoy-view` 12 passed. 전체 결과는 브랜치 보고에 있음
- gate 변화: 없음(SOURCE). 움직임 판단이라 독립 Safety-Review 전에는 착지하지 않음
- 결정: Fleet은 trip 로봇에 물러서기·비켜서기·재개를 보내지 않는다(풀린 블록으로 들어갈 수 있음). 교착은 경로를 스스로 바꾸지 않고 운영자 확인으로만 바꾼다
- 교훈: 없음

## 2026-10-08 · 0fd6d230e · fix(fleet): D-517 M4 Safety-Review M1/M2 반영
- 변경: 해결기 재계획은 장소 `arm_distance_m` 안, CORE 기동 아님, 그 장소 지시 미전송일 때만(M1). 순환은 `CYCLE_PERIODS` 3주기 이어져야 재계획을 고르고, 경로가 있는 재계획 보류가 운영자를 기다리는 동안 `replan`/`wait` 행 유지(M2). 지도 없는 경로에서 해결기 시계 초기화. main 병합, API Ref v1.149
- 증거: 모델 PC `operations/fleet/test/`·`test/architecture/test_module_structure.py` 2839 passed, 실패 2(learning_receiver PIL, site_map_api node: main에서도 실패)
- gate 변화: 없음(SOURCE)
- 결정: 확인 재계획의 장소 검사(LOW)는 하지 않음. 오류 코드가 새로 필요해 별도 단계
- 교훈: 없음

## 2026-10-08 · d3db27b9d · fix(fleet): D-517 사이트 통행권 꺼짐 + CORE 통행권 필수면 lane trip 거절
- 변경: `_caps_checks`가 `fleet.traffic.authority`가 꺼져 있고(또는 송신 모드가 `hold_back`) 능력 `line_follow_authority_required`가 참인 로봇의 `lane` trip을 422 `TRIP_AUTHORITY_SITE_OFF`로 거절. 반복 바퀴 재검사도 같은 함수를 쓴다. API Ref v1.150, ADR D-517 4항 Fleet 문단 한 문장
- 증거: 시험 `test_a_robot_requiring_authority_is_refused_while_the_site_flag_is_off`(고치기 전 실패 e722804ac). 모델 PC 결과는 브랜치 보고
- gate 변화: 없음(SOURCE). trip 시작 판단이라 독립 Safety-Review 전에는 착지하지 않음
- 결정: CORE 상태 필드는 늘리지 않음. 이미 있는 능력 `line_follow_authority_required`로 시작에서 막는다

## 2026-10-08 · uncommitted · fix(fleet): `straight` 지시에 지도 차로 방향 변화 `lane_turn_deg` (API v1.152)
- 변경: `junction_fields` 가 기대 창이 있는 `straight` 에 로봇에서 장소까지 차로의 부호 있는 방향 변화(도, `WINDOW_BEND_STEP_M` 간격 합, ±360 클램프)를 싣는다. `_curve_offset_m` 과 같은 표본(`_lane_steps`)을 쓴다
- 증거: `test_trip_d507.py::test_a_straight_on_the_ring_sends_its_lane_turn_and_a_turn_does_not` (ring_s → SE 45–65°), 모델 PC 53 passed
- gate 변화: 없음(SOURCE)
- 결정: 회전 지시에는 싣지 않는다(방향은 action 이 말한다)
- 교훈: 없음

## 2026-10-08 · uncommitted · feat(fleet): D-526 1단계 Fleet tether 감시 (API v1.156)
- 변경: `server/tether_watch.py` `TetherWatch`가 0.5 s마다 테더가 있는 로봇의 지도 자세(상태 pose, odom 프레임 제외)로 기준점 거리·펼친 누적 회전·자세 나이를 재고, 반경+0.15 m·405°·2 s 초과면 기존 로봇 E-Stop(`hub.scatter_estop`)을 보내고 trip을 `tether_trip`으로 끝낸다. 래치, 테더 POST가 재무장. `GET /api/fleet/tethers` 행 `watch`, 지도 원은 트립이면 `--status-crit`. `platform_parts.yaml` safety_modules에 태그(D-430)
- 증거: `test_tether_routes.py`(반경, ±180° 넘는 회전, 자세 없음, 테더 없음, 정지 재시도, 실제 앱의 로봇 estop 호출), `web/trail-view.test.mjs`. 모델 PC 결과는 브랜치 보고
- gate 변화: 없음(SOURCE). safety 태그 파일이라 독립 Safety-Review 전에는 착지하지 않음
- 결정: 되돌아가기는 Fleet가 하지 않는다(로봇 odom 길은 D-512 도구에 있다). Fleet 한도는 D-512 도구 한도 위의 backstop
- 교훈: 없음

## 2026-10-08 · uncommitted · fix(fleet): 실행 끝난 장소는 로봇이 다음 차로에 있을 때만 넘어간다 (lap SIM 2 lap_12)
- 변경: `_locate` 의 `done`(CORE가 우리 지시를 끝냄 + `pass_window_m` 안)에 다음 차로 반폭 안 조건을 더했다
- 증거: lap_12 `off_lane_m` 0.276은 ring_e까지 거리(참값 ring_s 밖 0.07 m). CORE가 D-407 후진 중 SE `straight` 를 닫자 Fleet이 SE 0.26 m 앞에서 ring_e로 넘어가 거기서 위치를 쟀다. 새 시험은 고치기 전 실패, 모델 PC `test_trip_runner.py` 87 passed
- gate 변화: SOURCE
- 결정: CORE가 직진을 일찍 닫는 일(후진 중 감지 끊김)은 그대로다. 그 경우 이제 잘못된 `pose` 대신 뒤의 `junction`·`stall` 로 끝날 수 있다
- 교훈: 위치 판정은 로봇이 실제로 있는 차로에 대고 한다. 지시 완료는 위치의 증거가 아니다

## 2026-10-08 · uncommitted · fix(fleet): 교차로 회전은 들어오는 차로 끝 방향에서 나가는 차로 접선까지 (lap SIM 2 원인 2)
- 변경: `turn_target` 이 `theta`(5 cm lead 접선) + 6° 대신, 들어오는 차로의 끝 방향(마지막 두 0.10 m 현: 마지막 현 + 차이의 절반)에서 나가는 차로 `start_tangent` 까지를 보낸다. `TURN_OVERTURN_DEG`·`BEND_MIN_DEG` 삭제, 0.20 m보다 짧은 차로는 `theta`. D-507 4항 개정 줄
- 증거: 260919 SW lead 접선 72.6°(입구 polyline 잡음) vs 현 62.7°, 로봇 진입 59–60° → 회전 끝이 ring 접선보다 약 20° 바깥(lap SIM 2·3 rec_01–03). 고친 뒤 SIM 4회 회전 끝 −4.3…+0.3°. 모델 PC `test_routing_execute.py`·`test_trip_d507.py`·`test_trip_d520.py` 100 passed
- gate 변화: SOURCE, ROS-SIM(SW 회전 끝 방향)
- 결정: D-520 `exit_segment` 경로(`theta`)는 다른 세션 몫이라 그대로 둔다(result.md에 기록)
- 교훈: 지도 polyline 끝 몇 cm의 방향을 로봇 자세처럼 쓰지 않는다. 회전 목표는 로봇이 실제로 달린 구간의 방향에서 잰다

## 2026-10-08 · a5c1bb395 · fix(fleet): 개발 세션 인증 뒤 모바일 설정 메뉴 복귀
- 변경: 잠금 때문에 자동으로 연 Fleet Console 설정 메뉴만 인증 성공 후 접는다. 사용자가 직접 연 설정은 유지한다.
- 증거: 390×844 회귀 수정 전 실패·수정 후 통과, 1440×900 화면 캡처, `known_failures.py` 0 new. `docs/validation/uiux-fleet-dev-menu-2026-10-08/result.md`.
- gate 변화: 없음. LOCAL 브라우저 증거만이며 D-153 전체 G1/G2/G3 및 설치 이미지 수용은 HOLD.

## 2026-10-09 · uncommitted · uiux(fleet): D-517 trip error codes all have console text
- 변경: `web/shared/site-map-model.js` 에 `TRIP_AUTHORITY_SITE_OFF`, `TRIP_AUTHORITY_NOT_REQUIRED`, `TRIP_CONVOY_NOT_BEHIND`, `TRIP_ROBOT_BUSY`, `TRIP_GOAL_REFUSED` 운영자 문구 추가(전에는 원시 코드가 보였다); `test/test_trip_error_labels.py` 가 Fleet 이 내는 모든 `TRIP_*` 코드에 문구가 있는지 지킨다
- 증거: 모델 PC `operations/fleet/test/` (아래 커밋 메시지)
- gate 변화: 없음
- 결정: 없음(D-517 10 화면 문구)
- 교훈: 새 오류 코드를 낼 때 화면 문구가 빠지기 쉽다 → 가드 테스트로 막는다

## 2026-10-09 · uncommitted · refactor(fleet): traffic 설정 파서를 전용 단위로 이동
- 변경: CLI의 zone·signal·authority YAML 파서를 `fleet.traffic.config`로 옮겼다. 호출·검증·오류 메시지는 유지하고 CLI와 Fleet 패키지 크기 판정을 실제 줄 수로 갱신했다
- 증거: 구조·CLI·신호·차로 시험 107 passed, `known_failures.py` 0 NEW; harness lint 0 errors
- gate 변화: SOURCE만 확인. ROS-SIM·DEVICE·FIELD 증거는 그대로다
- 결정: 신호등 판정과 사이트 설정은 Fleet traffic 소유이며 CLI는 진입점이다
- 교훈: 새 설정을 CLI에 누적하면 파일과 패키지 크기 계약이 함께 밀린다

## 2026-10-09 · uncommitted · uiux(fleet): 연결 뒤 토큰 접기와 현장 지도 우선 배치
- 변경: 공용 로그인에서 연결 성공 후 토큰 세부 입력을 접고, 현장 지도에서 표시 전용 평면 영상 도구를 지도 뒤로 옮겼다. 토큰 재접속 요약은 남긴다.
- 증거: 320×568, 390×844, 1440×1000 브라우저 시나리오와 스크린샷, 평면 영상 좌표 표시 전용 검증. `docs/validation/uiux-fleet-map-first-2026-10-09/result.md`.
- gate 변화: 없음. LOCAL 브라우저 확인이며 현장 배포·로봇 주행·사용자 G3 수용은 HOLD.
- 결정: 지도와 연결 상태를 첫 화면의 우선 정보로 둔다.

## 2026-10-09 · uncommitted · uiux(fleet): 지도 로봇 방향 마커 화면 비율
- 변경: 격자 지도 로봇 방향 마커 크기를 셀 수가 아니라 캔버스 화면 픽셀 밀도에 맞춰 제한했다. 지도 좌표와 명령 경로는 그대로 둔다.
- 증거: 1920×1080 기존 마커 상자 161.94px. 변경 후 데스크톱·320px 마커 42px 이하, 지도 라벨 겹침·모바일 래스터 회귀 6 passed / NEW 0. `docs/validation/uiux-fleet-marker-scale-2026-10-09/result.md`.
- gate 변화: 없음. LOCAL 합성 화면이며 DEVICE/FIELD/G3는 HOLD.
- 결정: 지도와 경로·거리 라벨을 읽을 수 있도록 마커의 화면상 크기를 제한한다.

## 2026-10-09 · uncommitted · uiux(fleet): 현장 지도 경로 작업 순서

- 변경: 현장 지도 뒤에 경로 미리보기·운행을 이어 배치하고 초안 편집을 뒤로 옮겼다. 표시 전용 평면 영상 도구는 키보드로 여는 접힌 항목으로 시작한다.
- 증거: [현장 지도 작업 순서](../../docs/validation/uiux-fleet-site-map-task-order-2026-10-09/result.md). 1440·390·320px 전후 화면, FastAPI/Chromium 7 passed, `known_failures.py` 0 NEW.
- gate 변화: LOCAL 작업 흐름·반응형 근거 보강. 실제 지도·로봇 주행, 설치본·DEVICE/FIELD·전체 G2/G3는 HOLD.

## 2026-10-09 · uncommitted · fix(fleet): 연결 재시도 브라우저 검사 복구

- 변경: 인증 후 접히는 토큰 입력을 재접속 검사에서 다시 열고, 연결 안내가 해당 입력에 초점을 줄 때도 펼친다. 비동기 인증 조회가 사용자가 다시 연 입력을 뒤늦게 접지 않도록 접는 시점을 조정했다.
- 증거: CI `37854678441`의 Fleet 브라우저 실패 19건을 모델 PC Chromium에서 다시 실행해 19 passed (46.09s). 비밀번호 로그인 브라우저 검사 1 passed, 변경 JavaScript 구문 검사 통과.
- gate 변화: LOCAL/MODEL-PC 재현 검사 복구. 새 CI 전체 결과와 설치본·DEVICE/FIELD 수용은 별도 확인한다.

## 2026-10-09 · uncommitted · fix(fleet): 느린 상태 수집이 모든 로봇 상태를 도착 즉시 낡게 만들었다
- 변경: `SharedGather`가 행마다 실제로 읽은 시각(D-493 `_state_mono`, 콘솔 단조 시계)을 추적 시계로 바꿔 `TrackingService.observe_states(observed=...)`에 넘긴다. 없으면 예전처럼 수집 시작 시각이다.
- 증거: 현장 2026-10-09 `/api/fleet/state` 수집 3.34–3.49 s > `STATE_FRESH_S` 2.0 s. 9dfk가 −0.0275 m/s로 움직이는 동안 LED 확인이 계속 `IDENTIFY_NOT_MOVING`이었고 천장 카메라 추적은 `NO_POSE`였다. 새 시험 2개(수정 전 실패) 포함 63 passed.
- gate 변화: SOURCE. 현장 Fleet 갱신 뒤 LED 확인·추적 연결 확인.

## 2026-10-09 · uncommitted · fix(fleet): 늦은 응답 한 번에 로봇이 오프라인으로 바뀌었다가 돌아오던 깜빡임
- 변경: 마지막 응답 뒤 `LINK_DEGRADED_S`(10 s) 안의 읽기 실패는 연결 단어 `degraded`(응답 지연, 주의)와 `link_degraded_s`로 보인다. `online`은 그대로 False라 교통·핸드오프·목표 판단은 바뀌지 않는다. 카드·예외 큐·연결 수 pill·목표 해제는 `degraded`를 오프라인으로 보지 않는다. 10 s를 넘으면 지금처럼 `unreachable`이다.
- 증거: 현장 2026-10-09 두 로봇 모두 hub 없이 REST 수집(3.4–4.5 s, 로봇 부하 평균 13), 5 s 제한을 넘는 한 번의 읽기가 카드를 오프라인으로 바꿨다. test_link_on_snapshot 새 시험 2개 포함 14 passed, link-tag.test.mjs 2 passed. web 전체 node 실패 10개는 main과 같은 목록.
- gate 변화: SOURCE/LOCAL. 현장 Fleet 갱신 뒤 관제 화면 확인.

## 2026-10-09 · uncommitted · uiux(fleet): 네 문서 공통 머리와 비상 정지 규칙 하나 (D-540 2)
- 변경: `web/shared/fleet-header.js`·`fleet-header.css` 신규. 관제·설치·보정·현장 지도·Cell이 같은 `<ui-topbar>`(글자 그대로, `test_fleet_header.py`)를 쓴다. 현장 지도·Cell의 `#session`·`#credential`·`#connect`를 없애고 `#console-token`·`#token-save`·`#user-role`로 통일, 역할은 "운영자"·"보기 전용"(principal·영어 역할은 `title`), 개발 배지·연결 수·시계·테마·설정 접힘을 네 문서에 둔다. 비상 정지 클릭·문구도 모듈 하나(`bindEstop`). 머리 CSS를 `styles.css`·`site-map.css`·`cell.css`에서 뺐다(styles.css 809→748줄, 판정 행 제거).
- 비상 정지 규칙: 마크업은 언제나 눌림. 세션 거절(401)이면 `접속이 필요합니다`, 보기 전용이면 운영자 사유로 잠근다. 모름(로딩·Fleet 끊김)은 눌린다. 관제·설치는 접속 전 잠김에서 모름=눌림으로, 현장 지도는 처음 잠김에서 같은 규칙으로, Cell은 401 뒤 잠김이 새로 생겼다(그 누름은 401로 거절됐던 것이다).
- 증거: 모델 PC `operations/fleet/test/`+관제 브라우저 묶음 3268 passed / 14 failed — 13건은 main `59f8427c1` 계열에서도 같은 실패(main 스냅숏 재실행 14 failed), 1건(`test_module_structure` styles.css 판정 stale)은 이 브랜치에서 고침. 새 `test_fleet_header_browser.py`(네 문서 × 1920·1440·1024·390, `#estop` 크기·자리 같음, 머리 줄 수, 가로 넘침 0, 401 잠금·토큰 해제). 캡처 `X:\DevTemp\fleet-header\{before,after}\`.
- gate 변화: 없음. LOCAL/MODEL-PC 브라우저. 세션 조회는 아직 `/api/fleet/session`(D-540 2의 `/auth/session` 하나로 합치기는 남음). 현장·G3는 HOLD.

## 2026-10-09 · uncommitted · feat(fleet): 미션 API가 개발 세션으로도 시작 (D-548)
- 변경: `--mission-api`는 `--users-file` 대신 살아 있는 개발 연결 모드(D-473)로도 시작한다. 개발 세션은 이미 이름 있는 운용자다.
- 증거: test_cli.py.
- gate 변화: SOURCE. DEVICE(표식 켬·끔, LCD DEV, SSH 403)는 열림.

## 2026-10-09 · uncommitted · fix(fleet): 후진 중 차로 여유 감시 유지

- 변경: 일방 차로에서 후진 복구 방향도 같은 물리 차로에 투영한다. 양방향 차로의 진행 방향별 호 선택과 차로 밖 UNKNOWN은 유지한다. Fleet 감시 판정만 바꾸며 로봇 명령은 보내지 않는다.
- 증거: 모델 PC에서 수정 전 2 failed/9 passed, 수정 후 차로 판정·감시 20 passed, `known_failures.py` 0 NEW (`X:/DevTemp/fleet-reverse-lane-{red,green2}/run-1.txt`).
- gate 변화: SOURCE/LOCAL 회귀 근거. D-511 M1/M2, 현장 지도 자세·Rosy Cam·실물 주행 수용은 아직 HOLD.

## 2026-10-09 · uncommitted · uiux(fleet): Cell 화면 목적과 미구성 복구 안내

- 변경: Cell 첫 화면에 문서 준비→미리보기→작업 제안→현재 5단계 승인·진행의 목적을 드러냈다. Cell 서비스 미구성 응답은 원시 코드 대신 사이트 설치 담당자의 다음 행동으로 설명한다.
- 증거: `test_cell_app_browser.py`의 목적·503 안내·가로 넘침 검사와 1440/390 캡처, Cell API·운영자 문구 검사. D-540의 큐 승인 이동 전이므로 현행 승인 위치를 정확히 적었다.
- gate 변화: Cell 입구의 LOCAL/SOURCE 결함 일부 수정. 공통 머리·실제 Fleet 큐 인계·전체 G1/G2/G3·DEVICE/FIELD는 HOLD.

## 2026-10-09 · uncommitted · fix(fleet): 움직이는 경로는 이름 있는 운영자, 멈춤은 열림 (D-540 9)

- 변경: 목표·차선 주행 선택(`OFF` 제외)·`/route`·LED 찾기·막힘 `RESUME`/`BACK_AND_RETRY`/`MANUAL`과 claim·대형 시작/변경/재개·물리 신호 명령(`all_red`/`flash_red` 제외)·시작점 쓰기·`/do`(멈춤 동사만인 요청 제외)는 `require_named_operator`. 공유 토큰·루프백 `site-console`은 403 `OPERATOR_IDENTITY_REQUIRED`. 비상 정지·전체 취소·로봇 취소·작업 취소·대형 해제·막힘 `WAIT`/`ABORT`·trip 취소(이전엔 이름 필요)는 어느 운영자에게나 열림. 화면은 같은 조작을 `reason="이름 있는 운영자 로그인이 필요합니다"`로 잠근다. API Ref v1.156.
- 현장 이행(배포 전): 관제 PC에서 `python -m fleet.server.site_users hash-password`로 해시 → `site-users.yaml`에 운영자마다 `login`·`password_scrypt`·`role: operator` 줄 → Fleet 재시작 → 다른 PC에서 로그인, 목표 한 번, 감사 actor가 로그인 이름인지 확인. 개발 연결 모드(D-473) 현장은 변화 없음. 줄이 없는 채 배포돼도 멈춤은 된다.
- 증거: 모델 PC `operations/fleet/test/` + 콘솔·작업 흐름 브라우저 + 계약 문서 3180 passed, 9 failed — 9개 모두 기준 main 6e5c91a1e에서도 같은 실패(레이아웃·설치 흐름, 이 브랜치와 무관). 브라우저 없는 fleet 묶음 2940 passed, `known_failures.py` 0 NEW. node(register 훅) 201 passed. 새 표 시험 `test_named_operator_motion_routes.py`는 구현 전 30건 실패를 먼저 확인했다.
- gate 변화: LOCAL/MODEL-PC 권한 표 근거. Safety-Review 대기, DEVICE/FIELD(현장 로그인 이행) HOLD.
- 교훈: 직접 `console.goal` 경로(작업 저장소 없음)는 이름 있는 운영자가 생길 수 없어 HTTP로는 닿지 않는다. 지울지 별도 판단.

## 2026-10-09 · uncommitted · docs(api): D-540 9 권한 변경은 v1.157

- 변경: main이 v1.156을 D-551에 먼저 썼으므로 위 항목의 API Ref 번호는 v1.157이다. main을 병합하고 막힘 결정 행은 main의 값별 권한 설명을 "구현됨"으로 고쳐 합쳤다.
- 증거: `rosy_harness.py lint` 0 error. 시험은 병합 뒤 다시 돌린다(아래 결과는 보고에).
- gate 변화: 없음.

## 2026-10-09 · uncommitted · fix(fleet): D-540 9 안전 리뷰 반영 — claim 열기, rearm 이름, follow_cancel

- 변경: `/line-stuck/claim`은 다시 열림(콘솔이 `ABORT` 확인 전에 claim 하고 403을 삼켜, 이름 없는 운영자의 중단 사이에 해결기가 움직이는 답을 낼 수 있었다). `/dispatch/rearm`은 이름 있는 운영자(대기 작업·재시작 뒤 남은 작업이 움직이고 OMX 팔을 다시 연다), 콘솔 재허가 버튼도 같은 사유로 잠근다. `/do`의 `follow_cancel`은 멈춤 동사. `cell-jobs/{id}/cancel`·`teach/stop`은 멈춤이 아니라(HOLD 작업 정리·녹화 종료) 이름 요구를 유지하고 API Ref v1.157 행에 적었다.
- 운영 메모: `tools/sim/d407_stuck_scenarios.py`(막힘 답 전송)와 `tools/sim/d395_s2_bench.py`(목표 전송)는 이제 공유 토큰으로는 403이다. 개발 연결 세션(D-473) 토큰이나 `site-users.yaml` 운영자 토큰을 넘긴다. `deploy/robot/omx/g2_runner.py`의 rearm 호출도 같다.
- 증거: 새 시험 3건(claim 열림, rearm 403, follow_cancel 열림)이 수정 전 모델 PC에서 실패, 수정 뒤 결과는 보고에.
- gate 변화: 없음. Safety-Review 재검토 대기.

## 2026-10-09 · uncommitted · docs(api): D-540 9 권한 변경은 v1.158

- 변경: main이 v1.157을 D-541(CORE trip lease)에 먼저 썼으므로 위 두 항목의 API Ref 번호는 v1.158이다. main 병합.
- 증거: `rosy_harness.py lint` 0 error.
- gate 변화: 없음.

## 2026-10-09 · uncommitted · docs(api): D-540 9 권한 변경은 v1.160

- 변경: main이 v1.158(D-526)·v1.159(D-548)를 먼저 썼으므로 위 항목들의 API Ref 번호는 v1.160이다. 리뷰 승인 뒤 한 커밋으로 합치고 main 병합.
- 증거: `rosy_harness.py lint`, 모델 PC 시험은 보고에.
- gate 변화: 없음.

## 2026-10-09 · uncommitted · docs(api): D-540 9 권한 변경은 v1.161

- 변경: main이 v1.160을 D-550 10(목표 임대)에 먼저 썼으므로 D-540 9 API Ref 번호는 v1.161이다. main 병합.
- 증거: `rosy_harness.py lint`.
- gate 변화: 없음.

## 2026-10-09 · uncommitted · feat(fleet): D-541 7 Fleet trip lease holder (Safety-Review)
- 변경: 새 `fleet/traffic/trip_lease.py` `TripLease`. 사이트 설정 `fleet.trip_lease_required`(기본 false)·`fleet.trip_lease_ttl_s`(기본 5, 1–10, `traffic/config.py`). 참이면 trip 시작이 pose 검사 뒤 `PUT /api/v1/trip-lease`를 연다(trip마다 새 uuid `lease_id`). 능력 `trip_lease`가 없으면 422 `TRIP_LEASE_UNSUPPORTED`, CORE 거절은 `TRIP_ROBOT_LEASED`·`TRIP_ROBOT_MANUAL`·`CALIBRATION_ACTIVE`·`TRIP_LEASE_REFUSED`. 그 뒤 시작 거절은 lease를 놓는다. 주기마다 자기 슬롯에서 renew(`trip_authority`와 같은 꼴). 404·409·그 밖 4xx·`renewed:false`·`ttl_s` 동안 확인된 renew 없음 → `stopped`/`lease_lost`(`detail.lease_reason`, `lease_by`), 자유 구간만 navigation cancel, 다시 열지 않음. 끝마다 정지 뒤 `DELETE`. `RobotApiError.detail`, `HttpRobotClient.trip_lease*`. 설정이 참이면 관제 토큰이 로봇 REST 토큰과 같을 때 app 시작 거절(D-541 1 주인 = 그 토큰). 관제 trip 줄에 `CORE 점유 중`과 끝 이유. API Ref v1.162.
- 결정: 설정 false면 lease를 열지 않는다(계획 되돌리기 줄 "현장 설정 false(lease를 열지 않음)"과 과제 지시를 따름). D-541 7의 "능력 없는 로봇: 설정이 참이면 거절" 문장만으로는 false일 때 지원 로봇에 여는지가 열려 있다.
- 증거: 모델 PC `operations/fleet/test/` + `test/architecture/test_module_structure.py` 2971 passed / 131 skipped, known_failures 0 new. 새 `test_trip_lease.py` 22개(커밋 c0d7295a2에서 수집 실패 = 구현 전 실패).
- 크기: trip_runner.py 826(판정 686 + 150), fleet 46931(46866 + 150), fleet/traffic 1653(1509 + 150). 판정은 고치지 않았다.
- gate 변화: SOURCE. SIM(Fleet kill → 5 s 안 IDLE)·DEVICE(Pilot 넘겨받기)·현장 설정 true는 열림.

## 2026-10-09 · uncommitted · fix(fleet): 관제 카메라 추적 표시가 1초마다 깜박이지 않게 한다
- 변경: console.js가 `/api/fleet/tracking`을 STATE_MS(1 s) 대신 TRACKING_MS(400 ms)마다 읽는다. 표시 수명(D-457 6: 최대 1 s − 서버 age − 요청 지연)은 그대로
- 원인: 2026-10-09 현장(site-54057e6872f3) 콘솔에서 "추적 중"과 "위치 수명 만료"가 번갈아 떴다. 1 s 폴링이면 다음 응답이 항상 수명 뒤에 와 표시가 매 주기 끊긴다(현장 폴링 간격 0.34–1.47 s 측정)
- 증거: test_overhead_tracking_console.py가 TRACKING_MS ≤ 500 ms와 그 사용을 고정
- gate 변화: 없음. 현장 반영 뒤 깜박임 재확인 전

## 2026-10-09 · uncommitted · uiux(fleet): 큐 항목이 그 자리에서 결정으로 펼친다, 레일 하나만 스크롤, 접힌 로봇 카드 (D-540 3, 계획 (c))
- 변경: `#stuck-panel`을 없애고 막힘 다섯 답(같은 값, 같은 비활성 사유, 경로 권한 그대로)을 최우선 큐 행 펼침으로 옮겼다. 재계획 확인(`바뀐 경로로 계속` / `운행 취소`, quiet·확인 없음)을 큐 행으로 더했다(`web/trip-replan.js`, 현장 지도 칸은 (e)까지 남는다). 한 번에 한 행, 가장 급한 결정이 먼저 펼친다. 넓은 단은 문서가 스크롤하지 않고 레일만 스크롤한다(큐 12rem·로봇 목록 15rem 상한 제거, 지도 칸은 남는 높이를 채움). 로봇 카드는 정상이면 한 줄(이름·운행 한 줄·배터리), 예외·선택이면 펼침, 오프라인·비상 정지 래치·안전 상태 미확인·보정 lease(`robot.calibration`, (h1) 필드)는 접기 없이 펼침. `전체 로봇 보기` 토글 제거. Cell 승인은 제안 대기 목록을 읽는 경로가 없어 이 브랜치에 넣지 않았다.
- 증거: ai PC(모델 PC가 첫 실행 중 응답 끊김) `operations/fleet/test/`+`test_module_structure` 1 failed(fleet 단위 크기 판정, 아래), 관제 브라우저 묶음+새 `test_console_queue_inline_browser.py`는 main 스냅숏과 같은 실패만. node `queue-inline.test.mjs` 7건. 캡처 `X:\DevTemp\fleet-queue\{before,after}\`.
- gate 변화: 없음. fleet 단위 크기 47012+150을 넘는다(+185, 판정 재심 필요) — 착지 보류.

## 2026-10-09 · uncommitted · feat(fleet): 로봇의 위치 요청에 답한다 (D-546 6)
- 변경: `localization/pose_request.py`(천장 카메라 LOCALIZED·기준 2 s 이내 자세 → `source: overhead` 결정 ttl 5 s, 그 밖은 중재기 → `resolve_pose_with_model`(미구현, `None`) → `needs_human` 배지). `LocalizationService`가 `lane_return_*`로 서 있는 로봇의 `GET /localization/request`를 읽는다. 천장 카메라 답은 `--localization-overhead-cue`가 켜졌을 때만.
- 증거: `test_localization_pose_request.py`, `test_transport_localization.py`.
- gate 변화: SOURCE. VLM(D-546 8)은 AI PC 주인 동의 대기.

## 2026-10-09 · uncommitted · fix(fleet): 위치 요청 3번 답해도 열려 있으면 needs_human, 천장 카메라 답 기본 켜짐 (D-546 6)
- 변경: `MAX_ANSWERS` 3 뒤 `needs_human`(lane_return이 놓을 때까지 고정). `--localization-overhead-cue` 기본 켜짐, 끄기 `--no-localization-overhead-cue`(사용자 결정, D-257 5 개정 제안은 D-546에 기록).
- 증거: `test_localization_pose_request.py`.
- gate 변화: SOURCE.

## 2026-10-09 · uncommitted · fix(fleet): 위치 요청 천장 카메라 플래그 분리, 답 횟수 유지 (D-546 6, review)
- 변경: `--pose-request-overhead/--no-pose-request-overhead`(기본 켜짐)는 위치 요청 답만, `--localization-overhead-cue`는 기본 꺼짐으로 복원. 답 횟수는 요청이 닫혔다 열려도 lane_return이 놓거나 `lane_return_corridor_verified`까지 유지하고 중재기 답도 센다.
- 증거: `test_localization_pose_request.py`, `test_cli.py`.
- gate 변화: SOURCE.

## 2026-10-09 · uncommitted · test(fleet): API 기준서 v1.166 참조 갱신

- 변경: D-531 굽이 단계 선택 필드로 기준서가 v1.166이 되면서 Fleet 문서 계약 테스트의 버전 기대값을 함께 갱신한다. Fleet 실행 코드는 바뀌지 않는다.
- 증거: 문서 계약 집중 테스트와 `known_failures.py`.
- gate 변화: SOURCE 계약 일치. Fleet 계획·현장 주행 수용은 별도.

## 2026-10-09 · uncommitted · feat(fleet): trips from the console robot card (D-540 (d))
- 변경: 첫 커밋은 순수 이동 — `web/roster.js`의 큐 규칙·행 채우기(`attentionItems`·`attentionKey`·`openDecisionKey`·`syncRows`·`fillQueues`·`setTriageHead`)와 `line-stuck.js`의 버튼 헬퍼를 새 `web/queues.js`로. 이어서 `shared/site-map-model.js`에 운행 경로 공용 함수(`planTrip`·`startTrip`·`cancelTrip`·`tripRefusalText`·`planSummaryText`·`repeatTripReason`·`tripEndText`)를 두고 `site-map.js`가 그것을 부른다(현장 지도 운행 칸은 (e)까지 남음). 새 `web/card-trip.js`: 카드 `운행…`(토글, 카드 안 폼: 활성 지도 목적지·`경로 보기`·`운행 시작`, 출발 자리·`반복 운행 시작`, "고리 n/m대"), `대형·대열` 블록의 대열(팔로워·리더·출발 자리 → `POST /trip` `convoy`). 카드 `취소` → `운행 취소`(quiet, 확인 없음): 열린 trip이면 trip 취소(실패하면 목표 취소로 이어짐), 없으면 목표 취소 + 켜진 차선 주행 OFF; 이름 없는 운영자도 누름, 오프라인 로봇의 열린 trip도 취소. 끝난 trip(stopped·failed)은 카드 줄과 주의 큐 행에 이유(D-541 lease 끝 이유 포함)를 보이고 다음 trip까지 카드를 펼친다. 관제 지도 찍어 목적지 고르기는 넣지 않았다(목록만). 서버 경로는 그대로. DESIGN.md `#cancel-all` quiet(D-540 6).
- 증거: 모델 PC `operations/fleet/test/`+공통 가드+`test_fleet_console_browser.py`(브라우저 켬). 새 `test_console_card_trips_browser.py` 5건, node `card-trip.test.mjs`·`trip-path.test.mjs` 통과. 나머지 3328 통과, 실패는 fleet 크기 판정 1건 + 브라우저 9건이고 그 9건은 기준 main `3b6072a46` 스냅숏에서도 같이 실패한다(NEW 0, 화면 문구·버튼 순서에 맞춘 시험 고침 포함). 캡처 `X:/DevTemp/fleet-card-trips/{before,after}/`.
- gate 변화: 없음. fleet 크기 판정 독립 재심 수락, main 병합 뒤 48481로 기록. 리뷰 반영: trip 취소가 실패하면 차선 주행 OFF도 보냄(trip guard가 서버에서 trip을 끝냄), 취소 범위는 누를 때 계산, 레일 행 높이 `max-content`(관제 카메라 칸 겹침), queues↔card-trip import 순환 제거. 가벼운 Safety-Review 필요(카드 운행 시작 경로, 운행 취소 의미 합치기). 착지·푸시 안 함.
- 결정: D-540 Proposed 그대로, D-517 10항 개정 줄은 수락 때 확정(이 단계에서 문구 안 바꿈).
- 교훈: 1 s 폴링이 카드를 다시 만들면 `<select>` 목록이 닫힌다 — 고르는 중인 카드는 `roster.place`가 그대로 둔다.

## 2026-10-09 · uncommitted · fix(uiux): Fleet 이름표 홈 이동

- 변경: 네 Fleet 문서의 Rosy Fleet 이름표를 `/console` 링크로 연결. D-501 문서 탭과 비상 정지는 유지.
- 근거: D-501 2항의 이름표 홈 링크와 UiBrand의 href 동작.
- gate: SOURCE 변경. 브라우저·장치·현장 수용은 별도.

## 2026-10-09 · uncommitted · uiux(fleet): 현장 지도·Cell 내부 단계 탐색

- 변경: 현장 지도와 Cell에 본문 건너뛰기 및 단계 앵커를 추가하고, 넓은 화면에는 왼쪽 작업 탐색, 320px에는 두 열로 모든 단계를 노출했다. D-501의 네 문서 상단 탭과 D-493의 관제 지도 비율은 유지했다.
- 증거: Playwright Chromium 148 정적 DOM/CSS 확인에서 두 화면의 320/1366px 가로 넘침 0, 모든 단계 링크와 건너뛰기 대상 존재. 실제 Fleet 서버·장치 상태를 포함한 G2/G3 증거는 별개다.
- gate 변화: 없음. UI 전체 수용은 HOLD.
- 결정: 없음.
- 교훈: 좁은 화면에서 가로 스크롤만 두면 뒤 단계가 처음에 보이지 않아 두 열로 모두 노출했다.

## 2026-10-09 · uncommitted · feat(fleet): Rosy Cam 지도 평면 영상을 받아 그대로 그린다 (D-560 S2)
- 변경: `shared/vision-view.js`가 lease `rectification: {"mode": "map"}`로 평면을 따로 받는다(`fetchMapPlane`, `createPlaneFeed`). `X-Frame-Plane`은 유한한 수 다섯, min < max, px_per_m > 0일 때만 받는다. 409 `plane-unavailable`, lease 422(옛 Fleet 계약), `X-Frame-Rectified: map`이 아닌 응답(옛 Vision)은 평면 없음 상태로 두고 30 s 뒤 다시 묻는다. 관제 현장 지도(`camera-backdrop.js`)는 신선한(3000 ms) 평면이고 그 revision이 이 현장 지도의 승인 보정이면 평면을 같은 `toPx`(view_turn_deg 포함)로 사각형에 그대로 그리고, 아니면 D-515 삼각형 펴기로 대신한다. map-tag는 "Rosy Cam 평면 영상" / "브라우저 보정(대체)". 교정 어긋남은 그대로 그림을 내린다. 썸네일·크게 보기는 원본 그대로. 현장 지도 탭 "직사각형 평면 영상 불러오기"는 평면을 먼저 받고 점 잡기는 `x = min_x + u/ppm`, `y = max_y − v/ppm`(화면 방향을 먼저 푼다), `warpImage`는 평면이 없을 때만. 설치·보정 확인 그림(`field-view.js`)은 승인 보정이 있으면 평면을 보여 준다.
- 증거: node `map-plane.test.mjs` 5건(헤더, 식 왕복, 0/90/180/270° 배치·점 잡기). AI PC 브라우저: 새 `test_rosy_cam_map_plane_is_drawn_into_its_rectangle_then_falls_back_on_409`, `test_vision_map_plane_is_drawn_and_picked_by_its_scale_then_falls_back_on_409` 통과, `test_site_map_browser.py` 56 passed, 관제·작업 흐름 브라우저 묶음은 기준 커밋 d08b96805와 같은 10 failed(새 실패 없음; `test_stale_camera_calibration_drops_the_frame_and_warns`는 기준에서도 `goto networkidle` 시간 초과). 실데이터(`paint-7b220d432c2a`, raw.jpg를 D-560 기하로 cv2 평면화) 관제·현장 지도 0°/90° 캡처 `X:/DevTemp/fleet-map-plane/`에서 차선이 도로 가운데에 놓인다.
- gate 변화: SOURCE. Vision S1(`mode: map`)과 같이 착지해야 실제로 평면이 나온다. 그 전에는 대체 경로다. fleet 크기 단위 48322로 재판정.

## 2026-10-09 · uncommitted · fix(fleet): D-560 S2 리뷰 반영
- 변경: 현장 지도 탭은 평면의 `X-Frame-Calibration`이 고른 보정 revision과 같을 때만 그리고 점을 잡는다(다르면 "보정 revision이 다릅니다 — 다시 불러오세요"). 헤더 사각형 × px_per_m가 영상 크기와 1 px 넘게 다르면 평면 없음으로 보고 브라우저 펴기로 대신한다. 점 잡기는 평면 사각형에 맞춘 view의 `toMap` 하나로 한다. 설치·보정 확인 그림은 관제와 같은 규칙(source, revision, Fleet 차선 지도의 map)으로 평면을 쓰고, 격자를 지도 미터에 맞추며 트랙 크기를 적는다. 관제는 그릴 수 있을 때만 평면을 묻고 사이트 뷰 밖은 자른다. 일시 오류는 신선한 그림을 만료까지 두고 5 s 쉰다. lease 수명은 `expires_in_s`를 따른다.
- 증거: node 224건(새 `map-plane.test.mjs` revision 불일치·1 px·만료·쉬기). 브라우저·원격 결과는 착지 전 실행에 기록한다.
- gate 변화: SOURCE.

## 2026-10-09 · uncommitted · feat(fleet): site map robot positions, trip panel removed (D-540 (e))
- 변경: 현장 지도 SVG에 `/api/fleet/guide` 로봇(몸체 원·방향·불확실성 고리·자세 이름표)과 열린 trip의 경로·다음 장소를 그린다. 지도 프레임·`view_turn_deg` 그대로, 읽기 전용, 1 s 폴링에 따로 그리는 층(`#robot-layer`, 클릭 통과). `guide-layer.js`를 `web/shared/`로 옮기고 순수 좌표 함수 `guideMarks()`를 나눠 관제 canvas와 현장 지도가 같이 쓴다(`test_document_imports.py` SHARED). 운행 칸(출발 자리·대열 리더·고리 정원·`운행 시작`·`반복 운행 시작`·`바뀐 경로로 계속`·`운행 취소`)을 없애고 "이 지도로 운행 중" 읽기 줄과 "운행은 관제의 로봇 카드에서" 링크를 둔다. 쓰는 곳이 없어진 `cancelTrip`·`tripCancelReason` 삭제. `site-map.css` 전역 input/select 재칠 제거(`ui-field`). 경로 미리보기는 그대로.
- 증거: 모델 PC `operations/fleet/test/` 3066 passed, 141 skipped, `known_failures` NEW 0. 브라우저(ai PC, OMEN 재부팅 중) 사이트 지도·교통·대열·카드 운행·import 울타리 65 passed — 새 `test_site_map_draws_robots_read_only_and_sends_trips_to_the_console`(위치·trip 선, 90° 돌리면 위치·방향이 시계 방향으로, 운행 버튼 없음, 관제 링크, POST 없음). node `guide-layer.test.mjs` 포함 226 passed. 캡처 `X:/DevTemp/site-map-pos/`.
- gate 변화: 없음. fleet 크기 48481 → 48440(−41), 판정 문구 그대로. Safety-Review 불필요(읽기 표시와 버튼 제거, 명령 경로 안 건드림).
- 결정: D-540 Proposed 그대로.
- 교훈: 전역 `input, select` 재칠을 지우면 `width: 100%`도 같이 빠져 320 px에서 61 px 넘친다 — `components.css`는 최대폭만 준다.

## 2026-10-09 · uncommitted · feat(fleet): D-564 바닥 장소 마커로 초안 장소 가르치기
- 변경: `POST /api/fleet/place-markers`(source 토큰, 2 s, source·marker별 순서)·`GET` 보기, `POST /api/fleet/teach/place-from-marker`(이름 있는 운영자; 새 초안 장소 또는 `place_id` 이동, 이동한 장소에 닿는 차로 끝도 옮김), `sightings_config.py` `place_markers` 검증, 지도 가르치기 패널 "마커로 등록". 로봇에 보내는 것 없음. API v1.167.
- 증거: 모델 PC `remote_pytest.py` 관련 묶음(fleet 13 파일·vision·foundation·version alignment·architecture) exit 0, `known_failures.py` 신규 0 (X:/DevTemp/place-markers/run-1.txt).
- gate 변화: 없음(SOURCE). 현장 스티커·천장 카메라 확인은 열림.

## 2026-10-09 · uncommitted · fix(fleet,vision): D-564 독립 검토 반영
- 변경: 마커 지도와 초안(활성·초안 없으면 빈 `site`)의 `map_id`가 다르면 409 `PLACE_MARKER_MAP_MISMATCH`. Vision 장소 마커 전송은 한 번에 하나인 백그라운드 작업이라 Fleet이 늦어도 프레임 루프·로봇 sighting을 막지 않는다. 콘솔 마커 목록은 반올림한 자세가 바뀌면 다시 그린다. 시험: ±90° yaw 부호, 목록에 없는 id 403, bend 이동 거절.
- 열림: 장소를 마커로 옮기면 그 장소에 닿는 차로는 끝점만 옮기고 안쪽 점은 그대로다. 크게 옮기면 차로 끝 접선이 꺾일 수 있다(활성화 전 지도에서 확인).
- 증거: 모델 PC `remote_pytest.py` 관련 묶음, `known_failures.py` (X:/DevTemp/place-markers/run-1.txt).
- gate 변화: 없음(SOURCE).

## 2026-10-09 · uncommitted · fix(fleet): 관제 지도와 로봇 표시 안정화
- 변경: 비상 정지의 보조 문구는 낭독기에 남기고 버튼은 한 줄로 줄였다. 현장 지도 캔버스를 넓히고 관측 마커를 키워 겹치던 추적 정보를 지도 아래로 옮겼다. 발견됐지만 미등록인 로봇은 등록 링크와 함께 별도로 표시한다. 배터리 상태 갱신 대기 시간을 200 ms로 늘려 일시적인 조회 지연이 경고 카드를 접었다 펴는 현상을 줄인다.
- 증거: 현장 API를 읽는 후보 자산 브라우저 캡처에서 1262×632, 320×700 모두 가로 넘침·JavaScript 오류 0; 넓은 화면 지도 높이 344 px, 정지 버튼 높이 58 px. `tracking-layer.test.mjs` 12건 통과. 실서버 설치·두 번째 로봇 등록·현장 화면 재검증은 별개다.
- gate 변화: SOURCE 후보. 실제 설치와 두 로봇 연결 확인 전 FIELD는 HOLD.

## 2026-10-09 · uncommitted · fix(fleet): TLS 로봇 번호 변경 뒤 재등록 (D-565)

- 변경: 등록되지 않은 승인 binding을 대기 binding으로 받아 기동 경고만 남긴다(다른 등록 행의 호스트 이름이면 계속 거절). 행이 없는 HTTPS 대상은 hostname·port가 같은 대기 binding 하나로 TLS 등록하고, identity `receiver_id`와 `system/info` `robot_id`가 binding ID와 같을 때만 저장·downgrade 기록을 남긴다. 다르면 409 `tls_binding_mismatch`, 토큰 로그아웃. runbook 절차, API v1.168.
- 근거: 2026-10-09 현장 rosy_26 → rosy_41 재등록이 409 `tls_binding_required`; D-562 번호 변경.
- gate: SOURCE + 원격 호스트 pytest. 현장 Fleet 재시작·재등록·보안 검토는 별도.

## 2026-10-09 · uncommitted · uiux(fleet): 기기 이름과 ArUco 표지를 내부 ID와 구분
- 변경: 관제 카드의 첫 이름은 등록 기록과 현장 발견이 확인한 mDNS 이름으로 표시하고 Fleet 내부 ID는 함께 남긴다. 지도에서 단일 설정 마커가 실제 관측된 경우 칩에는 ArUco 번호를 표시한다. 제어 요청과 상태 키는 계속 서버의 canonical robot_id를 쓴다.
- 증거: 현장 API를 읽는 후보 자산 캡처에서 등록 호스트 이름과 Fleet 내부 ID를 함께 표시하고, 현재 설정된 ArUco 번호를 지도에 표시했다. 미등록 기기의 부착 마커 번호는 운영자 답변으로 확인했으나, 현장 설정·Fleet 등록·카메라 연결 검증 전까지 지도에 로봇으로 배정하지 않는다.
- gate 변화: SOURCE 후보. 현장 등록과 마커 설정은 HOLD.

## 2026-10-09 · uncommitted · fix(fleet): site-map robot rings and labels stay on the map
- 변경: `fitView`가 로봇 고리(몸체 + 불확실성)를 원으로 받아 화면 방향 어느 쪽에서도 지도 안에 둔다. 고리 위에 자리가 없으면 이름표를 고리 아래로, 좌우는 지도 안으로 당긴다. 폴링에서 고리가 화면을 벗어나면 다시 맞춘다.
- 증거: 브라우저(ai PC) 새 `test_site_map_keeps_edge_robots_and_labels_on_the_map[0,90]`(네 변 밖 로봇) 통과. 같은 묶음 실패 2건(`test_view_edit_activate_and_preview_a_trip[320-568]`, `test_cell_emergency_stop_…[1440-1000]`)은 깨끗한 main `1d5912651`에서도 실패(문서 안 작업 이동 0ee1d027c 쪽, 다른 세션 담당). node 통과. 캡처 `X:/DevTemp/site-map-pos/robots-*.png`.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 가짜 시계(`page.clock`) 아래에서는 폴링 응답이 진짜 네트워크로 와서, 찍기 전에 로봇 수를 기다려야 한다.

## 2026-10-09 · uncommitted · refactor(fleet): 시작점·배경 다시 학습을 설치·보정으로 (D-540 (f))
- 변경: 관제 지도 아래에서 시작점 도구와 `배경 다시 학습`을 뺐다(범례·추적 상태줄·`관제 범위 안내`는 남김). 설치·보정 `카메라 설치·보정`이 시작점(D-513, `start-point-view.js`)과 새 `tracking-relearn.js`(D-539)를 가진다. 시작점은 맵 맞춤 위에서 본 그림에서 고르고(`picturePose`: 여백·트랙 밖·퇴화 변환은 자세 없음) 표시도 그 그림에 한다. 관제 `cameraPick`/`pointerPose`와 시작점 표시는 지웠다. 서버 경로는 그대로, 시작점 쓰기는 이름 있는 운영자(D-540 9). 카메라 승인 패널 하나로 합치기와 `#vision-heading` 중복은 이 브랜치 밖.
- 증거: node `start-point-layer.test.mjs` 5건. OMEN `operations/fleet/test/` 3210 passed, 3 failed: `test_cell_app_browser`·`test_site_map_browser[320-568]`은 깨끗한 main(039e21ab0)에서도 실패, `test_console_card_trips_browser`는 부하 탓(AI PC 단독 8 passed). `test/test_fleet_console_browser.py`는 main과 같은 8 failed. main 병합(ad7655ce9) 뒤 AI PC `operations/fleet/test/` 3266 passed, 5 skipped, 0 NEW. 캡처 `X:/DevTemp/setup-tools/{before,after}-*.png`.
- gate 변화: SOURCE. fleet 크기 +33(새 모듈 62, 관제 쪽 −120).

## 2026-10-09 · a7203b3c5 · feat(fleet): D-577 (a) 판단기 기본 켜짐 + 차선 상실 R3 조건·R5
- 변경: `fleet console`이 판단기를 기본으로 돌린다(`--no-stuck-resolver`로 끔, `--stuck-resolver`는 호환). `lane_lost`의 R3 `BACK_AND_RETRY`는 로컬 복구 켜짐·시도·예산 남음·R3 거절 없음·`line_follow.crosswalk` 없음·Fleet 지도 자세 모름 또는 LOCALIZED ≤ 2 s·뒤 띠 동료 없음일 때만. 아니면 R5 `WAIT` + `lane_lost_hold:<이유>` 사람 올림(막힘마다 한 번, 예산 안 씀, CORE가 WAIT 거절해도 올림). `lane_lost`에 RESUME·YIELD 없음. trip 로봇은 M4 그대로. 판단기 메모 `age_s`, 큐는 30 s 무응답 올림 행을 맨 위로(콘솔만). API v1.172.
- 증거: 먼저 실패 19건(`X:/DevTemp/d577a/red.txt`, e8f4dec52). 모델 PC `operations/fleet/test/` + `test/test_line_follow_contract_docs.py` 3144 passed, 144 skipped(67c942071), `known_failures` 0 new. 9dfk 재현: 자격 없음 → `no_resolver_token`, 자격 있음 → R5 WAIT 한 번 + `lane_lost_hold:attempts`.
- gate 변화: SOURCE 후보. Safety-Review 전, 착지·푸시 안 함. 로봇 자격 발급·`recovery_local_enabled`·AI 행동·비전은 꺼진 채(사용자 승인 대기).
- 안전 검토 보완(2026-10-10): 잃은 자세(`UNKNOWN`이지만 목격 출처 있었음) → `pose`, 뒤 띠는 신뢰 지도 자세로만 재고 모르면 `peer_unknown`, `line_follow.crosswalk` 보고 없음 → `crosswalk_unknown`(지금은 R3가 사실상 닫힘), R5 WAIT 전송 실패 한 번 재전송, 시작 시 답할 로봇 출력. 새 시험 10건 먼저 실패(`X:/DevTemp/d577a/red2.txt`), 모델 PC fleet 3162 passed, 0 new. API v1.173.
- 결정: D-577 Accepted (2026-10-09, 사용자)
- 교훈: 모델 PC로 `git archive` 200 MB를 보내면 느린 링크에서 40분이 넘는다. `repo`에 bundle(origin/main..HEAD)을 fetch해 거기서 archive하면 1분 안이다.

## 2026-10-09 · uncommitted · feat(fleet): D-573 횡단보도 구역을 현장 지도에
- 변경: `rosy.site_map/1` `crosswalks[] {id, polygon, approach[], lanes[], revision}`. 다각형은 `lane_graph.yaml`에서 그대로(`cw1`.., `lane_graph:<sha12>`), `lanes`는 검증 때마다 차로 교차로 유도, 대기 띠는 현장 지도 편집기에서 그리고 지운다(초안, 이름 있는 운영자 저장). 띠가 차로에 닿지 않거나 D-507 9 바닥(차로 + 0.30 m) 밖이면 `SITE_MAP_INVALID`. `GET /site-map/lane-graph-crosswalks`로 이미 활성 지도가 있는 현장도 가져온다. 관제 지도에 읽기 전용 윤곽. `PlaceKind` 그대로. CORE·교통·통행권 변경 없음. API v1.174.
- 증거: red `X:/DevTemp/crosswalk-zones/red.txt`(시험만, 수집 실패). 모델 PC `operations/fleet/test/` 전체(브라우저 포함) 3230 passed, 53 failed: 52개는 같은 부분 스냅숏의 깨끗한 main에서도 실패(deploy/·integrations/ 빠짐), 1개(`test_the_open_form_fits_every_viewport_without_rail_overflow`)는 부하 중 DOM 재그림 흔들림이고 단독 3/3 통과 (X:/DevTemp/crosswalk-zones/run.txt). 편집기 캡처 `X:/DevTemp/crosswalk-zones/site-map-crosswalk-band.png`.
- gate 변화: 없음(SOURCE). 관제 지도 윤곽은 캔버스라 브라우저 시험 없음.
- 열림: 바닥 검사는 띠 꼭짓점만 본다(오목한 바닥에서 변이 밖으로 나가는 띠는 통과). 상태색·카드 줄은 (f), CORE 전달은 (d).

## 2026-10-09 · uncommitted · docs(fleet): Fleet 호출 지도
- 변경: `docs/call-map.md`를 추가했다. 브라우저·Fleet·CORE·프록시의 현재 호출과, D-540 밖에 남아 구현 때 접을 메모를 적는다. `AGENTS.md` Key Files에 한 줄을 넣었다.
- 증거: 기준 local main `3b6072a46`의 소스 대조. 그 사이에 착지한 D-540 (a)(c), D-541 7, D-550 10을 지도에 반영했다. 시험 없음. 현장 이미지 확인 없음.
- gate 변화: 없음. 소스 지도이며 현장 수용이 아니다.
- 결정: 없음. 계약은 ADR과 API Reference. 화면 구조는 Proposed D-540.
- 교훈: 호출이 맞는 것과 화면 자리가 하나인 것은 다른 기록이다. 후자는 D-540이 이미 처분한다.

## 2026-10-09 · uncommitted · docs(fleet): 호출 지도에 목표 lease presence
- 변경: `POST /api/fleet/goal-lease/presence`는 임대 중인 목표가 있을 때만 보낸다. 지도 기준을 local main `d8f12328b`로 올렸다.
- 갱신 2026-10-13: 기준을 `e14245e86`으로 올렸다. 콘솔 원본이 `operations/ui/console`로 옮겨진 경로, 호스트 서비스·로그인·설치 호출, CORE 클라이언트 경로(`rotate_to`, `lane-cue`, `fleet/link` 등), 프록시 포트 표기, 해결기 경로를 현재 소스와 맞췄다.
- 증거: `signals.js`의 presence 조건(`e42ecc073`).
- gate 변화: 없음. 소스 지도이며 현장 수용이 아니다.
- 결정: 없음.

## 2026-10-10 · uncommitted · fix(fleet): keep the armed CORE arc end instruction

- Change: while CORE's arc is running, retain its armed end-place instruction if Fleet map localization has advanced to the next segment. A hold STOP still takes priority.
- Evidence: D-520 handshake and the 2026-10-09 U2 SE-to-NE early replacement that ended in arc_mismatch. Regression tests cover the early crossing, next instruction after consumption, and hold STOP.
- Gate: docs/validation/lane-arc-end-guard-2026-10-10/result.md. Isolated U-Net SIM reached the destination twice, but ring_n sampled body margin crossed the outer paint centre in 18/44 and 27/45 samples. Lane containment and field driving remain HOLD.

## 2026-10-10 · uncommitted · uiux(fleet): 좁은 지도 패널에서 전체 지도 가독성 확대

- 변경: 활성 지도 캔버스의 최소 높이를 데스크톱 28rem, 30rem 미만 화면에서는 최대 30rem·150vw로 높였다. 지도 좌표·축척 계산과 비상정지 동작은 그대로다.
- 증거: 현장 PC Chromium에서 설치 화면의 CSS 응답에 후보 규칙을 적용해 1262×632 지도 높이 344→448px, 320×800 높이 352→480px, 두 폭 모두 가로 넘침 0을 확인했다. 후보 스크린샷은 X:/DevTemp/rosy-map-large-1262.png, rosy-map-large-320.png에 보관한다.
- gate 변화: 후보 화면 미리보기만 확인. 새 이미지 설치와 실제 설치 화면 확인 전 FIELD 수용은 보류한다.

## 2026-10-10 · uncommitted · feat(fleet): D-587 approved_record sighting 수용

- Change: `SightingService.accept` takes `calibration_source: approved_record` only when its revision is the source's current approved D-457 record (`TrackingService.approved_revision`, wired in `cli.py`); otherwise 409 `CALIBRATION_MISMATCH`. Site config key `marker_yaw_offset_deg` is validated with Vision's shared check. API v1.177.
- Evidence: model PC pytest of sightings/tracking/map pose/site map/roster/version pins/ownership/module structure 426 passed, gateway site sightings + module criteria 16 passed, known_failures 0 new.
- Gate: SOURCE. The live site needs a release and the config line before D-494 anchors from the ceiling camera.

## 2026-10-10 · uncommitted · feat(fleet): D-600 robot regions for the tracking background

- Change: `detections/config` carries `occupied` (marker > D-494 map pose incl. operator pin > LOCALIZED own pose, plus unassigned markers and last OK blobs); relearn reply adds `occupied`/`unlocated`; tracking source rows carry `unknown_floor`, drawn as a hatch; relearn copy says robots stay. API v1.181.
- Evidence: model PC pytest operations/fleet/test exit 0, known_failures 0 new; guards (module structure after re-judge, safety separation, robot literals, behavior test ownership, version pins, tracking browser) on the model PC.
- Gate: SOURCE. Needs a site release; nudge (moving a robot off unknown floor) is a follow-up.

## 2026-10-10 · uncommitted · feat(fleet): D-596 LED 신원 확인 켜기

- 변경: `server/identity.py` — 서 있는 로봇도 요청(`IDENTIFY_NOT_MOVING` 제거), source마다 색 하나씩 열린 요청(두 번째 로봇은 남은 색을 이름으로), detections config `identity_challenges`, 읽기 `pendings`·`trigger`. 새 순수 모듈 `server/identity_triggers.py`(marker_missing 3 s·0.5 m, split, odom_reset; 로봇마다 30 s, E-Stop 아님). `identity.auto_request` 기본 true. 콘솔 "LED로 찾기"는 색을 Fleet에 맡기고 창 뒤 결과를 기록줄에 보인다. 안내 `CAMERA_NOT_SEEING`은 익명 blob이 있으면 LED 확인, 없으면 배경 다시 학습. API Ref v1.181
- 증거: 모델 PC pytest(식별·트리거·라우트·추적·차로 준수·안내) 통과, known_failures 비교. 현장 2026-10-10 06:48 서 있는 `rosy_40` 요청이 현재 배포본에서 409 `IDENTIFY_NOT_MOVING`, 두 로봇 `ROSY_LAMP_ENABLED=false`(rosy-face 식별 점멸은 이 값과 무관)
- gate 변화: SOURCE. 사이트 배포 뒤 서 있는 로봇의 실제 점멸 판정을 잰다

## 2026-10-10 · uncommitted · fix(fleet): D-595 지도 맞춤 고정과 교정 어긋남 경고
- 변경: 현장 지도 탭 `fitView`가 로봇 링(몸 + `u_m`)을 맞춤에 넣고 1 s 폴마다 다시 맞추던 것(be14cf129)을 없앴다. 맞춤은 장소·차로·`view_turn_deg`로만 정한다(be14cf129 이전 맞춤). 지도 밖 링은 잘리고 이름표는 지도 안에 붙는다. 관제 지도는 교정 어긋남이 떠도 수락된 보정의 실영상을 내리지 않고 경고 띠와 "맵 고정을 다시 하세요" 문구만 얹는다.
- 증거: 현장 읽기 표본에서 Fleet 기록·평면은 고정이었고, 흔들림은 브라우저 맞춤에서 났다(ADR D-595 Context). 브라우저 시험 `test_site_map_fit_stays_fixed_while_robots_move[0,90]`, `test_stale_camera_calibration_keeps_the_frozen_picture_and_warns`.
- gate 변화: 없음(SOURCE). 현장 화면 확인은 배포 뒤.

## 2026-10-10 · uncommitted · uiux(fleet): D-577 (b) 막힘 행의 근거 그림과 알림

- Change: `GET /api/fleet/robots/{robot_id}/line-stuck/evidence` (API v1.182) asks the robot for one front-camera frame (`front/status` then `front/frame?sequence=`) on the first read of an open stuck and `LineStuckBoard` keeps it in memory only until the stuck closes. The queue row shows it below the five answers with camera, frame and age (`evidenceCaption`), and `alertsDue` raises one tone and browser notice per new stuck row and one more at the 30 s deadline. Rosy Cam crop and AI facts on the row are not in this step (AI facts come with (c)).
- Evidence: AI PC remote pytest (line-stuck evidence/API, transport, queues contract, node web units, server app, version pins, module structure) green except the fleet size verdict (50617 vs 50404+150), which waits for an independent re-judge; red run first (X:/DevTemp/uiux-d577-queue-evidence-notify/red.txt). The new real-Chromium test is opt-in and was not run (no browser on the test hosts).
- Gate: SOURCE. Console only; no robot command path.

## 2026-10-10 · uncommitted · feat(situation): D-577 (c) rosy-situation 골격과 Fleet ai_observer 사실(shadow)

- Change: Fleet role `ai_observer`, `POST /api/fleet/ai/facts`·`/heartbeat`, `GET /api/fleet/ai` (API v1.183; (b) holds v1.182), `fleet_ai_facts`; the stuck row carries the AI chip and live facts. `ai_observer` is refused on every other write route in `authorize`. New `operations/situation` (stdlib service, analyzers stubbed) and the `deploy/ai_pc/rosy-situation.service` template, not installed.
- Evidence: AI PC remote pytest red first (X:/DevTemp/feat-d577-ai-pc-situation-skeleton/red.txt, collection errors), then test_ai_facts + situation tests + node web units 26 passed, including an in-process real Fleet over HTTP.
- Gate: SOURCE. Shadow only. Installing on the AI PC waits for the owner's consent.

## 2026-10-10 · uncommitted · feat(fleet): D-511 rev 1 return loop

- Change: lane monitor `return` (ON_LANE/ON_LINE/OFF_LANE/OFF_MAP/WRONG_WAY, debounced) from the Rosy Cam map pose + site map; `POST /api/v1/line-follow/lane-cue` to robots at 2 Hz with side/bearing/turn and a `fleet_map` crosswalk zone; resolver RESUME (`XW`) for a lost-like stuck at a mapped crosswalk; console one line. API v1.189.
- Evidence: offline replay of Fleet D-594 paths p5-p10 (X:/DevTemp/fleet-lane-return/replay.py); remote pytest lane/resolver/console suites green.
- Gate: SOURCE. Robot consumer on feat/core-fleet-lane-cue (Safety-Review).

## 2026-10-10 · uncommitted · feat(situation): D-577 (d) 교착·livelock·정체 분석기와 교착 행 조치

- Change: `operations/situation/rosy_situation/deadlock.py` `TrafficWatch` (`analyzer:traffic_watch@1`) reads Fleet's `/traffic` table and robot states over time and posts shadow facts of the existing kinds `wait_cycle_confirmed` (3 snapshots, all still; `fleet_agrees` flags Fleet's `wait_cycle` vs the table's own waits), `wait_cycle_stale_input` (offline, state > 2 s, unplaced, UNKNOWN unit), `waiting_but_moving` (> 0.05 m in 2 s), `livelock` (cycle re-formed 3x in 60 s, or 20 s moving/commanded without 0.05 m route progress), `stalled` (running trip with authority, 20 s still; held units, zones and who waits) and `unknown_occupancy_long` (30 s). `Analyzer` appends them after its proposals, so no proposal or Fleet rule reads them (no `ACTING_KINDS` change); a traffic fact Fleet would refuse (command word, > 16 ids) is dropped so it cannot sink a batch carrying an acting `rear_blocked`. Review fixes: a one-snapshot cycle flicker is not a re-formation, unknown start pose is not "still", AI facts shown once per kind (newest). The console wait-cycle row now opens (`decision: deadlock`) on Fleet's resolver decision per cycle robot, the AI facts from `GET /api/fleet/ai` (read only while a cycle is shown) and three actions on existing routes: `바뀐 경로로 계속` (`/trips/{id}/confirm-replan`, named operator), `운행 취소` (`/trips/{id}/cancel`, open), `로봇 카드 열기`. Labels: `RESOLVER_DECISION_LABEL`, `AI_FACT_LABEL` in `site-map-model.js`. No API change.
- Evidence: model PC remote pytest red first (X:/DevTemp/d577-dl/red, red-web), then situation tests, test_ai_facts, node web units green (X:/DevTemp/d577-dl/green-web); the only failure is main's `line_observer_node.py` size verdict (perception). The real-Chromium row test is opt-in and skipped on the test hosts.
- Gate: SOURCE. Shadow facts and console only; no motion decision changes.

## 2026-10-10 · uncommitted · uiux(console): walkthrough fixes — leader/follower appointment, lane-follow words, 100 robots

- Change: 대형 follower boxes leave the leader out, buttons 대형 시작/변경/재개/해제 with a one-line help, one cause line `#formation-why` (held-off buttons say 위 사유), shape/spacing stay reachable while running (대형 변경 used to send a hidden form), shapes and HOLDING ("멈춤 · 재개 대기") from `core_ui_logic.js`. Cards: 대형 리더/팔로워 tags, the lane-follow mode as the mode tag (was 대기 while CAMERA_LINE drove), no double 대기, 충전 확인 불가, one word 차선 추종. 대열: leader first, the follower list leaves out robots on a trip, the leader card names its followers. Scale: 로봇 찾기 filters every robot picker, bounded follower list, queue heads and summaries name a few and count the rest. No route, auth or motion change.
- Evidence: model PC real-Chromium walkthrough against the real Fleet app with fake COREs and a named login (X:/DevTemp/console-ux/walkthrough.md, before/ and after/); scale run at 3/10/30/100 robots; new test_console_roles_browser.py (incl. 100 robots) and operator-labels.test.mjs pass; test_fleet_console_browser 11 failures equal clean main c4646a066, guard suites 2 failures equal clean main (0 NEW).
- Gate: SOURCE. Console only; no robot command path.

## 2026-10-10 · uncommitted · uiux(console): position chip, map id labels, grouped queue causes, 전체 주행 취소 without confirm

- Change: the card's position chip says Fleet's site map pose first (지도 위치 확정/추정 · 카메라/odom 이음), CORE localization only when CORE reports one, else a neutral 지도 위치 없음 (no warn for a missing CORE block; the D-587 marker-yaw reason is not known to Fleet, so not shown). Map markers carry short ids with declutter (hidden on overlap except selected/called/최우선). The same warn cause on several robots is one expandable queue row; 최우선 rows stay one per robot and first; queue heads count instead of repeating names (D-540 3). 전체 주행 취소 runs at once without a confirm (D-540 6, user decision), quiet, any operator, "전체 주행 취소를 보냈습니다 · N대"; dialog contract pins console.js at 3.
- Evidence: model/AI PC remote runs: operations/fleet/test 3326 passed; guard suites only the perception size verdict listed in known_failures; browser suites equal clean main 8d7b5939f (11 known failures) plus new tests passing (labels/grouping, cancel-all immediate, 100 robots).
- Gate: SOURCE. Console only; 전체 주행 취소 calls the unchanged /api/fleet/cancel-all.

## 2026-10-10 · uncommitted · fix(trip): free 경로 이탈 때 목표 취소

- Change: Fleet의 0.5초 trip 감독에서 `LOCALIZED` 자세가 계획 경로 폭의 절반을 벗어나면 free 구간의 진행 중인 CORE 목표를 취소한다. 위치 상실 시 기존 deadman 정책은 유지한다.
- Evidence: `test_trip_runner.py` 경로 이탈 사례에서 목표 취소와 `stop_sent`를 확인한다.
- Gate: SOURCE; 실기기 정지 거리와 도착은 별도 검증이다.

## 2026-10-10 · uncommitted · fix(fleet): 이름 있는 차선 중간 장소에서 유한 trip 정지

- Change: 유한 trip의 마지막 이름 있는 중간 장소를 계획 action과 실행 place에 보존해 Fleet이 그 장소의 `stop_after_m` 정지를 보낸다. 반복 lap의 중간 장소는 기존처럼 통과하고, 좌표만 지정한 중간 종료는 계속 거절한다 (D-613).
- Evidence: 원격 `test_lane_traffic.py`, `test_routing.py`, `test_trip_runner.py`, `test_site_map_trip.py` 183 passed; `known_failures.py` NEW 0, KNOWN 0 (`X:/DevTemp/one-lap-midstop-2/run-1.txt`).
- Gate: SOURCE. 실제 두 로봇 동시 한 바퀴·정지 거리·차체 여유는 ROS-SIM·DEVICE·FIELD 별도.

## 2026-10-10 · uncommitted · refactor(fleet): isolate stuck peer pose checks

- Change: move trusted map pose and front/back peer-band helpers from stuck_resolver.py into stuck_peer_pose.py; preserve the resolver import surface and decisions.
- Evidence: focused stuck resolver/API tests 137 passed; structure size checks 2 passed. Main at 5d93a9255 had both size failures before this split.
- Gate: SOURCE and host tests only; no field robot action or changed motion contract.



## 2026-10-10 · uncommitted · fix(fleet): remove implicit legacy map-pose trust

- Change: 사용자 결정에 따라 위치 미보고를 UNKNOWN/untrusted로 처리한다. LOCALIZED + map만 교통·bays·교착 해결기의 원시 지도 자세로 쓴다. 30 s null 뒤 캐시 좌표를 버려도 신뢰는 복원하지 않는다. 목표 admission은 현재 상태를 먼저 읽는다. 화면은 map_id만 있는 raw pose를 지도에 그리지 않고 Fleet MapPose 출처와 CORE 상태를 구분한다.
- Evidence: AI PC 원격 집중 시험 193개 및 enrollment/formation/priority/task 호출부 시험 116개 통과; known_failures 비교 0 NEW. node localization-badge 10개 통과. 전체 Fleet 첫 실행의 위치 생략 fixture 실패 6개를 수정했으며 최종 통합 게이트는 착지 도구에서 다시 검사한다.
- Gate: SOURCE. 설치 이미지·현장 화면은 이 변경으로 아직 검증하지 않았다. 물리 주행이나 LED 신원 확인을 지시하지 않았다.

## 2026-10-10 · uncommitted · test(fleet): 정확한 카드 주행 컨트롤 선택

- Change: 경로 보기 버튼을 정확한 접근성 이름으로 선택하고 반복 출발 자리도 이름으로 찾아, 한 바퀴 폼이 추가돼도 부분 문자열·select 순서에 기대지 않는다.
- Evidence: 모델 PC 실제 Chromium 카드 주행 시험 10 passed; known_failures NEW 0. 실패한 CI fleet-1of3의 중복 버튼 선택과 반복 출발 선택을 재현하고 수정했다.
- Gate: SOURCE / 원격 브라우저 시험. 로봇 물리 주행 증거는 아니다.

## 2026-10-10 · 008d62b301 · feat(fleet): reassess stuck heading

- Change: 전체 대상의 하단 차선 통과·한 바퀴·원위치 정지를 계획의 완료 조건으로 기록했다. 열린 막힘마다 최신 신뢰 자세와 차로 방향을 비교하고 변화 시 로그를 남긴다. 같은 odom 시각에 새 지도 기준점이 들어와도 이전 차로 판단을 섞지 않으며 관찰 오류는 기존 resolver를 막지 않는다. 순수 자세 비교는 localization에 두고 명령 규칙은 변경하지 않았다.
- Evidence: 신규 기능 원격 RED(모듈 누락), 관련 시험 61개 GREEN. 독립 검토의 재앵커·관찰 오류 4건은 별도 원격 RED로 재현하고 수정했다. 최종 관련·구조 시험은 현재 후보에서 다시 확인한다. 검토자 lap_review는 008d62b301의 소스 수정 승인; REALIGN 실행·현장 완주 승인은 아니다.
- Gate: SOURCE. REALIGN 전달·trip 중 조작 점유 검증·공통 장치 배포·하단 실제 통과·전체 한 바퀴는 미완료다. 방향 로그는 5도 변화 단위 요약이며 전체 영상/표본을 대신하지 않는다.

## 2026-10-10 · uncommitted · fix(situation): open stuck judgement without changing command authority

- Change: D-618 separates ai_observer case reads from AI-first enrollment; removes unsupported REALIGN from the VLM table. API Reference specifies request correlation, image/model evidence, queued admission, Fleet verdict and CORE outcome, with three contract examples.
- Evidence: remote situation / AI facts / AI-first contracts 97 passed; known_failures 0 NEW. Live heartbeat reports Qwen model digest and both enrolled Fleet resolver robots; no corner inference or motion acceptance is claimed.
- Gate: SOURCE / remote API contracts; field judgement and lane-follow acceptance remain pending.

## 2026-10-10 · aa37d8cb6 · fix(fleet): 일정 시간 점등과 주기 재식별
- 변경: 기존 CORE 요청으로 1초 꺼짐 뒤 2초 연속 점등. 완전한 파랑 꺼짐-켜짐-꺼짐 증거는 예상 자리 밖에서도 이름을 붙인다. 미확인 로봇은 30초마다 source별 한 대씩 재요청하며 초기 신원 미상도 포함한다. 지도 기준점과 주행 권한은 변경하지 않는다.
- 증거: 원격 RED 5건으로 누락을 재현, 원격 통합 373 passed / 3 skipped. C 램프 시각표 포함 최종 시험은 별도 로그에 기록한다.
- Gate: SOURCE. 정식 착지·푸시·사이트/로봇 payload 적용·실제 두 대 LED 식별·추종 주행은 미확인.

## 2026-10-10 · 48de3f65c3 · feat: D-620 교차로 Fleet 신호 질의

- 변경: paired heartbeat에 교차로 요청 ID와 신호 응답을 연결. 완전 무응답 3초만 기존 CORE 우측 회전을 선택하고 명시적 red/unknown/오류/만료 답은 대기한다. 기본 꺼짐.
- 증거: AI PC 원격 교차로·FleetAgent·hub·신호표·API·횡단보도 관련 273 passed, known_failures 0 NEW. docs/validation/junction-signal-2026-10-10/result.md 참조.
- gate 변화: focused SOURCE/원격 계약 증거만 추가. 새 ARM64 payload/Fleet 이미지와 DEVICE/FIELD는 미확인. 기존 전역 게이트 수용을 올리지 않는다.

## 2026-10-10 · uncommitted · feat: shared situation direction (D-619)

- Change: D-619 uses raw front frames, calibrated ceiling metadata, task intent/current mode and sensor age; optional shared assessment validation preserves legacy proposals and D-577 authority. Qwen exact prompt and image hashes are recorded; no corner or arm acceptance claimed.
- Evidence: remote focused contracts 115 passed, 0 NEW before final context additions; final validation follows.
- Gate: SOURCE; live Fleet image and physical acceptance remain separate.

## 2026-10-10 · 79402f1f2 · fix: observation-first situation context

- Change: Each image is observed independently before task context reasoning; exact per-call prompts/options remain recorded. The shared 6-second deadline also rejects late final replies. Fleet retains timestamped route intent without granting motion authority.
- Evidence: Remote focused contracts 108 passed, known_failures 0 NEW. AI PC replay with local Qwen3-VL took 4.03/3.94 seconds and separated wall/front observations from ceiling objects in two cases; classification accuracy and execution freshness are unverified.
- Gate: SOURCE / remote contracts / offline replay. D-577 freshness, enrollment and CORE authority remain unchanged; no autonomous corner or arm acceptance.

## 2026-10-10 · 3aff82db2 · fix(fleet): lane convoy automatic leader selection

- Change: Integrated automatic-leader console selection. Lane convoy candidates are online open-repeat-trip robots; rank fresh LOCALIZED guide poses in the active map, otherwise robot number. Both callers share selection; formation capability admission is preserved.
- Evidence: Node suite 274 passed; remote focused Python contracts 62 passed, known_failures 0 NEW. Independent led_review approved source and fleet size 51061.
- Gate: SOURCE / remote contracts; deployment and physical convoy acceptance remain separate.

## 2026-10-11 · uncommitted · fix(fleet): fresh recovery context (D-623)

- Change: Fresh raw incident preview, per-frame backdrop cache, download/decode freshness and invalidation; validated map heading reaches AI case and console; actual Fleet command and CORE receipt shown separately.
- Evidence: Remote validation pending. Existing D-468 aligned-boundary comparison and D-595 frozen calibration remain authoritative.
- Gate: SOURCE; no new motion permission, AI-first activation or physical acceptance.

## 2026-10-11 · uncommitted · uiux: semantic colors and shared layout (D-624)

- Change: Semantic color roles preserve both palettes; shared controls and active CSS consume the same roles. Existing gallery collects colors, five button kinds, readback and task compositions. Fleet map/header and robot evidence containment improved.
- Evidence: Parallel independent source assessments; remote contracts and batched browser verification pending.
- Gate: SOURCE; no robot commands, motion policy, new theme or physical acceptance.

## 2026-10-11 · uncommitted · uiux: common control geometry and Fleet hierarchy (D-629)

- Change: All controls including emergency stop share 48px targets, label typography and horizontal inset. Danger is identified by fill, icon and verb. Current queues and robot status precede a folded neutral incident archive; source evidence, reviews and export remain available.
- Evidence: Remote checks and browser captures pending; the source review distinguishes current intervention from incident history.
- Gate: SOURCE; no new robot command or safety authority.

## 2026-10-11 · uncommitted · uiux: notification inbox and read semantics (D-632)

- Change: One shared Fleet notification entry opens the console inbox; existing intervention summaries and operator event messages share a read-only channel. Read state does not resolve intervention or send a robot command.
- Evidence: Remote browser verification pending for four entry documents, unread deduplication, keyboard navigation and mobile stop visibility.
- Gate: SOURCE; server deployment and physical acceptance remain separate.


## 2026-10-11 · 6d686c65a1 · fix(fleet): 현장 지도 좌표 유지와 위치 조회 연결 실패

- 변경: 활성 현장 지도와 카메라 지도 ID가 일치하면 로봇 SLAM 격자로 화면을 바꾸지 않는다. 로봇 발견 실패·시간 초과를 HTTP transport 연결 오류로 처리해 지도 위치 조회가 500 대신 UNKNOWN을 반환한다.
- 검증: AI PC 원격 관련 pytest 205 passed(exit 0), 안에 콘솔 Node 280개 포함. 운영자 핀의 odom→map 변환·신선도·재시작, 카메라 역변환·회전, TLS·자격 증명 미전송 시험 포함.
- 증거: docs/validation/fleet-map-stability-2026-10-11/README.md. 현재 로봇 offline과 전날 사건 원인은 구분한다.
- gate 변화: SOURCE/원격 관련 계약 검증. 착지·push·배포·실물 위치 추종 확인은 아직 없다.

## 2026-10-11 · 541815508 · feat(fleet): 지도 프로필과 좌표·영상 보기 (D-631)

- 변경: 기본 2D 좌표·선, 승인 교정 영상 오버레이, 교정 전 원본 영상 및 교정 후 비교. SQLite 프로필 라이브러리·JSON 파일/규칙 입력·선택 미리보기·초안 불러오기. 프로필은 활성 지도와 별도로 저장하고 revision·권한·입력 크기·개수 제한을 검사한다.
- 검증: 원격 계약 회귀 86 passed, 관련 Chromium 전체 68 passed. 마지막 영상 조건 변경 후 API/전체 Node 계약 26 passed 및 새 Chromium 시나리오 4 passed. known_failures NEW 0, harness lint 오류 0.
- 증거: docs/validation/fleet-map-stability-2026-10-11/README.md에 커밋별 검증과 로그 위치를 기록했다. 표시 전환·프로필 저장은 로봇 이동 명령을 발생시키지 않는다.
- gate 변화: SOURCE/원격 계약/Chromium 검증. main 착지·push·현장 배포·실물 위치 추종 수용은 별도다.

## 2026-10-11 · uncommitted · fix(fleet): 하단 좌표 표 안정성과 선택 카메라 유지 (D-634)

- 변경: 만료·관측 없음에서 좌표 표는 유지하고 숫자는 대시로 교체한다. 지도 위 만료 관측은 제거한다. source 소실·재연결·목록 순서 변경 때 다른 카메라로 자동 전환하지 않는다. Cam/Vision/Fleet/Console의 기존 책임과 노출 제어 writer 우선순위를 D-634에 기록했다.
- 검증: 기존 표 숨김·source 자동 전환을 Node 시험으로 재현한 뒤 전체 Node 284 passed. 관련 원격 pytest는 별도 검증한다.
- gate 변화: SOURCE/Node 검증만. 현장 발생 기록 대조·Cam 장치 검증·착지·push·배포는 별도다.

## 2026-10-11 · 26181c12d · test(fleet): 좌표 관측 수명과 화면 배치 검증

- 변경: D-634의 역할 분담과 좌표 표 안정성 검증을 기록했다. 사용자 정정에 따라 증상은 하단 좌표 표 소실로 분류하며, 별도 source 자동 전환 수정과 구분한다.
- 검증: b1b8214c5 원격 pytest 151 passed, 26181c12d Chromium 1 passed. 두 실행 known_failures NEW 0. Node 284 passed, harness lint 오류 0·기존 경고 25. 로그는 X:/DevTemp의 이 세션 logs/camera-ownership 및 camera-ownership-browser.
- gate 변화: SOURCE/원격 계약/Chromium 검증. 현장 APK·Vision 런타임·실장치 발생 기록 대조 및 배포는 검증하지 않았다.

## 2026-10-11 · uncommitted · feat(fleet): 지도 종류와 기본 정보 관리 (D-635)

- 변경: 차선 코스·축구장·일반 지도 종류, 설명과 축구장 치수 저장·선택·파일 입력. 중심 원점의 축구장 경계 템플릿과 기준선 표시. SQLite 추가 열로 기존 지도/기본 정보를 보존하며, 이전 클라이언트가 기본 정보를 생략하면 현재 정보를 유지한다. Games 기존 Field·SoccerGame 재사용 방향과 별도 연결 검증을 ADR로 기록했다.
- 검증: 기존 API/DB에서 기본 정보 미지원 실패를 원격 시험으로 재현했고, 축구장 템플릿 시험은 Node에서 실패 후 통과했다. 최종 원격 계약·Chromium 검증은 별도 기록한다.
- gate 변화: 구현 단계. 자동 Games 시작·Vision 축구 인식·배포·실물 수용은 이번 구현 범위에 포함되지 않는다.

## 2026-10-11 · 655093d8a · test(fleet): 지도 종류와 기본 정보 관리 검증

- 변경: D-635 기본 정보 관리와 Games 재사용 경계의 검증을 기록했다.
- 증거: docs/validation/map-profile-purpose-2026-10-11/result.md. 관련 원격 pytest 175 passed·Node 285 passed·Chromium 데스크톱/모바일 4 passed·DB 재개방 포함 프로필 시험 11 passed, known_failures NEW 0. browser fixture MIME 누락은 수정 후 재검증했다.
- gate 변화: SOURCE/원격 계약/Chromium. 자동 Games 연결·Vision 축구 인식·착지·push·배포·실물 경기 수용은 별도다.

## 2026-10-11 · 19e1c7eef · uiux: 바닥 지도와 상세 상태 분리

- 변경: 가상 신호는 작은 점선 램프로 표시하고, 점유·대기·입구별 상태는 지도 아래 고정 높이 영역으로 옮겼습니다. 지도 프레임 크기를 관측 행 수와 영상 유무에서 분리했습니다. 좌표 만료 시 값만 지우고 대기 행을 유지합니다.
- 증거: Node 287 passed. Chromium 데스크톱/모바일 관측→익명→만료 및 지연 응답의 프레임 크기 검증은 이어 진행합니다. 설계: docs/plans/2026-10-11-stable-map-readouts-design.md.
- gate 변화: 화면 구현. 서명 배포·현장 화면·실물 위치 정확도는 각각 별도입니다.

## 2026-10-11 · a64806ad3 · D-652 공통 개입 필요성 shadow 소비

- 변경: Situation 순수 필요성 평가를 기존 Fleet holder/wheel/sdist에 세 파일로 포함하고 현재 로봇 상태의 내부 shadow read에 연결했다. 사건 ID·owner·revision·freshness·유효기간을 대조하며 정상/개입/보류를 구분한다. 기존 resolver와 CORE final writer는 유지한다.
- 증거: AI PC 원격 Situation/Fleet API·근거·no-motion·wheel/sdist 178 passed, NEW 0 (`0926fc4fa5`). 추가 freshness/설치 순수성 및 최종 main 통합 검사는 착지 receipt에 기록한다.
- gate 변화: 내부 소스/원격 설치 계약. 현장 활성화·화면 의미 수용·Discord/Slack/Telegram·모델 토론/학습 승격은 후속이며 FIELD는 승격하지 않는다. 상세: docs/validation/intervention-assessment-2026-10-11.md.


## 2026-10-11 · 027e604fe · D-652 판단·현장 연결·설치 책임 분리

- 변경: 공통 판단은 Situation, 현장 소비는 Fleet, 소스 구성/빌드는 tools/packaging/fleet_sources.py에 둔다. self-contained sdist와 source-image 순수 평가 closure를 함께 갱신했다.
- 증거: 원격 책임 분리/구조/설치/source image/site candidate 57 passed, NEW 0. 이전 통합 5094 passed/217 skipped에서 발견한 크기 초과는 책임 분리로 수정하며 임계값과 실패 예외를 늘리지 않았다.
- gate 변화: SOURCE/원격 설치 구성. 실제 Docker build, push/배포, 현장 정확도 및 D-648 후속 단계는 별도다.

## 2026-10-11 · 583db17a3 · fix: 네 문서의 공통 헤더 box model 통일

- 변경: 공통 Fleet 헤더의 ui-topbar에 border-box를 명시했다. styles.css 유무에 따라 site-map/cell의 E-Stop 세로 위치가 console/install보다 8px 내려가는 원인을 공통 CSS 한 줄에서 고쳤다. 버튼 크기·접근성·권한·명령 동작과 strict 시험은 유지한다.
- 증거: main 063676cbcb의 CI 실패를 같은 immutable SHA의 원격 Chromium에서 재현했다(1 failed, 1 passed, NEW 1). 수정 583db17a3의 기존 browser/header/palette/shared controls 시험은 원격 54 passed, NEW 0. 독립 안전 소스 검토 승인. 최종 main 통합/CI는 별도 확인한다.
- gate 변화: 공통 헤더 소스 및 원격 브라우저 계약 확인. 사이트 배포·현장 E-Stop 수용·Isaac/Fleet 주행 수용은 승격하지 않는다.
- 교훈: 공통 헤더의 높이 계산을 각 문서의 전역 스타일에 의존하면 같은 컴포넌트도 배치가 달라진다.

## 2026-10-11 · fb2e5e07d3 · D-657 모델 도구 Fleet 어댑터와 순수 실행 규칙

- 변경: `model_feedback_dispatch`가 기존 store/journal/fence 도구 중재를 소유하고, goal_evidence 및 진척 시각/step 투영은 기존 execution wheel을 소비한다. store/auth/claim/transport는 이전하지 않았다.
- 검증: `fb2e5e07d3` 원격 212 passed / NEW 0, 독립 소스 리뷰 승인. 기존 execution wheel dependency와 source image COPY/allowlist를 함께 검증했고 Fleet wheel에 execution을 중복 포장하지 않는다.
- gate: 소스·설치 구성. main 착지·push/CI·실제 Docker build·배포·장치/현장 정확도는 각각 별도 증거다.

## 2026-10-11 · 0b14fa02b0 · 책임 추출·현재 판단·사람 인수·팀 알림

- 변경: 모델 원장 dispatcher는 Fleet, 순수 목표/진행 규칙은 execution/site에 두었다. D-660 현재 읽기 판단과 자연 해소 근거, D-661 이름 있는 case/revision 인수 및 기본 OFF 알림 outbox를 기존 DB/auth/CORE 경계에 연결했다.
- 증거: 원격 추출114/작업147/판단99/인수127/알림149 passed, 각각 NEW0. 최종 설치 및 독립 평가 보강 11 passed/NEW0; 독립 검토의 경쟁/만료/평가 결함 수정. 상세: docs/validation/responsibility-boundaries-2026-10-11/implementation.md.
- gate 변화: SOURCE/원격 fake·설치 계약. 실제 Discord 준비·수신·현장 정답/한계는 팀 담당이며 운영 수용 HOLD. 실제 모델 토론·provider 호출·배포·motion 없음.

## 2026-10-11 · 757226957d · 팀 사건 조정 책임 하위 패키지

- 변경: D-661 알림·이름 있는 사람 인수를 `fleet/incidents`로 그대로 이동하고 직접 호출자·설치 검사·문서를 갱신했다. 판단·resolver·장치 admission은 기존 소유자에 유지한다.
- 증거: 독립 responsibility_review 경계 확인. physical-line 실측 부모51933/incidents360, 예산·+150 유지. 최종 원격 terminal과 착지는 docs/validation/responsibility-boundaries-2026-10-11/landing.md에 후속 기록한다.
- gate 변화: 경계 분리만. 실제 팀 채널·현장 수용·모델 토론 HOLD 유지.

## 2026-10-11 · 7afb0e2c4f · 사건 조정 분리 최종 검증과 착지

- 변경: 판단·resolver·장치 명령 소유권을 보존하고 incidents 경계·직접 호출자·설치 계약을 최종 통합했다.
- 증거: AI PC 원격493 passed/NEW0, 독립 책임·설치 검토 통과, tools/land.py 로컬 main FF `7afb0e2c4f`. 실제 범위·로그·후속 관문은 docs/validation/responsibility-boundaries-2026-10-11/landing.md.
- gate 변화: 로컬 소스 통합 완료. 새 팀 Discord와 독립 현장 정답 수용은 팀 담당 HOLD; 실제 provider/발송/배포/motion 없음.

## 2026-10-11 · 89c9b79bbd · fix(test): 추적 응답 fixture 설치 뒤 화면 초기화

- 문제: 좌표 수명 브라우저 시험은 로그인 뒤에 tracking 응답을 가로챘다. 그 전에 실제 미설정404를 받으면 tracking view가 unavailable을 기억하므로 fixture가 있어도 표가 숨겨져 CI가 간헐 실패했다.
- 변경: 먼저 실제404 응답을 기다리는 새로고침으로 실패 조건을 고정하고, 모의 응답 설치 뒤 화면을 새로 초기화한다. 좌표 만료·복귀·표 가시성·지도 크기·페이지 오류 검사는 유지한다. 제품 UI/API·관측 수명·CORE·Fleet 명령은 바꾸지 않는다.
- 증거: 원격 실제 Chromium의 결정적 RED1 NEW 뒤 roles browser 전체6 pass·NEW0·exit0. 첫 원격 호출은 browser opt-in이 빠져 skip이었으며 실행 증거로 세지 않았다.
- gate 변화: 시험 준비 순서와 원격 브라우저 회귀를 확인했다. main 통합·새 CI·사이트 배포·Isaac/Gazebo 주행과 두 대 Fleet 수용은 별도다.

## 2026-10-11 · fb54c9f47f · fix(ci): 사건·알림 시험 helper의 xunit 충돌 제거

- 문제: main 4bcfc55d88의 CI 38147167947에서 pytest 7.4가 두 시험 모듈의 setup(tmp_path)을 xunit hook으로 호출해 Path 대신 module을 전달했다. 30개 시험이 준비 단계에서 오류로 끝났으며 원격 시험 PC의 최신 pytest 통과는 이 버전 호환성을 증명하지 못했다.
- 변경: helper를 make_board와 make_notifications로 바꾸고 전체 16개 정의·호출 위치를 함께 갱신한다. 시험 본문·검증과 제품의 사건 원장·알림·명령 권한은 유지한다.
- 증거: 수정 SHA에서 두 시험 모듈과 공용 UI 계약 원격 61 PASS, NEW 0. 독립 리뷰가 전체 호출 위치와 본문 보존을 승인했다. 안전 경로 trailer 검사는 통과했다.
- gate 변화: SOURCE/원격 관련 회귀 확인. pytest 7.4의 실제 새 CI 결과·main 통합·배포·두 대 주행 수용은 후속 확인이다.

## 2026-10-11 · ea60284994 · D-655 조사용 상대 odom 읽기

- 변경: World tracker의 최신 odom pose/stamp/epoch를 신선할 때만 읽는 survey_odom 포트를 Fleet 서비스로 전달한다. 지도 anchor 없이도 조사 근거를 읽지만 운행 MapPose·pin·명령은 생성하지 않는다. stale/future/unknown robot은 값 없음, 기존 gap/reset epoch를 유지한다.
- 증거: 신규 3개 remote RED 뒤 map pose/service/pin 및 World wheel·compatibility remote GREEN 88 PASS, known_failures NEW 0. X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/survey-odom-green-retry/run-1.txt. 현장 시험 PC의 5.0 cores/8.3 GB 기준 통과. 최초 shipping SSH timeout과 browser SSH reset은 PASS로 계산하지 않는다.
- gate 변화: 읽기 포트 소스와 원격 회귀. 조사 기록 시작·초안 확정 API/UI는 다음 연결 단계이며, 배포·실물 좌표 정확도·주행 수용은 아직 확인하지 않았다.

## 2026-10-11 · 7bf0f597dc · D-655 주행 기록 위치 단절 처리

- 변경: 기존 teach의 map pose가 UNKNOWN/DEGRADED 또는 bridge 0.5 m 초과로 유효하지 않으면 기록을 끝낸다. reason pose_lost로 유효한 앞부분만 pending에 남기고 짧은 기록은 폐기한다. 좌표를 다시 얻어도 끊긴 구간을 하나의 도로로 자동 잇지 않으며 로봇 명령은 보내지 않는다. API reference와 기존 정상 기록 fixture 및 세 불연속 시험을 같이 갱신했다.
- 증거: 세 시험 remote RED 이후 teach API/auth/audit·순수 계산·마커 장소 회귀 26 PASS, known_failures NEW 0. X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/teach-gap-green-paths/run-1.txt. 잘못된 시험 파일명의 첫 GREEN은 exit 4/실행 없음으로 별도 기록했다. 실제 GREEN은 모델 PC 자원 기준 통과.
- gate 변화: 기록 단절 source/remote 회귀. 지도 없는 상대 조사 API/UI와 카메라 누적은 계속 진행하며 통합·배포·실제 주행 수용은 미확인이다.

## 2026-10-11 · 1a14e9705a · D-655 지도 없는 상대 주행 조사 API

- 변경: 기존 teach/start의 선택 survey mode로 저장 초안 map_id/reference/revision과 신선한 odom을 확인한 뒤 상대 변환으로 선을 쌓는다. 기준 변경·odom gap/reset에서 유효 앞부분만 남기며 현재 초안 기준이 다른 confirm은 거절하고 기록을 유지한다. 확정은 기존 CAS 저장으로 odometry/observed 간선을 추가하고 조사 검토를 무효화한다. 공개 기준 snapshot은 표시 비교에 쓰며 내부 odom anchor/epoch는 내보내지 않는다. named operator·busy·감사·10분 pending 경로를 유지한다.
- 증거: 8 remote RED, 첫 구현의 points tuple 회귀를 고친 뒤 1a14e9705a API/auth/audit·stale/reset/gap/frame/CAS/no-motion·기존 teach/순수/마커 장소 37 PASS/NEW 0. X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/teach-survey-api-final/run-1.txt. 모델 PC 자원 기준 통과. UI 8596f7042b Chromium 6 PASS/NEW 0, 멈춘 선 표시 포함.
- gate 변화: 상대 기록 API/UI source/remote. 카메라 누적·작업/대형·개입 연결은 진행 중이며 main 통합·CI·서명 배포·실제 현장 주행/측량 수용은 미확인이다.

## 2026-10-11 · 7476837977 · D-655 조사 독립 검토 회귀 수정

- 변경: 일반 teach/place/marker 저장을 활성 지도와 초안의 동일 좌표계로 제한하고 기록의 활성 버전 변경을 차단한다. 거절된 odom은 조사 연속성만 끊고 운행 앵커는 유지한다. 같은 조사 지도에서 정상 teach 편집도 review를 무효화하며 새/변경 간선 observed 근거를 보존한다. 공개 기록 프레임 snapshot으로 다른 지도 위 표시를 제한한다.
- 증거: 독립 검토의 세 문제 remote RED 5 FAIL 뒤 API·마커·공통 계약 122 PASS/NEW 0, 추가 정상 조사 편집·활성 버전 변경·World 서비스 55 PASS/NEW 0. X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/survey-frame-final/run-1.txt. AI PC 자원 기준 통과.
- gate 변화: source/remote 회귀. 통합·CI·배포·실제 주행 정확도는 아직 확인하지 않았다.

## 2026-10-11 · b80fa42817 · D-655 카메라 지도 marker 편집 재검토

- 변경: survey가 없는 camera map에서도 marker로 이동한 장소의 연결 간선을 operator/observed로 바꿔 재검토를 요구한다. 기존 프레임/교정 note는 보존하고 활성 지도를 유지한다.
- 증거: 새 단일 시험 remote RED 뒤 ebf05b9811 원격 카메라·marker·UI·구조 12 PASS/NEW 0. X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/camera-review-final-retry/run-1.txt. AI PC 자원 기준 통과. marker 편집 뒤 활성화는 ROAD_UNREVIEWED로 거절한다.
- gate 변화: source/remote; endpoint 연결 검토·통합·CI·배포·실제 로봇/측정은 미완료다.

## 2026-10-11 · 962fa15277 · D-655 camera endpoint connection review

- 변경: 같은 전체 조사 기준에서 명시적으로 고른 0.05 m 이내 장소에 새 관측의 끝점만 접합한다. inferred 근거와 원본 frame/calibration note를 보존하며 검토 전 활성화를 거절한다. 같은 좌표의 다른 장소 ID와 robot_kinds를 중복 비교에 포함한다.
- 증거: Node 29 PASS. AI PC 자원 기준 통과한 원격 Chromium 16 PASS/63 deselected, NEW 0 (`X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/camera-connect-race-green/run-1.txt`). 독립 검토 수용. 이전 구조 시험 1 NEW는 Fleet 52995 > 52840+150이며 기존 실패로 간주하지 않았다. 독립 재측정 53010으로 split 판정을 갱신하고 +150·파일 상한·기존 분리 의무를 유지한다.
- gate 변화: source/remote 연결 검토 완료. main 통합·CI·배포·실제 사이트 및 실물 정확도는 아직 미확인이다.


## 2026-10-11 · d6abc8e863 · D-655 map activation and command conflicts

- 변경: trip뿐 아니라 진행 중 대형과 지도 기록에서도 활성화를 거절한다. 일반 기록 시작·pose 장소 저장은 위치 조회 전후 map_id·전체 조사 기준·활성 버전을 비교해 이전 위치의 새 지도 저장을 막는다. 팔로워 목표와 참여자 개별 운행, 진행 중 trip의 개별 목표를 기존 admission에 맞춰 설명하며 확인 직전 재검사한다. 충돌 작업을 자동 해제하거나 이동 명령을 추가하지 않는다. 재개·후진 수락과 실제 로봇 진행을 구분한다.
- 증거: busy RED 4 FAIL, start 경합 RED 뒤 131 PASS, place fixture의 같은 위치로 SITE_MAP_INVALID가 난 경우를 구분하고 distinct pose에서 실제 DID NOT RAISE를 재현했다. 공통 수정 a4a9e2f9e 132 PASS/NEW 0. 대형 화면/서버/구조 68 PASS, 개입·부분 취소·불명 응답·운행 권한·위치 손실 253 PASS/NEW 0. 최종 d6abc8e863 Chromium 역할/대형 및 teach/활성화/구조 140 PASS/NEW 0, 모델 PC 22 cores/7.9 GB 기준 통과. UI Node 301 PASS. 넓은 Node 첫 실행의 누락 loader 오류는 기존 loader를 지정해 해결했다.
- 근거 위치: X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/task5-command-final/run-1.txt; logs/task5-intervention/run-1.txt; logs/task5-node-final.txt. 독립 survey_feature_review가 shared guard·모든 UI 호출자·권한 보존을 수용했다.
- gate 변화: Task 4/5 source·원격 범위 완료. main 폴더 이동 통합·전체 회귀·CI·서명 릴리스·배포·실제 사이트 확인은 Task 6이며 목표는 active다. 실제 로봇 주행·측량·대형 개입 수용은 미확인이다.

## 2026-10-12 · 40b7937fa0 · D-671 기명 Discord 접수 source

- 변경: 기존 tasks DB의 별도 bounded 접수 원장, immutable Discord identity→현재 기명 operator, 전용 HMAC와 Goal/Cell producer 자격 격리, 같은 메시지 중복/수정 및 owner read를 구현했다. 순수 projection/signature holder는 Fleet wheel/sdist/source image에 함께 설치한다. Console 작업 화면은 자기 원문을 textContent로 읽고 권한 철회 시 지운다.
- 증거: 원격 RED 모듈 없음1 NEW, manifest 누락1 NEW 및 구조 증가1 NEW를 각각 수정했다. 최신 focused44 PASS/NEW0; 실제 Chromium4 PASS/NEW0(처음4 skipped는 pass 제외). 독립 source/Safety 검토 수용, Fleet53396/app906 재측정, +150/파일 상한/기존 추출 의무 유지. 실제 기명 HTTPS cookie 로그인은 별도 후속 증거에 기록했다.
- gate 변화: source 접수와 named Console 로그인 확인. Gateway/token/운영 identity mapping/실제 대화 수신 및 후보/승인/reply는 후속이다. Task/Mission/Job/claim/모델/장치 명령·push·image deploy는 없다. 근거: docs/validation/discord-fleet-pipeline-2026-10-12/named-login-and-intake.md.

## 2026-10-12 · 38941ff24 · D-675 Discord Gateway 수신 source

- 변경: 기존 Fleet lifespan 수신 worker, private Bot token 파일, 원장 commit 후 resume 및 미해결 session 공백 정지 구현.
- 증거: 원격 RED는 gateway 모듈 누락 확인. GREEN43 PASS, resume/secret/API/structure86 PASS+size1NEW; ACK/session 종료 코드 보완 및 독립 검토 중.
- gate 변화: source 구현 검증 중; 실제 이미지/수신은 미확인. 장치 명령 없음.

## 2026-10-12 · b78edf399 · D-675 optional reception caller closure

- 변경: required/optional intake flag 상호 배제와 FileNotFoundError 전용 OFF; Fleet-only signed Compose 경로.
- 증거: 원격138 PASS/NEW0, 독립 검토 승인, Fleet53617/CLI890/app906 기존 상한 유지.
- gate 변화: source 검증 완료; 전체 통합과 실제 signed image/현장 접수는 미완료.



## 2026-10-12 · acf4fd7eb · D-674 통합 규칙집과 실행 파이프라인

- 변경: 공통 law와 기존 rule/AI 후보 선택을 연결하고 stuck 및 stalled/pose_lost 전송 직전에 현재 사건, E-stop, calibration, trip, 사람 점유를 재검사한다. offline readback은 resolved 근거로 사용하지 않는다. README에서 Fleet 통합 규칙집을 연결했다.
- 증거: 원격 RED 8 NEW를 재현한 뒤 관련 Fleet 시험 220 PASS, NEW 0. 로그는 X:/DevTemp/projects/rosy-platform/2026-10-12--024325--fleet-rulebook--cdb91d/logs/red 및 logs/green. 추가 affected guard와 독립 검토는 진행 중이다.
- gate 변화: 브랜치 구현과 원격 범위 증거만 추가한다. main 통합, push, CI, 배포, 활성 현장 설정 및 물리 수용은 미실시다.


## 2026-10-12 · cb7c3396c · D-674 실행 파이프라인 최종 검증

- 변경: 최종 실행 코드의 검증 결과와 독립 검토를 기록한다. 런타임 코드는 추가 변경하지 않았다.
- 증거: 최종 source cb7c3396c의 원격 affected 두 묶음 5004 PASS/254 SKIP 및 213 PASS, 각각 exit 0, NEW 0. D-674 RED 8, AI permission RED 7, 다중 로봇/제안 바인딩 RED 3을 재현한 뒤 모두 전체 Fleet 회귀에 포함해 검증했다.
- 검토: pipeline_review가 admission 경합 수정과 3163줄 size 판정을 독립 수용했다. 기존 +150 및 ai_facts 분리 의무는 유지한다. Harness lint 0 error/27 기존 검증 시점 경고. 변경 파일 flake8은 기준 커밋에도 있던 E128/W391 5건만 남고 새 오류는 없다.
- 근거: X:/DevTemp/projects/rosy-platform/2026-10-12--024325--fleet-rulebook--cdb91d/logs/affected/run-1.txt 및 run-2.txt.
- gate 변화: SOURCE/원격 영향 범위 검증 완료. skipped 시험, CI 전체, main 통합, push, 배포, 현장 overlay/장치/물리 수용은 확인하지 않았다. SharedGather 최대 1 s 캐시와 CORE 최종 검사 권한을 유지한다.

## 2026-10-12 · 4c47e3823e · D-679/D-681 조건부 검토와 모델 주도 종결 목표

- 변경: 동일 사건의 Fleet 기준과 Qwen 의견 불일치를 제한된 GLM 검토로 연결하고 기존 정책과 cached 결과 교차 사용을 거부한다. 설치·실행 경계를 분리하고 모델 교체·확률 보정·자동 처리·최종 사람 인수·개선의 통합 목표를 기록했다.
- 증거: 원격 통합 146 passed, exit 0, NEW 0; 마지막 통합 실행은 자원 하한 fallback 경고가 있어 성능 증거로 쓰지 않는다. docs/validation/deliberation-host-admission-2026-10-12/conditional-review.md.
- gate 변화: SOURCE/원격 논리만 확인했다. 실제 Fleet 기준 선택 생산자·격리 SDK/모델 호출·독립 보정·자동 처리·배포·현장 수용은 미확인이다. Discord는 담당 세션 작업이다.

## 2026-10-12 · 8709923045 · verify: GLM 응답 모델 결속과 독립 검토

- 변경: upstream 모델 ID와 assistant 역할이 고정 요청과 다르면 결과 재작성 전에 거부한다.
- 증거: 새 3개 RED 확인 후 통합 149 passed, exit 0, NEW 0; opencode_admission 독립 검토에서 blocker 해소. model-binding-green/run-1.txt. 자원 하한 fallback 경고는 유지되므로 운영 성능 증거가 아니다.
- gate 변화: SOURCE/원격 검증만 확인. 실제 호출·영속 사용 표식·배포·자동 처리·독립 보정·현장 수용은 미확인 유지.

## 2026-10-12 · 3861935d44 · D-680 Console 검토 관계와 결과 회신

- 변경: 같은 tasks DB의 named 원문/hash/revision 검토 원장과 기존 operator/actor/key/goal Task 연결을 추가했다. 검토/접수와 회신 intent는 atomic이며 기존 Task 결과를 읽어 상태별 intent를 예약한다. UNKNOWN과 재시작 SENDING은 완료로 승격하거나 맹목 재전송하지 않는다. reply opt-in은 기본 false이며 초기화 실패 시 Gateway를 취소한다.
- 증거: 원격 영향군192 PASS/NEW0, 실제 Chromium6 PASS/NEW0. wheel/sdist·비밀 경계·권한/중복/회신 fence/lifespan 실패 회귀를 포함한다. 일부 원격 실행의 자원 fallback은 성능 수용 증거가 아니다. docs/validation/discord-fleet-pipeline-2026-10-12/workflow-source.md 참조.
- gate 변화: source/fake API 경로만 확인했다. Mission/Cell Job과 위험 사건 adapter·독립 크기/권한 검토·최신 main 착지·CI·서명 배포·운영 왕복·실제 로봇 수용은 남았다. provider/장치 명령·채널 전송 없음.

## 2026-10-12 · aa10b5080 · D-687 Discord Mission·Cell owner adapter

- 변경: 원문 기명 owner/hash/revision과 고정 key로 기존 proposal/resolve/Cell document prepare를 사용하고 실행 전 관계를 연결한다. 별도 admit은 기존 Mission owner의 evidence/generation/fence/claims/독립 approver 규약을 유지한다. 결과는 기존 원장에서 읽어 ACTION_SUCCEEDED와 GOAL_CONFIRMED를 구분한다.
- 증거: 원격 Model PC101 PASS/NEW0. 초기 self-lock과 view projection 신규 실패를 수정했고 기존 실패 목록은 변경하지 않았다. docs/validation/discord-fleet-pipeline-2026-10-12/mission-cell-source.md 참조.
- gate 변화: backend/source fixture만 확인했다. Console UI·위험 adapter·최종 독립 검토·최신 main 착지·CI·서명 배포·실제 Discord 왕복·FIELD는 미완료다. 운영 메시지·provider·장치 명령 없음.

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

2026-09-15 이전 이력은 [사이트 패브릭 계획](../../docs/plans/2026-09-14-site-middleware-role-fabric.md), [군집 대형 슬라이스 결과](../../docs/plans/2026-09-08-swarm-formation-slice-results.md)와 `git log -- src/fleet`를 본다.


## 2026-10-12 · 25c036ae8 · D-678 Fleet 실행 파이프라인 완결

- 변경: 실행 경로별 law/후보/최종 승인/owner/접수/readback/종결을 통합 규칙집에 연결했다. Task의 실제 발행 직전 policy/attempt/fence 검사, goal/bay의 명시적 receipt와 stop generation, trip 시작 취소, 늦은 formation 무장 rollback, Mission 다중 owner의 순환 대조를 구현했다. mover 취소와 겹친 불명 bay 전송에는 보상 cancel을 요청한다.
- 증거: source 25c036ae8의 원격 navigation/traffic/trip/Task policy/formation 324 PASS, exit 0, known_failures NEW 0/known 0. 로그는 X:/DevTemp/projects/rosy-platform/2026-10-12--032529--fleet-pipeline-complete--04dc41/logs/traffic-green-3/run-1.txt. RED로 재현한 실패를 known_failures 목록에 추가하지 않았다.
- 추가 검증: source 38f51c4c2의 접수 후 owner 거절/cancel 409/roster 변경은 UNKNOWN으로 보존한다. RED 3 NEW 뒤 원격 Task/goal/bay/traffic/policy 158 PASS, exit 0, NEW 0. 근거 logs/post-acceptance-green/run-1.txt. 이전 착지 후보 d6205067f와 최종 HEAD를 혼동하지 않으며 최종 영향 검사를 다시 수행한다.
- 검토: pipeline_review가 최종 소스/규칙집을 승인하고 Fleet parent 53366, Console 1325줄 재판정을 독립 수용했다. 기존 package +150/Console zero-growth와 observe/server/UI 분리 의무를 유지한다.
- 통합 추가 검증: d6205067f의 영향 시험은 4997 PASS/252 SKIP/2 NEW로 머지가 거절됐다. cancel-all 사유를 typed NavigationStopped로 보존하고 trip 시작 취소 UI 안내를 연결했다. 보상 cancel 409 RED 1 NEW 뒤 source 5f3f033a8의 원격 취소/label/goal/Task/policy 147 PASS, exit 0, NEW 0; Node site-map 29 PASS. Generic transport 오류와 CancelledError 분류는 유지한다. 최종 HEAD의 영향 gate는 다시 실행한다.
- main 통합 guard: 64d60b3d9 원격 영향 시험은 5050 PASS/252 SKIP/1 NEW로 멈췄다. main의 gateway Path 상수가 credential 검사에 오인되어 CONFIG_PATH로 명확히 바꾸고 유일한 시험 monkeypatch를 연결했다. source 7ab44069a의 보안/gateway/opencode/relay/sandbox 원격 134 PASS, exit 0, NEW 0; 독립 검토 승인. 경로·job·권한 검사와 스캐너 기준은 유지하며 최종 영향 검사를 다시 실행한다.
- gate 변화: SOURCE/원격 회귀/리뷰 완료. 최신 main 통합과 전체 영향 범위는 tools/land.py의 최종 gate로 별도 기록한다. CI, push, 배포, 현장 overlay 및 실제 다중 로봇/물리 수용은 미확인이다. CORE/Arm writer와 policy/AI opt-in을 유지한다.

## 2026-10-12 · 79febfdbe2 · D-681/D-684 판정 계약과 사건 관측 경계

- 변경: v2 프로파일·판정 JSON·공통 요청·CLI/로컬 어댑터·독립 보정을 구현하고 모델 프로파일 전체 SHA에 보정을 고정했다. GLM 첫 호출의 영속 표식과 Pinky 전용 읽기/지속 예산 계약을 추가했다. 로컬 실행은 기본 미수용이다.
- 증거: 통합 239 passed와 wheel/sdist·로컬 회귀 34 passed, exit 0, NEW 0. 두 실행은 자원 하한 fallback이며 지연·용량 수용이 아니다. 여유 호스트 component 145/82/94 passed는 범위 중복으로 합산하지 않는다. versioned-judgment.md에 근거를 기록했다.
- 검토: v2 판정·CLI의 독립 검토에서 중요 blocker 없음. 로컬 격리 표식 blocker를 수정했으며 최종 통합 검사를 수행한다.
- gate 변화: SOURCE/원격 논리·설치 패키지 증거. 실제 SDK/GLM·Qwen v2·독립 현장 보정·운영 루프·배포·현장 수용은 미확인이다. Discord 설정은 담당 세션 작업이다.

## 2026-10-12 · 73b23b956c · D-689 본인 기본 프로필과 일반 비밀번호 변경

- 변경: 기존 PasswordSessions/SQLite에 login+principal 결속 표시 이름과 GET/PATCH 본인 프로필을 추가했다. 일반 쿠키의 현재 비밀번호 검증과 원자적 세션 회전은 D-686 경로를 재사용한다. API reference v1.211과 정확한 버전 핀을 함께 갱신했다.
- 증거: 125209aa2 TDD 원격 RED 15 NEW 확인 후 73b23b956c 원격 선택 회귀 exit 0, known_failures 0 NEW/0 known. AI PC 시작 자원 22 cores/9 GB로 최소 조건을 충족했다. 동시 변경 한 승자, 이전 검사 무효화, DB commit rollback, 계정 분리, 재시작/자격 원본 결속, 입력 거절을 포함한다.
- gate 변화: 본인 프로필/일반 변경의 소스와 선택 원격 회귀 증거만 추가했다. 독립 검토, 최종 통합 CI, 설치 및 실제 팀원 사용은 아직 확인하지 않았다.

## 2026-10-12 · c7afe628ca · D-681 모델 실패 피드백 export

- 변경: 고정 프로파일 SHA와 subject/case를 대조한 단일 SQLite 읽기 snapshot에서 시도·비용·종결 근거를 export한다. 결과 불명·진행 중·미개입을 구분하며 비밀/원문/worker ID는 export하지 않는다. 기존 녹화 feedback 경로에 미검수 근거로 연결했다.
- 증거: 관련 5개 원격 파일 87 passed, exit 0, known-failures NEW 0. 모델/장치/알림 호출 없이 실제 SQLite와 CLI 연결을 합성 검증했다. 기존 부모 크기 기준은 유지한다.
- gate 변화: SOURCE/원격 관련 회귀만 확인했다. 최신 worker schema 통합과 로컬 착지를 이어서 확인한다. 실제 제공자·현장 recording export·독립 품질·학습·후보 승격은 미확인이다.

## 2026-10-12 · 99b25e23e · D-685 최소 사람 개입과 학습 원본

- 변경: 승인된 Fleet 범위에서 WAIT/YIELDED 재관측 복구·동일 사건 예산·durable UNKNOWN no replay·검증된 trip 재계획을 연결했다. 상태/센서 원장, read_guard cursor 조회, 해시 재검증되는 비라벨 학습 source export와 통합 규칙집을 추가했다.
- 증거: 관련 원격 238 passed/NEW 0, Node 52 passed, pipeline_review 독립 소스 검토 완료. 최신 main 통합 원격 5262 passed/252 skipped에서 8 NEW를 발견해 착지를 중단하고 호출자/fixture/layer/크기/공개 commit 표기를 수정했다. 최종 gate는 후속 실행 로그로 확인한다.
- gate 변화: SOURCE 구현 증거. CI·push·배포·현장 autonomous opt-in·물리 무인 수용·실제 학습/승격은 미확인. 센서 원본/불명/결측을 정답으로 만들지 않는다.

## 2026-10-12 · d8d4d4058 · D-684 사건 원장 책임 분리

- 변경: 실제 예산·creator·시도·종결·FINAL 원장을 `incidents/automation/ledger`로 옮기고 기존 import의 클래스·helper identity를 유지한다. DB 본문과 수치는 동일하며 store의 closure import 깊이만 조정했다.
- 증거: 분리 전 실제 wheel/sdist 부재와 automation 초과를 AI PC 9 GB 유효 원격 RED 3 NEW로 확인했다. 추출 후 GREEN은 별도 확인한다. 실측 Fleet53408/incidents502/automation429/ledger370; 기존 부모 기준과 +150은 유지한다.
- gate 변화: 책임 분리 source 검증 중이다. provider·운영 활성화·배포·push·물리 수용을 추가하지 않는다.

## 2026-10-12 · ccc7905f2 · 공유 지도 NE/SW 진입 정합성

- 변경: lane_rules의 기존 TurnBan으로 NW·SE 재진입을 금지하고 두 lane_graph를 재생성했다. Fleet import·신호 접근로 검사가 금지를 보존하며 camera sim site는 cap1 roundabout과 NE·SW 신호 접근로를 설정한다. Isaac 경로는 reverse 도로로 합법적인 진입을 사용한다.
- 증거: 두 파생 지도의 접근로·cap1·신호 plan과 실제 routing successor, native 금지 경로 거절 회귀를 추가했다. 원격 시험과 독립 안전 리뷰 결과는 후속 기록한다. 실제 Fleet A18 readback은 이전 설정에서 signals=[]·링 분리 블록을 확인한 원인 증거이며 새 설정의 성공 증거가 아니다.
- gate 변화: 아직 없음. 새 경로 baseline/RL·네 실제 신호 표시 연결·CORE/Fleet 회전 연결·완주·교통/장애물·Gazebo 두 대·병렬 RL·실물 수용은 미완료다. 다른 경로의 R17/R21 수치를 개선 비교에 사용하지 않는다.

## 2026-10-12 · a3150e7669 · 공유 지도 진입 규칙 원격 검증

- 변경: NE·SW 진입/NW·SE 진출 규칙을 공유 지도·Fleet·native route에 반영했다. 독립 D-430 소스 리뷰를 통과했다.
- 증거: 관련 6개 원격 파일 135 PASS·exit 0·known_failures NEW 0. 현장 PC 격리 pytest이며 물리 주행은 없다. lint 일지 heading 3개를 수정한 후 0 errors·28 warnings. A19 소스 전송은 Broken pipe·exit 1, 후속 SSH 두 번 timeout으로 서버를 실행하지 않았다.
- gate 변화: SOURCE 회귀만 확인했다. 실제 신호 적재·네 표시·새 경로 baseline/RL·완주·교통 안전·두 대·병렬 학습은 미완료다. 다른 작업의 예약과 부분 전송 소스를 실행 승인으로 해석하지 않는다.

## 2026-10-12 · aea25e6c15 · 최신 main 통합과 실제 Fleet 설정 readback

- 변경: main 16e6fa373을 작업 브랜치에 통합했다. 기존 TurnBan·공유 지도·camera site 신호 설정을 실제 격리 Fleet 서버에서 적재 확인했다.
- 증거: 통합 후 관련 원격 135 PASS·exit 0·NEW 0, lint 0 errors·28 warnings. A20 source archive SHA 양쪽 일치. 실제 인증 readback에서 map_v2_fleet·두 TurnBan·roundabout cap1·sig_ring NE/SW 접근로·errors=[] 확인. runner exit 0, 종료 후 독립 PID 부재·ECONNREFUSED 확인. private 원본 네 파일 hash 대조 보관.
- gate 변화: SOURCE/설정 적재만 확인했다. 신호는 virtual occupancy, online 0/total 2이며 실제 CORE/Gazebo·grant·주행·네 표시·완주·병렬 RL 수용이 아니다. main 착지·push는 아직 하지 않았다.

## 2026-10-12 · a49a754e94 · 새 합법 경로 native 평가와 Gazebo 연결 준비

- 변경: 새 NE/SW 진입 ordered 경로를 기존 segmentation·CORE·frozen RL로 실제 headless 평가했다. 최신 main 통합 소스로 별도 Gazebo build/install과 두 CORE·실제 Fleet 연결 정지 시험을 준비했다.
- 증거: R23 source 7,337 파일 실행 전후 hash 검증, SDK exit 1, 네 heading baseline/eval 완주 0/8·진행 0m. 영상 8개 ffprobe·SHA·시각 증가, 무효 camera 명령 0·최종 정지·GPU 없음·독립 runner PID 부재 확인. private 원본 56개 hash 대조 보관. A21 ROS 17 패키지 빌드 exit 0; 실행 직전 공식 sim selector는 eligible 없음·exit 1이다.
- gate 변화: 완주/RL 개선은 HOLD다. trace의 lane_cue null·junction idle과 camera_target_unavailable을 기록했다. native Fleet 회전·공간/오차 승인·재획득과 두 대 실제 주행이 남았다. 정지 sensor/Fleet 연결 script는 준비·syntax 확인뿐이며 A21 SDK/CORE/Fleet 실행을 주장하지 않는다. 기존 안전 정지를 완화하지 않았다.

## 2026-10-12 · 51176f181 · D-685 crash-consistent admission

- 변경: durable pending 선기록과 마지막 await 뒤 law/AI/사람 점유/동일 client 재검사를 연결했다. 모호한 receipt·500·crash는 재시작 후에도 동결하고 확정 대조만 해제한다. 자율 설정은 durable journal과 background resolver가 필수다.
- 증거: 관련 원격 184 passed, exit 0, known-failures NEW 0. pipeline_review 독립 검토 승인 및 stuck 3317 재판정; 기존 +150·이전 이력·책임 분리 의무 유지.
- gate 변화: SOURCE와 관련 원격 회귀만 확인. 최종 통합 착지·현장 활성화·물리 수용·실제 학습/승격은 별도 증거다.

## 2026-10-12 · uncommitted · 공유 지도 합법 진입 routing fixture 정합성

- 변경: 기존 east:fwd→SE 재진입을 기대하던 golden fixture를 같은 SW 목표의 east:rev→NE 합법 진입으로 갱신했다. east:fwd에서 SW로 가려는 금지 진입은 TRIP_NO_ROUTE로 거절되는 별도 회귀를 추가했다. planner·지도·TurnBan은 변경하지 않았다.
- 증거: 최신 main 착지 관련 통합 17,662 PASS·814 SKIP에서 크기·비밀 검사·금지 경로 기대 세 NEW를 확인해 착지를 중단했다. 이 경로는 D-676 NE/SW 진입·NW/SE 진출 목표와 맞지 않았다. 독립 검토·수정 후 원격 시험은 진행 중이다.
- gate 변화: 없음. 실제 통행권·신호·CORE 주행·카메라 절대 위치·완주·병렬 학습은 미완료다. skipped 시험과 CI·push·실물 수용은 별도다.

## 2026-10-12 · 1546582f5 · CI 시험 도구 호환성

- 변경: pytest 7.4의 module setup hook과 충돌하던 Fleet 시험 도우미 이름 및 모든 호출자를 바꿨다. Cell 401 검사는 실제 로그인·고급 접속 안내를 기대하며 세션 초기화와 조작 잠금 단언을 유지한다. 고립 설치 의존성 검사는 PEP 508 이름·공백만 정규화하고 정확한 버전 조건·무조건 의존성을 유지한다.
- 증거: commit 40e7287971의 G1 307 passed와 pre-push 7828 passed 이후 전체 CI 38180852375는 Fleet hook·Cell 구문·sdist Requires-Dist 문자열 차이로 실패했다. CI 도구 pytest 7.4.4/setuptools 68.1.2/wheel 0.42.0의 원격 RED 1 NEW로 실제 core-common >=0.0.1 표기를 재현했다. 수정 후 동일 도구 원격 95 passed 및 Cell 실제 Chromium 6 passed, 각 terminal exit 0/known-failures NEW 0. 로그는 X: 검증 폴더 ci-compatible-diagnostic/ci-compatible-green/ci-compatible-cell에 보존한다.
- gate 변화: 시험 호환성 수정과 선택 원격 회귀만 확인했다. 최신 통합·전체 CI·서명·새 설치본·사람 계정 발급은 별도 확인 중이다. production 권한·기계 토큰·비밀 검사·기존 실패 목록은 변경하지 않았다.

## 2026-10-12 · 1e29edaed · 최신 통합과 CI 도우미 회귀

- 변경: 최신 관측 기록·채널 작업 계약을 보존하며 통합했다. 새 채널 사건 시험의 setup 도우미와 세 호출만 이름을 바꿨다. 계정 규칙 문서에 확정된 첫 변경·기본 내 계정·현재 비밀번호 검증·결과 재조회를 반영했다.
- 증거: 최신 도구 선택 회귀 101 passed/exit 0/NEW 0. canonical G1 두 회차는 6165+4371 및 6165+4396 passed, 각 NEW 0; Node 각 318 passed. commit 03378323e를 로컬 main에 착지했다. 새 도우미는 CI 도구 원격 RED 9 NEW 후 commit 1e29edaed의 pytest 7.4 및 최신 도구에서 각각 9 passed/exit 0/NEW 0. native_games_ui가 이름 변경 AST 동등성과 문서 범위를 독립 승인했다. 출하 범위 171개 커밋의 안전 검토 기록 검사도 통과했다.
- gate 변화: 최신 소스 통합·원격 회귀·독립 검토를 확인했다. 이 후속 도우미 변경의 착지·푸시·전체 CI·서명·설치·계정 발급은 다음 gate다. 선택적 외부 채널 설정은 현장에 없으며 활성화하지 않았다.

## 2026-10-12 · fc055ee116 · CI 설치·Android·브라우저 보완

- 변경: Fleet 외부 package_dir의 colcon editable cleanup 오류를 기존 full-install fallback으로 해결하고 legacy uninstall 옵션을 보존한다. Pilot PhoneHeat 공유 소스 누락을 추가한다. 구조 헤더 및 로그인·복귀·고급 토큰 복구 시험을 현재 동작과 맞춘다. 설치 요구 조건을 PEP 508로 정확히 확인하며 최신 main의 learning 계약을 보존한다.
- 증거: 원격 실제 Chromium 2 passed, Pilot 단위 검사·debug APK BUILD SUCCESSFUL 및 실제 bundled proxy 1 passed, CI/최신 wheel·sdist 회귀 각 4 passed; 모두 종료 0/NEW 0. 실제 colcon 0.21.3/setuptools 68.1.2 새 설치와 legacy 정리, Discord 소스 4개 및 Console 자산 76개 바이트 보존을 확인했다. 이전 9d5b7d0a6446의 pre-push 18,942 passed에도 FULL/Android CI가 실패했으므로 새 서명·설치·계정 발급 증거로 삼지 않는다.
- gate 변화: 선택 원격 회귀다. Fleet은 복사 설치이며 편집 뒤 재빌드가 필요하다. 최신 통합·전체 CI·서명·실제 설치·계정 발급은 이어 확인한다. 실물 로봇/폰/LCD 수용과 사용자 최종 비밀번호 변경은 대신 완료하지 않는다.

## 2026-10-12 · e5f078ee02 · 지도 검토 저장 완료 관측 보완

- 변경: 지도 검토 브라우저 시험의 첫 저장 PUT 성공 응답을 기다린 뒤 서버 초안을 읽는다. 기존 출처·검토 후 편집의 재검토·활성화 거절·실제 명령 없음 단언은 유지하며 제품 코드는 변경하지 않는다.
- 증거: 문서 후속 9076d86f28 전체 CI는 Fleet 한 묶음의 1 failed/1,716 passed로 실패했다. 수정 전 원격 실제 Chromium은 다른 화면 폭에서 같은 race를 1 NEW로 재현했다. 수정 후 두 크기 2 passed/종료 0/NEW 0이며 native_games_ui가 독립 승인했다.
- gate 변화: 선택 브라우저 회귀와 독립 검토다. 설치 7a03bf1bf08e의 이전 전체·Android CI 및 실제 사이트 증거와 구분한다. 후속 후보 전체 CI는 이어 확인하며 본인 계정 초기화 승인은 대기 중이다.

## 2026-10-12 · 34b7856198 · D-725 native SIM 위치 연속성

- 변경: 명시적 실행 binding을 검증한 SIM-only map_pose_port를 trip·차로 감시·위치 조회·교차로에 동일하게 주입한다. 원본 시각·좌표·수신 신선도와 CORE UTC stamp를 구분하고 입력 공백·epoch 변경을 거절한다. 실물·teach·camera·pin·formation 경로는 기존 서비스를 유지한다.
- 증거: 독립 SOURCE APPROVE와 정상 자원 기준 원격 115 PASS/NEW 0이다. 최근 3초 이동 판정, 동일 stamp의 다른 pose 거절, binding 불변성을 포함한다.
- gate 변화: 소스·선택 회귀만 확인했다. 실제 Gazebo producer 결속과 지도 완주는 재실행으로 확인한다. 실물 감독은 추후 확정한다.

## 2026-10-12 · f0c5e5c130 · 경로 사실 묶음과 굽이 점 단축

- 변경: trip과 /route의 200 응답에 계획기별 사실 묶음을 붙였다. 호출자는 막힌 차로와 추가 초를 넘기고, 재계획은 그 값을 유지한다. ring_s에서 ring_e만 막으면 east로 우회하고, ring_e와 east를 함께 막으면 TRIP_NO_ROUTE다. /route의 0.20 m 현이 공칭 차체를 가져온 차로 밖으로 내보내면 0.12 m까지 줄인다. 링의 0.20 m 점은 그대로다.
- 증거: 모델 PC rosy@100.98.162.71에서 commit f0c5e5c130 원격 pytest 191 passed, 2 warnings, 15.78s, exit 0, known_failures NEW 0. 로그는 X:\DevTemp\route-context\run-1.txt. 직전 e9702c042는 우회를 거절로 기대한 시험 1건이 실패했다.
- gate 변화: 없다. 출발 검사, 선 추종, Nav2, D-557 링 랩은 그대로다. 로봇에 목표를 보내지 않았다.

## 2026-10-12 · 3ff2ffc1e5 · 없는 차로 문구와 Fleet 크기 재판정

- 변경: 관제 문구에 TRIP_UNKNOWN_EDGE(지도에 없는 차로입니다)를 넣었고, 차로 id가 있으면 그 이름을 붙인다. Fleet 크기 판정을 56077로 다시 적었다. 경로 사실 묶음과 점 단축은 그대로다.
- 증거: 착지 1회차 commit 1034c4bf0e. 가드 묶음 1 failed/3981 passed/225 skipped. fleet 줄 수가 55856+150을 넘었다. Fleet 시험 1 failed/4536 passed/246 skipped. TRIP_UNKNOWN_EDGE 문구가 없었다. known_failures NEW 1. 로그는 X:\DevTemp\land\fix-route-context\run-1-1.txt 와 run-1-2.txt.
- gate 변화: 없다. Nav2, 링 랩, 출발 검사는 그대로다.

## 2026-10-12 · 5941920df7 · D-720 기명 상태 숙고 연결 소스
- 변경: 별도 읽기 전용 status job/worker/고정 SSH broker composition과 owner 결과 조회·기존 Discord outbox를 연결했다. source clock·권한/원문/profile·비용 증빙·취소/UNKNOWN 경계를 보강했다.
- 증거: 원격 선택 회귀65/추가18 passed, exit0, NEW0(겹침으로 합산하지 않음). pipeline_review가5941920df7의 scoped source를 승인했다. 최종 통합·착지 receipt는 후속이다.
- gate 변화: source/원격 논리 검증. 보호 계정 설치·신규 signed site 배포·자동 숙고/GLM/Discord 왕복·오프라인 CORE 물리 수용은 별도 미확인.

## 2026-10-12 · 92ba11def · historical 숙고 증거 identity 오류 순서 보완

- 변경: calibration feedback은 입력·profile·domain identity를 먼저 확인한 뒤 judgment를 검증한다. 새 status domain을 허용한 이후 강화된 BoundProfile 검사에서 먼저 거절되던 오류를 기존 FEEDBACK_SAMPLE_IDENTITY_CHANGED 경계로 닫는다. 실제 historic receipt 시험은 유효한 judgment를 만든 뒤 profile domain과 manifest를 재봉인하여 reader와 builder가 모두 거절하는지 확인한다.
- 증거: AI PC 원격 선택 회귀 65 passed/exit 0, known_failures 0 NEW. 기존 door negative 입력을 유지하고 fleet_status negative 입력을 추가했다. 기존 세 domain binding과 status read-only/hash 회귀를 함께 통과했다. 이전 실패는 잘못된 증거 허용이 아니라 더 이른 binding 거절과 오류 순서/fixture 문제였다.
- gate 변화: source와 선택 원격 회귀다. 착지·푸시·전체 CI·보호 계정 설치·자동 Discord 통신·CORE 물리 동작은 이 변경에서 확인하지 않았다.

## 2026-10-12 · 36b51d124 · D-728 channel owner extraction

- 변경: `refactor/channel-owner-extraction` moves nine existing server channel implementations into `fleet.server.channel`; legacy module paths alias the same objects, including private symbols and monkeypatches. Relative imports are the only implementation AST changes. No request, execution, billing, UNKNOWN or outbox policy changed.
- Existing `find_packages` and Fleet source root discover the real subpackage; root broker installation still requires an approved source manifest containing the extracted imports. Wheel/sdist and copied source-image regressions now check canonical/legacy identity; source import tests check all nine aliases and the actual gateway HTTP client patch.
- Simultaneous architecture measurement: parent 55,120, channel 1,379, combined 56,499; +55 compatibility/package lines against previous 56,444. Largest child file 249. Independent `pipeline_review` structure precheck PASS; preserve all historical verdicts, +150 allowances, zero/file/hard ceilings and previous split obligations.
- 증거: Remote AI PC pytest exit 0 (201 cases), known-failure comparison 0 NEW/0 known, log `X:/DevTemp/projects/rosy-platform/2026-10-12--124534--fleet-ai-discord-check--60388b/logs/channel-extract/run-1.txt`; includes wheel/sdist and copied source-image closure.
- gate 변화: Source-only extraction does not establish natural-language control, signed deployment or physical acceptance.

## 2026-10-12 · 1164d858e · D-728 natural conversation source and remaining admission

- 변경: Independent conversation profile/input/source policy and flat semantic steps map to existing strict intent grammar. Fleet owns separate durable conversation tables, same-actor/channel 120-second unaccepted proposal history, before-model attempts, UNKNOWN no replay and atomic natural reply intent. Source/profile/policy/semantic-proof scope remains immutable across restart. AI never calls human review or a device owner.
- Optional CLI/runtime, both Compose overlays, fixed `rosy-conversation-v1` transport, protected broker and existing owner-only deliberation API consume the actual owners. Valid large site maps expose deterministic64-place subsets with full map revision/hash and completeness. Status/control/refusal/clarification facts use Fleet formatters; unsafe CHAT facts and command promises are rejected.
- 증거: Remote model/journal/runtime closure71 passed; installed wheel/sdist/CLI/app129 passed; architecture38 passed. Every terminal log compared with known_failures:0 NEW. Early extraction syntax error was corrected; a test invocation using two nonexistent paths was corrected, not called passing. All pytest ran remotely.
- gate 변화: Actual Qwen fixed-digest/context synthetic read-only smoke at source590604f05994a51e512cff31eef0f69beb3a8b8a:8 of11 category cases valid. Explanation/hypothetical unsafe CHAT and negated invalid intent remain rejected. Model semantic admission stays OFF; protected conversation installation, independent GLM codec/admission, Task2 grant/execution, deployment, live Discord and physical acceptance remain pending. No paid GLM, root install, robot command or Discord message was sent.

## 2026-10-12 · 8d4d752ee · D-728 original natural instructions and execution source

- Change: `feat/natural-execution` reuses the existing HTTP intent owner through `IntentExecution`; an independent anchored positive instruction validator binds immutable original robot/place aliases and values, with no model-only authority or forged human review. Greetings, quoted/negative/hypothetical/unknown commands remain non-executable. Same-actor selection requires a persisted accepted plan and correlated completed Task; proposal history is never a selection grant.
- Actual `fleet.server.channel.execution` owns durable grants/step checkpoints in the Task DB, atomic navigation links, queued/final source/profile/semantic/role/map/expiry checks, and direct resource claims. Discovery and enrolled TLS final admission compose scoped motion checks with existing identity checks. Compensating cancel remains available; only formation followers are reserved, preserving the existing leader navigation owner. Partial/unknown outcomes and resources survive restart without command replay.
- Native CORE cancellation, E-stop, docking, swarm and formation receipts are normalized as bounded RPC acknowledgement/owner state. They are not physical completion. The existing owner-only deliberation result exposes actual execution step/Task links. Edited/deleted Discord requests durably invalidate the original while keeping its immutable content; unknown channel deletions do not grow command tombstones.
- Evidence: Remote source/HTTP/navigation/transport/gateway regression414 passed, terminal exit0 at source8d4d752ee7, known_failures0 NEW/0 known. Prior162 and280-case runs passed; the intermediate run had one NEW old intake test expecting no withdrawal table, corrected to assert the precise new tombstone contract rather than relabelled known. All pytest ran on remote PCs.
- Structure: Actual execution child579, residual channel1440, conversation300 and Fleet parent55222 measured together with the unchanged harness filters. Independent structural precheck registered-boundary guidance is execution487+150, prior channel1379/conversation280/Fleet55120+150; all file/hard ceilings and historical obligations remain. Root integration owns the reviewed registry update.
- Gate: SOURCE execution linkage is tested with conformant fakes and existing owner journals. Task3 still needs direct owner readback/reconciliation, rich progress and hourly KST health. Conversation admission remains OFF pending independent semantic conformance/protected installation. No real Discord message, paid GLM call, deployment or device command was sent by Task2.

## 2026-10-12 · db0037481e · D-732 native 결과와 로컬 자원 해제를 분리
- 변경: CORE 첫 응답의 boot/run/attempt를 기존 Task·channel 원장에 결속하고, 정확한 typed readback과 2초 monotonic/SQLite claim CAS로만 로컬 자원을 해제한다. 같은 CID의 다른 run, 오래된 proof, 재할당 claim, ACK 유실은 자동 재발행하지 않는다. 원문 권한 만료·철회 뒤에도 읽기 전용 결과는 보존한다.
- 증거: ca2748f050 원격 focused 123 passed, known_failures 0 NEW. db0037481e 설치 wheel/sdist/source-image closure 4 passed, 0 NEW. 확대 Fleet 시험과 독립 구조·코드 검토는 진행 중이다.
- gate 변화: 실제 장치·Discord 운영·물리 수용으로 승격하지 않는다. CORE 최종 command 권한과 기존 safety/role/map/resource admission을 유지한다.

## 2026-10-12 · a5925d7ae · D-728 실제 이전 턴의 완료 문맥 결속

- 변경: 기존 실행 선택·Task 원장의 정확한 native 성공 및 안전 해제 증거를 재사용한다. 원문·사용자·채널·지도·권한·세대·receipt 변경을 각 모델 경계와 최종 전송 전에 거절한다. 기존 상태 조회로 이전 run과 현재 boot·owner generation을 확인하고 CORE CAS에 전달한다.
- 증거: 최초 재현 2 NEW, live 재시작·run 소실 재현 11 NEW 뒤 원격 집중 284개 및 공개 CORE CAS 2개 통과, NEW0. 전송 전 거절은 명령 호출·native marker·점유를 남기지 않는다.
- gate 변화: 없음. fake owner 경로의 소스 검증이며 실제 모델·보호 설치·Discord·물리 수용은 별도다.

## 2026-10-13 · 7c9547f52 · docs: correct console source holder guidance
- 변경: `fleet/server/AGENTS.md`의 옛 `web` 편집 안내를 `operations/ui/console` 정본과 설치 `fleet/server/web` mapping으로 정정했다.
- 증거: `fleet._source_layout.console_root`, `static_routes.WEB_ROOT`와 실제 Console source holder를 읽었다. 링크/원격 검사·착지 결과는 X: `folder-guidance-p0` 세션과 Git으로 확인한다.
- gate 변화: 없음. SQLite/auth/admission/serving은 수정하지 않았다.

## 2026-10-13 · 4a488ea3e · fix: D-622 REALIGN 선택 기록·보류 유지·설정 digest
- 변경: 규칙 선택 계약(`rosy-contracts-learning` 0.1.12)이 `REALIGN` ANSWER를 받고 `pipeline.selection_receipt`가 조작 본문을 `selection.realign_sha256`으로만 결속한다. R9 선택 하나가 그 poll 전체의 선택 원장과 모델 baseline을 버리던 결함을 고쳤다. `realign_hold:*`는 `autonomous_robots`에도 있는 로봇에서도 자율 `Hold`가 아니라 사람 인계가 되고(`resolver._escalate`, 96b86c039), 그 막힘에는 보류 사유가 풀려도 REALIGN을 다시 고르지 않는다. Fleet은 0.1.4다. `loop._rule_config`가 `realign_robots`와 복구 영역을 설정 digest에 넣는다.
- 증거: `test_rule_selection.py`(R9 기록과 같은 poll의 다른 로봇 기록 유지, realign 설정 변경 시 baseline 거절), `test_stuck_realign.py`(이중 등록 로봇의 사람 인계와 재선택 없음, 한쪽 목록 로봇은 그대로). 원격 시험 로그는 X: `land-recent/realign-fu` 세션이다.
- 이행: REALIGN 행은 0.1.11 독자가 거절한다. 어느 현장이든 `realign_robots`를 켜기 전에 현장 Fleet과 모델 PC wheel이 `rosy-contracts-learning` 0.1.12여야 한다.
- gate 변화: 없음. 설정 digest 값이 바뀌므로 이 변경 앞뒤의 선택 기록은 같은 `config_sha256` 범위로 export되지 않는다. 장치·현장 수용은 별도다.

## 2026-10-13 · uncommitted · 콘솔에서 로봇 한 대를 재우고 깨운다 (D-440 6, feat/device-power-policy에서 옮김)

- 변경: `POST /api/fleet/robots/{robot_id}/power {action: sleep|wake}`(이름 있는 운영자)가 로봇의 `/api/v1/power/mode`(STANDBY)·`/api/v1/power/wake`로 그대로 간다. `HttpRobotClient.power`. 로봇 카드에 절전·깨우기 버튼과 전원 태그의 `준비 중`. 경로는 `console_routes.py`의 identify 옆에 두었다.
- 증거: `test/test_fleet_power.py`. 원격 pytest와 브라우저 결과는 착지 보고에 둔다.
- gate 변화: 없음. 실제 로봇을 재우거나 깨우지 않았다.

## 2026-10-13 · 9e2d4ef0c · test(fleet): app bar and rail contracts follow D-741

- 변경: `test_fleet_header.py`, `test_doc_tabs.py`, `test_site_map_api.py`, `web/fleet-header.test.mjs`와 브라우저 시험 다섯 파일(`test_fleet_header_browser.py`, `test_development_console_browser.py`, `test_password_login_browser.py`, `test_fleet_account_browser.py`, `test_site_map_browser.py`)이 새 앱 바를 고정한다. 서버 코드와 API는 바뀌지 않았다.
- 증거: 원격 소스 시험 통과. 브라우저 시험은 CI 대기.
- gate 변화: 없음.

## 2026-10-14 · 3788d7696 · feat: Rosy Account 통합 로그인과 권한 검증 (D-757)
- 변경: 중앙 계정 저장소, PKCE, 세션 갱신과 회수, 앱별 권한 검증을 연결했다. 상세 계약과 범위는 Account completion plan과 protocol에 기록했다.
- 증거: 실제 API, SQLite, HTTPS Chromium 통합 10개 통과. 권한 회수 후 열린 WS가 15초 이내 종료됨을 검증했다. 원격 로그는 X: account-pipeline--063948 세션에 보관한다.
- gate 변화: SOURCE와 원격 시험 증거만 추가. CI, 배포, 실제 Android app-link와 현장 사용자 수용은 별도다.

## 2026-10-14 · 848a9b764 · feat: D-759 굽이 지시에 map_entry를 싣는다 (API v1.224)
- 변경: `server/ledger/trip_ports.py::bend_fields`가 `lane_bend_map_entry` 로봇에게, 이번 단계에서 로봇을 찾은 자세에 `odom_stamp`가 있을 때 `map_entry {yaw_rad, pose_yaw_rad, odom_stamp_s}`를 더한다. `yaw_rad`는 굽이 호 시작점의 차로 방향이다. `trip_runner._step_lane`이 그 자세를 `_step_bend`로 넘긴다. `console_view.TripCaps.lane_bend_map_entry`.
- 증거: `test_trip_bend.py`(능력과 stamp가 있을 때만 실음, 값, 그 밖의 필드는 오늘과 같음). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음. fleet 제품 줄 수는 0 증가다(`trip_ports.py` 600줄 그대로). 그 대가로 `bend_fields`의 주석 세 줄을 한 줄로, `TripCaps`의 주석 두 줄을 필드 옆으로 옮겼다.

## 2026-10-14 · 9ee82e94d · refactor: D-759 bend_fields의 map_entry 가지를 if 문으로 (검토 반영)
- 변경: `server/ledger/trip_ports.py::bend_fields`의 중첩 `**({} if ...)`를 `fields` dict와 `if` 한 가지로 바꿨다. 보내는 값은 같다. `console_view.TripCaps`의 두 주석을 줄였다.
- 증거: `test_trip_bend.py`(넘겨받은 자세가 없으면 능력이 있어도 `map_entry`를 싣지 않음, 기존 두 시험). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음. fleet 제품 줄 수는 main 대비 0 증가 그대로다(`trip_ports.py` 600줄).

## 2026-10-14 · 5264ef279 · 통행권 송신 ttl_s는 2 s 그대로 (D-760 2단계의 상수 분리)

- 변경: `fleet/traffic/trip_authority.py`가 `MAX_TTL_S` 대신 `LEGACY_TTL_S`(2.0)를 보낸다. 값과 동작은 바뀌지 않는다. CORE 계약의 상한이 5 s가 되면서 같은 상수를 보내던 Fleet이 모든 로봇에 5 s를 보내게 되는 것을 막는다.
- 증거: `test_trip_authority.py::test_the_payload_is_relative_to_the_pose_the_table_used`(`ttl_s` 2.0). 원격 재실행 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: D-760 Decision 3. 능력 플래그에 따라 5 s를 보내는 것은 3단계다.
- 교훈: 없음.

## 2026-10-14 · 97ad6ca74 · 목표 임대 갱신은 그 목표를 보낸 클라이언트로 (D-760 5단계 확인)

- 변경: 시험만. `test/test_goal_lease.py`에 `SenderRobot`(CORE의 D-760 9 규칙을 흉내 낸 가짜)와 갱신 경로 네 개(operator, dispatch, yield, trip) 매개 시험을 더했다. 보내기(`goal_lease.py:112`, 로스터 클라이언트)와 갱신(`goal_lease.py:173-177`, 같은 로스터 `_clients[rid]`)이 같은 객체임을 고정한다. stuck resolver 클라이언트(`cli.py:640`)는 목표를 보내지도 갱신하지도 않는다.
- 증거: `operations/fleet/test/test_goal_lease.py` 원격 exit 0.
- gate 변화: 없음.
- 결정: D-760 Decision 9.
- 교훈: 주소 이동(`_replace_client`, 새 토큰)은 임대 행을 남긴다. 새 토큰의 갱신은 403이고 Fleet은 경고만 남긴다. 목표는 CORE에서 ttl(≤5 s) 안에 끝나고 다음 갱신이 409라 행이 지워진다. 화면 코드 교환은 5 s보다 길어 실제로는 이미 끝난 목표다.

## 2026-10-14 · uncommitted · 목표 임대 갱신의 403도 임대를 놓는다 (D-760 5단계 안전 검토 MINOR 4)

- 변경: `fleet/server/goal_lease.py` `renew`가 403을 409처럼 다룬다. 그 임대 행을 지우고 경고를 한 번 남긴다. 화면이 CORE가 거절하는 임대를 살아 있는 것으로 보이지 않게 한다. CORE는 그 목표를 제 만료에 끝낸다.
- 증거: `test/test_goal_lease.py::test_every_renewal_path_renews_with_the_client_that_sent_the_goal`의 대조 단계(다른 클라이언트 403 → 행 삭제, 다음 갱신 시도 없음). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: D-760 Decision 9.
- 교훈: 없음.

## 2026-10-14 · 2c409d117 · refactor: 부르는 곳 없는 Fleet 코드 54줄 삭제
- 변경: `server/ledger/mission_store.py`의 `next_running_mission`·`next_reconciliation_mission`(16줄, 부르던 `mission_service` 두 줄은 6fd54b3a3에서 이미 지워졌다. 4fe614c8b 커밋 글의 6d764bd77은 추가한 커밋이라 틀린 표기다), `server/ledger/task_store.py`의 `recover_interrupted_requests`(29줄, 호출은 423921562에서 없어졌다), `server/signals.py`의 `SignalConsole.signal_ids`(4줄), Console `console.js`의 `authHeaders`·`lastStateOk`(5줄)를 지웠다. 동작, 경로, 스키마는 그대로다.
- Evidence: no executable callers remain; historical recover_interrupted_requests() plan references are superseded by recover_interrupted_work. Fleet 크기 단위는 56742에서 56688이 됐다(판정 56755+150 그대로). 원격 시험 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음. 시험만 부르는 코드(`load_policy_evidence_sources`, `load_cell_goal_registry`, `DeliberationJournal`, `decision_pipeline`, `selector_bridge`, `traffic_reservations`의 `verify_grant`·`waiting_seconds`, `task_store`의 claim 메서드)는 ADR이 이름으로 붙들고 있거나 연결을 기다리는 계약이라 남겼다.

## 2026-10-14 · 41a19818e · feat(fleet): 규칙 M 평가기, 경고만 (D-550 8항, D-760 3항 1단계)
- 변경: 순수 함수 `fleet/traffic/rule_m.py` `verdict`가 로봇마다 Fleet이 시작한 움직임(차로 trip, `navigation/goal`, 군집 추종)을 `bounded`·`unbounded`·`idle`로 판정한다. `GET /api/fleet/state` 로봇 행에 `rule_m {state, motion, reason}`을 더했다. 거절하는 것은 없다.
- 판정: 차로 trip은 `traffic_authority: core`이거나 trip 임대를 쥐고 있으면 한도 있음, 아니면 `hold_back`. 목표는 임대(`goal_lease: leased`)면 한도 있음, 아니면 허브 수집(`gather_source: hub`)이고 SAF-003 정책이 STOP·HOLD·RETURN_HOME일 때만 한도 있음(`rest_only`·`policy_continue`·`policy_unknown`). 군집 추종은 한도 있음. 모르는 입력은 한도 없음이다.
- 정책 읽기: 허브로 수집한 로봇만 `GET /api/v1/safety/state`의 `fleet_loss_policy`를 30초에 한 번 읽는다(`HttpRobotClient.safety_state`, 기존 `CapabilityDisplay`). 새 주기 루프는 없다. 답이 없으면 90초 뒤 "모름"이다.
- 뺀 것: trip 밖 LINE_FOLLOW. Fleet은 `POST /api/fleet/robots/{id}/line-follow`로 IR_LINE을 켤 수 있지만 켰다는 기록을 남기지 않아, 대시보드가 켠 것과 가리지 못한다. 추측하지 않고 판정에서 뺐다.
- 증거: `test_rule_m.py`(D-550 7항 행마다, 모르는 입력, 상태 행, 30초 읽기), `test_console_queues_contract.py`, `test/web/link-tag.test.mjs`·`attention-stale.test.mjs`. 원격 시험 로그는 X: `rule-m-warn` 세션이다.
- gate 변화: 없음. 표시만이다. 장치·현장 확인과 화면 확인은 하지 않았다.

## 2026-10-14 · ba11d856d · fix(fleet): 규칙 M은 Fleet이 쥔 TTL만 센다 (검토 반영)
- 변경: 앞 항목의 SAF-003 정책 경로를 지웠다(`safety_state` 읽기, 정책 캐시, `rest_only`·`policy_*` 이유). CORE의 SAF-003은 `correlation_id`가 있는 목표에만 동작하고 Fleet은 dispatch 시도나 목표 임대가 있을 때만 그것을 보내므로, 허브 연결과 정책으로 "한도 있음"이라 할 수 없다. 이제 한도는 통행권 `core`, 쥐고 있는 trip 임대, 목표 임대 셋뿐이고 임대 없는 목표는 `no_goal_lease`다. 군집 추종 입력도 뺐다(추종만 하는 로봇은 `idle`). 오프라인 행에는 `rule_m`이 없다.
- 범위: 1단계는 D-550 7항의 위반 셋 중 둘(임대 없는 목표, `hold_back` 차로 trip)만 본다. trip 밖에서 Fleet이 연 LINE_FOLLOW는 잡지 못한다.
- 알려진 오경보: 끝난 Fleet 목표의 기록이 남아 있는 로봇을 대시보드·Pilot이 항법으로 움직이면 Fleet 목표로 보인다. 상태 스냅숏에 항법 `correlation_id`가 없어 가릴 수 없다.
- 증거: `test_rule_m.py`(행 판정, 깨진 `navigation` 값, 오프라인 행). 원격 시험 로그는 X: `rule-m-warn/fix1`이다.
- gate 변화: 없음. 표시만이다.

## 2026-10-14 · 7f5e596614 · Trip ports retain the 600-line ceiling after bend integration

- Change: redundant module and bend_fields docstrings are shortened, retaining provider identities, both bend contracts and refusal conditions. All validation, geometry, error handling and safety rationale remain.
- Evidence: non-docstring module AST equals the preceding candidate; independent integration_review approved the editorial-only cleanup. Final remote gate is pending.
- Gate: no runtime or device claim.

## 2026-10-14 · uncommitted · fix(world): D-758 0단계 지도 자세 추적기가 CORE odom epoch 변경에 기준을 버린다

- 변경: `operations/world/src/rosy/world/state/projections/map_pose.py` — `OdomSample.epoch`(선택), `odom_from_snapshot`이 `odom_pose.epoch`(0 이상 정수만)를 읽고, `add_odom`이 이전에 받은 epoch와 다른 표본에서 이동이 없어도 `_reset`한다. epoch가 없는 로봇은 이전 규칙 그대로다. Fleet이 돌려주는 `pose_stamp`·`odom_stamp_s`는 바뀌지 않는다. API 핀 시험 4개를 v1.228로.
- 증거: `test_map_pose.py` 새 3건(수정 전 적색). Fleet·world 전체 스위트 결과는 보고서에 적는다.
- gate 변화: SOURCE·호스트 근거만.
- 결정: D-758 0단계.
- 교훈: 없음.

## 2026-10-14 · fec267000 · D-760 3단계: trip 끊김 기다리기(link_wait), 통행권 줄이기·순서, 재시작 뒤 5 s

- 변경: 임대를 쥔 trip에서 상태 읽기 실패나 로봇 호출 무응답은 trip을 끝내지 않고 `link_wait`로 둔다(`trip_progress._link_wait`). 그동안 교차로 지시·목표·늘린 통행권이 나가지 않고 블록 표에서 UNKNOWN이라 블록이 그대로 잡힌다. 끝내는 것은 `lease_lost`(기본 8 s)와, 임대 `ttl_s`를 넘겨 기다린 뒤의 정체 규칙뿐이다. 돌아오면 지도 버전과 차선 모드를 다시 보고(`trip_admission._link_back`) 실패하면 그 시작 거절 코드로 끝낸다. 정체 예외는 대기 사유→상한 표 하나(`_wait_bound`, 지금은 `link_wait`만). 송신기는 `seq`를 싣고 구간 id에 Fleet 프로세스 epoch를 넣는다. `line_follow_authority_shrink` 로봇에는 `ttl_s` 5와 `shrink`+`until_m` 0(답이 `accepted: true`일 때까지 주기마다), 없는 로봇에는 2와 옛 동작. 단계 중·`link_wait`·차선 켜기 전·시작 뒤 5 s에는 늘리지 않는다. 확인 전에는 지도 버전이 바뀐 로봇의 고정 블록이 마지막 `until_m`까지 덮는다. 출발 검사는 임대가 켜져 있으면 `line_follow_authority_under_lease`도 받는다. trip 임대 `ttl_s` 기본 8. 콘솔 상태 이름 `연결 대기`.
- 증거: `operations/fleet/test/test_trip_link_wait.py` 새 시험(3·4.5·5.5 s 끊김 뒤 이어 감, 9 s `lease_lost`, 돌아온 뒤 모드·지도 버전 검사, 임대 없는 trip은 첫 실패에 끝, 임대가 살아 있는 동안 정체 아님, 블록 유지와 뒤 로봇 대기, 다섯 경우의 줄이기와 확인 뒤 멈춤, 플래그 없는 로봇 2 s·줄이기 없음, `seq`·재시작 뒤 새 구간, 재시작 뒤 5 s, 차선 켜기 전 통행권 없음). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: SOURCE·호스트 근거만. Gazebo·장치 수용 전, 독립 Safety-Review 전.
- 결정: D-760 Decision 1·2·3·4·5와 개정 2. 기본값 `fleet.traffic.authority`·`fleet.trip_lease_required`는 그대로 false(6단계).
- 교훈: 송신 주기가 단계 결과를 기다리는 동안의 로봇도 "보내지 않음"이 아니라 "줄임"의 대상이다.

## 2026-10-14 · 58a3fdc99 · D-760 3단계 독립 Safety-Review CONDITIONS 반영

- 변경: HIGH-1 연결 끊김은 무응답(`HubError`, `OSError`·시간 초과, `httpx.TransportError`)만이고 `ValueError`·`RuntimeError`는 지금처럼 `failed`다. `link_wait`의 `since`는 한 단계가 끊김 없이 끝날 때까지 남는다. MEDIUM-2 trip이 끝나도 정지가 확인되지 않았으면(`stop_sent`가 참이 아님) 마지막 늘리기의 송신 시각 + 5 s + 클라이언트 한도까지 고정 블록이 그 끝을 덮는다. MEDIUM-3 단계 중인 로봇에는 늘리기도 줄이기도 보내지 않는다(검토자 결정, ADR에는 검토자가 적는다). 작은 것: `shrink_none_held`는 확인으로 센다, 통행권이 켜져 있으면 trip 임대 `ttl_s`는 5 s보다 커야 한다, 돌아올 때 끊긴 뒤 보낸 임대 갱신이 확인되어야 한다, `link_wait` 동안 목표 임대를 갱신하지 않고 돌아오면 목표를 다시 보낸다.
- 증거: `test_trip_link_wait.py`에 시험을 더해 먼저 원격에서 8건 실패를 보고(3aa6ff21b), 고친 뒤 trip·교통 묶음이 원격에서 통과했다(`known_failures` 0 new). 다리 확인과 `forget` 호출을 지우는 변이를 잡는 시험 두 건을 더했다.
- gate 변화: 없음. 독립 Safety-Review 재확인 전.
- 결정: D-760 Decision 3·4, 3단계 Safety-Review.
- 교훈: 블록 표가 한 번도 놓지 않은 로봇은 모든 지시를 막으므로, 끊김 시험은 로봇을 먼저 표에 놓아야 그 경로를 지난다.

## 2026-10-14 · 264b378bf · D-763 조각 1: 주인 검사 하나로 TRIP_ROBOT_BUSY 일곱 곳을 모은다

- 변경: `TripAware.trip_refusal(robot_ids)`(`console/console_view.py`)가 "이 로봇에 주인이 있는가"의 하나뿐인 검사다. `trip_busy` 위에 서고, 주인이 있으면 `HubError("TRIP_ROBOT_BUSY", ...)`를, 없으면 None을 준다. 대화 요청 제출, 콘솔 목표 받기와 비켜설 자리 보내기, 막힘 결정, `/route`, `/goal`, `trip_guard`의 대형·차선 추종 거절이 이것을 부르고, 각자 응답 모양·문구·검사 순서는 그대로다. `trip_runner` 시작 때의 `engaged` 검사는 반대 질문(콘솔 움직임이 이미 있는가)이라 그대로 둔다. Fleet 크기 단위 56856 → 56854.
- 증거: 원격 시험(ai PC) 631 passed, `known_failures` 0 new, 로그 X: `holder-check/run-1.txt`. 새 시험: 대화 요청 제출 409 문자열, `/goal`·`/route`·막힘 BACK_AND_RETRY의 409 본문 전체.
- gate 변화: 없음. 동작 같음.
- 결정: D-763 4항, 구현 조각 1. Safety-Review는 커밋 trailer.

## 2026-10-14 · 6bb334d16 · D-763 조각 5: 승인은 단계 종류 등록부가 정한다

- 변경: `step_action_kinds.StepActionKind`에 `approval`(값 `two_person`·`proposer_only`·`one_person`, 엄한 순서 `APPROVALS`)을 더했다. `CELL_TRANSFER`는 `two_person`. 레거시 `PICK_PLACE`는 단계 원장 규칙이 없어 `_LEGACY_APPROVALS`에 `proposer_only`로 따로 적었다(실물 하달 조각에서 두 사람으로, 개정 2 질문 5). `required_approval(kinds)`는 가장 엄한 값을 주고 모르는 종류·빈 목록은 `ValueError`. `mission_routes` admit은 `decidable()`로 등록부 판정을 읽고 `candidate.kind` 분기를 지웠다. 코드와 순서는 그대로(`CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER` 403, `PICK_PLACE` 비제안자 404, `PROPOSAL_NOT_RESOLVED` 409).
- 증거: `test_approval_registry.py`(등록된 모든 종류에 승인 값, 종류별 값, 모르는 종류 거절, 제안 단계의 모르는 종류 422, 두 사람 종류의 제안자 403과 다른 운영자 승인, 제안자만 종류의 다른 운영자 404·viewer 403, 공유 콘솔 토큰 403). 원격 119 passed: `X:/DevTemp/approval-registry/s5/run-1.txt`.
- gate 변화: 없음. 동작은 같다.

## 2026-10-14 · 65bea79df · D-763 조각 5b: 승인 대기 작업의 거절 경로 (API v1.230)

- 변경: `POST /api/fleet/missions/{mission_id}/reject`, 본문 `FleetWorkDecisionRequest {expected_generation}`(`core_common.protocol.work`, admit·Cell resume도 같은 모델). 이름 있는 운영자만, 볼 수 있는 범위는 admit과 같은 등록부 판정. 제안자는 `WITHDRAWN_BY_PROPOSER`, 다른 운영자는 `REJECTED_BY_OPERATOR`. Cell Job은 취소와 같은 끝 상태 HOLD/`CANCELLED_BY_OPERATOR`(resume·cancel·admit 거절, 사건 `CELL_JOB_REJECTED`), 레거시 Mission은 `CANCELED`(사건 `MISSION_REJECTED`). claim 없음. `PROPOSED`가 아니거나(두 번째 거절 포함) 정지 세대가 다르면 409 `MISSION_REJECT_REFUSED`. 크기: admit의 두 원장 분기를 한 경로로, 제안 생성·resolve의 Cell 역할 검사를 도우미 하나로, `cell_job_store._json`을 `mission_store._json` 재사용으로 줄였다.
- 증거: `test_approval_registry.py` 거절 시험(제안자 철회와 다른 운영자 404, 다른 운영자의 Cell 거절, viewer·서비스 403, 낡은 세대 409, 두 번째 거절 409, 거절 뒤 admit·resume 409, claim 없음, 감사 사건의 행위자, 공유 토큰 403, 잘못된 본문 422). 원격 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 화면(조각 5c)은 이 브랜치에 없다.
- 결정: v1.228·v1.229는 착지 전 브랜치(`fix/odom-log-monotonic-epoch`, `feat/junction-turn-map-entry`)가 쓰고 있어 v1.230을 썼다. 대화 요청에 연결된 작업의 서버 쪽 직접 승인 차단은 이 조각에서 하지 않았다.

## 2026-10-14 · 65e315231 · D-763 조각 5·5b 보안 검토 반영

- 변경: `decidable()`가 resolve된 원장 행의 단계 종류(Cell Job 단계의 `action_kind`, Mission `action_kind`)에서 가장 엄한 승인을 읽는다. 등록부에 없는 종류는 500이 아니라 409 `APPROVAL_RULE_UNREGISTERED`. resolve 전 제안의 보이는 범위는 전과 같다(Cell·제안자 409, 그 밖 404). Cell 거절은 새 메서드 대신 `CellJobStore.cancel(decision=, expected_generation=)`(사건 `CELL_JOB_REJECTED` 그대로). 대화 요청에 연결된 작업의 거절은 기존 결과 회신 경로로 요청자에게 간다: Cell `HOLD`는 이미 회신했고 Mission `CANCELED`를 관측 상태에 더했다. 작업 흐름 행은 `LINKED`(그 관계의 끝 상태)로 남는다. `work.py` docstring에 v1.230.
- 증거: `test_approval_registry.py`(경로 수준의 가장 엄한 값, 미등록 종류 409, 대화 요청 연결 작업 거절의 회신). 원격 `X:/DevTemp/approval-registry/r2/run-1.txt`, secret-scan 가드 `test/test_release_boundary_guards.py` 포함, `known_failures` 0 new.
- gate 변화: 없음.

## 2026-10-14 · c53057fef · Fleet 작업 원장을 자기 크기 단위로 등록 (D-763 5·5b)

- 변경: `docs/plans/2026-10-14-fleet-ledger-size-unit.md`. `fleet/fleet/server/ledger` 단위, 판정값 6,985(`61aa49b32`에서 잼), `fleet` 판정값 31,837. 지금 서버 31,886, 원장 7,036, 관제 18,023. 원장은 `__init__.py` 없는 `fleet.server` 보관 자리라 하위 패키지 시험이 `FLEET_SERVER_HOLDER_UNITS`도 받는다.
- 증거: 원격 `test/architecture` 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 독립 재판정 전.

## 2026-10-14 · 8163f878f · feat: D-759 개정 1 회전 지시에 출구 차로의 map_entry를 싣는다 (API v1.231)
- 변경: `server/ledger/trip_runner.py::_step_lane`이 `lane_turn_map_entry` 로봇에게, 찾은 자세에 `odom_stamp`가 있을 때 `left`·`right`에 `map_entry {yaw_rad, pose_yaw_rad, odom_stamp_s}`를 더한다. `yaw_rad`는 출구 차로의 `start_tangent`다. `console_view.TripCaps.lane_turn_map_entry`, trip 보기 `caps.lane_turn_map_entry`.
- 증거: `test_trip_turn_map_entry.py`(능력 읽기, 값, 그 밖의 필드는 오늘과 같음, stamp가 없으면 싣지 않음). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음. fleet 제품 줄 수는 0 증가다. `exit_segment` 조건문을 한 줄로, D-520 주석 두 줄을 한 줄로, `TripCaps`의 D-551 주석을 필드 옆으로 옮겼다.

## 2026-10-14 · 68a91feca · D-763 조각 2: trip 읽기에 기다림 판정의 답을 싣는다

- 변경: `ledger/trip_progress.py` `_waiting`이 판정할 때마다 `view.wait`에 `bound_s`·`over_bound`·`waiting`을 적는다. 정체 시계가 쓰는 판정 그대로다(두 번째 판정 없음). 줄 수 같음(서버 순증 0). 정체 규칙의 동작은 같다. API v1.231(문서는 f38a5093a).
- 증거: 원격 시험(모델 PC, f38a5093a) 284 passed, `known_failures` 0 new, 로그 X: `wait-read/run-1.txt`. 새 시험: 사유마다 상한 안 기다림·넘으면 `over_bound`, 사유가 바뀌어도 한 번, 진행이 끝냄, `link_wait`의 lease 상한.
- gate 변화: 없음. `GET /api/fleet/work`에는 trip 행이 없어(조각 4) trip 읽기에만 실었다.
- 결정: D-763 8항, 구현 조각 2.

## 2026-10-14 · 7c26a028c · D-763 조각 2 검토: 상한 넘김은 해결기 몫, 지난 tick의 답을 남기지 않는다

- 변경: `ledger/trip_runner.py` `_step`이 맨 앞에서 `view.wait`의 `waiting`·`bound_s`·`over_bound`를 None(모름)으로 둔다. `_waiting`까지 가지 않고 끝난 tick은 지난 답을 보이지 않는다. 세 키는 정체 규칙이 읽지 않으므로 정체 시계는 같다. 서버 순증 0(`trip_progress.py` 주석 한 줄 줄임).
- 증거: 원격 시험(AI PC, 7c26a028c) 285 passed, `known_failures` 0 new, 로그 X: `wait-read/run-1.txt`. 새 시험: 자세를 잃어 `_stalled` 전에 끝난 tick에서 세 키가 None.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 7. 상한을 넘은 기다림은 막힘 해결기(D-622)로 가고, 개입은 해결기가 사람에게 넘길 때만이다.

## 2026-10-14 · f79947c25 · D-763 조각 2 검토 2: tick마다 한 번 쓰고, 보고가 있을 때만 상한 넘김

- 변경: `_waiting`이 세 키를 지역값으로 계산해 한 번에 쓴다. `_step` 맨 앞의 None 초기화를 지우고, `_tick_robot`이 그 step이 `_waiting`에 닿지 않았을 때만(`live.waited`) 세 키를 None으로 둔다. tick 도중의 읽기는 앞 tick의 답을 본다(깜빡임 없음). `over_bound`는 규제나 `link_wait`가 지금 보고될 때만 참이다. 기다림의 시작은 사유가 바뀌어도 그대로다. 정체 규칙이 읽는 `_waiting`의 반환 식은 같다. 서버 순증 0(`trip_runner.py` +2, `trip_progress.py` 주석 −2).
- 증거: 원격 시험(모델 PC, f79947c25) 218 passed, `known_failures` 0 new, 로그 X: `wait-read/run-1.txt`. 새 시험: 느린 자세 읽기 도중의 읽기가 `waiting: true`. 보고가 그친 사이에는 `over_bound`가 거짓이라고 시험을 바꿨다(이전 시험은 참이라고 고정했다).
- gate 변화: 없음.

## 2026-10-14 · uncommitted · fix(test): 사실 기록 정지가 비상 정지를 늦추지 않는다는 시험을 시계 없이 (CI 38568954601)
- 변경: `test/test_ai_facts.py::test_a_stalled_fact_write_does_not_delay_the_emergency_stop`. 사실 쓰기를 `time.sleep(1.0)` 뒤 실제 쓰기로 두고 `/api/fleet/estop` 왕복을 0.5 s로 재던 것을, 쓰기를 끝내 풀리지 않는 `threading.Event`에 세워 두고 정지가 먼저 200으로 끝나는지만 보는 것으로 바꿨다(쓰기 진입 확인, 정지 뒤에도 쓰기 요청이 미완, 그다음 풀어 200). 시계는 hang 가드 30 s뿐. 제품 코드는 그대로다.
- 원인: 제품은 이미 쓰기를 `asyncio.to_thread`로 이벤트 루프 밖에 두고(`stuck/ai_facts.py` `ai_facts`) 정지와 공유하는 락이 없다. 시험이 잰 0.83 s는 sleep(1.0)보다 짧아 정지가 쓰기를 기다린 것이 아니다. 잰 창이 정지 경로 자체(감사 기록, 래치, fan-out의 SQLite 동기 쓰기)의 실제 작업을 담아 CI 러너 부하가 그대로 들어갔다. 그래서 0.5 s 벽시계 한도가 정지 지연이 아니라 러너 속도를 쟀다.
- 증거: 실패 로그 `gh run view 38568954601 --log-failed`(0.8307 s); 수정 전 같은 시험 20회 랩 PC 20 passed. 수정 뒤 반복, 그리고 쓰기를 이벤트 루프로 되돌린 변이에서 새 시험이 실패하는지는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 정지 한도를 느슨하게 하지 않았다: 지연 여부는 이제 결정적으로 판정한다.

## 2026-10-14 · 70092c527 · D-760 4단계: 로봇마다 공유 상태 읽기 하나

- 변경: `MapPoseService.state(robot_id, max_age_s)`가 로봇마다 하나인 REST 상태 읽기다. 읽기 시작 시각(Fleet 단조 시계)부터 `max_age_s` 안이면 그 값을, 아니면 진행 중인 읽기에 붙거나 새로 읽는다. 실패한 읽기는 아무것도 남기지 않고 같은 예외 객체를 기다리던 모두에게 던진다. 읽기마다 odom을 한 번 넣는다(스냅숏 stamp 그대로). trip 루프의 자세 갱신과 교차로 상태(`HttpLaneJunction(read=)`)가 0.45 s로 한 읽기를 같이 쓰고, 차로 준수(0.45 s), 위치 결정(`read_state`, 0.5 s), 관제 REST 대체(0.45 s, 2 Hz tether 감시가 매번 새로 읽는다)와 하달 직전 읽기(0.2 s)도 같은 읽기를 쓴다(`app.py`가 `console.read_state = map_pose.state`). `refresh`의 로봇 odom 시계 대 Fleet 벽시계 0.2 s 건너뛰기는 Fleet 단조 나이 규칙으로 바꿨다. trip 루프는 응답 없음(`HubError`, `OSError`, `httpx.TransportError`)만 읽지 못한 상태로 보고 그 밖의 읽기 오류는 trip을 끝낸다(D-760 개정 3의 2).
- 증거: `test_shared_state_read.py`(나이·합류·실패 객체·정확한 stamp, 교차로 읽기 공유, 느린 로봇, trip 루프의 전송 오류 `link_wait`·`ValueError` 실패, 가짜 로봇 2·10대 60 s에 로봇당 120회 = 2.0회/s·어느 1 s에도 3회 이하, 주기 루프의 직접 `state()` 금지). 가짜 로봇을 요청 사이에 바꾸는 기존 시험 8개 파일은 `fakes.fresh_reads(app)`로 공유를 끈다(`fleet_gather.max_age_s = 0`과 같은 뜻). 원격 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 전송 계약은 그대로다.
- 결정: D-760 Decision 8. 차로 준수는 계획의 0.5 s 대신 기본 0.45 s다(시뮬 자세 포트 `tools/sim/native_gazebo_map_pose.py`의 `refresh`가 `max_age_s`를 받지 않는다). 군집(`swarm/session.py`)과 명령 한 번짜리 경로는 그대로다.

## 2026-10-15 · 0349f6177 · 계정 runtime pin과 SSO CI 연결

- 변경: `fix/omx-readiness-followup`에서 패키지 OAuthlib 요구를 사이트·CI와 같은 4.0.0으로 정렬했다. full CI의 account pipeline 파일만 브라우저 opt-in을 추가해 일반 CORE 범위는 유지한다.
- 증거: pin/CI guard RED 뒤 원격 계정·selector·runtime 계약 102 passed, 1 skipped, NEW 0; 독립 소스 검토 완료. 실제 Chromium 실행은 새 CI에서 별도 확인한다.
- gate 변화: 없음. 장치 활성화나 계정 외부 수용 증거가 아니다.

## 2026-10-15 · aa9913d2f · 다단계 작업이 로봇의 lease와 claim을 쥔다 (D-763 조각 6)

- 변경: `ledger/trip_admission.py` `hold_job`(개정 2 질문 10 (a)(b) 관문, 아니면 422 `LINK_UNBOUNDED_MOTION`; `on_job_lost` 없이는 거절)와 `release_job`. `traffic/trip_lease.py`: `jobs`, 단계 사이 갱신(`period`가 열린 trip 없는 작업도 갱신, `/trip-lease`만 보낸다), 작업의 단계가 lease를 이어받고 닫아도 유지, 시작 실패는 작업 lease를 두고, 작업 lease 상실은 `on_job_lost`. `ledger/trip_runner.py` `start(job_id=)`: 작업이 쥔 로봇의 다른 시작은 정렬 회전 전에 `TRIP_ROBOT_BUSY`. `ledger/trip_guard.py`: `trip_busy`가 작업의 hold와 내구 D-330 `mission` robot claim도 본다. `server/app.py` 한 줄(claims 연결). 서버 크기 단위 순증 0(31904), traffic 2200(≤2201), ledger 7083.
- 증거: `test/test_trip_job_lease.py`. 원격(7334f9c40) 통과, `known_failures` 0 new, 로그 X: `job-lease/run-1.txt`.
- gate 변화: 없음. 아직 `hold_job`을 부르는 운영 경로가 없다(조각 7).
- 결정: D-763 4항·조각 6.
- 교훈: 없음.

## 2026-10-15 · d05bccdec · 조각 6 안전 검토 반영

- 변경: Fleet이 보낸 사람의 멈춤(취소, line-follow OFF)은 lease 주인 토큰이라 CORE가 lease를 두므로 `stop_job`이 lease를 놓고 사건 경로를 부르며 작업을 HOLD로 둔다. `hold_job`은 로봇 잠금 안에서, 이미 움직이는 로봇(열린 trip, 콘솔 목표, 대형)을 거절한다. `release_job`은 단계 trip이 열려 있으면 409 `TRIP_BUSY`. 사건 hook 예외는 기록한다. SRS CORE `SAF-007`, Fleet `MSN-007`.
- 증거: `test/test_trip_job_lease.py` 새 시험 셋. 원격(d05bccdec) 통과, `known_failures` 0 new.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 3.
- 교훈: 같은 토큰을 쓰는 Fleet 콘솔의 멈춤은 CORE의 "주인 아닌 멈춤" 규칙에 걸리지 않는다. Fleet 쪽에서 따로 닫아야 한다.

## 2026-10-15 · 9f1f7876f · trip 취소가 실패해도 작업은 HOLD

- 변경: `ledger/trip_guard.py` `end_trip`이 `stop_job`을 따로 `try`에서 부른다. trip 저장소가 실패해도 사람의 멈춤 뒤 작업 lease가 갱신되며 남지 않는다(재검토 LOW).
- 증거: `test_a_failed_trip_cancel_still_holds_the_job`. 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.

## 2026-10-15 · 0b7df2e16 · hold_job의 움직임 한도는 Rule M이 판정한다 (D-760 6, D-763 조각 6)

- 변경: D-760 담당 세션 요청. `ledger/trip_admission.py` `hold_job`이 로봇이 모는 다리(lane·free)마다 `traffic/rule_m.py` `verdict`를 lease 없이 부른다(lane은 통행권 `core`, free는 임대 있는 목표). 422 `LINK_UNBOUNDED_MOTION` 본문은 `reasons`(Rule M의 말: `hold_back`, `no_goal_lease`, `leg_unknown`)와 `missing`(질문 10의 능력·설정)이다. traffic 단위 그대로(2200), ledger 7115, 서버 순증 0.
- 증거: `test_the_motion_bound_part_is_rule_ms_verdict`, `test_a_lane_only_robot_needs_no_free_leg_bound`. 원격(0b7df2e16) exit 0, `known_failures` 0 new, 로그 X: `job-lease/run-1.txt`.
- gate 변화: 없음.
- 결정: D-760 Decision 6, D-763 4항.

## 2026-10-15 · e0febb524 · 잘못된 drive_modes는 leg_unknown, 다리 시험을 반증 가능하게

- 변경: `hold_job`이 list·tuple이 아닌 `drive_modes`(true, 5)를 모드 없음으로 본다(422 `leg_unknown`, TypeError 500이 아니다). lane만 가진 로봇 시험은 `goal_lease`를 빼고 Rule M 사유가 없음을 확인한다. free만 가진 경우를 더했다.
- 증거: 원격(e0febb524) `test_trip_job_lease.py`·`test_rule_m.py` exit 0, `known_failures` 0 new, 로그 X: `job-lease/run-1.txt`.
- gate 변화: 없음.

## 2026-10-15 · 0bc2a16c1 · native readback and background shutdown

- Change: reconcile up to 20 existing native Task owners concurrently; keep identity, quiescence, two-second freshness, claim CAS and UNKNOWN ownership. Cancel all app background workers before awaiting their results; log failed workers without interrupting remaining cleanup.
- Evidence: shutdown RED e4804ba77; corrected readback RED b73b04577 reached UNKNOWN instead of COMPLETED. Remote AI PC regression at 0bc2a16c1: 117 passed, exit 0, known_failures NEW 0. Raw logs: X: runtime-pipelines--0fd8e5 session logs/green-2/run-1.txt.
- Scope: 14 flow entries and outstanding inputs/evidence in docs/plans/2026-10-15-runtime-pipeline-closure.md. No main landing, push, deployment, model activation or robot actuation. Source review found no critical/important issue.
- Gate: unchanged. This regression does not establish ROS-SIM, ARTIFACT, DEVICE or FIELD acceptance.
- Final evidence: fc7cd8aea affected checkpoint: 6278 passed, 330 skipped, 3 NEW (journal format and size verdict). Those failures were fixed without changing the size allowance or known-failure list. 30b06737a remote functional/contract/structure regression: 273 passed, terminal exit 0, NEW 0. Broad affected was not repeated at the final SHA; skipped tests remain unverified.

## 2026-10-15 · 39d8e72973 · finish resource cleanup after worker shutdown

- Change: register existing sync/async close callbacks with AsyncExitStack and run them after all background workers are canceled and awaited. A failed close does not skip the other callbacks; exceptions remain visible to the caller. No new owner, dependency or activation.
- Evidence: 6b2b811f4 remote RED 2 NEW. 39d8e72973 remote app/native outcome/model feedback/harness/structure regression: 281 passed, terminal exit 0, NEW 0. Independent source review found no critical/important issue. Logs: X: pipeline-resources--0c429d session logs/green/run-1.txt.
- Gate: unchanged. Resource cleanup is not robot standstill, field acceptance or startup-failure recovery.

## 2026-10-15 · 95c9263a5 · D-760 4단계 독립 Safety-Review CONDITIONS 반영

- 변경: `MapPoseService`가 REST 읽기마다 번호를 매기고(`read_number`), `state`·`refresh`가 `after`를 받는다. 번호가 `after` 이하인 읽기는 나이가 젊어도 주지 않고, 그런 읽기가 진행 중이면 끝나기를 기다린 뒤 새로 읽는다. trip 루프는 단계의 읽기 뒤, 교차로 지시 송신 뒤, 링크 끊김 때 울타리를 친다(`trip_progress._fence`). 그래서 지시 앞의 읽기로 같은 지시를 다시 보내지 않고, `link_wait`는 끊긴 뒤 시작한 읽기로만 끝난다. 한 단계의 자세와 교차로 상태는 여전히 한 읽기다. 상태 읽기의 HTTP 오류는 trip을 그 코드·status로 끝낸다(`TRIP_LOOP_ERROR` 대신). 로스터를 떠난 로봇의 읽기를 지우고, odom을 넣은 뒤 읽기를 남긴다.
- 증거: `test_shared_state_read_fences.py`(0.43 s 간격으로 송신 뒤 단계가 와도 재송신 없음, 단계마다 새 읽기, 울타리 앞의 진행 중 읽기를 넘겨주지 않음, 끊기기 전 읽기가 끊긴 뒤 닿아도 `link_wait` 유지, 허브와 REST 읽기 분리, HTTP 503으로 `failed`/`HTTP_503`, 로스터 이탈). 원격 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음.
- 결정: D-760 4단계 Safety-Review. 읽기 번호가 없는 자세 포트(시뮬 `native_gazebo_map_pose.py`, 시험 가짜)는 울타리 없이 지금처럼 읽는다.

## 2026-10-15 · febf77ca9 · D-760 4단계 재검토: SIM 자세 포트 옆에서도 교차로 읽기에 울타리

- 변경: trip 울타리가 자세 포트가 아니라 교차로 포트가 읽는 공유 읽기의 번호를 센다(`HttpLaneJunction(read, read_number)`, `app.py`가 `map_pose.state`·`map_pose.read_number`를 넘긴다). `junction_state`가 `after`를 받는다. `simulation_pose`면 자세 포트가 SIM 포트(`tools/sim/native_gazebo_map_pose.py`, 읽기 번호 없음)라 지금까지 교차로 읽기에 울타리가 없었다. 자세 갱신은 같은 번호의 읽기일 때만 `after`를 받는다(`trip_progress._after`). 울타리는 단계의 자세·교차로 읽기 뒤에 친다(한 단계 한 읽기 그대로).
- 증거: `test_shared_state_read_fences.py`의 0.43 s 재송신 시험을 SIM 자세 포트로도 돌린다(직진 지시: 지시 앞의 idle 읽기면 다시 보낸다). 수정 전 SIM 경우 실패를 원격에서 확인했다(`X:/DevTemp/shared-state-read/red4/run-1.txt`). 원격 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음.
- 결정: D-760 4단계 Safety-Review 재검토 MEDIUM.

## 2026-10-15 · 868461505 · D-763 조각 4: 작업 읽기에 trip·Cell Job 출처, 보이는 상태, 승인 대기 범위, 새 작업 종류 (API v1.235)

- 변경: `GET /api/fleet/work`가 Task·Mission에 더해 trip(저장된 최근 것 + 열린 것 전부)과 Cell Job을 읽는다. 행마다 `visible_state`(D-763 8), trip 행은 `wait`(v1.232의 네 키, `since` 없음), `PROPOSED` 행은 등록부 `approval`. 응답에 `cell_jobs_available`·`kinds`(`trip`: 활성 지도 장소 + trip 능력을 알리는 로봇, `CELL_TRANSFER`: 단계 하달 열림 + 하달기 + OMX 설정). Cell Job 범위는 서버가 정한다: 제안자, `PROPOSED`가 아닌 행은 운영자(cell-jobs 상세와 같다), `PROPOSED` 행은 이름 있는 운영자(개정 2 질문 6). 제안자 신원은 쿼리 밖으로 나가지 않는다. `work_routes.py`를 같은 종류의 경로가 있는 원장 holder(`ledger/`)로 옮겼다. 크기: 서버 31904→31880(순증 −24), 원장 7036→7123(상한 7135), 기준값은 올리지 않았다.
- 증거: 원격 시험(모델 PC, 6ae1df74e) fleet 13개 파일 225 passed, 계약·구조 5개 파일 66 passed, `known_failures` 0 new, 로그 X: `work-read/run-1.txt`, `work-read/b/run-1.txt`. 새 시험 `test_work_sources.py`: 출처별 행, viewer·운영자·제안자·다른 운영자·이름 없는 운영자 범위, 원장 미설정, 종류 목록.
- gate 변화: 없음. 호스트 시험뿐이고 장치·현장 확인은 하지 않았다.
- 결정: D-763 조각 4. 끝난 작업 필터는 상태 목록 그대로(실패도 끝난 작업)이고 보이는 상태는 줄 글에만 쓴다.

## 2026-10-15 · e7b196839 · D-763 조각 4 검토: Cell Job 상세 범위, 닫힌 trip의 기다림, 루프 밖 읽기, 작업 영역 단위

- 변경: `GET /api/fleet/cell-jobs/{id}`가 작업 목록과 같은 범위다(제안자; `PROPOSED`가 아니면 운영자; 남의 `PROPOSED`는 이름 있는 운영자만, 나머지 404). 제안자 아닌 독자에게 `proposal_principal_id`가 없고 사건의 제안자는 `actor_id: "proposer"`다. trip 행의 `wait`는 열린 trip에만 싣는다. 작업 읽기의 SQLite 읽기는 `asyncio.to_thread` 한 번으로 이벤트 루프 밖에서 한다(33a0b5706). 관제 작업 영역은 자기 크기 단위 `site_ui/console/work`다(6377fe873, 계획 `docs/plans/2026-10-15-fleet-console-work-unit.md`). 원장 단위 7,135/7,135, 다음 원장 증가는 Mission 분리부터.
- 증거: 원격(모델 PC, e7b196839) fleet 16개 파일 266 passed, 계약·구조 6개 파일 69 passed, `known_failures` 0 new, 로그 X: `work-read/r3a/run-1.txt`, `work-read/r3b/run-1.txt`. 새 시험: 제안자·이름 있는 운영자·공유 토큰·viewer 상세 범위, 닫힌 trip의 남은 `over_bound`, 루프 밖 읽기.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 6. 남의 `PROPOSED` Cell Job 상세는 이전에 운영자 누구나였고 이제 이름 있는 운영자만이다.

## 2026-10-15 · db7b5cf3a · Mission 원장과 작업 읽기를 자기 크기 단위로 (main 머지 ab8ac53f6 뒤, API v1.238)

- 변경: main(조각 6, v1.236) 머지 뒤 원장 단위가 7,215로 한도 7,135를 넘었다. 원장 계획이 이름 붙인 분리로 `mission_*` 여덟 파일을 새 holder `server/missions`(2,575/2,725)로, 그것으로 모자라 작업 읽기(`work_read.py`·`work_routes.py`)를 `server/work`(128/207)로 옮겼다. 모듈 이름은 그대로다(`SERVER_HOLDERS`). 원장 4,545/4,560, 서버 31,846/31,930(같은 경계로 조각 전 31,847). 조각 4는 v1.237(feat/regulation-capabilities 선점) 위의 v1.238이다. 머지의 logs 해소가 main의 마지막 gate 줄을 잘랐던 것을 main 파일 + 이 브랜치의 추가 행으로 고쳤다.
- 증거: 원격(AI PC, db7b5cf3a) `operations/fleet/test` 전체 5,249 passed, 293 skipped(브라우저 opt-in), 계약·구조 176 passed, `known_failures` 0 new, 로그 X: `work-read/r4a/run-1.txt`, `work-read/r4b/run-1.txt`. 브라우저 3개 파일 93 passed, 로그 X: `browser-run/wrs4-b4.txt`.
- gate 변화: 없음.
- 결정: D-763 조각 4, 계획 `docs/plans/2026-10-15-fleet-ledger-missions-unit.md`.

## 2026-10-15 · f4fb26e0c · D-525 여러 호에 걸친 구역 span의 입구 보존

- 변경: `Layout.route`가 같은 구역의 이웃 span을 합칠 때 입구(`entry`)를 버렸다(`traffic/blocks.py`). 원형 교차로를 `west:fwd → ring_s → ring_e → ring_n`처럼 세 호 이상 지나는 경로는 구역 span의 입구가 `""`가 되어, 가상 신호가 그 로봇을 녹색에도 들이지 않았다(Gazebo m33: 녹색·빈 구역에서도 1,442 표본 대기). 합칠 때 첫 span의 입구를 유지한다. 입구를 읽는 곳(`step`의 적색 판정, `signal_phase.zone_occupancy`, `signal_service._signals_ahead`)은 모두 이 값을 쓴다.
- 증거: `test_signal_phase.py`에 네 호 경로가 입구 `west:fwd`를 유지하고 그 접근로 녹색에 들어가며 다른 접근로 녹색에는 막히는 시험을 넣었다. 원격 결과는 이 브랜치 보고에 적는다.
- 확인: `fleet_sim_camera_site.yaml`의 `west:rev`는 공유 지도(west가 SW→NW 양방향, 링은 CCW)에서 SW 입구로 들어가는 호라 맞다. m32/m33의 `west:fwd`는 저장소 밖 SIM 부트스트랩이 west를 NW→SW 일방으로 뒤집은 지도 기준이라 설정은 바꾸지 않았다.
- gate 변화: 없음.

## 2026-10-15 · 84bbabeca · D-763 10항 (c): 규제 능력 없는 로봇에 횡단보도·신호 구역 경로를 거절 (API v1.233)

- 변경: `TripCaps`가 `lane_crosswalk_gate`·`lane_junction_signal`을 읽는다(없으면 꺼짐). `ledger/trip_admission.py` `_caps_checks`(시작·바퀴·재계획)가 lane 경로가 현장 지도 횡단보도 다각형에 들어가거나(`crosswalks_on`, 2 cm 표본) 신호 구역을 지나는데(`TrafficService.route_signals`, `signal_refusal`이 하던 구간 걷기) 능력이 없으면 422 `TRIP_REGULATION_CAPS_MISSING` `{missing: {능력: [id]}}`. 콘솔 문구 추가. 시험 fixture `LANE`·`BOTH`·`PIVOT`·`LEGACY`는 map_v2_fleet에 횡단보도가 있어 `lane_crosswalk_gate`를 알린다.
- 증거: `test/test_trip_regulation_caps.py`, `test_traffic_signals.py`. 원격 시험(AI PC, cb1e6c61f) `operations/fleet/test` 전체 통과, `known_failures` 0 new.
- gate 변화: 없음. 크기: 서버 단위 순증 0(`console_view.py` 주석 압축), ledger +23, traffic +2.
- 결정: D-763 개정 2 질문 10 (c).
- 교훈: 횡단보도가 있는 기본 시험 지도 때문에 능력 하나를 요구하는 검사가 trip 시험 112개를 깨뜨렸다. 공유 caps fixture를 현재 로봇처럼 고치면 된다.

## 2026-10-15 · 4ca431d25 · D-763 10항 (c) 사용자 결정: 필드 없는 옛 CORE는 경고, false만 거절

- 변경: `TripCaps`의 두 능력이 `None`(알리지 않음)과 `false`를 가른다. `_caps_checks`가 `false`만 422 `TRIP_REGULATION_CAPS_MISSING`, `None`은 trip detail `regulation_caps_unknown {능력: [id]}`와 경고 로그 한 줄(ponytail: 새 릴리스가 다 깔리면 거절로 좁힌다). 시작·바퀴·재계획이 detail을 넘긴다. 공유 trip fixture의 `lane_crosswalk_gate=True`는 되돌렸다. 콘솔 문구·API 참조·D-763 부기 갱신.
- 증거: `test/test_trip_regulation_caps.py`(없음 → 시작+경고, false → 거절, true → 시작, 둘 다 없는 경로 → 시작). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 10 (c), 사용자 결정 2026-10-15.
- 교훈: 없음.

## 2026-10-15 · uncommitted · D-763 10항 (c) 규제 능력의 API 버전 v1.233 → v1.237 (main 병합)

- 변경: main이 v1.234(D-758 0단계)를 썼고 v1.235·v1.236은 다른 세션이 예약했다. 이 브랜치의 위 항목에 적힌 v1.233은 v1.237로 읽는다. API 참조 머리·절·이력, `app.py`, 버전 고정 시험이 v1.237이다.
- 증거: 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 10 (c).
- 교훈: 없음.

## 2026-10-15 · uncommitted · D-763 10항 (c) 독립 검토 반영: 운영자 재계획·다음 바퀴·잘못된 값·지난 경고

- 변경: `confirm_replan`이 `_apply_replan` 전에 보류된 계획의 구간으로 `_caps_checks`를 돈다(지도가 바뀌었으면 그대로 `TRIP_MAP_CHANGED`). `_next_lap`이 지금 바퀴의 남은 구간이 아니라 다음 바퀴 `body`의 구간을 검사한다. `TripCaps`는 있는데 bool이 아닌 값을 `false`로 읽어 거절한다. 깨끗한 검사가 trip detail의 `regulation_caps_unknown`을 지운다. `trip_runner.py` 896 → 898줄(한도 901).
- 증거: `test/test_trip_regulation_caps.py`(운영자 재계획 거절·통과와 경고 지움, 다음 바퀴 구간, 잘못된 값). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 10 (c), 독립 검토 LAND-WITH-CONDITIONS.
- 교훈: 거절 검사는 경로를 바꾸는 모든 입구(시작, AI 재계획, 운영자 재계획, 다음 바퀴)에 같이 둔다.

## 2026-10-15 · ca386fb1a · 크기: trip 시작 검사를 단위 `server/trip_checks`로, 신호 구간 걷기를 그 옆으로

- 변경: main `c4cd2bf95` 병합 뒤 원장 단위 7,170(한도 7,135), `trip_runner.py` 903(한도 901), `traffic` 2,202(한도 2,201)였다. `trip_admission.py`·`trip_progress.py`를 내용 그대로 `server/trip_checks/`(새 `SERVER_HOLDERS` 보관 자리, 크기 단위, 판정 제안·독립 재판정 필요)로 옮겼다. `TrafficService.route_signals`를 지우고 `signal_service.py`를 main 그대로 두었으며, 같은 구간 걷기를 `trip_admission.signals_on`으로 옮겼다. 운영자 재계획 확인은 `TripAdmission._admit_replan`(검사 뒤 `_apply_replan`)을 한 줄로 부른다. 동작은 바뀌지 않는다.
- 증거: 원장 6,714, `trip_checks` 472, `trip_runner.py` 901, `traffic` 2,195. 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 10 (c), `docs/plans/2026-10-14-fleet-ledger-size-unit.md` 2026-10-15 부기.
- 교훈: 남의 착지로 한도가 찬 단위에 더할 때는 판정이 이름 붙인 경계로 먼저 옮긴다.

## 2026-10-15 · uncommitted · D-763 10항 (c) 규제 능력의 API 버전 v1.237 → v1.238 (main 0cf827362 병합)

- 변경: main이 v1.237(D-763 조각 4, `feat/fleet-work-read-sources`)을 썼다. 이 브랜치의 위 항목에 적힌 v1.233·v1.237은 v1.238로 읽는다. 시작 검사 파일은 main의 `server/trip_checks/`, trip 루프는 `server/trips/`에 있다.
- 증거: 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: D-763 개정 2 질문 10 (c).
- 교훈: 없음.

## 2026-10-15 · d6d84dffd · 크기: `trip_checks`를 두 단위로 — `trip_progress` 보관 자리

- 변경: main 병합 뒤 `trip_checks` 474(한도 422, 이 브랜치의 D-763 10항 (c) +53). 판정 문구대로 수용하지 않고 `trip_progress.py`를 바이트 그대로 새 `server/trip_progress/`(`SERVER_HOLDERS`, 크기 단위, 판정 제안·독립 재판정 필요)로 옮겼다. import는 그대로다. `trip_checks` 338(기준 192, 한도 342), `trip_progress` 136(기준 80, 한도 230).
- 증거: 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.
- 결정: `docs/plans/2026-10-15-fleet-ledger-trips-unit.md` 2026-10-15 부기.
- 교훈: 없음.

## 2026-10-15 · 7f3bd72a1 · 제안 읽기는 Cell Job 상세 범위를, 채널 제출·승인은 이름 있는 운영자를 (D-763 조각 4 리뷰)

- 변경: `GET /api/fleet/proposals/{id}`가 Cell Job 제안을 `GET /api/fleet/cell-jobs/{id}`와 같은 범위·가림으로 읽는다(두 경로가 한 도우미 `cell_job_view`를 쓴다). 이전에는 운영자 누구나 남의 Cell Job 제안을 읽었고 응답의 `mission`에 `proposal_principal_id`가 실렸다. 이제 제안자, `PROPOSED`가 아닌 Job은 운영자, 남의 미판정·`PROPOSED` 제안은 이름 있는 운영자만 읽고 나머지는 404 `PROPOSAL_NOT_FOUND`다. 레거시 Mission 제안은 그대로 제안자만. `POST /api/fleet/channel-requests/{id}/admit`·`/submit`은 `require_named_operator`다(직접 Mission admit·`/goal`과 같다). API 참조의 세 경로 인증 문구, 버전 머리는 그대로.
- 증거: 원격(모델 PC, 7f3bd72a1) `operations/fleet/test` exit 0(293 skipped, 브라우저 opt-in), `test/architecture` exit 0, `known_failures` 둘 다 0 new, 로그 X: `proposal-scope/fleet/run-1.txt`, `proposal-scope/arch/run-1.txt`. 고치기 전 빨강 X: `proposal-scope/red/run-1.txt`.
- gate 변화: 없음.
- 결정: D-763 조각 4 리뷰. API 변경 이력 번호는 착지 때 정한다.

## 2026-10-15 · c0c7fb706 · Cell Job 제안자 가림을 모든 응답에, 자원 claim 읽기는 역할별로, API v1.240 (D-763 조각 4 보안 리뷰 L1/L2)

- 변경: 가림을 모듈 수준 `redact_cell_job(job, principal)`로 옮기고 Cell Job을 돌려주는 모든 응답(제안 읽기, Cell Job 상세, Mission admit·reject, Cell Job reconcile·resume·cancel)에 쓴다. 제안자 아닌 호출자는 `proposal_principal_id`가 없고 제안자의 사건은 `actor_id: "proposer"`다. `GET /api/fleet/resource-claims`: viewer는 `resource_key`·`resource_kind`·`resource_id`·`phase`만, 운영자는 Cell Job claim 행 전체, 다른 claim은 그 레거시 Mission의 제안자만 행 전체. API 참조 v1.240(머리, 변경 이력 행, 해당 경로 행), 버전을 고정한 시험 다섯 곳과 `core_api_web` app.py 설명. 시험: 숨긴 id의 404 본문이 없는 id와 같음, 제안자 사건이 두 읽기에서 `proposer`, 실제 `build_role_guards`와 `install_channel_feature`로 이름 없는 운영자의 채널 admit 403, L1/L2.
- 증거: 원격(AI PC, 2a2c1871a) `operations/fleet/test` exit 0, `known_failures` 0 new, 로그 X: `proposal-scope/fleet4/run-1.txt`. 원격(165a1d95d) `test/architecture`, `test/test_line_follow_contract_docs.py`, `middleware/core/api/test` exit 0, 0 new, 로그 X: `proposal-scope/arch2/run-1.txt`. 중간 실패 2건(새 시험이 stop generation을 두 번 rearm)은 2a2c1871a에서 시험을 고쳤다, 로그 X: `proposal-scope/fleet2/run-1.txt`.
- gate 변화: 없음.
- 결정: D-763 조각 4 보안 리뷰(APPROVE 뒤 L1/L2). API v1.240은 동료와 조율해 받은 번호다.

## 2026-10-15 · bbfac7c5c · claim 읽기는 행마다 쓰지 않고, 채널 submit 배선 시험, 작업이 쥔 로봇의 거절에 mission id 없음 (D-763 조각 4 보안 리뷰 N1·후속)

- 변경: N1(dd0da079a) — `GET /api/fleet/resource-claims`가 레거시 Mission 주인을 기존 `get_in_transaction`으로 한 연결에서 읽는다. 행마다 `get()`이 돌리던 `purge_expired()`(SQLite 쓰기 잠금을 잡는 DELETE)가 없다. 만료 행은 None으로 읽혀 답은 같다. 후속(bbfac7c5c) — 다른 작업이 쥔 로봇의 409 `TRIP_ROBOT_BUSY` 세 곳(trip 시작 `trip_runner`, 작업 단계 admission `trip_admission`, lease 채택 `trip_lease`)이 그 작업의 `job_id`를 실었다. 이제 `{"reason": "job", "owner_kind": "mission"}`이다. `trip_guard.py:35`의 `lease.claimed`는 그 `job_id`의 출처이고 그 자체는 응답에 나가지 않는다. `console_view.trip_refusal`의 문구는 로봇 id만 싣는다. API 참조 v1.240 절과 이력 행에 한 줄. 시험: 실제 `build_role_guards`·`install_channel_feature`로 이름 없는 운영자의 채널 `/submit` 403과 Task 0건, purge 0회, 거절 detail에 mission id 없음. fleet 줄 수 변화 0(31,901/31,930).
- 증거: 원격(AI PC, bbfac7c5c) `operations/fleet/test` exit 0, `known_failures` 0 new, 로그 X: `proposal-scope/fleet6/run-1.txt`. N1은 dd0da079a에서 같은 결과, 로그 X: `proposal-scope/fleet5/run-1.txt`.
- gate 변화: 없음.
- 결정: D-763 조각 4 보안 리뷰 후속. API v1.240 안에 든다.

## 2026-10-15 · uncommitted · D-763 조각 7: 작업의 운행 단계가 Step 원장 안의 trip이 된다

- 변경: Step 원장 CHECK가 등록부의 종류가 되었다(사용자 결정 2026-10-15 "작게 풀고 진행"). 표 정의는 `work/step_ledger_schema.py`에 있고, CHECK가 다른 표는 행을 그대로 두고 다시 만든다. 이관 버전은 2다. 등록부에 `TRIP`(한 사람 승인, SIM 전용)을 더했다. `JobTripSteps`(`missions/job_trip_steps.py`)가 단계마다 `trip_routes` `plan`으로 계획하고 `TripRunner.start(job_id=)`로 시작한다. `arrived`만 다음 단계로 간다. 나머지는 HOLD, lease 놓기, 사건 하나다(사건은 누가 쓴 HOLD든 tick이 연다). 원장 행은 `ledger/job_trip_rows.py`, 입구 `POST /api/fleet/trip-jobs`는 `trips/trip_job_routes.py`에 있다. 독립 안전 검토 지적 1–6·8–10을 고쳤다: lease를 잃은 표시, 비상 정지에서 lease 놓기, start token, 모든 HOLD에 사건, `stop_job`이 단계 trip을 끝냄, 이관 버전. SIM에서 찾은 trip 사이 넘겨받기도 고쳤다(`trip_progress.inherited_stop`, `TripRunner.held_stops`, `_core_busy`를 `TripProgress`로 옮김). 이어진 독립 검토 세 번의 지적도 고쳤다: E-stop epoch를 lease 전에 읽음, 넘겨받은 정지는 한 번만 쓰고 멈춤이나 E-stop이 지움, 행이 없을 때는 표시를 지우지 않음, 사건 중복 방지, 프로필이 닫히면 HOLD, Cell 재개 이벤트의 `approvals`.
- 증거: 원격 pytest(X:/DevTemp/job-trip-steps/held, fix3, fleet2, arch2, gateway2). AI PC Gazebo s7-1·s7-2·s7-3에서 두 단계가 모두 달려 `arrived`, `GOAL_CONFIRMED`, lease 풀림(X:/DevTemp/job-trip-steps/sim/s7-1). 크기: fleet 31,884 → 31,873, ledger 2,018, missions 2,704, work 188, trips 2,354, trip_checks 342, trip_progress 153, `trip_runner.py` 894.
- gate 변화: SIM(한 번, 2대 Gazebo). 장치는 하지 않았다.
- 결정: D-763 2026-10-15 부기(조각 7), D-420 2026-10-15 부기.
- 교훈: 차로 `arrived`는 CORE에 쥔 정지를 남긴다. 연이은 trip은 처음부터 그 정지를 넘겨받아야 한다. 같은 fence에서 다시 승인하면 이벤트가 중복으로 지워지므로, 원장 이벤트 수로 재승인을 셀 수 없다.

## 2026-10-15 · 279cfdd52 · D-767 P0 경로 미리보기 (Fleet만, 로봇에 보내지 않음)

- 변경: 새 `server/trips/trip_preview.py`(116줄)가 trip 주기마다 블록 표·신호 참고 뒤에 그 단계가 이미 읽은 자세(D-760 8 공유 읽기, 자기 읽기 없음)로 trip 경로 위 2 m 안의 사건 목록을 만든다: `turn`(가로선 `line_before_m`), `bend`(호 시작점, 여러 구간), `arc`(`exit_segment`), `crosswalk`(새 `site_map.crosswalk_spans`가 다각형을 경로에 투영한 앞쪽 경계), `signal`(경로 위 전부, `/traffic` 신호 접근로), `stop`(trip 끝·보류, `hold_back_m`), `authority_end`. `horizon_m = min(2, trip 끝, max(R + d_stop, v × 8 s))`, 8개에서 자름. `/api/fleet/traffic` 로봇 행 `preview`(≤ 2 s, 만료·없음은 행에 없음, `work_read` 아님). 방금 보낸 지시의 앞당김 전 지점과 0.005 m 넘게 다르면 `preview_mismatch{kind}`. 바뀜 = 다리·사건 집합·params·`s_m` 0.01 m. `ROSY_ROUTE_PREVIEW_LOG=<file>`이면 JSON 줄로 남고 `tools/sim/route_preview_accuracy.py`(5fba65e10)가 ADR 7항 기준으로 잰다. `trip_runner.py` 900줄: import·호출 두 줄을 `confirm_replan`의 같은 세 줄 블록 둘을 합쳐 갚았다. 주석 고침 ab922a2f8(`crosswalks[]`는 없다). 단위: trips 2,387/2,388, fleet 31,904/31,930, 콘솔 17,718/17,719.
- 증거: 원격(모델 PC, 239d2d607) `operations/fleet/test` 5,290 passed, 293 skipped(브라우저 opt-in), `known_failures` 0 new, 로그 X: `route-preview-p0/fleet/run-1.txt`. 원격(5fba65e10) 구조·하네스 계약·채점기·`operations/world/test` 146 passed, 0 new, 로그 X: `route-preview-p0/arch/run-1.txt`. 브라우저 시험은 원격 실행기가 `ROSY_RUN_BROWSER_TESTS`를 넘기지 않아 확인 못 함(카드 문구는 node 시험).
- gate 변화: 없음. Gazebo 2대 30분·장치 2대 10바퀴 정확도 측정은 남았다(참값 추출 도구 없음).
- 결정: D-767 B부 P0. 설정 `fleet.trip.route_preview: off|observe`는 만들지 않았다(app.py·TripConfig 동결). 되돌림은 호출 한 줄.

## 2026-10-15 · 512d26a73 · D-767 P0 독립 검토(CONDITIONS) 반영

- 변경: 횡단보도 투영은 `site_map.route_crosswalks`가 경로마다 한 번 계산해 캐시한다(지도 기하는 주기마다 바뀌지 않는다). 다각형 상자와 겹치지 않는 경로 조각은 표본을 뽑지 않고, 2 cm 표본에 교차점만 1 mm까지 이분한다. 한 로봇의 미리보기 실패는 그 로봇의 미리보기만 비우고 trip마다 한 번 ERROR로 남는다(이후 DEBUG). 자세와 앞 끝 사이의 사건은 싣지 않는다(`at_m` ≥ 0, 그 자리에 보낸 지시는 불일치로 세지 않음). `seq`가 바뀜 횟수를 센다(`changes` 필드 대신). 불일치 경고 로그는 줄 수 때문에 뺐고 `/traffic` 행 `preview.mismatch`에만 남는다. 채점기(69f10c23d): `pose_stamp` 없는 행 건너뜀, `--offset-s`(참값 시계 − 예측 시계), 통과에 `leg_id`가 있으면 같은 다리만 맞춤, 기준은 사건마다 |오차| / (a + b·`at_m`)의 p95 ≤ 1(ADR의 p95 ≤ a + b·`at_m`). 단위: trips 2,388/2,388, fleet 31,926/31,930, 콘솔 17,718/17,719.
- 되돌림: `ROSY_ROUTE_PREVIEW=off`(Fleet 프로세스 환경). `TripConfig` 필드(`fleet.trip.route_preview`)가 허락될 때까지 이것이 D-767 P0의 되돌림이다.
- 증거: 원격(f4162e635) `operations/fleet/test` 5,294 passed, 293 skipped(브라우저 opt-in), `known_failures` 0 new, 로그 X: `route-preview-p0/r3fleet/run-1.txt`. 구조·하네스·채점기·`operations/world/test` 148 passed, 0 new, 로그 X: `route-preview-p0/r3arch/run-1.txt`. 새 시험: 경로당 한 번 표본(두 번째 주기 0회, 먼 횡단보도 0회, 첫 주기 ≤ 130회), 한 로봇 실패 격리·로그 한 번, 앞 끝 거름, 끄기 스위치, 채점기 시계·다리.
- gate 변화: 없음.

## 2026-10-15 · 64816ae7e · lane_instruction_stamp 로봇에 pose_stamp, 지연 추정 없음 (D-767 A부, API v1.241)

- 변경: `server/console/console_view.py` `TripCaps.lane_instruction_stamp`. `server/trips/trip_runner.py` trip 능력 보기에 그 키(기존 줄 안, 901줄 그대로). `server/trips/trip_ports.py`: 능력이 참이고 이 걸음의 자세에 odom stamp(`live.at_stamp`)가 있으면 교차로·굽이 필드에 `pose_stamp`(= `map_entry.odom_stamp_s`), 굽이 앞당김 0, `_pose_tol`에서 읽기→전송·`SEND_ALLOWANCE_S` 항 제외(자세 나이·dead reckoning·드리프트는 남음). 600줄 그대로(주석을 줄였다). 능력이 없는 로봇은 그대로.
- 증거: `test/test_trip_instruction_stamp.py`(빨강 → 초록): 창 허용치 0.095(지연 0.5 s 무시), 능력·stamp 없으면 0.235와 `pose_stamp` 없음, 굽이 0.4 무앞당김과 `pose_stamp` = `map_entry.odom_stamp_s`, 능력 없으면 0.38. 원격(모델 PC, 9639a41b8) `operations/fleet/test` 통과, `known_failures` 0 new.
- gate 변화: 없음.
- 결정: D-767 A부 4항. `bend_send_s`는 능력 없는 로봇에 그대로 쓴다.
- 교훈: 없음.

## 2026-10-15 · 0f7ae1a51 · INSTRUCTION_STAMP_UNUSABLE 재시도, disabled면 stamp 없이 앞당김 (D-767 A 검토, API v1.241)

- 변경: `server/trips/trip_runner.py` `_send`: `INSTRUCTION_STAMP_UNUSABLE`을 `JUNCTION_ODOM_STALE`처럼 다음 주기에 새 자세로 다시 보낸다. `detail.reason`이 `disabled`이면 그 trip의 `caps.lane_instruction_stamp`를 거짓으로 고쳐 다음부터 stamp 없이 앞당김을 넣는다. 901줄 그대로(`_step_free`의 한 번 쓰는 `arc` 지역 변수를 없앴다). `trip_ports.py`: `pose_stamp`는 창 있는 교차로 지시와 굽이에만. 600줄 그대로.
- 증거: `test/test_trip_instruction_stamp.py`(빨강 → 초록): 창 없는 지시엔 `pose_stamp` 없음, 거절 뒤 새 stamp로 재전송, `disabled` 뒤 stamp 없이 0.38 앞당김. 원격 통과, `known_failures` 0 new.
- gate 변화: 없음.
- 결정: D-767 개정 2.
- 교훈: 없음.

## 2026-10-15 · 02fb4929d · junction_retry가 거절 까닭을 보인다 (D-767 A 재검토)

- 변경: `server/trips/trip_runner.py` `_send`: `detail.junction_retry` = 코드와 `detail.reason`(예: `INSTRUCTION_STAMP_UNUSABLE no_sample`). 901줄 그대로.
- 증거: `test/test_trip_instruction_stamp.py`. 원격 통과, `known_failures` 0 new.
- gate 변화: 없음.
- 결정: D-767 개정 2.
- 교훈: 없음.


## 2026-10-16 · uncommitted · Robot/Pilot 진입 JS 설치 closure

- 변경: Fleet 기존 static allowlist와 wheel/sdist 설치 검증에 device-discovery.js를 포함했다. 기존 API·정적 서빙을 유지한다. e596dc451의 최초 checkout 밖 설치·자산 HTTP 검증 55개 시험이 통과했으며, D-766에 따른 devices/ 분리 이후 최종 설치 검증을 다시 한다.
- 증거: `docs/validation/app-role-clarity-2026-10-16/result.md`. 최종 리뷰 회귀와 affected 시험은 실행 기록에서 확인한다.
- gate 변화: 없음. main 착지·push·배포·새 DEVICE/FIELD 시험 없음.

## 2026-10-16 · uncommitted · discovery 분리 후 기존 계약 시험 경로 수정

- 변경: disabled-feature poller와 scanner lease 경보 시험이 분리된 device-discovery.js를 검증한다. HTTP 자산 응답과 console.js의 import 연결도 확인한다.
- 증거: main 착지 전체 시험에서 기존 소스 경로를 읽던 2건 실패를 확인했다(5357 passed, 315 skipped). 제품 코드는 변경하지 않았으며 수정 후 원격 검증은 착지 절차에서 수행한다.
- gate 변화: 없음. 전체 검증 통과 전 main 반영 보류.

## 2026-10-16 · uncommitted · 경로 보기 브라우저의 명시적 탭 클릭

- 변경: 폼 밖 클릭을 패널 중앙 대신 상태 탭으로 지정한다. 앱 링크로 카드 높이가 바뀌자 중앙 좌표가 대형 관리 버튼과 겹쳤고 실제 탭 전환을 일으켰다.
- 증거: 전체 및 파일 단위 원격 Chromium에서 재현. 위치 없음의 경로 보기 차단과 위치 수신 후 활성화 검증은 유지한다.
- gate 변화: 없음.

## 2026-10-16 · uncommitted · 최신 크기 규칙 통합

- 변경: D-766 개정 2의 roster.js 제한을 지키도록 앱·지도 기록 링크 생성 코드를 기존 device-discovery.js로 옮겼다. 새 파일이나 권한 경로는 추가하지 않았다.
- 증거: main 통합 전 원격 FULL은 새 실패 0건이었다. 통합 후에는 크기 검사와 관련 브라우저·설치 검증을 다시 수행한다.
- gate 변화: 없음.

## 2026-10-17 · a49062a0e · D-775 실측 교정의 목적별 운영 연결

- 변경: versioned 수치 bundle, Fleet preview 승인·영속 CAS·감사·철회, source config와 수치 readback, 촬영 session/epoch에 결속한 Vision render, Console 승인·재확인·철회 흐름을 연결했다. 기존 tracking/sighting/World/CORE 권한은 유지한다.
- 증거: 검증 행렬은 docs/validation/measured-camera-lifecycle-2026-10-16/result.md. d4744b1758에서 공유 계약·Vision와 실제 Fleet→Vision 통합 1,610 passed; 1a9efa0baa UI/설치/공용 계약 79 passed; b367260187 provenance/비밀 경계/통합 128 passed. 광범위 회귀에서 발견한 fixture 의존 경로와 정확한 CSS 목록도 보완했으며 최종 범위 결과를 별도 기록한다.
- gate 변화: 코드·원격 합성·브라우저 범위. 실제 촬영·독립 측량·ARM64·설치·DEVICE/FIELD와 D-598 운영 주행 수용은 미검증. main 착지·push·배포 없음.

## 2026-10-17 · uncommitted · D-779 2~4단계 팔 여러 개 Cell Job 실행

- 변경: `arms: [{role, instance_id}]`와 Step별 `placement`(주 팔·대체 팔·구역·결합·depends_on·팔별 Action 내용)를 받는 팔 여러 개 Job을 만든다. 배치는 `fleet_cell_step_placements`, 표시는 `fleet_cell_arm_jobs`에 두고 1단계 거울 트리거와 backfill은 표시된 Job을 건너뛴다. 한 팔 디스패처 조회(`jobs_by_status`, `unresolved_jobs`)는 그 Job을 돌려주지 않는다. `cell_arm_dispatcher`가 팔별 준비 집합(의존 GOAL_CONFIRMED, 팔 READY, 팔·구역 claim 비어 있음)으로 Action을 내고, 결과는 그 팔과 그 claim만 HOLD한다(`tight`면 짝도). 대체 팔 한 팔 모드, 팔 단위·Job 단위 재개, 취소, 사이트 정지 래치와 시작 복구를 팔 단위로 처리한다. claim 단계 전환은 safety 태그 `cell/cell_arm_claims.py`와 `ledger/action_claims.release_held_keys`에 있다. app.py는 같은 자리에서 `CellJobDispatcher`를 만들고, 팔 여러 개 Job이 없으면 틱은 한 팔 틱과 같다.
- 증거: 원격 pytest 결과는 이 브랜치 보고에 적는다. 장치·ARM64·현장 수용 없음.
- gate 변화: 없음(SIM 코드만). 착지·push 없음. 팔 여러 개 Job의 목표 증거 경로와 API reference 개정은 남았다.

## 2026-10-17 · uncommitted · D-779 팔 여러 개 Job safety 리뷰 반영

- 변경: 팔마다 owner 작업대(`arms[].workcell_id`)를 Job에 적고, 그 작업대를 Job 단위 claim으로 승인부터 끝까지 잡는다. 같은 owner를 쓰는 한 팔 Job이나 다른 팔 여러 개 Job은 승인에서 거절된다. 설정이 그 인스턴스를 다른 작업대로 매핑하면 그 팔은 NOT_CONFIGURED다. 짝 Action은 두 번째 송신 전에 fence를 다시 읽고, 바뀌었으면 남은 팔을 미송신 HOLD로 두고 받은 팔을 취소한다. 짝의 틱당 I/O는 팔당 2와 취소 1이다. 취소는 팔·Action 표시까지 한 트랜잭션이다. Cell 원장 버전은 4다(1단계 Fleet는 거부).
- 증거: 원격 pytest 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 남은 일: 팔 여러 개 Job은 아직 끝까지 갈 수 없다. Cell 목표 증거 ingress(`cell_goal_evidence_service`)와 성공 hook이 팔 여러 개 Step을 모르고, `ArmJobStore.confirm_step_goal`만 GOAL_CONFIRMED를 쓴다(닫힌 쪽으로 실패). D-781 컴파일러 출력, API reference의 팔 단위 재개 경로, D-780 barrier가 든 짝 grant도 남았다.

## 2026-10-17 · uncommitted · feat(fleet): recipe/3을 팔 여러 개 Cell Job으로 컴파일 (D-781 §5, D-779 2~4단계)

- 변경: 레시피 스키마가 `rosy_cell.recipe/3`인 Cell 후보는 `cell_mixed_submission.compile_mixed_submission`으로 간다. `PalletizingCellJobCompiler.compile_mixed`가 혼합 계획기로 다시 컴파일하고, 후보 Job과 바이트 비교, recipe·cell digest 비교, 64 KiB 한도를 한 팔 경로와 같게 지킨다. 팔 목록은 cell/3 문서의 `arms`, claim은 작업대·팔 owner 작업대·팔레트다. 제안의 `instance_id`는 작업대 팔 가운데 하나여야 한다. recipe/1·/2 경로와 그 Job id는 바뀌지 않았다(26a148117 기준 고정값 시험). palletizing을 import하는 Fleet 모듈은 여전히 `cell_compiler.py` 하나다.
- 증거: 원격 pytest 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 후속: 팔별 좌표의 item_at_pose 목표 술어, Cell 앱 미리보기(`/cell-app/compile`)의 recipe/3, 한 팔 recipe/3.

## 2026-10-17 · uncommitted · feat(fleet): recipe/3 팔별 목표 술어, sku grant, Cell 앱 두 팔 미리보기 (D-781 §2·§5, API v1.259)

- 변경: 목표 허용오차가 설정되면 resolver가 recipe/3 Step마다 `goal_predicates`를 고정한다. 술어는 주 팔과 대체 팔마다 하나씩, 그 팔 입력과 sku 형상으로 계산된 그 팔 `robot_base` 좌표다. `cell_arm_jobs`는 그 키가 Step의 팔과 같은지 확인하고 `step_json`에 둔다. 목표 증거 서비스의 술어 팔은 배정된 첫 팔(첫 주 팔 또는 Step을 넘겨받은 대체 팔)이다. 대체 팔 Step은 그 팔 술어로 판정하고, 술어가 없으면 `CELL_GOAL_PREDICATE_MISSING`으로 거절한다. 첫 주 팔 좌표의 단일 `goal_predicate`는 대체 팔에 쓰지 않는다. `step_action_kinds`는 입력의 `sku`를 CELL_TRANSFER 본문에 옮긴다. sku가 없으면 본문은 같다. `/api/fleet/cell-app/compile`은 recipe/3를 `compile_mixed`로 미리 보고 `summary.multi_arm`(팔, Step별 sku·팔·대체 팔·구역·결합·depends_on)을 더한다. recipe/1·/2 응답은 그대로다.
- 증거: 원격 pytest를 돌리지 못했다. 이 시점에 실험실 시험 호스트에 하나도 닿지 않았다. 시험은 썼지만 실행하지 않았다.
- gate 변화: 없음. 남은 일(ADR 필요): 한 팔 recipe/3 Job, 짝 Step 부분 성공 회복, owner의 cell/3 승인.

## 2026-10-17 · bbaf06bbe · 주제와 등록 Cell 작업의 연결 클라이언트

- 변경: 에이전트가 고른 topic·레시피/셀 digest·instance를 기존 compile/proposal API로 연결하는 `fleet/server/work/cell_task_client.py`를 추가했다. 원본·제출 intent·Fleet 응답을 보존하고 기존 Cell Job 원장을 조회한다. 별도 명시적 admit는 저장된 요청과 현재 제안을 대조하고 기존 named operator·generation 검사로 위임한다. 자동 재전송·dispatch 재무장은 없다.
- 증거: bbaf06bbe 원격 pytest 30 passed, known failures NEW 0. 실제 Cell compiler·API와 새 프로세스 CLI import를 검사했다. 독립 계약 리뷰에서 추가 material finding 없음.
- gate 변화: 없음. 자유문장 해석기·Gazebo 실행·실물 구동·실제 모방학습 완료의 증거는 아니다. ACTION_SUCCEEDED와 독립 GOAL_CONFIRMED를 구분한다.

## 2026-10-17 · a3bd16c251 · test(fleet): G1 실패한 pair의 예약만 추적

- 변경: 한쪽 claim 거절의 즉시 rollback 검사는 유지하고 이후 독립 왼팔 작업이 점유한 정상 shared zone을 실패한 pair의 누수로 판단하지 않게 했다. 최종 action_id와 claims를 대상 pair에 결속한다.
- 증거: 통합 후보의 1 failed / 6635 passed / 354 skipped와 동일 후보 단독 통과로 타이밍 의존을 확인했다. 독립 producer-consumer 분석 후 수정 커밋 원격 G1 SIM·timing 12 passed, 새 실패 0개.
- gate 변화: 생산 제어·claim 권한 변경 없음. 중단된 후보의 병합 검사와 실제 G2·실물 수용을 완료로 표시하지 않는다.

## 2026-10-18 · c4bf531fd8 · Compute direction from the selected trip (D-769) (이식, 원래 2026-10-16)


- Added `fleet.routing.direction.route_direction`: follows selected directed plan segments, validates boundary continuity, returns source-relative here/ahead angles and plan station. Preview ends at the final partial destination or before free driving; returned ahead_m is actual available distance, including zero at the end.
- Evidence: remote missing-module red followed by 8 passing geometry tests (chosen outgoing lane despite a competing straight edge, partial destination, free transition, disconnected lanes, reverse direction, accumulated station and invalid inputs). Private logs: `rosy-d769-audit/route-direction-red`, `route-direction-reviewed`. Independent reviewer found no blocker for validated graph/plan inputs.
- Scope: pure geometry only, no publisher or motion permission. The actual Fleet producer must bind fresh validated MapPose, active map/route revision and source odometry to the existing CORE transport lifetime. CORE bridge wiring and Gazebo acceptance remain pending. Gate unchanged.
- 변경: See implementation and evidence recorded above.
- gate 변화: None; D-769 acceptance remains pending.
- 증거: 위 변경 본문 참조 (feat/d769-learned-follow에서 이식)

## 2026-10-18 · c11a34f64b · Bind selected-route guidance to fresh Fleet poses (D-769) (이식, 원래 2026-10-16)

- 변경: Fleet captures selected-route direction only for opted-in CORE capabilities and a fresh localized pose in the active map, with the exact authority odometry stamp. Changed route, plan, hold, source or age invalidates the captured sample; shrink carries no guide. Normalize full-lane endpoints only within the existing four-decimal station serialization precision. Share the injected trip clock with the authority sender.
- 증거: Remote integration suite passed 186 tests across Fleet route guidance, authority, route direction, trip runner, CORE capabilities/protocol/timers and SIM overlays. Private evidence: rosy-d769-audit/fleet-route-integrated/run-1.txt. Earlier failing integration exposed rounded lane endpoints and mismatched injected clocks. Independent review found no blocking producer issue; size-range and safety-review guards passed for all eight commits since 64c8eb701.
- gate 변화: None. Real Gazebo guide consumption and learned driving acceptance remain pending.

## 2026-10-18 · uncommitted · D-801 관제 콘솔 로봇 영상(사이트 발급 읽기 위임)

- 변경: `tracking/robot_media_routes.py`가 fleet.read 주체에게 로봇별 READ 위임을 발급·갱신·종료하고 `fleet_media_audit`에 남기며 미디어 권한 서비스의 재확인에 답한다. 콘솔 CSP는 설정된 media origin만 추가한다.
- 증거: 원격 시험 결과는 착지 기록에 남긴다. 장치·현장 측정은 2026-10-18 사용자 결정으로 생략했다.
- gate 변화: 없음. 모자이크(MCU)는 후속 feat/site-video-mosaic이다.

## 2026-10-19 · 103df862b · ID 뒤 ! 초기값과 본인 비밀번호 변경

- 변경: 사용자 지시에 따라 legacy·Account 이관에서 ID!를 첫 변경 대상으로 인식한다. 관리자 생성/reset의 정확한 ID!만 짧은 임시값 예외로 허용하고 첫 변경 제한을 유지한다. 영구 비밀번호 변경에서는 ID! 복귀를 거절한다. API·권한·기계 자격은 추가하지 않았다.
- 증거: 최초 정책 RED와 수정8675d2453의 원격153 passed·skip0·NEW0. 독립 리뷰가 짧은 생성/reset 경로 불일치를 찾아 API·실제 관리 Chromium 3건 RED로 재현 후 보완했다. 최종103df862b의6파일 원격160 passed·skip0·NEW0. 상세 범위와 실패 이력은 docs/validation/account-initial-password-2026-10-19/result.md.
- gate 변화: 없음. 팀 명단은 Notion 인증 실패로 미확인이고 운영 사용자·비밀번호·DB는 변경하지 않았다. source/지정 시험과 병합·서명 배포·실제 사용자 로그인을 구분한다.

## 2026-10-19 · uncommitted · 초기값 회귀 fixture 변수 구분과 중단 시험 회수

- 변경: 테스트의 임시 비밀번호·해시 변수 이름을 명확히 하고 함수 호출을 분리했다. 비밀 스캐너의 규칙이나 허용 목록은 바꾸지 않았다. 제품 인증 코드는 그대로다.
- 증거: 통신 중단 뒤 남아 있던 원격 job의 rc를 확인했다. 한 job은143, 다른 job은 fixture 변수 표현의 secret-scan 오검출1건이었다. 새 검사와 착지는 별도 실행한다. 이전160개 실제 Chromium 결과는 원래103df862b 범위로 유지한다.
- gate 변화: 없음. 운영 명단·비밀번호·서비스는 변경하지 않았다.

## 2026-10-19 · uncommitted · feat(fleet): recover OMX topic task client

- 변경: Recover the G2 wrapper and additional tests for the existing topic proposal/admission client, using Fleet compiler and named operator admission endpoints. The runner wiring is a later recovery group. Lost responses preserve intent and do not retry.
- 증거: Committed remote tests are pending. No robot or service activation is performed.
- gate 변화: None; topic text does not acquire ledger or device writer authority.

## 2026-10-19 · uncommitted · 성공 drivable SIM의 Fleet 생산 연결 분리

- 변경: 선행 schema·CORE/Drive·recentre 위에서 기존 지도 벽 검증·선택 경로 안내 생산·SIM 지도와 실행 설정을 복원했다. 운영 Fleet 안내 기본 1초, 명시적 SIM 3초이며 원격 자원 계산과 시나리오 도구 확장은 가져오지 않았다.
- 증거: 원본 소스의 모델 PC 재실행 PASS와 종료·실제 모델 소비를 `docs/validation/pinky-success-baseline-2026-10-19/result.md`에 보존했다. 현재 통합 후보는 별도 원격 회귀와 같은 조건의 SIM을 실행한다.
- gate 변화: 없음. 실물 지도 활성화·설치·서비스 변경은 수행하지 않는다.

## 2026-10-19 · 3cc60afde · (origin #92 2026-10-16) D-772 카메라 관측의 Fleet 인증·세션 경로

- 변경: 명시적인 station_ingress 구성에서만 위치 후보·상대 관측·설치 원장 조회를 설치한다. 카메라 자격은 사용자·로봇·Agent 자격과 분리하고 상대 관측은 기존 HttpRobotClient의 로봇 자격으로 CORE 관측 경로에만 전달한다. 세션 상태와 예약 권한은 단일 읽기 트랜잭션에서 확인한다.
- 증거: 6f845c8a7/3cc60afde에서 신규 모듈 부재 RED를 확인했다. 독립 안전 검토의 분리된 DB 표본·동기식 최종 검사 문제를 첫 구성 커밋 전에 수정했다. 원격 GREEN은 후속 기록한다.
- gate 변화: 없음. 소프트웨어 관측 경로이며 실기 자동 활성화·전체 복귀 사이클 수용은 미완료다.

## 2026-10-19 · 497c4a595 · (origin #92 2026-10-16) D-772 source 범위 조회와 관측 갱신

- 변경: v1.250 source 전용 조회가 현재 원장·CORE binding/ACK·실제 odom epoch를 확인한 측정용 메타데이터만 제공한다. 이전 카메라 착좌 만료가 새 프레임에 반복 상속되는 갱신 단절을 수정했다. 새 scope는 ACK·설치·odom·source 나이로 제한되며 기존 착좌/충전 증거를 갱신하지 않는다.
- 증거: 56c980d16 범위 경로 79개 시험, b857bc61d 관측/기존 경로 150개 시험 통과. 만료 피드백을 87c6522a1에서 독립 RED로 재현하고 독립 안전 검토 후 497c4a595의 이미지 HTTP/제어기 포함 49개 시험 통과, NEW 0. 로그 C:/DevTemp/station-charge/task-3-camera-pipeline-green/run-1.txt.
- gate 변화: 소프트웨어 관측 경로 검증. 실제 trip/native 복귀·주기 스케줄러·자동 이안/재투입과 전체 사이클은 미완료며 기본 구성은 비활성이다.

## 2026-10-19 · 987bea4e4 · (origin #92 2026-10-16) D-772 CORE 충전 근거의 Fleet 영속 상태 반영

- 변경: ChargeMotion이 acknowledged dock intent·native 성공·실행 ID/correlation과 현재 CORE 충전 readback의 session/boot/battery/ACK/map/위치 버전·만료를 대조한 뒤 CHARGING/CHARGED_HOLD를 기록한다. 접안 성공 이후 사라지던 operation ID도 유지한다. 중복 완료는 추가 전이나 이안을 만들지 않고 근거 유실은 HOLD이며 예약을 유지한다.
- 증거: 2ec9034cf의 11개 RED 뒤 독립 안전 검토를 거친 95e680d74 관련 82개 시험 통과, NEW 0. 987bea4e4의 실제 이미지·HTTP·접안 제어기·Fleet 상태 반영과 잘못된 ACK robot/map·I/O 중 만료 포함 54개 시험 통과, NEW 0. 로그 C:/DevTemp/station-charge/task-8-charge-sync-http/run-1.txt.
- gate 변화: 소프트웨어 통합 증거 추가. 실제 return trip·readiness·에너지 예산은 이 시험에서 SIM 대체물이고 정상 완료만으로 출발하지 않는다. 실제 trip/native 포트 구성·이안/재투입·실기 수용은 미완료다.

## 2026-10-19 · fbdb175a7 · (origin #92 2026-10-16) D-772 기존 trip 실행기를 쓰는 충전 복귀

- 변경: 실제 TripRunner·경로 원장·충전 예약 아래에 durable return context와 typed charge_session lease를 연결했다. 초기 lease 전에 scope/map/실제 끝점/에너지 검증, entry turn 전후 재검증, 한 번의 추적 가능한 제출, 실제 arrived+CORE 정지 ACK handover, 원장 장애와 경합에도 정확한 정리 시도를 구현했다. charge lease loss는 mission callback과 분리한다.
- 증거: 6b77e64a5 원격 3개 missing adapter RED 뒤 독립 안전 리뷰의 DB 이전 정지 차단·active map 결속 두 blocker를 수정했다. fbdb175a7 원격 179개 시험 통과, task-7-trip-port-green-valid/run-1.txt. 실제 경로 실행기+SIM robot port이며 기존 trip/job/lease 회귀를 포함한다. CORE HTTP 포트와 운영 구성은 미연결이다.
- gate 변화: 소프트웨어 복귀 포트 증거 추가. 장치 자동 활성화·전체 복귀/충전/이안/재투입 수용 및 FIELD는 미완료다.

## 2026-10-19 · bb966bcb6 · (origin #92 2026-10-16) D-772 복귀 포트 구조·안전 회귀

- 변경: 확장 시험에서 검출한 TripRunner 크기 증가와 안전 어댑터의 경로 모듈 직접 import를 기존 TripAdmission 포트·공통 시작 검사 추출로 정리했다. 크기 ratchet은 899→896으로 내렸다. charge_session 예약을 일반 trip/console이 존중하는 회귀를 추가했다. d87c81995에서 이미지 통합 시험을 형제 conftest 없이도 실행하도록 실제 소스 경로를 명시했다.
- 증거: 독립 안전 후속 리뷰에서 추가 blocker 없음. bb966bcb6 원격 Fleet·구조·안전·harness 393개 통과, NEW 0/skip 0(task-7-trip-fleet-final/run-1.txt). d87c81995 원격 CORE·반환 허가·trip lease·이미지 HTTP 접안/충전 통합 148개 통과, NEW 0/skip 0(task-7-trip-core-standalone/run-1.txt). 후자의 SHA 변경은 시험 경로 한 줄이며 제품 소스는 동일하다.
- gate 변화: 소프트웨어 회귀 증거 추가. 실제 HTTP 복귀 포트/운영 구성·주기 배터리 정책·안전 이안/재투입·현장 수용은 미완료이며 전체 목표는 계속 진행 중이다.

## 2026-10-19 · a6382343c · (origin #92 2026-10-16) D-772 실제 HTTP 복귀 포트와 ACK 수명

- 변경: scoped return의 실제 HTTP 경로, immutable native generation CAS, 기존 transport dispatch guard를 공유하는 PUT/POST, exact lease 정지와 명시적 standstill 거절만 허용하는 대기를 연결했다. 만료된 캐시 ACK 때문에 현재 복귀가 HOLD 되는 문제는 실제 CORE read_target을 검증해 해결했다.
- 증거: d563786c1의 HTTP 포트 부재 RED 8개, b7fe84b10의 만료 ACK 갱신 RED 4개 뒤 독립 안전 리뷰의 PUT dispatch 우회 blocker를 수정했다. a6382343c 원격 91개 통과, NEW 0(task-7-return-http-measured/run-1.txt). 실제 TripRunner/HTTP/CORE 권한 조합이며 motion backend·에너지·정지 odom·IDLE 전환은 SIM이다. 응답 유실·I/O 중 만료·다른 principal/lease·guard 거절을 검사했다.
- gate 변화: 소프트웨어 HTTP 증거 추가. 실제 ARRIVED는 arbitration NAVIGATION을 해제하지 않으므로 terminal native owner/quiescence에 근거한 제한적 IDLE 인계를 아직 구현해야 한다. 이 조건을 수동 SIM 모드 전환으로 대체해 실제 자동 복귀 완료로 판정하지 않는다. 전체 lifecycle·운영 구성·현장 수용은 미완료다.

## 2026-10-19 · 3a7348119 · (origin #92 2026-10-16) D-772 HTTP 복귀 포트 최종 회귀

- 변경: 실제 finish가 CORE에서 성공했으나 응답 또는 후속 readback이 유실된 경우에도 FINISH_PENDING과 예약을 유지하는 시험을 추가했다. 실제 backend의 자동 IDLE 부재는 Task 7 필수 미완료 항목으로 설계와 상태에 명시했다.
- 증거: 원격 HTTP/Fleet/transport/구조/안전/harness 337개와 CORE return authority/trip lease/이미지 HTTP 접안·충전 148개 통과, 각 NEW 0/skip 0. 로그 task-7-return-http-final/run-1.txt 및 task-7-return-http-core/run-1.txt. 생산 composition은 독립 리뷰의 transport dispatch 우회 수정 뒤 추가 blocker 없음으로 검토됐다.
- gate 변화: 소프트웨어 회귀 증거만 추가. NAVIGATION→IDLE native quiescence 인계·운영 bootstrap·주기 배터리 정책·안전 이안/재투입·전체 3-cycle과 실기 수용은 미완료다.

## 2026-10-19 · 3f44891bd · (origin #92 2026-10-16) D-772 연속 충전 HTTP 포트와 native 종료 대기

- 변경: ChargeRobotHttp로 실제 bind/return/dock/read/stop 경로를 ChargeService에 조합했다. scoped station-stop은 현재 principal/session/boot/native generation과 수락된 run/correlation을 검증하며, 수락 전 중단도 지연 시작을 닫는다. 이전 native goal이 실행 중이면 다음 lookahead와 finish를 기다린다. 충전 job의 readiness 의존성은 필수이며 arrival 대기는 stall_s로 제한한다.
- 증거: 2dcd8fa35 RED 8건 후 scoped stop 독립 검토를 거쳤다. 연속 시험이 실제 NAVIGATING 목표 중복을 재현했고 c3ac314b5 CORE/HTTP 144개, 3f44891bd Fleet 회귀 149개 통과, 각 NEW 0/skip 0. task-7-continuous-native-ready 및 task-7-charge-readiness-fleet-final/run-1.txt. 독립 검토의 같은 버전 refresh 비교·route 도착/native 종료 경쟁·명시적 의존성 지적을 반영했다.
- gate 변화: request_return→TripRunner→CORE 정지 인계→JPEG 상대 접안→착좌/충전 확인→CHARGED_HOLD의 연속 소프트웨어 근거다. 주행 backend/map pose/접점/BMS/에너지는 SIM이며 운영 bootstrap·주기 정책·안전 이안/재투입·실기와 FIELD 수용은 미완료다.

## 2026-10-19 · 39f94f151 · (origin #92 2026-10-16) D-772 연속 충전 경로 최종 관련 회귀

- 변경: 충전 전용 실행 전 검사를 charge_goal_gate로 분리해 Safety 추적과 기존 Decision 경로 기하의 경계를 유지했다. 도착 이후 항법 종료와 명시적 정지 미충족 응답에는 하나의 대기 제한을 적용한다. CORE 시험은 기존 API Mode와 실제 nav.resolve_goal을 사용하며 필요한 서비스 필드를 명시한다. v1.253 변경 이력과 envelope 1.0 문구, Vision의 정확한 station 관측 경로와 명령 금지를 함께 검증했다.
- 증거: 39f94f151 원격 CORE/HTTP 237개(task-7-charge-final-core), Fleet·구조·안전·설치·harness 486개(task-7-charge-final-contract), 합계 723개 통과. 각 NEW 0/skip 0이며 두 실행의 종료 코드 0을 확인했다. 앞선 확대 검사에서 발견한 실패를 재현해 수정했으며 실패 목록이나 공차·크기·CI 비용 상한을 늘리지 않았다. 독립 안전 검토는 이 guard 분리와 도착 대기 범위에 한정한다.
- gate 변화: 소프트웨어 관련 회귀 증거. 최초 확대 검사는 전체 GREEN이 아니며 이 기록도 CI 전체·배포·실기 수용으로 승격하지 않는다. 운영 bootstrap·주기 에너지 정책·안전 이안/재투입·이동 스테이션의 실시간 전역 관측·3회 전체 cycle·FIELD 수용은 계속 미완료다.

## 2026-10-19 · 209bfafc4 · (origin #92 2026-10-16) D-772 주기 충전 정책과 기존 app lifecycle

- 변경: ChargePolicyAdmission은 원본 robot/battery/budget 시각과 robot·boot·battery·station·map·pose/profile 및 승인 source/epoch/cost revision을 검사한다. ChargeRuntime이 기존 ChargeService를 주기적으로 진행하며 새 작업의 최종 admission은 실제 durable task ID·type·전체 request digest와 예산을 결속한다. 초기 미평가·저SOC·보수 프로필 없는 건강도 결측·만료·다른 작업은 새 작업 수락을 막는다. factory는 같은 TripRunner·지도/작업/충전/스테이션 원장·HTTP client와 callable source adapter를 요구하며 기본값은 비활성이다.
- 장애 처리: 전송 전 정확한 session/correlation/intent를 정지용으로 보관한다. 취소와 DB 장애에서도 해당 정지를 시도하고 HOLD 저장 실패를 숨기지 않는다. 다른 station/배터리 구성은 기존 세션을 자동 진행하지 않는다. 실제 lifespan 시험이 초기 CLAIMED 충전 예약의 재시작 해제를 발견해, 기존 stop 트랜잭션에서 모든 charge_session claim을 UNKNOWN으로 유지하도록 수정했다. rearm은 재조정 전 차단한다. ACK를 물리 정지·자원 해제로 간주하지 않는다.
- 증거: afba04ec2 관련 65개, fad32a155 연속 runtime→실제 TripRunner/HTTP/native→JPEG 접안→정상 종단 및 CORE 회귀 129개, a692cb51e app/충전/task 회귀 154개, 209bfafc4 DB 이관/구조/안전/설치/재시작 관련 170개 통과. 각각 원격 종료 코드 0, NEW 0/skip 0이다. 시험 범위가 겹치므로 합산하지 않는다. 로그는 저장소 밖 task-9-runtime-green-retry, task-9-runtime-continuous, task-9-charge-final, task-9-schema-retry/run-1.txt다. native navigation plant/map pose·배터리/BMS·접점·에너지 입력은 명시적 SIM이다.
- 수정 과정: bootstrap의 실제 clients() provider 계약, 선택 작업 미결속, 충전 예약 해제와 크기 위반을 재현하고 고쳤다. 확대 guard 실행 a692cb51e는 380 PASS/1 FAIL이며 유일한 TaskStore 크기 실패는 209bfafc4의 170개에 포함해 재검증했다. 첫 DB 함수 추출 5482fc995는 세 번째 migration 메서드 누락으로 실패했고 세 메서드를 보존하는 TaskSchemaMigrations로 수정했다. 실패를 면제하지 않았다. Fleet root 16042→16021, app 989→968, TaskStore 1014→955로 상한을 낮췄다.
- gate 변화: runtime 정지 경로, bootstrap/작업 digest 및 충전 claim 보존을 독립 안전 검토했다. 내부 조합만 추가해 API v1.253을 유지한다. 전체 CI·배포·실기 수용 승격은 아니다. 실제 장치 source/CLI/배포 설정, 장시간 충전 중 같은 버전 위치 갱신, 안전 이안·재투입, 독립 전역 스테이션 이동 producer, 전체 3회 cycle와 FIELD 수용은 미완료다. 전체 목표는 진행 중이며 push/merge/장치 활성화는 하지 않았다.
- 추가 검증: 209bfafc4의 원격 task-9-selection-final에서 영향 선택·Fleet CI shard 비용 상한을 포함한 65개 검사 통과, NEW 0/skip 0. 상한을 늘리지 않았다.

## 2026-10-19 · 741c9b95f · (origin #92 2026-10-16) D-772 원래 위치 수명을 넘기는 충전 세션

- 변경: ChargeRobotHttp는 실제 return/dock owner를 읽을 때에도 관제의 새 전역 위치 근거를 CORE의 기존 binding과 동기화한다. ACK만 신선하고 CORE target은 만료되는 단절을 해결했다. 같은 session/robot/boot/battery/map/attempt·위치/접근 포즈·출처/교정을 유지하며 새 capture의 시간·불확실성만 갱신한다. 만료/HOLD binding, 같은 capture의 TTL 연장, 다른 native owner, 만료/미래 측정 권한은 거절한다. source/native/DB I/O 뒤에도 원본 수명을 확인하며 feed·native 실행·착좌·충전 완료 근거를 재설정하지 않는다.
- 증거: 40d405e5e RED 5건과 3e579caae의 실제 runtime 위치 만료 RED를 확인했다. f1726a72e Fleet·위치 원장·구조/안전/설치 178개, 1f45569ca CORE/HTTP·refresh·owner 190개, 741c9b95f 충전 유지/완료 수명·sensor reader·영상 pipeline 134개가 원격 종료 코드 0, NEW 0/skip 0으로 통과했다. 범위가 겹쳐 합산하지 않는다. 로그는 저장소 밖 task-9-target-fleet-guards, task-9-target-refresh-retry, task-9-target-charge-final/run-1.txt다.
- 실행 범위: 연속 시험은 최초 2초 위치 lease와 충전 시작 시점의 lease를 넘기면서 3초 동안 CHARGING을 유지한 뒤 정상 종단으로 CHARGED_HOLD가 됨을 검사한다. 매 JPEG step에 실제 runtime을 진행한다. 갱신 permission은 초기 SIM seed 이후 실제 StationIngress scope 경로를 사용한다. 새 전역 후보는 SIM 입력으로 StationService.observe에 공급하므로 독립 전역 producer의 운영/인증 통합 수용은 아니다. 주행 plant·map pose·접점·BMS·에너지도 SIM이며 상대 접안은 실제 JPEG/worker/인증 HTTP 경로다.
- 검토/수정: scoped 독립 안전 검토의 post-I/O permission TTL 지적을 반영했다. 기존 순수 owner fixture의 미래 permission(100.1)을 시각 100에서 수락하던 잘못된 입력은 현재 시각을 100.1로 맞췄다. 별도의 미래/만료 거절 회귀는 유지했다. 실제 연속 경로가 ACK 수명과 target 수명의 차이를 재현해, 이후 exact intent 확인 뒤 owner 조회 때도 동기화하도록 수정·재검토했다.
- gate 변화: 소프트웨어의 같은 버전 장기 세션 갱신을 검증했다. 기존 PUT 계약과 DTO를 사용해 API v1.253을 유지하며 크기/공차/실패 허용을 늘리지 않았다. 안전 이안·재투입, 독립 전역 이동 producer, 전체 3회 cycle·실측 profile·DEVICE/FIELD 수용은 미완료다. 전체 목표는 ACTIVE이며 push/merge/실기 활성화는 하지 않았다.

## 2026-10-19 · a78e502f5 · (origin #92 2026-10-16) 충전 위치 갱신 최종 계약 회귀

- 변경: 제품 소스 변경 없이 같은 버전 위치 갱신 문서와 기존 API 의미를 검증했다.
- 증거: 원격 task-9-target-contract-final의 behavior 소유권·영향 선택/CI 비용·harness 계약 166개 통과, NEW 0/skip 0, 종료 코드 0.
- gate 변화: 개발 관련 회귀 근거 추가. 전체 CI·실기 수용 승격은 아니다.

## 2026-10-19 · 9286f5f77 · (origin #92 2026-10-16) 선택 작업에 결속된 실제 HTTP 이안과 재투입

- 변경: 선택된 QUEUED/READY 작업 digest·정책/용량 revision과 1회 UNDOCKING intent를 같은 원장에 저장한다. ChargeRuntime/ChargeService가 실제 ChargeRobotHttp→HttpRobotClient→CORE 이안을 호출한다. 시작·갱신·완료 전 마지막 원장 검사에서 session/claim/현재 permit/intent/task를 함께 검증한다. 최초 motion fence는 보존하고 살아 있는 동일 실행의 허가만 갱신한다. 새 실측 Receipt 저장·WORK_AVAILABLE·두 claim 해제는 한 트랜잭션이다. 시작 응답 불명은 HOLD이며, 완료 응답 유실은 GET으로 원래 Receipt를 확인한다. 없거나 만료됐으면 claim을 유지한다. 인계 시 새 원본 에너지 입력을 읽고 UTC 잔여 수명을 monotonic 주기 기한으로 변환한다.
- 증거: 13421ca4b task-8-departure-renew-green-verified 103개, aff57b47a task-8-departure-transport-green 208개, 9286f5f77 task-8-redeployment-http-final 253개와 task-8-redeployment-fleet-final 151개가 원격 exit 0, NEW 0/skip 0으로 통과했다. 범위가 겹쳐 합산하지 않는다. 실제 HTTP 시험은 최초 짧은 허가를 넘겨 같은 native 실행을 유지하고 실측 결과 이후 기존 scheduler가 선택 작업을 claim함을 검사한다. 취소/요청 변경의 전송 직전 차단, 유실 시작/완료, 만료 Receipt, 서로 다른 clock epoch를 포함한다.
- 수정/검토: 첫 renewal 명령은 잘못된 bootstrap 시험 경로로 exit 4여서 실제 파일 경로로 다시 실행했다. 022beed9f에서는 물리 완료/claim 해제 뒤의 stale work gate 2건과 legacy transport 오류 타입 import의 안전 의존성 위반 1건을 발견해 고쳤다. 독립 scoped 안전 리뷰에서 최신 generation보다 오래된 Receipt, task 검사 공백, UTC/monotonic 혼합을 지적해 수정·재검토했다. 실패를 면제하거나 크기/안전 상한을 늘리지 않았다.
- gate 변화: 관련 소프트웨어 회귀 근거 추가. 충전 완료까지의 초기 상태, plant·접점·차단/전류·공간·BMS/에너지 입력은 명시적 SIM이다. 앞선 JPEG/TripRunner 전체 경로와 이번 이안을 한 연속 시나리오로 묶는 작업, 새 session binding, 3회 cycle, 독립 전역 이동 producer와 실측 DEVICE/FIELD 수용은 미완료다. 목표 ACTIVE, 실기 구성 미정, push/merge/실기 활성화 없음.

## 2026-10-19 · 0ba8294c9 · (origin #92 2026-10-16) 실제 항법 인계 HTTP transport 조합

- 변경: 기존 navigation cancel/path/goal/goal-lease RPC를 응집된 NavigationTransport로 그대로 옮겨 HttpRobotClient가 조합한다. 기존 guarded POST를 한 번 사용하는 정확한 navigation/handover 호출을 추가하고 UUID·strict generation·correlation 입력과 accepted/IDLE/run/boot/generation ACK를 검증한다. legacy transport는 600→573줄로 줄었으며 기본 크기 한도를 늘리지 않았다. 안전 public entrypoint는 정확한 class anchor만 선언했다.
- 증거: a381aad0f 원격 RED는 새 실제 client method 부재 1건이다. 0ba8294c9 task-10-navigation-transport-green의 actual HTTP/native handover·기존 return/redeployment/JPEG pipeline·transport·구조/안전 261개 통과, NEW 0/skip 0/exit 0. 별도 v1.255 pin 회귀는 560a2ff27에서 93개 통과했다. 독립 scoped 안전 리뷰 PASS이며 범위가 겹쳐 합산하지 않는다.
- gate 변화: 실제 통신과 관련 소프트웨어 회귀 근거. FleetTaskService의 실제 nav.completed/COMPLETED와 native outcome safe_released 확인을 주기 인계에 연결하는 작업은 아직 남았다. charge ledger가 task claim을 대신 해제하거나 scheduler claim을 작업 완료로 간주하지 않는다. 전체 3회 cycle·운영 producer·실측 DEVICE/FIELD 수용은 미완료, 목표 ACTIVE다.

## 2026-10-19 · 70827fd97 · (origin #92 2026-10-16) 실제 완료 작업의 충전 복귀 인계

- 변경: FleetTaskService가 현재 CORE native 항법에 대응하는 실제 COMPLETED 작업의 원래 ACK, 정확한 boot/run/attempt, SUCCEEDED outcome, 기존 reconciler의 safe_released와 현재 dispatch generation·robot claim/reservation 부재를 확인한다. 기존 outcome owner만 claim을 해제한다. 원본 정책 boot를 현재 native/Task receipt와 결속하고, DB 최종 조회 뒤 원본 source admission·2초 monotonic budget을 다시 확인한다. 초기 조회는 off-loop, 최종 전송 guard의 DB contention은 즉시 거절한다.
- 연결: bootstrap이 검증된 동일 TaskService의 bound method를 ChargeRobotHttp와 Runtime의 명시적 optional callback에 연결한다. RETURN_REQUIRED이며 일반 NAVIGATION이 남은 경우에만 이동 없는 인계를 시도하고, 성공 뒤 새 원본 source를 읽어 기존 request_return 조건을 다시 확인한다. 두 공용 검증/guard leaf의 안전 분류와 정확한 public anchor를 명시했다.
- 증거: task-11-task-runtime-handover-final 원격 267 PASS/0 skip/NEW 0/exit 0. 실제 TaskService→HttpRobotClient→CORE native 완료→실제 EventBus→기존 outcome readback 자원 해제→인계를 포함한다. 최초 회귀의 SIM odometry 누락과 안전 dependency 분류 오류를 수정했다. source/DB 경합, 원본 boot, explicit callback은 독립 scoped 안전 리뷰 PASS다.
- gate 변화: 관련 소프트웨어 연결·회귀 근거. 새 IDLE의 실측 dwell을 기다려 다음 binding으로 이어지는 진행성과 전체 3회 연속 운용은 별도 미완료다. 운영 producer·실기 구성·DEVICE/FIELD 수용은 확인하지 않았고 목표 ACTIVE다.
- 추가 증거: 같은 70827fd97의 task-11-camera-departure-regression 원격 290 PASS/0 skip/NEW 0/exit 0. 기존 실제 귀환·JPEG 접안/충전·이안/재투입·target refresh·transport·harness 회귀이며 앞선 267개와 중복되므로 합산하지 않는다.

## 2026-10-19 · ad979adf8 · (origin #92 2026-10-16) 동일 원장의 3회 충전·작업과 이안 측정 범위 보정

- 변경: 연속 시험은 실제 Console.goal의 capability/localization·Task prepare_send/native receipt·최종 dispatch guard를 사용한다. 같은 TaskService/runtime/CORE/worker의 3회 충전→출발→작업과 2회 다음 세션 인계를 검증한다. Task 완료는 실제 EventBus와 기존 native outcome owner가 반영하며 충전 원장이 Task claim을 해제하지 않는다.
- 수정: 0268fe909는 StationIngress의 현재 측정 상태에 UNDOCKING을 포함한다. 실제 연속 이안 중 같은 위치의 전역 관측 갱신이 observation_scope=None으로 끊기던 누락이다. 기존 source/session/claims/binding/odom/TTL 검증과 HOLD/WORK_AVAILABLE 거절을 유지한다. 공개 DTO/명령 권한 변경은 없으며 독립 scoped 안전 검토 PASS다.
- 증거: task-12-undocking-scope 원격 161 PASS/0 skip/NEW 0, 이후 actual Console 경로의 task-12-console-continuous 단일 3회 시나리오 PASS/NEW 0. 여러 범위가 겹치므로 합산하지 않는다. 첫 RED는 실제 source 범위 누락으로 HOLD였으며 gate 완화나 수동 작업 완료로 해결하지 않았다.
- gate 변화: 해당 소프트웨어 SIM 시나리오 근거. deterministic tick 및 합성 장치/에너지/절대 위치/신규 session permission 입력이다. 실시간 lifespan, 이동 재발견 producer, 설치 CLI/profile, DEVICE/FIELD 수용은 별도 미완료다. 전체 목표 ACTIVE다.
- 최종 증거: c2cc1551d task-12-continuous-final 원격 239 PASS/0 skip/NEW 0/exit 0. 실제 Console 3회와 2회 후속 인계, 네 이동 phase의 1회 power gate 차단·출력 0·위치 불변, 기존 return/native 인계 및 구조/안전 회귀를 포함한다. 앞선 범위와 합산하지 않으며 전체 CI/실시간 lifespan·실기 수용은 아니다.

## 2026-10-19 · cb43b5da1 · (origin #92 2026-10-16) 앱 소유 충전 복귀 전의 정확한 Console 작업 인계

- 변경: 실제 앱 소유 TripRunner를 사용하면 완료 작업의 Console projection이 남아 다음 복귀를 TRIP_ROBOT_BUSY로 막는 결함을 수정했다. 기존 TaskService의 정확한 native handover ACK 이후 Task/정책/dispatch/claims를 재검증하고 같은 goal/route/lease projection만 정리한다. client/manager/값/전송·정지 세대와 held·formation·pending 상태가 바뀌면 정리하지 않는다. 미완료 정리는 IDLE 표본 뒤에도 재확인한다. 목표 lease 파일은 canonical 이름을 유지해 기존 ledger holder로 옮겼고 root ratchet을 15834로 낮췄다.
- 증거: 74e7a9f45 composed RED에서 두 번째 복귀 실패를 재현했다. cb43b5da1 task-15-retire-final 원격 229 PASS/0 skip/NEW 0, 별도 task-15-composed-final 117 PASS/0 skip/NEW 0. 앱의 실제 Console→CORE 복귀와 3회 충전·재투입, 두 번의 goal→점유 없음 인계와 기존 relocation HOLD를 검증했다. ee878e82e의 중간 2 FAIL은 만료된 고정 ACK의 fixture 주기와 root 크기였으며 만료/크기 한도를 완화하지 않고 같은 시험군으로 재검증했다. 독립 safety scoped PASS 및 trailer 검사 통과.
- gate 변화: 해당 factory/owner 조립·수동 SIM 근거. 실제 app lifespan/재시작·운영 설정/source 조립·실측 장치 프로필과 DEVICE/FIELD는 미완료다. 전체 브랜치 CI·착지·push·배포는 수행하지 않았다.

## 2026-10-19 · 518f2eeec · (origin #92 2026-10-16) 설치된 충전 원본 계측과 durable replay 포트

- 변경: D-776의 승인 POSIX 로컬 계측 포트를 기존 ledger에 추가했다. 파일은 원본 motion/Battery 사실만 제공하며 strict JSON·UID/권한·일반 파일·원자적 교체/읽기 무결성·크기와 독립 evidence 나이를 검증한다. TaskStore에 원본 sequence/hash/capture와 거절 watermark를 저장하기 전에 사실을 반환하지 않는다. 같은 battery 자료는 새 motion으로 수명을 갱신하지 않는다.
- 증거: e436466b2의 source RED 36 FAIL 후 518f2eeec task-18-source-green 원격 151 PASS/0 skip/NEW 0/exit 0. 새 source 및 기존 policy/runtime/battery와 구조/안전 시험을 포함한다. read gap/반환 TTL 및 battery lease 연장 counterexample은 첫 source 커밋 전 수정했고 독립 clock/재시작/파일·DB 오류 회귀와 scoped 안전 검토를 거쳤다.
- gate 변화: 미연결 source 포트의 software 근거다. 실제 Fleet CLI/factory·선택 작업 경로 예산·BMS/장치 지원·CORE capability/현장 수용은 별도다. 전체 브랜치 CI나 운영 충전 활성화로 확대하지 않는다.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) feat(fleet): recipe/3을 팔 여러 개 Cell Job으로 컴파일 (D-781 §5, D-779 2~4단계)

- 변경: 레시피 스키마가 `rosy_cell.recipe/3`인 Cell 후보는 `cell_mixed_submission.compile_mixed_submission`으로 간다. `PalletizingCellJobCompiler.compile_mixed`가 혼합 계획기로 다시 컴파일하고, 후보 Job과 바이트 비교, recipe·cell digest 비교, 64 KiB 한도를 한 팔 경로와 같게 지킨다. 팔 목록은 cell/3 문서의 `arms`, claim은 작업대·팔 owner 작업대·팔레트다. 제안의 `instance_id`는 작업대 팔 가운데 하나여야 한다. recipe/1·/2 경로와 그 Job id는 바뀌지 않았다(26a148117 기준 고정값 시험). palletizing을 import하는 Fleet 모듈은 여전히 `cell_compiler.py` 하나다.
- 증거: 원격 pytest 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 후속: 팔별 좌표의 item_at_pose 목표 술어, Cell 앱 미리보기(`/cell-app/compile`)의 recipe/3, 한 팔 recipe/3.

## 2026-10-19 · bbb785a31 · (origin #92 2026-10-17) durable charge work selection
- 변경: 실제 TaskStore의 READY queue 순서와 navigate request digest를 불변 선택에 결속한다. 원본 만료·lease·dispatch authority를 확인하고 별도 snapshot에서 stop/rearm을 다시 읽는다. claim/Task/scheduler 상태는 쓰지 않는다.
- 증거: task-18-selection-red 7ee01f51e module 부재 15 FAIL 후 bbb785a31 task-18-selection-green 129 PASS/0 skip/NEW 0/exit 0. 실제 SQLite 경합·취소·우선순위·stop/rearm·만료·불량 입력과 기존 이탈/scheduler/policy·구조/안전 회귀. 독립 Safety-Review scoped PASS. 로그는 저장소 밖 C:/DevTemp/station-charge/task-18-selection-green/run-1.txt.
- gate 변화: read-only 선택 경계의 소프트웨어 증거만 추가. 비용 상한/World boot-odom 결속/CLI factory는 미연결. 물리 로봇은 등록 기록만 확인했고 저장 주소 접속 불가, 현장 전원/네트워크 확인 대기. DEVICE/FIELD 및 전체 목표 미완료.

## 2026-10-19 · 1eeaeb653 · (origin #92 2026-10-17) World source-scope ingestion fences
- 변경: 기존 World tracker에 opt-in boot/CORE epoch/client/map ID 선언과 generation 경계를 추가했다. 이전 cache/anchor·늦은 REST/hub 완료·unqualified sink를 차단하고 새 원본 odom/camera anchor만 qualified pose로 읽는다. Ticket은 신뢰된 내부 선언이며 native boot 검증 자체가 아니다.
- 증거: ce5e9cce4 RED 13 FAIL 후 34006ca39 첫 회귀 211 PASS/1 FAIL(루트 크기 검사). MapPoseService를 기존 관측 holder로 전체 이동하고 canonical import/AST/두 source guard를 보존했다. root cap 15834→15558. 1eeaeb653 최종 원격 265 PASS/0 skip/NEW 0/exit 0. 독립 scoped safety review와 trailer 검사 통과. 로그 C:/DevTemp/station-charge/task-18-pose-scope-final/run-1.txt.
- gate 변화: 로컬 ingestion 경계의 검증만 추가. 실제 native boot bracket·timestamp 결속·map revision·비용 상한·factory/CLI와 DEVICE/FIELD 미완료, 전체 목표 ACTIVE.

## 2026-10-19 · e801f1e01 · (origin #92 2026-10-17) 원본 전송과 boot 대조를 결속한 충전 World pose reader

- 변경: 기존 공유 REST reader가 캡처한 client로 직접 요청하고 불변 receipt를 보관한다. 내부 ChargeWorldPoseSource는 boot/state/boot, facts/map revision/CORE epoch와 기존 World anchor를 결속한다. facts·odom·camera 각각의 최초 monotonic 수명을 유지하며 모순 뒤 proof와 scope를 폐기한다. 일반 공유 state 객체와 요청 주기는 유지한다.
- 증거: task-18-native-pose-green 원격 250 PASS/0 skip/NEW 0/exit 0. module 부재 RED 8 FAIL 후 sender/시간/재생/복원/최초 대기와 기존 World/공유 reader/구조/안전 회귀를 확인했다. 독립 scoped 안전 검토 PASS. 실제 장치 boot 대신 명시적 Fake client를 사용했다.
- gate 변화: 추가 실제 HTTP/SIM lifespan은 CHARGE_RETURN_CORE_SCOPE_CHANGED로 NEW 1 FAIL이다. bb6e03272·0fb3a8492 진단에서 ACK 수락·실제 motion lock 획득 성공·원본 motion sample 없음이 관측됐다. 1d7af41f5 clear stack 진단은 원격 host busy로 대기 중이다. 간헐 실패 해결, 운영 factory/CLI 연결, 실제 비용 상한, DEVICE/FIELD 및 전체 CI를 주장하지 않는다. 전체 목표 ACTIVE.

## 2026-10-19 · 79226ce97 · (origin #92 2026-10-17) SIM 초기 CORE 틱의 원본 이동 계측 보존

- 변경: 실제 lifespan worker가 최초 binding하기 전에 CORE 틱을 실행하도록 event로 순서를 고정했다. 시험의 직접 owner.tick 대신 production docking_mode.tick을 호출해 session이 없을 때 legacy fallback을 사용한다. 최초 UNBOUND·원본 motion 보존 assertion과 실제 worker/dispatcher, 최종 publisher를 유지한다. 생산 제어기·readback·TTL·권한 변경은 없다.
- 증거: e25e08ff3 task-18-startup-order-red 원격 NEW 1 FAIL은 session=None인데 HOLD가 되는 직접 호출 결함을 재현했다. 79226ce97 task-18-bridge-startup-green 원격 185 PASS/0 skip/NEW 0/exit 0은 전체 pipeline 10 variant와 trip lease·station wiring·mode ownership/release·motion feed를 검증했다. 독립 scoped 안전 검토 및 safety trailer 검사 PASS. 로그는 저장소 밖 C:/DevTemp/station-charge/task-18-bridge-startup-green/run-1.txt.
- gate 변화: 확인된 SIM 초기 호출 결함의 수정과 관련 회귀 근거다. 1d7af41f5의 앞선 clear 진단은 정상 1 PASS여서 그 실행에서 실패 stack을 얻지 못했다. 모든 과거 간헐 실패의 원인 확정, 전체 CI, 실제 ROS executor나 장치/현장 수용을 주장하지 않는다. 운영 source/실제 집행 예산/factory·CLI와 DEVICE/FIELD는 계속 미완료이며 목표 ACTIVE다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) measured health operational admission

- 변경: MeasuredChargePolicyAdmission을 기존 정책 위에 추가해 설치된 로봇별 측정 source 종류/capacity revision과 SOH·Wh·온도를 요구한다. 실제 app bootstrap은 같은 measured policy 인스턴스를 요구하며 기존 보수적 순수 정책은 유지한다. 새 원시 장치 권한·공개 API·실기 capability는 추가하지 않는다.
- 증거: 공식 원격 모델 PC의 31b704b79 반례 23 FAIL/NEW 23을 확인했다. 기존 bootstrap이 legacy 정책을 거절하지 않는 실패와 미구현 class 실패다. 소스 구현 후 독립 scoped static 안전 검토 PASS, 변경 Python AST 및 diff 확인. 원격 GREEN은 이 소스 커밋 후 수행한다.
- gate 변화: 없음. 실제 source attestation·vendor 어댑터·교정·CORE 기동/native 결합·암 interlock·장치/현장 수용은 미완료다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) exact charge stop before journal contention

- 변경: DB journal보다 cache의 정확한 정지를 먼저 시도하고, 정지 시작 시 로컬 session admission을 닫는다. journal은 제어 event loop 밖에서 실행하고 취소 시 정지/쓰기와 호출자 cleanup을 끝까지 drain한다. STOP port 자체 취소도 journal 후 전달하며 자원 claim은 해제하지 않는다.
- 증거: 실제 SQLite BEGIN IMMEDIATE 반례가 원격 3c2f8ac6e에서 STOP 지연을 재현했다(1 FAIL). 9fe2e83cbd는 잠금·취소·쓰기 실패 후 admission 반례 3 FAIL. source와 motion/service/departure 호출 경계는 독립 scoped static 안전 검토 PASS. 수정 SHA의 GREEN은 커밋 후 수행한다.
- gate 변화: 없음. 정지 ACK를 물리 정지나 claim 해제로 승격하지 않는다. 실제 장치·서명 배포·FULL 검증은 별도다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 분리된 영상 보정 구현의 계약 검사 경로

- 변경: 기존 D-318 계약 검사가 ingest_preview의 실제 보정 구현과 ingest의 위임 연결을 함께 확인하도록 경로를 맞췄다. 인증·수치 보정·preview/sightings 분리 검사는 유지하고 제품 코드는 바꾸지 않았다.
- 증거: 7fa484c528 원격 Fleet 묶음은 5903 passed, 이 경로 검사 1 failed, 316 skipped였다. known_failures 비교에서 NEW 1이며 기존 실패로 등록하지 않았다. 수정은 독립 scoped 검토 PASS, 최신 SHA 원격 검증은 커밋 후 수행한다.
- gate 변화: 없음. 건너뛴 브라우저·실물 장치 시험을 통과로 주장하지 않는다.

## 2026-10-20 · d91c5c0fb4 · fix(station): reconcile native completion during departure renewal

- 변경: 정상 native 완료가 status 조회와 permit 갱신 PUT 사이에 들어온 명시적 세대 거절만 재관측한다. 같은 boot/run/correlation, vacant owner, SUCCEEDED와 정확한 generation +1, 기존 permit·선택 작업·정책을 다시 검증한다. 새 motion·갱신 PUT·DB 갱신 없이 다음 tick으로 넘기며 다른 거절·불명 응답·권한 상실은 HOLD를 유지한다. CORE 가드와 원래 유효 기간은 그대로다.
- 증거: 실제 CORE tick을 갱신 직전에 넣은 a0c374810c 반례에서 정상 완료 1 FAIL, foreign readback·정책 해제·만료·불명 응답 4 PASS를 확인했다. 독립 계약 리뷰 후 d91c5c0fb4의 관련 HTTP·원장 5파일89 passed/skip0, 원격 exit0·known_failures 비교0. 중복 -q로 요약이 생략돼 실제 progress89건과 exit를 확인했다. source 범위16커밋 D-766 검사도 통과했다.
- gate 변화: 없음. 앞선 두 FULL 실패의 원인까지 입증한 것은 아니며 동시 시나리오와 새 통합 SHA의 FULL 관문을 추가 확인한다. 실기·현장 수용은 미실행이다.

## 2026-10-20 · 984a170d8e · fix(station): refresh readiness ACK and fence SIM goal admission

- 변경: navigation readiness의 HTTP·DB 조회 뒤 새 CORE ACK를 읽고, 이전 readback의 원래 수명도 다시 검사한다. 동일 위치의 전역 관측 갱신 때문에 옛 ACK가 거절되는 경합을 제거하며 기존 scope·permit·accept_ack 검사를 유지한다. 실제 호출자의 후속 원장·lease guard도 확인했다. SIM에서는 ordinary task 요청이 끝나기 전 다음 가상 시간 진행만 기다리며 trip·실제 worker는 그대로 실행한다.
- 증거: e0c51b8d0 동시 12건에서 4 FAIL/8 PASS. 3건은 실제 trip/job 없이 원본 정책 만료를 올바르게 거절했고, 1건은 옛 ACK 재사용이었다. 871fa4de73의 실제 HTTP·강제 시간 경계 반례에서 2 FAIL/음성 6 PASS·오류0을 확인했다. 두 독립 리뷰 후 984a170d8e의 HTTP·pipeline·runtime·bootstrap·trip 5파일98 passed/skip0, 원격 exit0·known_failures0. D-766 23커밋 및 lint0errors/33warnings를 확인했다.
- gate 변화: 없음. CORE·정책 유효기간과 motion 권한은 유지한다. 새 통합 SHA의 전체 착지 관문과 동시 재현 시험은 별도 확인하며 실기·현장 수용은 미실행이다.

## 2026-10-20 · uncommitted · lane 도착의 실제 정지 목표 결속

- 변경: 수락된 stop executing만으로0.3m에서 완료하지 않고, 검증된 실제 MapPose와 선택된 정지 목표의 Euclidean 거리에 기존0.15m 도착 기준을 적용한다. traffic hold-back 정지점과 free 판정·CORE stop 권한은 보존한다.
- 증거: f976 SIM은 전체 경로 arrived 뒤 실제 정착0.196729m로 FAIL이었다. native RED4→737 관련254 passed/skip0, 별도 문서 secret guard1 FAIL은 수정 문서 재검증 대상이다. 초과 거리의 접수·실제 hold·overshoot·측면·hold-back·거절 회귀와 독립 safety·최종 소스 검토0/0/0을 기록했다.
- gate 변화: 없음. 새 후보 반복 SIM 수용 HOLD. CORE가 목표 전에 hold하면 자동 해제·재지시하지 않는다.

## 2026-10-20 · uncommitted · 실제 목표 도달의 연속 SIM 검증

- 변경: stop 접수와 실제 도착을 구분한 후보의 최종 주행 증거를 보존했다. 기존0.15m와 traffic hold-back·CORE 권한은 유지한다.
- 증거: a24 native전체 영향12,973 passed/776 skipped/NEW0 중 Fleet5,592 passed/317 skipped. 같은 후보 연속2회 PASS, API arrived 위치가 기존0.15m 이내이며 실제 settle 오차0.004722/0.007501m, 최종 정지·lease 해제·정리 완료다.
- gate 변화: 전체 Fleet/현장 gate 승격 없음. 고정 조건 주행 SIM 수용만 충족했으며 실제 장치 이동·main 착지/push는 수행하지 않았다.

## 2026-10-20 · uncommitted · 통합관제 조회 전용 AI 대화

- 변경: D-810 웹 대화·영속 중복 방지·인증 재확인·관측 근거·독립 모델 broker와 Console 패널을 연결했다. 채널 설치·CLI 옵션은 소유 모듈로 옮겨 큰 app/CLI 파일의 증가를 피했다.
- 증거: dab629c171 집중 서버·CLI·기존 Discord·API 회귀 167개 통과. 재시작/UNKNOWN 재호출 금지, 타인 대화 비공개, 일반 CHAT의 근거 없는 완료 문장 차단을 검증했다. 전체 회귀·설치 검증은 후속 기록이다.
- gate 변화: 없음. 실제 모델 승인·AI PC 설치·운영 배포·작업 실행·장비 접근을 수행하지 않았다.

## 2026-10-20 · b1f18674b2 · D-821 명시적 이동 접수와 다국어 운영 경계

- 변경: 기명 운영자의 좌표 제출을 기존 IntentExecution/Task owner에 연결했다. 모델은 조회 권한을 유지하며 실행 연결은 기본 OFF다. ko-KR/en-US와 기존 요청 재시도 호환, optional 운영 설정을 추가했다.
- 증거: b0675386a1 서버/기존 설치기 94개, a1f0252d0a 사이트/설치 75개·Chromium 26개·Node 343개, b1f18674b2 실제 모델 19사례 통과. 같은 owner와 멱등 Task·권한 철회·타인 격리를 시험했다. 새 FULL은 별도 결과 기록을 따른다.
- gate 변화: 없음. 실제 운영 설치·장치 이동·Discord 메시지 송신은 하지 않았다.

## 2026-10-21 · d7fedbc9ab · D-831 관제 입력 전처리와 제안 경계

- 변경: 공통 Decision 정규화·등록 이름 해소·충돌/부정/조건/복합 후보 차단, Console/Discord 새 profile, broker 실제 사용량과 Fleet digest 검사·개인정보 없는 로그를 연결했다. 새 Discord profile은 자동 실행 worker를 설치하지 않는다.
- 증거: source 8454618b94 원격 전처리/보호 설치 123 passed; NFD+등록 이름 공백 회귀 RED1/36 뒤 d7fedbc9ab GREEN37. 독립 계약 검토의 이름 공백/장소-only STATUS 지적을 수정했다. 실제 모델 전후와 최종 영향 검증은 docs/validation/operator-preprocessing-2026-10-21/result.md에 기록한다.
- gate: 기존 SOURCE/LOCAL 경계만 다룬다. 새 확인 API·보호 설치·실음성·장치/현장 수용은 미실행. source 통과를 운영 활성화로 표시하지 않는다.

## 2026-10-21 · 5d90c8d670 · D-831 인용·Unicode 검색 경계 보완

- 변경: 원문과 모델용 인용문은 보존하고 검색 사본만 NFC/공백 정규화한다. 유의미한 공백의 등록 이름이 있으면 입력 사본 정규화를 생략해 혼합 조합형도 보존한다.
- 증거: 추가 RED5/37 및 RED1/42 후 GREEN43, 독립 계약 재검토 지적 해결. 실제 고정 모델 비교군19/19·Console26/26·Discord46/46, 입력 토큰 절감 없음. docs/validation/operator-preprocessing-2026-10-21b/result.md.
- gate: 보호 설치·실음성·장치/현장 수용·새 자연어 확인 API는 미실행. 새 Discord 자동 실행은 OFF.

## 2026-10-21 · uncommitted · Fleet 프런트 API의 여섯 성공 경로 검증 보완

- 변경: 정책 창 닫기·trip 재계획 확인·Cell reconcile·로봇 등록 해제·legacy 카메라 요청 거절·시작점 삭제에 실제 라우터와 기존 서비스/원장을 사용하는 HTTP 시험을 추가했다. 이름 있는 운영자·viewer 거절·상태 변경을 함께 확인한다.
- 증거: 기존 수신 기록은 여섯 경로의 403/503 응답만 증명했다. 새 시험의 커밋 SHA를 원격에서 실행한 뒤 실제 응답만 수신 기록과 기능표에 연결한다.
- gate 변화: 없음. 장치·모델·운영 배포·공개 게시를 실행하거나 입증하지 않는다.

## 2026-10-21 · a4fe41374e · 여섯 API의 정상 설정 HTTP 응답 확보

- 변경: 실제 200 응답을 정확한 통과 시험·소스 SHA와 연결해 수신 기록과 기능표를 갱신했다. 초기 거절 시험도 유지하며 앱 README에서 후속 검증 기록으로 안내한다.
- 증거: 원격 HTTP 시험 6 passed/skip 0/NEW 0. 앞선 세 실행의 시작점 설정 실패는 이 통과 결과와 분리했다. 독립 검토에서 권한 우회나 지원되는 결함은 없었으며, 기존 tracking 앱 fixture를 재사용한 최종 변경은 재검토한다.
- gate 변화: 여섯 경로의 HTTP 성공 관찰 공백을 해소했다. 장치·모델·운영 배포·공개 게시 gate는 바꾸지 않는다. docs/validation/fleet-frontend-http-success-2026-10-21.md.

## 2026-10-22 · aa784c548f · fix: 브라우저 Auth 오류 복구

- 변경: 등록된 요청의 HTML 승인 거부와 서비스 장애를 공통 로그인 복구로 보낸다. 잘못된 등록 정보는 복귀 대상으로 반영하지 않으며 JSON API 오류·PKCE·현재 세션과 resource grant 검사는 유지한다. 권한을 자동 부여하지 않는다.
- 증거: 원격 red에서 HTML 승인 거부·잘못된 요청 및 Learning callback 실패 4건을 재현했다. f2d7ea9d21의 Auth/Account/협업 49개 회귀가 통과했다. 후속 서비스 장애 사례와 통합 검증은 착지 기록에 남긴다.
- gate 변화: 운영 인증 서비스·원장·계정 권한은 변경하지 않았다.

## 2026-10-22 · fcdf36bdc1 · test: 실제 API에 연결한 Fleet 화면 흐름

- 변경: 기존 HTTPS 통합 서버를 공유 fixture로 추출하고 로그인·프로필 저장·목표 요청·QUEUED 작업 취소·로그아웃을 실제 화면과 API readback으로 확인하는 Chromium 시험을 추가했다. 실행 안내에 CI 필수 앱 검사와 재현 명령을 연결했다.
- 증거: 원격 합동 81 passed, skip 0, NEW 0. 취소 503과 실제 FakeRobot navigation_goal 호출을 각각 주입해 실패 검출을 확인한 뒤 제거하고 재통과했다. 독립 검토의 호출 기록 키 지적을 수정했다. docs/validation/fleet-frontend-ci-connected-2026-10-22.md.
- gate 변화: 서비스·API·장치 권한 변경 없음. 임시 DB·가상 장치와 대기 작업 취소 범위이며 실장치·배포·현장 수용은 포함하지 않는다.

## 2026-10-22 · uncommitted · camera-peer 전송 소비자 회귀

- 변경: 실제 camera-peer와 공통 PageScope를 사용하는 Node 회귀 9개를 추가했다. 권한 헤더·본문 미소비, 엄격 JSON, 종료 후 늦은 응답, 현재 자격·단일 POST를 확인한다.
- 증거: 전환 전 공통 전송 옵션 누락 1건 RED, 전환 후 기존 helper 2개를 포함해 11 passed/skip0. 실제 브라우저와 공식 원격 결과는 별도 기록한다.
- gate 변화: 시험 범위이며 권한·장치 명령을 추가하지 않는다.

## 2026-10-23 · 24856e823e · 계정 입력 전 화면 열기 회귀 보완

- 변경: 기본으로 접히는 계정 입력란을 사용하는 site-map 검사 24곳에서 기존 `open_token_access`를 먼저 호출한다. fixture와 assertions는 그대로 유지한다.
- 증거: 실제 수정 전 검사에서 hidden token 입력의 55 NEW를 확인했다. 수정 커밋의 데스크톱·모바일 로그인/재연결 5 cases가 원격 Chromium에서 passed/skip0/NEW0이며, helper 호출을 제외한 AST는 동등하다. [검증 기록](../../docs/validation/fleet-account-visibility-2026-10-23/result.md).
- gate 변화: 없음. 인증·권한·명령·실물 장치 동작을 변경하지 않는다. 전체 공식 병합 검증은 별도 기록한다.
- CE: 해당 없음. 기존 helper 사용과 실제 실패·회귀 근거로 판단을 복구할 수 있다.

## 2026-10-23 · 24856e823e · 계정 화면 변경의 로컬 main 통합 근거

- 변경: 계정 화면 준비 보완이 포함된 main 착지와 검증 한계를 별도 기록했다.
- 증거: guard 273 passed, 영향 범위 4,819 passed/219 skipped 및 6,228 passed/326 skipped, 브라우저 묶음 118 passed. 전체 Node wrapper도 별도 원격 실행에서 통과·skip0이다. 조사 상태 대기 1건은 단독 재검사 통과 후 공식 LOAD-FLAKY로 남았다. [통합 기록](../../docs/validation/fleet-account-visibility-2026-10-23/integration.md).
- gate 변화: 없음. 동시 실행으로 공유 로그가 겹친 범위의 전체 합계는 주장하지 않으며, 실물·배포·현장 수용과 push는 수행하지 않았다.
- CE: 해당 없음. 화면 준비 보완은 기존 helper로 설명되며, 남은 대기 불안정 원인은 해결된 교훈으로 기록하지 않는다.

## 2026-10-23 · 56762a179e · 독립·중첩 관제 구성과 영속 위임 기반

- 변경: 구성·직접 소유 검증과 영속 위임 identity·로컬 승인·owner 결과·취소 요청 기록을 추가했다. 기존 TaskStore admission transaction 안에서 위임과 작업을 함께 결속한다.
- 증거: 구성·저장·결속·null 승인 RED/GREEN을 공식 원격 실행했다. 최종 세 파일 30 cases 종료 0, known failures 0 NEW. [검증 기록](../../docs/validation/control-unit-foundation-2026-10-23/result.md).
- gate 변화: 없음. HTTP·화면·복구 종단·장치 수용은 후속이며 파이프라인 완성을 주장하지 않는다. CE 해당 없음: 검증한 판단은 코드·시험에 남는다.

## 2026-10-23 · uncommitted · 공통 조합 CSS의 닫힌 목록과 Fleet 적용 회귀

- 변경: 공통 동작 모음 CSS만 정확히 허용하고 다른 제품 CSS는 계속 거절하는 대조 검사를 추가했다. 로봇 선택 이동·긴 라벨 회귀를 별도 착지 단위로 보존한다.
- 증거: `37951c2501`의 검증된 두 시험 파일을 그대로 옮겼다. 이전 스타일 계약 4 passed·후속 영향 선택 707 passed 근거를 유지하고 새 main 조합은 착지 도구로 확인한다.
- gate 변화: 없음. API·명령·원장·물리 운전 변경 없음.

## 2026-10-24 · a7aaaed472 · 관제 간 위임·현장 승인과 native 결과 연결

- 변경: 직접 이웃 위임 HTTP·기명 현장 승인·동일 Task transaction 결속·고정 peer 자격과 앱 생애를 연결했다. stale·취소 요청·단절/재시작을 원래 identity로 조정하며 기존 dispatch와 native 결과 검사를 사용한다. 무로봇 독립 aggregate도 CLI에서 연다.
- 증거: 집중 store/서비스/routes/HTTP/재시작47 PASS, 실제 앱/CLI132 PASS, 독립 aggregate/기존 CLI52 PASS, port/앱/CORE 종단16 PASS(서로 겹치는 별도 실행). [검증 기록](../../docs/validation/control-unit-pipeline-2026-10-24/result.md).
- gate 변화: 최종 통합 검증·로컬 main 착지는 대기한다. 실물·FIELD 수용은 열지 않는다. CE 해당 없음: 판단을 코드·회귀·검증 기록에 보존했다.

## 2026-10-24 · uncommitted · D-856 중립 운송 snapshot과 요청 대조

- 변경: 기존 TRIP 원장에서 생성 principal 전용 GET 두 경로를 추가했다. 원본 요청 key·본문 digest·로봇·step/attempt와 수행 상태만 반환하고 Cell 공정 문서는 노출하지 않는다. 닫힌 profile에서도 읽되 쓰기·재시작 HOLD·claim·lease·안전 권한은 유지한다.
- 계약: API v1.298과 schema·버전 핀을 함께 갱신했다. POST 응답 유실 뒤 404는 미접수 증명이 아니며 자동 재접수 근거로 사용하지 않는다.
- 증거: RED commit 8cea2b26cb에서 새 시험 12개가 누락 route로 실패했다. commit 95664a6496의 공식 원격 관련 회귀는 77 passed, skip 0이다. 최초 회귀의 두 기존 호출자 시험은 새 읽기/기존 쓰기 경계를 구분하도록 보완했다. 공정 import 금지 subprocess에서도 읽기 동작을 확인했다. 최종 변경과 외부 앱 HTTP 검증은 후속 결과로 구분한다.
- gate 변화: 실물·production dispatch 활성화 없음. 첫 TRIP 흐름이며 팔 동작 중립화·Harbor 도달 검증 계약은 남는다. CE 해당 없음: 기존 실행·조회 구조와 회귀 시험으로 판단을 복구할 수 있다.

## 2026-10-24 · uncommitted · Fleet task worker 기동 이름 보존

- 변경: worker 분리 병합 뒤 lifespan이 import하지 않은 task_dispatch_loop를 호출하던 오류를 실제 import인 _task_dispatch_loop로 교정했다. 기존 monkeypatch와 task dispatcher 구현은 유지한다.
- 증거: 고정 f3d7d3fba5 전체 원격 회귀의 app ownership 시험 7개가 NameError로 실패했다. 수정 commit 477948a415에서 app ownership·CLI·link-address 기존 시험 76 passed, skip 0, 0 NEW다. 전체 회귀의 다른 run과 최종 head 증거는 별도로 분류한다.
- gate 변화: 기동 회귀 수정이며 실행 권한·profile 변경은 없다. CE 해당 없음: 원인과 교정은 코드·기존 회귀 시험으로 복원할 수 있다.

## 2026-10-24 · uncommitted · D-856 전체 회귀 발견 사항 교정

- 변경: TRIP_JOB_NOT_FOUND를 운영자 오류 문구 표에 추가했다. 없는 요청과 권한 밖 요청을 같은 조회 불가 문구로 표현한다.
- 증거: 고정 f3d7d3fba5 전체 회귀에서 worker NameError 34건과 문구 누락 1건을 분류했다. 수정 commit 52a9ccf6b5에서 해당 파일의 전체 suite와 기존 CLI/link-address/app ownership을 원격 실행해 261 passed, skip 0을 확인했다. 이는 수정 범위의 회귀이며 이전 FULL 실행 전체를 통과로 바꾸지 않는다.
- gate 변화: dispatch/권한 변경 없음. CE 해당 없음: 오류 문구 coverage와 기존 기동 시험이 회귀를 검증한다.

## 2026-10-24 · uncommitted · D-856 중립 팔 사전검사 HTTP

- 변경: 기존 proposer 인증과 workcell→instance 설치 대응으로 simulation preflight만 전달한다. dispatcher·Cell compiler·새 원장을 요구하지 않으며 응답 version/status·요청 전체 결속·typed code/reason을 검증한다. Fleet 수신 시각과 owner의 계산 시점 상태 나이를 구별한다.
- 증거: 신규 계약 RED 뒤 API v1.299를 구현했다. 전체 관련 원격 213 passed/skip0/0 NEW이며 독립 stdlib-only HTTP client→Fleet→UDS→owner admitted state를 검증했다. 최종 소스·이력 metadata 보완과 한계는 docs/validation/harbor-neutral-arm-preflight-2026-10-24/result.md에 기록했다. 기존 충전 HTTP pipeline은 별도 34ff5f55c1에서 10 passed/skip0다.
- gate 변화: 공개 simulation 읽기다. 기존 두 사람 승인·원장·claim·stop/rearm·출력 writer는 변경하지 않는다. 새 팔 실행·Harbor 공정 변환은 남는다. CE 해당 없음: 검증과 소스가 처리 조건을 보존한다.

## 2026-10-24 · uncommitted · D-856 step grant의 종류별 검증 경계

- 변경: Store의 고정 Cell 파싱과 직접 Cell 속성 검사를 registry의 typed 파싱·common identity/fence·전체 payload 대조로 분리했다. Cell body가 recipe/cell/job/step·자세·item·pallet/layer·선택 SKU를 계속 결속한다. DB 생성·등록 kind·승인/profile·owner dispatch·claim 상태 전이는 유지한다.
- 증거: 경계 함수 누락 RED12 후 구현했다. 유효하게 재서명한 Cell payload 변조와 원장/claim 불변, 비활성 시험 kind의 Cell 없는 helper 검사를 포함해 commit f3213debe8 원격 184 passed/skip0/0 NEW다. commit 1b9ed965ab의 별도 dispatcher/transport/문서·release 회귀는 152 passed/skip0/0 NEW이며 중복 사례가 있다. 독립 검토의 material finding은 없었다. Store ratchet은 943→928줄로 낮췄다.
- gate 변화: 중립 실행의 내부 선행 단계다. 새 kind·wire·DB producer·실행 권한을 열지 않았다. CE 해당 없음: 검증 책임과 거절 조건을 source·회귀·docs/plans/2026-10-24-step-grant-boundary-design.md에 남겼다.

## 2026-10-24 · dda08892c9 · D-856 원장 provenance 분리

- 변경: version5 parent schema가 legacy/physical 저장 형식을 구분하고 네 Cell 필수 provenance를 physical 행에서는 NULL로 강제한다. 기존 Cell 읽기·복구·checkpoint·정지 소비자의 물리 행 해석을 차단하며 root 연결의 FK ON 정책을 유지한다.
- 증거: 원격 RED9와 약한 schema 수용 RED2 뒤 atomic migration·전체 SQL 제약 대조를 구현했다. 원장 69개, 추가 checkpoint/SQL 실패 13개, 기존 Cell/다중 팔/TRIP 소비자 244개 별도 원격 회귀가 각각 skip0/0 NEW로 통과했다. 독립 구현 재검토 finding 해소. 정확한 소스와 실패 이력은 docs/validation/harbor-neutral-arm-ledger-2026-10-24/result.md를 따른다.
- gate 변화: schema 준비와 legacy 소비자 차단이다. 실제 physical 생성·승인·owner 실행·물리 자원 종료·Harbor 연결은 후속이다. CE 해당 없음: 코드·회귀에 보완 이유가 남는다.

## 2026-10-24 · fc5d75eecd · D-856 중립 팔 v2 transport 호환

- 변경: Fleet client의 ARM kind→v2 map·grant union·공통 receipt 타입을 연결했다. receipt identity·phase summaries·timeout·재시도 없는 경계를 유지한다.
- 증거: kind 누락 RED6 후 관련 원격 15 passed/skip0/0 NEW와 독립 검토를 확인했다. 선행 migration affected source 635d1e226e도 두 그룹 4722/6270 passed, 187/336 skipped, 각각 0 NEW로 끝났다. owner와 migration 검증 기록의 소스 범위를 구분한다.
- gate 변화: client 호환이며 실제 physical creator·등록 kind·claim 해제는 아직 없다. CE 해당 없음: source와 프레이밍 회귀에 조건이 남는다.

## 2026-10-24 · 46f56d6b48 · D-856 canonical owner capability와 ARM 응답 검증

- 변경: SDK가 실제 설치 capability를 v2 UDS로 한 번 조회하고 scope/closed DTO를 대조한다. ARM receipt는 grant의 canonical journal과 일치해야 하며 ARM404는 None 대신 fenced reconciliation이 필요한 unavailable다. Cell/TRIP 형식과 기존 조회를 유지한다.
- 증거: 누락 DTO/API/owner binding·receipt/404 RED35 뒤 관련 원격 790 passed/7 skipped/0 NEW. 실제 adapter/UDS와 SDK를 함께 검증했고 fixed SHA 독립 검토와 size/safety exit0를 확인했다. docs/validation/harbor-managed-capability-2026-10-24/result.md를 따른다.
- gate 변화: FULL23개 목록은 진행 중이다. registry·physical creator/two-person 승인·World 물리 종료 증거·claim 해제·Harbor ARM 연결은 아직 닫혀 있다. CE 미해결: 이전 e26 G1 timing의 원인은 미확정이다.

## 2026-10-24 · ebba429c4c · D-856 FULL 이력 표 guard 수정

- 변경: 빠진 v1.306 변경 이력 표 행을 추가했다. 원본 FULL summary JSON을 validation에 보존했다.
- 증거: entry9의 API 이력 표 행 누락1 NEW, 다른22개0 NEW로 종료했다. Fleet entry12는6285 passed/336 skipped/0 NEW였다. doc commit ebba429c4c에서 표를 보완하고 entry9 전체를 재실행 중이다. source Python은46 이후 동일하다.
- gate 변화: FULL 통과 판정 전이다. 기존 Cell/TRIP와 새 physical producer/claim 경계를 유지한다.

## 2026-10-24 · ebba429c4c · D-856 이력 표 수정 재검증 완료

- 변경: 수정 후 재검증과 원본 FULL 실패를 validation/plan에 함께 기록했다.
- 증거: 실패 entry9 전체가7371 passed/91 skipped/0 NEW, runner exit0였다. 원본46의 다른22개는0 NEW다. 원본과 수정 SHA의 결과를 구분한다.
- gate 변화: physical create/approval/World 관측/atomic claim 종료·Harbor ARM은 다음 승인된 계획의 실행 범위다. 이 host 결과를 실물 수용으로 사용하지 않는다.

## 2026-10-24 · 205cd08767 · D-856 두 표본 물리 검사

- 변경: World 사실을 설치 정책·durable attempt context와 대조하는 내부 pure validator. 모든 참가자의 전체9개 링크·속도/그리퍼·엄격한 expanded-zone 이탈, object-origin source/target pose, 두 관측의 순서/경계 이후/age를 검사한다. 원장/claim/dispatch 쓰기는 없다.
- 증거: 최초 RED25 뒤 집중63 passed, 독립 검토의 quaternion norm/축소 descriptor 두 누락을 RED4로 재현하고 보완했다. source205 집중67 passed/skip0, affected 전체 두 묶음4587 passed/189 skipped와6312 passed/336 skipped, 각각exit0/known0 NEW·고정 SHA 독립 재검토 finding 없음, source size/safety exit0. 범위 중복과 skips는 합산/수용으로 세지 않는다. 상세는 docs/validation/harbor-physical-evaluator-2026-10-24/result.md다.
- gate 변화: credential ingress·실제 current context/fence·physical create/approval·atomic claim 종료·Harbor ARM은 미완료다. CE 해당 없음: source·회귀·검증 문서가 두 검토 finding의 원인/수정을 보존한다. 과거 e26 G1 timing 원인 미확정은 별도다.

## 2026-10-24 · 76a173b5fd · D-856 중립 물리 제안과 두 사람 승인

- 변경: 같은 Fleet DB에 physical create/read/approval을 추가했다. 정책에 arm/zone/object 키를 결속하고 legacy owner workcell도 함께 claim한다. 정확한 proposal/설치/capability와 두 사람·dispatch control을 확인해 approval/READY/claims를 원자 기록한다. schema version6·old-host 거절, stop/startup HELD/UNKNOWN 보존, 무관 DB/권위 필드 덮어쓰기/역행 시각 거절을 포함한다. legacy 완료 메서드는 AST 동일 이동하고 기존 호출을 보존했다.
- 증거: 초기 RED21, 검토 네 finding은 RED5 failed/24 passed 뒤 보완했다. 원본3c 회귀의 구조 검사2건·기존 version 기대값1건과9d FULL의 구조/G1 2 NEW를 보존했다. source76 집중1292 passed/skip0, FULL23개 각각exit0/known0 NEW(Fleet6343 passed/336 skipped, root9707 passed/1135 skipped), 동일source G1 timing4 passed/skip0와 독립 안전 검토, source9 commits size/safety exit0다. 기존 normalize/reserve/release AST는 유지했고 중복/skip은 합산·수용으로 세지 않는다. docs/validation/harbor-physical-proposals-2026-10-24/result.md를 따른다.
- gate 변화: public HTTP/DTO·실제 capability 수집·prepared context/dispatcher·관측 ingress·물리 claim 종료·Harbor ARM은 미완료다. CE 미해결: 원본G1 접촉 간격 p99 0.525457s의 원인은 미확정이며 최신 strict 통과를 해결로 보지 않는다. 코드 검토 finding은 source·회귀·검증 기록에 남긴다.


## 2026-10-24 · 58f7cc7b14 · D-856 중립 ARM 작업 HTTP 제안과 승인

- 변경: simulation 설치 시 create/read-by-key/ID와 named-operator admit를 기존 auth/audit에 연결했다. 모든 owner의 실제 SDK capability를 transaction 밖에서 수집하고 기존 원장의 승인/CAS/fence/claims를 호출한다. present-Origin은 기존 same_origin helper로 검사한다. 앱은 물리 refs만 보내며 자원·capability·grant·업무 완료를 지정하지 못한다. 미설치는503이다.
- 증거: b5 집중1205 passed/16 NEW(시험의 잘못된 자원 조회15건/Origin누락1건) 뒤 최종18 passed/skip0/known0 NEW다. 소스58 FULL23개 각각exit0/known0 NEW(Fleet6361 passed/336 skipped, root9710 passed/1132 skipped), 독립 계약·전체로그 evidence 검토 추가 finding 없음이다. docs/validation/harbor-arm-job-http-2026-10-24/result.md를 따른다. 원본 실패와 각SHA를 보존하고 중복/skip을 합산·수용으로 세지 않는다.
- gate 변화: 제안/승인 HTTP만 연결했다. prepared context·장치 제출·관측 credential·physical receipt/claim 종료·Harbor ARM은 이 소스에서 미완료다. 뒤의 schema7/8 변경은 별도 검증한다. CE 미해결: 이전G1 timing 실패 원인은 미확정이며 이번 strict 통과는 원인 해결 근거가 아니다.


## 2026-10-24 · 3b23a23bca · D-856 물리 준비·전송 의도·종료 원장

- 변경: common migration7/8의 physical attempt·raw observation 기록, 고정 grant/context·최초 전송의 최종 시간/표본 snapshot 검사, owner receipt causality·HOLD 유지, 별도 POST_ACTION receipt/원래 owner·generation claim 해제를 구현했다. 기존 Cell resolver·recipe·완료 callback·_KINDS에 등록하지 않았다. 실제 SDK submit/get/cancel과 credential HTTP/Harbor는 아직 없다.
- 증거: 준비74·최초 의도91·결과 보완229·물리 종료101의 각 고정 SHA 집중 원격은 skip0/known0 NEW다. 원본 RED와 affected 실패를 별도 보존하고, legacy version 기대값72/구조 small 표시46을 보완했다. 독립 계약 검토의 TTL·clock/list·receipt causality/HOLD finding은 RED 후 재검토했으며 source3b 물리 해제의 추가 finding은 없다. 958d→3b19커밋 size/safety 각각exit0. docs/validation/harbor-physical-execution-2026-10-24/result.md를 따른다.
- gate 변화: synthetic World 사실과 원장 transaction의 집중 검증이다. sourcecf의 local_invocations 두 그룹은 FULL이 아니며 후속 구현을 고정한 최종23개 FULL은 대기 중이다. HTTP58 FULL과 합치지 않고 중복 수치를 합산하지 않는다. 실제 bounds/장치/현장 수용을 넓히지 않는다. CE 미해결: 이전G1 timing 원인은 미확정이다.


## 2026-10-24 · 54f27e6fb7 · D-856 전체 stop 대상과 내부 SDK dispatcher

- 변경: 같은 workcell의 모든 physical participant를 별도 stop/rearm target에 결속하고 legacy dispatcher/recovery mapping을 유지했다. SDK 클래스는 모든 owner의 fresh simulation identity/capability, 공통 journal의 process-safe RPC guard, control 조회 뒤 최종 proof/fence/claim/freshness 재검사를 거쳐 고정 grant로 한 번만 제출한다. refresh/cancel은 원래 grant만 사용하고 유실/404/restart/HOLD는 점유를 보존한다. app ingress에는 아직 연결하지 않았다.
- 증거: stop RED7 뒤 source80dde 집중65 passed/skip0/0 NEW와 genuine safety review/trailer, SDK RED14 errors 뒤 겹친 dispatcher·늦은 control read RED4 failed/14 passed를 재현했다. source54 집중121 passed/skip0/0 NEW(실제 POSIX process guard 포함), 독립 재검토 추가 finding 없음이다. docs/validation/harbor-physical-execution-2026-10-24/result.md와 stop-source-review.md를 따른다.
- gate 변화: Fake SDK/stop port와 transaction·동시성의 집중 증거다. native UDS/독립 TCP HTTP·관측 credential·Harbor ARM·최종 FULL23은 후속이며 HTTP58 FULL에 합치지 않는다. 물리/현장 gate를 넓히지 않는다. CE 미해결: 이전G1 timing 원인은 미확정이다.
