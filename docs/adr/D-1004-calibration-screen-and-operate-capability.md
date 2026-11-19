## D-1004 Calibration 화면은 Account 로그인으로 열고, 실측 요청의 답은 calibration.operate가 한다

**Status:** Accepted (2026-11-09, 사용자 결정; 구현·시험의 수용이며 관제 PC 배포·HTTPS 프록시·실계정 수용은 별도)

**관련:** D-951 덧붙임 2026-11-09 · D-757 · D-777 · D-807 · D-990

## Context

실측 요청(`cell_requests.py`)의 답은 지금 명령줄에서 `--by <이름>`을 손으로 적어 남긴다. 사용자는 관제 PC에서 엔진·위 카메라 옆에 도는 화면을 정했고, 모든 ROSY 앱은 Account를 공통 코어로 쓴다.

## Decision

1. **화면:** `applications/calibration/calibration_web.py`. 관제 PC에서 loopback(127.0.0.1)에만 열고 HTTPS 역프록시 뒤에서 Account receiver로 로그인한다(Games 보드와 같은 방식). 저장소 `ROSY_CELL_REQUESTS`는 엔진 `cell_requests`가 유일한 작성자이고, 화면은 `cell_requests.answer`만 부른다.
2. **권한:** site 자원에 `calibration.operate`를 더한다. 요청 답은 이 권한이 있는 세션만 한다. 목록·상세·그림을 보는 것은 그 site의 유효한 로그인 세션이면 된다(권한 불필요). Account 설정이 없으면 화면은 읽기 전용이다(답 불가, fail closed).
3. **누가:** 답의 `by`는 입력칸이 아니라 세션이다. Account 표시 이름과 account_id를 쓴다. 요청 본문의 이름은 무시한다.
4. **쓰기 조건:** 등록된 HTTPS origin과 같은 출처, 유효한 세션, `calibration.operate`. 이미 답이 있으면 409, 값이 잘못되면 422다.
5. **배포 순서(D-990 경고):** 모르는 capability가 든 토큰은 옛 receiver가 거절한다. 모든 receiver(Fleet·Games·카메라 앱 등)를 먼저 배포하고 그 뒤에 `calibration.operate`를 부여한다. 팀 기본 묶음에는 이 권한을 넣지 않는다(관리자가 명시 부여).
6. **값을 바꾸지 않는다:** D-951 2항 그대로 답은 후보 판정이다. 화면이 셀 값을 쓰지 않는다.

## Consequences

- 허용 capability 목록(`account_access.py`, 계정 화면, Android 사본, 프로토콜 표)이 한 개 늘고 이를 고정한 시험이 함께 바뀐다.
- 실계정·HTTPS 프록시·receiver 배포 전에는 읽기 전용만 쓸 수 있다. 그 전 답은 `cell_requests.py answer`로 남긴다.
