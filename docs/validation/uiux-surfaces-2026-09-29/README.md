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

## 남은 수용

- G3 사람 평가(운용자·설치자 8항 시트) — 표면 GO의 필수 조건.
- 실물 CORE/Host Agent readback, 물리 E-stop, DEVICE/FIELD 증거.
- `share/dashboard` 이미지 설치 증거(ARTIFACT)는 여전히 HOLD.
