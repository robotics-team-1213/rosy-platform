# 320px 운용 지도와 상태 가독성 (2026-10-08)

## 평가와 수정

기존 지도 상태 시험은 390×844와 1366×768만 캡처했다. 320×568을 같은 실제 FastAPI 자산·합성 CORE 응답으로 추가하자 지도 작업 버튼이 공용 `ui-actions`의 22rem 미만 규칙에 따라 세로로 쌓여 캔버스가 293px에서 시작하는 실패가 드러났다. 두 버튼만 가로 배치하고 44px 누름 높이를 유지해 캔버스 시작을 241px로 올렸다.

첫 수정의 320px 캡처에서 네 줄의 상태 HUD가 지도 위 로봇·경로를 가렸다. 이 폭에서만 HUD를 캔버스 바로 아래로 옮겼다. 정상 캡처에서 로봇 방향과 계획 경로가 가리지 않고 보인다. 390px와 1366px는 기존 지도 위 HUD를 유지한다.

| 폭 | 캔버스 시작·높이 | HUD 시작 | 작업 버튼 높이 | 가로 넘침 | 비상 정지 |
|---|---|---:|---:|---:|---|
| 320×568 | 241px · 256px | 501px | 각 44px | 0 | 보임 |
| 390×844 | 241px · 379.8px | 249px | 각 44px | 0 | 보임 |
| 1366×768 | 201px · 341.3px | 209px | 각 44px | 0 | 보임 |

## LOCAL 증거

원본 캡처와 상태 매트릭스는 X: `projects/rosy-platform/2026-10-08--robot-map-320-4fd1/evidence/final/navigation-stage/`에 있다. 정상·지연·연결 끊김·정보 없음·안전 정지 320px 화면과 기존 두 폭을 육안 확인했다. 합성 상태이며 물리 주행을 뜻하지 않는다.

- `operator-console-navigation-320x568.png` SHA-256 `15E76389439E63C965FF1209F7E20ED161B68B0EA06F0CBBF61CE00DCFF94466`
- `operator-console-navigation-390x844.png` SHA-256 `8D633470DD13425D842ACF53303AA6C4416795BEDECF269A263576200AC56819`
- `operator-console-navigation-1366x768.png` SHA-256 `0D94417212B8A8B7C5B4363A77015C9ACA22414A86B3CFFA6C73DBCBC8A10CE2`

Chromium 지도 상태 시험 **1 passed** (`logs/final-320.txt`), 패키지 검사 **19 passed** (`logs/package-final.txt`), 둘 다 `known_failures.py` **0 NEW**. 브라우저 단언은 세 폭의 작업 버튼 같은 행·44px 높이, 캔버스 첫 위치, 320px HUD와 지도 비겹침, 가로 넘침 0, 비상 정지 가시성을 확인한다. `impeccable detect --json` 변경 파일 결과는 `[]` (`logs/impeccable.json`). 로그는 같은 X: 세션에 있다.

## 판정

이 변경의 320×568·390×844·1366×768 LOCAL 배치 검증은 통과했다. D-153 전체 G2 매트릭스·G3 운영자 평가·현재 설치 이미지·실제 로봇 지도/경로/SLAM readback은 **HOLD**다.
