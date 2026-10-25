## D-812 learning의 실행 코드 의존과 부트스트랩 경계

**Status:** Proposed

### Context

`learning/evaluation/perception/road_replay.py` 등은 source 경로를 추가해 middleware·tools 구현을 읽는다. standalone 도구의 `_in_checkout`는 공통 패키지를 import하기 전에 실행되기도 한다.

### Alternatives

1. 재사용할 순수 계약을 contracts로 올리고 학습·운영 구현 의존을 제거한다.
2. 필요한 예외를 platform_parts에 좁게 기록하고 `import_prefix: []` 경로까지 경계 검사를 확장한다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 직접 실행·Colab·설치 wheel에서 필요한 모듈이 있는지 확인하고 우회 import를 주입해 경계 검사의 실패를 확인한다.
