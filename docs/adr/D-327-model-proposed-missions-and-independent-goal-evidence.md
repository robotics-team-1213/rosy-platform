## D-327 모델 제안 Mission과 독립 목표 증거를 분리한다

**Status:** Proposed (2026-09-29). D-308의 Intent/Fleet/Device Action 소유권과 D-307의 Action 결과/물리 정지 구분을 다장치 작업에 구체화한다. 새 Mission API, 자동 모델 dispatch, OMX/Pinky 복합 운영, Isaac Sim 또는 DEVICE/FIELD 수용을 승인하지 않는다.

### Context

[사용자 제공 ER 2·Isaac Sim 분석](../plans/2026-09-29-er2-isaac-sim-architecture-assessment.md)은 모델이 작업 분해·다음 도구 선택·실패 뒤 경로 변경을 도왔으나, 한 예시에서 물체가 남았는데도 완료를 선언했다고 보고한다. 영상의 수치와 실험 장면은 원문 보고이며 독립 검증 전이다. 이 사례가 드러내는 구조 문제는 모델이 다음 행동을 고르는 것, 물리 Action이 종료되는 것, 사이트 목표가 충족되는 것이 서로 다른 사실이라는 점이다. Google의 ER 2는 사용자 정의 함수 호출과 영상 진행도 분류를 제공하지만, 공식 조작 함수 예시는 mock이며 진행도는 물리 목표의 권위 있는 판정이 아니다.

ROSY의 현행 Fleet은 단일 Pinky navigation task/attempt를 영속화할 수 있다. `/api/fleet/do`의 다중 `steps`는 순차 REST 호출이며, 다장치 의존 관계·인계·병렬 join·goal predicate를 가진 Mission 실행기가 아니다. OMX 운영 Action API도 아직 없다. 따라서 모델의 tool 호출을 이 경로에 바로 연결하면 일부 동작이 이미 실행된 뒤 응답만 실패하거나, 모델의 완료 문구를 실제 완료로 승격할 수 있다.

### Decision

1. **모델 출력의 역할을 Plan/Next-Step 후보로 한정한다.** ER 2, 다른 모델, 사람, 규칙 엔진은 관측 revision에 묶인 목표·대상·제약·제안 단계를 낼 수 있다. 후보에는 장치 실행권이 없다. Fleet 입구가 새로 인증한 principal, capability/version, 작업대/로봇 identity, 관측·구성 신선도, 예상 물리 효과, 승인된 정책과 기한을 평가해 수용·명확화·거절·HOLD를 결정한다. 모델이 생성한 actor, confidence, tool 결과 문자열은 권한으로 사용하지 않는다.
2. **Fleet이 Mission의 영속 실행과 의존 관계를 소유한다.** 승인된 Mission은 목표 predicate, Step DAG, 장치/공유 구역 예약, `mission_id`/`step_id`/`action_id`/`attempt_id`, 재시도 한도와 취소·재조회 규칙을 기록한다. 서로 독립인 장치 Step만 병렬 실행하고, 인계 장벽은 권위 있는 선행 결과와 실제 적재/보유 관측을 확인할 때만 연다. 모델 세션 종료·재연결·중복 tool call은 이미 제출된 물리 Step을 재실행하지 않는다. 이 결정은 현행 `/api/fleet/do`의 `steps`에 Mission 의미를 부여하지 않는다.
3. **장치 로컬 owner가 Action과 즉시 정지를 소유한다.** Pinky CORE는 주행 최종 명령, 검증을 마친 OMX 로컬 owner는 팔/그리퍼 명령을 소유한다. 장치 Action은 수락, 실행, 취소 요청, 최종 결과와 ROS/driver readback을 독립 기록한다. 대상 이동·충돌·상태 stale·통신 상실에 대한 빠른 중단은 로컬 감시와 정지 경로가 맡는다. 모델이 뒤늦게 보낸 변화 신호는 재관찰·재계획 후보가 될 수 있으나 안전 정지 latency 보증이 아니다. 일반 cancel, 안전 stop, E-stop 및 물리 정지 확인은 분리한다.
4. **목표 성공은 사전에 정의한 predicate와 독립 증거로 판정한다.** Fleet은 Mission 수락 전에 성공 조건과 필요한 출처를 기록한다. 예를 들어 블록 옮기기는 장치 `PICK_PLACE` 최종 결과만이 아니라 목적지의 물체 identity/영역 관측, 그리퍼 해제, 필요한 팔 후퇴를 확인한다. 여러 로봇 인계에는 적재·고정·출발 전 팔 후퇴·도착 후 적재 유지·하역 확인을 각 Step의 장벽으로 둔다. 모델의 “완료” 문구와 모델 영상 진행도는 보조 관측이며 단독 성공 증거가 아니다. 독립 센서/장치 readback이 없거나 서로 충돌하면 목표는 미확인 상태로 남기고 새 관측 또는 운영자 조정을 요구한다. 장치 Action 결과 `UNKNOWN`, 목표 미충족, 물리 정지 미확인은 서로 다른 축이다.
5. **재계획은 기존 물리 효과를 확인한 뒤에만 새 시도로 만든다.** 실패/장애가 오면 Fleet은 해당 attempt의 최종 이벤트와 정지 readback, 물체의 현재 위치·보유자, 예약 자원을 다시 확인한다. 모델의 대체 순서는 신규 후보이며 기존 Step을 덮어쓰지 않는다. 물체가 이미 파지되거나 이동했을 가능성이 있으면 자동 재시도하지 않고 HOLD한다. 새로운 attempt를 열 때 원래 목표·이전 실패·새 관측·승인 주체를 연결한다.
6. **모델 tool 프로토콜과 사이트 비동기 실행을 분리한다.** Google streaming에서 물리 tool은 `BLOCKING`이고 대응 결과를 반환해야 한다. 이는 사이트의 다장치 병렬 scheduler가 아니다. 모델에는 실행권 없는 `propose_plan`/`request_observation`/`get_mission_status` 성격의 경계를 우선 제공하고, 실제 병렬/의존 Step은 Fleet이 영속 실행한다. 장치 물리 tool을 나중에 직접 노출할 경우에도 장치 최종 결과를 기다리는 blocking 의미, timeout·중복·단절 처리, 제한된 capability와 독립 안전 경계를 별도 검증한다.

