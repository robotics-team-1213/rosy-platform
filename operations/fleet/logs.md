# fleet logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [사이트 패브릭 계획](../../docs/plans/2026-09-14-site-middleware-role-fabric.md), [군집 대형 슬라이스 결과](../../docs/plans/2026-09-08-swarm-formation-slice-results.md)와 `git log -- src/fleet`를 본다.

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
