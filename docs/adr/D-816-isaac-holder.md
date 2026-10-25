## D-816 Isaac 시뮬레이션 holder의 소유권

**Status:** Proposed

### Context

현재 Isaac ROS 패키지는 `learning/envs/isaac`에 있고 manifest의 장치 설치 예외를 가진다.

### Alternatives

1. integration 역할로 정하고 integrations/simulation/isaac로 옮긴다.
2. 학습 환경 역할을 유지하고 learning holder 및 기존 설치 예외를 명시한다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: colcon 발견·배포 closure·학습 입력과 실행 권한을 확인하고 기존 패키지 identity를 보존한다.
