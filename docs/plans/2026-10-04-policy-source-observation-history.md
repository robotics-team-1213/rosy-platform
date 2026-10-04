# OMX 정책 추론 원관측 보존

추론 중 정상 관절 상태 수신으로 sequence가 증가하면 현 래퍼는 후보를 무조건 거절한다.
기존 ArmCommandOwner는 원래 시작 자세와 설치된 허용 오차가 있으면 이전 source sequence를
검증할 수 있다. 이 경로를 사용하되 최신 자세를 원래 입력으로 대체하지 않는다.

- owner가 승인한 JointStateSnapshot만 bounded history에 보존한다. 기본 64개, 설정 1~4096개.
- 후보 sequence와 관측 시각이 실제 수신 원관측과 일치해야 한다.
- 원관측도 설치된 max_observation_age_ns를 만족하고 현재 자세와 차이가 owner tolerance 이하여야 한다.
- 원관측 시작 자세로 TrajectoryCommand를 만들며 final fence 내부에서 나이·자세를 재검사한다.
- 알려지지 않은/evicted/future/오래된 관측, 허용 오차 초과는 HOLD로 거절한다.
- camera, lease, authority, calibration, generation, action age와 기존 owner 재사용 방지 규칙은 유지한다.

검증: 정상 갱신 중 원관측 제출과 시작 자세 보존, 최종 authority callback 중 갱신,
오래된 원관측/범위 초과/eviction/시각 위조 및 capacity 입력 거절을 host에서 실행한다.
독립 safety review 후에만 commit한다. 이는 issuer 설치, 운영 승격, 실제 SIM 실행 또는 장치 수용 증거가 아니다.
