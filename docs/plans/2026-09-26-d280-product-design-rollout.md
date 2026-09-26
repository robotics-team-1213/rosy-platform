# D-280 ROSY 제품 디자인 철학 적용 계획

**Goal:** `차분한 지능에 은은한 따뜻함`을 운용 화면, Fleet, 로봇 얼굴, 설치·정비, 제품 문서에서 관찰 가능한 디자인 기준으로 적용한다.

**Architecture:** D-280은 제품 성격을, concept 16과 D-153은 화면 법칙과 평가 방법을 소유한다. 먼저 현행 접점의 대표 장면을 기록하고, 한 접점씩 정보 위계·문구·복구 동선을 개선한 뒤 G1/G2/G3와 장치 증거로 판정한다. 새 토큰·프로토콜·권한·동작은 이 계획만으로 열지 않는다.

**Tech Stack:** 현행 FastAPI 정적 웹 UI, `src/hmi/web` 토큰·공유 부품, Fleet 웹 콘솔, PIL 로봇 얼굴 렌더러, pytest, Playwright, Pi/LCD 벤치 증거.

**Status:** 실행 계획. 작업별 완료와 제품 전체 수용은 별도 기록한다.

---

## 범위와 순서

| 순서 | 작업 단위 | 핵심 결과 | 다음 단계 조건 |
|---|---|---|---|
| 0 | 기준선과 대표 장면 | 접점별 질문·현재 캡처·불확실성 목록 | 변경할 문제를 장면과 근거로 지목 |
| 1 | 공통 표현 규칙 | 문구·정보 위계·온기 사용 범위의 적용 예 | concept 16/D-277/D-278과 충돌 없음 |
| 2 | 운용·설치 웹 | 상태와 다음 행동을 빠르게 찾는 화면 | 역할·권한·안전·복구 계약 통과 |
| 3 | Fleet | 예외 우선 관제와 읽기 쉬운 밀도 | 로봇 상태와 Fleet 장애를 구별 |
| 4 | 게임 호스트 | 경기 상태가 선명한 초점 화면 | 가시성·HOLD·정지 판정 확인 |
| 5 | 로봇 얼굴·장치 신호 | 멀리서 읽히는 의도, 같은 상태를 전하는 출력 | D-260 계약과 LCD/LED/음향 벤치 증거 확인 |
| 6 | 제품 문서·통합 평가 | 접점 간 같은 성격, 검증된 주장 | 표면별 G1/G2/G3와 증거 등급 명시 |

선행 관계: D-279 역할별 빈 상태·복구 작업은 별도 계획(`2026-09-26-role-aware-empty-state-recovery-plan.md`)이 소유한다. 여기서는 그 결과를 운용·설치 화면 평가에 포함하고 구현을 중복하지 않는다. D-255의 B2(벤치 합동)와 B3(진단 편입)는 이 계획이 자동으로 닫지 않는다.

## Task 0 — 기준선과 대표 장면 확정

**읽을 파일:** `docs/adr/D-280-calm-intelligence-product-design-philosophy.md`, `docs/architecture/16_ROSY_Interface_Design_Principles.md`, `docs/adr/D-153-ui-ux.md`, `docs/adr/D-255-uiux-evaluation-round-2.md`, `docs/validation/uiux-surfaces-2026-09-26/README.md`, `STATUS.md`.

