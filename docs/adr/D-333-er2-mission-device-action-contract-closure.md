## D-333 ER 2 조작 후보의 Mission 승인, 장치 Action 수락, 정지와 목표 증거를 분리한다

**Status:** Accepted (2026-09-29, 계약 경계와 구현 순서에 한정). 새 REST 경로·wire schema·OMX capability, 모델 자동 승인, 실제 장치 동작, 사이트 정지 가용성 또는 DEVICE/FIELD 수용을 승인하지 않는다.

### Context

D-326/D-331은 모델을 실행권 없는 후보 생산자로, D-328은 Fleet을 Mission과 목표의 원장으로, D-327은 제품별 로컬 owner를 물리 Action의 소유자로, D-330은 Fleet의 단일 발행 claim과 stop generation을 정했다. 현행 소스에는 ER 2 표준 Interactions 어댑터, `MissionStore`/`MissionService`, OMX `ActionStore`/`PickPlaceTransaction`, 팔 trajectory port가 있다. 그러나 어댑터를 부르는 운영 경로, Mission REST/dispatcher, OMX Device Action API와 gripper/driver 결합, 독립 증거 생산자 연결은 없다. 각 단위가 있다는 사실은 통합된 물리 `PICK_PLACE`를 뜻하지 않는다.

ER 2 후보의 점은 `[y,x]` 0–1000 이미지 좌표이고 OMX `TargetSelector`의 점은 원본 관측 픽셀의 `(x,y)`다. 현재 두 타입 사이에 원본 프레임·crop/회전·보정 revision을 보존하는 변환기가 없다. Fleet의 generation 재검사는 장치가 아직 이전 명령을 받을 수 있는 네트워크 경합을 닫지 못한다. 전용 `/api/fleet/estop`은 감사 저장소 장애에도 fanout을 시도하지만 `/api/fleet/do`의 `estop`은 순차 step과 일반 감사 gate를 통과한다. 둘을 같은 긴급정지 계약으로 표기하면 오해를 만든다. 현행 goal 검증기는 호출자가 준 카메라 증거 필드를 비교하며 등록된 독립 생산자와 원본의 연결을 확인하지 않는다.

### Decision

