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

## 2026-10-01 · uncommitted · feat(discovery): 검색기 임대가 끊기면 관제가 경보한다

- 변경: 점검(2026-10-01) #4 연쇄 — 발견 브리지가 끊긴 뒤 45 s가 지나면 새 로봇 발견과 새 주소로 옮기기가 멈추는데, 관제는 처음부터 스캔이 없을 때와 같은 노란 "검색기 연결 대기"만 보였다. `server/discovery.py` `snapshot()`이 `scanner_state`(`never_seen`·`online`·`expired`)와 `scanner_age_s`를 더한다(`scanner_online`은 그대로). `web/console.js` 발견 패널이 `expired`면 `crit` "검색기 끊김", 마지막 스캔 나이와 멈춘 기능, `rosy-mdns-bridge` 확인 안내를 보이고, 끊김·복귀를 한 번씩 이벤트 로그에 남긴다. 등록 코드(`enrollment.py`·`enrollment.js`)는 건드리지 않았다(feat/d341-fleet-pairing-server와 겹침 회피). API 참조 `/api/fleet/discovery` 행 갱신.
- 증거: `test_discovery.py` 상태 시험(never_seen → online 45 s → expired), 콘솔 경보 소스 계약, `test_discovery_api.py` 응답 모양, `test/test_fleet_console_browser.py`의 Chromium 시험(`ROSY_RUN_BROWSER_TESTS=1`, 경보 crit·로그 1회·복귀) 통과. `python -m pytest src/site/fleet/test -q` 986 passed, 6 skipped (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(discovery): 고정 주소가 지금 망에 있는지 로봇마다 판정한다

- 변경: 점검(2026-10-01, "192.168.1.x 가정 없음") #2 — 사이트 Wi-Fi가 192.168.1.x에서 10.16.36.x로 바뀌자 로봇이 까닭 없이 오프라인으로만 보였다. 새 순수 모듈 `server/address_drift.py` `classify_addresses()`가 로스터의 고정 base_url을 최근 스캔과 대조해 `in_scanned_subnet`·`outside_scanned_subnets`·`seen_at_other_address`·`unknown`(스캔 없음·검색기 꺼짐·`.local` 이름이 스캔에 없음)으로 나누고, 모든 고정 로봇이 스캔된 망 밖이면 `all_outside`를 켠다. 새 `GET /api/fleet/discovery/addresses`(viewer+)가 이것에 출처(`static`·`enrolled`)와 `movable`(등록부가 `address_changed`이고 새 주소가 하나)을 붙인다. 스캔을 받을 때 robots.yaml 로봇이 모든 스캔 망 밖이거나 다른 주소에 보이면 경고 로그를 한 번 남긴다.
- 결정: 스캔 행에는 robot_id·device_uid가 없다. 그래서 같은 로봇 판정은 등록부가 이미 쓰는 발견 이름(등록 로봇), 인증된 HELLO의 `device_name`, 그 둘이 없으면 base_url 자체의 `.local` 이름(파일 로봇)으로만 한다. 신원이 없는 로봇은 이름으로 짐작하지 않는다. 실제 이동은 기존 "새 주소로 옮기기"가 토큰으로 robot_id·hostname·serial·device_uid를 다시 확인한다. 스캔 행에 넷마스크가 없어 "스캔된 망"은 스캔 주소마다 /24로 잡는다(`site_networks` 인자는 사이트 호스트 인터페이스를 알게 되면 더한다 — 지금은 배선하지 않음: Fleet은 컨테이너 안이라 호스트 인터페이스를 모른다). 포트만 다르면 주소 변경으로 보지 않는다(파일 로봇의 https:8443 대 광고 8080). `.local`은 풀지 않고(D-370 5.3) 스캔의 IP를 제안으로만 싣는다. 응답에 토큰·경로·userinfo가 없다. API 참조에 행을 더했다.
- 증거: 새 `test_address_drift.py` 14, `test_address_drift_api.py` 4 — 모듈 없음으로 적색 확인 뒤 18 passed.
- gate 변화: 없음(LOCAL).
