# core logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [흡수 결과](../../docs/plans/2026-09-12-control-absorption-results.md)와 `git log -- src/core`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the core harness pilot
- 변경: `progress.md`, `logs.md`, 생성 `index.md` 추가. `AGENTS.md`에 기록 위치와 작업 순서 연결
- 증거: `PYTHONPATH=src/core;src/control;src python -m pytest src/core/test -q` 759 passed, 10 skipped (Windows, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음. 기존 SOURCE/LOCAL/ROS-SIM GO, ARTIFACT/DEVICE HOLD, FIELD PARKED를 스냅샷으로 옮김
- 결정: D-61 Proposed
- 교훈: 없음


## 2026-09-15 · uncommitted · docs(harness): stop carrying over unrerun ROS-SIM evidence
- 변경: 리뷰 반영. `last_verified.commit`을 `uncommitted`로, SOURCE에 재실행 명령 추가
- 증거: `python -m pytest test/test_harness_contracts.py test/test_network_topology_contracts.py -q` 62 passed; `python tools/harness/rosy_harness.py lint` 0 errors, 2 warnings(uncommitted). ROS 시험 자체는 미실행
- gate 변화: ROS-SIM GO→HOLD (2026-09-13 증거를 재실행 없이 GO로 옮겼던 것을 정정)
- 결정: 없음
- 교훈: 없음

## 2026-09-17 · uncommitted · feat(web): compress dashboard assets and make tokens.css the single source of colour
- 변경: S0 — `api/app.py`에 `GZipMiddleware(minimum_size=1024)` 추가. S1 — `web/tokens.css` 신규(닫힌 3집합 + 래스터 토큰), `styles.css`의 원시 색 62곳을 토큰 참조로 치환(값 보존), `map.js`가 캔버스 색을 tokens.css에서 읽도록 변경, `index.html`이 tokens.css를 styles.css보다 먼저 링크, allowlist에 `tokens.css` 한 줄 추가. 신규 `test/test_ui_token_contracts.py` 13건과 `test_dashboard.py` 압축 시험 2건
- 증거: `PYTHONPATH=src/core;src python -m pytest src/core/test -q` 797 passed, 10 skipped (2026-09-17 Windows, 미커밋 WIP 포함 작업 트리; 이 호스트 python3에 PyYAML이 없어 `python` 3.14.5 사용). 전송량(LF 정규화): 원본 119,606 B → gzip 30,994 B. L1 압축 첫 로드 두 표면 합계 60,465 B ≤ 62,000 PASS, L2 요청 8 ≤ 10 PASS
- gate 변화: 없음. SOURCE/LOCAL GO 유지하되 LOCAL 증거를 759→797로 갱신
- 결정: D-72 (Proposed) 이행 S0·S1. 계획은 `docs/plans/2026-09-17-interface-design-implementation-design.md`
- 교훈: 계획의 S1 소스 상한(+2,400 B)을 초과했다 — 실제 +5,061 B(tokens.css 3,568 + map.js 팔레트 해석기 1,415). 압축 뒤에는 +1,884 B이고 L1 게이트는 통과하므로 되돌리지 않았으나, 단계 상한은 빗나갔음을 기록한다. 원시 색 계약 시험이 기존 결함 둘을 잡았다: `map.js`가 점유 셀과 pose 마커에 status 색 `#c4db76`을 쓰고 있었고, `styles.css`에 선언된 팔레트 밖의 둘째 팔레트(#fbbf24·#f87171·#6ee7b7·#94a3b8)와 셋째 앰버(rgba(244,186,84,·))가 섞여 있었다

## 2026-09-17 · 8fdd8d2 · feat(core): D-72 S3–S6 evidence, gauges, inventory states
- 변경: StateSnapshot.evidence, dashboard data-evidence와 teleop 게이트, 장식 제거, inventory state+reason
- 증거: `PYTHONPATH=src/core;src python -m pytest src/core/test -q` 814 passed, 12 skipped (2026-09-17 Windows)
- gate 변화: 없음. LOCAL GO 유지. ARTIFACT/DEVICE HOLD
- 결정: D-72 S3–S6. G4 HOST 조각이며 DEVICE GO가 아니다
- 교훈: 없음

## 2026-09-17 · uncommitted · feat(web): regenerate the palette from OKLCH and gate its values
- 변경: `web/tokens.css`를 OKLCH에서 생성한 값으로 교체(바탕 중립화, 경보 2색, 계열은 차가운 띠, 래스터 무채색, `--route-dim`·`--series-goal` 추가, 중복 팔레트 병합). 신규 `test/test_palette_gates.py` 10건 — 표준 라이브러리만으로 OKLCH·WCAG·적록 색약을 계산해 값 자체를 단언한다
- 증거: `PYTHONPATH=src/core;src python -m pytest src/core/test -q` 826 passed, 10 skipped (2026-09-17 Windows, 미커밋 WIP 포함 작업 트리). 팔레트 게이트 실측: 신호 색 채도 전부 >= 0.133, 주의·위험 지각 밝기 차 0.30, 색약 대비 2.05:1, 위험 면 위 잉크 5.3:1, 실선 대 파선 색약 2.06:1, 래스터 채도 <= 0.01 단조, 본문 대비 >= 4.5:1
- gate 변화: 없음. SOURCE/LOCAL GO 유지하되 LOCAL 증거를 814→826으로 갱신
- 결정: D-82 Proposed. `control`은 건드리지 않는다(D-77로 레거시 진단, concept 16 §6이 별개 파이프라인)
- 교훈: 이전 팔레트는 적록 색약 시야에서 위험 대 주의 대비가 1.07:1이었다 — 로봇 콘솔에서 주의와 위험이 구분되지 않았고, 위험이 셋 중 가장 밝았다. HSL로 보면 밝기 3pt 차이라 멀쩡해 보였고, 지각 밝기 차는 0.009였다. 색을 눈으로 고르면 이 결함은 보이지 않는다. 그리고 현대 팔레트를 그대로 베끼면 같은 함정에 빠진다 — Radix 9나 Tailwind 500이 예뻐 보이는 이유가 모든 색상을 같은 밝기에 두기 때문이고, 그 균일 밝기가 정확히 색약 분리를 파괴한다(측정치 1.22:1). 브랜드 액센트와 의미 인코딩은 다른 작업이다

## 2026-09-17 · uncommitted · feat(web): finish the D-82 pass — component tokens, typography, touch targets
- 변경: `web/tokens.css`에 컴포넌트·치수 토큰 층 추가(space 6 · radius 4 · target 3 · surface 3 · nominal 2 · button/field/flag/gauge · `--focus-ring` · `--series-secondary`)과 타이포그래피 토큰을 `styles.css`에서 이관. `styles.css` 의미 재배치 22곳(초록 참조 0), 장식 3개 제거(body gradient wash · 패널 wash · 드롭섀도), 44px 미만 터치 타겟 5곳을 `--target-secondary`로. `test_ui_token_contracts.py`에 게이트 8건 추가
- 증거: `python -m pytest src/core/test/test_ui_token_contracts.py src/core/test/test_palette_gates.py -q` 31 passed; `python -m pytest src/core/test -q` 836 passed, 1 failed, 10 skipped (2026-09-17 Windows). 실패 1건은 `test_module_criteria.py::test_c6_seam_reaches_match_the_published_triage`이며 피어 커밋 `7f674f9`의 `safety/manager.py` getattr 도달이 C6 문서 분류에 없어서다 — 이 변경과 무관하고 웹 파일을 건드리지 않는다
- gate 변화: 없음
- 결정: D-82 적용 범위를 색에서 컴포넌트·치수·글자까지 넓혔다. 전면 간격 정규화(px 243 · rem 101, 344곳)는 브라우저 회귀 시험이 CI에 없어 하지 않았다 — 남은 일로 기록한다
- 교훈: 토큰을 선언만 하고 쓰지 않으면 결함이 숨는다. 치수 토큰 13개가 사용처 0이었고, 채택하자마자 44px 미만 터치 타겟 5곳이 드러났다(설정·호스트 입력 42px, 지도 툴바 34px, 웨이포인트 32px). 폰트도 같은 종류였다 — `Aptos`는 MS Office 전용이라 Linux·macOS에서 라틴이 한글 서체로 떨어지고, `Malgun Gothic`이 없어 Windows에서는 한글이 스택 전체를 빠져나가며, 등폭에 macOS 항목이 없어 계기 숫자가 Courier로 떨어지고 있었다

## 2026-09-18 · uncommitted · feat(web): triage the console, age stale values, stop shipping em dashes
- 변경: `web/triage.js` 신규 — 서버가 이미 보내는 것(estop · battery_status · 채널별 evidence · navigation · inventory blocked)만 읽어 고장을 파생하고, `CATEGORY_ORDER` 선언 표로 정렬한다. `index.html`에 머리 자리 추가(고장이 없으면 렌더하지 않는다), `app.js`가 상태·inventory 양쪽에서 다시 분류. `dom.js`가 delayed/disconnected에 나이를 노출하고 CSS가 그린다. 배송 마크업의 em dash 45곳 제거 + `requested` 플래그로 첫 fetch 전에는 빈칸. `api/app.py` allowlist에 triage.js
- 증거: `python -m pytest src/core/test -q` 856 passed, 1 failed, 10 skipped (2026-09-18 Windows, 피어 미커밋 포함 트리). 신규 계약 시험 16건(triage 7 · margin 4 · first-paint 5). 실패 1건은 `test_c6_seam_reaches_match_the_published_triage`이며 피어 커밋 `7f674f9`의 `safety/manager.py` getattr 도달이 C6 문서 분류에 없어서다 — 이 변경은 `web/`·`api/app.py`·`test/`만 건드린다. 루트 계약 73 passed, lint 0 errors
- gate 변화: 없음
- 결정: 서버 계약을 바꾸지 않는다. 셋 다 S3·S4가 이미 배송한 데이터만 소비한다. 임계값(`stale_after_s`)은 읽지 않는다 — 피어가 커밋한 게이트(`test_dashboard.py:427-429`)가 클라이언트 접근을 금지하며, 표시와 재계산은 다르지만 그 경계를 이 세션이 일방적으로 옮기지 않았다
- 교훈: 고침과 그 고침을 지키는 시험이 같은 좁은 패턴을 인코딩하면 둘 다 같은 구멍을 갖는다. em dash를 `>—<` 모양으로만 찾아 지웠고 시험도 같은 정규식을 썼더니 `SEQ —`·`voltage —`처럼 라벨이 앞에 붙은 4곳이 고침과 시험 양쪽을 빠져나갔다 — 리뷰어가 잡았다. 시험을 "텍스트가 대시로 끝나는 id 자리"로 넓히고 수정 전 마크업에 걸어 45곳을 잡는지 확인했다. 그리고 `표본 수집 대기` 같은 문구를 처음에 같은 결함으로 봤으나, 그건 "아직 안 물어서 기다린다"를 산문으로 말한 것이라 결함이 아니다 — `상태 없음` 하나만 "물었는데 없다"로 읽혀 기존 관용구 `확인 전`에 맞췄다


## 2026-09-18 · uncommitted · fix(core): 보고 pose 의 임자를 map 프레임으로 못박는다
- 변경: `bridge/odometry.py` 에 `odom_owns_pose()`, `ros_bridge` 가 map→base TF 를 읽은 시각을 기억하고 그것이 신선하면 odom 콜백은 pose 를 건드리지 않는다. 시험 2건(`test_bridge_odometry.py`)
- 증거: 미로 주행 뒤 실측 — Gazebo 정답 (2.005, 2.181), TF `map→base` (1.969, 2.228) 로 AMCL 은 6 cm 안에 있었는데 `/api/v1/robot/pose` 는 (4.219, 4.590) 을 돌려줬다. 그 값은 `/rosy_01/odom` 과 정확히 같다. 수정 뒤 같은 시나리오에서 측위 오차 3.27 m → 0.03 m
- gate 변화: 없음
- 결정: 없음
- 교훈: pose 를 쓰는 곳이 둘이었고(odom 콜백 약 30 Hz, state 틱 10 Hz) 주기가 높은 쪽이 조용히 이겼다. 좌표를 읽는 쪽(관제 화면, 미션 판정, 대시보드)은 전부 map 프레임을 뜻하므로 그쪽이 임자다. odom 은 지역화가 없는 구성의 폴백으로만 남긴다

## 2026-09-18 · uncommitted · refactor(web): give the dashboard the spatial grammar it was designed for
- 변경: `/dashboard`를 한 문서 안의 두 뷰로 나눴다. **운용**(`.console`)은 고정 3분할(감지 264 / 관측 1fr / 조작 340)이고 페이지가 스크롤하지 않는다. **점검**(`.inspect`)은 기동 순서 수직이며 여기서만 스크롤한다. 섹션 11개를 이름·id·aria-label 하나 안 바꾸고 각 영역으로 옮겼다. 상단에 뷰 전환, 비상정지를 조작 영역 맨 위로(DOM 순서), 좁은 칸용 타이포 한 벌, `--topbar-height` 토큰 신설. `map.js`는 크기를 모르면 `undefined×undefined` 대신 "크기 미상"을 쓴다
- 증거: `python -m pytest src/core/test -q` 866 passed, 10 skipped (2026-09-18 Windows). 신규 `test_console_layout.py` 8건, `test_ui_token_contracts.py`에 위험 면 잉크 짝 게이트 1건. Playwright 1280×720 실측: pageScroll 3582→**0**, 상태줄 158→**65**, 관측 영역 363→**455**, 지도 24→**191**, 비상정지 y=832(화면 밖)→**331**
- gate 변화: 없음
- 결정: 두 문법을 한 화면에 섞지 않는다(concept 16 §4 L2). 점검 뷰의 패널은 지우지 않고 옮겼다 — 설치·정비가 쓰는 화면이고 절차 문법이 맞는 자리다
- 교훈: 시험이 전부 통과해도 화면은 안 뜰 수 있다. 기존 브라우저 시험이 **CSS를 빈 문자열로 서빙**해서 배치는 한 번도 검증된 적이 없었고, 실제로 렌더해 재 보니 네 개의 결함이 한 번에 나왔다 — `[hidden]`이 `display:flex`에 져서 숨긴 뷰가 레이아웃을 먹고 있었고(3582px 스크롤), `aspect-ratio: 5/3`이 `flex:1`과 싸워 지도를 54px로 눌렀고, `hero-copy`의 `padding: 50px`이 상태줄을 141px로 만들었고, 존재를 잊고 있던 `.page-footer`가 64px를 더하고 있었다. 그리고 내가 `#page-footer`로 셀렉터를 썼는데 그건 클래스였다 — 재보지 않았으면 못 찾았다. 마지막으로 D-82가 위험을 어두운 빨강으로 바꾼 뒤 옛 옅은 빨강에 맞춰진 어두운 잉크가 대비 2.86:1로 남아 있었다. 값만 보는 게이트는 CSS 안의 **짝**을 못 본다 — 짝을 보는 게이트를 새로 넣었다


## 2026-09-18 · uncommitted · refactor(web): float the map controls so the map gets the observe region back
- 변경: `.field-map-panel` 흐름에 있던 지도 툴바 두 줄(레이어·클릭 동작)을 `.map-stage` 안으로 옮기고 `.map-controls`로 묶어 지도 위 좌상단에 겹쳤다. 겹친 칩은 `--scrim` 바탕과 `--surface-line` 테두리로 점유 격자와 갈린다. `test_console_layout.py`에 게이트 1건
- 증거: `python -m pytest src/core/test -q` 867 passed, 10 skipped (2026-09-18 Windows). 루트 계약 921 passed, lint 0 errors. Playwright 1280×720 실측: 지도 191→**307px**(관측 영역 467 중), pageScroll 0 유지, 페이지 오류 없음
- gate 변화: 없음
- 결정: 범례와 안내 문구는 지우지 않고 흐름에 남겼다 — 읽는 것이지 조작하는 것이 아니라 겹치면 지도를 가린다. 툴바만 겹친다
- 교훈: 고정 높이 영역에서는 보조 요소가 전부 주 요소의 예산에서 나온다. 관측 영역 455px 중 지도가 191px이었던 것은 지도가 작아서가 아니라 툴바 두 줄·범례·안내가 264px을 먼저 가져갔기 때문이다. `layerRoot`가 `#field-map-panel`이라 DOM 이동 뒤에도 `[data-map-layer]`·`[data-map-click]` 질의가 그대로 걸린다는 것을 먼저 확인하고 옮겼다

## 2026-09-18 · uncommitted · refactor(web): rewrite the surface rules as one design system
- 변경: `web/styles.css`를 처음부터 다시 썼다(856→약 700줄). 카드 기반 원본 위에 콘솔 패치를 15겹 얹은 구조를 버리고, 콘솔 규칙을 `.console .x` 덮어쓰기가 아니라 제자리에서 정의한다 — 콘솔이 기본형이고 카드 대접은 `.inspect .panel`에만 준다. 별칭 층(`--ink`·`--line`·`--signal-*` 8개) 삭제, `.panel::before` 색 띠 5종과 등장 애니메이션 삭제, 상태 어휘를 하나로 통합(뱃지·기계 태그·모드 칩·`[data-status]`·이벤트 심각도가 같은 셋을 쓴다). `tokens.css`에 글자 계단 `--text-micro|label|body|value|title`과 `--track-label` 신설. 마크업: 비상정지가 제목 `<div>` 안에 중첩돼 있던 것을 꺼내고, 범례·안내를 `.map-stage` 위 오버레이로 이동. 게이트 3건 추가
- 증거: `python -m pytest src/core/test -q` 870 passed, 10 skipped. 루트 계약 923 passed, lint 0 errors. Playwright 실측 — 1280×720: 지도 307→**469px**, 상태줄 44px, pageScroll 0. 900×700: 지도 388×457, 가로 넘침 0. 390×844: 세로로 쌓고 스크롤, 오류 없음. 새 게이트를 이전 stylesheet에 걸면 별칭 8개·계단 밖 간격 118곳(값 53가지)·계단 밖 글자 95곳(68가지)이 잡힌다
- gate 변화: 없음
- 결정: 좁은 화면(≤1080px)에서도 영역 셋의 **자리는 바꾸지 않는다**. 조작을 아래 줄로 돌려 봤더니 그 칸이 제 내용만큼(412px) 가져가 지도가 37px로 눌렸다 — 공간 문법을 버리고 얻는 것이 없었다. 레일 폭만 좁힌다. 휴대폰(≤720px)은 고정 프레임이라는 전제 자체가 없으므로 세로로 쌓고 스크롤을 허용한다
- 교훈: "카드처럼 보인다"는 취향 문제가 아니라 구조가 그렇게 시켜서였다. 제목이 세 층(영역 머리·패널 제목·소제목)이고 층마다 상자를 만들면 화면이 목차로 읽힌다. 제목을 **줄**로 바꾸고(작은 대문자 라벨 + 이어지는 실선 + 오른쪽 기계 값) 값 격자를 1px 간격의 실선 격자로 짜자 같은 데이터가 계기판으로 읽혔다. 그리고 덮어쓰기로 쌓은 규칙은 언제나 원본을 이긴 척만 한다 — `.region .panel { border: 0 }`으로 카드를 지워도 원본의 카드 여백·카드 리듬·카드 타이포가 계속 밀고 올라와 패치가 한 겹씩 늘었다. 원본을 고치는 것이 패치를 얹는 것보다 짧았다

## 2026-09-18 · uncommitted · feat(core): scan/imu/range use sensor-data QoS (D-119)

- 변경: ros_bridge LaserScan/Imu/Range 구독이 qos_profile_sensor_data. RELIABLE depth 10 과 센서 BEST_EFFORT 가 어긋나지 않게.
- 증거: `python -m pytest src/core/test/test_bridge_timers.py test/test_dds_rmw_contracts.py -q`
- gate 변화: 없음. DEVICE PARKED

## 2026-09-18 · uncommitted · feat(core): apply Cyclone before rclpy.init (D-121)

- 변경: `apply_cyclone_rmw` 를 `rclpy.init` 앞에. 스냅샷 `rmw` 필드와 대시보드 표시. FastDDS 기동 거절.
- 증거: `python -m pytest src/core/test/test_rmw.py src/core/test/test_ros_graph_monitor.py src/core/test/test_dashboard.py -q`
- gate 변화: 없음. DEVICE PARKED

## 2026-09-18 · uncommitted · feat(core): correct foreign RMW on next CORE start (D-122)

- 변경: FastDDS/기타 RMW 는 거절하지 않고 Cyclone으로 고친 뒤 init. 커널 reboot 없음.
- 증거: `python -m pytest src/core/test/test_rmw.py -q`
- gate 변화: 없음. DEVICE PARKED

## 2026-09-18 · uncommitted · feat(core): persist Cyclone then Host Agent reboot (D-123)

- 변경: POST /api/v1/system/dds/cyclone. 오버레이 dds.rmw 저장 후 Host Agent system.reboot. 대시보드 확인 버튼.
- 증거: `python -m pytest src/core/test/test_rmw.py src/core/test/test_dashboard.py src/core/test/test_host_cards.py -q`
- gate 변화: 없음. DEVICE PARKED

## 2026-09-18 · uncommitted · feat(core): dashboard AP toggle and Wi-Fi connect (D-124)

- 변경: 네트워크 카드에 AP 켜기/끄기와 SSID·암호 연결. POST /host/network/mode, /connect. PSK는 GET/응답에 안 채움
- 증거: `python -m pytest src/core/test/test_host_cards.py src/core/test/test_dashboard.py -q`
- gate 변화: 없음. DEVICE PARKED

## 2026-09-20 · uncommitted · feat(core): person advisory caps linear speed (SAF-006)

- 변경: `core_features/safety/manager.py`에 `PersonAdvisory`(present/confidence/observed_at/max_age) + `set_person_advisory`. `clip()`이 신선한 자문에만 전진 상한 0.05 m/s 적용(낮추기만, 선회율 불변). stale/부재/해제는 프로필 복귀. e-stop 경로와 분리
- 증거: `python -m pytest src/core/core/test/test_core_logic.py -q` 27 passed (신규 8건). core 전체 901 passed·10 skipped. flake8 신규 구간 무경고
- gate 변화: 없음. 자문 주입원(YOLO evidence 파이프)은 vision 슬라이스 몫 — 정지 거리 확대는 CommandPolicy 관측 연결 후

## 2026-09-20 · uncommitted · feat(core): DetectionEvidence schema and person injection (D-137 T2)

- 변경: `core_common/protocol/detections.py` 신규 — Detection(정규화 박스)/DetectionEvidence(revision+seq+입력 제원), fresh 300 ms, gap_after, of_label. `safety/manager.py`에 `person_advisory_from` 주입 고리. API Ref §6.1.1 + v1.9 (envelope 1.0 유지)
- 증거: `test_protocol_schemas.py` 15 passed (신규 6건), `test_core_logic.py` 주입 4건, core 전체 919 passed·10 skipped
- gate 변화: 없음. revision 게이트(known-model registry)는 vision 슬라이스 몫

## 2026-09-20 · uncommitted · feat(core): known-model registry gates revisions (D-137 T3)

- 변경: `safety/manager.py`에 `ModelSpec`+`ModelRegistry`(revision+입력 제원 명부, 비어 있으면 fail-closed). `person_advisory_from`에 `registry` 옵션 — 모르는 revision·어긋난 제원은 None. 없으면 옛 동작
- 증거: `test_core_logic.py` 5건 신규(적색→녹색). full suite 타 세션 머지 포함 927 passed·11 skipped
- gate 변화: 없음. D-137 소프트웨어 계약 닫힘 — 남은 것은 vision 실측과 실물 게이트

## 2026-09-20 · uncommitted · feat(vision): D-136 T1 boundary contracts

- 변경: `test_vision_boundaries.py` 2건 (AST import walk + 코드 토큰, 테스트 픽스처 제외, mutation-proven). fleet `test_no_video_relay.py` 2건 (import walk + 라우트 열거, vacuous 방지)
- 증거: 4 passed. core 전체 929 passed·11 skipped, fleet 332 passed·5 skipped
- gate 변화: 없음

## 2026-09-21 · uncommitted · feat(core): gate SLAM mapping and persist maps safely (D-144)

- 변경: runtime backend selects localization or SLAM readiness; mapping start now fails closed until that graph is ready. SaveMap accepts only a safe basename and resolves it below `/var/lib/rosy/maps`, then hashes the generated PGM for the map ID.
- 증거: root plus CORE suite `2018 passed, 24 skipped`; focused readiness, save-map, API, and commissioning contracts pass.
- gate 변화: SOURCE/LOCAL evidence refreshed. ROS-SIM/ARTIFACT/DEVICE remain HOLD pending their actual environments.
- 결정: D-144.
- 교훈: capability advertisement, lifecycle readiness, filesystem scope, and commissioning hashes must describe the same selected backend.

## 2026-09-21 · uncommitted · test(core): make ROS-installed native ARM64 tests deterministic

- 변경: the output-graph fixture now supplies the bridge readiness field explicitly, and the missing-provider test patches entry-point discovery instead of relying on the control package being absent from the environment.
- 증거: native arm64 run 35539577735 reproduced 10 `_readiness` fixture failures and one installed-provider failure after the source build succeeded. Corrected focused tests pass locally; combined root+CORE suite is `2021 passed, 24 skipped` and the native run is repeated after integration.
- gate 변화: none until the repeated native job is green.
- 교훈: a missing-optional-package contract must isolate discovery; installing the optional package must not invert the test's premise.

## 2026-09-21 · uncommitted · refactor(core_api_web): route v1 domain types through api.deps
- 변경: core_api_web v1 라우터 9개 모듈의 core_features 직접 import 12건을 api/deps.py 재수출 면으로 교체(Mode, NavigationError, Dock*, LineFollowMode, valid_costmap_scope, worst, SwarmError, Waypoint). core/test/test_v1_import_boundary.py 2건 추가 — v1 의 core_features 직접 import 금지 + deps 가 타입 면을 소유하는지 검사.
- 증거: 결합도 평가(2026-09-19) §7-5 — features 재조정의 전파 반경이 deps 에서 멈춘다. 텍스트 검사라 rclpy/fastapi 불필요.
- gate 변화: 없음

## 2026-09-21 · uncommitted · test(safety): D-137 T1 sequence contracts, host pytest 4

- 변경: `test_core_logic.py`에 `TestD137SequenceContract` 신규 — (1) person 자문은 clip 상한만 낮추고 (0,0) 정지를 못 만든다, (2) 자문은 estop 플래그를 못 만지고(건다/떼는 것 모두 해금 아님), (3) e-stop 진입(`trigger_estop`)·해금(`release`) 몸통에 vision 토큰 없음 소스 스캔 + 자문이 살아 있어도 연산자 해금 가능, (4) `src/**` 생산 코드에 `vision/detections` 발행자 0명 — rosy-vision 착지 시 화이트리스트 단일 항목으로 열리는 게이트. `_function_body` 헬퍼로 메서드 몸통만 스캔
- 증거: 신규 4건 녹색 + 변이 증명 3건 — clip 단독 정지 삽입 → (1) 적색, release 자문 조회 삽입 → (3) 적색, 발행 문자열 심기 → (4) 적색, 각 원복 후 녹색. 원복은 git diff 공백으로 확인. core 전체 976 passed·11 skipped (2026-09-21 Windows, PYTHONPATH)
- gate 변화: 없음. T1 요건(계약 4건) 충족 — 남은 것은 T4(ROS-SIM 거짓음성 주입·버스트 트리거 게이트)와 T5(DEVICE 실츱)뿐. D-137 Status 전환은 계획서 종료 조건에 따름

## 2026-09-21 · uncommitted · feat(safety): PersonAdvisoryFeed wire ingest seam (D-137 T4)

- 변경: `safety/manager.py`에 `PersonAdvisoryFeed` 신규 — 와이어 패킷 1건을 자문 좌석에 닿게 하는 유일한 유입점(ROS 구독자 착지 시 core.bridge가 연결). `ingest()`는 model_validate → person_advisory_from(registry 게이트) → set/clear이고, 어떤 입력에도 예외로 죽지 않는다(구독자 콜백 방어 — 검증 텍스트는 밖으로 새지 않고 사유만). broken/stale/빈 검출/seq 점프는 전부 자문 해제("못 본 것"으로 상한을 유지하는 쪽이 자문의 방향이 아니다), e-stop은 어느 경로로도 안 건드린다
- 증거: `TestPersonAdvisoryFeed` 4건 신규 녹색 + 변이 증명(`_clear` 해제 누락 변이 → stale 잔류로 clip 적색 → 원복 녹색). 발견 1건: pydantic lax가 모델 인스턴스는 재검증 없이 통과시켜 변조 confidence가 PersonAdvisory까지 도달 — ingest를 total하게 만들어 흡수하고, 시험은 와이어 실제(dict) 경로로 고정. 회귀: Windows core 980 passed·11 skipped, WSL Jazzy 979 passed + cv2 4.6 환경 실패 1건(pre-existing, 본 변경 무관). flake8 신규 블록 무경고(E128 2건 기존 라인)
- gate 변화: 없음. T4 남은 것은 ROS-SIM fault-injection(구독 배선 = rosy-vision 착지 시, 호출점은 이 시임)과 FP 폭주율 수치 합의. 계획서에 진행 기록 섹션 추가

## 2026-09-21 · uncommitted · feat(core): gate line driving with supervised traffic policy (D-151)

- 변경: ROS-free traffic policy와 원자적 bridge gate, 교통 상태/API, 정지 상태 전용 stage/apply, capability-gated simulation signal, 관제 정책 카드를 추가했다. CORE Command Manager가 계속 유일한 최종 `cmd_vel` 소유자다.
- 안전: stale/conflict/scene mismatch는 `HOLD`와 zero command이며, 관제는 이 fail-closed 판단을 우회할 수 없다.
- 증거: 정책·API·bridge·dashboard focused tests와 실제 Chromium stage→apply 흐름이 통과했다. 첫 캡처에서 발견한 test-stub state 유실과 거짓 양성 문자열 검사를 수정해 성공 문구를 정확히 단언한다.
- gate 변화: SOURCE/LOCAL 증거만 추가. 실제 ROS graph와 장치·현장 gate는 HOLD/PARKED 유지.
- 결정: D-151.

## 2026-09-21 · uncommitted · fix(core): route traffic type through api.deps (D-147, D-151)

- 변경: 최신 main의 v1 import 경계에 맞춰 traffic router의 `Mode`를 `core_api_web.api.deps` 재수출 면에서 가져오도록 했다.
- 증거: `test_v1_import_boundary.py`와 traffic API 8건 통과, focused flake8 0 errors.
- gate 변화: 없음. rebase 통합 경계 수정이다.
- 결정: D-147의 API 결합도 경계와 D-151의 traffic API를 함께 지킨다.

## 2026-09-21 · uncommitted · feat(core): serve a bounded authenticated camera preview (D-152)

- Review hardening: status/frame sequence binding, per-token 400 ms pulls, capture-clock epoch reset, BEST_EFFORT depth 1, and browser lifecycle cancellation.
- Latest evidence: integrated CORE `1026 passed, 12 skipped`; Chromium camera suite `6 passed`; deterministic rate-limit and policy-budget contracts pass.

- 변경: `camera/preview/compressed`의 최신 JPEG 한 장만 보관하고 Viewer 인증 status/frame API와 지도 위 dashboard panel을 추가했다. 크기·JPEG marker·시각 역행·2초 stale을 거부하며 JPEG 재압축은 `Content-Encoding: identity`로 차단한다.
- 증거: CORE 전체 회귀와 실제 Chromium dashboard 흐름을 통합 main 병합 상태에서 재검증했다.
- gate 변화: SOURCE/LOCAL 증거만 추가. Windows HOST-SIM frame은 실제 Gazebo/Pinky frame이 아니므로 ROS-SIM/DEVICE/FIELD는 승격하지 않는다.
- 결정: D-152. 이 예외는 MJPEG/녹화/raw/Fleet/상태 WebSocket으로 확장하지 않는다.

## 2026-09-21 · uncommitted · feat(bridge): detection_evidence subscription + ROS graph injection test (D-137 T4)

- 변경: `ros_bridge.py`에 `detection_evidence` 구독(String JSON, D-136 §2 분리 채널) + `_on_detection_evidence` 한 줄 콜백(파싱 실패는 None으로 피드 위임) + 노드 시계 `bind_clock`. `services.py`가 `PersonAdvisoryFeed`를 소유(advisory_feed 필드). `test_bridge_timers.py` 핀 갱신(구독 20건) + RecordingNode 시계에 nanoseconds. `test_advisory_feed_ros.py` 신규 — rclpy 그래프 주입 시험(ROS 없는 호스트는 모듈 스킵): 발행→좌석 캡, 깨진 패킷→프로필 복귀, e-stop 불변
- 발견·수정(WSL 그래프 시험이 잡은 실결함): 좌석 `observed_at`이 ROS epoch인데 `clip()`은 monotonic으로 판정 — 기준 어긋남으로 자문이 한 번도 살지 못했다. `PersonAdvisoryFeed`에 `seat_clock`을 두고 캡처 시 **나이만** 좌석 시계로 옮기는 TrackedEvidence 패턴으로 수정. DDS 매칭 전 발행 유실도 재발행 루프로 방어
- 증거: Windows core 1026 passed·12 skipped. WSL Jazzy 실 rclpy 그래프 10 passed(주입 1 + 브리지 구조 핀 9) — 러너 `interfaces` 패키지 colcon 빌드 + `LD_LIBRARY_PATH`/`AMENT_PREFIX_PATH` 직결(오버레이 setup이 PYTHONPATH를 덮어쓰는 문제 우회). 병합 충돌 12파일은 병렬 세션이 내용 해결 중 — 본 변경은 그 위에 미커밋
- gate 변화: 없음. T4의 와이어 구간은 닫힘 — 남은 것은 Gazebo 상 주입 실측(ROS-SIM), FP 폭주율 수치 합의, T5 DEVICE

## 2026-09-21 · uncommitted · test(safety): D-137 T4 fault-injection composition (metric stop + broken vision)

- 변경: `test_core_logic.py`에 `TestD137MetricStopComposition` 신규 — Control 정책 obstacle 정지(bind_control_policy, 출력 0) 위에서 사람 자문 좌석이 살아 있어도 정지 유지, 깨진 패킷 후 자문 해제·프로필 복귀로도 정지 유지, vision이 만든 정지·해제·e-stop 모두 없음을 단언. vision에는 정책 입력 경로가 아예 없는 구조적 분리의 증명 — T4 "깨진 영상 + LiDAR 장애물 → 정지 유지"의 순수 합성 증명(rclpy 불요)
- 증거: Windows 1027 passed·12 skipped, WSL Jazzy 1038 passed(cv2 4.6 `generateImageMarker` 환경 실패 1건 — 기존 불변). 계획서 진행 기록 갱신
- gate 변화: 없음. 참고: 장애물 정지는 `evaluate_candidate`가 None(policy_stop)이 아니라 limit 경로의 (0, 0) 출력으로 온다 — 시험이 실제 계약을 따르도록 단언 수정

## 2026-09-21 · uncommitted · fix(web): graph topics no longer spend the warning colour (D-153 session 8, F-08)

- 변경: `styles.css`의 `.graph-topic` 채움을 `--status-warn`에서 `--series-primary`로 옮겼다 — 정상 ROS 그래프의 토픽 마커가 항상 경보 색으로 그려져 D-82 "화면에 따뜻한 것이 보이면 언제나 무언가 잘못된 것이다"를 위반했다. 토픽은 series 정체성(§6 차가운 대역)이고 노드와의 구분은 형태(사각·원)가 이미 담당한다
- 증거: `test_dashboard_browser.py` runtime-normal 상태에 행동 게이트 신규 — 캔버스 fillStyle 정규화로 토픽 계산색과 `--status-warn` 계산색을 비교. 변이 증명: warn 되돌림 → 적색, 복원 → 녹색. 첫 게이트는 문자열 형식 불일치로 항상 통과하는 동어반복이어서 폐기·재작성했다. 대시보드 브라우저 18 passed, console_layout·token·core_api_web 43 passed
- gate 변화: 없음
- 결정: `.graph-node.foreign`의 crit 사용은 유지 — 외부 참가자 출현은 경보 의미다. D-153 회차8 F-08

## 2026-09-21 · uncommitted · fix(web): inspect order follows §7.2 bring-up order (D-153 session 10, F-10)

- 변경: `index.html` — release-card·commissioning-card를 host-panel(네트워크)
  안에서 ROS 그래프 섹션 뒤로 이동(자체 `.host-card-grid`). §7.2 순서표
  "network → DDS → graph → release → commissioning"과 정렬.
  `test_console_layout.py`에 `test_the_inspect_order_follows_bringup_order`
  게이트 신설(패널 존재만 보던 게이트에 순서가 없어 표류했음)
- 증거: 이동 안전성 — `.host-card` CSS 클래스 스코핑·app.js의 host-panel/
  host-card 컨테이너 참조 0(전부 id 갱신)·`data-step` 1→(그래프)→2→3 읽기
  순서 정합. 변이 증명: 게이트 순서 뒤집기 → 적색 → 복원 → 녹색.
  console_layout **10 passed**, host_cards·dashboard 62 passed 합산, 브라우저
  19+10 passed. 점검 뷰 캡처 재생성(5841px — 절차 스크롤 연장은 §7.2 합법)
- gate 변화: 없음
- 결정: 커미셔닝·릴리즈는 그래프 건강에 의존하는 단계 — 법 순서가 의존
  순서다. D-153 회차10 F-10
- 교훈: "존재" 게이트는 순서를 못 지킨다 — 순서가 법 계약이면 순서 게이트를
  별도로 세운다

## 2026-09-21 · uncommitted · feat(core): consume server-judged evidence and expose HITL handoff

- 변경: `HeadlessState`가 브라우저 시계 계산 없이 서버 evidence enum을 소비한다. HITL JSON 요청은 ROS-free parser에서 검증하고, 상태·LCD 얼굴·대시보드 지원 요청으로 전달한다. 버튼은 자동 주행 명령을 내리지 않고 기존 저속 teleop 영역으로만 이동한다.
- 증거: dashboard/headless/HITL/bridge/token/package focused 95 passed, `node --check`와 Python compile 통과.
- gate 변화: SOURCE/LOCAL GO 유지. 실제 ROS subscription과 Pinky LCD/teleop DEVICE 증거는 HOLD다.
- 결정: D-999, D-157.

## 2026-09-21 · 3747199 · test(core): ROS-SIM boot smoke 재실행 — ROS-SIM HOLD 해소

- 변경: 없음(검증과 기록만). WSL2 ROS 2 Jazzy에서 현재 트리를 `colcon build --symlink-install --packages-up-to core`(7패키지, 22.5s)로 빌드하고 `ros2 run core core` 부트 스모크를 재실행했다(CI와 동일 형식, identity `ROSY_ROBOT_NUMBER=1` → `rosy_01`/domain 41).
- 증거: `/core` 노드 발견, `ros_bridge ready (cmd_vel sole publisher @50Hz)`, `/cmd_vel` publisher count=1(`/nav_cmd_vel`은 publisher 0/구독 1 — Nav2 출력은 CORE 구독으로 귀속), `/api/v1` 200, `/dashboard` 200, `/robot/state` 401(토큰 계약 정상), SIGTERM 후 깨끗한 종료. `docs/validation/ros-sim-core-2026-09-21/result.md` + evidence 14파일.
- gate 변화: ROS-SIM HOLD→GO. 2026-09-20 `AttributeError(self.core_common)` 부팅 결함(9b77daa 유입, 6ff2cb8 수정)이 현재 트리에서 미재현 확인. ARTIFACT/DEVICE는 HOLD 유지.
- 결정: core ROS-SIM은 부트 스모크+ROS 출력+API로 판정한다. Gazebo 리그·Nav2 스택 실행은 gz_sim·navigation 게이트 범위다.

## 2026-09-22 · uncommitted · feat(core): D-162 T5 scene context additive 수용 (observability 전용)

- 변경: `RoadEvidence`에 선택 `context_id`/`context_confidence`/`context_profile_revision` 필드(all-or-none 검증, [0,1] 경계), `translate.road_evidence`가 additive `context` 매핑을 엄격 디코딩(부재 시 전부 None, `null`/부분 키는 거부), `ros_bridge._on_road_observation`이 sensor snapshot에 `context_id`/`context_profile_revision`을 표시. 정책 판정(`_verdict`)은 변경 없음 — 장면은 설정이지 권한이 아니다(D-162).
- 증거: `core/core/test` 1054 passed, 12 skipped (2026-09-22 Windows). traffic policy/bridge contract/traffic api/bridge translate/bridge timers 집중 시험 78 passed.
- gate 변화: LOCAL GO 유지(evidence 갱신). ROS-SIM GO→HOLD — 본 변경이 ros_bridge를 만졌으므로 2026-09-21 부트 스모크는 현재 트리 증거가 아니다. 동일 절차 재실행 필요.
- 결정: 프로토콜 스키마(`TrafficPolicyStatus`)는 건드리지 않고 sensor snapshot observability로만 노출했다. 상태 스키마 확장은 별도 슬라이스에서 D-18과 함께.
- 발견(미수정, 본 변경 스코프 밖): `ros_bridge.py`에 `import json`이 없다 — road/observation 콜백의 `json.loads`와 except 절의 `json.JSONDecodeError`가 첫 메시지에서 NameError를 낸다. 별도 결함 처리 필요.

## 2026-09-22 · uncommitted · fix(bridge): import json 결함 수정 + AST 계약 시험, ROS-SIM 재실행 절차문

- 변경: `ros_bridge.py`에 `import json` 추가 — 전 항 발견 결함(road/observation 콜백의 `json.loads`와 except 절 `json.JSONDecodeError`가 임포트 없이 사용됨)을 수정한다. `test_executor_contracts.py`에 `test_bridge_json_calls_are_backed_by_a_module_import` 추가 — 정적 AST로 json 사용↔임포트를 결합해 재발을 막는다(host pytest는 이 모듈을 임포트할 수 없으므로 NameError는 실기 콜백에서만 터진다). `docs/validation/ros-sim-core-2026-09-22/README.md` 재실행 절차 작성 — 2026-09-21 방식에 road/observation 유효+malformed 프로브 2건을 추가했다. malformed 발행이 except 절의 `json.JSONDecodeError` 평가를 강제하므로 이 결함의 재발을 ROS-SIM에서 잡는다.
- 증거: `python -m pytest core/core/test/test_executor_contracts.py -q` 4 passed. flake8 F821(`json` undefined) 소거 확인.
- gate 변화: 없음(ROS-SIM HOLD 유지 — 절차문은 실행 전). ROS-SIM gate에 절차문 경로를 cmd로 기록.
- 결정: 계약 시험은 test_executor_contracts.py의 기존 정적 AST 패턴을 따르고, 구조 전용 stub인 test_bridge_timers.py에는 넣지 않는다(bridge/AGENTS.md 규칙).

## 2026-09-22 · uncommitted · test(core): ROS-SIM 재실행 PASS — ROS-SIM 복원 (D-162 T5 이후 트리)

- 변경: 없음(검증과 기록만). WSL2 Jazzy에서 `git archive HEAD`(89c1d11) 스냅샷을 빌드(`--packages-up-to core`, 7패키지)하고 부트 스모크 + road/observation 회귀 프로브를 실행했다. 절차·판정 기준은 `docs/validation/ros-sim-core-2026-09-22/README.md`.
- 증거: `/core` 기동, `/cmd_vel` publisher 1(단일 발행자), API 200·대시보드 200·/robot/state 401, **유효 context payload와 malformed JSON 모두 NameError 없이 수신**(구독 확인 Subscription count 1, `import json` 수정 검증), SIGTERM 후 `core shutting down`. evidence 13파일.
- gate 변화: ROS-SIM HOLD→GO. ARTIFACT/DEVICE는 HOLD 유지.
- 결정: malformed payload 프로브를 표준 절차에 포함한다 — except 절 평가 경로를 ROS-SIM에서 직접 검증하는 유일한 방법이다.

## 2026-09-22 · uncommitted · feat(core): SAF-002 워치독 만료를 safety.watchdog 로 알린다 — 정지가 바퀴에 닿은 뒤에

- 변경: `CommandManager`가 MANUAL teleop 세션의 워치독 만료를 `select_output`에서 기록만 하고(`_note_watchdog_lapse`), `announce_pending`이 `safety.watchdog`(warning, `{timeout_ms}`)을 세션당 한 번 낸다. 세션은 번호로 센다(불리언 래치는 뒤늦은 쓰기가 새 세션을 삼킨다). E-Stop·정책 정지(`_clear_for_stop`)는 이미 알려진 사유라 밀린 알림을 버린다. 50 Hz 한 주기의 순서(고르기 → readiness HOLD면 0 → 바퀴 → 절전 관측·알림)는 ROS 없는 `bridge/cmd_vel.py::cmd_vel_cycle`로 떼어냈고 `ros_bridge._publish_cmd_vel`은 그것을 한 번 부른다(`_send_twist`가 유일한 `cmd_vel_pub.publish`). 보관 브랜치 `archive/2026-09-22/fix/event-catalogue-drift`(d73606d·4c1ea99)를 D-125/D-126 트리로 이식한 것이다.
- 증거: `test_teleop_watchdog_event.py`(12)·`test_cmd_vel_cycle.py`(13) 25 passed; manager 변경을 되돌리면 워치독 시험 12 failed. `src/core/core/test` 1081 passed, 12 skipped (2026-09-22 Windows, catalogue 시험 제외).
- gate 변화: ROS-SIM GO→HOLD — `ros_bridge.py`의 cmd_vel 경로를 만졌으므로 2026-09-22 부트 스모크는 현재 트리 증거가 아니다. 동일 절차 재실행 필요.
- 결정: 알림은 바퀴 뒤에 온다. EventBus는 구독자를 동기로 부르고 감사 로그 싱크가 그중 하나라, 앞에 두면 SAF-002 정지가 그만큼 늦게 나간다. readiness HOLD 판정은 기존대로 브리지가 주입한 게이트를 쓴다(동작 변경 없음).

## 2026-09-22 · uncommitted · fix(core): config.changed·swarm.aborted 가 계약대로 warning 을 싣는다

- 변경: `core_api_web` 의 `config.changed` 발행 5곳(safety.limits, robot.identity, auth.tokens 추가·삭제, dds.rmw)과 `core_features.swarm.manager` 의 `swarm.aborted` 에 `severity="warning"` 을 명시했다. 지금까지는 기본값 info 로 나가 §8 카탈로그(warning)와 어긋났다. 보관 브랜치 `archive/2026-09-22/fix/event-catalogue-drift` 의 심각도 정정을 D-125/D-126 트리로 이식.
- 증거: `src/core/core/test` 전체 통과(아래 catalogue 가드 커밋의 심각도 검사가 이 둘을 고정한다).
- gate 변화: 없음.
- 결정: 설정 변경과 군집 중단은 소비자가 경보를 거는 대상이다 — 문서가 아니라 코드를 고쳤다.

## 2026-09-22 · uncommitted · test(core): §8 이벤트 카탈로그 드리프트 가드 — 발행 지점에서 읽는다

- 변경: `test/test_event_catalogue.py` 추가. CORE 다섯 패키지(core, core_common, core_events, core_features, core_api_web)의 AST 에서 발행 지점(`publish`/`_emit`/수집 튜플)의 이름·심각도·payload 키를 읽어 §8 표와 양방향으로 대조한다. 이름을 정적으로 못 읽는 자리는 통과가 아니라 실패, 중계 함수 4개(`_emit`/`_emit_all`)는 몸통 지문으로만 면제. 보관 브랜치 `archive/2026-09-22/fix/event-catalogue-drift`(7b2384f…f5df9e1 의 최종판)를 이식하면서 새 자리 두 가지를 배웠다 — `svc.vision.publish(bytes…)` 카메라 프레임(소유자+모양으로 제외), `_wire_*(value, "lane.visible")` 필드 경로 라벨; CAP-001/concept id 는 `core_common.domain` 표에서 읽는다.
- 증거: 문서 정정 전 7 failed(미문서 19종, 키 8건, 심각도 7건, `safety.watchdog`·`nav.blocked` 미발행), 정정 후 73 passed. `src/core/core/test` 전체 통과(커밋 메시지 참조).
- gate 변화: 없음.
- 결정: 손으로 관리하는 이벤트 목록을 두지 않는다. 예외 목록(`not_events`)은 발행 이름과 겹치면 실패한다.

## 2026-09-22 · uncommitted · fix(core): 리뷰 반영 — 버전 무관 중계 지문, MANUAL 이탈 시 teleop 폐기, 만료 기록의 세션 경합

- 변경: (1) `test_event_catalogue.py` 의 `fingerprint()` 가 `ast.dump`(3.13 에서 출력이 바뀜) 대신 docstring 을 뺀 `ast.unparse` 를 해시한다 — 3.14 에서 고정한 값이 CI·Pi(3.12)에서 네 중계를 모두 "바뀜"으로 빨갛게 만들던 결함. `PINNED_RELAYS` 재고정(docking `15ae9dd72fa20f0b`, safety `e0aca301e45601ff`, battery `fdb020d71a91a47a`, power `da516d1499355bc6`) + 고정 스니펫 지문 시험. (2) `CommandManager.select_output` 이 E-Stop·EMERGENCY·readiness HOLD·MANUAL 이탈에서 쥐고 있던 teleop 을 버리고 그 세션을 알림 완료로 적는다(`_drop_manual_session`, `_clear_for_stop` 도 이것을 쓴다). MANUAL→IDLE→MANUAL 에서 나던 거짓 `safety.watchdog` 을 없애고, **기존 결함이던 500 ms 안 복귀 시 옛 teleop 명령 재생(stale replay)도 함께 없앤다**. (3) 만료 기록은 판정 **전에** 읽은 세션 번호를 쓴다(`_note_watchdog_lapse(session)`); `teleop()` 은 워치독을 명령보다 먼저 되살린다. (4) `test_cmd_vel_cycle.py` 시험 이름 정리.
- 증거: 신규 3 시험(모드 왕복, HOLD, 판정↔기록 사이 teleop)은 수정 전 manager 에서 3 failed, 수정 후 통과. `src/core/core/test`: Python 3.14 와 `uv run --python 3.12` 양쪽 통과(수치는 커밋 메시지). 앞 항목의 catalogue "73 passed" 는 오기다 — 당시 실제 71 passed, 지문 시험 추가 후 72.
- gate 변화: 없음(ROS-SIM HOLD 유지 — cmd_vel 경로 재검증 필요는 그대로).
- 결정: MANUAL 을 벗어난 teleop 은 조종이 아니다. `manual_active` 도 이탈 후 첫 틱부터 거짓이 된다(도킹 복귀 정책은 이제 IDLE 로 빠진 로봇을 운영자 조종 중으로 보지 않는다).

## 2026-09-22 · uncommitted · fix(core): 만료 뒤 끼어든 teleop 이 옛 명령을 한 틱 되살리지 않게 한다

- 변경: 재리뷰가 찾은 main 대비 회귀(8820ce2). 만료 뒤 `teleop(0,0)` 이 틱과 엇갈리면 한 20 ms 틱이 만료된 세션의 0 아닌 명령을 다시 바퀴로 보냈다 — (1) 틱이 명령을 판정 전에 읽어 두고 그 사이 teleop 이 워치독을 되살린 경우, (2) `teleop()` 이 워치독을 명령보다 먼저 되살려 그 사이 틱이 새 워치독·옛 명령을 읽은 경우. `teleop()` 순서를 main 대로(명령 → epoch → 워치독 → 세션) 되돌리고, `select_output` 은 세션 번호만 판정 전에 읽고 명령은 판정 **뒤에** 다시 읽는다.
- 증거: 결정적 끼어들기 시험 2건(`expired`/`refresh` 가로채기로 teleop(0,0) 삽입)이 8820ce2 manager 에서 2 failed, 수정 후 통과. 재현 스크립트(race.py) 두 경우 모두 0 송신. 전체 수치는 커밋 메시지.
- gate 변화: 없음(ROS-SIM HOLD 유지).
- 결정: 세션 번호(알림 귀속)와 명령(바퀴 출력)은 읽는 시점이 다르다 — 번호는 판정 전, 명령은 판정 후.

## 2026-09-22 · uncommitted · fix(core_events): 감사 로그 쓰기 비용·정전 손실·정리 실패 집계 (archive 브랜치 이식)

- 변경: `core_events/events/audit.py` `FileAuditLog` — 이벤트마다 파일 전체를 읽고 재작성하던 것을 덧붙이기 전용으로 바꾸고, 정리는 쓰기 경로에서 최대 한 시간에 한 번 락 밖에서 파싱해 원본 바이트를 그대로 남긴다(스냅샷 이후 덧붙은 꼬리는 `st_dev`/`st_ino` 신원을 확인한 뒤 이어 붙임, 임시 파일 + `os.replace`). `history()` 는 더 이상 파일을 재작성하지 않고 메모리에서 보존 기간을 거른다. 정전으로 잘린 마지막 줄 뒤 첫 이벤트를 삼키지 않도록 개행 종결 여부를 프로세스당 한 번 확인(쓰기 실패 시 캐시 무효화), 잘린 UTF-8 꼬리는 `errors="replace"` 로 읽어 `/logs/audit` 500 을 막는다. 읽기와 정리가 같은 규칙(`_raw_lines`, 바이트 `strip`)으로 줄을 나눈다. Windows CRLF 변환을 막는 `newline=""`. 새 `health()` — 연속/누적 쓰기 실패, 정리 실패, 정리 건너뜀과 채널별 마지막 사유. 원본: `archive/2026-09-22/fix/audit-log-write-cost` (470ce7b..f04e430, 2026-09-07), 재구조화(D-125/D-126) 이후 경로로 재구현.
- 증거: 이식한 `test_audit.py` 47 시험 중 30 건이 수정 전 main 코드에서 실패, 수정 후 47 passed (2026-09-22 Windows).
- gate 변화: 없음(LOCAL). 쓰기 경로는 50 Hz cmd_vel 타이머 위에서 불리므로 ROS-SIM/DEVICE 증거는 아니다.
- 결정: fsync 하지 않는다(매 이벤트 SD 카드 fsync 비용이 원래 문제를 되살린다). 다중 프로세스 쓰기는 D-1 전제로 막지 않는다 — 필요해지면 ADR.

## 2026-09-22 · uncommitted · feat(core_api_web): 감사 로그 기록 상태를 `logs/audit` 와 `/metrics` 로 노출

- 변경: `core_api_web/api/v1/observability.py` — `GET /api/v1/logs/audit` 응답에 `log`(= `FileAuditLog.health()`)를 더하고, `/metrics` 에 `rosy_audit_write_failures_consecutive`(gauge)·`rosy_audit_write_failures_total`·`rosy_audit_prune_failures_total`·`rosy_audit_prune_skipped_total`(counter)을 더한다. EventBus 가 구독자 예외를 삼키므로 감사 기록이 멈춰도 어디에도 남지 않던 상태를 닫는다. API ref v1.13. `test_diagnostics_api.py` 에 계약 문서와 metric 이름을 묶는 시험 추가. 원본: `archive/2026-09-22/fix/audit-log-write-cost` 848a934.
- 증거: 새 시험은 수정 전 observability 에서 실패, 수정 후 `test_diagnostics_api.py` 9 passed (2026-09-22 Windows).
- gate 변화: 없음(LOCAL).
- 결정: 게이지 이름을 `_consecutive` 로 둔다 — `rosy_audit_write_failures` 는 `_total` 카운터와 같은 OpenMetrics family 가 되어 충돌한다. `events` 목록 모양은 그대로(additive).

## 2026-09-22 · uncommitted · fix(core_events): 감사 로그 정리·조회를 이벤트를 낸 스레드 밖으로 (리뷰 REQUEST CHANGES 반영)

- 변경: `core_events/events/audit.py` — (1) `record()` 는 덧붙이기만 하고, 정리 시각이면 전용 데몬 스레드(`audit-compactor`, 한 번에 하나, 할 일이 없으면 종료)에 넘긴다. 정리는 락을 크기·신원을 뜰 때와 꼬리 이어 붙이기+`os.replace` 때만 잡고, 읽기·파싱·임시 파일 쓰기는 락 밖에서 256 KB 조각과 128 줄마다 1 ms 잠들며 한다(GIL 때문에 같은 프로세스의 CPU 일이 50 Hz 스레드를 세운다). 새 `settle()` 로 정리 완료를 기다린다. (2) `history()` 는 여는 순간만 락을 잡고(바꿔 끼우기와 겹치면 Windows 에서 `PermissionError`), 끝에서부터 필요한 만큼만 파싱한다. (3) 직렬화 실패(`PydanticSerializationError`)를 `serialize_failures`/`last_serialize_error` 로 세고 값을 `repr` 로 바꿔 기록은 남긴다. (4) 정리의 새 파일을 `fsync` 한 뒤 바꿔 끼우고 POSIX 에서는 디렉터리도 `fsync` 한다(덧붙이기와 정리 도중 덧붙은 꼬리는 그대로 fsync 없음). (5) 스키마로 못 읽는 줄은 지우지 않는다 — JSON `ts` 가 있으면 그 `ts` 로 보존 규칙을, 없으면 바이트 그대로 `audit.jsonl.quarantine` 으로 옮긴다. (7) `record()` 는 `OSError` 를 다시 던지지 않고 센다.
- 증거: `test_audit.py` 60 passed (Python 3.14), `test_audit.py`+`test_diagnostics_api.py` 69 passed (Python 3.12, uv). 새 시험 11 개는 이전 구현에서 모두 실패. 리뷰어 측정(10 만 줄 19.4 MB, Windows x86): 첫 기록 626→2.0 ms, 매시 기록 797→1.0 ms, `history(limit=1)` 1412→0.4 ms, 20 ms 티커의 최악 `record()` 263→1.5 ms(최악 주기 302→22 ms). 재작성하는 정리와 동시에 도는 티커의 `record()` p99 약 2 ms, 최대 2.5–10 ms(`os.replace` 창).
- gate 변화: 없음(LOCAL). Pi SD 카드의 fsync·replace 시간은 측정하지 않았다 — DEVICE 증거가 아니다.
- 결정: 정리 스레드는 상주하지 않는다(한 시간에 한 번 열고 끝낸다). 격리 파일은 정리하지 않는다 — 손상은 드물고 그 바이트가 조사 증거일 수 있다.

## 2026-09-22 · uncommitted · refactor(core_api_web): audit metrics 블록을 따로 만들어 잇고 `rosy_audit_serialize_failures_total` 추가

- 변경: `observability.py` `/metrics` — `lines[-2:-2]` 끼워 넣기 대신 audit 블록과 diagnostics 머리를 각각 목록으로 만들어 잇는다(출력 순서 동일). `rosy_audit_serialize_failures_total`(counter) 추가. `test_diagnostics_api.py` 의 계약 이름 목록에 추가.
- 증거: `test_diagnostics_api.py` 9 passed.
- gate 변화: 없음.
- 결정: API ref v1.13 은 이 브랜치에서만 존재하므로 버전을 올리지 않고 v1.13 항목을 넓힌다.

## 2026-09-22 · uncommitted · test(structure): audit.py 에 D-168 P6 크기 판정(accept, X5) 기록

- 변경: `test/test_module_structure.py` `SIZE_VERDICTS` 에 `core/core_events/core_events/events/audit.py` (675 줄) 를 `accept` 로 추가. main 에서 합쳐 온 D-168 P6(파일 600 줄 예산)이 리뷰 반영으로 늘어난 이 파일을 잡았다.
- 증거: `test/test_module_structure.py` passed.
- gate 변화: 없음.
- 결정: 09-06 X5 — 소유자 하나(`svc.audit`), ROS 없음, `test_audit.py` 가 덮는다. 길이의 절반가량은 덧붙이기·정리·격리 규칙이 기대는 근거 주석이다. 나누면 생기는 이음매가 떠받치는 것이 없다.

## 2026-09-22 · uncommitted · test(core): ROS-SIM 부트 스모크 재실행 — cmd_vel_cycle·watchdog·감사 로그 이후 트리

- 변경: 코드 변경 없음. `0adbe50`(cmd_vel_cycle, `safety.watchdog`)과 `11f1164`(감사 로그 덧붙이기+compaction, `{events, log}`, `rosy_audit_*`) 이후 main(`581741e`)을 WSL Jazzy 에서 09-22 절차대로 재실행하고 teleop→송신 중단→워치독 프로브를 더했다. 증거 `docs/validation/ros-sim-core-2026-09-22b`.
- 증거: `/core` 기동, `/cmd_vel` Publisher count 1(node core, teleop 뒤에도 1), `/nav_cmd_vel` pub 0/sub 1, `/api/v1` 200·`/dashboard` 200·`/robot/state` 401, road 유효/malformed 프로브 NameError 없음. teleop 0.1 ×10 → `/cmd_vel` linear.x 0.0→0.1(79 표본)→0.0, 마지막 teleop 약 0.5 s 뒤 `safety.watchdog`(timeout_ms 500) 감사 기록 1건, `logs/audit` 최상위 `events`·`log`(writable, 실패 0), `/metrics` `rosy_audit_*` 5개 모두 0.
- gate 변화: ROS-SIM HOLD→GO.
- 결정: 종료 경합은 게이트를 막지 않는다 — 본 실행의 SIGTERM 에서 `core shutting down` 뒤 `executor.spin()` 이 `RCLError: failed to initialize wait set`(context 무효)으로 traceback, `ros2 run` exit 1. 정상 상태 반복 5/5 는 exit 0·`system.shutdown` 감사 기록. 기동 창 SIGTERM 에서는 `failed to create guard_condition` 도 관찰. `core/main.py` 가 `KeyboardInterrupt` 만 잡고 rclpy 의 SIGTERM 에 의한 context 종료(`RCLError`/`ExternalShutdownException`)를 정상 종료로 다루지 않는 기존 경로이며 두 머지와 무관하다. 후속: exit 1 이 systemd 재시작 판정에 닿으므로 main 에서 외부 종료를 정상 종료로 처리할지 결정 필요. 또 09-22 README 의 road 유효 payload 명령은 닫는 `}` 가 빠져 있어 그대로는 발행되지 않는다(09-22b README 에 올바른 형태).

## 2026-09-22 · uncommitted · fix(core): SIGINT/SIGTERM 종료 경합을 정상 종료(exit 0)로

- 변경: `core/main.py` — `main()` 첫 문장에서 SIGINT/SIGTERM 을 예외를 던지지 않는 처리기로 바꿔 종료 요청만 기록(`install_stop_handlers`)하고, `rclpy.init()` 전후에 요청이 있으면 노드를 만들지 않는다. spin/기동 중 예외는 ROS 없는 `is_orderly_shutdown()` 으로 판정 — 종료 요청 뒤, 또는 한 번 유효했던 context 가 무효가 된 뒤의 예외는 정상 종료(exit 0), context 가 살아 있는 채 난 예외와 `rclpy.init()` 실패는 그대로 올린다(exit 1). finally 순서(`node.shutdown()` → `rclpy.shutdown()`)와 cmd_vel 경로는 그대로. 새 `test/test_core_main_shutdown.py`(판정 함수, 가짜 rclpy 로 경합·기동 창·진짜 오류 전파·훅 순서).
- 증거: `docs/validation/core-sigterm-2026-09-22` (WSL Jazzy, 부하 6 busy loop, 신호는 core 노드 PID). 수정 전 `0a9a07a`: steady SIGTERM 20회 17×0·3×1(wait set `RCLError`), 기동 0.2–1.5 s 10×241(SIGTERM 사망), 기동 1.5–8 s 3×0·7×1(guard_condition/wait set/publisher). 수정 후 `c6230cc`: steady SIGTERM 20회 19×0·1×245(teardown SIGSEGV), faulthandler steady 85×0, 기동 0.2–1.5 s 6×0·6×241(모두 `main()` 이전 entry script 창), 기동 1.5–8 s 12×0, SIGINT steady 6×0·기동 6×0. 수정 후 exit 0 실행 모두 `system.shutdown` 감사·8080 해제. 새 시험은 수정 전 main.py 에서 실패(수집 오류), 수정 후 13 passed.
- gate 변화: 없음(ROS-SIM 증거, DEVICE 아님).
- 결정: 판정은 예외 타입이 아니라 상태(종료 요청·context 유효성)로 한다 — 같은 경합이 `RCLError`, `InvalidHandle`, 콜백 future 의 publish 실패 등 여러 모양으로 나온다. 남은 것: (1) `main()` 전 entry script(`importlib.metadata` 조회) 창의 SIGTERM 은 코드로 닫을 수 없다 — 필요하면 `rosy-core.service` 에 `SuccessExitStatus=241 254` 를 따로 결정. (2) 종료 훅 뒤 teardown SIGSEGV 1/105, 스택 없음 — 후속 조사.

## 2026-09-23 · uncommitted · fix(core): 두 번째 종료 신호 격상 + 삼킨 종료 예외 기록 (리뷰 반영)

- 변경: `core/main.py` — 첫 SIGINT/SIGTERM 은 그대로 기록만, 두 번째는 SIG_DFL 을 되돌리고 격상(SIGINT → `KeyboardInterrupt`, SIGTERM → `os.kill(self, SIGTERM)`) — 멈춘 종료 훅/작업 스레드 join 을 SIGKILL 없이 끊는다. 종료로 판정해 삼킨 예외는 stderr `core: suppressed during shutdown: {exc!r}`. context-무효 분기에 "core 프로세스에서 rclpy context 를 내리는 것은 main() 뿐" 불변식 주석. `test_core_main_shutdown.py` 에 이중 신호(두 신호 모두), RMW 단계 신호 → init 없음, load_config 중 신호 → 노드 없음, `rclpy.init()` 실패 전파, 삼킨 예외 기록, src/core 생산 코드에 `rclpy.shutdown`/`try_shutdown` 없음 시험 추가. main `e8b2976` 병합(BOM 수정 포함).
- 증거: `docs/validation/core-sigterm-2026-09-22` "리뷰 반영 재확인" — WSL `a545d55` steady SIGTERM 10×0, 기동 1.5–8 s 6×0, 느린 종료(WSL 전용 20 s sleep 패치) 중 이중 SIGINT 3회 exit 254·이중 SIGTERM 3회 exit 241, 첫 신호→종료 1.1–2.0 s. core 시험 3.14 1251 passed·12 skipped, 3.12(uv) 1250 passed·13 skipped.
- gate 변화: 없음.
- 결정: 이중 신호의 241/254 는 실패로 남긴다(운영자가 멈춘 종료를 끊은 것). teardown 명시화(`executor.shutdown`/`destroy_node`)는 executor 가 `node.run()` 지역이고 1/105 SIGSEGV 를 검증할 수 없어 보류 — 후속 조사 항목 유지.

## 2026-09-23 · uncommitted · fix(core): 종료 teardown 명시화(executor drain·destroy_node·API join) + 두 번째 SIGINT 격상 통일

- 변경: `core/node.py` — `run()` 의 finally 가 `_stop_executor()` 로 `MultiThreadedExecutor` 의 `ThreadPoolExecutor` 를 `shutdown(wait=True, cancel_futures=True)` 로 비우고(보조 스레드, 3 s 상한) **그 다음** `executor.shutdown(timeout_sec=0)` 을 부른다(rclpy 7.1.11 은 풀을 비우지 않고, `Executor.shutdown()` 은 진행 중 콜백을 기다리지 않으며 먼저 부르면 guard condition 파괴로 `cannot use Destroyable` 이 난다). `shutdown()` 은 감사 `system.shutdown`·`core shutting down` 뒤 API 스레드를 join(5 s 상한) 한다. `core/main.py` — finally 가 `node.shutdown()` → `node.destroy_node()` → `rclpy.shutdown()` 순서로 노드를 context 보다 먼저 내린다. 두 번째 종료 신호는 SIGINT 도 `KeyboardInterrupt` 대신 `os.kill(self, SIGINT)` 로 격상한다(예전엔 그 뒤 `rclpy.shutdown()` 이 CPython 트램폴린을 되돌려 놓아 세 번째 SIGINT 가 무시됐다). 상한 합 8 s < `TimeoutStopSec=15`. cmd_vel 경로·종료 훅 순서 불변. 새 `test/test_core_node_teardown.py`(가짜 rclpy: drain 순서·상한·spin 예외 경로·API join), `test_core_main_shutdown.py` 에 `node.destroy` 순서와 두 신호 격상 시험. C6 `getattr(executor, "_executor")` 는 판정과 함께 기준 문서·`ALLOWED` 에 기록.
- 증거: `docs/validation/core-shutdown-2026-09-23` (WSL Jazzy, 레인 4 + busy loop 4). steady SIGTERM 수정 전 `5a4cedb` 600회: 598×0·**2×245(SIGSEGV)**·`never retrieved` 125회, 수정 후 `7614627` 600회: **600×0·245 0건**·`never retrieved` 109회(모두 publish 경합, `Destroyable` 0). SIGINT steady 40×0. 이중 신호(느린 종료 흉내) SIGINT 3×254·SIGTERM 3×241, `KeyboardInterrupt` 0. 모든 실행 마지막 감사 `system.shutdown`·포트 해제·잔존 0. 시험 3.14 `src/core/core/test/ test/` 2556 passed·52 skipped, 3.12(uv) core 1256 passed·13 skipped.
- gate 변화: 없음(ROS-SIM 증거).
- 결정: SIGSEGV 는 **고쳤다고 말하지 않는다** — 수정 전 발생률 0.33%(2/600)라 0/600 은 우연일 확률이 17–25%다. 스택은 못 얻었고, 못 얻은 이유가 단서다: CycloneDDS/lttng 스레드는 SIGSEGV 를 블록하므로(`evidence/thread-sigmask.txt`) faulthandler 도 LD_PRELOAD 처리기도 돌 수 없다 — crash 는 파이썬 스레드가 아니라 네이티브 스레드 또는 인터프리터 종료 이후다. 그래서 고친 것은 "파이썬이 통제할 수 있는 부분"(콜백·노드·API 스레드가 `main()` 안에서 끝나는 것)뿐이다. 실기 재발 시 core dump + gdb 가 필요하다.
- 교훈: 신호 처리기가 안 돌면 처리기를 의심하기 전에 그 스레드의 `SigBlk` 를 본다. 라이브러리 스레드가 신호를 블록하면 faulthandler 는 조용히 아무것도 못 한다.

## 2026-09-23 · uncommitted · fix(core): 멈춘 종료 격상을 `os._exit(2)` 로 (리뷰 2차) + teardown 경고·uvicorn graceful

- 변경: `core/main.py` — 두 번째 종료 신호는 `SIG_DFL` 복원 뒤 stderr 한 줄을 남기고 `os._exit(STUCK_SHUTDOWN_EXIT_CODE=2)`. 같은 신호로 자기 종료(`os.kill`)하면, 유닛이 `ros2 run` 래퍼 없이 노드를 직접 exec 하는 지금은 systemd 가 주 프로세스의 SIGINT/SIGTERM 사망을 깨끗한 종료로 쳐서 **멈춘 종료를 끊은 것이 정상 `systemctl stop` 과 구별되지 않는다**(리뷰 지적, 실측으로 확인). finally 의 삼킨 예외도 `core: suppressed during shutdown: ...` 로 남긴다. `core/node.py` — `_stop_executor` 가 logger 를 받아 (a) 상한 초과, (b) executor 에 `ThreadPoolExecutor` 가 없음(그 경우 `False` 반환), (c) `executor.shutdown()` 예외를 각각 경고로 남기고, `run()`/`shutdown()` 이 상한을 넘겼을 때도 경고한다. uvicorn `timeout_graceful_shutdown=3`(WS 엔드포인트가 await 에 park 해 API join 상한을 다 쓰는 것 방지). 상한 상수는 클래스 위로. 새 ROS 레인 canary `test/test_core_node_teardown_ros.py`(진짜 rclpy 로 `MultiThreadedExecutor._executor` 가 `ThreadPoolExecutor` 인지 고정), 호스트 drain 시험은 sleep 대신 사건 기반.
- 증거: `docs/validation/core-shutdown-2026-09-23` B·D절 — 래퍼 없이(출하 형태) 멈춘 종료 + 두 번째 신호: `os._exit(2)` 는 SIGINT·SIGTERM 각 3회 **exit 2**, 1차 수정(`os.kill`)은 130/143(신호 사망). systemd 에서 같은 상황: `os._exit(2)` → **`Result=exit-code`, `ExecMainStatus=2`, `failed`** ×2, `os.kill` → `Result=success` ×2(정상 정지와 구별 불가). 평범한 정지는 그대로 success(steady 12 + 기동 중 5 = 17/17). steady SIGTERM 240회 재실행 `861386e`: **240×0, SIGSEGV 0, 상한 경고 0건**. ROS 레인 32 passed. 시험 3.14 2559 passed·53 skipped, 3.12(uv) core 1259 passed·14 skipped.
- gate 변화: 없음.
- 결정: 격상은 **종료 코드**로 보인다(신호 사망 아님). 이 파일 위쪽 2026-09-23 항목의 "이중 신호의 241/254 는 실패로 남긴다"는 `ros2 run` 래퍼 아래의 관찰이며, 래퍼를 걷어낸 출하 형태에서는 이 항목이 대체한다. 정지 의미가 유닛의 exit-code 표가 아니라 프로세스가 내는 값으로 정해진다.
- 교훈: 래퍼를 걷어내 "신호가 그대로 보이게" 하면 정상 정지만 깨끗해지는 게 아니라 **격상도 깨끗해진다** — 신호로 의미를 나누던 곳에서는 래퍼 제거가 의미 하나를 지운다.

## 2026-09-23 · uncommitted · fix(core): 격상 처리기를 async-signal-safe 하게 (`os.write`) + `SIG_IGN` + 경고 0건 주장의 근거 교체 (리뷰 3차)

- 변경: `core/main.py` — 두 번째 종료 신호 처리기가 (1) `SIG_DFL` 대신 **`SIG_IGN`** 을 깐다(그 몇 줄 사이에 세 번째 신호가 오면 기본 동작은 신호 사망 = systemd 가 보기에 깨끗한 종료라 격상이 다시 정상 정지처럼 보인다), (2) `print` 대신 미리 만든 바이트 상수를 **`os.write(2, ...)`** 로 쓴다(버퍼 잠금을 인터럽트된 주 스레드가 쥐고 있으면 처리기가 거기서 막히고, 멈춘 종료를 끊어야 할 바로 그 경로가 SIGKILL 까지 늘어진다). finally 의 삼킨 예외 메시지는 단계 이름을 싣는다(`... (shutdown)`/`(destroy_node)`). 시험: 격상 시험이 `SIG_IGN`·`os.write` 호출 인자를 확인하고, 새 `test_escalation_message_is_preformatted_bytes_for_os_write` 가 처리기 본문에 `print(` 가 없음을 붙든다. 새 `test_suppressed_hook_exception_names_the_step`.
- 증거: `docs/validation/core-shutdown-2026-09-23`. **정정**: 바로 위 2026-09-23 항목의 "상한 경고 0건"은 당시 `lane.sh` 가 경고를 세지 않아 근거가 없었다 — `lane.sh` 에 `warn=` 칸(teardown 경고 4종)을 더해 240회를 다시 돌렸고 `warn=[1-9]` 실행 **0건**, exit 0 240/240, SIGSEGV 0(`evidence/after4-steady-TERM-round3.txt`). 최종 코드로 재실행: 래퍼 없는 이중 신호 SIGINT·SIGTERM 각 3회 **exit 2** + 격상 메시지 6/6(`evidence/double-direct-round3.txt`), systemd steady 12 + 기동 중 5 = **17/17 success**(`evidence/sd-new-round3.txt`), 멈춘 종료 2/2 **`Result=exit-code` `ExecMainStatus=2` `failed`**(`evidence/sd-stuck-round3.txt`). 시험 3.14 2561 passed·53 skipped, 3.12(uv) core 1261 passed·14 skipped.
- gate 변화: 없음.
- 결정: 신호 처리기 안에서는 포맷도 버퍼도 쓰지 않는다 — 바이트 상수 + `os.write` 만. 격상 중에는 같은 신호를 무시한다(`SIG_IGN`), 그래야 exit 2 가 보장된다.
- 교훈: "경고가 0건이었다"는 주장에는 경고를 센 칸이 있어야 한다. 수집기에 없는 필드를 근거로 쓰면 그 숫자는 관측이 아니라 인상이다.

## 2026-09-23 · uncommitted · docs(adr): D-182·D-184 Proposed — 명령 코드와 core 시험의 경계

- 변경: 명령 다중화 코드가 시뮬 리터럴을 갖지 않는 결정과, `core/test`는 공개 계약만 본다는 결정을 진행 기록에 연결했다. 시험 파일은 옮기지 않았다.
- 증거: ADR 기록. 실행 시험 없음.
- gate 변화: 없음.
- 결정: D-182, D-184 Proposed
- 교훈: 없음.

## 2026-09-24 · uncommitted · chore(core): remove the legacy core/deploy installer

- 변경: `src/core/core/deploy`의 옛 `install.sh`와 `rosy-core.service`를 제거했다. 제품 유닛은 `deploy/robot/native`에 있다.
- 증거: `test/test_folder_layout.py` 통과 (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: D-186 Accepted
- 교훈: 없음.

## 2026-09-24 · uncommitted · fix(core): CORE-only 에서 출처 없는 채널은 `unavailable` (US-010)
- 변경: `core/services.py` 가 `runtime.mode == core` 일 때 `StateManager(sources_configured=False)` 로 만든다 — 한 번도 값이 오지 않은 채널은 `disconnected`(출처는 있는데 무음)가 아니라 `unavailable`. 첫 표본이 오면 보통 판정. inventory descriptor 에 런타임 차단 이유 전달. `bridge/display.py` `battery_percent` 결측은 `None`. `test_api.py`·`test_battery.py` 기대값을 새 계약으로 갱신, `test/test_truthful_core_only.py`(이 패키지, 16건) 추가.
- 증거: `python -m pytest src/core/core/test -q` 초록 (2026-09-24 Windows, 위 1966 passed 에 포함).
- gate 변화: 없음 (DEVICE 재검증 필요).
- 결정: D-161, D-32.
- 교훈: 하드웨어 모드의 `safety` 채널은 여전히 공급자가 없다(API estop 만 갱신) — 대시보드는 이제 그것을 UNVERIFIED 로 정직하게 보인다. 공급 경로는 후속 과제.

## 2026-09-24 · uncommitted · refactor(core): move the bridge's DockingExecutor into bridge/docking_executor.py
- 변경: `ros_bridge.py`의 DockingExecutor 구현(`navigate_to`·`cancel_navigation`·`drive`·`stop`·`set_collision_exemption`·`reset_odometry_mark`·`travelled_m`·`odometry_available`·`odometry_pose`와 `_dock_odom_mark`·`_applied_dock_exemption`)을 ROS-free `bridge/docking_executor.py`의 `BridgeDockingExecutor`로 옮겼다. ROS 동작(Nav2 goal 전송·취소, 면제 Bool 발행, 마지막 odom 포즈)은 callable 로 받는다. `services.docking.executor`는 이제 `bridge.docking_executor`다. `_last_odom_xy`는 없애고 포즈에서 xy 를 읽는다(둘은 `_on_odom`에서 함께 쓰였다). 순서 보장 유지: `external_goal_sent` → send_goal, 면제 latch 멱등. 소스 읽는 시험 3건(`test_executor_contracts`, `test_docking_mode_release`, `test_bridge_timers`)은 경로·이름만 바꿨다. 신규 `test/test_bridge_docking_executor.py` 10건.
- 증거: `ros_bridge.py` 635 → 581줄(D-168 P6 600줄 예산 안, 새 verdict 불요). `src/core/core/test` 1133 passed·13 skipped, `src/core/core_features/test` 202 passed, `test/test_module_structure.py` 11 passed, harness lint 0 errors (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: 없음. main 의 24b6d4bb(`bridge/observation.py`)와 같은 방식의 동작 보존 추출.
- 교훈: 없음.

## 2026-09-24 · uncommitted · feat(robots): CORE loads the robot profile from robots/<model> (D-196)

- 변경: `config/profile.pinky_pro.yaml`·`config/capabilities.yaml`을 `src/robots/pinky_pro/config/{profile,capabilities}.yaml`로 옮겼다. `rosy_default.yaml`은 최상위 `profile:`/`capabilities:` 대신 `robot.model: pinky_pro`를 둔다. `core/node.py` `_resolve_path`는 네 번째 인자 `base_dir`(로봇 패키지 config)를 받고, 기본 경로는 `robot_config_dir(robot.model or DEFAULT_ROBOT)`다. 절대 경로 오버레이(`/etc/rosy/profile.yaml` 등)는 그대로 우선한다. 두 파일을 읽던 core 시험 11개(`conftest.py` 포함)는 `robot_config_dir("pinky_pro")`로 읽는다.
- 증거: `src/core/core/test` 1199 passed·14 skipped, `src/robots/pinky_pro/test` 2 passed, `test/test_module_structure.py`·`test_robot_literals.py`·`test_harness_contracts.py` 통과, harness lint 0 errors (2026-09-24 Windows).
- gate 변화: 없음. share 조회 경로는 ROS-SIM(WSL Jazzy colcon build + CORE 부팅)에서 아직 미확인.
- 결정: D-196 Proposed
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(core,robots): clear error for a missing robot package; ship robots in docker/ci (D-196 review)

- 변경: `core/node.py` `_resolve_path`를 순수 함수 `_robot_file_paths(config)`로 바꿨다. `profile`/`capabilities`가 둘 다 절대 경로(오버레이)면 로봇 패키지를 조회하지 않아 패키지가 없어도 부팅한다. 키가 없거나 상대 이름일 때만 `robot_config_dir(robot.model)`를 한 번 부른다. 신규 `test/test_core_node_robot_paths.py` 4건(가짜 rclpy로 호스트에서 검사, `test_core_node_teardown` 방식). 11개 시험 파일은 `robot_dir = robot_config_dir("pinky_pro")`를 한 번 묶어 120자 안으로.
- 증거: 실패 먼저 — 4 failed(`AttributeError: _robot_file_paths`). 수정 후 대상 실행(core·core_common·robots 시험 + 구조·리터럴·harness·scorecard·payload·runtime 계약) 1339 passed·14 skipped. WSL Jazzy `ros2 run core core`가 오버레이 없이 `core up: robot_id=rosy_01 model=Pinky Pro`로 부팅(share/pinky_pro/config).
- gate 변화: 없음
- 결정: D-196 Proposed
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(core_common): no-ament-env falls back too; path tests hold on a sourced ROS box (D-196 review)

- 변경: `test/test_core_node_robot_paths.py`의 기본·상대·미설치 경우에 지역 `no_ament_share` fixture(가짜 `ament_index_python.packages`, PackageNotFoundError)를 걸어 소싱된 ROS 상자에서도 소스 폴백 경로를 단언하도록 했다.
- 증거: WSL Jazzy 소싱 상태에서 core_common·이 파일·robots 시험 20 passed; Windows host 48 passed(대상 묶음) (2026-09-24).
- gate 변화: 없음
- 결정: D-196 Proposed
- 교훈: 없음

## 2026-09-24 · uncommitted · docs(adr): D-200 docking owns the DOCKING mode
- 변경: `docs/adr/D-200-docking-owns-the-docking-mode.md` 추가(Accepted), ADR Log 표 D-200 행, `progress.md`의 `adrs`에 D-200. 주차 설계 문서에 D-200 링크 한 줄. 이미 main에 있는 구현(도킹 전용 슬롯, `route_nav_cmd_vel`, `take_docking_mode`/`release_docking_mode`/`leave_docking`, ModeMachine `expect`와 리스너 격리)을 기록했다. 코드 본문은 바꾸지 않았다.
- 증거: 시험 `test_docking_mode_ownership`, `test_docking_mode_release`, `test_mode_listener_isolation`, `test_bridge_docking_executor`, `test_docking_parking*`, `core_features/test/test_docking_review_fixes`. Gazebo 미션 4/4(주차 오차 1.4–2.3 mm, 1.7° 이하)는 25° 세계의 ROS-SIM이고 장치 증거가 아니다.
- gate 변화: 없음.
- 결정: D-200 Accepted. API 코드는 API & Protocol Reference v1.20.
- 교훈: 없음. 후속(최종 리뷰): 라인 추종 PUT과 `dock()` 경합(MED), 정지·해제 경합 시 잠금 없는 EMERGENCY, 잠금 없는 `on_battery_level`, `cmd_vel_cycle` 오류 로그 폭주.

## 2026-09-24 · uncommitted · docs(adr): D-205 real lane mission transition order
- 변경: `docs/adr/D-205-real-lane-mission-transition-order.md` 추가(Proposed), ADR Log 표 D-205 행, `progress.md`의 `adrs`에 D-205. D-199·D-200에 see-also 한 줄, 인식 설계 문서에 D-205 링크 한 줄. `harness.yaml`의 `adr_gaps`에 D-201–D-204(concept 16과 역할 화면 설계가 먼저 쓴 번호)를 선언했다. 코드 본문은 바꾸지 않았다.
- 증거: 문서 변경. 시험은 harness lint와 문서 구조 시험.
- gate 변화: 없음.
- 결정: D-205 Proposed. D-200 최종 리뷰의 core 후속 넷을 이어받는다.
- 교훈: 없음. 후속: (MED) 라인 추종 `PUT`과 `dock()` 경합, 정지·해제 경합 시 잠금 없는 EMERGENCY, 잠금 없는 `on_battery_level`, `cmd_vel_cycle` 오류 로그 폭주. API 문서의 `LINE_FOLLOW_ACTIVE`·`NO_ODOMETRY` "(v1.18)" 표기는 v1.20이 맞다.

## 2026-09-24 · uncommitted · fix(core): inventory 가 런타임 증거(readiness 포함)로 descriptor 를 막는다 (D-32)
- 변경: `services.py` `inventory()` 가 `runtime_truth(config, state, readiness).reasons` 를 넘긴다. 시험 `test/test_hardware_runtime_truth.py` 신규(무동작 `rosy-io`, 배터리만, 끊김, lease 만료, 시뮬 벤치, SAFE_STOP 순서, 맵 존재). `test_truthful_core_only.py` 하드웨어 모드는 motor adapter·Nav2 보고 뒤에만 광고. `test_api.py` BOOTING 보다 런타임 이유가 먼저.
- 증거: `python -m pytest src/core/core/test -q` 초록 (2026-09-24 Windows, 위 1553 passed 에 포함).
- gate 변화: 없음 (DEVICE 재검증 필요).
- 결정: D-32, D-192.
- 교훈: 없음

## 2026-09-25 · uncommitted · refactor(runtime): move core under src/runtime (D-231)

- 변경: src/runtime/core로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 runtime 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(core): D-260 HostRuntimeProbe.temperature()
- 변경: `core/system/runtime.py`에 온도만 읽는 공개 메서드. `snapshot()`은 CPU·네트워크 델타를 전진시키므로 두 번째 독자가 부르면 안 된다. `test_event_catalogue.py` not_events에 장치 id `pi.power`
- 증거: `test_host_status_summary.py::test_the_runtime_probe_reads_only_the_temperature` 통과; 2026-09-26 Windows, `feat/d260-status-signals`: 호스트 묶음(foundation·gateway·api_web·hmi web/dashboard/face·lamp·boot display·hw-test·hw-probe·boot-status·native systemd·device surface·image customization·lamp image·harness) 2051 passed, 32 skipped, 2 failed — 둘 다 main의 `src/hmi/dashboard/logs.md` 두 항목(`- 근거:`)이 원인이고 깨끗한 main worktree에서도 같게 실패한다. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 62 passed
- gate 변화: 없음
- 결정: D-260 Proposed
- 교훈: 없음

## 2026-09-26 · uncommitted · test(core): D-257 site sighting schema coverage

- 변경: `SiteSightingPayload` 계약의 finite/bounds/lineage/image-free 거부를 gateway contract suite에서 검증한다.
- 증거: `python -m pytest src/runtime/gateway/test -q -p no:cacheprovider` 1325 passed/16 skipped.
- gate 변화: 없음; ROS-SIM/DEVICE/FIELD 범위 밖.
- 결정: D-257 Proposed; schema-only pass는 카메라/vision worker 동작 증명이 아니다.
- 교훈: 없음

## 2026-09-26 · uncommitted · FleetAgent site discovery integration

- 변경: CORE가 기존 직접 Fleet URL 경로를 유지하면서, 승인된 pairing token이 있는 경우에만 발견된 사이트로 outbound WSS를 연다. SD 등록용 일회성 값은 연결 토큰으로 쓰지 않는다.
- 증거: gateway/Fleet/first-boot 집중 58 passed, 변경 Python flake8 통과. ROS-SIM/실제 Pi는 미실행.
- gate 변화: LOCAL 검증만 추가.

## 2026-09-27 · uncommitted · consume core_common configuration
- Change: launch now resolves default YAML from core_common share; source fixtures follow the new owner.
- Evidence: 1,812 gateway/config/image tests passed with 28 skipped; flake8 passed for changed runtime/config Python files.
- Gate: LOCAL only; ROS-SIM, image and device runtime remain unverified.

## 2026-09-28 · uncommitted · report camera-line observation hold

- Change: selected CAMERA_LINE missing/stale/invalid evidence keeps the existing fail-closed zero command candidate and adds a camera-specific reason. Source changes still discard old evidence; no IR auto-switch was added.
- Evidence: line-follow and simulation-clock regression suites 27 passed. Full gateway suite: 1,384 passed, 16 skipped, 5 failures; failures include unrelated event catalogue/API-reference alignment and two outdated camera-state expectations, which were corrected and rechecked in the focused suites.
- Gate: SOURCE/LOCAL only; no ROS-SIM, device, or field acceptance.

## 2026-09-28 · uncommitted · test correlated navigation event lifecycle

- Change: cover CORE REST goal metadata and verify `nav.started`, cancel-request, and final result events retain the same navigation attempt ID.
- Evidence: focused gateway API/core-logic/event-catalogue tests pass. One full event-catalogue literal-classification test still fails on pre-existing `network.status` and `release.status` literals in Host Agent status decoding.
- Gate: SOURCE/LOCAL test evidence only; live Nav2, artifact and device acceptance unchanged.

## 2026-09-28 · uncommitted · fix(core): isolate navigation result correlation

- Change: bind result-event correlation to the action generation; superseded results are ignored and uncorrelated moving-goal results remain uncorrelated. Add fleet-owned goal takeover guard and durable event replay coverage.
- Evidence: focused gateway navigation/API/core-logic/GoalTracker regressions 19 passed. The separate event-literal classification failure remains a pre-existing Host Agent status decoding issue.
- Gate: SOURCE/LOCAL only; no ROS-SIM, image, device, stop readback, or FIELD acceptance.

## 2026-09-28 · uncommitted · retain correlated result after cancel

- Change: preserve the canceled Nav2 generation's Fleet correlation until the terminal result callback, including cancel-before-acceptance. Publish that result without changing a newer navigation state.
- Evidence: focused GoalTracker and navigation manager regression suites pass; full changed-suite rerun pending.
- Gate: SOURCE/LOCAL only; no ROS-SIM, image, device, stop readback, or FIELD acceptance.

## 2026-09-28 · uncommitted · close canceled-generation result recovery

- Change: retain at most 128 canceled correlations; publish late terminal results without changing a newer navigation state. Unreadable action results leave the attempt unresolved.
- Evidence: GoalTracker + navigation manager tests 67 passed; relevant API, services, and Fleet suites passed separately.
- Gate: SOURCE/LOCAL only; no ROS-SIM, artifact, device, physical-stop, site, or FIELD acceptance.

## 2026-09-29 · uncommitted · classify host agent status commands as non-events

- Change: register `network.status` and `release.status` in the event-catalogue `not_events` table — both are host agent commands from `host_agent.ALLOWLIST`, never emitted by core — and retarget the CORE-to-agent allowlist check to `deploy/robot/pinky_pro/release` after the role-dir regroup.
- Evidence: gateway suite 1402 passed, 16 skipped; CI core step 1841 passed, 16 skipped. The `not_events` cross-check against `emitted()` keeps the new entries from ever hiding a real event.
- Gate: SOURCE/LOCAL only; no ROS-SIM, image, device, stop readback, or FIELD acceptance.

## 2026-09-29 · uncommitted · feat(traffic): wire unsignalized junction rule through CORE

- Change: `_traffic_policy_config` now maps `traffic_policy.junction_rule` from config into the policy (validated `signal_controlled` | `stop_and_go`), `TrafficPolicyPatch` accepts it on `/api/v1/traffic/policy/stage`, and `test_traffic_policy.py` covers the stop-and-go verdicts — proceed after complete stop+dwell with no observed signal (`unsignalized_proceed`), hold on any observed signal including weak false positives (`signal_unexpected`), conflict precedence, unchanged `signal_controlled` waiting, staging/validation, and CORE config wiring. Korean dashboard `/console` facts gain a 규칙 row.
- Evidence: focused host runs (Windows): traffic policy+API+runtime config + foundation + services 380 passed; protocol schemas + api_web + dashboard 105 passed 47 skipped; semantic road simulation + event catalogue 74 passed. API Reference v1.54 in the same change.
- Gate: SOURCE/LOCAL only; no ROS-SIM loop over an authored unsignalized scene, device stop-and-go readback, or FIELD acceptance.

## 2026-09-29 · uncommitted · feat(traffic): D-337 T3 — bind the measured-light observer in CORE

- Change: `_signal_observer_binding` parses the file-only `traffic_policy.signal_observer` block (empty/absent = feature off; malformed values fail the build; a binding without the policy's map/scene fails the build too — every frame would be rejected otherwise). CoreServices carries `signal_observer` and starts the daemon-thread monitor next to the manager it feeds; status fields `signal_source_kind`/`signal_head_age_s`/`signal_head_frozen` flow to snapshots and `/api/v1/traffic` unchanged routes.
- Evidence: test_traffic_policy +4 (absent by default, binds+starts with url captured, missing map/scene ValueError, status view). Combined host run 501 passed (traffic, services, API, event catalogue, foundation, runtime config); flake8 clean on changed lines — the reported services.py F401/E306/W293 sit outside this diff (parallel track's lines).
- Gate: SOURCE/LOCAL only; no live observer, ROS-SIM, device, or FIELD acceptance. Dashboard readback (T4) remains.

## 2026-09-29 · uncommitted · docs(core): 24b6d4bb 브리지 판정 추출의 모듈 기록 보수

- 변경: 24b6d4bb(2026-09-24)가 bridge/observation.py 신설, 시블리 4종 확장(reconcile.led·display.republish_due·goal_tracker.on_response/on_result·save_map.await_call), ros_bridge 757-590행(D-168 예산 복귀)을 반영하면서 이 모듈의 저널과 bridge/AGENTS.md 갱신이 빠졌다. bridge/AGENTS.md에 observation.py 행(Key Files·시험 sibling 목록)과 D-338 원칙 서술을 추가하고, 낡은 no-remote 주장을 origin/CI 현황으로 정정했으며 이 항목으로 모듈 저널을 소급 기록한다. 결정 원칙의 정본은 docs/adr/D-338.
- 증거: 24b6d4bb stat 13 files +1047/-237. 현재 observation.py 203행(c33f51a6 카메라 폴트 폴백 확장 포함), ros_bridge.py 582행. bridge 시블리 시험(test_bridge_observation·timers·goal_tracker·reconcile·display·save_map) 전체 통과(2026-09-29 Windows).
- gate 변화: 없음.
- 교훈: 병행 세션에 작업이 흡수 커밋되면 저널 의무까지 사라지지는 않는다 — 구현이 이미 main에 있으면 기록만 별도 커밋으로 보수한다.

## 2026-09-29 · uncommitted · feat(api): /system/capabilities에 lifecycle 블록 (D-347, v1.58)

- 변경: api/v1/system.py의 capabilities 끝점에 lifecycle_from(svc.capability.to_dict(), truth.reasons)를 실었다 — 광고된 플래그별 단일 생애 어휘(additive). 기존 flags·withheld·runtime·501 게이트·409 CAPABILITY_WITHHELT 불변. 신규 시험 test_capability_lifecycle.py(wire 1건 포함 6건).
- 증거: test_capability_lifecycle 6 passed; test_api·test_runtime_capability_truth·test_truthful_core_only·foundation 185 passed. 앱 설명 문구·line-follow 핀 v1.58 동시 갱신(버전 핀 3곳 한 변경 단위).
- gate 변화: 없음.
- 결정: inventory PresentationState는 그대로 — D-347 본문 표가 대응을 정의한다(unavailable≈blocked 등).
- 교훈: core_client은 팩토리 픽스처다( (TestClient, services) 반환) — 첫 사용에 401·function 오류가 나면 소비 방식부터 확인한다.

## 2026-09-30 · uncommitted · feat(display): display/info에 charging 상태 추가 (D-350·D-351)

- 변경: bridge/display.py info_payload에 "charging" 필드 추가 (additive, false 기본). 화면이 CHARGING/CHARGED_HOLD 상태를 표시할 수 있게 한다.
- 증거: test_bridge_display 전체 통과 (필드 목록 갱신 포함).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 없음.

## 2026-09-30 · uncommitted · fix(bridge): display charging이 실제로 켜지게 — 죽은 getattr 제거 (C6)

- 변경: display.py의 `getattr(battery, "charging", False)`를 `snapshot.battery_status.charging` 직접 접근으로 교체. `Battery`(생 percent/voltage)에는 charging이 없고 D-27 확인된 충전 판정은 `BatteryStatus`에 있으므로, 이전 reach는 항상 False를 돌려주는 죽은 코드였다 — D-351의 충전 표시가 화면에 절대 켜지지 않았다. C6 판정을 기준 문서에 "Seam lie — fixed by deletion"으로 기록(safety/profile 판례와 같은 형식). test_bridge_display의 `_snapshot` fixture에 battery_status를 추가하고 charging=True 종단 시험을 신설.
- 증거: test_module_criteria 1 passed (reach 소거로 집합 동일성 회복), test_bridge_display 15 passed, gateway 전체 1439 passed/16 skipped (2026-09-30 Windows). 이것이 main CI 적신의 첫 원인이었다(41b3a704부터 5연속 실패 중 유일하게 CI 로그에 잡힌 core 도메인 실패).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: getattr 기본값은 "있으면 읽는다"가 아니라 "이름이 바뀌어도 침묵한다"다 — D-351 회차가 시험에 기본값(False)만 적어 통과시킨 것이 이 결함을 통과시킨 길이었다. 참(True) 종단을 같이 적었으면 즉시 잡혔다.

## 2026-09-30 · e3eb2561 · feat(line-follow): LiDAR 점을 path 판정에 넘기고 수동 한도를 차선 추종에 연결

- 변경: `core/bridge/observation.py front_clearance` 가 `obstacle_mode: path` 면 `scan_points`(반경 horizon+half_width 안)를 `observe_scan_points` 로, sector 면 옛 정면 최소 거리를 넘긴다. `core/services.py` 가 새 설정 네 개를 파싱하고 `LineFollowManager(angular_ceiling=lambda: safety.limits.manual_angular)`. `rosy_default.yaml line_follow` 에 기본값과 주석.
- 증거: `test_line_follow_obstacle_path.py` 의 브리지·설정 파싱 시험 포함 18 passed; gateway `-k "line_follow or clearance or ir"` 247 passed, 5 skipped (2026-09-30 Windows).
- gate 변화: SOURCE 진행. 기본 설정에서 차선 추종 각속도 상한이 0.70 → 0.60(safety.manual_angular 기본)으로 내려간다 — 가제보 재확인 필요.
- 결정: D-344 §11 보강, §13.

## 2026-10-01 · uncommitted · fix(core): D-380 실기 검증이 잡은 모드 미러 결함

- 변경: services.py 가 ModeMachine change_listener 로 전이를 StateManager 에 미러한다(mirror_mode). 그동안 POST /mode 는 set_mode 를 직접 불렀지만 SAF-001 e-stop 경로는 transition 만 불러, 정지·해제 내내 스냅샷 모드(대시보드 칩·/robot/state·부팅 표시 핸드오버)가 이전 모드를 말했다.
- 증거: test_api.py test_the_snapshot_mode_follows_the_e_stop_cycle (변이 증명: 리스너 제거 시 빨강).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(test): 대시보드 계약 시험이 D-362 P1 소유자 파일을 읽게

- 변경: 13803932(D-362 P1)가 `styles.css`·`app.js`를 `console-detail.css`·`telemetry.js` 소유 모듈로 나눴지만 게이트웨이 시험 네 개는 옛 파일을 계속 읽어 main CI에서 8건이 붉었다. `test_console_layout` 의 `css()`가 두 css를 캐스케이드 순서(styles.css → console-detail.css, 그 파일 스스로가 밝힌 연결 순서)로 읽고, 뷰 상태 기록(`document.body.dataset.view`)·머리 숨김(`node.hidden = !headline;`)·`from "./triage.js"` import는 새 소유자 `telemetry.js`에서 단언한다. `test_host_cards`·`test_host_hardware`의 장치 카드 규칙(`.host-card[data-available="false"]`, "D-247 장치 카드" 절)도 두 css를 함께 읽는다. 단언 내용은 그대로 — 읽는 파일만 실제 소유자로 옮겼다.
- 증거: 해당 8건 복구. core 도메인 전체(gateway·events·services·web_common·api_web) 2014 passed, 29 skipped (2026-10-01 Windows). 단 `test_core_node_teardown::test_run_drains_executor_workers_before_returning` 은 이 변경과 무관하게 Windows에서 간헐 실패한다(재실행 통과, CI Linux 통과).
- gate 변화: 없음.
- 교훈: 파일을 나누는 리팩터는 그 파일을 텍스트로 읽는 계약 시험의 소유자도 함께 옮겨야 한다 — 분할 커밋이 시험을 안 고치면 CI가 다음 커밋에서 대신 말한다.

## 2026-10-01 · f34781ae · feat(core): line_follow LiDAR 장착 yaw 단일 출처 (D-47 부록)
- 변경: `core/lidar_mount.py` 가 시작 때 한 번 정한다 — 승인된 `lidar_mount` 레코드 > 센서 어댑터에 묶인 `lidar_yaw_offset`(D-47) > `line_follow.lidar_forward_deg` 손값. `node.py` 가 쓴 값과 출처를 로그에 남긴다. 어댑터에 `bound_parameters` 속성 추가.
- 증거: `test_lidar_mount_source.py` 7 passed(순서, 후보 무시, 190° 섹터·경로), gateway 전체 1501 passed(event_catalogue 한 건은 점 표기 출처 문자열을 고쳐 통과), teardown 간헐 실패는 기존과 같다 (2026-10-01 Windows).
- gate 변화: SOURCE. 기본 설정에서는 여전히 손값(저장소·어댑터 비어 있음).

## 2026-10-01 · d20e976e · fix(core): 승인 장착 레코드 검증, 손값이 어댑터 바인딩보다 우선 (H1·M3)
- 변경: 승인된 lidar_mount 레코드는 check_values 를 통과할 때만 쓴다(아니면 이유를 남기고 넘어감, KeyError/TypeError/ValueError 포함). 측정 레코드가 승인되기 전에는 손값이 어댑터의 lidar_yaw_offset(현재 손으로 맞춘 190°)보다 우선하고, 3° 넘게 다르면 경고로 로그한다.
- 증거: test_lidar_mount_source.py 12 passed — 실제로 켠 ControlSensorAdapter 로도 손값이 이긴다 (2026-10-01 Windows).
- gate 변화: 없음(기본 설정은 전과 같이 손값).

## 2026-10-01 · 0af2f6a2 · fix(core): 장착 해석기가 경고 플래그를 돌려준다 (F9)
- 변경: resolve_lidar_forward_deg 가 (deg, source, warn) 을 돌려주고 node.py 는 문자열 대신 플래그로 로그 수준을 고른다.
- 증거: test_lidar_mount_source.py 12 passed (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(bridge): D-385 set_emotion 클라이언트와 표정 래치

- 변경: ros_bridge 가 5 Hz 상태 틱에서 reconcile.emotion(LiDAR 문법 — latch 없이 재시도)으로 표정을 바꾼다. 서비스 클라이언트 5개로 늘어 test_bridge_timers 핀을 같이 갱신했다.
- 증거: test_bridge_reconcile.py 표정 3건·test_bridge_timers.py. 433 passed.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(test): status-inputs 키 집합에 swarm_role 추가 (D-383 뒤치움)

- 변경: d0f2b7f5(D-383)가 `api/v1/host.py` 의 `status_inputs` 에 `swarm_role`(대형 역할 leader/follower, 없으면 absent)을 더하며 루트 host 시험만 갱신했다. 게이트웨이의 키 집합 동일성 시험이 그 키를 몰라 main CI core 단계가 붉었다. 기대 키 집합에 `swarm_role` 을 넣고, 상태 없음(None)도 absent로 기록됨을 함께 단언한다.
- 증거: test_host_status_summary.py 전체 passed(키 집합·absent·핸드오버). 로컬 core 도메인 전체 회귀 결과는 별도 기록.
- gate 변화: 없음.
- 교훈: 핸드오버에 필드를 더하는 커밋은 그 필드의 소비자 시험이 사는 *모든* 시험실을 찾아 갱신해야 한다 — 이번에도 한쪽(루트 test/)만 녹색이어서 다른 쪽(gateway)이 다음 push 에서 붉었다.

## 2026-10-01 · uncommitted · feat(bridge): D-394 주행 카드 drive_due·drive_payload

- 변경: bridge/display.py 에 DRIVE_EVERY_S/DRIVE_HOLD_S·drive_due(운용 중에만, 20 s)·drive_payload(kind: drive, 웨이크 카드와 같은 반올림 계약, 결측 속도 None). ros_bridge 상태 틱이 기존 display/info 퍼블리셔로 발행한다(구조 변화 없음).
- 증거: test_bridge_display.py (변이: EMERGENCY 제외 시 빨강). 게이트웨이 관련 212 passed.
- gate 변화: 없음.

## 2026-10-01 · a527920a · feat(core): 보정 lease 배선과 만료 타이머
- 변경: `CoreServices.calibration` 을 만들고 상태 스냅샷 provider 로 건다. `ros_bridge._tick_power` 가 `calibration.expire_due()` 를 불러 아무도 상태를 읽지 않아도 만료 이벤트가 난다. 새 시험 `test/test_calibration_session.py`. 15770a9c: `display.info_payload` 가 `activity` 를 싣는다(LCD).
- 증거: test_calibration_session.py 13 passed, test_bridge_display 통과, test_event_catalogue·test_module_criteria 통과(릴레이 함수·getattr 도달을 만들지 않도록 고침).
- gate 변화: 없음.

## 2026-10-01 · ce7a3413 · test(host): host-card 가짜 서비스에 idle 보정 lease
- 변경: host install/rollback/reboot 가 `svc.calibration` 을 읽게 되어 SimpleNamespace 가짜가 AttributeError 5건. 스텁 메서드가 아니라 실제 `CalibrationSessionManager`(idle)를 넣었다.
- 증거: test_host_cards·host_hardware·host_status_summary 162 passed.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · test(gateway): D-359 콘솔 프레임·비활성 사유 시험을 현재 계약에 맞춤

- 변경: `test_console_layout.py::test_the_console_does_not_scroll`은 D-359 §6.5의 고정 프레임 조건(`@media (width >= 64rem) and (height >= 40rem)`) 안의 `.console`이 `100dvh`·`--topbar-height`·`overflow: hidden`인지 본다. `test_host_hardware.py`는 `setEnabled("hardware-refresh", isAdmin(), "관리자 권한 필요")`(D-359 §5.3 비활성 사유)를 기대한다.
- 증거: origin/main f0b20f02 CI 적신 2건(rosy-0d 보고) 재현 후 수정. `src/runtime/gateway/test` 1578 passed; 남은 3건(core_node_teardown, event_catalogue의 road_behaviour 이벤트명, module_criteria C6 ros_bridge)은 D-359와 무관.
- gate 변화: 없음.
- 결정: D-359 §5.3·§6.5. 시험 의도(넓은 창에서 콘솔은 스크롤하지 않는다, 관리자 전용 버튼)는 그대로다.
- 교훈: UI 계약을 바꾸는 가지는 `src/runtime/gateway/test` 전체도 회귀 목록에 넣는다(대시보드 정적 자산을 읽는 시험이 거기 있다).

## 2026-10-01 · uncommitted · feat(bridge): idle 시계와 주행 카드 충전 플래그

- 변경: ros_bridge._reconcile_emotion 이 _idle_since 를 추적해 reconcile.emotion 에 전달. drive_payload 에 battery_status.charging 을 실었다.
- 증거: test_bridge_display.py 충전 플래그, test_bridge_reconcile.py 통과.
- gate 변화: 없음.

## 2026-10-01 · edca9b2e · feat(core): LiDAR 정면 — 운영자 오버레이가 레코드를 이긴다 (D-397)
- 변경: `core/lidar_mount.py` 순서가 운영자 오버레이(`line_follow.lidar_forward_deg`) > 승인 `lidar_mount` 레코드 > core.yaml URDF NOMINAL 180. 오버레이도 150–210°를 통과해야 하고(아니면 경고·무시), 어댑터 비교 경고는 남는다. `node.py`가 `local_overlay()`로 운영자 값을 넘긴다.
- 증거: `test_pinky_lidar_forward_device.py` 순서 테스트, `test_lidar_mount_source.py` 거부·어댑터 비교.
- gate 변화: SOURCE/LOCAL. DEVICE HOLD.
- 결정: D-397 Proposed(D-47 addendum 개정).

## 2026-10-01 · uncommitted · feat(bridge): 주행 카드에 내비게이션 목표 좌표

- 변경: drive_payload 가 goal_x·goal_y 를 실는다(NAVIGATION 중에만, 소수점 2자리). ros_bridge 가 nav.current_goal 에서 좌표를 가져온다.
- 증거: test_bridge_display.py 목표 좌표 2건.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(bridge,display): 주행 카드 도킹 상태 + hello 인사

- 변경: drive_payload 에 docking_state 를 실었다(DOCKING 중 DockState 값). ros_bridge._reconcile_emotion 이 CORE 기동 직후 10초간 hello 표정을 먼저 보낸다.
- 증거: test_bridge_display.py 도킹 상태 + 기존 전표 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(core): D-400 safety policy mode and shadow assembly
- 변경: `control.sensor_adapter.mode` off/shadow/enforce(`enabled` 호환, property), `build_control_adapter`(그림자 워커 시작 실패 → off + `mode_error`, 설정 오류는 모든 모드에서 예외, enforce는 `calibration.required` 거부·shadow/off는 경고 후 무시, shadow+`control_policy_required` 거부), `safety_params.py`(LiDAR = line_follow 값, 봉투 = CORE 속도 상한 쌍, overlay 허용 키·워커 타입/범위 검사, revision = 파라미터만), `safety_policy_status.py`(상태 `safety_policy` 블록), `node.py` 조립 순서(LiDAR → 안전 파라미터 → 어댑터 → 바인딩 → 상태 공급자).
- 증거: 전체 시험(gateway+services+foundation+api_web+test/) `5 failed, 5919 passed, 249 skipped, 31 warnings, 4 errors in 3428.70s`; `known_failures.py`는 exit 1: 9건 모두 이 브랜치가 건드리지 않은 시험이며(main 4804d417에서도 test_module_separation, test_release_boundary_guards, test_robot_literals, test_dashboard_drive 4건이 같게 실패, test_module_criteria C6와 test_behavior_test_ownership은 main이 이후 고쳤고 이 브랜치는 그 이전 기준) 이 브랜치 기인 실패는 0건.
- gate 변화: 없음. SOURCE만. 그림자는 어느 로봇에서도 켜지 않았다(기본 off).

## 2026-10-01 · uncommitted · feat(bridge,services): D-395 P2-1 스냅샷 localization 채움

- 변경: `ros_bridge.py` 가 `localization/state`·`candidates`(transient-local)·`result` 를 구독하고 `localization/decision`·`suspect`(reliable, depth 5)를 발행한다. `received_s` 는 ROS 시계. `_tick_state` 가 `_on_odom` 과 같은 신선도 규칙으로 frame 플래그를 넘긴다. `services.py` 가 `LocalizationAssist` 를 만들어 StateManager 에 live provider 로 걸고, LOCALIZED 진입·결정 수락 때 `nav.cancel(source="localization")` 을 부른다.
- 증거: `test/test_localization_api.py` 30, `test_bridge_timers.py`(구독 3·발행 2·latch 2 추가), `test_event_catalogue.py`.
- gate 변화: 없음(장치·sim 미검증; lane A 노드와의 통합은 P2-8).

## 2026-10-01 · uncommitted · feat(services): D-395 LOCALIZED 이탈 정지 조립

- 변경: `services.py` 가 `wire_assist` 로 LocalizationAssist 를 조립한다(LOCALIZED 진입 → Nav2 취소, 이탈 → 자율 주행 정지).
- 증거: `test/test_localization_api.py` +7 (Nav2·line-follow·swarm·도킹 정지, state_stale, teleop 유지, 도킹·follow 게이트, pre-D-395 무영향).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(bridge): D-395 리뷰 — SAF-005 귀환 게이트, 시작·정지 순서

- 변경: `battery_policy.py` — `RETURN_HOME` 은 `localization.gate` 안에서 `autonomy_allowed()` 를 보고, 아니면 보낼 수 없는 귀환과 같이 e-stop. `localization` 없는 서비스는 그대로.
- 증거: `test/test_bridge_battery_policy.py` +2, `test/test_localization_api.py` +2 (odom 프레임 거부, 검사와 시작 사이에 끼어든 정지가 시작 뒤에 접는다 — 잠금 제거 변이로 빨강 확인).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(bridge): D-394 주행 카드 reach 셋 삭제(C6) — 죽은 current_goal 판정

- 변경: CI 빨강(36877526967 등 3회 연속, 2026-10-01 14:28 원격 푸시부터)의 원인인 C6 reach 8종을 전부 삭제로 수정. snapshot.mode/navigation/docking 은 StateSnapshot 이 보장하는 선언 멤버(schemas.py)라 직접 접근으로 바꾸고, docking_state 는 pin 된 모드-맥락 계약(도킹 중에만 실린다)대로 고침. self._svc.nav.current_goal 은 NavigationManager 에 선언된 적이 없는 멤버 — 주행 카드의 목표 좌표는 태어나서 한 번도 값이 실린 적 없었다(죽은 reach). 읽기를 지우고 판정을 문서에 남긴다. 시험 stub 의 docking.state 를 실제 DockState enum 으로(문자열 이중 모양 제거).
- 근거: docs/plans/2026-09-06-module-split-criteria.md 행 추가(판정: 전부 Seam lie — deletion). test_module_criteria·test_bridge_display·test_bridge_reconcile·test_bridge_timers·test_emotion_map·test_goal_tracker 87 passed, flake8 초록.
- gate 변화: 없음. 목표 좌표 표시는 NavigationManager 가 current_goal 을 선언하는 커밋에서 돌아온다(직접 접근 + 실측 시험 동반).


## 2026-10-02 · uncommitted · feat(bridge): D-395 P2-7 미션 조립과 배선

- 변경: `services.py` 가 `wire_assist` 의 미션을 `loc_mission` 으로 든다. `ros_bridge.py`: 새 발행 `localization/mission`(신뢰, 깊이 5), `_on_odom` → `observe_odom`, 20 Hz line-follow 타이머 첫 줄에서 `loc_mission.tick()`(타이머 수 그대로). `observation.front_clearance` 가 LiDAR 표본을 미션에도 넘긴다(정면 여유는 미션이 필요할 때만 잰다). `docking_mode.route_nav_cmd_vel` 은 회전·전진 미션 중 Nav2 출력을 버린다. 직접 속성 접근(C6 새 reach 없음); 가짜 서비스 두 곳에 `loc_mission=None`.
- 증거: `test/test_localization_mission.py` 30, `test_bridge_timers.py` 발행 목록 +1.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(bridge): D-395 P2-7 미션도 line clock 으로

- 변경: `ros_bridge.py` 가 `loc_mission.bind_clock(self._line_clock)` — `use_sim_time` 이면 미션 시간 한도·센서 신선도가 sim 초로 잰다.
- 증거: `test/test_localization_mission.py::test_the_bridge_ticks_missions_on_the_line_clock`.
- gate 변화: 없음.

## 2026-10-02 · 00b806cb · fix(bridge): 지역화 시간을 로봇 노드 시계에 맞춤 (D-395 S1 finding 6)

- 변경: (d1d297d1, 00b806cb) `ros_bridge.py` 가 `localization.bind_clock(self._line_clock)` — `state_stale` 이 sim 초로 잰다. `received_s` 는 노드 ROS 시계 그대로: 두 노드가 use_sim_time 을 같이 쓰므로 sim 에선 sim 시각, 실기에선 epoch 시각이다(실기 line clock 인 monotonic 이면 로봇이 만료로 거부). `pose_frame` 을 정하는 2 s map-pose 신선도도 line clock 으로 찍고 재며, 초기값은 `-inf`(sim 시각은 0 근처에서 시작).
- 증거: `test/test_localization_cross_lane.py` +7 (sim·device 시계 각각: `received_s` 가 `RECEIPT_AHEAD_S` 안이고 수락됨, line clock 3 s 에 stale; device 에서 monotonic 수령 시각은 거부; 브리지 배선 AST 2).
- gate 변화: 없음.

## 2026-10-02 · 7a44f39d · feat(core): D-407 막힘 답 API와 CORE 배선

- 변경: `POST /api/v1/line-follow/stuck/decision`(Operator+, `STUCK_ID_MISMATCH`·`STUCK_DECISION_REFUSED` 409, MANUAL·ABORT 는 차선 추종 OFF 후 MANUAL·IDLE), `core/line_follow_wiring.py`(설정 파서를 services.py 에서 옮김 + FleetAgent 연결·보정 lease·수동 선속도·미리보기 순서번호 묶기), scan 브리지가 self-mask 점과 `range_min` 을 넘김. API Ref v1.72.
- 증거: `python -m pytest src/runtime/gateway/test/ test/architecture` 1780 passed, 17 skipped; `known_failures.py` 0 new.
- gate 변화: 없음. Fleet 콘솔·FleetAgent 답 중계는 다음 단계.

## 2026-10-02 · caa0d51d · fix(api): D-407 검토 반영 — MANUAL 답은 POST /mode 규칙, 답 감사에 토큰

- 변경: `/mode` 전이를 `common.apply_mode` 로 옮겨 MANUAL·ABORT 막힘 답이 같이 씀(보정 lease 를 막힘 소비 전에 확인, MANUAL 은 navigation·swarm 취소). `nav.line_stuck_answered` 에 `token_id`. 설정 형 검사(`recovery_local_enabled` 불리언만, `recovery_max_attempts` 정수·정수 float). sector 모드 몸 점은 막힘 근처에서만, scan `range_min` 없으면 None.
- 증거: `test_line_follow_stuck_api.py` 14 passed, line-follow·calibration·api 시험 초록.
- gate 변화: 없음.

## 2026-10-02 · b9f1b277 · test(localization): D-395 S1 R1 — LOCALIZED 물체 세 갈래 왕복

- 변경: 코드 변경 없음(브리지는 원문을 `LocalizationAssist` 에 넘긴다). `test_localization_cross_lane.py` 에 왕복 시험을 더했다. 로봇 A 의 LOCALIZED 상태에 실린 물체가 CORE `/api/v1/robot/state` 를 거쳐 Fleet `trust.status_of` 로 그대로 읽히고, 스캔이 1 s 넘게 묵으면 빈 목록이 된다.
- 증거: `test/test_localization_cross_lane.py` +1 (13 passed).
- gate 변화: 없음.

## 2026-10-02 · f341e9fd · feat(core): D-411 A 녹화 브리지 배선과 API 시험
- 변경: `bridge/ros_bridge.py` 가 `teleop/intent`·`pilot_recorder/fetched` 발행, `pilot_recorder/status` 구독, SetBool 클라이언트, 가드 배선(정지 재시도·확인된 정지). `core/services.py` 에 `pilot_recording`. `test_recordings_api.py` 로 권한·차단·짧은 본문·소유자 없는 정지·슬롯 해제를 고정.
- 증거: `python -m pytest src/runtime/gateway/test/test_recordings_api.py src/runtime/gateway/test/test_bridge_timers.py -q` → 29 passed (2026-10-02 Windows).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · 94a8b833 · fix(fleet_agent): hub 작업을 API 루프에서 시작

- 변경: `fleet.hub_url`+`pairing_token` 이 있으면 `CoreServices.build` 의 `fleet_agent.start()` 가 루프 없이 `asyncio.create_task` 를 불러 CORE 가 죽었다(D-407 Gazebo 2026-10-02). `create_app` 이 라우터 lifespan 을 감싸 uvicorn 루프에서 `start_on_loop()` 를 부른다. e-stop 리스너는 `line_follow.stop(reason="estop")`.
- 증거: `test_fleet_agent_startup.py`(core_client, hub_url 설정으로 build 후 startup 에서 작업 생성), `test_line_follow_stuck.py` 초록.
- gate 변화: 없음.

## 2026-10-02 · 8dd300c52 · feat(core): D-415 SAF-003 배선
- 변경: `core/fleet_loss_wiring.py` — `safety.fleet_loss_timeout_s` 검증(1–60 s, 기본 3), 저장된 정책 정규화(모르는 값→STOP, `CONTINUE_CURRENT_NAVIGATION`→`CONTINUE`), RETURN_HOME 을 SAF-005 와 같은 지역화 문으로. `services.py` 에 `fleet_loss` 필드, `ros_bridge._tick_power`(5 Hz)가 `tick()`. `fleet.enabled` 는 고치지 않고 읽히지 않음으로 문서화(D-415 결정 7).
- 증거: `test/test_fleet_loss_wiring.py` 10 passed(빌드 실패·정규화·PUT·REST Fleet 목표 정지·`safety/state.fleet_link`). test_event_catalogue·test_protocol_version_alignment·test_module_criteria·test/architecture 통과(core_features 크기 판정 11160 재판정). gateway+services+api_web 2537 passed 29 skipped 1 failed — `test_host_hardware.py::test_rows_rosy_io_holds_are_judged_from_fresh_topics`, 깨끗한 main(13e6d5e45)에서도 실패, known_failures.txt 에 없음(이 브랜치 무관).
- gate 변화: 없음.

## 2026-10-02 · 758f9878e · fix(core): D-419(구 D-415) 리뷰 반영 — 배선
- 변경: `fleet_loss_wiring` 이 '설정됨'을 빌드 때 한 번 정하고(`enabled` 가 뒤에 꺼져도 끊긴 링크), `last_rx` 를 넘긴다. `ros_bridge._tick_power` 의 `fleet_loss.tick()` 을 try/except 로 감쌌다. `services.py` import 순서.
- 증거: `test_fleet_loss_wiring.py` 14 passed(wiring RETURN_HOME 지역화 거절, 빌드 시 고정된 설정, PUT RETURN_HOME 경고, `_tick_power` 가드 구조 시험). 리뷰 지정 묶음 205 passed.
- 번호: 앞 항목들의 D-415(SAF-003)는 **D-419** 로 바뀌었다 — main 에 다른 D-415(콘솔 운영 가시성)가 먼저 들어왔다. ADR 파일 `docs/adr/D-419-saf003-fleet-link-loss-policy.md`.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(core): D-419 재리뷰 — 배선 타이밍, console_linked 디바운스
- 변경: `fleet_loss_wiring` 이 판정 시간과 답 시한의 관계를 검증(어기면 기동 실패)하고 Agent 의 `link_fresh_s` 를 모니터 신선도로 넘긴다. `line_follow_wiring` 의 D-407 `console_linked` 는 `connected` 이거나 허브를 링크 신선도 안에 들었으면 이어진 것으로 본다(재접속 깜빡임이 관제 대기를 건너뛰지 않게).
- 증거: `test_fleet_loss_wiring.py`(범위·관계·답 시한 빌드 실패, 기본 5 s 판정), `test_line_follow_stuck_api.py::test_console_link_is_debounced_on_recent_hub_traffic`. 재리뷰 지정 묶음 + line-follow 막힘 시험 250 passed.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(core): D-419 라운드 3 — Fleet 없는 로봇의 SAF-003 검증
- 변경: `fleet_loss_wiring` 이 판정 시간·관계 검증을 Fleet 링크가 설정된 로봇에서만 기동 실패로 하고, 아니면 경고 한 줄 뒤 기본 5 s.
- 증거: `test_fleet_loss_wiring.py` 21 passed(Fleet 있는 로봇 실패 6+2건, Fleet 없는 로봇 부팅 3건).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(core): D-419 라운드 4 — Fleet 링크 판정 함수 하나
- 변경: `fleet_loss_wiring` 이 Fleet 없는 로봇 판정과 모니터의 '설정됨'을 Agent 와 같은 `fleet_link_configured(config['fleet'])` 로 정한다.
- 증거: `test_fleet_loss_wiring.py` 21 passed.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · fix(core): D-419 착지 — console_linked 를 D-407 유예와 합침
- 변경: `bind_stuck_recovery` 의 `console_linked` 는 main 의 `linked_within(line_follow.recovery_console_grace_s)` **또는** D-419 `recently_heard()`(마지막 허브 수신이 링크 신선도 이내). 둘 다 재접속 깜빡임을 덮고, 앞은 끊긴 시각부터, 뒤는 마지막 수신부터 잰다.
- 증거: `test_line_follow_stuck_api.py`(D-419 디바운스 시험 포함), `test_fleet_loss_wiring.py`.
- gate 변화: 없음.

## 2026-10-03 · uncommitted · test(console): 지도 도구는 격자 밖에 둔다
- 변경: `test_the_map_tools_stay_off_the_raster`가 툴바를 무대 밖 한 행으로, 범례를 캔버스 아래로 고정한다. 절대 위치 겹침 게이트는 뺐다.
- 근거: D-77 운용 화면. 격자를 가리던 배치를 계약으로 되돌리지 않기 위해서.
- 증거: 2026-10-03 Windows. test_the_map_tools_stay_off_the_raster가 콘솔 묶음 240 passed 안에 포함된다.
- gate 변화: 없음.

## 2026-10-03 · f4c311569 · feat(bridge): D-423 모델 상태 두 토픽 latched 구독

- 변경: `ros_bridge.py` `_on_lane_model_status`·`_on_object_det_model_status`(TRANSIENT_LOCAL) → `svc.vision.models`. 구독 목록·latched 시험 갱신. `test_core_logic` D-137 단일 발행자에 `runtime/sensing/control/object_detector.py`.
- 증거: gateway 두 묶음 1141+715 passed; 실패 `test_core_node_teardown::test_run_drains_executor_workers_before_returning` 1건은 부하 아래에서만(단독 8 passed).
- gate 변화: 없음.

## 2026-10-03 · e021264e6 · feat(face): D-433 CORE가 rosy-face에 얼굴 핸드오버를 쓴다

- 변경: 브리지 5 Hz 전원 틱에서 `/run/rosy/face-inputs.json`을 바뀔 때와 1 s마다 쓴다(`display.face_inputs_payload`·`face_inputs_due`, `host.write_face_inputs` 0644 강제). 얼굴 이름은 `set_emotion` 서비스 유무와 무관하게 `emotion_for`로 정한다. `display.drive_due`는 `core_common.face_screen`을 다시 내보낸다.
- 증거: `python -m pytest src/runtime/gateway/test/test_face_inputs.py src/runtime/gateway/test/test_bridge_display.py -q` 통과. ros_bridge.py는 rclpy 없이 import할 수 없어 py_compile만.
- gate 변화: 없음. 실기 확인 전.
- 결정: D-433 (Proposed)

## 2026-10-03 · uncommitted · feat(link): D-432 주소 없는 장비 접속

- 변경: 선택적 CORE TLS를 listener 이전에 검증하고 shutdown에서 공유 발견 캐시를 닫는다. 4자리 코드와 LAN 장비 목록 admission 시험을 추가했다.
- 증거: 관련 Python 계약 시험·실제 loopback TLS HTTP/WS 시험을 실행했다. Pilot Android 설치·화면과 실제 로봇 연결·현장 트래픽 수용은 서로 다른 증거다.
- gate 변화: 실제 장비의 제어·FIELD 관문은 이동하지 않는다.
- 결정: D-432 2026-10-03 추가 결정.

## 2026-10-03 · uncommitted · fix(link): 현재 접속과 후속 코드 규약 구별

- 변경: 사용자 보정으로 4자리 코드 발급·Cam 표시 별칭은 이번 적용에서 제외했다. 현재 로봇 8자·Cam 6자리 규약을 유지하며 D-432에 추후 통합을 기록했다. 실제 Pinky 접속 수정은 진행한다.
- 증거: 영향받는 Python 2345 passed/84 skipped, quick tier 459 passed/2 skipped, Pilot PWA 87 passed/58 skipped. 코드 규약 보정 뒤 해당 인증·페어링 시험을 다시 실행한다. 공개 검증 기록은 docs/validation/discovery-link-2026-10-03/README.md.
- gate 변화: Android 설치·실제 CORE 인증 확인은 실제 주행·Cam 화면 off 연속 송출·현장 트래픽 수용과 별개다. DEVICE/FIELD 이동 없음.
- 결정: D-432 후속 결정: 접속은 지금, 짧은 코드 통합은 추후 적용.

## 2026-10-04 · uncommitted · D-442 U2 Pinky single-use binding

- 변경: cmd_vel_cycle에서 원본 GuardedMotion만 한 번 풀어 기존 send를 부르는 얇은 포트를 연결했다. private token·identity·불변 snapshot·300ms/주기 만료와 consume-before-send를 적용했고 생성 실패는ZERO다. bridge와 publish/D-422 순서는 유지했다.
- 증거: RED11 및 독립리뷰RED2 보완 후 관련137 passed/1 ROS skip·NEW0, 구조76 passed, 실제설치Linux53 passed, 독립28 passed·APPROVE. docs/validation/d427-source-migration/pinky-twist-port-2026-10-04.md.
- gate 변화: 없음. SOURCE/host만 검증했으며 ARM64/SD/Docker/CI/ROS-SIM/DEVICE/FIELD와 전체profile/OMX 타입admission은 pending이다.


## 2026-10-04 · uncommitted · fix: D-427 push5 통합 게이트 정합성

- 변경: 운영 시나리오에서 MANUAL 해제를 실제 IDLE API로 명시했다. Fleet 재명령 문구는 의도를 한국어로 표시하고, CORE image closure는 정확한 ROS 열 개와 계약 wheel 두 개를 분리 검증한다. 운영 MANUAL·신호 감독 가드는 바꾸지 않았다.
- 증거: Python 집중 35 passed, 추가 구조/Fleet 97 passed, Node 전체 109 passed. 실제 입력 누락·colcon 오배치·raw enum 표시 mutation 네 건 RED 뒤 원본 bytes 복원·GREEN. 알려진 실패 0 new, backlog 증가 없음. `docs/validation/d427-source-migration/push5-gate-corrections-2026-10-04.md`.
- 독립 리뷰: d427_safety_review APPROVE source/host, 별도 Python 22 passed·Node 3 passed. Fleet +12 줄은 기존 +150·split 판정 안에 있고 예산·allowlist를 늘리지 않았다.
- gate 변화: SOURCE/로컬 증거만 추가한다. 새 pre-push·원격 CI·ARM64·SD·기기·현장 수락은 후속이다.

## 2026-10-04 · uncommitted · feat(vision): 원본 조도와 얼굴 handover

- 변경: JPEG metadata의 원본 low_light quality를 기존 front/status에 전달한다. legacy·malformed·stale는 null이며 JPEG는 유지한다. face-inputs에 camera_quality와 JPEG 수신 나이를 전달하고 reader가 handover 나이를 더해 만료한다. read-only 표시로서 이동 권한은 아니다.
- 증거: preview·bridge·schema·face handover·CORE focused 143 passed, 1 skipped; 회귀 55 passed.
- gate 변화: SOURCE/LOCAL. 실제 조명 보조 동작은 별도 기기 증거다.

## 2026-10-04 · uncommitted · feat(bridge): typed 녹화 시작과 원본 JPEG admission

- 변경: pilot_recorder/start typed service에 RAW0/ANNOTATED1만 전달하며 legacy SetBool 정지는 유지한다. camera/preview/raw/compressed를 별도 read-only 구독하고 ROS capture clock을 검증한다. 오래된 원본은 거절, 기존 JPEG는 조도만 unknown으로 표시한다. final cmd_vel 소유권은 변경하지 않는다.
- 증거: 실제 Bridge wiring registry와 typed0/1 transport, CORE API readback·원본/주석 header 및 source age 검증 포함162 passed,1 skipped.
- gate 변화: SOURCE/LOCAL. ROS service 설치/실기 녹화 확인은 root 배포 단계에서 수행한다.

## 2026-10-04 · uncommitted · fix(vision): preserve fresh overexposed quality
- 변경: 원본 조도 invalid reason overexposed를 preview store, API protocol, face handover sanitizer에 전달한다. low_light 조명 허용 범위와 2초 촬영·수신·handover 신선도는 유지한다.
- 검증: 과다 노출 관측을 버리는 RED 3 failed; API·handover·stale 회귀 포함 GREEN은 X:/DevTemp/rosy-lane-device-20261004/overexposed-api-green.txt. 배포·실주행 미검증, 명령 전송 없음.
- 추가 검증: face handover integration RED 1 failed로 display whitelist 누락을 확인·수정. 최종 focused 129 passed, 3 skipped (overexposed-api-green.txt).

- gate 변화: SOURCE/LOCAL. 실기 노출·조명·주행은 별도 검증이다.

## 2026-10-04 · uncommitted · test: 카메라 프레임 모듈의 실제 제공 경로

- 변경: Dashboard 카메라 계약을 분리된 shared frame 모듈의 import와 실제 제공 bytes, 인증·취소·late frame guard에 연결했다.
- 증거: Dashboard·role surface·paired camera 회귀 47 passed. 기존 API·동작·권한 검사를 약화하지 않았다.
- gate 변화: SOURCE/LOCAL. 실기 화면 검증은 별도다.


## 2026-10-04 · uncommitted · feat(power): fresh battery evidence and idle saving

- 변경: 반복 저배터리 표본의 wake를 단계 변화로 제한하여 기존 IDLE/STANDBY 타이머가 동작한다. Viewer GET /api/v1/power/health와 공유 typed 응답에 배터리·충전 확인 age, 정책 상한·wake 근거, shutdown 요청, 진단 요약을 제공한다. API Ref v1.92, envelope 1.0 유지.
- 검증: injected clock 회귀와 auth/read-only API, 기존 배터리·정지·sentinel 경로 검증. 최종 근거는 docs/plans/2026-10-04-power-health-and-wake.md. OS halt·EEPROM·GPIO·기본 LiDAR 모터 정책 변경 없음.
- gate 변화: SOURCE/LOCAL; 실제 소비전력·충전·RTC/외부 버튼 wake와 배포는 미검증.


## 2026-10-04 · uncommitted · feat(power): long testing dwell with low battery saving

- 변경: 정상 IDLE/STANDBY 기준을 600/1800초로 늘리고 warning60/300, critical/deep30/120초와 min을 취한다. YAML override·API effective timers에 연결한다. 기존 이동·정보 hold·disabled와 배터리 정지/종료 권한을 유지한다.
- 증거: 주입 시계·설정 parser RED3 failed, 전원/배터리/bridge GREEN180 passed. 구조 재판정은 docs/plans/2026-10-04-power-health-and-wake.md에 기록한다.
- gate 변화: SOURCE/LOCAL. 기기 소비전력·물리 wake·배포 검증은 별도다.

## 2026-10-05 · uncommitted · feat(core): 수신 승인용 신뢰 anchor와 보조 runtime

- 변경: 기존 TLS cert/key 설정에 선택적 공용 CA를 더하고 실제 hostname·CA·leaf chain을 검증한다. device CORE는 현재 서명 release의 고정 암호화 wheel 경로만 활성화하며 ROS/learning 전역 Python과 D-189 base runtime 해시는 유지한다.
- 증거: 실제 CA·hostname 실패와 보조 import-root·쓰기 권한·startup hook 거부를 포함한 통합 32 PASS. 호스트 시험은 native ARM import나 로봇 TLS 설치 증거가 아니다.
- gate 변화: SOURCE/LOCAL만. 외부 client가 ROS를 직접 말하거나 최종 cmd_vel·정지·제어 lease를 우회하는 경로를 추가하지 않는다. ARTIFACT/DEVICE/FIELD 확인은 남아 있다.

## 2026-10-05 · uncommitted · feat(services): D-368 vision_stream 배선

- 변경: `core/services.py` `CoreServices`에 `vision_stream: DriverStreamGate` 필드(default_factory) 추가. `gateway/test/test_vision_stream.py` 추가 — core_client 팩토리로 실제 CoreServices 위에서 스트림 라우트 계약(401·409·새 sequence만·운전자 교체·연결 종료)을 검증. 무한 응답을 TestClient portal과 함께 쓰면 교착이라 생성기 직접 반복으로 검증한다(파일 머리말에 근거 기록).
- 증거: test_vision_stream 8 PASS + 게이트 단위 5 PASS + test_api·v1 import boundary·api_web 155 PASS. known_failures 대비 신규 실패 0.
- gate 변화: SOURCE. 로봇 위 동작(arm64 부팅·실기 영상)은 주장하지 않는다.

## 2026-10-05 · uncommitted · test(pairing): 구버전 인증서 API 거절 회귀

- 변경: verifier와 신규 UTC 날짜 속성이 없는 인증서 형태를 주입해 명시적 ValueError 거절을 확인한다. 유효한 인증서 검증 시험은 그대로 유지한다.
- 증거: 수리 전 1 failed/3 passed로 검사 순서 문제를 재현했고 수리 후 관련 TLS·CI·버전 19 passed를 확인했다.
- gate 변화: SOURCE/LOCAL 회귀 증거. DEVICE 연결 수용은 별도다.

## 2026-10-05 · uncommitted · feat(command): cumulative bounded trial

- 변경: private trial ledger, original odom stamp/frame and final CORE port restriction; no second publisher/API/config activation.
- 증거: synthetic guard26PASS, installed geometry/CORE independent180PASS/NEW0. Actual measurement/braking UNKNOWN, no motion or push.
- gate 변화: SOURCE/LOCAL only; HOLD/readiness retained. Plan docs/plans/2026-10-05-core-bounded-camera-trial.md.


## 2026-10-05 · uncommitted · fix(core): 제한 시험 STOP와 최종 제출 직렬화

- 변경: 소유자가 미확정 양수 제출 의도를 먼저 영속화한 뒤, canonical SQLite `BEGIN IMMEDIATE`와 같은 소유자의 `RLock` 안에서 최종 STOP·신선도 확인부터 기존 `PinkyTwistPort.submit` 콜백까지 유지한다. 공개 `permits` 판정은 제출 권한이 아니며 production bridge는 `submit_fenced`를 사용한다. 다른 연결의 STOP·재개장은 제출 전후로 직렬화되고 잠금 실패는 양수 제출을 거부한다.
- 증거: 실제 SQLite에서 허가 확인 뒤 확정된 STOP에도 0.04가 제출되던 회귀와 writer 중 재개장 허용 회귀 RED 2 FAIL. 동일 소유자·별도 연결의 실제 threaded STOP, 기존 bounded/cmd_vel 시험 GREEN 43 PASS 2.44초 (`X:/DevTemp/rosy-ui-ship/trial-fence/final-tests.log`). 미확정 송신·영속화 실패는 기존 정지 래치를 유지하고 양수 재시도하지 않는다.
- gate 변화: 이 변경의 SOURCE/LOCAL 검증만. 실기 이동·제동·거리 bounds, ARM 산출물·배포·FIELD 수용은 미실행이며 기존 제한 시험은 안전 승인이나 public API/config 활성화가 아니다.

## 2026-10-05 · uncommitted · test(core): D-184 제한 시험 소유 경계 복구

- 변경: ledger·envelope·pose freshness·재개장 순수 정책 검사 10개를 services의 `test_bounded_trial_owner.py`로 옮겼다. 소유자 검사 helper는 실제 `submit_fenced`와 합성 callback만 사용하고 gateway를 import하지 않는다. 기존 테스트 함수 20개의 AST·단언은 모두 보존하며, bridge 최종 제출·준비 상태·미확정 응답·odometry·camera mux·STOP 경합 및 envelope 변조의 bridge 예외 처리는 gateway의 나머지 10개 함수가 검증한다. runtime·frozen 예외 목록·소유권 검사 구현은 바꾸지 않는다.
- 증거: 정규 push의 D-184 실패를 exact RED 1 FAIL로 재현했다. 최종 소유자·gateway 제한 시험·기존 cmd_vel·D-184 검사 44 PASS/2.16초, services 단독 19 PASS/1.13초. 중간 envelope 변조 검사는 owner 예외를 bridge의 ZERO와 혼동하여 1 FAIL이었고 gateway에 원문 그대로 되돌렸다. 원본 실패와 최종 로그는 X:/DevTemp/rosy-ui-ship/trial-fence/ownership-*.log에 보존한다.
- gate 변화: SOURCE/LOCAL 검사 배치만. runtime bytes·권한·서명·실기 bounds·장치 상태·배포 수용은 변경하지 않는다.

## 2026-10-05 · uncommitted · feat(bridge): validate optional lane containment
- 변경: CAMERA_LINE 원본 영상 시각과 지면 출처에 맞는 optional containment만 LineObservation에 허용한다.
- 증거: 관련 source 입구/manager/새 계약·정책 76 PASS, 0 NEW.
- gate 변화: 파싱 입구 추가만. 실제 pose 연결·자동 복구 명령·배포/현장 수용은 아직 없음.

## 2026-10-05 · uncommitted · feat(bridge): preserve odom source identity for lane return
- 변경: 원본 odom header·정규화 quaternion·동일 planar body frame을 검증하여 lane manager에 전달한다. 시간·자세 변환을 추정 명령 적분으로 대체하지 않는다.
- 증거: 관련 기존 bounded-trial/bridge/line-follow/새 evidence 및 구조 검사 109 PASS, 0 NEW. 원본 rotation 무효화 세 경우를 RED로 재현하고 검증 추가 후 통과했다.
- gate 변화: source callback 연결. 장치 설치·자동 복귀 명령·실제 복구 수용은 아직 없음.

## 2026-10-05 · uncommitted · fix(bridge): D-468 구조 검사 정렬

- 변경: 공통 odometry 브리지의 프레임 전제에서 기종명을 제거하고, 원본 헤더가 실제 관리자까지 전달되는 교차 경계 시험을 D-184 예외 목록에 근거와 함께 등록했다.
- 증거: 동작 시험 소유 및 로봇 리터럴 계약 검사 재실행. 제어 동작 변경 없음.
- gate 변화: 없음.

## 2026-10-05 · uncommitted · feat(bridge): query leased current floor evidence for return
- 변경: enforce sensor adapter에서만 LiDAR·IMU·IR 유효 기간에 묶인 현재 바닥·후보 제한 판정을 조회한다. 부분 stream 설정·shadow/off·종료·예외·비 boolean 허가는 거부한다.
- 증거: 신규 query와 기존 adapter/구조 검사 105 PASS, 0 NEW. 독립 SOURCE/크기 검토도 105 PASS, 0 NEW.
- gate 변화: 센서 판정 seam만. CORE swept path·바닥 경로 검증 전에는 실제 복귀 이동 공급자로 연결하지 않는다.

## 2026-10-05 · uncommitted · fix(ci): D-468 센서 경계 시험과 C6 기록

- 변경: gateway 시험은 provider 원래 clock·candidate 전달과 strict boolean 거부만 검증한다. 실제 센서 lease·floor 판단은 perception 소유 시험에서 유지한다. 공개 local_return_allowed 연결의 기본 거부 계약을 C6 triage와 동일 커밋으로 기록한다.
- 증거: ownership+gateway 6 PASS, 실제 센서 판단 26 PASS, C6 1 PASS. 제품 안전 판단 변경 없음.
- gate 변화: SOURCE/HOST 경계 검증만. 실제 주행 수용 없음.

## 2026-10-05 · uncommitted · feat(bridge): bind D-468 motion evidence into CORE
- Change: CORE now binds local lane-return candidates to the live enforced floor/sensor verdict and the manager's fresh full-circle LiDAR swept-body check. Unknown provider failures deny the candidate.
- Evidence: gateway/scan/bridge integration checks 151 PASS, 0 NEW; host source only. No ROS-SIM, device, release, or field result.
- Gate: source wiring present; deployment and physical recovery remain pending.

## 2026-10-05 · uncommitted · fix(bridge): document D-468 scan provenance seams
- Change: update the C6 seam triage for the policy capability probe and LaserScan angular/source-time fields; keep non-recovery scan mocks explicit about not requesting D-468 scans.
- Evidence: affected gateway checks 43 PASS, 0 NEW. A broader gateway run had 2163 PASS, 17 SKIP, and two failures in these expectation/triage checks before the fixes; the full suite was not rerun afterward.
- Gate: source and host tests only; no runtime/device/field result.

## 2026-10-05 · uncommitted · fix(bridge): C6 센서 공급자 선택 기능 판정 기록

- 변경: `local_return_allowed`의 동적 조회를 D-468/C6 예외 목록에 명시하고, 구 공급자에 메서드가 없을 때 복귀 후보를 거부하는 검사를 추가했다.
- 증거: C6 구조 검사와 차선 복귀 센서 검사. 최종 명령 권한 변경 없음.
- gate 변화: 없음.

## 2026-10-06 · uncommitted · feat(sim): simulation_sensors 플래그와 D-468 정책 시계

- 변경: `control.sensor_adapter.simulation_sensors`(bool, `use_sim_time` 없으면 시작 거부)가 `resolve_safety_params(simulation=True)`로 worker에 `accept_simulation_scans`·`imu_angular_velocity_unit rad_s`·`use_sim_time`을 넘긴다(overlay 허용 키 아님). `bind_lane_return_motion(policy_clock)`: `use_sim_time`이면 D-468 바닥 증명은 worker 정책을 `time.monotonic`으로 묻고 몸 sweep은 line clock에 둔다. 장치는 플래그 없음·`policy_clock None`으로 전과 같다.
- 증거: `test_safety_params.py`, `test_lane_return_sensors.py`, `test_control_sensor_adapter.py` 추가 시험 PASS. 모델 PC sim에서 정책 창 monotonic·`floor_observed True` 확인.
- gate 변화: 없음.

## 2026-10-07 · uncommitted · feat(bridge): D-494 2 odom 콜백이 odom_pose를 채운다

- 변경: `ros_bridge._on_odom`이 odom 메시지마다 `state.set_odom_pose`를 부른다. `pose` 소유 규칙(`odom_owns_pose`)은 그대로다. 시각은 ROS 헤더가 아니라 CORE 수신 벽시계다(sim time이어도 UTC로 남는다).
- 증거: 호스트는 `ros_bridge.py`를 import하지 않는다. 상태 쪽 시험은 services `test_state_odom_pose.py`. `test_capabilities_controls.py`에 D-494 1 시험 2개 추가. gateway 2181 passed·17 skip, known_failures 0 new.
- gate 변화: 없음. ROS-SIM·DEVICE 미확인.
- 결정: D-494 (Proposed)

## 2026-10-07 · uncommitted · feat(bridge): keep_debug 교차로 사유를 line-follow 정지 입력으로
- 변경: `bridge/observation.py` `keep_junction`이 `line/keep_debug`의 `reason`(`junction_transverse`·`junction_fork`)과 카메라 시각(`stale_after_s` 안)을 읽어 `observe_junction`에 넘긴다. 정지 입력으로만 쓴다. `ros_bridge.py`의 기존 구독에 한 줄 붙임
- 증거: `test_line_junction.py` 18 PASS, `test_line_junction_api.py` 8 PASS. services·api_web·contracts/foundation·line-follow 문서 시험 1859 PASS·18 skip, gateway 2187 PASS·17 skip, Fleet 버전 고정 시험 90 PASS, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음. SOURCE 호스트 시험만. 실기·SIM 미실행(Gazebo는 이 노트북에서 돌리지 않음)
- 결정: D-494 (Proposed) 4항, 구현 부록 2026-10-07
- 교훈: 오늘 인식은 CORE에 분기 후보를 주지 않는다. 좌·우 주행은 분기 계약 ADR이 먼저다

## 2026-10-07 · uncommitted · test(line_follow): D-495 bridge 로봇 기본값 켜짐 고정
- 변경: `rosy_default.yaml` `bridge_enabled: true`(D-495). 고정 시험이 켜짐과 CORE 설정 겹으로 끄기를 확인한다. bridge는 여전히 `recovery_local_enabled`(기본 꺼짐)가 필요하다
- 증거: `test_line_junction.py` 44 PASS, `test_line_junction_api.py` 9 PASS. services·api_web·contracts/foundation·line-follow 문서·perception 배선 1968 PASS·18 skip, gateway 2188 PASS·17 skip, perception 2704 PASS·109 skip, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음. SOURCE 호스트 시험만. SIM(모델 PC map_v2_fleet_real)·DEVICE 미실행
- 결정: D-495 (Proposed), 구현 메모 2026-10-07
- 교훈: 기본값을 켜는 ADR은 그 값의 전제(`recovery_local_enabled`, keep 모드)와 되돌리기 경로를 코드로 확인해야 한다

## 2026-10-07 · uncommitted · feat(line_follow): D-495 recovery_local_enabled 기본 켜짐과 keep 증거
- 변경: `keep_junction`이 `corner_turning`을 넘긴다. `rosy_default.yaml` `recovery_local_enabled: true`(D-495 개정). 고정 시험: 기본 켜짐, 겹으로 끄기, 끈 로봇의 `local_recovery_disabled`, 일반 기본의 `body_geometry_unset`
- 증거: services·api_web·contracts/foundation·line-follow 문서·perception 배선/lane_keep 1969 PASS·18 skip, gateway 2190 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows; 동시 실행 중 `test_site_rooms.py` 자식 프로세스 시간 시험 한 번 실패, 단독·재실행 통과)
- gate 변화: 없음. SOURCE 호스트 시험만. SIM·DEVICE 미실행
- 결정: D-495 (Proposed) 결정 개정 2026-10-07
- 교훈: 인식 파라미터는 CORE 설정이 아니다. 능력 판정은 살아 있는 증거로 한다

## 2026-10-07 · uncommitted · fix(bridge): D-495 검토 L3 keep_debug 문서
- 변경: `keep_junction` docstring: 감지가 이제 회전 시작도 가르므로 0.3 s 지연 한도를 명시. `junction_reacquire_frames`·`junction_turn_lead_s` 설정 파싱
- 증거: services·api_web·contracts/foundation·line-follow 문서·perception 배선/lane_keep·Gazebo launch 고정 시험 2007 PASS·18 skip, gateway 2192 PASS·17 skip, 문서 시험 1 PASS, `test/known_failures.py` 0 new (2026-10-07 Windows). 검토 탐침 `probe_lag.py`·`probe_junction.py` 재실행
- gate 변화: 없음. SOURCE 호스트 시험만. SIM·DEVICE는 D-495 수용 점검표
- 결정: D-495 (Proposed) 독립 안전 검토 반영 2026-10-07
- 교훈: 지연이 있는 odom 위의 닫힌 고리는 지연 보정과 머무름 확인이 있어야 허용 오차를 지킨다

## 2026-10-07 · uncommitted · fix(bridge): ControlSensorAdapter.return_proof_configured
- 변경: `return_sensor_allowed`의 상시 조건(enforce, LiDAR·IMU·IR 필수, 바닥 정책)을 메서드로 뽑았다. `bind_lane_return_motion`이 그것을 junction_turn 능력의 근거로 넘긴다(getattr 없이, C6)
- 증거: services·api_web·contracts/foundation·문서·perception 배선/lane_keep·Gazebo launch·test/architecture 2196 PASS·19 skip, gateway 2211 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음
- 결정: D-495 (Proposed) 착지 전 검토 반영
- 교훈: 능력 보고는 그 동작을 실제로 허가할 증거와 같은 조건이어야 정직하다

## 2026-10-08 · uncommitted · fix(bridge): 카메라 원본 시각도 하나의 미래 허용치를 쓴다 (D-507 8)
- 변경: `bridge/observation.camera_preview`가 CORE 시계보다 앞선 영상(음수 나이)을 낡은 것으로 보던 것을 `SOURCE_FUTURE_TOLERANCE_S`(0.1 s) 안이면 나이 0으로 받고, 넘으면 전처럼 품질을 버리고 raw를 거절한다.
- 증거: `test_bridge_observation.py::test_camera_capture_stamp_ahead_of_core_clock_counts_as_now_within_the_tolerance`.
- gate 변화: 없음. 호스트 시험만.
- 결정: D-507 8
- 교훈: 없음

## 2026-10-08 · uncommitted · fix(bridge): 점유 지도 수신 시 ID와 격자를 묶음
- 변경: `_on_map`은 수신 격자와 그때의 map ID를 같이 저장한다. 이후 상태 map ID가 바뀌어도 API가 오래된 격자를 새 지도처럼 말하지 않는다.
- 증거: `test_map_snapshots.py` 11 passed, [로봇 지도 화면 검증](../../../docs/validation/uiux-robot-navigation-stage-2026-10-08/result.md). ROS 실기 수신은 미확인.
- gate 변화: LOCAL 스냅숏 계약 근거 추가. DEVICE/FIELD는 HOLD.

## 2026-10-08 · uncommitted · fix(bridge): 경로 frame과 지도 ID 수신 근거 보존
- 변경: `nav_msgs/Path.header.frame_id`와 수신 시 로봇 map ID를 점 좌표와 함께 스냅숏에 전달한다. 좌표계가 map이라고 확인되지 않은 경로는 로봇 지도에 그리지 않는다.
- 증거: 지도·브리지 41 passed, [로봇 지도 화면 검증](../../../docs/validation/uiux-robot-navigation-stage-2026-10-08/result.md). ROS 실기 수신은 미확인.
- gate 변화: LOCAL 경로 출처 근거 추가. DEVICE/FIELD는 HOLD.

## 2026-10-08 · uncommitted · fix(device identity): system/info에 프로비저닝 UID 노출

- 변경: `GET /api/v1/system/info`에 `device_uid`를 추가하고 Pi 시리얼을 `serial_number`로 읽는 계약을 API v1.150에 기록했다. 기존 Fleet 등록 DB는 자동 변경하지 않는다.
- 증거: 관련 CORE/계약 테스트 97 passed, 신규 실패 0; 현장 실기 API 판독은 배포 후 확인.
- gate 변화: SOURCE/LOCAL 확인, DEVICE/FIELD 미확인.

## 2026-10-09 · uncommitted · feat(core): D-541 trip lease 배선
- 변경: `core/trip_lease.py`(`TripLeaseManager` + `build_trip_lease`), `CoreServices.trip_lease`. 모드 리스너가 NAVIGATION 밖으로 가는 모든 전이에서 lease를 끝낸다(EMERGENCY는 `estop`, 나머지 `mode_left`), e-stop 리스너도 끝낸다. `halt_trip`이 만료·넘겨받기·주인 아닌 멈춤에서 IDLE로 둔다. `ros_bridge._tick_power`(5 Hz)가 `trip_lease.expire_due()`를 부른다.
- 증거: `test/test_trip_lease.py` 만료·비상 정지·도킹 시험.
- gate 변화: SOURCE.

## 2026-10-09 · uncommitted · feat(core): D-531 경로 문맥 발행

- 변경: `ros_bridge`가 기본 꺼짐 설정에서 경로 문맥 토픽을 만들지 않는다. 켜면 VOLATILE/RELIABLE depth 1로 5 Hz 문맥을 발행하고 지시 소실·E-Stop·시계 역행에 clear를 보낸다. 인식 증거의 `route_context_seq`가 현재 지시와 다르면 거절한다.
- 증거: gateway 전체 2421 passed/17 skipped, API 문서 버전 문자열 1건 실패를 수정한 뒤 관련 34 passed·`known_failures.py` 신규 실패 0. ROS 2 DDS·SIM·DEVICE는 아직 재실행하지 않았다.
- gate 변화: D-531 P1 SOURCE 후보. 실제 주행 허가 변화 없음.

## 2026-10-09 · uncommitted · fix(core): 문맥 전환의 현재 지시 확인

- 변경: 인식 콜백이 마지막 발행 seq 대신 그 순간 CORE의 지시/호 seq를 확인한다. 다른 번호의 관측은 즉시 무효화하고 교차로 감지는 버린다.
- 증거: gateway 관련 46 passed, 독립 안전 검토, 문서/구조 36 passed. ROS 그래프는 미검증.
- gate 변화: P1 SOURCE 후보.

## 2026-10-10 · uncommitted · feat(face): D-583 질문과 회전을 인계에 싣는다
- 변경: `face_inputs_payload`가 stuck·reason·angular·junction으로 `signal`을 만든다. 없는 필드는 신호 없음.
- 증거: `test_face_inputs.py`.
- gate 변화: SOURCE.
- 결정: D-583

## 2026-10-10 · 48de3f65c3 · feat: D-620 교차로 Fleet 신호 질의

- 변경: paired heartbeat에 교차로 요청 ID와 신호 응답을 연결. 완전 무응답 3초만 기존 CORE 우측 회전을 선택하고 명시적 red/unknown/오류/만료 답은 대기한다. 기본 꺼짐.
- 증거: AI PC 원격 교차로·FleetAgent·hub·신호표·API·횡단보도 관련 273 passed, known_failures 0 NEW. docs/validation/junction-signal-2026-10-10/result.md 참조.
- gate 변화: focused SOURCE/원격 계약 증거만 추가. 새 ARM64 payload/Fleet 이미지와 DEVICE/FIELD는 미확인. 기존 전역 게이트 수용을 올리지 않는다.

## 2026-10-11 · 5faad3583 · refactor: CORE Drive 조립 책임 분리

- 변경: D-627 core/drive의 line-follow 배선·docking/swarm 조립을 추출하고 legacy import와 CoreServices 공개 attribute·동일 객체·listener 순서를 유지했다. services.py는 481줄이다. 새 배선 Safety 추적과 앵커 4개를 등록했다.
- 증거: 추출 전 원격 257 성공, 후보 전체 CORE와 실제 wheel 설치 2575 성공·10 skip, feature 1675 성공. 독립 Safety source 승인과 최초 구현 trailer, 현재 holder를 따르는 종료/사건 scanner 검증. 세부 결과는 docs/validation/d626-holder-migration-2026-10-11/result.md.
- gate 변화: 없음. 기존 ROS-SIM evidence를 이 후보에 확대하지 않는다. 새 graph·ARM64·장치·현장 수용 미확인.

## 2026-10-12 · uncommitted · 정지 기동 시 교통 정책 snapshot 일치

- 변경: CoreServices가 교통 관리자를 생성한 직후 실제 status를 StateManager에 반영한다. 관측·주행 tick이 없어도 기본 DISABLED 값이 활성 설정을 가리지 않는다. 명령·정책 gate는 변경하지 않는다.
- 증거: A21 설정 ENFORCED와 snapshot DISABLED 불일치를 추적했다. 기본 snapshot 초기값과 비활성 line-follow tick의 early return을 확인했다. 세 모드의 관측 없는 기동에서 API 관리자 status와 snapshot 일치·HOLD/no_road_evidence 보존 회귀를 추가했다. 원격 시험과 native 직접 readback은 아직 미확인이다.
- gate 변화: 없음. 신호·위치·도로 증거·명령 admission과 완주 수용은 기존 기준을 유지한다.

## 2026-10-12 · 077d2e475 · API 시작 전 유효 주행법칙 handover 기록

- 변경: 기존 schema2·원자 기록·0644 status-inputs에 CORE 주행법칙 4개와 robot/process 식별만 추가했다. 인증정보나 개인 설정 접근 권한은 변경하지 않는다. native 수신은 오래되거나 신뢰할 수 없는 입력을 거절하고 법칙·epoch 변경 시 조향과 기억 경로를 초기화한다.
- 증거: 독립 SOURCE APPROVE, 유효 자원 기준의 startup/handover 183 PASS·NEW 0, 전체 관측 3,140 PASS/110 SKIP·NEW 0이다. 실제 장치 시험은 수행하지 않았다.
- gate 변화: 소스·회귀만 확인했다. API 시작 전에 초기 기록하며 쓰기 실패의 기존 정책과 최대 3초 신선도 창은 유지한다. Gazebo 지도 완주와 실물 수용은 미확인이다.

## 2026-10-12 · uncommitted · feat(face): D-719 발행된 주행 사유를 얼굴 노트로

- 변경: `face_line_note`가 발행된 `line_follow.reason`만 본다. `crosswalk_`와 `ir_guard_crosswalk`는 횡단보도, 차선 가장자리 셋은 차선 가장자리, `stuck_yield`는 양보다. 그 이름으로 붙은 HOLD는 선 소실 주의를 내지 않는다. 각속도가 있는 양보는 기존 좌우 신호가 남는다.
- 증거: `test_face_inputs.py`에 사유별 노트와 양보 회전·일반 HOLD 시험을 넣었다. 원격 pytest는 커밋 전이라 돌리지 않았다.
- gate 변화: 없음.
- 결정: D-719

## 2026-10-12 · 47ace984f2 · 내장 센서 이름과 CORE clock 전달

- 변경: 명시 namespace의 sensor-only SafetyNode가 CORE 전역 이름 remap에 덮이지 않도록 자체 이름만 지정한다. CORE는 실제 use_sim_time을 센서 생성에 전달하며 기존 namespace·topic remap을 유지한다.
- 증거: 실제 Jazzy 실행을 포함한 정상 원격 115 PASS/NEW 0, 독립 SOURCE 승인이다. 별도 안전 gate 계약도 NEW 0이다. 실제 Gazebo graph에서 이 후보의 readback은 다음 실행에서 확인한다.
- gate 변화: 없음. Leg4 실행 소스는 e6d0fe12ba이며 0.311955m 뒤 전방 제한으로 정지했다. 원본 지도 완주·실물 수용은 미확인이다.

## 2026-10-12 · af76fcc5f · 관측 표식의 가까운 경계와 기존 교통 gate 검증

- 변경: 실제 road detector와 payload 변환을 통과한 두꺼운 정지선·거리 미확인 표식을 기존 CORE 교통 정책으로 검증하는 시험을 추가했다. CORE 제품 정책·모드·안전 상한은 바꾸지 않았다.
- 증거: 중앙 거리로는 양수 APPROACH가 나왔던 RED를 가까운 경계로는 기존 stop_distance에 들어가 STOP_REQUIRED/zero가 되는 것으로 검증했다. 지평선 바로 아래 먼 표식의 거리None은 HOLD/stop_distance_unavailable을 유지한다. 정상 원격 관련 234 PASS/NEW 0이다.
- gate 변화: SOURCE/원격 SDK 계약 증거만 추가한다. 관측 의미 분류와 실제 Gazebo 주행·완주·실물 수용은 별도 검증 대상이다.

## 2026-10-12 · d3bd5513c · 이동 교통 감속과 실제 command SDK 정합성

- 변경: gateway 제품 bridge는 바꾸지 않았다. static profile clip 이후의 주행 호가 공유 교통 정책·CommandManager 곡률 보존 제한을 지나 유지되고 같은 traffic 적용 값이 issued trail에 기록되는지 검증했다.
- 증거: 정책의 이동 선속도만 줄이면 실제 SDK에서 곡률 3.2가 9.2로 바뀌는 RED가 났다. D-735 수정 뒤 관련 402개 시험은 정상 원격에서 통과했고 독립 SOURCE 승인이다. stale 또는 새 evidence/revision은 기존 적용 거절을 유지한다.
- gate 변화: SOURCE/원격 SDK 증거만 추가한다. 실제 수정 후보 Gazebo 주행·완주·실물 수용은 아직 확인하지 않았다.

## 2026-10-12 · uncommitted · 카메라 곡률이 CORE 유효 법칙과 같다

- 변경: 시험만 추가한다. 카메라가 역산한 추종 오차를 실제 `LineFollowManager._steer`에 넣으면, Pinky 0.10/2.0을 포함한 불러온 법칙에서 각속도/선속도가 기하 곡률과 같다. 공백 구간의 ExpectedPath도 같은 인스턴스 법칙을 쓴다.
- 증거: `test_line_follow_drivable_law.py`. 원격 pytest는 이 기록 시점에는 아직 돌리지 않았다.
- gate 변화: 없음.

## 2026-10-13 · uncommitted · D-440 기기 전원 어댑터와 웨이크 뒤 cmd_vel 0 유지 (feat/device-power-policy에서 옮김)

- 변경: `core/bridge/device_power.py`가 `_reconcile_lidar`를 대신한다(LiDAR 서비스 포트, latched `power/devices` 보드, `power/device_ready` 보고). 받은 스캔이 LiDAR의 확인 보고다. `cmd_vel_cycle`은 `motion_ready`가 정확히 True가 아니면 0을 내고, 게이트 예외는 바퀴에 쓴 뒤에 경고한다. `core/system/power.py`가 `presence.min_presence_s`·`max_gap_s`와 `device_policy`를 읽고, 잘못된 블록은 오류를 남기고 정책을 끈다.
- 증거: `test_cmd_vel_cycle.py`, `test_power_device_adapters.py`, `test_power_command_routes.py`, `test_bridge_timers.py`. 독립 리뷰(code-reviewer, REQUEST CHANGES 한 번 뒤 APPROVE WITH NOTES)를 받았다. 원격 pytest 결과는 착지 보고에 둔다.
- gate 변화: 없음. 스위치가 꺼진 로봇은 기기 명령을 하나도 내지 않고 `motion_ready`는 늘 true다. 실기 증거 없음.
- 결정: `power/manager.py`·`power/devices.py`·`bridge/device_power.py`의 safety 태그는 넣지 않았다. D-430 매니페스트 결정으로 남긴다.

## 2026-10-13 · uncommitted · D-556 한쪽 경계 충돌 품질 사유 포팅

- 변경: CAMERA_LINE `quality.reason=odom_side_conflict`를 불가시·신뢰도 0으로만 받는다. CORE line-follow는 저조도처럼 D-476 bridge·D-468 로컬 복구를 거치지 않고 HOLD한다(`reason: camera_odom_side_conflict`). 최종 cmd_vel 소유권은 그대로다.
- 증거: 커밋 779dd22fe의 원격 `middleware/core/gateway/test` 2780 passed(`X:/DevTemp/land-recent/odomveto/3-gateway/run-1.txt`). 실물 수용 근거는 아님.
- gate 변화: 없음(SOURCE 후보).

## 2026-10-14 · 06ce5334b · enforce 어댑터가 stale_hold_s를 안전 관리자에 넘긴다 (D-400 4항, API v1.223)

- 변경: `bridge/control_sensor_adapter.py::bind_safety`가 enforce에서 `bind_control_policy(policy, stale_hold_s=...)`로 묶는다. shadow와 off는 그대로다. `safety_policy_status.py`가 enforce일 때 `hold {count, reason}`를 싣고 `node.py`가 안전 관리자를 넘긴다.
- 증거: `test_control_sensor_adapter.py`(설정값 전달, shadow·off 미전달, 실제 `SafetyManager` 바인딩), `test_control_absorption_safety.py`·`test_control_policy_link.py`(HOLD, 재개, 2 s 뒤 래치, 바로 래치하는 경우), `test_safety_policy_status.py`. 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: SOURCE·호스트 근거만 더한다. SIM과 장치 수용은 미검증이다.
- 결정: D-400 개정(2026-10-14).
- 교훈: 시험의 가짜 safety 둘(`bind_control_policy(self, policy)`)은 새 키워드 인자를 받도록 고쳐야 했다.

## 2026-10-14 · 0e59264da · D-400 active policy-gap clock rollback

- Change: fail closed before lease reset when an active gap tick precedes the previous gap tick; no clock clamp, final writer or E-stop reset added.
- Evidence: remote RED on c4e5d4ae3: three partial rollback cases failed, three original rollback cases passed. Six regressions cover late, unbound and unavailable observation paths. Independent authority_review SOURCE PASS; remote GREEN follows in the deployment evidence.
- gate 변화: no DEVICE or FIELD acceptance; existing D-400 boundaries retained. Plan: docs/plans/2026-10-14-policy-gap-clock-fix.md.

## 2026-10-14 · e60a7891e · line_follow.bend_map_entry_enabled 설정 읽기 (D-759 검토 반영, API v1.224)

- 변경: `core/drive/line_follow.py::_line_follow_config`가 `bend_map_entry_enabled`를 YAML boolean으로만 읽는다(`_flag`).
- 증거: `test_line_junction_api.py`(기본 `false`, `true`, `"true"`는 `ValueError`), `test_capabilities_controls.py`(설정이 꺼지면 `lane_bend`가 참이어도 `lane_bend_map_entry`는 거짓). 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음. SOURCE·호스트 근거만이다.
- 결정: D-759(Proposed).
- 교훈: 없음.

## 2026-10-14 · 1ee33639c · trip 임대가 열려 있으면 차선 추종이 통행권을 요구한다 (D-760 2단계, API v1.225)

- 변경: `core/trip_lease.py::build_trip_lease`가 `line_follow.authority_leased = lambda: trip_lease.current() is not None`을 묶는다. 5 Hz 타이머가 아직 끝내지 않은 만료 임대도 열린 것으로 센다. 임대 객체는 그대로다(움직임을 주지 않는다, D-541 9).
- 증거: `test_trip_lease.py` 3건(임대 없으면 통행권 문이 명령을 그대로 둠, 임대 → 차선 → `authority_none` → 통행권 → 통과 → lane·free·lane 뒤 다시 `authority_none` → 임대 해제 뒤 통과, 만료 임대는 타이머가 끝낼 때까지 강제), `test_line_authority_api.py` 2건, `test_capabilities_controls.py`. 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음. SOURCE·호스트 근거만이다. `trip_lease.py` 315줄 → 318줄.
- 결정: D-760 Decision 2. 잠금 순서는 차선 관리자 잠금 → 임대 잠금 한 방향이다(임대는 자기 잠금을 놓은 뒤에만 `halt`를 부른다).
- 교훈: `fleet.trip_lease_required`만 켜고 `fleet.traffic.authority`를 끈 현장에 이 CORE를 올리면 lane trip 로봇이 `authority_none`으로 서 있다. Fleet 출발 검사(`TRIP_AUTHORITY_SITE_OFF`)는 아직 `line_follow_authority_required`만 본다(3단계).

## 2026-10-14 · 8a73125e6 · 임대가 첫 통행권 전에 끝나도 로봇은 서 있다 (D-760 2단계 안전 검토 M1, API v1.225)

- 변경: 코드 변경 없음(`core/trip_lease.py`의 묶음은 그대로). 차선 관리자가 강제를 세션에 래치하므로, `TripLeaseManager.end()`가 임대를 지운 뒤 `halt`가 차선 추종을 끄기 전의 틈에서도 통행권 문이 명령을 0으로 둔다.
- 증거: `test_trip_lease.py` — 만료와 인수 각각에서 `halt`가 불리는 순간(임대 없음, 차선 추종 켜짐) 문이 0을 낸다. 해제(DELETE) 뒤에도 `authority_none`이고 모드를 바꾼 뒤에만 풀린다. `test_line_authority_api.py` — `seq`를 본 구간의 `seq` 없는 요청은 `seq_required`, 쥔 것 없는 `shrink`는 `shrink_none_held`. 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음. SOURCE·호스트 근거만이다.
- 결정: D-760 Decision 2.
- 교훈: 없음.

## 2026-10-14 · uncommitted · fix(bridge): D-758 0단계 odom 스냅숏 stamp를 line-follow odom 기록에 넘긴다

- 변경: `core/bridge/ros_bridge.py::_on_odom`이 `state.set_odom_pose`를 먼저 부르고(odom `frame_id`·헤더 시각을 같이 넘겨 epoch 판정) 그 반환 stamp를 `odometry.observe_lane_return(..., wall=)`로 line-follow에 넘긴다.
- 증거: `test_lane_return_odometry.py::test_the_published_wall_stamp_keys_the_odom_log`(수정 전 적색), `test_line_follow_lane_cue.py` 벽시계 ±5 s 시험, `middleware/core/gateway/test` 2865 통과(`X:/DevTemp/odom-monotonic/gw/run-1.txt`), `known_failures` NEW 0.
- gate 변화: SOURCE·호스트 근거만. `ros_bridge.py` 910 → 912줄(판정 799 + 150 안).
- 결정: D-758 0단계.
- 교훈: 없음.

## 2026-10-14 · uncommitted · refactor(bridge): D-758 0단계 검토 2항 — odom 넘김을 `odometry.observe_odom`으로

- 변경: `ros_bridge._on_odom`의 스냅숏 stamp → line-follow 기록 넘김을 ROS 없는 `core/bridge/odometry.py::observe_odom`으로 옮기고 `_on_odom`은 그것을 부른다(`test_bridge_timers.py`가 콜백 시험을 ROS 없는 형제 모듈에 두라고 한다). `ros_bridge.py` 912 → 908줄.
- 증거: `test_lane_return_odometry.py::test_the_odom_callback_logs_the_sample_under_the_snapshots_stamp`. `wall=wall`을 뺀 변이 커밋 `1a0413b01`(가지에 없음)을 만들었으나 원격 실행은 전송 실패로 확인 못 함.
- gate 변화: SOURCE 근거만, 호스트 시험 미확인.
- 결정: D-758 0단계 독립 Safety-Review 조건 2.
- 교훈: 없음.

## 2026-10-14 · 775b1f3f6 · 설정 line_follow.turn_map_entry_enabled를 읽는다 (D-759 개정 1)
- 변경: `core/drive/line_follow.py`가 `turn_map_entry_enabled`를 bool로만 읽는다(기본 꺼짐).
- 증거: `test/test_line_junction_api.py`(기본값, 켬, 문자열 거절), `test/test_capabilities_controls.py`. 원격 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.

## 2026-10-14 · uncommitted · test: 수동 거절 시험을 벽시계 워치독에서 떼어 낸다
- 변경: `test/test_line_junction_api.py::test_refused_while_manual_control_is_active`가 `watchdog.timeout_ms`를 60 s로 고정한다(`test_manual_navigation_ownership.py`와 같은 방식). 제품 코드는 그대로다.
- 원인: CI 38573105206(b1e84dd79)에서 teleop과 `/line-follow/junction` 사이가 500 ms를 넘어 teleop 세션이 만료됐고(`command/manager.py` `manual_active`), `require_manual_released`가 통과해 `set_junction`의 `LINE_FOLLOW_NOT_ACTIVE`가 나왔다. 확인 순서는 맞다: 거절 검사가 먼저이고, 만료된 세션을 수동 제어로 치지 않는 것은 설계다(SAF-002). 시험 설정 경합이지 제품 순서 결함이 아니다.
- 증거: 원격 pytest 20회 호출. 수정 전 20/20 통과(느린 러너에서만 재현돼 재현 못 함), 수정 후 19/20 통과 + 1회 하네스 기동 실패(같은 HEAD 파일 전체 재실행 21 passed). 원인 판단 근거는 코드 경로와 CI 로그다.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 벽시계 워치독(500 ms)을 쓰는 시험은 세션 유지가 시험 대상이 아니면 타임아웃을 고정한다.

## 2026-10-15 · 84f0c8456 · 작업의 trip lease는 단계 사이 IDLE에서 끝나지 않는다 (D-763 조각 6, API v1.236)

- 변경: `core/trip_lease.py` `_Lease.job_id`. `job_id`로 연 lease는 모드 감시(`end_on_mode`)가 IDLE에서 끝내지 않는다. MANUAL·도킹·비상 정지·넘겨받기·만료·주인 해제는 그대로 끝낸다. renew는 `job_id`를 바꾸지 않는다. 공개 dict에 `job_id`. 통행권 래치(`authority_leased`)는 그대로라 다음 차선 세션에서 lease가 있으면 바로 다시 걸린다.
- 증거: `test/test_trip_lease.py` D-763 6 절 — 주인 IDLE 뒤 lease 유지, 단계 사이 주인 아닌 `/mode`(MANUAL·NAVIGATION)·`/teleop` 409, 넘겨받기 통과, 주인 아닌 IDLE·E-stop은 lease를 끝냄, 단계 중 주인 아닌 IDLE도 끝냄, 주인 MANUAL은 끝냄, 만료는 지금과 같음, renew가 작업 lease로 바꾸지 않음, `job_id` 검증, 능력, lease를 갱신해도 통행권(`authority_expired`)과 목표 임대가 만료함, lease → 모드 → 첫 통행권 순서. 원격(모델 PC, 7334f9c40) 통과, `known_failures` 0 new, 로그 X: `job-lease/core/run-1.txt`.
- gate 변화: 없음. SOURCE·호스트 근거만이다. 장치 미확인.
- 결정: D-763 4항·조각 6, 개정 2 질문 2·3. 팔 단계 중 만료의 동작은 정하지 않았다(남은 질문 1).
- 교훈: 없음.

## 2026-10-15 · 1a9960df2 · line_follow.instruction_stamp_enabled 설정 읽기와 능력 lane_instruction_stamp (D-767 A부, API v1.241)

- 변경: `core/drive/line_follow.py`가 `instruction_stamp_enabled`(bool 엄격)를 읽는다.
- 증거: `test/test_capabilities_controls.py`(능력이 설정을 따름), `test/test_line_junction_api.py`(설정 읽기, `distance_basis` 기록). 원격(모델 PC, 9639a41b8) `middleware/core/gateway/test` 통과, `known_failures` 0 new.
- gate 변화: 없음.
- 결정: D-767 A부 4항.
- 교훈: 없음.

## 2026-10-16 · ddd1b70f4 · Publish authority-bound route priors through CORE (D-769)

- 변경: Added the single line/lane_guide publisher to the existing line-follow timer; no new motor publisher or timer. Inactive line following, E-stop and unavailable authority yield ordered clears. Initial and rewound source clocks announce a publisher epoch with clear before active data. Publication retains monotonic source expiry across epoch resets and caps wire validity by remaining budget. Existing route-context cadence moved into a state holder so the oversized bridge shrank by one line, with its size ratchet lowered in the same commit.
- 증거: 48 remote tests passed across route publication, real publisher-to-inbox lifetime, route context, bridge registrations, authority binding and inbox. Review regressions reproduced expired-source resurrection and receiver lifetime extension after rewind; both now pass. Independent review of ddd1b70f4 found no further narrow blocker. Private evidence: rosy-d769-audit/lane-route-publication-red, lane-route-rewind-red, lane-route-wire-budget-red and lane-route-wire-budget-green. Structural publisher registration proves the sole cmd_vel publisher remains, not real DDS behavior.
- gate 변화: None. Fleet selected-route production, deployed capability and actual Gazebo acceptance remain pending. Paused ROS time during message transit cannot expose elapsed wall time from this schema alone; budget is capped at publication and again at receipt.

## 2026-10-16 · c11a34f64b · Explicit deployment opt-in for route guidance (D-769)

- 변경: Parse false-default route_guide_enabled and expose line_follow_route_guide only when authority and the deployment setting are enabled. CORE publishes clear while disabled. Learned-drivable Fleet SIM overlays explicitly enable the setting; other overlays retain the default. API reference and advertised version advance together to v1.247.
- 증거: Remote integration suite passed 186 tests, including capability opt-in, protocol alignment, bridge registration and both SIM overlay settings. Private evidence: rosy-d769-audit/fleet-route-integrated/run-1.txt. Independent safety review approved the false default and explicit opt-in; the commit carries its Safety-Review trailer. Size and safety guards passed.
- gate 변화: None. Capability reflects deployment configuration, not consumer health attestation. Gazebo acceptance remains pending.

## 2026-10-19 · uncommitted · preview API 짝 시험의 시간 의존성 제거

- 변경: raw/annotated API의 신선한 짝을 검증하는 시험에서 canonical core_features.vision.store에만 고정 clock을 주입한다. 운영 TTL과 pairing·rate 제한은 변경하지 않는다.
- 증거: 693dae79b4의 원격 시험에서 두 publish 후 clock을 20→23초로 이동하면 기존 raw_available 단언이 실패함을 재현했다. 수정 뒤 preview API 및 explicit-clock frame pair·만료 시험과 전체 영향 시험은 별도 실행한다.
- gate 변화: 없음. 실제 카메라·ROS·장치 수용은 검증하지 않음.

## 2026-10-19 · uncommitted · Account 장애·재시도·미디어의 실제 연결 검증

- 변경: 실제 Fleet Authority와 CORE receiver를 사용하는 HTTP 로그아웃 실패, lifespan 회수 재시도, 미디어 strict online 검증을 추가했다. HTTPS Chromium의 정상/회수 대기 로그아웃을 함께 검사한다.
- 증거: `41e03f029e`의 원격 모델 PC에서 pipeline/media 14개 통과, skip 0, NEW 0. 첫 browser 실패는 조회 전용 Pilot 차단 화면의 로그아웃 부재를 재현했고 Pilot 수정 뒤 같은 검증이 통과했다. 로그는 외부 scratch의 `rosy-account-rollout-20261019/task2-fixed/run-1.txt`다.
- gate 변화: 없음. 실제 운영 계정·배포·단말·MediaMTX 연결 종료를 이 시험으로 수용하지 않는다.

## 2026-10-19 · 212a8b51b2 · Account CORE HTTP·browser 회귀를 앱 착지 단위로 재적용

- 변경: 실제 Authority fixture의 HTTP 로그아웃 pending·쿠키 제거·lifespan 재시도·strict media 재검증·새 family 분리를 최신 main 위에 재적용했다. CORE 제품 인증 코드는 변경하지 않았다.
- 증거: 원래 d58258fee6의 공통/CORE/Pilot 실제 Chromium/proxy 묶음35개 PASS, skip0·NEW0. 이번 착지 SHA의 검증은 별도 실행한다. 이전 SHA 결과를 최신 main 수용으로 대신하지 않는다.
- gate 변화: 없음. 실제 미디어 종료·운영 배포·사용자 수용은 미확인이다.

## 2026-10-19 · uncommitted · 성공 drivable SIM의 CORE 소비 결선 복원

- 변경: foundation 선행 계약 위에서 기존 v2 성공 구현의 지도 벽 band와 경로 안내 표본 결선을 복원했다. 새 writer나 실물 활성화를 추가하지 않는다.
- 증거: 원본 91f14c997f의 모델 PC 재실행은 PASS, 목표 거리 0.105 m, 최종 명령·odom 속도 0, lease released다. 이는 원본 소스 증거이며 이 후보의 검증은 별도다.
- gate 변화: 없음. 실물 지도 오차·보정·장치 수용은 남아 있다.

## 2026-10-19 · 27427874e · (origin #92 2026-10-16) D-772 실제 영상·관제 API·접안 확인 통합

- 변경: 이상적 운동학 plant를 JPEG 마커 영상으로 렌더링해 실제 Vision worker·source 전용 Fleet API·HttpRobotClient·CORE API·기존 접안 제어기로 전달하는 SIM 시험을 추가했다. plant 위치는 영상 생성과 독립 오차 판정에만 쓰며 상대 카메라 입력으로 직접 주입하지 않는다.
- 증거: 27427874e 관련 40개 시험 통과, NEW 0. 위치 20 mm·방향 5° 이내 정렬 뒤 접촉 없음·측정 속도 잔류는 착좌를 차단한다. 연속 접촉/정지 뒤 충전 확인, 현재 정상 종단 뒤 CHARGED_HOLD·정지/예약 유지, 표식 손실 뒤 확인 해제를 검증했다. 로그 C:/DevTemp/station-charge/task-3-normal-pipeline/run-1.txt.
- gate 변화: 이미지·HTTP·controller SIM 증거. local_scope·motion_feed·executor와 접촉/BMS를 대체했다. 실제 Safety/mode·원본 ROS odom·최종 publisher/power gate·Gazebo·실기·전체 Fleet 이안/재투입 수용을 대체하지 않는다.

## 2026-10-19 · d5c1a61e4 · (origin #92 2026-10-16) D-772 기존 trip lease의 스테이션 복귀 출력 결속

- 변경: station 서비스가 실제 TripLeaseManager의 비차단 원본 잔여 시간 검사를 사용한다. 지정 Fleet owner·정확한 lease/trip/job=session과 현재 native boot/generation·설치 버전을 확인한 RETURNING만 최종 NAVIGATION 후보 출력을 통과시킨다. 만료/교체와 실제 scope 손실은 이전 허가의 부활을 막고 잠금 경합은 해당 주기만 차단한다.
- 증거: 4016579af 신규 DTO/경로 부재 RED 뒤 독립 안전 리뷰에서 scope 복구 시 부활·일시적 상태 lock 경합의 영구 손실 오인을 수정했다. d5c1a61e4 관련 283개 원격 시험 통과, NEW 0. 네 station 쓰기 경로를 실제 다른 trip lease owner로 거절하고, 최종 출력에서 state/native/lease 경합·원본 잔여 시간·수동/E-stop을 검증했다. 로그 C:/DevTemp/station-charge/task-7-return-permit-final/run-1.txt.
- gate 변화: 소프트웨어 CORE 경계 증거. 특정 귀환 경로/에너지·실제 TripRunner 연결·최종 ROS publisher·현장 동작 수용은 별도 미완료다. 실제 trip 성공 없이도 IDLE/정지 후 단계 인계 조건은 시험할 수 있으며 도착 증거로 쓰지 않는다.

## 2026-10-19 · 50a6ef719 · (origin #92 2026-10-16) D-772 terminal navigation의 실제 IDLE 인계

- 변경: CORE drive 구성이 Navigation owner lock 아래 성공 terminal native run·실제 transport quiescence를 확인하고, 현재 충전 복귀의 scope를 다시 확인한 뒤에만 NAVIGATION 후보 제거와 조건부 IDLE 전환을 수행한다. 일반 backend 취소를 호출하지 않는다. 실제 TripRunner/HTTP 시험에서 수동 IDLE 주입을 제거했다.
- 증거: 9992fbf55에서 실제 terminal navigation이 NAVIGATION에 남는 RED를 확인했다. 독립 안전 리뷰의 native kind home whitelist를 수정하고 50a6ef719 원격 35개 통과, NEW 0. 실제 NavManager/GoalTracker/lease/API/모드 인계와 진행 중 목표/admission/callback·수동/E-stop·교체 lease·만료·Nav lock 경합을 검사했다. backend 결과·plant·odom은 SIM이다.
- gate 변화: 소프트웨어 자동 모드 인계 증거. Nav2 실기 callback·정지 계측·운영 bootstrap·전체 충전/이안/재투입·FIELD는 미완료다.

## 2026-10-19 · 002ee166e · (origin #92 2026-10-16) D-772 terminal 인계 최종 회귀

- 변경: 신규 terminal 인계와 기존 native/lease/수동/도킹 mode·이미지 HTTP 접안·Fleet 상태/공유 API를 함께 검증했다. 설치 패키지와 safety/구조 계약도 포함했다.
- 증거: 원격 CORE 322개(task-7-native-handover-core-final/run-1.txt), Fleet/계약/구조/안전/설치/harness 291개(task-7-native-handover-contract-final/run-1.txt), 총 613개 통과. 각 NEW 0/skip 0. 두 실행 모두 002ee166e이며 backend·plant·odom·에너지는 명시적 SIM이다. 수동 IDLE 주입 없이 실제 NavManager·GoalTracker·CORE 인계가 동작했다.
- gate 변화: 소프트웨어 회귀 증거 추가. 실제 ROS/backend/장치 정밀도, 운영 구성·주기 정책·이안/재투입·전체 cycle·FIELD 수용은 미완료다.

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

## 2026-10-19 · 741c9b95f · (origin #92 2026-10-16) D-772 원래 위치 수명을 넘기는 충전 세션

- 변경: ChargeRobotHttp는 실제 return/dock owner를 읽을 때에도 관제의 새 전역 위치 근거를 CORE의 기존 binding과 동기화한다. ACK만 신선하고 CORE target은 만료되는 단절을 해결했다. 같은 session/robot/boot/battery/map/attempt·위치/접근 포즈·출처/교정을 유지하며 새 capture의 시간·불확실성만 갱신한다. 만료/HOLD binding, 같은 capture의 TTL 연장, 다른 native owner, 만료/미래 측정 권한은 거절한다. source/native/DB I/O 뒤에도 원본 수명을 확인하며 feed·native 실행·착좌·충전 완료 근거를 재설정하지 않는다.
- 증거: 40d405e5e RED 5건과 3e579caae의 실제 runtime 위치 만료 RED를 확인했다. f1726a72e Fleet·위치 원장·구조/안전/설치 178개, 1f45569ca CORE/HTTP·refresh·owner 190개, 741c9b95f 충전 유지/완료 수명·sensor reader·영상 pipeline 134개가 원격 종료 코드 0, NEW 0/skip 0으로 통과했다. 범위가 겹쳐 합산하지 않는다. 로그는 저장소 밖 task-9-target-fleet-guards, task-9-target-refresh-retry, task-9-target-charge-final/run-1.txt다.
- 실행 범위: 연속 시험은 최초 2초 위치 lease와 충전 시작 시점의 lease를 넘기면서 3초 동안 CHARGING을 유지한 뒤 정상 종단으로 CHARGED_HOLD가 됨을 검사한다. 매 JPEG step에 실제 runtime을 진행한다. 갱신 permission은 초기 SIM seed 이후 실제 StationIngress scope 경로를 사용한다. 새 전역 후보는 SIM 입력으로 StationService.observe에 공급하므로 독립 전역 producer의 운영/인증 통합 수용은 아니다. 주행 plant·map pose·접점·BMS·에너지도 SIM이며 상대 접안은 실제 JPEG/worker/인증 HTTP 경로다.
- 검토/수정: scoped 독립 안전 검토의 post-I/O permission TTL 지적을 반영했다. 기존 순수 owner fixture의 미래 permission(100.1)을 시각 100에서 수락하던 잘못된 입력은 현재 시각을 100.1로 맞췄다. 별도의 미래/만료 거절 회귀는 유지했다. 실제 연속 경로가 ACK 수명과 target 수명의 차이를 재현해, 이후 exact intent 확인 뒤 owner 조회 때도 동기화하도록 수정·재검토했다.
- gate 변화: 소프트웨어의 같은 버전 장기 세션 갱신을 검증했다. 기존 PUT 계약과 DTO를 사용해 API v1.253을 유지하며 크기/공차/실패 허용을 늘리지 않았다. 안전 이안·재투입, 독립 전역 이동 producer, 전체 3회 cycle·실측 profile·DEVICE/FIELD 수용은 미완료다. 전체 목표는 ACTIVE이며 push/merge/실기 활성화는 하지 않았다.

## 2026-10-19 · 8674f07fd · (origin #92 2026-10-16) D-772 명시적 빈 이안 피드 설치

- 변경: build_station_owner가 simulation의 명시적 departure_profile만 설치한다. station/battery 범위를 검증하고 빈 로컬 feed로 시작하므로 측정 producer 없이 이동하지 않는다. 실기 DEVICE_ACCEPTANCE_REQUIRED는 유지한다.
- 증거: de3d825c2 명시적 프로필 부재 원격 RED를 확인했고 독립 검토 scoped PASS를 받았다. 실제 native HTTP 시험은 mode/bridge와 분리한 로컬 owner SIM이며 실제 장치 수용을 뜻하지 않는다. 구현 원격 검증 대기.
- gate 변화: 없음. CORE/SIM 구성 단계이며 장치 profile·배선·센서/릴레이 수용은 미정이다.

## 2026-10-19 · 1216b3f7b · (origin #92 2026-10-16) 이안 계약과 실제 native API 최종 회귀

- 변경: v1.254 이안 허가/실측 Receipt, 로컬 원본 시각 피드·기존 native owner, 명시적 simulation 빈 피드와 관제 API·정확한 중단을 검증했다. 이전 API 경로 추적표·버전 이력·로그 제목/생성 인덱스 실패를 수정했으며 허용 한도나 안전 검사를 완화하지 않았다.
- 증거: task-8-departure-final 원격 412개 통과, NEW 0/skip 0, exit 0. 별도 1f8569773 task-8-departure-contract-pins 96개 통과, NEW 0/skip 0, exit 0. 7d3f6418d의 native/기존 docking 회귀 194개와 범위가 겹치므로 합산하지 않는다. Safety-Review scoped PASS는 DTO/source/controller·owner/manager 및 API/갱신/프로필/중단 범위다.
- gate 변화: 관련 소프트웨어 회귀 증거. HTTP 정상 경로는 실제 native owner+합성 로컬 facts로 adapter를 검증했고 bridge/mode 구성은 별도 시험이다. Fleet의 영속 선택 작업/예산 결속·실제 Receipt 기반 claim 해제/재투입·3회 cycle·독립 전역 위치 producer·실측 프로필/DEVICE/FIELD 수용은 미완료다. 목표 ACTIVE, 실기 구성 미정, push/merge/실기 활성화 없음.

## 2026-10-19 · 9286f5f77 · (origin #92 2026-10-16) 실제 Fleet HTTP 이안과 유실 완료 조회

- 변경: v1.254의 기존 guarded 시작/갱신/finish와 GET station-target을 실제 Fleet runtime/client에 연결해 검증했다. 허가 갱신은 같은 native 실행만 유지하고, 완료 응답 유실은 현재 owner의 원본 수명이 남은 Receipt로만 복구한다. 공유 readback은 session/boot/battery/work/correlation·native 세대와 현재 상태를 결속한다.
- 증거: c6abafd83 readback 원격 407개 및 9286f5f77 task-8-redeployment-http-final 원격 253개 통과, 각각 NEW 0/skip 0, exit 0. scoped 독립 안전 리뷰 PASS. 실제 HTTP/native 소프트웨어 경로이며 초기 충전 완료 상태와 로컬 센서·공간·전원/BMS·에너지 입력은 명시적 SIM이다.
- gate 변화: 관련 회귀 근거. 이전 camera/return pipeline과 이번 departure의 전체 연속 cycle, 다음 session binding, 3회 cycle·독립 이동 producer·실기 수용은 미완료다. 목표 ACTIVE, push/merge/장치 활성화 없음.

## 2026-10-19 · a4ead2712 · (origin #92 2026-10-16) 완료 뒤 다음 session binding API 검증

- 변경: 기존 v1.254 PUT station-target은 완료된 session 다음의 새 binding을 실측 정지 boundary에서만 받는다. 새 session/attempt와 local/native fence를 확인하며, 지연된 retired session 요청과 과거 Receipt의 새 session 전이를 거절한다. 새 public endpoint나 물리 사실 업로드는 추가하지 않았다.
- 증거: task-8-rebind-green 원격 282개 통과, NEW 0/skip 0, exit 0. 실제 gateway는 새 local stop 전 409/이후 200이며 기존 native operation을 새로 실행하지 않고 과거 Receipt를 readback에서 제거한다. owner/motion 및 기존 departure/redeployment 회귀를 함께 실행했다. 독립 scoped 안전 검토 PASS.
- gate 변화: 관련 API/SIM 회귀 근거. 입력 motion·완료 초기 상태는 명시적 SIM이며 실제 normal-work→IDLE 인계·전체 3회 순환·현장 수용은 미완료다.

## 2026-10-19 · 70827fd97 · (origin #92 2026-10-16) 실제 Fleet 작업 결과에서 항법 인계 검증

- 변경: 기존 v1.255 인계 API의 실제 FleetTaskService 호출 경로를 검증한다. 실제 CORE 완료 이벤트만으로는 robot claim이 남아 인계를 거절하고, 기존 Task native outcome owner가 actual HTTP quiescence로 해제한 뒤에만 정확한 native 실행을 IDLE로 인계한다. 새 이동·취소 명령이나 physical stop 판정은 추가하지 않는다.
- 증거: task-11-task-runtime-handover-final 원격 267 PASS/0 skip/NEW 0/exit 0. 현재 source boot·Task receipt·CORE boot 결속, 전송 직전 정책/DB guard와 기존 lease/native/runtime/안전 구조를 포함한다. 최초 실제 항법 시험에 빠진 odometry presence를 명시적 SIM 입력으로 보완했다. 독립 scoped 안전 리뷰 PASS.
- gate 변화: 해당 host API/SIM 검증 근거. 새 정지 dwell→다음 binding 및 전체 3회 cycle은 미완료이며 장치·현장 정밀도 수용으로 승격하지 않는다.
- 추가 증거: 같은 SHA의 기존 실제 귀환·JPEG 접안/충전·이안/재투입·target refresh 및 계약 회귀 290 PASS/0 skip/NEW 0/exit 0. 전체 연속 cycle의 증거는 아니다.

## 2026-10-19 · ad979adf8 · (origin #92 2026-10-16) 실제 최종 출력과 완료 인계를 잇는 3회 카메라 시나리오

- 변경: 동일 CORE/TaskService/runtime/worker에서 귀환·JPEG 접안·착좌/실측 정지·충전 완료·이안·실제 작업을 3회 수행하는 시험이다. 두 후속 session은 실제 작업 결과/자원 해제→이동 없는 native 인계→새 motion dwell→새 binding을 거친다. native 완료나 원하는 정지 명령을 measured zero로 직접 바꾸지 않는다.
- 증거: actual Console 경로의 task-12-console-continuous 단일 3회 시나리오 원격 PASS/NEW 0. 앞선 target 갱신/ingress와 기존 JPEG/안전 회귀는 0268fe909에서 161 PASS/0 skip/NEW 0이다. 독립 test fidelity 리뷰로 desired/applied 분리와 ARRIVED/IDLE 포함 매 tick의 실제 cmd_vel_cycle/power/readiness/station gate 적용을 확인했다.
- gate 변화: 해당 host/SIM 근거. 이상적 plant·localization·접점·전원 격리·후방 공간·에너지·전역 위치·첫 permission은 합성이다. 스테이션 이동/실시간 운용·실기 수용으로 승격하지 않는다.
- 최종 증거: c2cc1551d task-12-continuous-final 원격 239 PASS/0 skip/NEW 0/exit 0. 네 이동 phase의 실제 power gate 거절 시 출력 0·plant 위치 불변도 3회 시나리오 안에서 검증했다. deterministic 수동 tick이며 실시간 서버나 실기 수용 근거가 아니다.

## 2026-10-19 · 3621458a6 · (origin #92 2026-10-16) 독립 지도 JPEG를 통한 이동 스테이션 복귀 회귀

- 변경: 연속 카메라 시험의 전역 SIM 위치 주입을 독립 고정 landmark 네 개와 스테이션 marker의 실제 JPEG→source 인증 Fleet ingress 경로로 연결했다. 작업 사이 이동은 기존 위치 무효화·일관성 검증·새 revision·구 revision 거절을 거치고, 복귀 중 이동은 기존 session HOLD와 실제 출력 0·claims 유지를 확인한다.
- 증거: fd96e9120 relocation-route 2 PASS 뒤 anchor 보강 3621458a6 anchors-order에서 관련 원격 245 PASS/0 skip/NEW 0/exit 0. 동일 CORE/TaskService/runtime/native owner로 3회 충전·이안·실제 작업 재투입을 검증했다. 초기 통합 실행의 Fleet/CORE 동일 시험 모듈명 충돌은 gateway test_trip_lease 선행 로딩으로 같은 SHA에서 재검증했다. 로그 C:/DevTemp/station-charge/task-13-anchors-order/run-1.txt.
- gate 변화: deterministic host/SIM 근거. 실시간 lifespan·재시작 장애 matrix·실측 장치 프로필·물리 정밀도 수용은 별도이며 전체 CI 또는 DEVICE/FIELD로 승격하지 않는다.

## 2026-10-19 · cb43b5da1 · (origin #92 2026-10-16) 동일 앱 TripRunner의 3회 충전 복귀 회귀

- 변경: composed 카메라 시나리오가 실제 create_app의 TripRunner와 충전 runtime을 공유하도록 연결한다. 상대/지도 JPEG·실제 Console/CORE HTTP·native owner·최종 속도 게이트는 기존 경로를 사용한다. Task 완료 인계 뒤 Console의 이전 목표를 정확히 정리하고 다음 복귀를 시작한다.
- 증거: cb43b5da1 task-15-composed-final 원격 117 PASS/0 skip/NEW 0/exit 0. 전체 5 variant와 두 goal→None 인계, 같은 owner들의 3회 충전·재투입을 확인했다. 별도 Fleet 인계·경합·구조/안전 229 PASS/0 skip/NEW 0이다. 로그 C:/DevTemp/station-charge/task-15-composed-final/run-1.txt 및 task-15-retire-final/run-1.txt.
- gate 변화: 앱 생성/factory 조립 검증이며 수동 SIM tick이다. 서버 lifespan·재시작/프로세스 장애·실측 물리 수용은 별도다. CORE 장치 상태나 busy/claim 검사를 우회하지 않았다.

## 2026-10-19 · 6da412cb7 · (origin #92 2026-10-16) 실제 Fleet lifespan 충전 사이클과 계측 경합 보류

- 변경: continuous SIM의 한쪽 방향 도착 판정을 실제 평면 거리·방향 오차로 고쳤다. 실제 Fleet lifespan 소유 실행기/dispatcher variant와 실제 motion feed lock 경합 variant를 추가했다. 모든 이동은 기존 최종 cmd_vel 출력이며 CORE bridge/계측/시간은 명시적 SIM이다.
- 증거: b7860877b task-16-arrival-green 117 PASS/0 skip/NEW 0. fd97129bb task-16-lifespan-scope 1 PASS/0 skip/NEW 0으로 실제 Fleet 루프의 3회 사이클·runtime 종료를 확인했다. 6da412cb7 task-16-motion-busy 1 PASS/0 skip/NEW 0으로 HOLD·재진입 없음·native navigation 없음·출력 0·claims 보존을 확인했다. 각 원격 exit 0. scoped 독립 검토와 safety trailer 검사 통과.
- gate 변화: 최초 lifespan 실행의 CHARGE_RETURN_CORE_SCOPE_CHANGED 실패는 관측 추가 후 재현되지 않았고 해결로 판정하지 않는다. 강제 경합은 안전 보류 전파의 증거이며 최초 원인 확정은 아니다. 전체 CI·모든 background 종료·CORE ROS lifespan·재시작·실기 수용은 별도다.
- 최종 관련 회귀: fd97129bb task-16-final의 gateway lease와 전체 6 variant 118 PASS/0 skip/NEW 0/exit 0. 추가한 6da412cb7 경합 1건은 별도 실행이며 이 SHA에서 전체 시험군을 재실행한 것으로 합산하지 않는다.

## 2026-10-19 · 49e4cb188 · (origin #92 2026-10-16) 복귀·충전·이탈 중 Fleet 종료 및 보류 재구성

- 변경: 실제 Fleet lifespan에서 RETURNING 양의 출력·CHARGING 계측 확인·UNDOCKING 음의 출력 시점에 종료하고 새 SQLite store/Service/Runtime/Console/HTTP client/Fleet 앱을 구성하는 SIM 회귀 3건을 추가했다. phase checkpoint를 강제하고 원본 intent/claim과 최종 출력 0·위치 불변을 검증한다. 생산 안전 경계는 변경하지 않았다.
- 증거: 49e4cb188 task-17-shutdown-final 원격 3 PASS/0 skip/NEW 0/exit 0. 새 실제 runtime 첫 tick 및 후속 12 tick에서 HOLD와 callback 미호출, CORE navigation/docking/trip-lease mutation 없음·queued work 유지·원본 charge owner의 UNKNOWN claims·조정 전 rearm 거절을 확인했다. c7abdcfc8의 최초 3 FAIL은 rearm 성공을 잘못 기대한 시험 oracle이며 기존 guard를 유지해 수정했다. 독립 scoped review 및 safety trailer 검사 통과.
- gate 변화: 동일 CORE가 살아 있는 graceful Fleet 종료/재구성의 SIM 증거다. 전체 프로세스/route 복구·kill/전원 상실·CORE restart·실기 수용·전체 CI는 별도이고 최초 간헐 readback 실패는 미해결로 남는다.

## 2026-10-19 · 1d7af41f5 · (origin #92 2026-10-17) 통합 SIM의 원본 motion readback 진단

- 변경: 시험 전용 probe가 실제 lock 획득 결과와 lock 보유 중 원본 sample/시각을 기록하고 마지막 네 clear 호출 stack을 보관한다. 생산 readback·TTL·최종 publisher·명령 권한은 변경하지 않는다. 독립 scoped 검토 PASS.
- 증거: e801f1e01 lifespan NEW 1 FAIL 재현 후 bb6e03272 task-18-readback-diagnostic은 정상 lifespan FAIL/강제 motion_busy PASS다. 0fb3a8492 task-18-readback-sample은 NEW 1 FAIL이며 ACK 수락, motion lock 획득 true, 원본 sample None과 source/local 시각 100.55를 확인했다. known_failures로 새 실패를 확인했으며 baseline에 추가하지 않았다.
- gate 변화: clear stack 진단은 원격 test PC busy로 대기 중이다. 무조건 owner.tick을 호출하는 SIM과 session 존재 시에만 호출하는 실제 CORE 브리지의 차이를 조사한다. 아직 원인 해결이나 정상 통합 회귀 통과를 주장하지 않는다. 실기 수용과 전체 목표는 미완료다.

## 2026-10-19 · 79226ce97 · (origin #92 2026-10-17) SIM 초기 CORE 틱의 원본 이동 계측 보존

- 변경: 실제 lifespan worker가 최초 binding하기 전에 CORE 틱을 실행하도록 event로 순서를 고정했다. 시험의 직접 owner.tick 대신 production docking_mode.tick을 호출해 session이 없을 때 legacy fallback을 사용한다. 최초 UNBOUND·원본 motion 보존 assertion과 실제 worker/dispatcher, 최종 publisher를 유지한다. 생산 제어기·readback·TTL·권한 변경은 없다.
- 증거: e25e08ff3 task-18-startup-order-red 원격 NEW 1 FAIL은 session=None인데 HOLD가 되는 직접 호출 결함을 재현했다. 79226ce97 task-18-bridge-startup-green 원격 185 PASS/0 skip/NEW 0/exit 0은 전체 pipeline 10 variant와 trip lease·station wiring·mode ownership/release·motion feed를 검증했다. 독립 scoped 안전 검토 및 safety trailer 검사 PASS. 로그는 저장소 밖 C:/DevTemp/station-charge/task-18-bridge-startup-green/run-1.txt.
- gate 변화: 확인된 SIM 초기 호출 결함의 수정과 관련 회귀 근거다. 1d7af41f5의 앞선 clear 진단은 정상 1 PASS여서 그 실행에서 실패 stack을 얻지 못했다. 모든 과거 간헐 실패의 원인 확정, 전체 CI, 실제 ROS executor나 장치/현장 수용을 주장하지 않는다. 운영 source/실제 집행 예산/factory·CLI와 DEVICE/FIELD는 계속 미완료이며 목표 ACTIVE다.

## 2026-10-19 · 1558c56b4 · (origin #92 2026-10-17) timer 이전에 만료된 목표 임대의 갱신 거절

- 변경: 기존 D-550 목표 임대의 시각상 만료를 같은 Nav lock의 단일 monotonic 읽기로 확인한다. expired 판단을 owner 검사보다 먼저 수행해 기존 409 계약을 지키고, 정상 갱신도 같은 시각으로 deadline을 계산한다. 거절은 기존 lease·native generation·mode를 바꾸지 않으며 기존 exact-run timer 취소를 유지한다. 공개 shape/version 변경과 module 크기 증가는 없다.
- 증거: 8d6e8b7ed RED 4 FAIL/NEW 4 후 1558c56b4 task-18-goal-lease-deadline-green 원격 200 PASS/0 skip/NEW 0/exit 0. 같은/다른 토큰과 정확한 만료/직후, 한 번의 timer 취소·재생 거절 및 기존 goal lease/core/native handover/Fleet loss·구조/안전 회귀를 검증했다. 별도 task-18-goal-lease-return은 실제 HTTP 복귀/정지 인계/authority·trip lease 186 PASS/0 skip/NEW 0/exit 0이며 합산하지 않는다. 독립 scoped 안전 검토 및 trailer 검사 PASS. 로그는 C:/DevTemp/station-charge/각 task 디렉터리다.
- gate 변화: 기존 lease 계약 복구의 소프트웨어 근거다. 총 운행 시간·최종 출력 중단·공간 상한을 아직 제공하지 않는다. 늦은 최초 제출·지속 갱신·비동기 cancel과 ordinary NAV의 범위를 CORE/Fleet 경로로 별도 해결해야 한다. 유한 에너지 budget/factory 활성화, 실제 장치·현장 수용과 전체 CI를 주장하지 않으며 충전 목표 ACTIVE다.

## 2026-10-19 · 1fc85c6f9 · (origin #92 2026-10-17) 최종 발행과 후처리 관측 분리

- 변경: 기존 ROSBridge._send_twist는 동일 publisher의 ROS 발행만 수행한다. D-422 wheels_sent와 5초 경고 제한은 _note_wheels로 옮겨 cmd_vel_cycle의 notify_written에 연결했다. 정상 host write와 성공한 ZERO fallback만 Port close·trial transaction 해제 후, power/events 전에 알린다. 관측 예외는 전달 불명으로 바꾸거나 이동 명령을 재시도하지 않는다.
- 증거: a93774889 writer-observation-red 원격 exit 1, NEW 16으로 미구현 callback/배선을 확인했다. 새 시험은 actual Port·BoundedTrial과 다른 스레드의 잠금 획득 및 SQLite transaction으로 후처리 순서를 검증한다. 독립 scoped source 안전 검토 PASS이며 수정 커밋의 원격 GREEN은 아직 대기다. 로컬 pytest는 실행하지 않았다.
- gate 변화: 향후 실제 출력 fence 안에 관측·로그 잠금이 들어가지 않게 하는 준비다. parent/budget 최종 fence·native 연결·capability는 아직 활성화하지 않았다. host publish 정상 반환은 물리 수신·정지 증거가 아니다. 전체 충전 목표와 DEVICE/FIELD 수용은 계속 미완료다.

## 2026-10-19 · 7d5eadfd3 · (origin #92 2026-10-17) 발행 후 관측의 원격 회귀 확인

- 변경: 기존 actual_publish_method 시험 fixture에 _note_wheels를 명시하고 정상/거부 ZERO의 전체 성공 발행 목록과 관측 목록의 일치를 확인했다. source 1fc85c6f9는 변경하지 않았다. 자체 journal heading도 실제 source hash로 교정했다.
- 증거: 첫 GREEN 요청은 잘못된 test/test_module_structure.py 경로로 exit 4/미실행이었다. 교정한 경로의 1fc85c6f9는 319 PASS/0 skip/NEW 1 FAIL(새 callback이 없는 시험 fixture)이었다. 최종 writer-observation-green-final 7d5eadfd3 원격은 320 PASS/0 skip/NEW 0/exit 0이며 known_failures로 확인했다. 독립 scoped source·fixture 검토 PASS. 로그는 C:/DevTemp/station-charge/writer-observation-green-final/run-1.txt.
- gate 변화: 후처리 분리의 host 검증을 완료했다. ROS 구성/장치 설치·물리 정지 수용·budget 최종 fence·운영 자동 충전 활성화는 계속 남아 있다. 카메라·이동 로봇 현장 확인은 담당자가 나중에 수행할 예정이며 이번 변경에서 장치 설정이나 모터를 조작하지 않았다.

## 2026-10-19 · 01a901f3a · (origin #92 2026-10-17) 동일 최종 cycle에 실행 receipt 제한 연결

- 변경: actual CommandManager의 모든 cycle과 ZERO/예외 경로를 같은 비차단 cycle lock으로 직렬화했다. 최초 legacy cycle이 시작된 뒤 제한을 설치하지 못하며 중복/재진입은 두 번째 ZERO나 이동을 발행하지 않는다. 선택 직후 receipt를 캡처하고 기존 trial의 느린 검사가 끝난 안쪽에서 같은 Port를 제출한다. 준비 확인/제출 예외는 원래 receipt parent를 소모하며 관측은 모든 출력 잠금 밖에서 처리한다.
- 증거: 실제 CommandManager·ModeMachine·Budget/Ledger·기존 BoundedTrial·cmd_vel_cycle을 결합한 RED 19건, 별도 reviewed defective witness의 3건과 추가 fault closure witness의 4건을 원격으로 재현했다. 독립 scoped source/회귀 검토 PASS이며 수정 source의 결합 원격 GREEN은 대기다. 공통 ROS publisher와 ros_bridge.py 888 lines는 변경하지 않았다.
- gate 변화: private 제한의 host 검증 준비다. raw Nav2 논리 출처는 UNATTRIBUTED이며 선언한 child metadata를 실제 native admission으로 취급하지 않는다. 운영 factory/capability를 켜지 않았고 ROS 실행·실기 설치·물리 정지/접안 정밀도 수용과 전체 충전 목표는 미완료다.

## 2026-10-19 · a9efc3800 · (origin #92 2026-10-17) 실제 final cycle의 예산 제한 회귀 통과

- 변경: source 변경 없이 원래 receipt의 1회 제출·실제 final 시각 재검사·모든 실제 cycle의 직렬화와 host/실기 경계를 계획에 기록했다. 기존 ROS publisher와 후처리 순서는 유지했다.
- 증거: execution-writer-green 원격 572 PASS/0 skip/NEW 0/exit 0, independent scoped review PASS. 특히 tick 없는 MANUAL/EMERGENCY 인계, policy/준비 callback 중 parent/child 교체·입력 clear·payload 변경, slow trial/TTL/watchdog 만료, Mode/Ledger/Budget 경합, 중복/재진입·전달 불명·원래 receipt 재생과 callback 오류 뒤 새 parent 보존을 포함한다.
- gate 변화: private restriction의 source/host 근거다. 실제 ROS graph/장치 설치·실측 정지·운영 charging capability를 새로 검증한 것이 아니다. actual native owner·Fleet cost/factory·DEVICE/FIELD와 전체 목표는 계속 남아 있다.

## 2026-10-19 · f9c05107a · (origin #92 2026-10-17) 정상 선택 교체의 ZERO와 다음 주기 재개

- 변경: private fence의 정상 context 교체 결과를 기존 PortDecision 거절로 전달해 같은 writer에서 ZERO를 발행한다. 원래 receipt를 소비하고 다음 주기의 새 선택만 다시 검사한다.
- 증거: 61e95e784 execution-refresh-green-final 관련 원격 745 PASS/0 skip/NEW 0/exit 0. 정책/최종 writer 경계의 input·선언 generation 갱신, 동시 변조·STOP·TTL/예산/clock·속도 제한·재생을 포함한다. 독립 scoped 검토 PASS.
- gate 변화: host 검증이며 native owner·ROS/장치 설치·실측 정지 수용은 남아 있다.

## 2026-10-19 · cfa8ab1ad · (origin #92 2026-10-17) 실제 CoreServices의 private native 조립

- 변경: 기존 mode 권한을 유지하는 명시적 최초-cycle 전 설치와 full-invocation 1회 ticket을 추가했다. fence 공개 전 native domain을 닫고 실제 owner receipt에서 child를 구성한다. Dock phase 변경 전에 Dock→Nav 순서로 STAGING token을 폐기한다.
- 증거: 실제 Nav/Dock manager와 같은 final writer를 사용한 관련 원격 363 PASS/0 skip/NEW 0/exit 0, 신규 native 회귀 23개. admission callback 중 만료/수동 인계·spec 변경, 성공 후 옛 입력 제거, 취소 전 ZERO와 옛 terminal cancel의 새 reservation 보호를 포함한다. 확장 검사와 후속 Undock 회귀는 이 수치에 포함하지 않는다.
- gate 변화: 기본 factory가 설치하지 않는 private 조립이다. ROS/Gazebo·물리 착좌/이안·운영 capability 수용은 별도다.

## 2026-10-19 · 605ba2c17 · (origin #92 2026-10-17) native 이안과 handover 이벤트 재검증

- 변경: 기존 handover 이벤트 식별자 문서 누락을 API-002 Corrective로 수정하고 중복 호출의 단일 이벤트를 확인했다. wire나 mode 권한은 바꾸지 않았다.
- 증거: 모델 PC 원격 native-owner-catalogue-green 256 PASS/0 SKIP/NEW 0/exit 0. 24번째 native 회귀는 주입한 dock 완료·release 뒤 실제 Undock admission·첫 ZERO WAIT·역방향 controller candidate를 같은 parent/Budget/final writer로 통과시켰다. 실제 charger/contact/정지 수용의 증거는 아니다. event catalogue·handover·protocol·harness/network도 통과했다. 독립 scoped 검토 PASS다.
- gate 변화: private host 근거다. 기본 runtime·실측 source/profile·전체 충전 주기와 DEVICE/FIELD는 남아 있다.

## 2026-10-19 · a67abda37 · (origin #92 2026-10-17) 실제 거리계 callback의 private Budget 관측

- 변경: `_on_odom`은 변환 전에 parent와 Ledger monotonic clock을 캡처하는 ROS-free adapter를 호출한다. 원본 source 시각·좌표계·body frame·planar pose와 같은 쓰기의 epoch를 Budget에 전달한다. 읽기 실패나 교체는 원래 parent에만 반영한다. bridge는 887줄로 크기 row를 낮췄다.
- 증거: 원격 RED 17 FAIL/NEW 17, 최초 확장 351 PASS/1 FAIL(크기 row 누락), 최종 관련 352 PASS/0 SKIP/NEW 0/exit 0이다. 신규 17건과 기존 native/writer/odom/lane/CORE/bridge 등록·구조·안전·harness를 포함한다. 독립 scoped 검토 PASS. manifest FULL의 lab mapped 51대상은 별도 실행 중이다.
- gate 변화: private 설치가 있을 때의 source/host 근거다. 기본 factory·ROS/device clock/profile·기존 StationMotionFeed epoch 조회와 운영 HTTP 통합, 전체 충전 및 DEVICE/FIELD 수용은 별도다.

## 2026-10-19 · 2b1991f85 · (origin #92 2026-10-17) 실제 station motion과 원본 receipt 공유

- 변경: fence가 없는 명시적 SIM station도 원래 feed/읽기 하한과 같은 메시지의 epoch를 사용한다. 이후 state scope 조회로 재표기하지 않는다. 원본 pose/twist·frame을 검사하고 실패는 캡처한 feed만 비운다. 기존 wiring 시험도 전체 raw message를 실제 receive_odom에 전달한다.
- 증거: 이전 a67 mapped 7367 PASS/217 SKIP/1 FAIL은 실제 통합 시험 다섯 경로의 D-184 등록 누락으로 별도 보완했다. 새 motion RED는 12 PASS/17 FAIL, clock 추가 RED는 12 PASS/21 FAIL이다. 첫 수정 관련 515 PASS/1 FAIL은 연속 camera HTTP SIM의 동명 test helper 충돌이다. 49564de0e의 test-only import 수정 뒤 같은 23대상은 516 PASS/0 SKIP/NEW 0/exit 0이다. continuous는 JPEG 인식·HTTP·실제 native/final writer의 충전 세션 3개·이안/작업 3회·복귀/재충전 2회와 station relocation을 포함하지만 contact/BMS·odom·clearance·energy는 합성 source다. 독립 scoped 검토 PASS다.
- gate 변화: 실제 source/owner admission의 host 경계 보강이다. profile·운영 factory·HTTP native ticket·실측 착좌/충전·DEVICE/FIELD는 남아 있다.

## 2026-10-19 · 165c317e5 · (origin #92 2026-10-17) parent 이전 원본 odometry receipt

- 변경: private native 설치가 exact Limits/profile을 받고 parent 없이도 실제 bridge의 원래 header·clock·planar pose/전체 twist·same-write scope를 불변 receipt로 유지한다. 실패 header 소모·반복 수명 보존·clock fault와 오래 끝난 read를 구분하며 final writer에는 source lock을 추가하지 않는다.
- 증거: 미구현 RED 1 PASS/17 ERROR, 추가 RED 1 PASS/21 ERROR는 absent installer API의 setup 실패다. 경로 오기 요청은 수집 전 exit 4였다. 실제 첫 관련 538 PASS/2 FAIL은 lane observer의 clock 재조회에도 interposition을 반복한 신규 fixture 오류다. test-only bd3aebe7f 수정 뒤 같은 24대상은 540 PASS/0 SKIP/NEW 0/exit 0이며 신규 bootstrap 21건을 포함한다. source와 fixture 각각 독립 scoped 검토 PASS다.
- gate 변화: 원본 source의 host 근거다. map/energy 인증·운영 HTTP/factory·전체 3회 복귀와 DEVICE/FIELD는 미완료다. FULL CI나 이번 continuous SIM 실행을 주장하지 않는다.

## 2026-10-19 · 78b095ec8 · (origin #92 2026-10-17) 실제 원본 지도 callback과 parent STOP

- 변경: `_on_map`과 map-server/SLAM lifecycle을 ROS-free adapter에 연결했다. 원래 parent에 먼저 STOP을 요청하고 raw 전체 grid를 NavigationManager에 조립된 Drive evidence owner로 넘긴다. render는 별도 read path다. 동일 grid 재수신도 정지시키는 보수적인 진행성 한계가 있다. 기본 factory는 이 제한을 설치하지 않는다.
- 증거: 미구현 RED 1 PASS/29 FAIL/8 ERROR/NEW 37은 adapter/evidence module 부재다. source 78b095ec8의 관련 원격 32대상은 651 PASS/0 SKIP/NEW 0/exit 0이다. 신규 지도 37건, 이전 native/writer/odom/station source, map/readiness/MANUAL/SLAM·구조/안전/harness를 포함한다. 기존 표시 ID 문자열 guard는 실제 값 검증과 좁은 callback delegation guard로 바꿨다. 독립 scoped source 검토 PASS, bridge ratchet 887→881이다.
- gate 변화: CORE가 관측한 원본 지도와 software STOP 요청 경계다. backend 소비/채택 ACK·승인 revision/변환·energy·운영 HTTP/factory·물리 정지/실기 정밀도는 미완료다. FULL CI·이번 continuous SIM/DEVICE/FIELD 실행은 아니다.

## 2026-10-19 · d3c1017f8 · (origin #92 2026-10-17) cached TF의 위치 수명 재갱신 제거

- 변경: 원본 dynamic TF의 시각/frame/planar geometry와 전체 read/State lock 대기를 ROS-free adapter에서 검증한다. 같은 header 수명은 연장하지 않는다. map/lifecycle 갱신은 exact-parent STOP과 map ticket/epoch 뒤 TF를 무효화한다. line clock의 비정상·미래 capture는 odom ownership으로 거절한다. bridge ratchet은 881→874다.
- 증거: RED 2 PASS/4 FAIL/22 ERROR는 새 module 부재 22건과 기존 clock helper 실패 3건/구조 1건이다. source d3c1017f8 관련 30대상은 705 PASS/1 FAIL/0 SKIP/NEW 1이다. 실패는 제거된 inline receipt 갱신을 기대한 AST guard다. 그 테스트만 바꾼 d261d4698의 TF/cross-lane/localization API/state odom/ownership 5대상은 98 PASS/0 SKIP/NEW 0이다. 각각 독립 scoped PASS. [검증 기록](../../../docs/validation/station-map-pose-freshness-2026-10-17/result.md).
- gate 변화: 위치 ownership과 후속 admission의 host 검증이다. ongoing command 정지·native adopted-map/승인 좌표·원본 energy·HTTP/factory·전체 3회 복귀·실기 수용은 남아 있다. 전체 목표 ACTIVE이며 FULL CI·장치 배포·현장 운행 증거로 올리지 않는다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) CORE native map evidence 소유자 RED 준비

- 변경: 실제 MapEvidence 원본/MapObservation 객체와 캡처 parent에 두 readback을 묶는 ROS-free 회귀를 추가했다. 두 응답·첫 bracket 기준 만료·provider/nonce one-use·원본 교체·reset 후 높은 generation·gap 비복구·옛 callback의 새 parent 비간섭·옛 selection deadline·source-lock 없는 writer predicate를 검사한다.
- 증거: 아직 실행 전이다. native 소유자 모듈이 없는 현재 revision의 import/setup RED부터 확인한다. synthetic native replies를 사용한 소유자 단위 시험이며 실제 ROS 응답/최종 writer·운행 수용으로 계산하지 않는다.
- gate 변화: 없음. 기본 factory와 실기 활성화는 바꾸지 않으며 전체 스테이션 목표는 ACTIVE다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) native owner 경계 회귀와 실제 generated-array 소비 경로

- 변경: 독립 검토의 clock 재검증/실제 fixed-array 타입 지적에 맞춰 source getter·reply 검증 지연 회귀와 bounded buffer 복사를 추가했다. 같은 SHA interfaces 생성·serialization 뒤 실제 numpy fixed array를 domain 값으로 캡처·불변 복사·negative 응답 거절하는 원격 ROS 검증 경로도 추가했다.
- 증거: source AST 확인만 했으며 검토 수정본의 원격 실행은 아직 전이다. 기존 소유자 RED는 모듈 부재 setup 오류이며, 새 generated-array 검사는 실제 producer ACK/운행 증거가 아닌 synthetic wire 소비 시험이다.
- gate 변화: 없음. bridge 실제 client wiring과 final writer의 required/CLOSED 설치·admission/만료 거절은 후속 작업이다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 실제 generated 응답 소비와 owner 수명 검증 기록

- 변경: [native owner 검증](../../../docs/validation/station-native-map-owner-2026-10-17/result.md)은 순수 owner/변환 시험을 실제 ROS client·CORE writer 연결과 구분한다. domain unit은 services/test에 두고 generated helper의 gateway seam만 등록했다.
- 증거: a90891d712 원격4대상110 PASS/0 SKIP/NEW0. 동일 production64accf7fe9의 actual generated response 두 roundtrip·immutable capture/negative 거절과 interfaces/wire 검증 exit0이다. 이전 native producer30건을 재실행하거나110건에 합산하지 않았다.
- gate 변화: 없음. 일반 factory와 하드웨어는 활성화하지 않으며 실제 bridge/fence/운영 전체 연결은 후속이다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 실제 비동기 native map client RED 시험

- 변경: 실제 generated MapAdoption DDS 서버와 CORE client 간 nonce·두 role 응답·갱신·옛 선택 만료·timeout/late reply·replacement parent·closed/missing service 검증 경로를 추가했다. 서버 값과 clock/parent는 합성이다.
- 증거: 아직 실행 전이다. 실제 native consumer ACK·writer·factory·장치 수용은 시험 범위에 포함하지 않는다.
- gate 변화: 없음. 기본 bridge 생성·timer와 현장 장치는 바꾸지 않았다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) native map 비동기 통신 소유

- 변경: 명시적 create에서만 generated MapAdoption client 두 개를 생성하고 실제 client identity를 consumer profile에 묶는다. ROS-free orchestration은 nonce 발급·issue bracket·async 완료·buffer capture·예외/취소/overlap·pending detach를 처리하고, close는 완성된 증거도 영구 무효화한다. 기본 RosBridge/timer/factory에는 아직 설치하지 않는다.
- 증거: 구현 전 transport 모듈 부재 collection RED와 owner 종료 API 부재 61PASS/1FAIL을 승인 원격 pytest에서 확인했다. 실제 DDS RED 시도는 sim floor 미달로 아직 실행되지 않았다. 구현 수정본은 독립 안전 검토 중이며 원격 GREEN은 아직 없다.
- gate 변화: 없음. native consumer ACK·required/CLOSED source·admission/final writer·장시간 nonce 수명·실기 검증은 남아 있다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) map TF 의존성 선언 복구

- 원인: 새 통신 경로와 함께 실행한 C6 검사가 이전 map_pose 변경의 getattr fallback을 발견했다. 실제 RosBridge는 이미 _map_pose_lease를 생성하며, fallback은 오래된 ROS-free fixture의 필드 누락만 숨기고 있었다.
- 변경: 선언된 bridge._map_pose_lease를 직접 사용하고 TF reader 없는 fixture는 None을 명시한다. C6 allowlist·scanner는 바꾸지 않는다.
- 증거: 2fd55d947b 원격 7대상은 134PASS/1FAIL/0SKIP/NEW1이며 유일한 실패가 이 C6 의존성 검사다. 수정본의 지도/TF 회귀 검증은 아직 전이다.
- gate 변화: 없음. ongoing MAP→ODOM frame loss 정지나 native final writer 연결 완료를 뜻하지 않는다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 비동기 client 검증 기록

- 변경: [검증 기록](../../../docs/validation/station-native-map-clients-2026-10-17/result.md)에 실제 generated DDS와 ROS-free Future 시험 범위를 남겼다.
- 증거: source2fd55d947b 실제 DDS PASS/exit0. C6 원인 수정 cd53393a09에서 통신·map/TF·구조9대상198PASS/NEW0이며 독립 scoped source review도 통과했다.
- gate 변화: 없음. 기본 factory/timer 변경과 actual native admission·final writer 연결은 아직 하지 않았다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) required native map의 실제 writer RED 사례

- 변경: 실제 Navigation/Docking manager와 sole writer를 대상으로 지도 증거 미설치/한 role만 완료/실패 설치 재시도/첫 ZERO cycle 이후 설치 거절, callback lock 정지 중 final expiry, 옛 selection 수명 비연장, 정상 refresh, source/generation/close, gap, 옛 callback/새 parent를 검증하는 시험을 추가했다. map readback·clock·pose는 합성이다.
- 증거: 구현 전 실행 대상이다. 특히 미설치 admission은 기존 실제 manager 동작을 검증하며 missing API setup 오류와 구분한다.
- gate 변화: 없음. 장치/현장 수용과 실제 runtime factory는 아직 닫혀 있다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) native map REQUIRED/CLOSED와 actual boundary 연결

