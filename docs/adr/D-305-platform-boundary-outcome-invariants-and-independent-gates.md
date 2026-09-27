## D-305 플랫폼 경계는 안전 결과 불변식과 독립 검증 게이트로 판정한다

**Status:** Accepted (2026-09-27, 구조 판정 기준과 검증 출구에 한정). [D-304](D-304-platform-expansion-boundary-and-evidence-gates.md)를 대체한다. 새 합성 인터록의 구현, OMX·드론 운영 제어, 공개 action schema, 폴더 이동 또는 설치 변경을 승인하지 않는다. D-282·D-297·D-299의 Proposed 장치·계약 게이트는 그대로 둔다.

**Context:** D-304는 물리 명령, Fleet 원장, 교환 계약, 배포 단위를 구분했지만 복합 장치의 결과 조건과 구현 책임, 소스 이동과 장치 수용의 검증 출구를 더 분명히 나눌 필요가 있다. 부모 [플랫폼 역할·계약 계획](../plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md)은 Pinky 탑재 OMX의 별도 조정기와 두 제어기의 교차 게이트 중 구현 주체를 미결정으로 둔다. 현행 P0 추적은 SOURCE/LOCAL이며, OMX의 서명된 독립 산출물·digest·의존 목록과 실물 action은 아직 수용되지 않았다. P3는 Pinky와 **고정 작업대 OMX** 사이의 사이트 인계다.

**Decision:**

1. **네 경계를 각각 판정한다.** 물리 명령·정지·복구는 해당 장치 로컬 owner, 사이트 Mission/Step·인계·결과 불명 원장은 Fleet, 버전된 wire 값은 실제 생산자와 소비자 사이의 교환 계약, 배포 단위는 이미지 package closure·서명·digest·설치 목록·장치 readback으로 판정한다. Pinky 주행 최종 writer는 CORE다. OMX 팔의 최종 writer는 D-282/P1의 장치 수용을 거친 별도 로컬 제어기 후보이며 Fleet·화면·AI·조정 흐름은 최종 actuator 명령을 발행하지 않는다. Fleet의 수락 기록은 장치 완료나 물리 정지를 증명하지 않는다.

2. **탑재형 복합 장치는 결과 불변식만 채택한다.** CORE의 base 최종 명령 경계와 OMX 로컬 제어기의 arm 최종 명령 경계는 각각 로컬 상호 인터록의 안전 조건을 집행해야 한다. 팔 전개·운반물·차체 운동 또는 상대 상태가 허용 범위 밖이거나 불명·stale이면 위험한 새 동작을 허용하지 않는다. 이미 진행 중인 동작에서 허가 만료, 상대 상태 stale, 통신 단절 또는 한쪽 재시작이 발생하면 해당 경계가 정의된 안전 중단을 요청하고 실제 driver/actuator readback으로 결과를 확인해야 한다. 정지 요청이나 성공 ACK만으로 정지를 판정하거나 자동 재개하지 않는다. 재개에는 양쪽 원본 상태의 신선도, 정지·적재물 상태, fault 해제와 새 허가의 검증된 조건이 필요하다. 구체적인 중단 동작·시간 상한·물리 정지 회로는 실측 후 결정한다. 별도 조정 흐름과 두 제어기의 교차 게이트 중 구현 주체, 호스트·프로세스·폴더, 허가 프로토콜과 검사 방법은 미결정이다. 이 결과 불변식은 두 제어기가 반드시 상대 데이터를 직접 읽는다는 구현 지시가 아니다. 실물 수용 전 동시 동작은 HOLD다.

3. **Local Transaction과 Fleet Mission을 분리한다.** D-55의 `robot-local mission`은 D-298의 `Local Transaction`, 곧 장치 내부 접근·파지·배치 상태 흐름으로 읽는다. 이는 Fleet Mission/Step 원장을 복제하거나 세 번째 최종 명령 writer가 되지 않는다. Fleet의 “이동 후 집기” 순서만으로 탑재형의 동시 동작 안전을 증명하지 않는다.

