## D-369 Mission 제어·장치 실행·ROS 제어·안전 정지의 책임을 분리한다

**Status:** Accepted (2026-09-30, 사용자 확인 경계). 이 결정은 역할·책임·증거 어휘를 고정한다. 새로운 wire schema/API, provider 활성화, 자동 Mission dispatch, OMX capability, 실물 정지·동작 또는 DEVICE/FIELD 수용을 승인하지 않는다.

**관련 결정:** [D-18](D-18-rosy-core.md) (공유 API/schema), [D-38](D-38-core.md) (Pinky 최종 `cmd_vel`), [D-326](D-326-agent-loop-boundary.md) (모델 역할), [D-330](D-330-fleet-action-admission-stop-and-recovery.md) (Fleet 중재·generation·정지), [D-333](D-333-er2-mission-device-action-contract-closure.md) (조작 Action·증거), [D-334](D-334-er2-tool-and-progress-read-boundary.md) (도구·진행 상태), [D-336](D-336-fleet-omx-local-ipc-boundary.md) (Fleet–OMX 로컬 IPC), [D-357](D-357-er2-mission-feedback-loop.md) (ER 2 피드백), [D-358](D-358-er2-feedback-outbox-and-replan-fencing.md) (후보 fence·모호성).

**번호 정정:** 이전 미커밋 초안은 D-362였다. main의 파일 크기 ADR 및 Pilot 브랜치 D-363–D-368과 충돌을 피하여 D-369로 변경했다. 이전 로그의 D-362 제어권 기록은 이 결정을 가리킨다.

### Context

“컨트롤”은 현재 네 층의 서로 다른 권한을 가리킨다. Fleet은 어느 Mission을 승인·순서화·발행할지 정하는 업무 오케스트레이터다. 장치 로컬 owner는 실제 ROS/driver 명령의 최종 writer이자 로컬 software stop owner다. ROS controller/driver는 제한된 setpoint나 trajectory를 실행한다. 물리 E-stop 경로는 Fleet·모델·일반 네트워크 호출과 독립해 장치에 설계된 안전 정지 기능을 수행한다. 여기에 성공 여부를 독립 판정하는 goal verifier가 있다.

D-330·D-333·D-357은 이 원칙의 상당 부분을 정했지만, 역할 이름과 각 호출의 권한·응답 의미가 여러 문서와 인터페이스에 흩어져 있다. 특히 Fleet의 원격 E-stop 응답을 물리 정지로 읽거나, ROS Action 접수를 Mission 완료로 읽거나, 모델의 도구 응답을 controller command로 취급하면 계층 사이의 증거가 끊긴다.

### Decision

