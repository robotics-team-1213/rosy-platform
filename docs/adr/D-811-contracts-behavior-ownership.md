## D-811 contracts의 동작 코드 소유권

**Status:** Proposed

### Context

`contracts/foundation/core_common/protocol/account_client.py`, `contracts/learning/src/rosy/contracts/learning/prediction.py:forward`, `camera_setup.py:judge`에는 DTO 검사 외의 실행 계산이 있다.

### Alternatives

1. 각 동작을 소비하는 owner 패키지로 옮기고 contracts에는 데이터·검증만 둔다.
2. 현재 계약의 재현 가능한 순수 계산과 PKCE 클라이언트를 허용하도록 contracts 규칙을 명시한다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 각 소비자, wheel 설치 묶음, 저장 digest·프로토콜 호환성을 추적하고 owner별 검증을 통과시킨다.
