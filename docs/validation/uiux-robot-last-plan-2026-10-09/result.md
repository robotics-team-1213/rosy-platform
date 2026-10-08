# Robot Console 마지막 계획 경로 표시 — 2026-10-09

- 기준: `uiux/robot-last-plan-display`, 분기 기준 `1fecdce7162d6ac495520dd5f35e06a7176fd7a1`.
- 근거: API reference §5.3의 `/api/v1/navigation/path`는 CORE가 마지막으로 받은 계획의 좌표·지도 ID·좌표계·수신 후 경과 시간만 제공한다. 현재 목표와 같은 경로인지는 확인할 수 없다.
- 변경: 유효한 지도 좌표 계획은 화살표 없는 점선으로 그리고, 상태줄에 수신 후 경과 시간과 `목표 일치 미확인`을 표시한다. 지도 ID·좌표계·위치 추정·안전 정지에 따른 기존 표시 차단은 유지한다. 320px에서는 상태줄이 지도 아래에서 줄바꿈한다.
- LOCAL 화면: 실제 CORE FastAPI의 Console 자산을 Chromium으로 열고 합성 지도·경로·로봇 상태를 주입했다. 1366×768, 390×844, 320×568에서 점선과 근거 문구를 확인했다. 세 폭 모두 가로 넘침·페이지 오류 0, 비상 정지 표시와 지도/조작 순서 유지. 지연·연결 끊김·지도 ID 불일치·좌표계 불일치·안전 정지 상태도 같은 브라우저 회귀에서 확인했다.
- 검증: `test_console_navigation_stage_local_captures` 1 passed, `known_failures.py` 0 NEW; `node --check` 2개, `git diff --check`, Impeccable detector `[]`.
- 원시 증거: `X:/DevTemp/projects/rosy-platform/2026-10-09--last-plan-display/run.txt`와 `captures/navigation-stage/`의 PNG 및 `navigation-stage-matrix.json`.
  - `operator-console-navigation-1366x768.png` SHA-256 `65eab481468d09dcc7c217e1935e480add8931246bfeb3da1abe9e1d5b9724e4`
  - `operator-console-navigation-390x844.png` SHA-256 `1cba255ee3ed4813761dbf60d39c328fc55eaac3a5226cef800f24cd0e238116`
  - `operator-console-navigation-320x568.png` SHA-256 `39036d64bdba4c5711e20b993e5ce1976c9e755222246f52a300029688d02f15`
- 판정: LOCAL 경로 표현의 사실성·반응형 확인. 계획과 현재 목표의 연동, 실제 경로 추종, SLAM 실행·지도 갱신, 설치 이미지, DEVICE/FIELD 및 전체 G2/G3는 HOLD.