4. **계약은 실제 경계마다 감사한다.** `core_common`의 각 모듈에 생산자·소비자·직렬화 여부·버전·독립 import/설치·이미지 소비자를 기록한다. Overhead→Fleet `SiteSightingPayload`, Robot↔Fleet `Envelope`, 사이트 내부 `FleetTaskStatus`는 서로 다른 계약·타입이다. `intent`·`succession`은 Fleet와 CORE가 함께 실행하는 규칙이며 호출자가 둘이라는 이유만으로 wire schema나 Pinky 전용 코드가 되지 않는다. 기존 JSON 호환과 ID·중복·지연·`UNKNOWN` 반례를 따로 검증한다. D-18의 세 번째 실제 소비자는 추출 재검토 조건이지 자동 패키지 분리 지시가 아니다. 첫 OMX 실물 action 표본 전에는 Pinky `x/y/yaw` 또는 `RobotMode`를 팔·드론의 공통 action으로 확장하지 않는다.

5. **D-231의 층별 소스 배치와 D-303 기각을 유지한다.** `runtime/<제품>`·`controllers/<제품>`으로 일괄 이동하거나 `deploy/robot`을 지금 개명하지 않는다. 순수 소스 경로 이동은 D-231의 경로 참조 수정, 전체 host pytest, harness lint, colcon build, 이미지 빌드 조건으로 검증하고 장치 인수는 별도 게이트다. 설치 경로·이미지 내용·패키지 closure·릴리스 단위를 바꾸는 경우에는 해당 ARTIFACT 검증과 실제 대상 설치/readback을 추가한다. 소스 폴더 이동 자체에 모든 장치의 DEVICE readback을 일괄 요구하지 않는다.

6. **드론은 독립 후보로 둔다.** 기종·비행 제어 스택·좌표계·비행 모드·링크 단절 시 로컬 안전 동작을 확인하기 전 owner, 비행 action schema, ROS graph 연결 또는 폴더 골격을 고정하지 않는다. 드론 게이트는 탑재형 복합 인터록이나 고정 OMX 인계의 선행조건이 아니며, 그 게이트들도 드론의 선행조건이 아니다.

7. **화면·영상·호스트 상태는 작업 결과와 분리한다.** 사이트 관제 화면은 Fleet의 요청·상태·증거를 표시하고 로봇 로컬 화면은 로컬 제어기의 권한을 따른다(D-275). 영상 원본은 각 source의 인증·신선도·보존 경계를 지키며 Fleet 작업 원장이나 공통 명령 경로에 넣지 않는다. 영상 가용성, 사이트 PC·장치 호스트의 서비스/아티팩트 상태, 실제 Device Action 결과는 서로 다른 관측값이다. 하나가 정상이어서 다른 것도 완료됐다고 판정하지 않는다. ROS 2 사용만으로 모든 장치를 하나의 전역 제어 graph에 묶지 않는다.

**독립 검증 출구:** 각 행의 오른쪽 출구는 왼쪽의 SOURCE/LOCAL 또는 ROS-SIM 진전을 막는 단일 출구가 아니다. 단, 운영 capability의 활성화에는 해당 행의 실제 장치·현장 증거가 필요하다.

