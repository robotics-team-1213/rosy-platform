## D-304 플랫폼 확장은 제어권·계약·배포 증거로 경계를 결정한다

**Status:** Accepted (2026-09-27, 구조 판정 기준과 이행 순서). 장치 API, ROS 패키지, 소스 폴더, 배포 산출물 또는 운영 capability를 이 결정만으로 추가·이동·활성화하지 않는다. D-231의 층별 소스 배치와 D-303의 Rejected 상태를 유지한다. D-281·D-282·D-297·D-299의 Proposed 구현·장치 게이트를 승인한 것으로 읽지 않는다.

**Context:** ROSY Platform의 첫 경로는 관제사가 Pinky에 이동을 요청하고 실제 결과와 정지를 확인하는 것이다. 장기적으로 고정 OMX 작업대, Pinky에 탑재한 팔, 독립 드론과 다른 ROS 기반 장치를 같은 사이트 운영 경험에 연결하려 한다. 현재 `src/runtime/`은 Pinky CORE·주행·감지에 무게가 있지만 Fleet도 `core_common`의 일부 규칙과 타입을 실행한다. D-303의 제품별 `controllers/` 일괄 이동은 이 의존성과 이미지 경로를 해결하지 못해 기각됐다. 현행 Fleet 영속 작업은 `robot_id`와 평면 목표 `x/y/yaw` 중심이고, Fleet `task_id`와 CORE의 최종 주행 이벤트에는 검증된 연결이 없다. OMX 운영 제어기와 드론 기종·비행 제어 경로는 수용되지 않았다. 폴더 모양만 먼저 고정하면 실행 소유권, 설치 단위, 결과 의미가 다시 섞인다.

**Decision:**

1. **네 경계를 별도로 판정한다.** 새 기능마다 다음 표를 작성하고, 한 행의 근거로 다른 행의 완료를 주장하지 않는다.

   | 경계 | 판정 질문 | 현재 기준 |
   |---|---|---|
   | 물리 제어 | 최종 명령과 로컬 정지·복구를 누가 집행하는가? | Pinky 주행은 CORE, OMX 팔은 장치 수용을 마친 별도 로컬 제어기. Fleet·화면·AI는 최종 writer가 아니다. |
   | 작업 정본 | 누가 사람의 요청, 순서, 장치 간 인계와 불명 결과를 기록하는가? | 사이트 Fleet 한 곳. 장치의 실제 상태와 안전 판단은 로컬 제어기에 남는다. |
   | 교환 계약 | 독립 배포 주체가 실제로 어떤 값을 직렬화해 주고받는가? | 생산자·소비자·버전·인증·만료·취소·중복·결과 출처를 확인한 값만 공통 계약 후보로 삼는다. |
   | 배포 단위 | 어떤 패키지와 설정이 산출물에 실리고 어느 호스트·장치에서 실행되는가? | 폴더명이 아니라 package closure, 서명·digest, 설치 내용과 장치 readback으로 확인한다. 한 호스트의 공유는 하나의 제어권을 뜻하지 않는다. |

2. **현행 소스 배치를 유지하며 모듈별로 감사한다.** `src/{contracts,runtime,devices,products,hmi,site,sim}`은 D-231의 현재 분류다. `runtime`이 Pinky 중심이라는 관찰은 맞지만 `runtime/pinky_pro`나 `controllers/pinky_pro`로 통째 이동할 근거는 아니다. `core_common`의 각 모듈을 (a) 사이트↔장치 wire schema, (b) 사이트 내부 타입, (c) 장치 로컬 실행 규칙, (d) 둘 이상이 실행하는 규칙으로 분류하고 실제 import·생산·전송·이미지 소비자를 기록한다. `intent`·`succession`처럼 Fleet와 CORE가 함께 쓰는 실행 규칙은 호출자가 둘이라는 이유만으로 wire 계약이 되지 않으며 Pinky 폴더 아래로 옮기지도 않는다. 독립 시험·설치와 의존 방향을 개선하는 작은 추출만 별도 변경으로 제안한다. D-18의 세 번째 실제 소비자는 재검토 계기이며 자동 분리 지시는 아니다.

3. **복합 로봇은 로컬 상호 인터록을 별도로 검증한다.** Pinky에 OMX를 장착해도 CORE는 base 최종 `cmd_vel`, OMX 로컬 제어기는 arm 최종 trajectory를 각각 소유한다. Local Transaction 후보는 팔 접힘·차체 정지·운반 상태와 측정된 한계를 이용해 동작 순서를 조정하지만 세 번째 최종 writer가 되지 않는다. Fleet의 “이동 후 집기” 순서만으로 팔 전개 중 주행을 허용하지 않는다. 상대 상태 미확인·통신 상실·재시작 시 새 동작을 차단해야 한다. 이미 동작 중 상태가 만료되면 각 최종 명령 경로의 정의된 안전 동작과 실제 readback을 검증해야 하며, 확인 없이 자동 재개하지 않는다. 단일 로컬 조정 흐름과 두 제어기의 교차 게이트 중 구현 주체, 허가 표현·신선도·해제 조건, 동시 동작과 복구 절차는 D-55의 측정·DEVICE 시험을 포함한 별도 결정 전까지 확정하거나 활성화하지 않는다.

