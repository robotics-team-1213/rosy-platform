# Pilot 연결 로비 전화 폭 LOCAL 확인

2026-10-07 · `uiux/pilot-edge-width` · D-153 G2 부분 근거

320×568과 390×844의 로봇 미발견·목록 조회 실패 화면을 현재 Pilot PWA와 가짜 CORE 서버로 렌더했다. 로비의 `다시 찾기`와 로그인 폼의 `연결`을 코드 입력 칸과 같은 가용 폭으로 맞췄다. 네 요소의 측정 폭 차이는 각 상태·폭에서 1px 이하다. 가로 넘침과 페이지 오류는 0이며, 비상 정지·재검색·로그인 입력이 보인다. 태블릿에는 기존 배치를 유지한다.

원본 PNG 4장은 `X:/DevTemp/projects/rosy-platform/2026-10-07--pilot-edge-width/evidence/pilot-lobby-{empty,failed}-{320x568,390x844}.png`에 있다. 실행 로그는 같은 X: 경로의 `logs/`에 있다.

- 전화 빈 목록·실패: `focused.txt` **2 passed**, `known_failures.py` **0 NEW**
- 로비 관련·태블릿 게이트: `lobby-tablet.txt` **7 passed**, **0 NEW**
- D-153 G1 관련 계약: `g1.txt` **90 passed**, **0 NEW**

합성 LOCAL 화면의 폭 근거다. Pilot의 선언 G2 상태 전체, 실제 태블릿·로봇 readback, 운전자 G3 독회와 제품 전체 수용은 **HOLD**다.
