## D-653 Isaac 두 대 진단의 CORE 명령과 카메라 상태를 장치별로 분리한다

**Status:** Accepted (2026-10-11, 사용자 두 대 Fleet 목표의 준비 계약; 실행 수용은 별도)

### Context

D-638과 D-650의 한 대 진단은 `isaac-pinky` 신원을 고정한다. 두 대가 같은 신원으로 명령과 이벤트를 내면 다른 로봇의 후보나 reset을 구별할 수 없다. 실제 Fleet·신호·횡단보도 연결 전에 독립 CORE 슬롯을 준비한다.

### Decision

1. 격리 진단의 신원은 기존 `isaac-pinky`와 두 대용 `isaac-pinky-a`, `isaac-pinky-b`로 제한한다. 기본값을 유지하고 실제 장치나 임의 신원은 생성 시 거절한다. 기존 MotionHeader 필드를 그대로 사용하며 외부 API·운영 POLICY admission을 만들지 않는다.
2. 각 SimulationOwner는 자신의 CORE CommandManager·ModeMachine·SafetyManager와 episode epoch·pending·halt를 가진다. 해당 신원의 후보만 검사하며 다른 장치의 후보·이전 epoch·TTL/관측 만료는 수신 owner만 정지한다. 상대 owner의 유효한 명령이나 상태를 변경하지 않는다.
3. 각 LearnedCameraLane은 동일 신원의 EventBus와 독립 기존 LineFollowManager·worker·keeper·steer·odom history를 사용한다. 한 로봇의 차선 상실이나 종료가 다른 로봇의 관측·조향을 무효화하지 않는다. 학습 gain은 기존 안전 gate 이전에 적용한다.
4. 이 준비는 D-638/D-650 진단 객체의 신원 분리에 한정한다. 실제 두 대 runner는 각 객체와 native articulation의 일대일 연결, 실제 정지·reset, 공통 clock 및 고정 모델/정책 identity를 후속 검증해야 한다. 같은 신원 객체의 중복 생성을 막는 전역 registry는 만들지 않으며 runner가 배정한 서로 다른 신원을 사용한다.
5. 기존 Fleet 서버·TripRunner·TrafficService의 권한은 유지한다. 정지선 이전 admission과 진입 후 점유, 신호 freshness, 보행자·통행권 충돌·만료·단절은 후속 계약과 native 실패 주입으로 확인한다. 두 객체 원격 시험을 두 대 Isaac 완주나 교통 수용으로 부르지 않는다.

### Consequences

기존 한 대 호출을 유지하면서 두 대의 명령과 인식 상태를 분리해 시험할 수 있다. 카메라 baseline·실제 camera Q 학습·Fleet/신호/횡단보도 영상은 여전히 별도 관문이며 D-606·ROS-SIM·실물 HOLD를 변경하지 않는다.

**Related:** D-2, D-8, D-442, D-517, D-525, D-573, D-606, D-638, D-650.
