# Pilot 주행 HUD 상태 용어 · LOCAL

판정: **부분 확인 / 제품 전체 HOLD**. Pilot 주행 화면의 링크 상태와 CORE 운전 모드를 운용자 용어로 표시한다. 내부 상태값은 `data-state`와 `title`에 남겨 기존 상태별 색상과 진단을 유지한다.

- 재현: 수정 전 Chromium 4개 폭 모두 링크 표시가 `OPEN`이어서 새 브라우저 검사 4건 실패.
- 수정 후: 2000×1200, 1200×2000, 390×844, 320×568에서 `상태 수신`·`수동` 표시, 페이지 오류 0, 가로 넘침 0. 브라우저 검사 **4 passed**, `known_failures.py` **0 NEW**.
- D-153 G1 관련 검사 **90 passed**, `known_failures.py` **0 NEW**.
- 캡처: `X:\DevTemp\pilot-drive-status\after\pilot-drive-status-<폭>x<높이>.png` (LOCAL fixture, 실제 장치 아님).

남은 수용: 재연결·권한 거부 등 전체 G2 상태×폭, 현장 설치본 readback, 사용자 G3 작업 검토. 이 결과로 제품 전체 GO를 선언하지 않는다.
