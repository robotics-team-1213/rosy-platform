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

## 2026-09-27 · uncommitted · D-300 surface typography tokens
- 변경: games board의 본문·제목 계층을 공유 weight/leading/track 토큰으로 이동하고 고유 kicker 자간은 보존했다.
- 증거: Fleet+games host suite에서 games 포함 619 passed/5 skipped; D-300 browser run에서 games board 시나리오 통과. screenshot: X:\DevTemp\games_board_initial.png.
- gate 변화: SOURCE/LOCAL 유지. 실제 경기·로봇 동작 수용은 아님.
- 결정: D-300.

## 2026-09-27 · 9049bd37 · test(games): verify D-300 after latest-main integration
- 변경: games board typography 토큰 변경을 최신 main 기준에서 검증했다.
- 증거: Fleet+games host suite 636 passed/5 skipped; games browser 시나리오를 포함한 Fleet/games browser run은 17 passed, 2 known-main cases deselected.
- gate 변화: SOURCE/LOCAL 유지. 경기장/실물 로봇 수용은 아님.
- 결정: D-300.

## 2026-09-27 · f4f15776 · verify games after latest main integration
- 변경: latest main 통합 상태에서 games host test를 실행했다.
- 증거: games 101 passed.
- Gate: SOURCE/LOCAL remain GO; no device or field acceptance claimed.
- Decision: D-300.

## 2026-09-27 · 9ca7bc26 · verify games host suite
- 변경: latest main 통합 후 D-300 surface token contract와 함께 games styles를 검증했다.
- 증거: games host suite 101 passed.
- gate 변화: SOURCE/LOCAL 유지. device/field acceptance는 포함하지 않는다.
- 결정: D-300.

## 2026-09-27 · uncommitted · fix(games): readable match and stop request states

- 변경: 최초 수신 전 점수를 결측으로 표시하고, 경기 단계·점수·유실을 변화 시에만 `role=status`로 안내한다. 호스트 연결 오류 시 마지막 수신 정보임을 표시한다. `/stop` 요청은 대기·접수·실패를 보여주며 실패 뒤 재시도할 수 있다. D-218·D-253의 즉시 정지와 Space 경로는 유지한다.
- 증거: Chromium 1280×800 게임 보드 9 passed; 게임 호스트 110 passed; 공유 UI/대화 상자 계약 58 passed. 실패·연결 오류 LOCAL 캡처는 `X:\DevTemp\games_board_stop_retry.png`, `X:\DevTemp\games_board_host_disconnected.png`.
- gate 변화: 모듈 SOURCE/LOCAL GO 유지. 게임 UI/UX G2 전체 셀 미완료로 HOLD; DEVICE/FIELD PARKED.
- 결정: D-306.

## 2026-09-27 · uncommitted · fix(games): 마지막 필드 위치 구분 (D-306/D-309)

- 변경: 서버가 판정한 `delayed`/`unavailable` 또는 호스트 연결 오류 때 필드 좌표와 천장 프레임을 감광하고, 필드 중앙에 `마지막 수신 위치 · 현재 위치 아님`을 표시한다. 점수에도 마지막 수신 표지를 붙인다. 정상 수신으로 회복하면 표지와 보조기기 설명 참조를 제거한다. 점수·경기 식별은 마지막 기록으로 남고 `/stop` 경로는 유지한다.
- 증거: Chromium 1280×800 최초 오류·HOLD·지연·끊김 4 passed, 최초 대기·정지 실패 2 passed, 정지 행 뷰포트 단독 재실행 1 passed. `src/site/games/test`와 `test/test_rosy_games_surface.py` 111 passed. 전체 브라우저 묶음은 중간 편집 후 중단했고, 추가 회차의 Chromium launch 10초 timeout 1건은 단독 재실행에서 통과했다. LOCAL 캡처 `X:\DevTemp\games_board_delayed.png`, `X:\DevTemp\games_board_host_disconnected.png`.
- gate 변화: SOURCE/LOCAL GO 유지. UI/UX G2 전체 셀·DEVICE/FIELD 실측 수용은 이 변경으로 완료되지 않는다.
- 결정: D-306, D-309. 물리 정지 GO 근거 아님.