1. **Fleet Mission Orchestrator가 애플리케이션 제어권을 가진다.** Fleet은 사용자 의도와 모델 후보를 typed Mission/Action 후보로 검토하고, 신원·workcell·capability·관측 근거·정책·운영자 승인 조건을 확인한다. 승인된 Mission의 순서, 자원 claim, 발행 grant/generation, 시도(attempt) 상관관계, timeout·취소·재조정, durable 상태와 피드백을 소유한다. Fleet은 ROS topic을 직접 쓰지 않고, 장치 owner가 수락했다고 물리 목표 달성을 선언하지 않는다.
2. **모델은 제한된 추론자이자 후보/읽기 도구 호출자다.** ER 2의 허용 도구는 현재 결정대로 읽기 전용 `get_mission_status`와 candidate-only `propose_replan` 등 명시적으로 allowlist된 도구에 한정한다. 모델은 Mission·장치 Action 상태를 직접 변경하거나 `SubmitAction`, 모터/그리퍼 명령, cancel, stop/E-stop, rearm을 호출하지 않는다. 모델 응답 종료는 Mission/Action 완료가 아니다.
3. **장치 로컬 Action owner가 최종 ROS/driver writer와 software stop owner다.** Pinky에서는 CORE가 이동 명령의 최종 중재자이자 `/cmd_vel` writer다(D-38). OMX에서는 승인·설치·활성화된 OMX local owner만 팔/gripper driver 명령을 소유할 수 있다. 로컬 owner는 각 발행 직전에 action/attempt, grant·generation, 로컬 stop latch, precondition/resource를 검사하고, 거부·불명·stale 입력을 fail-closed 처리한다. 결과와 driver readback을 자체 Action identity에 결속하고 불명 결과를 자동 재발행하지 않는다. Fleet의 grant는 권한 위임 범위를 표시할 뿐 최종 local interlock을 대체하지 않는다.
4. **ROS controller와 driver는 정해진 동작만 실행한다.** controller는 owner가 승인한 bounded velocity/trajectory/setpoint를 주기적으로 실행하고 자체 joint/velocity limits·상태를 보고한다. Mission 해석, 사용자/model authorization, 자원 중재, 목표 성공 판정은 맡지 않는다. 임의 topic publish나 별도 publisher가 CORE/OMX owner를 우회하지 못한다.
5. **물리 E-stop은 독립 안전 경로다.** 하드웨어 E-stop·안전 relay/drive enable 경로는 Fleet, ER 2, Wi-Fi, ROS graph, 일반 CPU software stop보다 우선하며 가능한 한 그 경로에 의존하지 않는다. Fleet `/api/fleet/estop`은 인증된 원격 stop request와 dispatch latch/fanout이다. 로봇 또는 로컬 owner의 software stop도 유용한 별도 경로지만 물리 E-stop의 증거가 아니다. HTTP 200, `stopped` 대상 수, 전송 완료, 수신 ACK 어느 것도 standstill을 단독 입증하지 않는다.
6. **Goal verifier는 실행·추론과 독립한다.** verifier는 등록된 센서/증거 producer의 출처, 대상 Action/attempt, 관측 시각·신선도와 predicate를 검증해 `GOAL_CONFIRMED` 또는 미확정/거절 근거를 기록한다. 모델 문장, API 성공 응답, ROS goal acceptance만으로 goal을 확인하지 않는다.
7. **공개 API는 권한 층을 따라간다.** 사람과 제품 클라이언트는 인증·인가된 Fleet/Core API를 호출한다. 모델 tool contract는 Fleet이 실행하는 allowlist된 읽기/후보 API다. Fleet-to-device 계약은 grant를 가진 장치 동작 API다. D-336 OMX 연결은 per-instance same-host UDS의 `SubmitAction`, `GetAction`, `CancelAction`, `StopLocal`, `GetStopState`, `RearmLocal` 범위다. 장치 owner-to-ROS 경로는 해당 장치 내부다. API 이름은 현재 소스 경계 설명이며 이 ADR만으로 새 공개 REST 경로나 schema를 만들지 않는다. wire field·version·오류 코드는 D-18의 API Reference, 공유 schema 및 실제 producer/consumer 시험과 함께 바꾼다.

### 현재 API 경로를 역할에 대입

Site Fleet과 로봇 CORE의 유사한 경로는 서로 다른 서비스·권한 경계다. 아래는 현재 API Reference/source에 있는 경로를 정리한 것이며, 새 endpoint 제안이 아니다.

