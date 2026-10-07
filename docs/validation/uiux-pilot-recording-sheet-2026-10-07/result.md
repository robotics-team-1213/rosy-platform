# Pilot 녹화본 시트의 좁은 폭 — LOCAL

**판정: Pilot G2 부분 근거, 제품 전체 HOLD.** `uiux/pilot-recording-320` 브랜치의 시작 커밋 `58a9d0467`에서 로컬 가짜 CORE 응답과 Chromium으로 확인했다. 실제 로봇 녹화 파일·다운로드·정지 상태의 장치 근거는 아니다.

기존 시트는 카메라 stage 안에 붙어 있었다. 390×844와 320×568에서 stage의 `overflow: hidden` 및 조작부 때문에 시트 하단이 가려졌다. 시트를 주행 화면 root에 붙여 HUD 아래 위치와 화면 안의 비상 정지를 유지하면서 조작부 위에 그렸다. 같은 행의 「다시 불러오기」·「닫기」를 같은 폭으로 맞췄고, 320px에서는 두 행동을 전폭으로 쌓았다. 이 폭에서는 중복 설명을 접어 녹화본 행·차단 이유·두 행동을 첫 화면에 함께 보인다.

| 폭 | 녹화 중 차단·파일 행 | 시트 하단 가시성 | 두 행동 폭 | 받기·취소·초점 흐름 |
|---|---|---|---|---|
| 2000×1200 | 확인 | 확인 | 동일 | 확인 |
| 1200×2000 | 확인 | 확인 | 동일 | 확인 |
| 390×844 | 확인 | 확인 | 동일 | 확인 |
| 320×568 | 확인 | 확인 | 동일, 한 열 | 확인 |

수정 전 하단 가시성 검사는 **2 failed / 2 passed** (`X:/DevTemp/pilot-recording-320/red-bottom.txt`). 320px에서 닫기 첫 화면 검사는 수정 전 **1 failed** (`red-close.txt`). 수정 후 관련 브라우저 **7 passed** (`related.txt`), D-153 G1 **90 passed** (`g1.txt`), 각각 `known_failures.py` **0 NEW**. 원본 캡처 네 장은 `X:/DevTemp/pilot-recording-320/shots/pilot-recording-sheet-{2000x1200,1200x2000,390x844,320x568}.png`; 320px PNG SHA256 `69be157d0731d7e4d93fdd87f4ca6345f2de4532b47d86059cf686c18fba34ff`, 관련 시험 로그 SHA256 `37b177f5ca24c7cbdfcb6468bfb613d7a4d53516caaa5b5967dda90a23104d7d`.

다른 Pilot 선언 G2 셀, 실제 Lenovo 태블릿·로봇 readback과 요청자의 G3 여덟 항목은 남아 있다.