- 변경: native installer가 확보한 Fence는 지도 증거 슬롯이 없으면 닫힌다. trusted NativeExecution의 첫 cycle 전 단 한 번 설치만 허용하고 실패 claim은 재시도하지 못한다. 실제 nav의 원본 source pointer와 exact parent/retained sample을 native entry/readiness/receipt 동기화·selection/final submit에서 검사한다. 기본 non-native factory는 바꾸지 않는다.
- 증거: d91751aa30 승인 원격 RED는 5FAIL/8ERROR였다. 두 실제 NAV/dock admission은 증거 없이 허용돼 DID NOT RAISE였고 나머지는 install API 부재다. 수정본은 source AST만 통과했으며 독립 검토와 원격 회귀 전이다.
- gate 변화: 없음. fixture는 실제 manager/writer와 합성 readback/pose를 묶으며 운영 runtime factory·장시간 용량·물리 정지는 별도다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) clock 경합 fixture의 lease identity 수정

- 원인: ab7d2c2f3c 원격8대상은 232PASS/1FAIL이었다. entry clock-refresh 회귀가 lease_ttl_s를 주면서 기존 필수 correlation_id를 빠뜨려 해당 경합 검증 전 VALIDATION_ERROR로 실패했다.
- 변경: 그 시험에 correlation_id를 명시한다. production source는 바꾸지 않는다.
- 증거: 수정본 재실행 전이다. 다른 실제 manager/writer 거절·비차단/만료 사례는 앞 실행에서 통과했다.
- gate 변화: 없음.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) native map actual admission/writer 회귀 PASS