| 작업 | 지금 가능한 출구 | 별도 보류 출구 |
|---|---|---|
| P0 Pinky 한 이동 | SOURCE/LOCAL에서 Fleet `task_id`·발행 시도·CORE 수락·최종 이벤트의 ID 연결, 중복·지연·취소·재시작·`UNKNOWN`을 검증한다. 기존 P0 추적은 이 출구의 미충족 간극을 기록할 뿐이다. | 실제 Pi/Nav2 정지·도착과 안전 readback은 DEVICE, 관제 인계 결과는 FIELD에서 따로 증명한다. 수락을 완료로 승격하지 않는다. |
| P1 OMX 로컬 owner | SOURCE에서 identity·단일 writer·원본 joint 시각·취소·fault 규칙을 검토하고 ROS-SIM에서 단일 writer와 stale/restart HOLD를 시험할 수 있다. LeRobot 직접 연결은 운영 ROS owner와 배타적인 개발 모드로 둔다(D-299). | OMX 독립 산출물의 서명·digest·의존 목록·설치 목록은 ARTIFACT, 실제 관절/그리퍼·버스·독립 정지·재개 readback은 DEVICE다. 검증 전 `omx.enabled: false`와 원격 action HOLD를 유지한다. |
| P2 공통 계약 | 지금 `core_common` 모듈별 생산·소비·wire 여부·JSON 호환·독립 설치/import·이미지 closure를 감사한다. | Pinky 한 이동과 **실물** OMX action 표본 뒤에만 최소 wire 의미 추출을 결정한다. 시험 전 범용 enum·공개 schema·공통 실행 라이브러리를 만들지 않는다. |
| P3 고정 OMX 인계 | Fleet Mission/Step와 두 Device Action의 ID·인증·멱등성·취소·`UNKNOWN` 재조회 설계를 검토한다. | 승인된 OMX 장치 API와 두 장치의 실제 결과를 FIELD에서 검증한다. 탑재형 인터록 수용을 P3의 암묵적 선행조건으로 넣지 않는다. |
| 탑재형 Pinky+OMX | SOURCE/ROS-SIM에서 CORE·OMX 최종 writer 단독성, 양 경계의 안전 결과, 허가 만료·상대 stale·단절·재시작 중 새 명령 HOLD와 진행 동작 중단 요청을 시험한다. | 실제 장착 장치에서 driver/actuator readback, 적재물 불명, 정지 실패, 관성 운동, 재개 조건, 물리 인터록과 복구를 DEVICE/FIELD로 검증한다. 조정 구현은 별도 ADR로 확정한다. |
| 독립 드론 | 기종 선정 전 owner·계약·단절 질문만 문서화한다. | 선정 기종의 비행 스택·링크 단절·비행 중 안전 동작과 결과 출처를 별도 ROS-SIM/ARTIFACT/DEVICE/FIELD에서 검증한다. |
| 소스 이동 / 설치 변경 | 소스 이동은 D-231의 host pytest·harness·colcon·이미지 빌드를 따른다. 변경된 설치/이미지 경로는 package closure와 의존 목록을 별도 감사한다. | 설치/이미지 변경의 서명·digest·대상 설치/readback·되돌리기 증거는 해당 ARTIFACT/DEVICE 게이트에서 확인한다. |

**필수 반례:** 팔 접힘 확인 직후 원본 상태가 stale이 되는 경우, 동작 중 허가 만료·한쪽 재시작·통신 단절, 늦은 성공 ACK, 관절·그리퍼·적재물 상태 불명, 취소 응답 뒤 관성 운동을 각각 시험한다. 새 명령 HOLD, 진행 동작의 중단 요청, 실제 driver/actuator readback, Fleet의 `UNKNOWN` 표시, 재개 조건을 각각 기록한다. 특정 stop 방식이나 시간 상한은 실물 계측 없이 여기서 정하지 않는다.

**Consequences:** 이 ADR의 Accepted 범위는 위 판정 기준과 독립 게이트다. D-55·D-231·D-275·D-290·D-296·D-298의 기존 Accepted 의미를 유지하고 D-303을 되살리지 않는다. OMX 운영 owner·탑재형 허가 메커니즘·드론 로컬 owner·새 API·폴더·릴리스 산출물은 승인되지 않는다. SOURCE/LOCAL, ROS-SIM, ARTIFACT, DEVICE, FIELD는 서로 대체하지 않는다.

**References:** [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-297](D-297-command-ack-and-fleet-record-activation.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-303](D-303-controller-owned-source-layout.md), [D-304](D-304-platform-expansion-boundary-and-evidence-gates.md), [플랫폼 역할·계약 계획](../plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md), [P0 추적](../validation/2026-09-27-platform-p0-task-result-trace.md), [OMX P1 소스 판정](../validation/2026-09-27-platform-p1-omx-source-gate.md).