1. **첫 작업은 고정 OMX 작업대의 한 `PICK_PLACE`로 제한한다.** operator 또는 ER 2는 동일한 불변 `Proposal`을 만들 수 있다. 후보에는 출처, caller request key, 원본 observation ID/이미지 digest, 관측 시각, selector, 요청한 goal을 담는다. 모델의 tool-call ID, confidence, 텍스트, provider credential은 principal·승인·Action ID가 아니다. Fleet은 명명된 사용자 인증이 활성화된 배포에서 인증된 operator가 후보와 해결된 대상을 확인한 뒤에만 Mission을 승인한다. 이 절차는 첫 수동 파일럿의 발의·승인 범위이며 향후 등록된 정책 작업마다 사람 클릭을 요구하는 일반 규칙은 아니다. 개발용 기본 principal로 물리 admission을 허용하지 않는다. 자동 admission, 단독 `PICK`/`PLACE`, 이동 중 조작과 streaming 제어는 별도 결정과 증거를 요구한다.
2. **외부 작업 계약은 세 번의 별도 수락으로 설계한다.** `CreateProposal`은 미해결 후보와 idempotency key를 별도 후보 원장에 남기고 물리 발행을 하지 않는다. 현행 `MissionStore.create_proposal()`은 이미 해석된 object/goal predicate를 요구하므로 모델의 미해결 후보를 그대로 넣지 않는다. 단일 대상 해석 뒤 `CreateMissionDraft`가 해결된 target evidence와 goal predicate를 Mission 원장에 남긴다. `AdmitMission`은 서버가 인증한 principal, workcell/capability, 현재 관측과 구성, goal predicate, Fleet generation, 공유 자원 claim을 원자적으로 확인한다. Fleet의 단일 dispatcher는 영속 발행 의도와 ID를 기록한 뒤 승인된 단일 Step만 `SubmitDeviceAction`으로 장치 로컬 owner에게 전달한다. 요청 handler나 모델 callback에서 바로 ROS goal을 보내지 않는다. 읽기·취소·결과는 각각 Mission ID와 Action/attempt ID를 돌려준다. caller 입력·관측·의미적 목표의 digest를 요청 키에 묶으며 provider interaction/call ID나 새 발행 generation은 이 digest의 일부가 아니다. 같은 키의 재호출은 저장된 후보를 반환하고 provider를 다시 부르지 않으며, 다른 의미적 입력은 충돌로 거절한다. 불명 결과와 timeout은 실패로 재분류하거나 자동 재발행하지 않는다. Site Fleet의 운영 경로는 `/api/fleet/*` 범주로 두고, 문서의 중앙 Fleet `/api/v1/fleet/missions` 카탈로그를 현행 경로로 표기하지 않는다. 실제 URL, HTTP 상태, 필드와 버전은 D-18에 따라 API Reference·`core_common.protocol.schemas`·양쪽 소비자 시험을 같은 변경에서 확정한다.
3. **이미지 selector는 해당 프레임에서만 해석한다.** 정규화 `[y,x]`/`[ymin,xmin,ymax,xmax]`를 카메라 관측의 원본 픽셀 `(x,y)`/`(xmin,ymin,xmax,ymax)`로 변환할 때 제공한 모델 입력 이미지의 크기, resize, crop, 회전 및 원본 프레임 digest를 보존한다. 원본 observation ID, camera/optical frame, capture time, calibration/TF revision이 실행 시 유효한 관측과 일치해야 한다. 해석기는 단 하나의 물체와 목적지를 확정해야 하며 다중/무응답/stale/이동/보정 불일치는 명확화 또는 HOLD다. 물체 identity 선택은 3D pose·grasp·충돌/도달성 승인이 아니며 로컬 planner가 별도로 판정한다.
4. **Fleet 발행 허가와 장치의 최종 명령 허가를 연결한다.** Fleet은 `mission_id`, `step_id`, `action_id`, `attempt_id`, 장치/workcell, 요청 digest, capability/config revision, observation revision, Fleet authority/epoch, 단조 증가 `dispatch_generation`, 짧은 유효 기한을 가진 단일 발행 grant를 만든다. Fleet이 두 상관 ID를 발급하고 OMX 원장은 이를 그대로 영속한다. 현행 `ActionStore`가 두 ID를 자체 생성하므로 새 연결 전에 충돌·중복 검증을 포함해 이 저장소 계약을 변경해야 한다. 장치는 인증된 Fleet 발행자, 바인딩된 장치 identity, 현재 로컬 stop latch/owner generation, 마지막으로 수신·영속화한 Fleet authority/epoch와 generation의 일치 및 유효 기한을 확인한 뒤 `SUBMITTING` 의도를 영속화하고 단일 owner만 ROS goal을 보낸다. 구 epoch/낮은 generation을 거절하고 clock 신뢰도가 없어 grant 만료를 확인할 수 없거나 통신/lease 신선도가 없으면 새 goal을 거절한다. stop을 수신하면 먼저 로컬 발행 래치와 generation high-water mark를 영속화하고 새 goal을 거절한 뒤 진행 중 goal의 로컬 정지를 요청한다. rearm은 새 generation의 장치 측 명시적 동기화와 미확인 Action 조정 뒤에만 가능하다. Fleet의 stop 요청이 장치에 도달하지 않은 구간은 사이트 API만으로 물리 정지를 보증할 수 없으므로 독립 로컬 stop·watchdog·하드웨어 E-stop과 실측이 필요하다.
5. **정지 API의 의미를 구분한다.** 일반 cancel은 queued Mission 또는 진행 중 Action의 취소 요청이다. 전용 `/api/fleet/estop`은 인증된 operator의 사이트 원격 정지 fanout이며 감사 장애에도 전송을 시도한다. `/api/fleet/do`의 `estop`은 긴급정지 UI나 장치 로컬 안전 경로로 사용하지 않는다. CORE 로컬 안전 stop, OMX owner stop, 독립 물리 E-stop은 각각의 수신·래치·driver readback·실측 시간으로 판정한다. HTTP 성공, cancel ACK, ROS action 결과, Fleet `stopped` 수는 물리 정지 증거가 아니다. owner/driver 재시작, grant 만료, 통신 단절, stop 후 재개에는 자동 재발행을 금지한다.
6. **Action 종료와 목표 달성을 별도 확인한다.** OMX는 arm/gripper의 접수·실행·파지·해제·후퇴 결과를 Action/attempt/driver goal ID로 기록한다. Fleet은 승인 시 고정한 goal predicate에 대해 작업 뒤 새로 수집한 독립 관측을 요구한다. 등록된 카메라 증거 생산자의 신원, 원본 observation digest, 시각, evaluator revision, 대상 identity/목적지 영역과 필요한 gripper/arm readback을 검증한다. 독립성은 모델의 초기 프레임·완료 문구와 별도의 생산/평가 경로로 입증하며 카메라 하드웨어가 반드시 달라야 한다는 뜻은 아니다. 호출자가 제출한 `satisfied=true` 또는 모델의 “완료”만으로 Mission을 완료하지 않는다. 증거 부재·충돌·출처 미확인·Action `UNKNOWN`은 완료가 아니라 HOLD 또는 미확인 상태다.
7. **provider와 운영 권한을 격리한다.** ER 2 adapter는 후보 생성에만 쓸 수 있는 별도 자격 증명과 호출 예산을 사용한다. 실제 이미지 전송 전에 서비스 요금제·데이터 처리 조건, 허용 장면, 보존·접근 기간, 키 주입/교체/마스킹을 승인한다. `store=false`를 전체 데이터 미보관 보증으로 해석하지 않는다. 모델은 stop 해제나 `SubmitDeviceAction`을 호출하지 않는다.

### 계약 추적표

