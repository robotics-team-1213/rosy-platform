## D-817 움직임을 요청하는 보정 노드의 holder

**Status:** Proposed

### Context

`middleware/perception/nodes/calibration_sequence.py`와 `startup_calibration_node.py`에는 관측 수집과 보정 움직임 요청이 함께 있다.

### Alternatives

1. 움직임 절차를 Drive로 옮기고 Perception에는 측정·관측만 남긴다.
2. 기존 nodes 예외를 유지하고 CORE의 lease·최종 명령 권한을 문서와 경계 시험에 고정한다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 보정 lease, 취소·timeout·정지와 실물 calibration 값을 보존하고 독립 Safety 검토를 받는다.