## 2026-09-27 · uncommitted · fix(games): 마지막 경기 단계 구분 (D-306/D-309)

- 변경: 지연·데이터 대기·호스트 연결 오류 때 상단 경기 단계를 `마지막 수신 단계`로 구분하고 보조기기 경기 요약에도 같은 맥락을 반영한다. 서버 fresh 수신으로 회복하면 현재 경기 단계 문구로 되돌린다. 정지 요청·접수·재시도 경로는 유지한다.
- 증거: Chromium 1280×800 게임 보드 14 passed 및 추가 집중 회귀 2 passed, 게임 호스트 111 passed. `X:\DevTemp\games_board_delayed.png`, `X:\DevTemp\games_board_host_disconnected.png` LOCAL 캡처. 수정 전 끊김 단계 검사는 적색으로 재현했다.
- gate 변화: SOURCE/LOCAL GO 유지. 게임 UI/UX G2 전체 셀과 DEVICE/FIELD·실제 정지 수용은 별도 HOLD.
- 결정: D-306, D-309.

## 2026-09-28 · uncommitted · fix(games): 필드 중심 반응형 경기 보드 (D-280/D-309)

- 변경: 1280×800에서 588px 필드와 빈 오른쪽 공간에 흩어진 관측 정보를 필드(720px)·관측 패널 2열로 재배치했다. 760px 이하에서는 한 열로 접고 상단 연결 상태와 마지막 수신 점수 배지를 별도 행에 둔다. 정지 행은 화면 하단 sticky로 유지하며 600px 폭 스크롤 후에도 보이도록 검증했다. 경기 상태·정지 API 의미와 D-280 상태색은 유지했다.
- 증거: Chromium 전/후 1280·600·390×800 캡처는 `X:\DevTemp\rosy-games-layout\before_*.png`, `after2_*.png`. 1280 필드 588→720px, 세 폭 모두 가로 넘침 0; 1280 세로 넘침 0, 390 세로 넘침 0, 600은 관측 패널을 스크롤하되 정지 행은 화면 안이다. 새 레이아웃 브라우저 1 passed; 게임 호스트 111 passed. 전체 브라우저 15개는 경합 중 13 passed/2 fixture 시간 의존 실패였고, 두 fixture를 고정 clock으로 바꾼 집중 회차 2 passed. 첫 라이브 fixture도 고정 clock으로 바꾼 뒤 2개 집중 검사 통과.
- 디자인 검사: `impeccable detect --json --scope layout` 경고 2건. 점수 wrapper는 자식 셀마다 12px padding이고, 정지 행도 위쪽 12px padding이다. 검사기가 `/common/tokens.css`를 로컬 파일로 해석하지 못해 토큰 값(`--space-3: 12px`)을 반영하지 못한 정적 오판으로 판정했다.
- gate 변화: SOURCE/LOCAL 유지. DEVICE/FIELD·실제 정지 수용은 별도 HOLD.
- 결정: D-280, D-309.

## 2026-09-29 · uncommitted · fix(games): HOLD alarm is a crit-filled chip (P3 round)

- 변경: `#lost` 경보("공을 잃음 · HOLD")를 `--lost` 빨간 글자에서 공용 `--status-crit` 채움 칩으로 바꿨다(D-202 — 위험은 채움이다). `.lost[hidden]` 가드를 함께 넣어 명시적 display가 hidden 속성을 덮는 이 리포의 정전 패턴을 막았다. `--lost` 토큰은 남는 참조가 없어 제거했다.
- 증거: `src/site/games/test test/test_games_board_browser.py` 117 passed. 초기·play·HOLD·지연·stale × 1280/390/600 재촬영 — 가로 넘침 0, 페이지 오류 0(`X:\DevTemp\rosy-uiux-p3-games`). 지연·stale은 "마지막 수신 단계"·필드 증거 칩으로 정직 표시 확인. `impeccable detect` []. 회차 기록은 `docs/validation/uiux-surfaces-2026-09-29/README.md`.
- gate 변화: 없음. SOURCE/LOCAL GO 유지, 실물 카메라·양측 로봇 정지 readback과 사람 G3는 별도다.

## 2026-09-29 · uncommitted · web-surface-hardening: 보드 CSP·/stop Origin·web_common share 해석

