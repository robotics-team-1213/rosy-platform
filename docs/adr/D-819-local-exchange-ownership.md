## D-819 local action과 stop 전송의 공통 구현

**Status:** Proposed

### Context

Fleet `server/local_action_transport.py`와 `local_stop_transport.py`에는 유사한 `_exchange`가 있지만 안전 경로와 오류·timeout 의미를 따로 검토해야 한다.

### Alternatives

1. 오류·인증·timeout·종료 의미가 같은 부분을 공통 전송으로 추출한다.
2. 정지와 action의 실패 정책을 구분해 사본을 유지하고 대조할 불변식을 시험으로 고정한다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 독립 Safety 검토와 trailer, 원래 timeout·오류 분류·중복 전송·stop 보장을 검증한 뒤 후속 계획을 쓴다.