| 경계 | 최소 식별자·입력 | 권위 있는 반환 | 거절·불명 상태 |
|---|---|---|---|
| 후보 생산자 → Fleet | caller key, provider provenance, observation ID/digest/time, typed selectors | `proposal_id`, `PROPOSED` | malformed/ambiguous/stale 후보는 실행 없음 |
| Fleet 승인 → Mission 원장 | 인증 principal, proposal/goal predicate, workcell/capability/config revision, expected generation | `mission_id`, 승인 상태와 claim | conflict, 미지원 capability, generation 불일치, 자원 충돌 |
| Fleet → OMX 로컬 owner | mission/step/action/attempt ID, digest, device/workcell, grant generation/expiry, resolved target evidence | durable Action 수락/거절과 동일 ID | 불명 ACK는 `UNKNOWN`/HOLD, 자동 중복 송신 없음 |
| OMX owner → ROS/driver | local owner generation, ROS goal ID, arm/gripper 상태 | 실제 driver 접수·readback | ACK/결과 손실은 조정 전 `UNKNOWN` |
| 독립 증거 → Fleet 목표 | 등록 producer, observation digest/time, evaluator revision, predicate/object/destination | goal 충족/미충족/미확인 | 출처·신선도·물리 결과 불일치는 완료 불가 |

### Alternatives

- **모델 함수를 곧바로 ROS/driver에 연결:** 영상 좌표의 의미, 장치 권한, 정지와 결과 판정을 건너뛰므로 채택하지 않는다.
- **Fleet generation 재검사만으로 정지 완료 선언:** 송신 뒤 또는 stop 전달 전에 장치가 옛 goal을 받을 수 있어 채택하지 않는다.
- **모든 요청을 한 `/api/fleet/do` 순차 배열로 표현:** 영속 Mission/Action ID, 독립 emergency stop, 늦은 결과 조정과 goal 증거를 표현하지 못해 채택하지 않는다.
- **단계별 수락과 장치 로컬 fence:** 제어 소유권을 유지하면서 미확인 상태를 보존하므로 선택한다.

### Transition / validation

1. SOURCE/LOCAL: 새 wire 경로가 필요해지는 첫 구현에서 API Reference·schema·producer/consumer 시험을 함께 추가한다. 기존 `MissionService`와 `ActionStore`를 실제 route/runner에서 호출하는지 확인한다. 중복 키, 오래된 observation, 좌표 변환, 권한, generation/expiry, 감사 장애와 두 stop 경로의 차이, driver 접수 직후 crash를 실패 주입으로 검증한다.
2. ROS-SIM: 같은 장치에서 navigation/Mission/직접 조작 claim 경합, stop과 goal의 교차 순서, 통신 단절·늦은 ACK·재시작·그리퍼 보유 불명·목표 증거 누락을 재현한다. 시뮬레이션은 물리 E-stop 증거가 아니다.
3. ARTIFACT/DEVICE/FIELD: 실제 OMX 모델/revision, gripper·driver·ROS 버전과 단일 writer, 설치된 API/owner, 로컬 정지·물리 E-stop 회로, 실제 정지 시간과 물체 낙하/보유, 독립 카메라 결과를 분리 수용한다. 이 증거 전에는 OMX 조작 capability와 자동 모델 dispatch를 켜지 않는다.

**Consequences:** 모델·사람·규칙의 제안을 같은 Mission 입구에서 비교할 수 있다. Site Fleet의 중앙 원장은 승인과 공유 자원을 소유하고 장치 로컬 owner는 최종 ROS 명령을 소유한다. D-327/D-328의 넓은 Proposed 범위와 D-331의 provider-only 수용은 유지되며, 이 ADR은 첫 작업의 연결·정지·증거 계약을 좁혀 결정한다.

**References:** [D-18](D-18-rosy-core.md), [D-307](D-307-final-action-outcome-and-stop-readback-evidence.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md), [D-326](D-326-agent-loop-boundary.md), [D-327](D-327-semantic-manipulation-actions-and-device-adapters.md), [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-331](D-331-gemini-er2-proposal-adapter.md), [ER 2 공식 개요](https://ai.google.dev/gemini-api/docs/robotics-overview), [ER 2 모델 카드](https://deepmind.google/models/model-cards/gemini-robotics-er-2/).

### Implementation note: SQLite response growth (2026-09-29)

Fleet's safety-relevant SQLite journals use WAL with `synchronous=FULL`, foreign
keys, and a 5-second busy timeout on every connection. WAL allows readers to
coexist with a writer; it does not make SQLite a multi-writer database. Keep
SQLite's default auto-checkpoint and FULL synchronization until representative
Linux/device measurements justify a change without weakening Action, stop,
Mission, or audit durability.

Mission snapshots return at most 50 recent events and expose
`history_truncated`; complete retained history is read through cursor pages.
Each event detail is finite JSON capped at 16 KiB both when written and at the
typed response boundary, so a bounded event count also has a payload-size cap.
The snapshot separately obtains the latest events for its active Action attempt
using the `(mission_id, action_id, attempt_id, event_id)` index. Query-plan tests
guard the ordered reads against full-history scans and temporary sorting. These
changes bound snapshot materialization, but do not claim target-device latency,
checkpoint behavior, or physical-control performance.
