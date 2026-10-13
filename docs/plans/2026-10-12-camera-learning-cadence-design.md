# 카메라 관측 단위의 Isaac 조향 학습

## 문제와 범위

R41에서는 같은 카메라 source_stamp 안에서도 조향 행동이 11,055회 바뀌었다. 기존 Q update의 gamma 0.95가 240Hz마다 적용돼 1초 뒤 가중치가 약 4.5e-6으로 줄어든다. 기존 segmentation·line_follow·CORE를 유지하면서 조향 보정을 학습한다는 D-650/D-676 목적에 맞게 의사결정과 보상 집계 단위를 카메라 관측으로 바꾼다. 물리 설정 변경이나 traffic gate 우회는 범위 밖이다.

## 선택

- 매 physics tick 학습 유지: 관측 중복과 짧은 할인 시간을 해결하지 못한다.
- 고정 N tick마다 선택: 카메라 acquisition 실패·중복·지연과 어긋날 수 있다.
- **새 유효 source_stamp마다 선택**: 실제 관측 획득에 연결하고 중복 stamp에서는 동일 gain을 유지한다. 이 방식을 채택한다.

## 계약

1. episode별 카메라 의사결정 상태를 초기화한다. 첫 유효 관측에서는 행동을 선택하지만 이전 행동 보상을 만들지 않는다.
2. 엄격히 증가하는 유한 source_stamp와 유효 state가 새 의사결정 경계다. 동일 stamp에서는 기존 행동을 유지하고 재탐색하지 않는다. 역행 stamp는 새 의사결정으로 승인하지 않는다.
3. 구간마다 발생한 measured reward를 합쳐 다음 유효 관측에서 이전 실행 행동을 한 번 갱신한다. gamma 0.95의 단위는 물리 tick이 아닌 관측 구간이다. 관측 주기는 현재 0.1 sim second다. 관측 간격이 달라지는 실험은 별도 의미 검토가 필요하다.
4. CORE 성공 receipt로 확인된 유효 state/action만 학습한다. ZERO 대기는 마지막 유효 실행 연결을 보존할 수 있지만, 비학습 nonzero 이동·경고·후보와 다른 dispatch는 연결을 끊는다. 구간 보상을 관계없는 행동에 합산하지 않는다.
5. target 상실의 명시적 종료는 기존 원인 제한을 유지해 마지막 실행 행동에 한 번만 bootstrap 0으로 갱신한다. stale·추론·scan 실패는 조향 벌점 대상이 아니다. truncated와 정상 종료의 기존 의미를 분리해 시험한다.
6. 매 tick camera_tick·line_follow·CORE·freshness·obstacle·정지 검사를 유지한다. gain 유지가 오래된 관측 승인이나 명령 재전송 권한이 되지 않는다. held-path는 baseline gain만 쓰고 학습 연결을 끊는다.
7. baseline은 항상 gain 1, eval은 탐색·Q 쓰기 없이 같은 관측 주기를 따른다. 변경 전 physics-tick 정책을 새 정책으로 복원하지 않도록 camera policy schema를 구분한다. 모델 revision/hash pin은 유지한다.

실행 순서는 기존 runner처럼 새 관측의 행동 선택 → camera_tick 안전 판단 → 이전 구간 Q 갱신이다. 새 행동은 이 경계의 Q 갱신 전 표를 사용하므로 같은 bin의 greedy 선택에는 한 관측 경계 지연이 있을 수 있다. pending과 previous를 분리해 이전 reward가 새 행동으로 넘어가지 않게 한다. 경고·비학습 이동으로 receipt 연결이 끊어지면 누적 reward를 버린다. 같은 유효 관측에서 정상 dispatch가 재개되면 재개가 확인된 이후의 결과만 합산한다. 따라서 이때는 전체 관측 구간이 아닌 확인된 후반 구간의 reward이며, 간극·중단 전 reward는 포함하지 않는다. trace의 camera_learning에 실제 갱신 대상과 합산 reward를 남겨 원시 reward와 대조한다.

## 변경 경로

- tools/sim/isaac/camera_checks.py 및 필요한 작은 camera 전용 helper: 경계·보상 누적·실행 연결.
- tools/sim/isaac/run_map_rl.py: 매 tick 안전 실행을 유지하며 경계 선택/학습 및 trace 증거 연결. 600행 상한 유지.
- tools/sim/isaac/camera_lane.py: camera policy 시간 의미 schema 및 복원 거절.
- learning/envs/isaac/test: 중복 stamp, 새 stamp, 무효/역행, 보상 합계, 종료 1회, 외인성 실패, episode reset, ZERO/held/불일치 receipt, baseline/eval freeze.
- D-676 addendum·모듈 logs 및 private 실행 일지: 코드 시험과 native 완주 결과 분리.

## 검증 순서

먼저 실패 시험을 커밋해 원격 pytest로 재현하고 known_failures와 비교한다. 구현 뒤 해당 시험·기존 terminal credit·camera policy restore·CORE zero 경계·architecture를 원격 실행한다. 독립 소스 검토 후 최신 main을 반영한다. 새 headless native run에서 stamp당 선택 횟수, 구간 보상 합계, 종료 credit, Q 재계산과 eval 불변을 확인한다. 같은 seed/출발 자세의 baseline과 완주·이탈·정지를 비교하며 영상은 private에 보관한다. 주기 수정 통과만으로 완주·병렬 RL·Fleet 교통 수용을 선언하지 않는다.
