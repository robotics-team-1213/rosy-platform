# Robot 운용 열 너비 LOCAL 확인

2026-10-07 · `docs/robot-width-round` · D-153 G2 부분 근거

현재 `/console`·`/setup`·`/device`를 dark/light × 1280×800·390×844·320×568의 18셀로 렌더했다. `/console` wide 고정 프레임은 감지 열만 세로 스크롤바 자리를 예약해서, 같은 행의 `ui-section` 폭이 수정 전 **395.66/395.66/410.67/410.66px**였다. 지도·조작 열에도 같은 스크롤바 자리를 예약한 뒤 **395.66/395.66/395.67/395.66px**로 맞았다. 390px 네 패널은 모두 366px, 320px은 모두 296px이다. 두 테마에서 동일하고 문서 가로 넘침·페이지 오류·패널 렌더 실패는 0이다. 기존 1366×768 콘솔 셸 시험에도 실제 패널 너비 ≤1px 검사를 추가했다.

원본 PNG·계측 JSON은 `X:/DevTemp/projects/rosy-platform/2026-10-07--robot-surface-current/evidence-equal/`, 수정 전 원본은 같은 경로의 `evidence-measured/`에 있다. 실행 기록은 같은 X: 폴더의 `capture-equal.txt`, `robot-layout.txt`, `g1.txt`이다.

- 역할 셸 브라우저 **9 passed**, G1 관련 계약 **90 passed**, 각 `known_failures.py` **0 NEW**.
- 이 합성 CORE에는 지도가 없어서 `/api/v1/map`·costmap이 404이고, Host Agent가 없어서 `/api/v1/host/ssh/password`가 503이다. 캡처 명령은 이를 `PROBLEM`으로 보고하며 **정상 지도·호스트 상태의 G2 통과 근거가 아니다**. 화면은 해당 결측 안내를 렌더했다.

현재 후보의 선언 상태·폭 전체 G2, 실제 로봇·호스트 readback 및 운영자 G3는 **HOLD**다.