- 변경: [검증 기록](../../../docs/validation/station-native-map-writer-2026-10-17/result.md)에 pre-cycle 일회성 설치·실제 native entry·retained sample 최종 제출·normal poll 경합을 남겼다.
- 증거: 1144e9e4e0 원격13대상296PASS/NEW0, source ab7d2c2f3c는 독립 scoped 안전 검토 PASS다. callback lock 정지 중 만료와 old callback/new parent도 실제 manager/writer에서 검사했다.
- gate 변화: 없음. 실사용 factory·실제 native readback 3회 전체 주기·장시간 용량·장치는 남아 있다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 지속 운행의 frame-only 위치 상실 RED

- 변경: LOCALIZED 이름을 유지하면서 map→odom으로 바뀌는 tick/state에 대해 HTTP 운행 취소·재개 방지·MANUAL 유지, 실제 native NAV/dock parent 소비, 원본 TF 만료→기존 운행→다음 wheel 출력 정지를 검증하는 회귀를 추가했다.
- 증거: 구현 전 RED 실행 대상이다. 위치·TF·readback은 합성이며 실제 manager/writer를 사용한다.
- gate 변화: 없음. 물리 위치 정밀도·장치 수용은 별도다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) frame 상실과 실제 운행 정지 연결

- 변경: HTTP/line-follow·실제 native parent·original TF→writer 회귀와 frame loss가 goal check와 start 사이에 들어오는 gate 경합을 검사한다. 복구 후 기존 운행 재개와 MANUAL 중단을 허용하지 않는다.
- 증거: 원격 RED는 146PASS/8FAIL이었다. 수정본은 독립 검토와 원격 회귀 전이며 profile/TF/readback은 합성이다.
- gate 변화: 없음. 물리 위치·actual native factory·전체 충전 주기는 아직 별도다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) frame 수정 회귀와 event tuple 모호성 정리

