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
