# games logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-18 · uncommitted · feat(games): load a match config without touching the robots

- 변경: `config/match.yaml` + `load_match()` + `games match --config ... --dry-run`. Field와 두 `RobotEndpoint`만 만들고 HTTP를 열지 않는다. `match.local.yaml`은 gitignore.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: 없음 (LOCAL GO 유지)

## 2026-09-18 · uncommitted · feat(games): talk to CORE with mode, teleop, and stop only

- 변경: `HttpPlayerClient`가 CORE `POST /api/v1/mode`·`/teleop`·`/safety/stop`만 부른다. 4xx/5xx는 예외. `MatchHost._estop_all`은 한쪽 `estop` 실패 후에도 나머지를 호출한다.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: 없음 (LOCAL GO 유지)

## 2026-09-18 · uncommitted · feat(games): run the match loop against fake robots

- 변경: `MatchHost`가 `Observer.observe` → `game.step` → `policy.act` → `gate` → `PlayerClient.teleop`/`estop`. 킥오프 미준비·유실 HOLD도 roster 양쪽에 teleop 0. `teleop` 예외면 양쪽 `estop`. TwistSink 제거.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: 없음 (LOCAL GO 유지)

## 2026-09-18 · uncommitted · feat(games): policy returns twists for both robots

- 변경: `Policy.act(obs, state) -> dict[str, Twist]`. 휴리스틱은 PLAY에서 관측된 두 로봇 모두에 추적·골 바이어스·이격을 내고, 그 외 phase는 빈 dict. MatchHost.tick이 dict를 gate에 넘긴다.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: 없음 (LOCAL GO 유지)

## 2026-09-18 · uncommitted · feat(games): clamp non-play and ramming twists in the referee gate

- 변경: `game/gate.py`가 PLAY가 아니면 ZERO, 0.35 m 이내면 전진 linear를 `min(linear, 0)`, NaN/inf는 ZERO. `Field.min_spacing_m=0.35`. MatchHost.tick이 gate를 거친다.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: 없음 (LOCAL GO 유지)

## 2026-09-18 · uncommitted · chore(games): bootstrap pytest path and drop empty isaac

- 변경: `test/conftest.py`로 루트 pytest 수집. 빈 `games/isaac/` 삭제. harness 기록 추가
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: SOURCE/LOCAL HOLD로 기록 시작. ROS-SIM/ARTIFACT N/A, DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(games): mark LOCAL host complete without overhead camera

- 변경: 경계 시험이 field/game/policy에서 cv2/httpx/rclpy/core/fleet을 금지하고, host는 overhead.py만 cv2를 허용한다. loop.py/transport.py는 cv2 없음. LOCAL 호스트를 overhead 없이 닫음.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 31 passed
- gate 변화: LOCAL GO 유지. SOURCE는 트리에서 overhead/homography를 다음 계획으로 명시한 채 GO. DEVICE/FIELD PARKED.

## 2026-09-18 · uncommitted · feat(games): plug soccer in and arm CORE without a camera

- 변경: `catalog`로 soccer/heuristic 플러그인. `match.local.yaml` 오버레이. `HoldObserver`+`run_match`로 카메라 없이 MANUAL 무장·정지 teleop. 관측 예외 시 양쪽 halt. 빈 토큰은 Authorization 생략.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 42 passed
- gate 변화: 없음. LOCAL GO 유지. DEVICE/FIELD PARKED.

## 2026-09-18 · uncommitted · feat(games): project the ceiling camera onto the pitch

- 변경: `field/homography.py` 순수 호모그래피. `host/project.py` 픽셀→Observation. `host/overhead.py`만 cv2 (ArUco 코너 10–13, 로봇 마커, 주황 blob). CLI `--observer overhead|hold`.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 53 passed
- gate 변화: LOCAL GO 유지 (합성 프레임). DEVICE/FIELD PARKED.

## 2026-09-18 · uncommitted · docs(adr): remaining games track is D-95–D-99

- 변경: progress `adrs`에 D-94–D-99. 다음 게이트는 D-96 계단 1
- 증거: ADR 로그 색인
- gate 변화: 없음. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(adr): D-100 goal markers

- 변경: progress `adrs`에 D-100. 골 20/21 + 영역
- 증거: ADR 로그
- gate 변화: 없음

## 2026-09-18 · uncommitted · feat(games): see goals as ArUco 20/21 (D-100)

- 변경: `match.yaml` `goals.home_id`/`away_id`(기본 20/21), 선택 HSV 입구. overhead가 마커·영역을 필드 m 폴리곤으로 투영. 양쪽 없으면 필드 끝 기하. 득점은 `in_home_goal`/`in_away_goal`. cv2는 overhead만.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 64 passed
- gate 변화: LOCAL GO 유지 (합성). DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(adr): D-101 games board is not CORE dashboard

- 변경: progress `adrs`에 D-101. 축구 보드는 노트북 게임 표면
- 증거: ADR 로그
- gate 변화: 없음

## 2026-09-18 · uncommitted · feat(games): serve a laptop match board off CORE (D-101)

- 변경: `games/web/` 정적 보드. `--preview`가 127.0.0.1에서 overlay JSON·선택 JPEG. CORE `/dashboard`·tokens.css 없음. cv2는 overhead만.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 69 passed
- gate 변화: LOCAL GO 유지. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · fix(games): keep --preview open until interrupt

- 변경: `--preview`이고 `--ticks`가 없으면 20 Hz로 Ctrl+C까지. 프레임 유실 시 JPEG를 비움. dry-run에 `goals 20/21`. 보드는 home_id로 색을 가름.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 72 passed
- gate 변화: 없음. LOCAL GO 유지. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(adr): D-102 20 Hz loop, D-103 yaml limits

