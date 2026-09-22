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
