# D-535 Fleet 연결 사유의 독립 안전 리뷰 — 2026-10-09

**판정:** `cd7464f3241145b28c1d2fa21aa734e7ccb6940f`의 변경을 승인한다. 작성 세션과 별도의 Codex 세션에서 diff와 호출자를 검토했다. 커밋에 `Safety-Review:` trailer가 없어 CI가 중단됐으므로, 이 커밋 하나만 `tools/harness/safety_review.py`의 사후 검토 목록에 넣는다.

- `console.py`의 안전 태그 경로 변경은 로봇 읽기 실패 시 `link_reason(exc, scheme)` 결과를 `row["link_reason"]`에 붙이는 세 줄이다. `console_view.py`의 함수는 예외를 D-535의 닫힌 연결 사유 코드와 설명·복구 행동으로 바꾼다. `roster.js`는 그 값을 명단 태그의 제목으로 보여 준다.
- `rg -n 'link_reason' operations/fleet/fleet -g '*.py' -g '*.js'`로 운영 호출자를 확인했다. 작성·표시 외에 이 필드를 읽는 명령, E-Stop, 취소, 이동 허가 경로는 없다. 기존 D-499 `link` 판정도 유지된다.
- 모델 PC에서 소스 `d1ce9d0ce1f20f8fa7d3bbff6eb234e480dbe508`의 `operations/fleet/test/test_link_reason.py`, `test_dispatch_stop_latch.py`, `test_cancel_all.py`를 실행했다. **48 passed**, exit 0. 로그는 비공개 `X:/DevTemp/safety-review-cd746/run-1.txt`에 보관했다. 이는 후속 통합 소스의 호스트 시험이다. 원 커밋 단독 시험이나 장치 시험으로 확대 해석하지 않는다.

검토 범위는 연결 오류 **표시**와 기존 정지·취소 경로의 호스트 회귀다. 현장 로봇 연결, 안전 회로, LCD 픽셀, 실제 주행은 이 리뷰로 승인되지 않는다.