- 원인: d0fd038c43 원격13대상은 375PASS/2FAIL/0SKIP이었다. 첫 CANDIDATES에서도 정지하는 새 동작에 기존 cancel-count fixture를 맞춰야 했고, 이벤트 scanner가 native transport의 (pending-dict, empty-dict) 다중 대입 RHS를 dynamic event tuple로 읽었다. 완료 로그를 받아온 뒤 driver stdout cp1252 출력도 실패했다.
- 변경: 첫 invalid 취소를 별도로 확인하고 카운터를 비운 뒤 취득 callback을 확인한다. pending 분리는 같은 lock 안의 순차 대입으로 풀어 scanner의 모호한 tuple을 제거한다. scanner/allowlist는 바꾸지 않는다.
- 증거: 수정본 독립 검토·원격 재실행 전이다. 다음 driver 호출에는 UTF-8 stdout 환경만 명시한다.
- gate 변화: 없음.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) frame-only loss 실제 운행 회귀 PASS

- 변경: [검증 기록](../../../docs/validation/station-localization-frame-loss-2026-10-17/result.md)에 original TF 만료·HTTP/native NAV/dock 정지·gate 경합·MANUAL 유지·복구 비재개를 남겼다.
- 증거: 승인 원격14대상387PASS/NEW0. pending 순차 대입도 실제 Future 회귀와 event guard를 통과했으며 source 수정 두 건은 독립 scoped 안전 검토 PASS다.
- gate 변화: 없음. actual native ACK/운영 factory/전체 충전 주기와 물리 장치는 별도다.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) original pack energy admission counterexample

