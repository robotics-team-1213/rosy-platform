# UI/UX 표면 — D-245 파일럿 회차 (2026-09-25)

D-245(E-Stop 파일럿)의 G2 셀 1개. 전체 UI/UX 판정이 아니라 파일럿 한 건의
착지 증거다. D-153의 Część 표면 판정(GO/HOLD)은 열지 않는다.

- 회차 조건: Windows HOST, 작업 트리 uncommitted. 증거 상한 LOCAL.
- 계측 수단: 저장소 브라우저 하네스 패턴(임시 캡처 스크립트, `test_fleet_console_browser.py`의
  fixture와 같은 서빙·라우팅) + Playwright Chromium 1920×1080(D-201 Fleet 선언 뷰포트).

## Result (LOCAL 한정)

| 셀 | 캡처 | 판정 근거 |
|---|---|---|
| Fleet 전체 정지 범위 병기 | `captures/fleet-estop-note-1920x1080.png` | 버튼 라벨 `전체 정지\n등록된 모든 로봇` 단언 통과, 바운딩 박스 뷰포트 내(y=14.5, h=58, ≤1080), 페이지 오류 0. 확인 문장(`등록된 모든 로봇을 정지시킵니다. 계속할까요?`)과 같은 말을 버튼으로 올림 — PINNED 불변 |
| Fleet 잠금 pill (D-248) | `captures/fleet-locked-pill-1920x1080.png` | 오토큰 입력 후 pill `토큰 필요`(crit) 유지 단언 통과, 2.5s 추가 대기 후 추가 `/api` 호출 0 (프로브: 수정 5회 vs 변이 9회·증가 중). `refreshState` catch가 잠금 pill을 `Fleet 서버 없음`으로 덮던 결함도 함께 수정 — 401의 이유가 남는다 |

## 한계

- G1(기계 게이트)은 별도 실행분(`test_web_dialog_contract.py` 등)으로 커버하고 이 폴더는 G2 셀만 둔다.
- 사람 눈의 G3 최종 판정은 BENCH 회차의 몫이다(D-153).