- 변경: `preview.py`가 web_common을 ament share(manifest 있을 때) 다음 소스 트리 순으로 찾고, `/common` 목록은 `manifest.json`에서 읽는다. `package.xml`에 `exec_depend web_common`. HTML 응답에 CSP를 싣고, `POST /stop`은 Origin 헤더가 있는데 보드 자신이 아니면 403으로 거절한다(Origin 없는 호출은 통과).
- 증거: `python -m pytest src/site/games/test -q` 104 passed.
- gate 변화: 없음.
- 결정: D-157.

## 2026-09-30 · faa60733 · D-359 US-002 경기 보드는 어둡게 고정

- 변경: `index.html`에 `data-theme="dark" data-theme-pin="dark"`를 정적으로 둔다(theme.js를 싣지 않는 쪽이 단순하다 — 경기장 녹색이 바탕이다). `surfaces.yaml` `themes: [dark]`, 레지스트리 시험이 pin을 지킨다. `.lost`의 위험 채움 글자를 `--ink-on-crit`로 바꿨다(값은 같다).
- 증거: `python -m pytest src/site/games/test -q` 통과(876 passed 묶음).
- gate 변화: 없음.

## 2026-09-30 · bbba318f · D-359 US-003 피치 캔버스가 styles.css 피치 블록을 읽는다

- 변경: `board.js`의 hex 리터럴 9개를 `window.RosyPalette.cssColor("--pitch"|"--line"|"--home"|"--away"|"--pitch-ink"|"--ball")`로 바꿨다 — 값의 주인은 `styles.css` `:root` 피치 블록이다. 로봇 이름 글꼴 `11px sans-serif` → `canvasFont(12, "body")`. 화면은 여전히 dark 고정이라 보이는 색은 같다.
- 증거: `test_canvas_palette_contract.py::test_games_pitch_colours_live_in_its_stylesheet` 통과. 브라우저 `test/test_rosy_games_surface.py` 9 passed, `test/test_games_board_browser.py` 8 passed 7 failed — 7건은 `wait_for_function` 문자열 평가가 보드 CSP(`script-src 'self'`, unsafe-eval 없음)에 막히는 하네스 문제로 e19f2ef4에서도 똑같이 7 failed. 렌더 시험 `test_match_board_renders_published_play_state`는 페이지 오류 없이 통과, 캡처 `X:/DevTemp/rosy-d359/shots/us003-games-board.png` 색 그대로.
- gate 변화: 없음.

## 2026-09-30 · 890309a8 · D-359 US-004 보드 자간·낡은 영상 흐림·마커 칩이 토큰을 쓴다

- 변경: `.kicker` 자간 0.14em → `--track-label`, `#frame[data-evidence]` 0.48 → `--disabled-opacity`, `.chips li`는 경기장 칩 어휘를 두고 글자만 토큰 척도(`--weight-label --text-label/--leading-label --body`, 자간 0 — 320px 네 칸이 넓어지지 않게).
- 증거: `test/test_rosy_games_surface.py` 9 passed, `src/site/games/test` 통과.
- gate 변화: 없음.

## 2026-09-30 · aeb31356 · D-359 US-005 경기 보드 세 단

- 변경: 760px → `(width < 64rem)`, 540px → `(width < 30rem)`. `.chips`는 `repeat(auto-fill, minmax(min(100%, max(4.5rem, 25% - gap)), 1fr))` — 넓은 칸은 네 칸을 넘지 않고 320px에서는 세 칸. compact 머리는 부제를 접고 위아래 여백을 줄인다(320×568 105px, 18.5%). 시험 `test_compact_board_keeps_header_budget_stop_and_chips_in_view[390|320]`.
- 증거: `test/test_games_board_browser.py` 10 passed 7 failed — 7건은 이 가지 이전부터 같은 목록(CSP, main에서도 실패). `test/test_rosy_games_surface.py` 9 passed. 변이 `ui-topbar` `min-height: 300px` → 빨강. 옛 네 칸 격자 되돌림은 초록이다 — US-003 자간 0 뒤로 320px에서 넘치지 않는다(칩 검사는 감시용).
- gate 변화: 없음.