4. **첫 공통 작업 의미는 결과 추적에서 검증한다.** Fleet Mission·Mission Step, Device Action, Local Transaction은 D-298처럼 구별한다. Pinky 첫 이동에서 Fleet 요청 ID·발행 시도·CORE 수락·실행·최종 이벤트·취소·정지 readback을 같은 작업으로 검증하기 전에는 `ACCEPTED`를 `COMPLETED`로 바꾸지 않는다. 타임아웃, 중복·지연 이벤트, 연결 상실과 재시작 뒤 결과가 불명확하면 `UNKNOWN`을 보존하고 자동 재실행하지 않는다. 현재의 `robot_id+x/y/yaw` 요청에 팔·드론 필드를 덧붙여 범용 action이라고 부르지 않는다. 첫 실물 OMX action 표본 이후 두 장치가 공유하는 최소 의미와 장치 고유 payload를 비교한다.

5. **드론은 새 로컬 제어 경계의 후보로 둔다.** Fleet Mission과 Device Action의 구분, 요청·수락·최종 결과·취소·불명 상태의 출처는 확장 시 평가할 공통 의미다. 특정 기종과 ROS/비행 제어 경로, 좌표계, 비행 모드, 이륙·착륙, 링크 단절 시 로컬 동작과 정지 증거가 정해지기 전에는 드론 owner, 공용 비행 API, `Pinky RobotMode` 재사용 또는 `src/drone` 골격을 정하지 않는다. ROS 2/DDS 사용 여부만으로 사이트와 드론이 하나의 제어 graph에 참여하거나 Fleet이 모터 출력을 소유하게 하지 않는다.

6. **화면·영상·호스트 상태를 작업 결과와 구별한다.** 사이트 관제 화면은 Fleet의 요청·상태·증거를 투영하고, 로봇 로컬 화면은 로컬 제어기의 권한을 따른다(D-275). 카메라 원본은 각 source의 인증·신선도·보정 경계에 두며 Fleet 작업 원장이나 공통 명령 경로에 넣지 않는다. 영상 가용성, 사이트 PC·장치 호스트의 서비스/아티팩트 상태, 장치의 실제 작업 결과는 각각 다른 관측값이다. 하나가 정상이어도 다른 것의 완료 증거가 되지 않는다.

7. **설치 결과를 보고 폴더를 결정한다.** 현재 Pinky 필수 ROS 패키지 목록에는 `omx_adapter`가 있고 `deploy/robot`은 릴리스·설치 경로로 참조된다. 포함 이유와 제거 조건, `description`의 장치/시뮬레이션 소비자, CORE·Fleet·Overhead의 `core_common` 설치 의존을 확인하기 전에는 패키지를 제거하거나 `deploy/robot`을 개명하지 않는다. 두 번째 로컬 제어기의 소스·시험·산출물 경계가 실제로 분리되면 그때 새 ADR로 소스 루트와 배포 루트를 결정한다. 새 폴더는 확장 가능성의 증거가 아니다.

**판정 기록:** 새 장치나 복합 작업의 설계에는 `사용 사례 → 물리 명령·정지 owner → Fleet/로컬 상태 정본 → 실제 교환값과 버전 → 단절·재시작 결과 → package closure와 설치 호스트 → 현재 증거 수준 → 반례 시험`을 한 표로 남긴다. 미확인 항목은 후보로 표시하며 공개 API·capability·폴더를 선행하지 않는다.

**대안:**

- `controllers/<제품>` 또는 `runtime/<제품>`으로 지금 일괄 이동: Pinky 중심 코드, Fleet와 공유하는 실행 규칙, 이미지 package closure가 제품 폴더와 일치하지 않아 D-303의 실패를 반복한다.
- 하나의 범용 Runtime·ROS graph·작업 payload로 팔과 드론까지 처리: actuator, 정지, 좌표와 완료 의미가 달라 안전 소유권과 결과 출처가 흐려진다.
- 폴더와 배포를 영구히 현행대로 고정: 두 번째 제어기의 실제 독립 수명과 중복 실행 규칙이 확인돼도 구조 개선을 막는다. 이 결정은 증거가 생길 때 별도 ADR로 재배치할 길을 남긴다.

**이행과 검증 게이트:** 첫 사용자 목표인 Pinky 관제 이동의 결과 연결을 우선한다. 아래 감사·설계는 병행할 수 있으며 앞 행의 DEVICE/FIELD 완료가 뒤 행의 SOURCE 조사를 막지 않는다. 각 산출물의 승격은 자기 증거 수준에서 따로 판정한다.

