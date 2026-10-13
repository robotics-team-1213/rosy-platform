## D-678 Fleet 실행 승인과 결과 대조 파이프라인 완결

**Status:** Accepted (2026-10-12)

### Context

D-674가 자동 복구의 law/후보/전송 재검사를 연결했다. navigation·trip·formation에는 승인 도중 정지와 소유권이 바뀌는 창, goal의 거절 응답을 목표/lease로 기록하는 창, 늦은 무장 응답으로 STOPPED를 되살리는 창이 남았다. Mission은 첫 RUNNING만 읽어 다른 원장을 대조하지 못할 수 있었다.

### Decision

1. 기존 Task/Mission/Cell Job/trip/formation/signal 실행 소유자를 유지한다. Fleet의 완료 목표는 각 경로의 law → 후보 → 실행 직전 승인 → 전달 → 접수/결과 readback → 종결 또는 이유 있는 미해결 연결을 SOURCE/원격 회귀/리뷰/로컬 main 머지로 검증하는 것이다. 배포·활성 설정·실제 움직임은 별도 증거다.
2. navigation은 로봇별 하나의 goal/bay 승인·전달·교통 후처리만 진행한다. 같은 로봇의 겹친 요청은 기존 `COMMAND_REJECTED`로 거절하고, 순차 목표 교체는 유지한다. admission 진입부터 유지한 stop token이 capability/state await 뒤 바뀌면 전송하거나 대기열을 만들지 않는다. 전송 뒤 route/observe/map/bay 계산에도 검사하며 내부 traffic cancel의 예상 다음 generation만 인정한다.
3. CORE의 명시적 boolean `accepted`만 목표와 lease를 기록할 근거다. false는 거절, 누락/잘못된 타입은 불명이다. 전달 중 cancel/E-stop이 발생하면 늦은 수락 또는 불명 응답에 다시 navigation cancel을 요청하며 lease·성공 기록을 되살리지 않는다. mover stop과 겹친 bay 전송은 성공/예외 경로 모두 bay 로봇에 보상 cancel을 요청한다. 접수 후 교통 처리의 Hub/owner 거절은 원래 Task의 확정 실패로 쓰지 않고 UNKNOWN/점유/재발행 금지를 유지한다. HTTP cancel은 물리 정지 증거가 아니다.
4. Task의 source, 정확한 attempt, dispatch generation 및 policy 증거/활성 여부를 실제 owner 호출 직전에 다시 검사한다. 승인 대기 중 변한 known-unsent Task는 이유 있는 HOLD로 기록하고 자원 점유를 반환한다. 기본 policy gate는 계속 비활성이다.
5. trip 시작은 최초 검사부터 같은 stop generation을 유지한다. 정지가 중간에 발생하면 409 `TRIP_START_CANCELED`로 거절하며 live trip을 열지 않는다. 검사 후 열린 lease는 반환한다. alignment도 같은 generation을 검사하며 시작한 turn은 기존 CORE 정지와 bounded readback을 따른다.
6. formation은 진행 중인 follower goal pipeline과 겹쳐 시작하지 않는다. 마지막 follow 응답 뒤에도 STOPPED를 검사하고 늦게 무장된 팔로워를 해제한다. 운영자 stop 사유와 STOPPED는 늦은 무장 응답으로 덮지 않는다.
7. Mission은 Cell Job의 기존 round-robin 원칙처럼 configured READY와 모든 RUNNING/reconciliation_pending 중 한 Mission을 순환 선택한다. 한 번의 worker 호출은 owner 교환 하나로 제한된다. READY의 resource/fence/instance 검사와 기존 GetAction attempt를 유지하며 UNKNOWN을 자동 submit하지 않는다. 설정이 사라진 readback도 기존 attempt로 대조한다. cursor는 실행 상태가 아닌 process-local 순서이며 재시작은 원장을 읽는다.

### Consequences

새 범용 실행기나 정책 언어, 자동 AI 활성화, 임의 시간 초과 기준을 추가하지 않는다. 진행 중인 Action·UNKNOWN은 안전한 자원 점유를 유지하고, Task 완료는 correlated CORE 최종 결과, Mission 목표 완료는 독립 goal evidence를 요구한다. 경로별 실제 구현·시험·남은 현장 gate는 [통합 규칙집](../reference/fleet-rulebook.md)과 [완성 계획](../plans/2026-10-12-fleet-pipeline-complete.md)에 둔다.
