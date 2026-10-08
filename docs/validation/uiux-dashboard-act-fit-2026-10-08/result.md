# Dashboard 조작 열의 차단 이유 적합성 (2026-10-08)

## 실제 화면에서 찾은 문제

기존 `/dashboard`의 1366×768 운용 화면에서 `NAVIGATION` 상태가 되면 저속 직접 제어 버튼 4개에 각각 `수동 모드에서만`이라는 이유가 나타난다. 버튼 행은 가용 폭 287px에서 356px을 요구했고, 조작 영역은 `clientWidth 319px / scrollWidth 372px`로 오른쪽 53px이 잘렸다. 기존 D-201 적합성 시험은 세로 넘침만 검사해 이 상태를 놓쳤다. D-359는 버튼의 차단 이유를 화면과 접근성 설명에 표시하도록 요구한다.

## 변경

저속 직접 제어 버튼의 행을 칸 폭에 맞게 계산한다. 차단 이유가 있는 비활성 상태에서는 2열로 배치해 한글 이유를 온전히 읽을 수 있게 했다. 조작 가능한 수동 상태의 4열 배치, 지도 폭, 안전 정지 위치와 명령 동작은 유지했다.

## LOCAL 캡처와 회귀

실제 `/dashboard` CSS·JS를 Chromium에서 실행한 합성 상태다. 로봇 또는 설치 이미지의 증거는 아니다.

| 상태 | 뷰포트 | PNG | SHA-256 |
|---|---|---|---|
| 수정 전 | 1366×768 | `X:/DevTemp/projects/rosy-platform/2026-10-08--dashboard-act-fit-6f2b/evidence/before/navigation-teleop-1366x768.png` | `3E24C993853244C676EC92A9F093D144D4FF9FD3F14A2CC4294773B846DF3866` |
| 수정 후 | 1366×768 | `X:/DevTemp/projects/rosy-platform/2026-10-08--dashboard-act-fit-6f2b/evidence/after/navigation-teleop-1366x768.png` | `43CBF979B5FA94B16D4FA126D9FAA61E147A5AE2D91A5A51A36D4E972E2F8559` |
| 수정 전 | 390×844 | `X:/DevTemp/projects/rosy-platform/2026-10-08--dashboard-act-fit-6f2b/evidence/before/navigation-teleop-390x844.png` | `F110B84ECCF5B805719F99086A7F8A86BAE38DE97CA70ED7A8EEE506D1B0908B` |
| 수정 후 | 390×844 | `X:/DevTemp/projects/rosy-platform/2026-10-08--dashboard-act-fit-6f2b/evidence/after/navigation-teleop-390x844.png` | `547F2C640FA9B7C4264BA2F2597034B3DB3C365338E38A09609EC565AA167633` |

새 시험은 `NAVIGATION`의 네 버튼 이유가 모두 존재하고 조작 영역·버튼 행의 가로 넘침이 없는지 390×844와 1366×768에서 확인한다. 1366×768에서는 세로 넘침도 검사한다. 수동·안전 정지·CORE 전용·낮은 데스크톱·패키지 시험까지 **28 passed**, `known_failures.py` **0 NEW** (`X:/DevTemp/projects/rosy-platform/2026-10-08--dashboard-act-fit-6f2b/logs/regression-final.txt`). 수정 전 같은 시험은 1366×768에서 가로 넘침으로 실패했다 (`logs/before-navigation-fit.txt`).

## 수용 범위

이 변경은 `/dashboard` 조작 열 한 상태의 LOCAL 적합성이다. 전체 앱 G2/G3와 설치 이미지·장치·현장의 내비게이션 사용성 수용은 계속 **HOLD**다.
