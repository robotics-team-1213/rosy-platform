## D-638 Isaac의 한 대 CPU 강화학습 진단은 운영 정책 수용과 분리한다

**Status:** Accepted (2026-10-11, 사용자 실행 요청; 구현·실행 결과 별도 판정)

### Context

사용자는 최신 main 병합 뒤 실제 `map_v2_fleet`에서 headless 강화학습과 완주 실행을 요청했다. D-606의 Isaac Lab 수용은 RAM 32 GB와 물리 추종 검사 때문에 HOLD다. 현재 장비의 물리 RAM은 약 15 GB다. SDK 단독 headless 실행과 전진·정지는 확인됐지만 회전 추종 오차가 남았다. 이 상태에서 일반 학습 준비 완료를 선언하거나 swap을 물리 RAM으로 세면 안 된다.

### Decision

1. D-606의 Isaac Lab·운영·실물 수용 기준은 유지한다. 이번 별도 진단은 한 대, native Isaac SDK, 카메라 없는 경로·odom 관측, 표 형태 CPU Q-learning으로 제한한다. Isaac과 GPU 학습을 동시에 실행하지 않는다. 정책은 규칙 기반 경로 추종기의 회전 보정을 학습하며 순수 end-to-end 정책이라고 부르지 않는다.
2. `260919 MAP FILE.STL`의 해시를 확인하고 기존 `training_scene`과 `training-curved/lane_graph.yaml`을 함께 사용한다. 흰색 0.30 m 외곽 벽은 충돌체, 차선은 기존처럼 시각 전용이다. 지도·차선·로봇 형상은 학습을 쉽게 하려고 바꾸지 않는다.
3. 실행 권한은 Isaac 프로세스 안의 전용 simulation owner에만 있다. 운영 API, ROS publisher, 실제 Fleet 연결을 만들지 않는다. POLICY MotionIntent의 출처·장치·유효기간·관측 freshness·episode epoch·속도 한계를 owner가 검사한 뒤 기존 CORE NAVIGATION 슬롯과 `cmd_vel_cycle`을 사용한다. 이것은 D-442의 운영 POLICY admission을 여는 구현이 아니다. 실제 장치용 20 cm `BoundedTrial`은 그대로 둔다.
4. reset은 기존 CORE 슬롯 삭제와 실제 정지 확인 뒤에만 한다. 새 episode는 새 epoch를 쓴다. 이전 후보·만료 관측·엔벌로프 이탈은 0과 실패 종료로 처리한다. 환경은 실측 위치·속도로 진행률과 목표 정지를 판정한다. 경로의 순서를 건너뛰거나 종료 판정을 위해 로봇을 이동하지 않는다. 시간 초과만 truncation이다.
5. 기준 규칙 제어와 학습 후 고정 정책을 별도 시드에서 비교한다. 학습 Q 값 변경, 산출물 해시, 실행 소스, 실제 위치 궤적, 순서별 경로 통과, 실패·정지·자원 사용과 종료 코드를 기록한다. 학습 중간 진행률만으로 완주 성공을 선언하지 않는다.
6. 사전 자원 검사와 process memory/timeout 제한 안에서만 실행한다. 메모리 초과, SDK 오류, 무효 관측 또는 정지 미확인은 실패로 종료하며 학습 결과를 수용하지 않는다. 두 대 Fleet·횡단보도 신호·카메라 경계 모호성·실물 수용은 이 진단으로 대체하지 않는다.

### Consequences

실측 모델에서 작은 폐루프 학습 진단을 할 수 있으나 물리 회전 오차를 해결한 것으로 보지 않는다. CPU 표 학습과 성공한 단일 경로 평가도 Isaac Lab readiness, 두 대 교통 규칙 수용, 정책 승격을 뜻하지 않는다. 진단 실패의 source와 trace는 다음 수정의 근거다.

**Related:** D-322, D-427, D-434, D-442, D-606.