| 호출 주체 → 소유자 | 현재 경로/계약 | 의미와 한계 |
|---|---|---|
| 운영자 → Site Fleet | `POST /api/fleet/proposals` → `POST /api/fleet/proposals/{proposal_id}/resolve` → `POST /api/fleet/missions/{mission_id}/admit` | 후보 기록·근거 재검사·Mission admission. `admit`은 실행 완료가 아니며, policy dispatch는 별도 gate다. |
| 운영자 → Site Fleet | `GET /api/fleet/dispatch-control`, `POST /api/fleet/dispatch/rearm`, `POST /api/fleet/estop` | 제어 latch/generation readback, 명시 rearm 요청, 원격 stop fanout. `estop` 응답은 CORE 요청 결과와 local OMX software-latch receipt이며 물리 E-stop 증명이 아니다. |
| 운영자/호환 클라이언트 → 로봇 CORE | `/api/v1/fleet/missions` 및 `/api/v1/fleet/do` | Site Fleet Mission API와 구분되는 CORE API. `do`의 현재 `goto/home/stop/estop/estop_release/mode/formation` 어휘는 generic pick/place 또는 임의 motor API가 아니다. |
| Site Fleet → OMX owner | D-336 same-host `/run/rosy/omx/{instance_id}/control.sock` UDS: `SubmitAction`, `GetAction`, `CancelAction`, `StopLocal`, `GetStopState`, `RearmLocal` | 인증된 Fleet peer와 versioned grant/readback 경계. 신규 원격 HTTP API나 Fleet→ROS/DDS 연결은 아니다. runner는 기본 비활성이다. |
| ER 2 adapter → Fleet tool dispatcher | `get_mission_status`, `propose_replan` | 도구 허용목록 안에서 현재 Mission snapshot을 읽거나 fenced 후보를 기록한다. tool result는 위 operator admission이나 device Action 호출을 대신하지 않는다. |
| Device owner → ROS/controller | 제품별 내부 action/topic/service/driver port | CORE/OMX가 최종 명령을 전달한다. 제품·설치별 concrete graph와 physical writer 검증은 SOURCE/LOCAL/DEVICE 증거로 각각 확인한다. |
| 독립 safety chain → drive/relay | 하드웨어 E-stop 입력 | Network API가 아니다. 회로·drive readback과 물리 정지 수용을 별도로 측정한다. |
### 책임 및 인터페이스 표

| 책임자 | 소유하는 것 | 허용된 경계 | 성공으로 말할 수 있는 증거 |
|---|---|---|---|
| 운영자/클라이언트 | 의도 제출, 검토·승인, 취소/stop 요청, 재개 승인 | 인증된 Fleet/Core API 및 콘솔 | 서버가 반환한 접수/승인 상태만 |
| ER 2 / 모델 adapter | 관측 해석, typed 후보, allowlist 도구 호출 | Fleet이 제공한 제한된 context/tool loop | provider turn/tool result만 |
| Fleet Mission Orchestrator | Mission 원장·정책·승인·순서·claim·grant·세대·피드백 | Fleet API와 등록된 device Action transport | Mission journal의 admission/dispatch/readback 상태 |
| 장치 Action owner (CORE / OMX) | 최종 명령 writer, local Action lifecycle, local software stop, driver readback | CORE REST/WS 또는 D-336 OMX UDS; 내부 ROS/driver | 장치 owner의 상관된 Action 및 driver 상태 |
| ROS controller / driver | 한정된 제어 setpoint/trajectory의 실제 실행 | 장치 내부 ROS interface | controller/driver telemetry 및 상태 readback |
| 독립 safety chain | 물리 에너지 차단과 안전 reset 조건 | 하드웨어 안전 회로/drive input | safety circuit·drive readback 및 별도 standstill 검증 |
| Goal verifier | 완료 predicate와 관측 증거 검증 | 등록된 신뢰 evidence producer | 해당 attempt에 결속된 `GOAL_CONFIRMED` 증거 |

### 요청·진행·종료 의미

| 관측 단계 | 의미 | 다음 단계로 추론할 수 없는 것 |
|---|---|---|
| `PROPOSED` | 모델/사용자가 의도를 후보로 제출 | 승인·발행 |
| `ADMITTED` | Fleet 정책과 필요한 사람 승인이 Mission을 받아들임 | 장치가 받음 |
| `ACTION_ACCEPTED` / `RUNNING` | 장치 owner가 상관된 attempt를 접수/실행 중 | Action 성공·목표 달성 |
| `ACTION_SUCCEEDED` | 장치 owner의 terminal Action readback | 목표 predicate 달성 |
| `GOAL_CONFIRMED` | 독립 verifier가 신뢰 evidence로 목표를 확인 | 추가 안전조건이나 물리 정지 |
| `STOP_REQUESTED` / `STOP_LATCHED` | 원격 요청/로컬 software latch의 상태 | controller 정지 또는 물리 standstill |
| `CONTROLLER_STOP_READBACK` | 제어 owner/driver가 정지 상태를 읽어 확인 | 안전 회로 차단 또는 검증된 standstill |
| `PHYSICAL_STANDSTILL_CONFIRMED` | 지정된 독립 계측 절차가 물리 정지를 확인 | 재무장/재개 허가 |

