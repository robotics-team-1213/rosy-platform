## D-307 장치 최종 결과와 물리 정지 증거를 별도로 판정한다

**Status:** Accepted (2026-09-27, 결과 분류·검증 기준에 한정). D-305의 **필수 반례** 문장 중 모든 인터록 실패 사례에 Fleet `UNKNOWN` 표시를 요구하는 듯한 부분만 대체한다. D-305의 구조 경계, 탑재형 인터록 결과 불변식과 독립 검증 게이트는 유지한다. 새 API·상태 enum·합성 인터록·운영 capability는 승인하지 않는다.

**Context:** D-304의 50행과 D-305의 필수 반례는 허가 만료·적재물 불명·관성 운동 각각에서 Fleet `UNKNOWN`을 기록하는 듯 읽힌다. 그러나 [D-298](D-298-mission-action-and-stop-evidence-terminology.md)의 `UNKNOWN`은 **해당 Device Action/attempt의 최종 결과가 확인되지 않은 상태**다. 로컬 owner가 동일 action/attempt에 대해 출처가 확인된 확정적 중단·실패 최종 이벤트를 낸 경우, 물리 정지 확인이 별도로 남아 있어도 그 최종 결과를 지우면 안 된다. 현행 Fleet `task_id`와 CORE 최종 이벤트의 연결은 아직 검증되지 않았으므로 이 문서는 결과 경로가 구현됐다고 주장하지 않는다.

**Decision:**

1. **작업 결과는 동일 action/attempt의 최종 이벤트로 판정한다.** 권위 있는 로컬 owner의 최종 이벤트가 ID·attempt·출처와 연결되고 중복·지연·재시작 반례를 통과하면, 확인된 중단·실패 결과를 그대로 보존한다. 그 연결 또는 최종 결과가 불명인 경우에만 Fleet이 `UNKNOWN`을 유지한다. 허가 만료, 적재물 불명, 소프트웨어 HOLD, 취소 ACK 자체가 무조건 `UNKNOWN` 또는 완료를 뜻하지 않는다. 늦은 성공 ACK도 해당 attempt의 확정적 실패를 자동으로 뒤집지 않는다. 실제 결과 불일치는 별도 조정 대상으로 남긴다.

2. **정지 증거는 작업 결과와 다른 축이다.** 정지 요청 전송, 로컬 안전 래치, driver/actuator readback, 물리 정지 또는 E-stop/driver 인터록을 분리 기록한다(D-298). 물리 정지 readback만으로 원래 action의 성공·실패를 확정하지 않고, 최종 이벤트만으로 물리 정지를 확인했다고 표시하지 않는다. 진행 중 안전 동작과 재개 가능성도 별도로 검증한다.

3. **반례별 DEVICE 기록을 남긴다.** [탑재형·드론 반례 검증표](../validation/2026-09-27-platform-mounted-interlock-and-drone-counterexamples.md)의 각 탑재형 사례에 자극 시점, 새 명령 차단, 진행 중 안전 동작, 독립 driver/actuator readback, 측정된 시간 한계, 재개 조건, 동일 attempt의 최종 이벤트 유무와 Fleet 결과 분류를 별도로 적는다. 시간 상한·허가 프로토콜·정지 회로는 실측과 별도 결정 전까지 고정하지 않는다. 탑재형 인터록과 독립 드론의 게이트도 계속 분리한다.

**Validation / Transition:** SOURCE/LOCAL에서는 동일 ID/attempt의 확정적 실패 최종 이벤트와 최종 이벤트 부재, 늦거나 중복된 ACK, 정지 readback만 존재하는 경우를 각각 구별하는 시험을 요구한다. ROS-SIM은 인터록 자극과 이벤트 순서의 반례를 다루며, 실제 물리 정지·재개 판정은 DEVICE/FIELD에 남긴다. 현재 [P0 추적](../validation/2026-09-27-platform-p0-task-result-trace.md)은 최종 결과 상관관계의 간극을 기록할 뿐 이 출구를 통과하지 않았다.

**Consequences:** D-305의 구조 Accepted 상태는 유지된다. `UNKNOWN`은 결과 불명일 때만 남고, 확정적 로컬 최종 결과와 물리 정지 증거는 서로 독립적으로 보존된다. D-297의 Proposed ACK/결과 활성화와 OMX·탑재형·드론 DEVICE/FIELD 게이트는 변하지 않는다.

**References:** [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-297](D-297-command-ack-and-fleet-record-activation.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-304](D-304-platform-expansion-boundary-and-evidence-gates.md), [D-305](D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [탑재형·드론 반례 검증표](../validation/2026-09-27-platform-mounted-interlock-and-drone-counterexamples.md).