| 작업 | 지금 가능한 SOURCE/LOCAL 판정 | 운영 승격에 추가로 필요한 증거 |
|---|---|---|
| Pinky 결과 연결 | 현재 P0 추적의 누락을 기준으로 Fleet `task_id`·CORE 명령·최종 이벤트 연결과 중복·응답 손실·late cancel·재시작 반례를 설계·시험한다. 연결 전에는 `COMPLETED` 승격과 자동 재시도를 금지하고 `UNKNOWN`을 유지한다. | 실제 Pi/Nav2 결과·정지 readback·현장 복구는 DEVICE/FIELD에서 별도 확인한다. 호스트의 결과 연결 시험이 물리 도착을 증명하지 않는다. |
| OMX 로컬 owner | 정적 identity·단일 owner·취소/정지 규칙과 ROS-SIM 경로를 검토한다. LeRobot 직접 연결은 운영 ROS owner와 배타적인 개발 모드로 둔다. | 실물 관절/그리퍼 상태, 버스 점유, 독립 정지·복구와 native 설치 산출물의 ARTIFACT/DEVICE readback 전에는 `omx.enabled: false`와 원격 운영 action HOLD를 유지한다. |
| 계약 감사 | `core_common` 모듈별 생산자·소비자·wire 여부·버전·독립 설치/호환을 지금 조사한다. 별도 계약 추출의 필요성은 Pinky·OMX action 표본과 실제 교환 경계로 판단한다. | 새 공개 schema·범용 enum·공용 실행기의 활성화는 D-18 호환 시험과 두 owner의 실제 소비를 요구한다. OMX DEVICE 완료만으로 자동 추출하지 않는다. |
| 복합 로봇 | 상호 인터록과 진행 중 상태 만료의 반례를 문서·ROS-SIM에서 탐색한다. 로컬 조정 방식과 폴더는 미결정으로 둔다. | 각 최종 명령 경로의 안전 동작·readback·stale·재시작·동시 동작을 장착 실물에서 DEVICE/FIELD로 측정한다. |
| 독립 드론 | 필요한 owner·비행 계약 질문을 기종 선정 전 문서로 정리한다. 빈 폴더나 운영 capability를 만들지 않는다. | 선정된 기종/제어 스택의 좌표·비행 모드·링크 단절 동작·결과/정지를 별도 DEVICE/FIELD에서 측정한다. |
| 소스 재배치 | `core_common`·`description` 생산자·소비자와 이동 후 의존 방향을 감사한다. | 위치 변경은 D-231을 다루는 별도 ADR과 소스·빌드·호환 시험으로 판단한다. 이 자체가 장치 운영 승인이나 설치 경로 변경은 아니다. |
| 배포 분리 | 현행 package closure, `omx_adapter` 포함 이유, `deploy/robot` 설치·릴리스 소비자를 감사한다. | 릴리스 변경은 대상별 서명·digest·설치/readback·되돌리기 시험으로 별도 판정한다. 검증 전 기존 아티팩트를 유지한다. |

**필수 반례:** 복합 장치 시험은 허가가 동작 중 만료되거나 재시작 뒤 남는 경우, 수신 시각만 새롭고 원본 측정·보정은 오래된 관절 상태, 적재물 유무 불명, 취소 응답 뒤 관성 운동을 포함한다. 각각에서 새 명령 차단, 이미 진행 중인 동작의 정의된 안전 동작, 실제 readback과 Fleet의 결과 불명 표시를 별도로 확인한다. 드론은 같은 단어의 `stop`을 재사용해 이 시험을 통과한 것으로 간주하지 않고 선정 기종의 링크 단절·비행 중 안전 동작을 별도 측정한다.

SOURCE/LOCAL 문서·호스트 시험은 ROS-SIM, ARTIFACT, DEVICE, FIELD 수용을 대체하지 않는다. 배포나 계약 변경에 실패하면 해당 capability를 비활성으로 두고 마지막으로 검증된 단일 owner·API·아티팩트로 되돌린다. 이 ADR 자체의 검증은 ADR 로그·하네스·문서 링크와 현재 소스/배포 사실의 대조에 한정한다.

**Consequences:** 플랫폼 확장 논의에서 “어느 폴더에 둘까”보다 위 네 경계와 관제 결과의 실제 출처를 먼저 확인한다. D-231·D-275·D-290·D-296·D-298의 Accepted 의미는 유지하고 D-303의 제품별 일괄 이동은 재활성화하지 않는다. D-282의 물리 소유권 제안과 D-299의 LeRobot 운영 경계는 각각의 승인·DEVICE 게이트를 계속 따른다. 이 ADR은 API Reference·typed schema·ROS package name·설치 스크립트를 변경하지 않는다.

**References:** [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-290](D-290-rosy-platform-naming-and-site-intent-boundaries.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-297](D-297-command-ack-and-fleet-record-activation.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-303](D-303-controller-owned-source-layout.md), [플랫폼 역할·계약 계획](../plans/2026-09-27-rosy-platform-role-and-contract-implementation-plan.md), [P0 추적](../validation/2026-09-27-platform-p0-task-result-trace.md), [OMX P1 소스 판정](../validation/2026-09-27-platform-p1-omx-source-gate.md), [필수 이미지 패키지](../../deploy/image/required-ros-packages.txt).
