## D-813 CORE와 Fleet peer 암호·TLS 사본의 소유권

**Status:** Proposed

### Context

CORE `api/peer_pairing`과 Fleet `server/peer`는 별도 배포에서 peer proof와 TLS 검증을 유지한다. `test_peer_proof_ownership.py`가 사본 일치를 검사한다.

### Alternatives

1. 순수 암호·검증 구현을 contracts/foundation으로 모으고 두 배포가 그 버전을 설치한다.
2. 독립 배포 사본을 유지하고 proof 바이트·체인 검증의 대조 시험을 필수 관문으로 둔다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: trust anchor·인증서 유효기간·hostname·오래된 cryptography에서의 거절과 두 설치 묶음을 독립 검증한다.
