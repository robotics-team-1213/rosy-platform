# UI/UX 평가 회차 — G2 행렬 (2026-09-26, D-255 B1)

D-255의 blocker B1을 치는 캡처다. 전부 LOCAL(Windows Chromium)이며 페이지
오류 0 셀만 둔다. 판정은 D-255의 G3 표를 잇는다.

## 조건

- 대시보드: 시험 하네스(`test_dashboard_browser.py`의 `_launch_page` +
  `CONSOLE_STATE_INIT`)를 그대로 재사용. `X:/DevTemp/opencode/round_console.py`
- Fleet: 시험 fixture 패턴(스냅샷·그리드·대형 상태 주입).
  `X:/DevTemp/opencode/round_fleet.py`
- 게임: 실제 `PreviewServer` + 게시 페이로드. `X:/DevTemp/opencode/round_games.py`

## 셀 (15)

| # | 파일 | 표면·뷰포트·상태 |
|---|---|---|
| 1 | console-operate-fresh-1366x768.png | 운용 · 1366×768 · fresh |
| 2 | console-operate-delayed-1366x768.png | 운용 · 1366×768 · delayed |
| 3 | console-operate-disconnected-1366x768.png | 운용 · 1366×768 · disconnected |
| 4 | console-operate-safestop-1366x768.png | 운용 · 1366×768 · SAFE_STOP(estop triage) |
| 5 | console-operate-unauthorized-1366x768.png | 운용 · 1366×768 · 401 토큰 |
| 6 | console-operate-firstboot-1366x768.png | 운용 · 1366×768 · 최초 기동(응답 없음) |
| 7 | console-operate-visionoff-1366x768.png | 운용 · 1366×768 · 카메라 unavailable |
| 8 | console-operate-fresh-390x844.png | 운용 · 390×844 전화 · fresh |
| 9 | console-inspect-runtime-1366x768.png | 점검 · 1366×768 · ROS 정상 |
| 10 | fleet-normal-1920x1080.png | Fleet · 1920×1080 · 2대 정상 |
| 11 | fleet-empty-1920x1080.png | Fleet · 1920×1080 · 빈 목록(0/0) |
| 12 | games-play-1280x800.png | 게임 · 1280×800 · play |
| 13 | games-lost-hold-1280x800.png | 게임 · 1280×800 · 유실 HOLD |
| 14 | games-initial-1280x800.png | 게임 · 1280×800 · 최초 기동 |
| 15 | console-map-crosshair-1366x768.png | 운용 지도 · 1366×768 · 키보드 십자선 (D-259) |

## 읽기

- 4(safestop): triage 적색 띠 + SAFE_STOP 모드가 선다. 히어로 SAFETY CIRCUIT
  표기와 triage가 어긋나 보이면 시험 fixture의 mock 불일치다(서버 계약이
  아니다) — triage가 정답이다.
- 5(unauthorized): 로그아웃 상태에서 지도가 그려져 보이지만 하네스 인공물이다.
  제품 `/api/v1/map`·`/map/costmap`은 viewer 이상을 요구한다(`v1/map.py:17,26`)
  — 실서버에서는 빈 지도가 뜬다. 텔레메트리·기능 가용성의 빈 상태는 정상이다.
- Fleet normal 셀 재측정: 문서 넘침 0, 신호 힌트 하단 839 < 1080 — D-201 적합.
  접힘 아래로 보인 것은 패널 끝과 하단 고지문이다.
- 11(empty): 큐 패널 없음·0/0 연결. "이상 없음"을 칠하지 않는다.
- 13(lost-hold): 이유 문장 + HOLD. 색이 아니라 글로 말한다.

## 한계

- 불가역 확인 대화상자 열림 상태는 캡처하지 않았다(하네스가 대화를 자동
  수락한다). 거부 경로는 시험(`decline_blocks`)이 커버한다.
- BENCH/DEVICE 증거 없음. 진단 PARKED라 범위 밖이다.
