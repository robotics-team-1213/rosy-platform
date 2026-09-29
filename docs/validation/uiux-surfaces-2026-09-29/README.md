# 역할 운용 웹 P1 크래프트 회차 — 2026-09-29

`docs/plans/2026-09-29-uiux-craft-improvement-plan.md` P1(역할 운용 웹)의 실행 기록이다.
브랜치 `feat/uiux-p1-roles-web`, 기준선 27e6da33.

## 판정

**표면 UI/UX 판정은 HOLD 유지다.** D-153 GO는 G1(기계)+G2(선언 셀)+G3(사람 8항) 셋인데
이 회차는 G1·G2의 LOCAL 분량만 채웠고 G3 사람 평가는 수행하지 않았다. DEVICE/FIELD와
물리 readback은 별도다.

## 변경과 근거

| 변경 | 이유 | 파일 |
|---|---|---|
| 공유 계약 위반 3건 복원 — helper 버튼 kind 선언, Fleet 토글을 `kind=segment`로(표면 재도색 삭제), SVG 포커스 링을 공용 치수로 | main에 커밋된 G1 위반. G1 빨간 표면은 전 표면 HOLD다(D-153) | `src/hmi/dashboard/panels/host/system.js`, `src/site/fleet/fleet/server/web/{index.html,styles.css}` |
| 패널 모듈 import 중 `ui-empty` 로딩 문구 | 빈 테두리 카드는 Law 0 위반의 로딩 번역. 느린 네트워크에서 "빈 상자=정상"으로 읽히는 것을 막는다 | `src/hmi/dashboard/shell/mount.js` |
| `/setup`·`/device` 데스크톱 main 슬롯을 2열 grid에서 multicol로 | row-pairing grid은 카드 높이가 어긋나면 좌열에 구멍을 남긴다(8항 위계). multicol+`break-inside: avoid`는 패널 수와 무관하게 채운다(D-265) | `src/hmi/dashboard/shell/shell.css` |
| action-group 탭 리스트를 균등 전폭 grid에서 콘텐츠 폭 flex로 | 단일 그룹 fixture에서 전폭 스트레치 탭이 의미 불명의 큰 버튼으로 읽혔다 | `src/hmi/dashboard/shell/shell.css` |
| 접근 토큰 행 flex 배치 | 58px 불가역 삭제 버튼이 행 높이를 넘어 텍스트·인접 행을 침범(8항 불가역) | `src/hmi/dashboard/panels/surface-panels.css` |
| G2 harness 조립 완료 대기 | 첫 패널 마운트 500ms 뒤 캡처는 조립 중 DOM을 찍어 빈 카드·로딩 문구를 증거 셀에 남겼다 | `src/hmi/dashboard/test/test_role_g2_browser.py` |

## 검증 (LOCAL, Windows Chromium)

- 공유 계약: `src/hmi/web/test` 22 passed.
- Fleet 회귀(계약 복원 확인): `test/test_fleet_console_browser.py src/site/fleet/test` 576 passed / 5 skipped.
- 대시보드 전체: `src/hmi/dashboard/test` 43 passed(역할 G2 재생성 포함).
- D-283 콘솔·surface 레이아웃: `test_d283_console_browser.py` `test_action_groups_browser.py` `test_surface_layout_browser.py` 23 passed.
- 역할 메뉴·표면 상태: `test/test_role_menu_panels_browser.py test/test_role_surface_states_browser.py` 29 passed.
- Impeccable 기계 검사: `impeccable detect --json` on `shell.css` `mount.js` → `[]`.
- 역할 G2 매트릭스: 60셀 재생성, overflow 0, pageerror 0. 조립 완료 대기로 캡처가 안정 DOM을
  담는지 전체 화면 육안 확인 — 로딩 문구 잔존·빈 컨테이너·좌열 구멍·토큰 버튼 침범 해소.