### Alternatives

- **모델 세션을 Mission scheduler와 성공 판정기로 사용:** 재연결·응답 누락·물리 효과·잘못된 완료 선언을 영속 조정할 수 없어 채택하지 않는다.
- **각 장치 API가 사이트 목표까지 판정:** 장치 간 의존과 최종 목적지 확인이 분산되므로 채택하지 않는다.
- **모든 모델 신호를 버리고 고정 workflow만 사용:** 단기 고정 작업에는 유효하지만 새로운 장면·실패의 후보 생성 범위를 제한한다. 초기 baseline으로 유지하고 모델 도입의 비교 기준으로 사용한다.
- **Fleet 원장 + 로컬 Action + 독립 목표 판정:** D-308/D-326의 소유권과 맞고 단계별 증거를 남길 수 있어 제안한다.

### Transition / validation

1. SOURCE/LOCAL: 모델 없는 고정 `PICK_PLACE`의 목표 predicate, Action 결과와 불일치하는 목적지 관측을 먼저 재현한다. 현재 Fleet navigation attempt 연결을 기준으로 늦은/중복 이벤트, 일부 Step 실행 뒤 HTTP 오류, 재시작, 직접 조작 충돌을 시험한다.
2. ROS-SIM: 한 장치 정상·grasp 실패·이동한 대상·거짓 완료를 거친 다음 두 장치 병렬 join과 적재→운반→하역 의존 장벽을 시험한다. 별도 진행 중인 D-322의 Isaac 형상/import 초안은 조작 시뮬레이션 수용을 뜻하지 않는다. 영상 원문의 시간 수치를 ROSY의 허용 정지 한계로 복사하지 않는다.
3. ARTIFACT/DEVICE/FIELD: 장치별 단일 writer와 로컬 안전 경로, 파지·적재·관절·모터의 실제 readback, 모델 단절과 Fleet 장애 중 정지, 운영자 복구를 따로 측정한다. 물체 추적/센서 독립성과 오탐률, 목표 predicate의 판정 한계도 측정한다. 각 게이트 전에는 자동 dispatch와 OMX 운영 capability를 disabled로 둔다.

**Consequences:** 모델 제안, Fleet Step 수락, 장치 Action 최종 결과, 물리 정지, 사이트 목표 성공의 다섯 사실을 별도 ID와 증거로 추적한다. 새 wire 경로·필드·enum은 D-18에 따라 API Reference와 공유 schema, 생산자·소비자 시험을 한 번에 변경할 때 결정한다. 이 ADR은 D-308/D-307을 대체하지 않는다.

**References:** [사용자 제공 자료와 현재 구조 대조](../plans/2026-09-29-er2-isaac-sim-architecture-assessment.md), [D-18](D-18-rosy-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-70](D-70-fleet.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-305](D-305-platform-boundary-outcome-invariants-and-independent-gates.md), [D-307](D-307-final-action-outcome-and-stop-readback-evidence.md), [D-308](D-308-intent-and-device-action-interpretation-boundary.md), [D-316](D-316-pinky-site-fleet-navigation-result-correlation.md), [D-326](D-326-semantic-manipulation-actions-and-device-adapters.md), [Google ER 2 개요](https://ai.google.dev/gemini-api/docs/robotics-overview), [Google 도구 예시](https://ai.google.dev/gemini-api/docs/robotics-orchestration), [Google streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming), [Google 영상 진행도](https://ai.google.dev/gemini-api/docs/robotics-video-progress).
