# docs logs

추가만 한다. 형식: [module harness 설계](plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `docs/reference/ROSY ADR Log.md`, `docs/plans/`의 날짜별 문서, `git log -- docs`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the docs harness pilot
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python tools/harness/rosy_harness.py lint` 0 errors, 2 warnings(rosy_core·deploy last_verified uncommitted, docs 자체 오류 아님); `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q` 64 passed (2026-09-15 Windows). `docs` 경로에 미커밋 변경이 있어(`git status --short -- docs` 비어 있지 않음) `last_verified.commit`은 `uncommitted`
- gate 변화: 없음. SOURCE/LOCAL GO, ROS-SIM/ARTIFACT/DEVICE/FIELD N/A(문서 모듈, 실행 대상 없음)를 처음 기록
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-15 · uncommitted · docs(harness): register docs and correct generated-file wording
- 변경: `harness.yaml`에 `docs` 등록, `AGENTS.md`에 기록 위치·계약 시험 명령 추가, `progress.md`에서 생성물 범위를 `index.md`·`STATUS.md`로 정정하고 `cmd`를 `python3`으로
- 증거: 미실행 — 기록 정정만. 등록 후 검증은 이어지는 generate·lint 실행으로 확인
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): hold docs while the ADR log carries a conflict marker
- 변경: 2차 리뷰 반영. 다른 세션 merge-aside 복원이 `ROSY ADR Log.md` 1590행에 충돌 종료 표시를 남겼고, lint가 충돌 표시를 오류로 잡도록 바뀌므로 lint 기반 증거를 쓰는 SOURCE/LOCAL을 HOLD로. 표시는 다른 세션 소유 작업이라 이 기록에서 고치지 않았다
- 증거: `Select-String -Path "docs/reference/ROSY ADR Log.md" -Pattern '^(<<<<<<<|=======|>>>>>>>)( |$)'` → 1590행 (2026-09-16 01:10)
- gate 변화: SOURCE GO→HOLD, LOCAL GO→HOLD
- 결정: 없음
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(concept): fix interface design laws and per-surface grammar as D-72
- 변경: `docs/concept/16_ROSY_Interface_Design_Principles.md` 신규. ADR Log에 D-72 표 행·본문 추가(Proposed). concept README의 Document Index와 Current mapping 표에 16행 등록. 2026-09-16이 기록한 ADR Log 1590행 충돌 종료 표시가 해소되어 SOURCE/LOCAL 재판정
- 증거: `python tools/harness/rosy_harness.py lint` 0 errors, 16 warnings; `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q` 69 passed (2026-09-17 Windows, 미커밋 WIP 포함 작업 트리). 이 호스트의 python3에는 PyYAML이 없어 `python`(3.14.5)으로 실행했다. 1590행 재확인: 충돌 표시 없음, D-61 본문 산문
- gate 변화: SOURCE HOLD→GO, LOCAL HOLD→GO (blocker 해소). ROS-SIM/ARTIFACT/DEVICE/FIELD는 N/A 유지
- 결정: D-72 Proposed. D-68(CAP-001과 개념 descriptor 분리)과 D-71(합성 미구현)은 유지하며 뒤집지 않는다. 콘솔 통합(두 서버·CSP·단일 파일 자족성)과 D-7/D-23 상태 불일치는 이 기록이 결정하지 않는다
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(adr): supersede D-7 so the local screen has one standing decision
- 변경: ADR Log에 D-75 표 행·본문 추가(Proposed). D-7 표 행과 본문 Status를 `Superseded by D-75`로. `docs/progress.md`의 `adrs`에 D-75 추가하고 다음 gate 3번을 해소로 표시. 계획 문서 `docs/plans/2026-09-17-interface-design-implementation-design.md` 신규(pending approval, 범위 A 확정)
- 증거: `python tools/harness/rosy_harness.py lint` 0 errors, 16 warnings; `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q` 69 passed (2026-09-17 Windows, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음. SOURCE/LOCAL GO 유지
- 결정: D-75 Proposed — D-7(React+TS+Vite)을 대체하고 로봇 로컬 화면을 빌드 단계 없는 손으로 쓴 정적 자산으로 확정한다. D-23이 사실상 대체해 왔으나 두 ADR이 모두 Accepted로 남아 모순이었다
- 교훈: Accepted ADR 둘이 서로 모순인 채로 한 달 넘게 남아 있었고, 구현은 한쪽을 따르고 문서는 양쪽을 주장했다. 이행 계획을 세우는 단계에서야 드러났다 — 새 결정이 기존 결정을 실질적으로 대체할 때 Status 갱신을 같은 커밋에서 하지 않으면 이런 모순이 조용히 남는다

## 2026-09-17 · 8fdd8d2 · docs: lock G4 vocabulary, one operator console, and D-61 records
- 변경: concept 16 어휘 정정, D-77, D-61 Accepted, 모듈 progress/logs와 생성 index 착륙
- 증거: `python tools/harness/rosy_harness.py lint`; `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py test/test_control_launch_boundary.py -q`
- gate 변화: 없음. SOURCE/LOCAL GO 유지. DEVICE N/A
- 결정: D-61 Accepted, D-77 Accepted
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(adr): lock leftover gates as D-78–D-81
- 변경: 남은 HOLD를 새 ADR로 가름. D-78 네이티브 Pi ARTIFACT, D-79 현재 트리 GO, D-80 G4는 Device, D-81 Fleet REST gather. device-validation §1 ROS-SIM을 HOLD로 정정
- 증거: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`
- gate 변화: 없음. docs SOURCE/LOCAL GO. ARTIFACT/DEVICE는 소비 모듈 HOLD
- 결정: D-78–D-81 Accepted (경로·증거 규칙). G0–G3는 D-41–D-56 Proposed 유지
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(adr): record the OKLCH palette decision as D-82
- 변경: ADR Log에 D-82 표 행·본문 추가(Proposed). `docs/progress.md`의 `adrs`에 D-82 추가
- 증거: `python tools/harness/rosy_harness.py lint` 0 errors, 13 warnings; `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q` (2026-09-17 Windows, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음. SOURCE/LOCAL GO 유지
- 결정: D-82 Proposed — 팔레트를 OKLCH에서 생성하고 값이 지켜야 할 성질을 계약 시험으로 고정한다. 경보는 둘(정상은 잉크), 위험은 채움, 밝기가 색상보다 먼저, status는 따뜻한 띠·series는 차가운 띠
- 교훈: D-72 S1이 색을 토큰으로 "옮기기만" 하고 값을 재지 않았다. 옮긴 뒤 재 보니 적록 색약에서 위험과 주의가 1.07:1로 붕괴해 있었다 — 리팩토링에서 값을 보존하는 것과 값이 옳은지 확인하는 것은 다른 일이고, 전자만 하면 결함이 그대로 이사한다

## 2026-09-17 · uncommitted · docs(adr): accept D-82 after palette gate tests
- 변경: D-82 Status Proposed→Accepted. 계약 시험 `test_palette_gates.py`가 값을 지킨다
- 증거: `PYTHONPATH=src/rosy_core;src python -m pytest src/rosy_core/test/test_palette_gates.py src/rosy_core/test/test_ui_token_contracts.py -q`
- gate 변화: 없음
- 결정: D-82 Accepted. Device GO가 아니다
- 교훈: 없음

## 2026-09-17 · dc89264 · docs(harness): stamp last_verified after SOURCE re-run
- 변경: deploy를 제외한 모듈 progress last_verified를 dc89264로. deploy SOURCE의 bash identity 시험은 이 Windows 호스트에서 Git Bash 임시경로가 깨져 재실행 증거가 아니다
- 증거: 185 passed, 13 failed (전부 test_dds_identity_contracts.py). 나머지 SOURCE 계약은 통과
- gate 변화: 없음. ARTIFACT/DEVICE HOLD
- 결정: D-79
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(adr): lock remaining runtime as D-83–D-86
- 변경: ROS-SIM 최소 묶음, hardware 이미지 제외, 도크 ESP32 ARTIFACT, POSIX identity last_verified
- 증거: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`
- gate 변화: 없음
- 결정: D-83–D-86 Accepted (실행 순서). G0–G3는 D-41–D-56 Proposed 유지
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(adr): lock remaining execution as D-87–D-89
- 변경: colcon install 전제, Fleet 소켓은 사이트 PC·D-83 뒤, D-35는 Task 14 재실행 전 금지
- 증거: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`
- gate 변화: 없음
- 결정: D-87–D-89 Accepted
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(adr): lock soccer as a game host (D-90)
- 변경: RobotMode에 SOCCER 없음. 1단계는 노트북 천장 카메라 + MANUAL teleop
- 증거: `python -m pytest src/rosy_core/test/test_protocol_schemas.py test/test_network_topology_contracts.py -q`
- gate 변화: 없음. DEVICE/FIELD HOLD
- 결정: D-90 Accepted
- 교훈: 없음

## 2026-09-17 · uncommitted · docs(adr): accept D-54–D-56 source gates, park Device ADRs (D-91)
- 변경: D-54 Nav2 fail-closed, D-55 조작은 로봇 로컬, D-56 엔코더 기본. D-41–D-44·D-51·D-52는 Device 측정 전 Proposed
- 증거: 색인 Status + `test_nav2_profile_limits.py` / `test_footprint_profiles.py` (소스 게이트). Device GO 아님
- gate 변화: 없음
- 결정: D-54–D-56 Accepted (소스/아키텍처). D-91
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(c6): rule the profile velocity reaches a seam lie, not an accepted duck-type
- 변경: `docs/plans/2026-09-06-module-split-criteria.md` C6 판정 표에 `safety/manager.py — profile → max_linear_velocity, max_angular_velocity` 행 추가. 판정은 **seam lie**이며 `ALLOWED` 항목 추가가 아니라 삭제로 닫혔다
- 증거: `RobotProfile`은 `rosy_core/profile.py:11`이 소유하고 두 멤버는 `@property -> Optional[float]`다(`:24`, `:29`). `services.py:195`가 같은 객체에 `profile.model`을 직접 읽으므로 `profile`은 None일 수 없다. `test_core_logic.py:29` 스텁 둘 다 속성을 명시 선언해 `getattr` 기본값은 어떤 시험도 타지 않았다. 코드 수정은 피어 커밋 `73f0128`이 같은 형태로 반영했고, `python -m pytest src/rosy_core/test -q` 857 passed, 10 skipped, 0 failed (2026-09-18 Windows)
- gate 변화: 없음
- 결정: 승인된 D-64 덕타이핑(`policy`/`calibration`)과 범주가 다르다. 그쪽은 `safety/`가 `rosy_control`을 import하지 않으려고 외부 객체를 덕타이핑하는 것이고, 이쪽은 자기 패키지가 소유한 타입에 방어적으로 접근한 것이다
- 교훈: `getattr(owned_type, "field", None)`은 안전해 보이지만 침묵을 산다. 프로퍼티 이름이 바뀌면 예외 대신 기본 속도 상한으로 조용히 떨어지는데, 그게 하필 속도 제한을 계산하는 경로다. 방어가 필요 없는 자리의 방어는 결함을 감추는 장치다


## 2026-09-18 · uncommitted · docs(adr): record that L2 components are shared as a vocabulary table, not a file
- 변경: ADR **D-92** 신규(색인 행 포함). 파일로 공유하는 것은 L1(`tokens.css`)뿐이고 L2 컴포넌트는 표면마다 각자 쓴다는 결정, 콘솔 L2 어휘 열 개와 각각을 지키는 게이트 표, 그리고 아직 없는 넷(되돌릴 수 없는 조작의 확인 · Fleet 예외 행 · 좁은 화면의 콘솔 · face intent)의 **설계만** 기록. concept 16 §10 적합성 목록에 새 게이트 3건 추가
- 증거: `python -m pytest test -q` (루트 계약), `python tools/harness/rosy_harness.py lint`. D-92 본문의 수치는 이 세션의 실측이다 — 다시쓰기 전 시트에 새 게이트를 걸면 별칭 8개·계단 밖 간격 118곳(값 53가지)·계단 밖 글자 95곳(68가지), Playwright 1280×720에서 지도 469px·pageScroll 0
- gate 변화: 없음
- 결정: 공용 컴포넌트 라이브러리를 만들지 않는다. concept 16 §4가 네 표면을 아우르는 컴포넌트 라이브러리를 "목표가 아니라 결함"으로 규정하고 있고(Fleet이 콘솔처럼 보이게 되며 LCD는 불가능해진다), D-75 아래서는 Fleet 서버가 `rosy_core` 자산을 서빙해야 해 모듈 경계도 넘는다(D-73). 대신 이름과 규칙을 표로 공유한다
- 교훈: "나머지 컴포넌트를 미리 만들자"는 요구의 기본 형태가 하필 설계 법이 금지한 것이었다. 쓰이지 않는 컴포넌트는 결함을 숨기기도 한다 — 이번에 치수 토큰 13개가 사용처 0이었고 채택하자마자 44px 미만 터치 타겟 다섯이 드러났다. 그래서 만들지 않고 적었다

## 2026-09-18 · uncommitted · docs(adr): lock remaining rosy_games track as D-95–D-99

- 변경: ADR D-95–D-99 색인·본문. 합성 overhead ≠ DEVICE, 현장 다섯 계단, 온보드/Isaac/신경망은 FIELD 반복 뒤. D-94 수정(합성 시험은 overhead import 허용).
- 증거: `python -m pytest test/test_harness_contracts.py src/rosy_games/test test/test_rosy_games_surface.py -q`
- gate 변화: 없음. rosy_games DEVICE/FIELD PARKED 유지
- 결정: D-95–D-99 Accepted (방향). 현장 GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(adr): goals are ArUco 20/21 plus a mouth region (D-100)

- 변경: ADR D-100. 골 위치는 천장 ArUco 20/21과 선택 HSV 영역. 일반 QR 아님. 득점은 필드 m 폴리곤. D-96 계단 1에 골 가시성 포함.
- 증거: ADR 색인 연속, `python -m pytest test/test_harness_contracts.py -q`
- gate 변화: 없음
- 결정: D-100 Accepted (관측). 구현 GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(games): see goals as ArUco 20/21 (D-100)

- 변경: 골 마커 20/21과 선택 HSV 입구를 overhead가 필드 m 폴리곤으로 투영. 양쪽 없으면 필드 끝. 합성 시험 ≠ DEVICE (D-95).
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q` 109 passed
- gate 변화: rosy_games LOCAL GO 유지. DEVICE/FIELD PARKED
- 결정: D-100 LOCAL 관측 확장. 현장 계단 1은 실제 웹캠
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(adr): D-101 games board is not CORE dashboard

- 변경: ADR D-101. 축구 미리보기는 노트북 게임 표면. CORE `/dashboard` 금지. concept 16 §2 Game host 행.
- 증거: ADR 색인
- gate 변화: 없음
- 결정: D-101 Accepted. DEVICE GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(games): serve a laptop match board off CORE (D-101)

- 변경: `rosy_games match --preview`가 127.0.0.1에서 피치 보드를 연다. CORE 자산·이미지에 없음.
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q` 114 passed
- gate 변화: rosy_games LOCAL GO 유지. DEVICE/FIELD PARKED
- 결정: 프론트엔드를 표면별로 나눔. 게임 보드는 콘솔이 아니다
- 교훈: 없음

## 2026-09-18 · uncommitted · fix(games): keep --preview open until interrupt

- 변경: 미리보기가 1틱 만에 닫히지 않게. 유실 프레임 JPEG 잔상 제거. dry-run에 골 20/21.
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q` 117 passed
- gate 변화: 없음. DEVICE/FIELD PARKED
- 결정: D-96 계단 1 노트북 도구가 실제로 떠 있어야 한다
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(adr): lock host loop 20 Hz and yaml limits (D-102, D-103)

- 변경: ADR D-102·D-103. 매치 루프는 `--ticks` 없으면 20 Hz. limits는 gate. 유실 HOLD 즉시.
- 증거: ADR 색인
- gate 변화: 없음
- 결정: D-102·D-103 Accepted. DEVICE GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(games): run live matches at 20 Hz and clamp yaml limits (D-102, D-103)

- 변경: 라이브 매치가 preview 없이도 20 Hz. angular 0.40 클램프. period > lost_hold_s 거부.
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q` 121 passed
- gate 변화: rosy_games LOCAL GO 유지. DEVICE/FIELD PARKED
- 결정: YAML에만 있던 한계를 호스트 계약으로 옮김
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(adr): lock PUT limits and host halt input (D-104, D-105)

- 변경: ADR D-104·D-105. arm은 PUT safety/limits. 정지는 스페이스와 보드 /stop.
- 증거: ADR 색인
- gate 변화: 없음
- 결정: D-104·D-105 Accepted. DEVICE GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(games): arm PUT limits and halt on space or board stop (D-104, D-105)

- 변경: HttpPlayerClient.set_limits. 보드 정지 버튼은 같은 노트북 서버만 친다.
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q` 124 passed
- gate 변화: rosy_games LOCAL GO 유지. DEVICE/FIELD PARKED
- 결정: 설계 §4.2·§5를 호스트 계약으로 옮김
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(adr): Fleet match-start is later one-way (D-106)

- 변경: ADR D-106. Fleet 매치 버튼은 지금 없음. reset()은 games. fleet↛games.
- 증거: ADR 색인, `test/test_rosy_games_surface.py`
- gate 변화: 없음
- 결정: D-106 Accepted. 콘솔 버튼 미구현
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(adr): D-96 stair 1 is observe-only (D-107, D-108)

- 변경: ADR D-107·D-108. 기본 관측만. `--drive`는 계단 2+이며 FIELD GO 아님.
- 증거: ADR 색인
- gate 변화: 없음
- 결정: D-107·D-108 Accepted. DEVICE GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(games): default to observe-only, opt in with --drive (D-107, D-108)

- 변경: CLI 기본은 모터 무장 없음. `--drive` / `--drive rosy_01`.
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q` 130 passed
- gate 변화: rosy_games LOCAL GO 유지. DEVICE/FIELD PARKED
- 결정: D-96 계단 1 호스트가 공을 보면 달리지 않는다
- 교훈: 없음

## 2026-09-18 · uncommitted · docs(adr): lock deferred catalog (D-109)

- 변경: ADR D-109. 계단 4 전 카탈로그는 soccer/heuristic/hold/overhead. onboard/isaac/neural 거절.
- 증거: ADR 색인, catalog 시험
- gate 변화: 없음
- 결정: D-97·D-98·D-99 호스트 잠금. 구현 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(games): first-contact 0.10 cap and --stair 1-5 (D-110, D-111)

- 변경: ADR D-110·D-111. `limits.linear` ≤ 0.10. `--stair 1–5` 호스트 프리셋. pytest ≠ FIELD GO.
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q`
- gate 변화: rosy_games LOCAL GO 유지. DEVICE/FIELD PARKED
- 결정: D-96 계단 2–5 호스트 스위치. 현장 GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(games): stair 1 visibility report; close host track (D-112, D-113)

- 변경: ADR D-112·D-113. 계단 1 가시성 보고. LOCAL 호스트 트랙 닫힘. 웹캠·Pinky 실측이 남음.
- 증거: `python -m pytest src/rosy_games/test test/test_rosy_games_surface.py test/test_harness_contracts.py -q`
- gate 변화: rosy_games LOCAL GO 유지. DEVICE/FIELD PARKED
- 결정: `ready`와 pytest는 FIELD GO가 아니다
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(sim): gz_multi bridge lock, spawn pose seed, coincident yield guard (D-114–D-116)

- 변경: ADR D-114·D-115·D-116. 시뮬은 ros_gz_bridge. spawn 을 map initialpose 로 심음. 관제는 겹친 pose 를 길로 보지 않음.
- 증거: `python -m pytest src/rosy_gz_sim/test src/rosy_fleet/test/test_server_yield.py src/rosy_fleet/test/test_server_traffic.py test/test_harness_contracts.py -q`
- gate 변화: rosy_gz_sim/rosy_fleet LOCAL GO 유지. ROS-SIM HOLD
- 결정: D-114–D-116 Accepted. 현장/시뮬 GO 아님
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(dds): Cyclone, no raw Image on bridges, sensor QoS (D-117–D-120)

- 변경: ADR D-117–D-120. env.sh/gz_multi 가 Cyclone+LOCALHOST. 생 Image 는 gz_multi 브리지에 없음. scan/imu/Image 는 sensor-data QoS.
- 증거: `python -m pytest test/test_dds_rmw_contracts.py src/rosy_core/test/test_bridge_timers.py src/rosy_gz_sim/test/test_gz_package_contract.py test/test_harness_contracts.py -q`
- gate 변화: LOCAL GO 유지. ROS-SIM/DEVICE HOLD
- 결정: FastDDS 이중 프로파일 없음. 생 Image 는 Fleet/보드에 안 탐
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(core): apply Cyclone before rclpy.init; web reports only (D-121)

- 변경: ADR D-121. `apply_cyclone_rmw` 는 init 전. 빈 RMW 채움, FastDDS 거절. 대시보드는 rmw 표시만. REST로 RMW를 바꾸지 않음.
- 증거: `python -m pytest src/rosy_core/test/test_rmw.py src/rosy_core/test/test_ros_graph_monitor.py src/rosy_core/test/test_dashboard.py -q`
- gate 변화: LOCAL GO 유지. DEVICE PARKED
- 결정: 웹 적용 버튼 없음. init 이후 env 변경은 거짓 성공
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(core): correct foreign RMW on next CORE start (D-122)

- 변경: ADR D-122. FastDDS env 는 거절이 아니라 Cyclone으로 고친 뒤 init. 커널 reboot 아님. 웹 `system.reboot` 연동 없음.
- 증거: `python -m pytest src/rosy_core/test/test_rmw.py src/rosy_core/test/test_ros_graph_monitor.py -q`
- gate 변화: LOCAL GO 유지. DEVICE PARKED
- 결정: 런타임 재기동으로 이웃 노드를 맞춘다. Pi reboot 는 RMW 도구가 아니다
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(core): persist Cyclone then Host Agent reboot from dashboard (D-123)

- 변경: ADR D-123. 관리자 POST /api/v1/system/dds/cyclone 이 오버레이에 저장한 뒤 system.reboot 중계. confirmed 없으면 저장 안 함. CORE 는 reboot() 를 직접 안 부름.
- 증거: `python -m pytest src/rosy_core/test/test_rmw.py src/rosy_core/test/test_dashboard.py src/rosy_core/test/test_host_cards.py -q`
- gate 변화: LOCAL GO 유지. DEVICE PARKED
- 결정: 웹 수정 후 재부팅은 Host Agent. 라이브 RMW 패치 없음
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(core): dashboard AP toggle and Wi-Fi connect via Host Agent (D-124)

- 변경: ADR D-124. network.status 구조화. POST /api/v1/host/network/mode 와 /connect. 대시보드 AP 켜기/끄기·SSID 연결. PSK는 응답/감사에 안 남김. CORE는 nmcli 안 부름
- 증거: `python -m pytest test/test_host_agent.py src/rosy_core/test/test_host_cards.py src/rosy_core/test/test_dashboard.py test/test_harness_contracts.py -q`
- gate 변화: LOCAL GO 유지. DEVICE PARKED
- 결정: AP on/off는 SITE_STA/RELAY_AP_STA. Wi-Fi 연결은 Host Agent network.connect
- 교훈: 없음

## 2026-09-19: Core 패키지 모듈화 (Level 3 Phase 1)

- 배경: 모놀리식 core 패키지의 의존성 분리를 위해 논리적 라이브러리 단위(ament_python)로 분할 결정
- 결정: ADR D-125 기록 (Option A - 단일 프로세스 유지 및 도메인 라이브러리 분할)
- 실행: Phase 1으로 `core_common` 패키지 신규 생성 및 기초 모듈(identity, config, protocol 등) 이동 완료
- 검증: `colcon build` 및 Python import 경로 전체 수정

## 2026-09-19: Core 패키지 모듈화 (Level 3 Phase 2 & 3)

- 실행: Phase 2로 `core_events` (이벤트 버스) 패키지를 분리하여 독립시킴
- 실행: Phase 3로 `core_features` (안전, 배터리, 네비게이션, 군집, 도킹 등 도메인 로직) 패키지를 분리하여 독립시킴
- 검증: 파이썬 import 경로 전체 재지정(core.events -> core_events.events, core.safety -> core_features.safety 등) 및 `package.xml` 의존성 주입 완료

## 2026-09-19: Core 패키지 모듈화 완료 (Level 3 Phase 4 & 5)

- 실행: Phase 4로 `core_api_web` (FastAPI 및 웹 대시보드) 패키지를 분리하여 독립시킴
- 상태: Phase 5로 기존의 `core` 패키지에는 진입점 노드(`main.py`, `node.py`)와 `bridge/`, `system/` 모듈만 남겨 `core_node` 역할을 하도록 정비함
- 결과: 단일 거대 모놀리식 구조(Option A 아키텍처)를 4개의 도메인 라이브러리(`core_common`, `core_events`, `core_features`, `core_api_web`)와 1개의 실행 노드(`core`)로 완전히 분리 완료

## 2026-09-19: Fleet 도메인 폴더명 변경 (site)

- 결정: 다중 로봇 관제를 담당하는 도메인 폴더명을 중복되는 `fleet/fleet` 구조에서 내부 용어와 일치하는 `site/fleet`으로 변경 (SiteHub, site-fabric 등)

## 2026-09-19 · uncommitted · docs(adr): propose full module separation (D-126)

- 변경: ADR D-126 색인·본문(Proposed). D-125 색인 행 누락 보충. 설계 `docs/plans/2026-09-19-full-module-separation-design.md` 신규, 실행 `docs/plans/2026-09-19-full-module-separation.md` 신규(이음새 S0~S5, Task 0~6)
- 증거: 2026-09-19 작업 트리 실측 — `package.xml` 19개 선언 의존 파싱, 비테스트 import sweep(임시 스크립트, 저장소 미포함), `cmd_vel` 발행/구독 grep, launch 포함 추출. S1 어댑터 `control.*` 3건(`control_sensor_adapter.py:118,140,213`)·S2 구독 잔재 2곳(`web_node.py:431`, `wander/node.py:36`)·S3 fleet 생산 코드 `core_common` 5파일·S4 `swarm_bench.py`의 `fleet.*` 직접 참조·S5 v1 12모듈의 features 7영역 참조. D-64 구 가드(`test_runtime_slices.py`)는 구 경로 `src/rosy_core`를 가리켜 신 구조 미검사 확인
- gate 변화: 없음. SOURCE/LOCAL GO 유지. ARTIFACT/DEVICE/FIELD HOLD·PARKED
- 결정: D-126 Proposed. Accepted 조건은 가드 5개 초록 + 관련 회귀 PASS. `core_features` 추가 분할·멀티 프로세스·mapping 분리는 비목표
- 교훈: 없음

## 2026-09-19 · uncommitted · docs(adr): accept D-126 after the five guards and affected suites go green

- 변경: D-126 Status Proposed→Accepted(색인 포함). S1 provider 역전·S5 Protocol+모듈 이동·C6 ALLOWED 재건·auth_dependency 구 경로 복원·host_cards/rmw 구 경로 수정. 설계·실행 계획에 실제 메커니즘 반영(토픽 경계→provider 역전, 파사드→Protocol, 가드 6 삭제)
- 증거: `test/test_module_separation.py` 5 passed; adapter 23 passed; api/host/rmw/criteria/policy_link 158 passed 1 failed(실패 1건은 D-126 미접촉 `rosy_default.yaml` 구 경로 — 9b77daa 잔재); control 996 passed 26 skipped + 환경성 2건(패키지 디렉터리 실행 시 PASS); fleet 312·omx 10·games 101·gz_sim 14 passed. core 나머지 실패(web 자산·swarm 경로·triage/palette 등)는 D-126 미접촉 파일의 구 경로 참조로 별도 백로그
- gate 변화: 없음. SOURCE/LOCAL GO 유지. ARTIFACT/DEVICE/FIELD HOLD·PARKED
- 결정: D-126 Accepted (분리 계약 범위). Level-3 구 경로 잔재 백로그는 수용을 막지 않는다
- 교훈: 구조 개편 커밋이 시험의 경로 상수를 함께 옮기지 않으면, 다음 작업의 회귀가 개편 잔재와 자기 결함을 구분하는 데 반나절이 든다 — 이동과 경로 갱신은 같은 커밋에
