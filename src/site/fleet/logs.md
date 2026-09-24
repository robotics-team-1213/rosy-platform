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