위 문자열은 층 간 상태의 **의미 구분**이다. 모두가 오늘의 공통 wire enum이라는 뜻이 아니다. 기존 API가 더 좁은 증거를 반환하면 그 범위대로 표시하고, 증거가 없거나 stale/상충이면 `UNKNOWN`/`HOLD`로 남긴다. stop 후 rearm은 권한 있는 운영자의 명시 승인, 새 generation, 모든 진행/불명 attempt의 조정, local owner 상태 확인 및 적용 가능한 safety reset 조건을 요구한다. 재연결·provider retry·프로세스 재시작은 재개 신호가 아니다.

### Pick-and-place에 적용

“빨간 블록을 초록 트레이에 놓아” 같은 의도는 자동으로 좌표나 관절 명령이 되지 않는다. 모델/vision은 관측 frame·시각·식별 근거에 결속된 object/target **후보**를 낸다. Fleet은 workcell과 현재 등록 capability, 승인 규칙, Action schema 및 자원 예약에 맞는 typed `PICK_PLACE` Mission을 준비·승인·순서화한다. OMX owner는 원본 frame/calibration revision, 좌표계·단위·도달 범위, grasp/place precondition, gripper/driver 준비 상태를 검증한 뒤 bounded Action을 실행하거나 거절한다. owner readback 뒤 verifier가 실제 placement predicate를 확인한다.

현재 코드의 후보/mission/feedback/OMX 로컬 API 구조는 이 연결의 일부를 표현하지만, 일반 자유 문장→정확한 pose 변환·좌표계/calibration 변환·선정된 ROS/gripper driver의 실기 동작·물리 stop/goal acceptance가 완성됐다는 뜻은 아니다. OMX runner는 기본 비활성이고 selected driver·물리 증거는 별도 게이트다(D-336). 첫 실장 범위는 등록 capability와 관측 근거가 갖춰진 고정 workcell/action profile로 제한하며, 부족한 전제는 `HOLD`로 표면화한다.

### Action과 메시지 종류의 관계

Action은 실행 수명·상태·결과를 갖는 작업이다. 작업을 제출·조회·취소하고 진행·결과를 알리는 메시지는 command/query/response/event의 의미를 가진다. `action_kind=PICK_PLACE`는 작업 종류, `Envelope.type=command/event/ack`는 PRT 메시지 종류, UDS `operation=SubmitAction/GetAction/CancelAction`은 연산이다. `EnvelopeType.ACTION`을 추가하거나 `action_id`를 `msg_id`로 대체하지 않는다.

- `action_id`는 여러 메시지가 함께 가리키는 장치 작업이고 `attempt_id`는 실행 시도를 식별한다. 현재 구현은 Action 한 개에 한 attempt를 사용하며 여러 attempt 자동 실행을 지원한다는 뜻은 아니다.
- `msg_id`는 현재 PRT 메시지 ID다. `message_id`는 설명용 명칭이며 새 wire 필드가 아니다. UDS v1은 연결당 요청/응답 한 쌍이며 이 필드를 받지 않는다.
- `event_id`/`journal_event_id`는 사건 또는 출처별 원장 ID다. 반복 조회는 새 실행이나 사건을 만들지 않는다. 동일 사건의 재전달과 새 진행 사건을 구분해야 하며, source별 정수 ID를 전역 ID로 취급하지 않는다.
- 요청 중복 키, grant digest, attempt, correlation, 권한 세대는 별도 책임이다. ID 자체는 권한이 아니다. `Envelope.correlation_id`는 schema에 있지만 top-level runtime 생산·소비가 없으므로 구현된 연결로 표시하지 않는다.
- 같은 grant의 중복 수신은 driver 재실행을 만들지 않는다. 불명 submit 뒤에는 저장된 Action을 조회하고 응답의 전체 identity/generation을 보존한 grant와 비교한다. 새 메시지 ID·재접속·stop 해제는 새 실행 허가가 아니다.
- 공통 의미를 맞추되 PRT·REST·UDS·ROS를 하나의 범용 메시지 bus로 합치지 않는다. 물리 stop은 일반 메시지 queue나 Action 존재에 의존하지 않는다.
- 모든 메시지에 Action ID를 요구하지 않는다. heartbeat·pose·장치 관측은 각각의 장치/관측 식별을 사용하고, site/device stop은 해당 범위를 대상으로 한다. Action 관련 payload에만 Action/attempt 상관관계를 적용한다. 따라서 command 전체가 장시간 실행 Action을 뜻하지도 않는다.

