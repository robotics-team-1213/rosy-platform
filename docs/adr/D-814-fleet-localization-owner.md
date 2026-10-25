## D-814 Fleet localization 자세 판정의 소유권

**Status:** Proposed

### Context

Fleet `localization/`은 World의 MapPose 투영을 소비하며 lane·lap 문맥을 판정한다. 현재 Fleet transaction과 World 상태 투영의 경계는 D-315 및 D-752를 따른다.

### Alternatives

1. 순수 자세·지도 해석을 World로 옮기고 Fleet에는 원장·admission·dispatch를 남긴다.
2. Fleet 운영 규칙으로 유지하고 World가 내는 관측·현재 상태와 판정의 경계를 문서화한다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 각 판정의 입력·상태 writer·소비자를 추적하고 source=bridged가 dead reckoning이라는 의미를 보존한다.