- 변경: Add actual CoreServices/native composition counterexample: parent adoption without any measured energy must return no handle and dispatch no native run. Existing fixture can now stop before parent admission. Remote behavioral RED pending; no product source changed.
- 증거: Remote execution pending; test source only.
- gate 변화: none. Full station goal remains ACTIVE.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) independent map proof and energy context loss

- 변경: extend the actual-manager counterexample to navigation and docking entry after loss of the private energy slot while native map proof and original Budget remain valid. It asserts no backend/run/mode side effect, consumed parent and next sole-writer ZERO.
- 증거: not executed. The first committed parent-admission counterexample is still in the approved runner no-host retry window. No product energy code changed.
- gate 변화: none.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) new energy log formatting correction

- 변경: Correct only the new entries created in bab06a2c34/4449dc4772/4be5552ec7: PowerShell stdin encoding replaced separators and required field labels were missing. Earlier session records and verification facts are unchanged.
- 증거: Initial lint caught 4 malformed headings; corrected headings then exposed missing labels and the HEAD append-only comparison. This explicit format repair is recorded, with post-commit lint still required.
- gate 변화: None. No source implementation, test execution or device acceptance is claimed.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) original energy remote verification not run

- 변경: R2 energy plan and test-only commits are retained for continued execution. No product energy implementation or runtime/device change was made.
- 증거: remote_pytest on bab06a2c34, test_native_execution_binding.py, approved first two test hosts, completed exit 1 after the default 600 s no-host retry. Tests did NOT run: no collection, behavioral RED, PASS count or run-1.txt; known_failures comparison is unavailable. Latest pure-source and slot-loss tests also remain unexecuted. Local committed-tree lint passed with 0 errors/33 warnings after the explicit journal-format repair; AST/diff checks pass.
- gate 변화: None. Full station goal remains ACTIVE; this is the first consecutive test-infrastructure interruption after prior source progress. No local test fallback, landing, push or hardware activation.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) original pack energy restriction implementation