1. 기존 LOCAL 캡처 15셀을 접점·상태·뷰포트별로 대조한다. fixture 합성값과 실제 CORE/장치 값을 분리해 기록한다.
2. 운용 화면에서 `지금 움직여도 되는가`, Fleet에서 `어느 로봇에 주의가 필요한가`, 게임에서 `경기장·공·로봇·골이 보이는가`, 설치 화면에서 `무엇을 확인·조치·재확인할까`, 얼굴에서 `다음에 무엇을 할까`, 기기 상태 신호에서 `로봇이 준비·주의·실패 중 무엇인가`를 대표 과제로 정한다.
3. 각 과제의 정상·지연/연결 끊김·빈 상태·권한 거부·위험 상태 중 해당하는 셀을 선언한다. 없는 상태는 캡처를 꾸미지 말고 미평가로 남긴다.
4. `docs/validation/uiux-surfaces-<date>/README.md`에 현재 장면의 판정과 개선 후보를 `판단 — 근거 셀 — 대안 기각 이유`로 남긴다(D-258). 캡처 작업 중 스크래치 파일은 `X:\DevTemp\`에 둔다.

**완료:** 각 활성 접점에 우선 문제 1~3개가 실제 화면/코드 위치에 연결되고, 잘하는 부분도 기록된다. 게임 호스트의 기존 LOCAL 캡처를 포함한다. 얼굴·부팅음·LED의 실기 근거가 없으면 미검증, 진단은 PARKED로 남긴다. LOCAL 캡처는 DEVICE/FIELD로 표기하지 않는다.

**현재 상태:** 부분 완료. 기존 9월 26일 `console-*` 캡처는 역할별 `/console`이 아닌 구형 `/dashboard` 화면임을 확인했다. 캡처 인상은 구형 화면 근거로만 남기고, 현재 `/{surface}` 셸의 렌더 밀도와 상태 위계는 새 LOCAL 캡처를 얻기 전까지 HOLD다. `docs/validation/d280-product-design-baseline-2026-09-26/README.md`에 이 경계를 기록했다.

## Task 1 — 제품 전체 표현 기준 만들기

**파일:** `docs/adr/D-280-calm-intelligence-product-design-philosophy.md`(기준, 임의 수정 금지), `src/hmi/web/tokens.css`, `src/hmi/web/template.html`, `src/hmi/dashboard/styleguide.html`, `src/hmi/face/emotion/info_screen.py`, `src/site/fleet/fleet/server/web/styles.css`.

1. Task 0의 문제를 `정보 순서`, `상태·복구 문구`, `시각 밀도`, `따뜻함의 사용`, `검증되지 않은 주장`으로 분류한다.
2. 접점별 한 장면에 대한 개선 전/후 안을 만든다. 공통 규칙은 의미와 성격이고, 화면 배치는 접점이 소유한다.
3. 장미색은 D-277의 브랜드 표식 범위, 상태색은 concept 16의 의미 범위 안에 둔다. D-220의 정지 계약에 따라 장식성 애니메이션을 제안하지 않는다.
4. 새 색·부품·행동이 필요하면 해당 소유 ADR과 테스트 범위를 먼저 정한다. D-280을 새 UI 토큰의 포괄 승인으로 읽지 않는다.

**첫 시안의 초점:** 운용 화면은 `준비/제약/정지`의 읽는 순서와 감지·관측·조작 밀도를, Fleet은 지도와 예외 목록의 면적 비율을, 설치 화면은 원인→복구→재확인 문장의 순서를, 얼굴은 의도 형태와 위험 표시의 구분을 다룬다. 현재 색 값을 바꾸는 작업으로 시작하지 않는다. 상단 라벨·숫자·보조 설명의 서체 위계를 현행 닫힌 크기 척도 안에서 정리하고, 같은 의미의 테두리 카드가 반복되는 장면을 줄이는 안을 비교한다.

**완료:** 실제 장면을 놓고 두 사람이 같은 이유로 `적합/수정`을 말할 수 있는 예시와 검토 문장이 있다. 원칙만 나열한 새 스타일 문서로 끝내지 않는다.

## Task 2 — 운용·설치 웹 화면 개선

**후보 파일:** `src/hmi/dashboard/surface.html`, `src/hmi/dashboard/styles.css`, `src/hmi/dashboard/shell/shell.css`, `src/hmi/dashboard/panels/console/overview.js`, `src/hmi/dashboard/panels/console/map.js`, `src/hmi/dashboard/panels/host/operations.js`; 실제 변경 파일은 Task 0 판정 후 확정한다.

1. 콘솔의 가장 중요한 상태·행동이 처음 시선에 드는지 확인한다. 기존 캡처에서 정보 밀도가 높은 감지/관측/조작 영역을 우선 검토한다.
   단, 구형 `/dashboard` 캡처의 시각 판단을 현재 `/console`에 승계하지 않는다. 현재 `surface.html` + 역할 manifest + panel 조립 경로를 1366×768과 390×844에서 LOCAL 렌더하고, 그 캡처를 기준으로 수정 대상을 선택한다.
2. D-279 결과를 받아 지도 빈 상태, 403, 일시 오류, Host Agent 미연결을 원인·역할별로 구분한다. 서버가 제공하지 않은 진단이나 복구 명령을 화면에서 만들지 않는다.
3. 가장 작은 수정 단위를 골라 실패 사례를 브라우저 테스트에 먼저 추가하고, 코드와 문구를 변경한다. E-stop 위치, 44px 대상, 실제 API 권한, D-218 확인 계약은 유지한다.
4. 데스크톱 1366×768과 전화 390×844에서 정상/빈 상태/거부/SAFE_STOP을 확인한다. 무스크롤 화면의 눌림·잘림과 키보드 초점을 점검한다.

**검증:** `src/hmi/web/test/`, `src/hmi/dashboard/test/`, `test/test_dashboard_browser.py`, `test/test_web_dialog_contract.py`의 해당 시험과 D-153 G2/G3. LOCAL 통과 후 실기 화면은 별도 벤치 회차로 둔다.

## Task 3 — Fleet 예외 화면 개선

**후보 파일:** `src/site/fleet/fleet/server/web/console.js`, `src/site/fleet/fleet/server/web/styles.css`, `src/site/fleet/test/test_console_queues_contract.py`, `src/site/fleet/test/test_console_palette.py`.

1. 정상·0/0·로봇 연결 끊김·Fleet 연결 장애·하나의 위험 예외를 별도 장면으로 비교한다.
2. 지도와 로봇 목록의 면적을 작업 질문에 맞춰 재평가한다. 기존 LOCAL 캡처의 큰 빈 지도 영역은 우선 검토 후보이며, 실제 사이트 데이터·화면 크기로 확인한 뒤 변경한다.
3. 예외가 먼저 눈에 들고, 정상 로봇을 경보색으로 칠하지 않으며, 로봇 장애와 Fleet 장애가 다른 문구로 읽히도록 수정한다. 키보드 순회와 전체 정지 접근은 유지한다.
4. 1920×1080 선언 뷰포트에서 목록 내부 스크롤·지도 축소·안전 조작 가시성을 확인한다.

**검증:** Fleet 계약 시험, `test/test_fleet_console_browser.py`의 해당 셀, D-153 G2/G3. 사이트 PC와 실제 로봇 상태에 대한 판정은 LOCAL과 구분한다.

## Task 4 — 게임 호스트의 초점과 경기 가시성

**후보 파일:** `src/site/games/games/web/index.html`, `src/site/games/games/web/styles.css`, `src/site/games/games/web/board.js`, `src/site/games/test/test_visibility.py`, `src/site/games/test/test_preview.py`.

1. play, initial, lost/HOLD 장면과 1280×800 선언 뷰포트를 기준으로 경기장·공·로봇·골·정지 조작을 살핀다.
2. 따뜻한 초점색은 공에, 팀 정체성은 차가운 계열에 둔다. 손실/HOLD는 문장으로 명시하고 정지 행은 항상 보이게 한다(D-101, concept 16 §7.5).
3. 기존 캡처에서 천장 프레임 자산이 깨져 보이는 셀은 의도한 빈 상태인지 fixture/자산 문제인지 확인한다. 원인을 확인하기 전 제품 결함으로 단정하지 않는다.
4. 게임 표면은 D-153 G2/G3로 평가하되 공통 웹 토큰을 강제로 적용하지 않는다.

**검증:** `src/site/games/test/`, `test/test_games_board_browser.py`의 해당 셀, 선언 뷰포트 G2/G3.

**현재 상태:** 프레임 미수신 시 숨김 계약은 수정·검증했다. 기존 캡처의 깨진 대체 텍스트 원인은 `#frame`의 CSS가 `hidden`을 덮은 것이었다. 재현 브라우저 테스트는 수정 전 실패, 수정 후 게임 보드 브라우저 6개 테스트 통과. 이 작은 UI 결함의 LOCAL 확인이며 Task 4의 전체 가시성·G2/G3 평가는 계속 열린다.

