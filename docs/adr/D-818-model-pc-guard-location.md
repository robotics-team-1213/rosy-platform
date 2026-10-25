## D-818 모델 PC guard 설치 스크립트의 존치

**Status:** Proposed

### Context

`deploy/site/install-model-pc-guard.sh`는 이름과 설치 대상 역할이 site holder와 다르다.

### Alternatives

1. 지원 경로이면 deploy/model_pc로 옮기고 호출자와 운영 문서를 갱신한다.
2. legacy 경로이면 현재 대체 설치 경로와 복구 방법을 확인한 뒤 삭제한다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 직접·간접 호출과 배포 프로필을 조사하고 모델 PC의 기존 guard가 제거되거나 약해지지 않는지 확인한다.
