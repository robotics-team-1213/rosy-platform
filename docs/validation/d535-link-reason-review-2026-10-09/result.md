# D-535 Fleet 연결 이유 독립 안전 검토 · 2026-10-09

검토자: Codex `/root` (원 변경 작성 세션과 분리). 대상: `cd7464f32`의 Fleet `console.py` 변경과 후속 예외 분류 보강. D-430 §5의 안전 태그 경로 검토다.

## 변경 경계

- 안전 태그가 붙은 `console.py` 변경은 `link_reason` import와 `snapshot()` 응답 행에 `link_reason` 표시 필드를 추가하는 세 줄이다. 기존 `classify_link`와 `_remember`, `_run_traffic`, `_manage_swarm_speed` 호출 순서, goal·cancel·E-Stop·래치·admission 코드는 바뀌지 않았다.
- `console_view.py`의 분류기는 HTTP/전송 예외를 닫힌 연결 이유 코드·사람 안내로 바꾼다. 이 필드는 로봇 명령이나 교통 판단의 입력이 아니다. 브라우저는 실패 이유와 다음 행동을 보여 준다.
- 검토 중 인증서 검증 오류 객체에 `verify_code`가 없으면 분류가 `AttributeError`로 끝나 `snapshot()`이 `_remember` 전에 중단되는 빈틈을 재현했다. `getattr(..., None)`로 일반 CA 오류에 안전하게 귀착시키고 같은 입력의 회귀 시험을 추가했다. 이 보강이 함께 착지해야 원 커밋을 예외 목록에서 수용한다.

## 검증과 한계

- 보강 전 `test_transport_failures_get_reasons`는 위 `AttributeError`로 실패했다. 보강 후 `test_link_reason.py`, `test_server_console.py`, `test_cancel_all.py`, `test_dispatch_stop_latch.py`: 60 passed, `known_failures.py` 0 NEW.
- 소스 검토와 호스트 시험은 응답 필드와 정지·취소 경계만 다룬다. 장치 네트워크, 실제 이동, 물리 정지, 운영자 수용은 검증하지 않았다.
- 원 커밋의 빠진 trailer는 이 검토와 회귀 보강을 근거로 `safety_review.py`의 해당 커밋 하나만 예외 처리한다. 새 safety 변경의 trailer 의무는 유지한다.