## Task 5 — 로봇 얼굴과 장치 상태 신호

**후보 파일:** `src/hmi/face/emotion/info_screen.py`, `src/hmi/face/emotion/rosy_lcd.py`, `src/hmi/face/test/test_info_screen.py`, `src/hmi/face/test/test_info_screen_palette.py`, `src/hmi/face/test/test_info_screen_capture.py`.

1. 이동·대기·도움 필요·위험 정지의 표정/의도 어휘를 현재 이벤트 계약과 대조한다. 서버가 제공하지 않는 의도를 화면이 추측하지 않는다.
2. 320×240 실제 렌더 기준으로 1.5m 거리에서 약 0.5초 안에 의도와 위험 여부가 구분되는지 평가한다. 글자를 읽어야만 이해되는 안은 고친다.
3. 따뜻함은 짧은 표정·형태에 담고 위험 채움과 만료 규칙을 유지한다. 새로운 GIF나 애니메이션은 D-220 및 얼굴 계약과 별도 검토한다.
4. ROS-free 이미지 시험 후 LCD 실물 사진을 남긴다. 화면 생성 성공만으로 실물 가독성을 주장하지 않는다.
5. D-260이 별도 Accepted되고 일관 상태 원천·각 출력 계약이 확정된 경우에만 부팅음·LED·LCD·운용 요약줄을 교차 검토한다. Proposed D-260을 근거로 제품 동작을 바꾸지 않는다.

