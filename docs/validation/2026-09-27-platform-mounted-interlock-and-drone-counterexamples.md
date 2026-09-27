# 탑재형 Pinky+OMX 인터록 및 독립 드론 반례 검증표

**상태:** 시험 설계, 미실행 (2026-09-27). [D-305](../adr/D-305-platform-boundary-outcome-invariants-and-independent-gates.md)의 결과 불변식을 검증 가능한 반례로 풀어 쓴다. 조정기 배치, 허가 wire 형식, 시간 상한, 정지 회로 또는 드론 최종 writer를 결정하지 않는다. SOURCE/ROS-SIM 시험 통과는 ARTIFACT·DEVICE·FIELD 수용을 뜻하지 않는다.

## 탑재형 Pinky+OMX: 고정 OMX 인계 P3와 독립된 출구

CORE의 최종 base 명령과 OMX 로컬 제어기의 최종 arm 명령은 각자 하나의 writer를 유지한다. 로컬 상호 인터록의 검사 방법은 미결정이지만, 아래 각 경우에서 새 위험 동작을 막고 진행 중 동작의 안전 중단·실제 상태 확인·명시적 재개 판정을 증명해야 한다. Fleet Mission/Step의 순서나 성공 ACK는 이 증거를 대신하지 않는다.

| 반례 | SOURCE/ROS-SIM에서 실패시켜야 할 경우 | DEVICE/FIELD에서 필요한 관측과 출구 |
|---|---|---|
| **기존 접힘 허가와 OMX 재시작** | CORE가 팔 접힘 허가를 캐시한 뒤 OMX가 재시작해 팔 위치가 불명이 된다. 이전 허가·세션·설정/보정 generation을 새 실행에 재사용하거나 주행을 자동 재개하면 실패다. 구체적 generation 필드는 아직 계약하지 않는다. | 재시작 전후 원본 팔 위치·설정/보정 identity를 구분하고, 상태 불명 동안 base 명령 HOLD와 진행 중 주행의 안전 중단을 관측한다. 새 측정과 새 허가를 확인하기 전 재개하지 않는다. |
| **신선한 수신, 오래된 하드웨어 샘플** | ROS `JointState` 수신 시각만 최근이고 하드웨어 원본 샘플 또는 보정은 오래된 경우를 주입한다. 수신 시각만으로 팔 접힘·허가를 신선하다고 판단하면 실패다. 현 [P1 소스 판정](2026-09-27-platform-p1-omx-source-gate.md)은 원본 샘플 시각·driver 출처·보정 provenance를 아직 검증하지 못했다. | source-stamped joint/driver 샘플과 실제 관절을 대조하고, 원본 신선도·출처를 증명할 수 없으면 동작을 HOLD한다. 단순 ROS receipt 또는 ACK는 관절 readback이 아니다. |
| **접힌 팔과 불명 적재물** | 팔 접힘이 확인돼도 파지물 유무·질량·돌출 범위가 불명 또는 달라진 경우를 주입한다. D-55의 측정된 2-D footprint와 speed envelope 없이 기존 빈 차체 한계로 이동하면 실패다. | 물체·그리퍼 상태와 측정된 적재 footprint/속도 한계를 연결한다. 새로운 적재 상태에 맞는 측정·제한이 없으면 이동 HOLD를 유지한다. |
| **소프트웨어 HOLD/취소 ACK 이후 관성** | 한쪽이 HOLD나 취소 성공 ACK를 반환해도 팔 또는 차체가 관성으로 움직이거나 driver 상태가 불명인 경우를 주입한다. ACK를 물리 정지로 판정하거나 재개하면 실패다. | 정지 요청 전송, 로컬 안전 래치, driver/actuator readback, 물리 정지 또는 E-stop/driver 인터록을 서로 다른 증거로 기록한다(D-298). 진행 중 안전 중단 뒤 실제 정지와 fault 해제·양쪽 상태 재측정·새 허가를 확인하기 전 재개하지 않는다. |

**시험 기록 항목:** 각 반례마다 입력·원본 샘플 시각·세션/설정 identity·허가 출처, 두 writer의 새 명령 차단 시점, 진행 중 동작에 대한 중단 요청, 안전 래치, driver/actuator readback, 물리 정지, Fleet의 `UNKNOWN` 표시, 재개 승인/거부를 별도로 남긴다. 특정 stop 방식과 제한 시간은 실물 계측 후 별도 결정한다. 단일 조정 흐름과 두 제어기의 교차 게이트 중 구현 주체도 여기서 선택하지 않는다.

## 독립 드론: 별도 출구

기종과 비행 제어 스택을 고른 뒤 실제 최종 actuator authority가 ROS 노드, 비행 제어기, autopilot 또는 다른 계층 중 어디에 있는지 명령 경로·설치·실물 readback으로 확인한다. ROS 노드를 최종 writer로 미리 단정하지 않는다. 링크 단절·재시작·상태 stale에서 해당 스택의 로컬 failsafe와 비행 중 안전 동작, 명령 수락과 최종 결과의 출처를 별도 ROS-SIM/ARTIFACT/DEVICE/FIELD 게이트로 시험한다. Pinky+OMX 인터록 완료는 드론의 선행조건이 아니며 드론 시험도 고정 OMX 인계 P3의 선행조건이 아니다. Pinky의 `x/y/yaw`·`RobotMode`·`stop` 의미를 비행 action으로 재사용하지 않는다.

**현재 판정:** 위 반례는 실행·계측되지 않았다. 탑재형 동시 동작과 드론 운영 action은 HOLD다. 기존 [D-55](../adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-298](../adr/D-298-mission-action-and-stop-evidence-terminology.md), [부모 계획](../plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md)의 별도 장치 게이트를 유지한다.
