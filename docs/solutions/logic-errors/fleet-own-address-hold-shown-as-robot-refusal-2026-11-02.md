---
module: fleet
tags: [fleet, enrollment, console, field-diagnosis]
problem_type: bug
---

# Fleet이 스스로 막은 요청을 "로봇이 거절"로 보였다

## 문제

2026-11-02 현장 관제 화면에서 다섯 대가 모두 오프라인이었다. 그중 rosy_40·41 카드는 "로봇이 거절: ADDRESS_UNVERIFIED"였고, 상태 행 `error.reachable`은 `true`였다. 로봇이 켜져 있다가 무언가를 거절한 것처럼 읽혔다. 실제로는 두 대 모두 꺼져 있었다. mDNS 광고가 없었고, 관제 PC에서 고정 주소로 보낸 요청에도 응답이 없었다.

## 원인

- 두 대의 Fleet 등록 자격이 2026-10-16에 만료됐다(`GET /api/fleet/enrollment/robots`의 `state`·`hold`가 `needs_new_code`, `legacy_lifetime: true`). 그 뒤 D-361 고정 주소 검사(`fleet/server/auth/enrollment.py` `_PinnedTransport.admit`)가 정지 요청 말고는 모두 Fleet 안에서 막았다. 로봇에는 아무것도 묻지 않았다.
- `console_view._error_of`가 모든 `RobotApiError`를 `reachable: true`로 바꿨다. 이 검사가 던지는 409 `ADDRESS_UNVERIFIED`도 그 안에 들어갔다. 관제 화면은 `reachable`이 참이면 "로봇이 거절"이라고 썼다.

## 해결

- `ADDRESS_UNVERIFIED`는 `{reachable: null, held: true}`(API v1.348). 로봇 카드는 같은 행의 `held`로 이유를 쓴다. 예: "Fleet이 정지 요청만 보냄 · 등록 자격 만료 · 로봇 화면의 새 코드로 다시 등록".
- 회귀 시험:
  - `operations/fleet/test/test_enrollment_service.py`(오류 모양)
  - `operations/fleet/test/web/offline-why.test.mjs`(카드 문구)

## 다음에 적용할 조건

- 오프라인 로봇을 진단할 때 상태 오류만 보지 말고 `GET /api/fleet/enrollment/robots`의 `state`·`hold`·`expires_at`를 먼저 본다. 쉬는 기간이 2주를 넘으면 예전 수명(legacy) 자격은 만료돼 있다.
- 로봇이 켜졌는지는 관제 PC의 `avahi-browse -arpt | grep pinky`와 고정 주소 직접 요청으로 확인한다. Fleet의 `reachable`만으로 판단하지 않는다.
- 다시 등록하려면 로봇이 켜져 있어야 한다. `ssh rosy-pinky-<id> sudo rosy-login-code --role operator`로 받은 코드를 출력하지 않고 Fleet 등록 API로 넘긴다.
- 로컬 검사가 막은 요청을 원격 응답과 같은 필드로 보고하지 않는다. 오류 출처(Fleet·로봇·연결)를 따로 표시한다.