**완료:** 얼굴은 최소 정상/대기/실패/위험 장면에서 의도를 읽는 결과와 실제 LCD 증거가 있다. D-260 기기 상태 신호는 별도 결정 승격·벤치가 있기 전까지 미착수로 기록한다.

## Task 6 — 설치 경험과 제품 문서

**후보 파일:** `src/hmi/dashboard/panels/host/operations.js`, `src/hmi/dashboard/panels/host/hardware.js`, `docs/deployment/pinky-pro-first-device-runbook.md`, `README.md`; 변경은 해당 문서·코드 주인과 현재 계약 확인 후 결정한다.

1. 설치자가 전원·호스트·네트워크·ROS 그래프·릴리스·커미셔닝 순서에서 막히는 대표 사례를 고른다.
2. 각 실패 장면에 `무엇이 확인됐나 → 무엇을 할 수 있나 → 어떻게 재확인하나`를 제공한다. 관리자 권한이 없는 사람에게 관리자 조작을 권하지 않는다.
3. README와 제품 소개 문구의 능력·지원 플랫폼·검증 수준을 `STATUS.md`와 해당 모듈 증거에 대조한다. 목표 아키텍처를 현재 제공 기능으로 쓰지 않는다.
4. 사진·일러스트·하드웨어 마감은 이 회차에서 자동 결정하지 않는다. 필요한 자산과 실물 소재의 판단은 별도 디자인 결정으로 기록한다.

**완료:** 대표 복구 장면에서 다음 행동이 실제로 가능하고, 공개 문구가 현재 증거를 넘어서지 않는다.

## Task 7 — 통합 평가와 착지

1. 변경된 접점마다 D-153 G1(계약 시험), G2(선언한 상태·뷰포트 캡처), G3(8항 사람 판정)을 현재 트리에서 다시 수행한다.
2. D-280의 다섯 질문을 각 장면에 적용한다: 근거·권한, 첫 판단, 위험 위계, 색·움직임의 의미, ROSY 성격의 일관성. 개선 전/후를 같은 조건에서 비교한다.
3. 화면별 GO/HOLD/PARKED와 미검증 장면을 `docs/validation/uiux-surfaces-<date>/README.md`에 남긴다. 벤치·DEVICE·FIELD 증거는 각각 실제 출처를 확인한 경우에만 올린다.
4. 해당 모듈 `logs.md`를 append하고 gate가 바뀐 경우에만 `progress.md`를 갱신한다. `python tools/harness/rosy_harness.py generate`와 `lint`를 실행해 색인을 맞춘다.
5. D-258 목표 스택에 남은 B2/B3와 이번 회차에서 발견한 우선 문제를 남긴다. 시각 품질이 좋아져도 장치·현장 게이트는 독립적으로 유지한다.

**제품 전체 완료 기준:** 활성 접점의 대표 장면이 D-280 원칙으로 설명되고, 게임 호스트가 포함되며, 얼굴·장치 신호의 장비 증거와 PARKED 진단 범위가 명시된다. 각 접점의 미완료/미검증 상태가 드러나고, 안전·권한·증거·읽힘 계약 위반이 0건이어야 한다. 어느 한 접점의 LOCAL 성공을 제품 전체 실기 수용으로 합치지 않는다.