- 변경: Add serialized private pack ingress, releasing source locks before modes-to-ledger publication; install exact source once before first cycle. Native parent/entry/selection/final writer require original and latest published energy, matching profile/load/clock and full-window reserve. Failed admission consumes the attempt and returns no handle; positive native test fixtures now explicitly install synthetic energy.
- 증거: Independent scoped static review PASS and source AST; execution pending. Regression oracles cover source clock offsets, full future window, pending new admission, low-to-high STOP, decoder cleanup, selected deadline, cap eight and fault/healthy publication after an entered writer. No tests were executed on these edits.
- gate 변화: None. No ROS subscription/vendor adapter, runtime deployment, restart, physical movement or automatic activation.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) private energy handover naming

- 변경: Rename EnergyContext.publish to finish at its definition and sole ingress call. Behavior, lock order, immutable cache and STOP ordering are unchanged.
- 증거: Read existing event catalogue scanner: it treats every non-ROS .publish call as an event emission, which this private fact handover is not. No scanner, allowlist or event contract changed. Static AST only; independent scoped static review PASS, no runtime test result.
- gate 변화: None. Existing remote source job still requests ba4868ef59; it does not test this subsequent naming change.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) non-simulation station source evidence

- 변경: Preserve source commits ba4868ef59 (energy restriction) and e5f51f5c7 (internal completion naming) with independent scoped static safety reviews, plus attended runbook and validation/station-pack-energy-source-2026-10-17/result.md.
- 증거: Both official default-three-host pytest requests ended exit1 after600s with no hosts and no tests/report/RED/GREEN. Source request covered ba4868ef59 only; latest naming-only source also remains unexecuted. Changed Python AST/doc links/diff pass; harness lint0errors33warnings; source safety_review/size_range checked both commits successfully. FULL CI remains required and unrun. No simulation, local pytest, deployment, landing or push.
- gate 변화: None. Actual vendor energy port, hardware factory/Fleet HTTP closure, source-rate capacity/long-run map limits and deferred physical three-cycle/relocation acceptance remain.


