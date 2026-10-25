## D-815 Gazebo scripts의 manifest와 책임 문서 일치

**Status:** Proposed

### Context

`integrations/simulation/gazebo/scripts/`의 물리 위치·manifest 목표와 책임 문서가 서로 다른 이동 의도를 담고 있다.

### Alternatives

1. 도구 소유로 정하고 tools/sim으로 옮기며 설치·실행 참조를 함께 갱신한다.
2. integration 소유로 유지하고 manifest 목표와 책임 문서를 현재 holder로 맞춘다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 설치된 Gazebo entry point, world·model·resource 경로와 현재 simulation 시험을 확인한다.
