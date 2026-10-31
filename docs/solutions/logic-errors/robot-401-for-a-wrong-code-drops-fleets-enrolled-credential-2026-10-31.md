---
module: fleet
tags: [fleet, core, enrollment, http-status, auth, estop]
problem_type: bug
---

# 로봇이 틀린 코드에 401을 주면 Fleet은 자기 등록 자격이 죽은 줄 안다

## 문제

2026-10-31 v1.337 정지 화면 해제 코드(`POST /api/v1/safety/release-code`)의 첫 구현은 틀린 코드에 401 `UNAUTHORIZED`를 냈다. 시험은 모두 통과했다. 독립 검토가 Fleet 쪽 결과를 짚었다. 팀원이 코드를 한 번 잘못 치면 Fleet이 그 로봇 등록을 `needs_new_code`로 바꾸고 폴링을 멈춘다. 그 뒤로는 화면 코드로 다시 등록해야 했다.

## 원인

Fleet의 등록 로봇 연결(`fleet/server/auth/enrollment.py` `_PinnedTransport.handle_async_request`)은 경로와 본문을 보지 않는다. **어떤 401이든** `on_unauthorized`로 넘기고, 그러면 행이 `needs_new_code`로 바뀌고 로봇이 hold된다(D-361 2). 401은 "Fleet의 bearer가 죽었다"는 한 뜻으로만 읽힌다. 호출자 인증은 성공했는데 요청 본문의 비밀(코드)이 틀린 경우에도 401을 쓰면 이 둘이 섞인다.

Fleet 시험의 가짜 CORE는 응답 상태만 돌려줘서 행 상태 변화를 보지 않았다. CORE 시험은 CORE만 봤다. 그래서 경계를 넘는 이 결과는 어느 시험에도 걸리지 않았다.

## 해결

- CORE는 틀린 해제 코드에 403 `CODE_REJECTED`를 준다. 호출자 토큰은 유효하다. 401은 토큰이 죽었을 때만 쓴다.
- Fleet `enrollment_release.py`는 `CODE_REJECTED`를 `code_rejected`로, 진짜 401(`UNAUTHORIZED`)을 `robot_auth`(다시 등록)로 따로 알린다.
- 회귀 시험: `operations/fleet/test/test_enrollment_estop_release.py::test_a_mistyped_code_keeps_the_robot_enrolled`가 틀린 코드 뒤에도 행이 `active`인지 본다. `middleware/core/gateway/test/test_safety_release_code.py`는 403과 `CODE_REJECTED`를 고정한다.

## 다음에 적용할 조건

Fleet이 등록된 operator 연결로 부르는 CORE 엔드포인트를 새로 만들거나, 본문에 코드·PIN·비밀을 받는 엔드포인트를 만들 때 지킨다.

- 업무상 거절에는 401을 쓰지 않는다. 403·409·422처럼 구분되는 코드를 쓴다.
- Fleet 시험에서는 거절 응답 뒤에 등록 행의 `state`도 확인한다. `/auth/pair`는 예외다. 이 경로는 Fleet이 등록 연결 밖의 새 `httpx` 클라이언트로 부른다.