## 2026-10-19 · uncommitted · (origin #92 2026-10-17) map refresh fixture preserves installed energy clock

- 변경: 공유 native 시험 fixture에 동일 trusted clock callable 안의 갱신 hook을 추가했다. map 갱신 경합 시험은 실행 중 Ledger clock을 교체하지 않고 capture 이후 갱신을 재현한다. 별도 반례는 같은 숫자를 반환하는 시계 교체도 ZERO/STOPPED가 됨을 요구한다. 제품 제어·에너지 제한은 변경하지 않는다.
- 증거: 57a136d87 공식 원격 회귀 581 PASS/2 FAIL/NEW 2. 두 실패의 기존 시험이 Ledger clock을 교체해 설치된 energy clock과 다른 객체가 되는 직접 원인을 확인했다. 수정은 시험만이며 전체 회귀를 새 커밋에서 재실행한다.
- gate 변화: 없음. 실기/현장 수용·FULL CI를 대신하지 않는다.

## 2026-10-21 · ed405d1ecf · native map client cleanup

- 변경: 개별 destroy_client 예외/false 뒤에도 나머지 client의 해제를 시도하고 실패를 보고한다. failed create는 원래 구성 예외를 유지한다. evidence 폐쇄·pending 분리·CORE writer 경계는 유지한다.
- 증거: source53c7d91367 native RED2FAIL/11PASS와 실제 generated DDS RED exit1 뒤 sourceed405d1ecf native137PASS/0SKIP/NEW0 및 실제 DDS exit0. 기본 parent64/global nonce65536의 빠른 합성 clock 용량 경계와 frame 복구 후 새 Budget/ACK/navigation 성공을 추가 검증했다.
- 검토: native_map_cleanup_review 독립 안전 검토 승인, Safety-Review trailer 기록. 정본 docs/validation/pipeline-native-map-cleanup-2026-10-21/result.md. 운영 factory·장시간 운행·장치/현장 수용은 HOLD다.
- gate 변화: 없음. SOURCE/native 정리·합성 수명 경계와 복구 회귀 범위이며 운영 factory·장시간 운행·장치/현장 수용은 별도다.

## 2026-10-24 · a7aaaed472 · 원래 실행에 한정한 관제 취소와 결과 종단

- 변경: boot/run/correlation이 현재 owner와 일치할 때만 잠금 안에서 취소하는 별도 경로를 추가했다. 기존 trip lease의 수명을 바꾸지 않아 취소 직후 새 owner가 들어오는 경쟁에서도 새 실행을 보존한다.
- 증거: receiver·lease·Fleet sender/transport201 PASS, 별도 실제 Fleet dispatch→CORE→native 완료/취소 재조정2 PASS. odometry·localization·actuator는 합성이고 실제 정지 증거가 아니다. [검증 기록](../../../docs/validation/control-unit-pipeline-2026-10-24/result.md).
- gate 변화: 기존 장치/FIELD gate는 유지한다. 최종 통합 검사와 공식 착지는 대기한다. CE 해당 없음: 경쟁과 receipt 범위를 회귀로 보존했다.
