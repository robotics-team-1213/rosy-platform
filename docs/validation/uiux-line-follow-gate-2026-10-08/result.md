# 차선 추종 화면의 구동 조건 일치 (2026-10-08)

## 발견과 조치

Robot Console `/console`의 차선 추종 화면은 구동 준비(`teleop: true`, `runtime.drive: ready`)가 확인되면 Nav2 없이 시작 버튼을 열었다. 기존 `/dashboard` 호환 화면은 `navigation.goal_navigation`을 요구해 같은 로봇의 IR·카메라 추종 버튼을 잠갔다. D-344 보강 7항에 따르면 차선 추종의 조건은 MOVE/구동 준비이고 Nav2 목표 주행과 별개다.

호환 화면의 버튼과 확인창 재검사를 같은 구동·운용자 권한·비상 정지 조건으로 맞췄다. 시작 요청 처리 중에는 기존처럼 버튼을 잠그고 OFF는 운용자에게 계속 열어 둔다. 실제 차선 증거와 최종 시작 수락은 CORE가 검사한다. 이번 변경으로 Nav2 지도 목표나 실제 주행 권한을 추가하지 않았다.

## LOCAL 전후 화면

개발 브라우저의 같은 합성 로봇(`teleop=true`, `runtime.drive=ready`, `goal_navigation=false`, `estop=false`)을 390×844와 1366×768에서 캡처했다. 변경 전에는 `IR 센서`·`카메라`가 비활성이며 이유가 `내비게이션을 쓸 수 없음`이었다. 변경 후에는 두 추종 선택이 열리고 지도 목표 조작은 기존 조건을 따른다. 화면 원본은 `X:/DevTemp/projects/rosy-platform/2026-10-08--line-follow-gate-7a2c/evidence/{before,after}/lane-follow-no-nav2-{390x844,1366x768}.png`에 있다. 합성 API 응답의 LOCAL 증거이며 실기 추종을 뜻하지 않는다.

| 화면 | 변경 전 SHA-256 | 변경 후 SHA-256 |
|---|---|---|
| 390×844 (SHA-256) | `1E065A61E3BC17BC68E1D6E67B602805A6986F376B3F89A34DA3BF290F5532C5` | `F9476940B814A79E56A31CA71D074B061CCAEFF56C1866C86DB8A5870700CAAF` |
| 1366×768 (SHA-256) | `02170BF5EE4145AC84E25F3DC4DCD98D446DA87DA7442F98FFD107547279E652` | `F21C5FF534DCAA3E21BA6AB24711451A414C5CC510173C79991710AD6B982724` |

## 회귀와 수용 경계

- 새 브라우저 시험: 변경 전 2 failed, 변경 후 두 폭 2 passed. 확인창을 연 뒤 구동 준비가 사라지면 차선 추종 요청 0건, 준비가 돌아오면 IR_LINE 요청 1건을 확인했다 (`logs/before.txt`, `logs/after-final.txt`).
- 기존 확인창·구동 불가 회귀를 포함한 관련 묶음 5 passed, `known_failures.py` 0 NEW (`logs/regression-final.txt`). 변경된 JS 둘의 `node --check` 통과.
- 추가로 실행한 옛 인증·지도 확인창 시험은 브랜치와 변경 전 `main` 모두 같은 위치에서 실패했다 (`logs/regression.txt`, `logs/main-old-auth.txt`). 현재 목표 버튼의 지도 준비 조건과 시험 fixture를 별도로 대조해야 한다. 이 묶음을 PASS로 세지 않는다.

설치본, 실제 로봇의 구동 준비·비상 정지·차선 증거 readback, 실물 차선 추종 및 운영자 G3는 확인하지 않았다. D-153 전체 G2/G3와 DEVICE/FIELD는 **HOLD**다.