- 변경: progress `adrs`에 D-102·D-103
- 증거: ADR 로그
- gate 변화: 없음

## 2026-09-18 · uncommitted · feat(games): run live matches at 20 Hz and clamp yaml limits (D-102, D-103)

- 변경: `--ticks` 없으면 20 Hz Ctrl+C. `--preview`는 보드만. `limits.angular`는 gate·휴리스틱 클램프. 유실 HOLD는 즉시. period > lost_hold_s면 기동 거부.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 76 passed
- gate 변화: LOCAL GO 유지. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(adr): D-104 limits PUT, D-105 halt input

- 변경: progress `adrs`에 D-104·D-105
- 증거: ADR 로그
- gate 변화: 없음

## 2026-09-18 · uncommitted · feat(games): arm PUT limits and halt on space or board stop (D-104, D-105)

- 변경: arm이 MANUAL 다음 PUT `/safety/limits`. 스페이스와 보드 POST `/stop`이 양쪽 halt. 보드는 CORE URL을 열지 않음.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 79 passed
- gate 변화: LOCAL GO 유지. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(adr): D-106 Fleet does not start matches yet

- 변경: progress `adrs`에 D-106. Fleet 매치 버튼 없음, reset은 games
- 증거: ADR 로그
- gate 변화: 없음

## 2026-09-18 · uncommitted · test(games): lock the Fleet/games one-way cut (D-106)

- 변경: Fleet 소스는 games를 모르고, 게임 보드/CLI에 fleet 시작이 없다. RobotMode.SOCCER 없음.
- 증거: `python -m pytest src/games/test test/test_games_surface.py src/fleet/test/test_boundaries.py -q`
- gate 변화: 없음. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(adr): D-107 observe-only, D-108 --drive

- 변경: progress `adrs`에 D-107·D-108. 계단 1 기본 관측만
- 증거: ADR 로그
- gate 변화: 없음

## 2026-09-18 · uncommitted · feat(games): default to observe-only, opt in with --drive (D-107, D-108)

- 변경: 기본은 arm/teleop 없음. `--drive` 또는 `--drive rosy_01`. `--observe-only`와 배타.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 85 passed
- gate 변화: LOCAL GO 유지. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · docs(adr): D-109 catalog lock for deferred track

- 변경: progress `adrs`에 D-109. observer는 hold/overhead만
- 증거: ADR 로그
- gate 변화: 없음

## 2026-09-18 · uncommitted · test(games): reject onboard, isaac, neural until stair 4 (D-109)

- 변경: `OBSERVERS` 카탈로그. `make_observer("onboard")` 거절. isaac/neural/onboard 파일 없음. catalog는 cv2를 상단 import하지 않음.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: 없음. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · feat(games): first-contact 0.10 cap and --stair 1-5 (D-110, D-111)

- 변경: `load_match`는 `limits.linear` > 0.10을 거절. `--stair 1` 관측만, `--stair 2`는 `--drive <한 id>`, `--stair 3|4|5`는 두 대. pytest ≠ FIELD GO.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q` 103 passed
- gate 변화: 없음. DEVICE/FIELD PARKED

## 2026-09-18 · uncommitted · feat(games): stair 1 visibility report; close host track (D-112, D-113)

- 변경: `stair1_visibility` 코너·로봇·골·공 보고. `ready` ≠ FIELD GO. LOCAL 호스트 트랙 닫힘. 다음은 웹캠·Pinky.
- 증거: `python -m pytest src/games/test test/test_games_surface.py -q`
- gate 변화: 없음. DEVICE/FIELD PARKED

## 2026-09-22 · uncommitted · test(games): unique test basenames; fix the gate cmd spec

- 변경: `test_cli/test_session/test_transport.py`를 `test_games_cli/test_host_session/test_host_transport.py`로, `fakes.py`를 `fake_host.py`로 바꿨다. fleet/test와 같은 basename이면 합친 pytest 수집이 깨지는 것을 없앤다.
- 변경: `progress.md` gate cmd와 `AGENTS.md` 테스트 명령의 옛 경로를 고쳤다 — `src/games/test`→`src/apps/games/test`, 없는 `test/test_games_surface.py`→`test/test_rosy_games_surface.py` (harness.yaml과 같게).
- 증거: `python -m pytest src/apps/games/test test/test_rosy_games_surface.py -q` 110 passed (2026-09-22 Windows)
- gate 변화: 없음. SOURCE·LOCAL GO 유지.

## 2026-09-24 · uncommitted · fix(games): 경기 보드 정지 행 가시 (D-201)

- 변경: `#pitch`·`#frame`에 `max-width/height` 종횡비 보존 상한 ? 선언 뷰포트(1280×800)에서 halt 행이 y=806으로 접힘 아래로 내려가던 것 해소. 초점 물체는 줄어들 수 있어도 정지를 밀어낼 수 없다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_games_board_browser.py -q` → 5 passed(신규 게이트 변이 증명: 상한 제거 → 429px 적색).
- gate 변화: 게임 G1에 halt 가시 게이트 추가.
- 결정: D-201
- 교훈: 없음.

## 2026-09-25 · uncommitted · fix(games): the Space promise is real (D-224)

- 변경: F-22 — body-focus Space fires the same /stop POST once as the
  halt click; controls keep native Space-to-click (no double fire),
  repeat ignored. The "Space stops both" hint was text-only before.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pytest space test -q passes
  (mutation: dead handler goes red, restore goes green).
- gate 변화: games G1 gains the Space browser gate.
- 결정: D-224
- 교훈: none.