- 캡처는 `X:\DevTemp\rosy-uiux-d306-roles-g2\` 일회성이다(D-153.4 보존형 G2 규칙은 후속 회차 과제).

## 관찰, 미변경

- 모바일 390px `/console`에서 조작 패널이 지도·웨이포인트 뒤로 밀린다. 슬롯 순서 변경은
  9-27 회차가 선언한 배치 계약을 다루는 별도 결정이라 이번 범위에 넣지 않았다.
- 관찰된 나머지 표면(Fleet P2, 게임 P3, 얼굴 P4, 문서 P5)은 계획 순서를 따른다.

## P2 — Fleet (같은 날짜, `feat/uiux-p2-fleet`)

표면 질문 "어느 로봇에 주의가 필요한가"에 대한 critique·distill·harden·adapt 독회를
8상태×3뷰포트 24셀(1920×1080·390×844·320×844)로 수행했다.

**결과:**

- 계약 준수 확인 — 예외 우선 로스터(기본 목록은 개입 대상만, 정상은 "전체 로봇 보기" 토글 뒤),
  정상 로봇 중립색, 지연 나이 표시(`지연 · 2.1초`), E-STOP 목표 비활성과 해제 안내, 빈 목록 안내,
  320px에서 전체 정지가 첫 행. 신규 가로 넘침·페이지 오류 0.
- **수정 1건:** E-STOP 로봇의 SAFETY 값이 평문 strong으로 렌더되어 정지 사실이 배터리 같은
  측정값과 같은 무게로 읽혔다(8항 위계·D-202). 공용 `tag crit` 채움으로 렌더하도록 바꾸고
  계약 시험을 요소 타입 대신 값으로 단정하게 정렬했다. 수정 후 estop 셀 재촬영으로 확인.
- **기각:** 카메라 빈 상태의 16:9 예약 영역 축소 — 영상 도착 시 레이아웃이 밀리는 것이
  예약하지 않는 것보다 덜 차분하다(D-220 정신). 빈 상태 문구는 현재 계약대로 정직하다.
- 캡처 스크립트 특성상 discovery 응답을 fixture에 넣지 않은 첫 시도는 발견 패널에
  "확인할 수 없습니다"를 만들었다 — 스크립트 결함이지 제품 결함이 아니어서 fixture를
  보완해 재촬영했다.

**게이트:** `test_fleet_console_browser.py` + `test_web_dialog_contract.py` 34 passed,
`impeccable detect` []. **표면 판정은 HOLD 유지** — 실물 페어링·E-STOP/목표 readback,
사람 G3가 남아 있다. 캡처는 `X:\DevTemp\rosy-uiux-p2-fleet` 일회성이다.

## P3 — 게임 보드 (같은 날짜, `feat/uiux-p3-games`)

표면 질문 "경기장·공·로봇·골이 보이는가"를 초기·play·HOLD·지연·stale × 1280/390/600
7셀로 독회했다.

**결과:**

- 계약 준수 확인 — 필드가 화면의 주 면(720px), 공만 따뜻한 초점색, 팀·골은 냉색/중립,
  정지 행 하단 고정, 초기 상태는 점수를 `—`로 두고 "경기 데이터 대기 중", 지연·stale은
  "마지막 수신 단계" 단계 문구·필드 증거 칩·"현재 위치 아님"으로 마지막 수신값과 구분.
  신규 가로 넘침·페이지 오류 0.
- **수정 1건:** HOLD 경보("공을 잃음 · HOLD")가 `--lost` 빨간 글자였다 — D-202의
  "status-crit는 글자색으로 쓰지 않는다" 위반. 공용 `--status-crit` 채움 칩으로 바꾸고
  `.lost[hidden]` 가드를 추가했다(명시적 display가 hidden을 덮는 정전 패턴). 전폭 밴드로
  그렸다가 경보 예산에 과해 내용에 맞는 칩으로 좌혔다 — 회차 안에서 두 번의 배치 확인.
- **첫 캡처 시도의 fixture 결함:** 보드 클록을 고정 람다로 둔 탓에 지연·stale 셀이 fresh와
  동일하게 찍혔다. 가변 클록으로 publish 후 시간을 진행시켜 재촬영했다 — 제품 결함이
  아니라 캡처 스크립트 결함이었다.
- **기각:** 필드 관측 패널의 빈 세로 공간 — 패널이 경기장 높이에 맞춰 늘어나는 것으로,
  내용을 늘리는 것보다 예약이 경기 가시성을 해치지 않는다.

**게이트:** `src/site/games/test test/test_games_board_browser.py` 117 passed,
`impeccable detect` []. **표면 판정은 HOLD 유지** — 실물 카메라·양측 로봇 정지
readback, 사람 G3가 남아 있다. 캡처는 `X:\DevTemp\rosy-uiux-p3-games` 일회성이다.

## P4 — 로봇 얼굴 LCD (같은 날짜, `feat/uiux-p4-lcd`, LOCAL 범위)

Pi 벤치 없이 PIL 렌더 11장(웨이크 7 + 부팅 4)을 0.5초 판독 기준으로 독회했다.

**결과:**

- 계약 준수 확인 — 정상은 무채색 잉크, 저전압은 경고 숫자, 위험(15%·E-STOP·FAILED)은
  crit 채움 칩, 결측은 `--`와 빈 게이지, AP 카드 QR 정숙 영역, 긴 로봇 ID는 축소·말줄임.
- **수정 1건:** ASSIST REQ(사람 개입 요청)가 HEALTH 행의 평문이어서 OK와 같은 무게로
  읽혔다(8항 위계). warn 채움 칩(`_draw_caution`, ground 잉크)을 추가해 crit 칩과 형태가
  같고 색만 다른 어휘로 정리했다.
- **벤치 미착수:** Pi 설치 폰트, 1.5m·각도·조도 판독, 실물 만료 복귀는 미측정 —
  표면 판정은 BENCH/DEVICE **HOLD**다. 렌더는 `X:\DevTemp\rosy-uiux-p4-lcd` 일회성이다.

**게이트:** face 시험 162 passed / 4 skipped.

## P5 — 문서·제품 소개 (같은 날짜)

README의 능력 주장 문장을 동사 스캔(지원·완료·동작·검증·가능)으로 전수 대조했다.
교정 대상 0건 — 강한 주장은 전부 부정문·증거·게이트 경계와 함께 쓰여 있다(예:
"OMX 장치의 운영 writer 수용 완료를 뜻하지 않는다"). Phase 로드맵은 계획으로 명시적이다.
STATUS 대조도 통과 — README는 게이트 스냅샷을 대신하지 않는다.

## P6 — 총평

D-280 후속 크래프트 시퀀스의 LOCAL 분량이 닫혔다: P1 역할 웹(브라우저 회귀·G2 60셀),
P2 Fleet(24셀·E-STOP crit), P3 게임(7셀·HOLD crit 칩), P4 얼굴(11장·ASSIST REQ warn 칩),
P5 문서(교정 0건). 회차마다 유한 검증(배치 검증 → 수정 1배치 → 확인 1회)을 지켰다.

**표면 판정은 전부 HOLD로 유지한다.** 남은 조건은 표면마다 두 가지다 — (a) D-153 G3
사람 평가(운용자·설치자 등 청중 2인의 8항 시트), (b) 실물 증거(장치 readback, 물리
E-stop, LCD 실물 사진, FIELD). LOCAL 성공은 어느 표면의 DEVICE/FIELD 수용으로도
승격되지 않는다. G2 보존형 증거 저장소 규칙과 ADR 후보 A-1(표정 어휘)·A-2(온기 문구)는
다음 회차 과제로 남는다.

## 남은 수용

- G3 사람 평가(운용자·설치자 8항 시트) — 표면 GO의 필수 조건.
- 실물 CORE/Host Agent readback, 물리 E-stop, DEVICE/FIELD 증거.
- `share/dashboard` 이미지 설치 증거(ARTIFACT)는 여전히 HOLD.