[설계 검토](../plans/2026-09-30-action-message-identity-design.md)와 [구현 계획](../plans/2026-09-30-action-message-identity.md)에 근거와 단계별 작업을 둔다. ROS 2 Action은 goal/result/feedback과 관련 service/topic으로 구성된다. ROSY Action과 ROS goal은 반드시 일대일이 아니며, 현재 OMX의 단일 `driver_goal_id`를 여러 phase의 arm/gripper goal 기록 지원으로 해석하지 않는다.

### Alternatives

- **Fleet를 “전체 controller”로 부르고 ROS 명령까지 소유:** 실제 writer와 로컬 interlock을 흐리고 network API를 safety path처럼 보이게 하므로 거절한다.
- **ER 2 tool에 `pick`, motor, stop, rearm을 바로 노출:** Mission admission·grant·local fence·독립 verifier를 우회하므로 거절한다.
- **ROS controller가 Mission 승인/goal 완료까지 소유:** device execution과 Fleet 업무 정책, verifier 증거를 한 계층에 결합하므로 거절한다.
- **Fleet stop ACK를 E-stop 성공으로 표기:** 요청/전달과 물리 에너지 차단의 증거가 달라 거절한다.
- **모든 제품에 같은 transport/API를 강제:** CORE REST/WS, OMX same-host UDS, ROS 내부 제어는 신원·배치·실행 owner가 다르므로 공통 의미와 correlation을 맞추되 transport는 소유자 경계에 둔다.

### 결과 및 추후 계약 작업

- 설계·코드 리뷰에서 “controller” 대신 **Fleet Mission Orchestrator**, **device-local Action owner**, **ROS controller/driver**, **independent safety chain**, **goal verifier**로 지칭한다.
- status/API UI는 요청·접수·실행·terminal readback·goal evidence·stop latch·physical stop proof를 하나의 “완료”로 합치지 않는다.
- 후속 구현 전에 D-18 기준으로 실제 producer/consumer를 대조하여 각 profile의 Action envelope, `action_id`/`attempt_id`/generation correlation, timeout/UNKNOWN 재조정, cancel/stop/rearm readback, goal evidence schema·freshness를 한 계약에 고정한다. 기존 API에 없는 상태를 UI나 문서에서 보장하지 않는다.
- `POLICY_DISPATCH_ENABLED=False`, 모델 provider egress gate, OMX runner 기본 비활성 및 현재 DEVICE/FIELD hold를 유지한다. 이 ADR은 배포·장치 활성화 권한을 주지 않는다.

**검증 기준:** SOURCE에서 책임표와 현재 API/source boundary가 일치하고 문서 lint가 통과해야 한다. LOCAL 계약 시험은 허가 전후·중복/늦은 ACK·stop generation 경쟁·재시작·불명 Action, 모델 도구의 금지 호출, stale goal evidence, stop 요청/수신/local latch/driver 상태 분리와 물리 증거 부재를 다뤄야 한다. ROS-SIM은 writer 단일성·action correlation·재개 차단을 확인한다. DEVICE/FIELD의 정지 거리, hardware E-stop 및 pick/place 수용은 별도 계측·승인이다.
