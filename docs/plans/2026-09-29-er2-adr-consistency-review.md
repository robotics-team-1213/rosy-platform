# 자율 루프·조작 Action·Mission 결정 정합성 검토

**범위:** D-326(인지 역할과 폐루프 밸브), D-327(의미적 조작), D-328(Mission·목표 증거), `2026-09-29-er2-semantic-actions-mission-implementation.md`. 2026-09-29 소스 기준 문서·계약 검토이며 실행/장치 수용 기록이 아니다.

## 결론

세 결정의 기본 소유권은 양립한다. 모델과 센서는 후보·관측을 제공하고, Fleet은 승인된 Mission/Step 및 목표 증거를 관리하며, 장치 로컬 owner는 Action·ROS/driver 실행과 즉시 정지를 맡는다. 모델의 문장, tool-call 결과, 장치 수락, Action 종료, 물리 정지, 사이트 목표 성공은 별개 사실이다. 단, 아래 경계를 명시하지 않으면 구현 시 우회 경로가 생긴다.

| 검토 항목 | 확인된 간극 | 이 변경의 처분 |
|---|---|---|
| 모델의 도구 권한 | D-326의 Fleet API 소비자 제한과 D-327/D-328의 물리 tool 설명만으로는 모델→장치 직접 호출도 읽힌다. | D-326 본문에서 현 단계의 모델 API를 후보·관측·상태 조회로 한정했다. 미래 물리 tool도 Fleet 인증·원장·장치 발행을 거쳐야 하며 별도 승격 결정이 필요하다. 계획 작업 6에 직접 Device/CORE 호출 거절 시험을 넣었다. |
| 사람 확인과 목표 판정 | D-326의 '원장과 사람 확인'이 모든 정상 성공의 수동 승인을 뜻하는지 불명확했다. | 사전에 승인된 목표 predicate의 독립 증거 판정은 Fleet이 할 수 있다. 사람 확인은 증거 충돌·불명 상태의 조정과 미래 자율 재발의 승인 위치에 적용하며, 후자는 아직 닫혀 있다. |
| 벤더 명칭 | D-326의 공통 역할 이름 원칙과 계획의 `er2_standard.py`가 충돌할 수 있다. | 벤더 전용 adapter 파일명에만 제품 식별자를 허용한다. 공통 계약과 capability에는 넣지 않는다. |
| 기존 Fleet 예약과 새 Mission | 현재 navigation task의 `fleet_robot_reservations` 및 dispatch 루프가 따로 존재한다. Mission 원장을 추가하기만 하면 같은 장치에 이중 발행할 수 있다. | 계획 작업 4·5에서 기존 예약·직접 조작 lease와 새 Mission을 같은 제어권 판정에 묶고 충돌 시험을 선행한다. |
| 정지 뒤 대기 Step | 현재 Fleet 정지는 기존 navigation 대기열만 취소한다. 새 Mission READY/QUEUED Step은 정지 후 재발행될 수 있다. | 계획에서 Mission 대기 Step의 영속 정지 래치와 해제 뒤 재검증을 필수로 했다. 실행 중 정지는 로컬 owner/readback이 확인한다. |
| 사이트 정지 가용성 | D-308은 감사 DB 장애 시 `/api/fleet/estop`이 CORE 호출 전에 `503`을 반환함을 기록한다. | 로컬 정지와 사이트 정지를 같은 가용성으로 주장하지 않는다. 사이트 전체 정지 경로·감사 내구성은 별도 구현과 DEVICE 검증 전 HOLD다. |
| 장치 접수와 원장 기록 사이 장애 | 요청 키만으로는 driver 접수 직후 프로세스 사망 시 물리 재발행을 막지 못한다. | 계획 작업 3에 driver goal ID 재조회·fencing 또는 HOLD, 장애 주입 시험을 추가했다. |

## 여전히 열려 있는 결정과 검증

- D-327/D-328은 **Proposed**다. 실제 API 경로, host placement, 보유 센서, 목표 predicate의 관측 출처, stop latency는 구현·실측으로 정해야 한다. 이 검토는 capability를 활성화하지 않는다.
- 정책 발의의 자동 재계획·재발행은 D-326의 별도 ADR, D-268 처분, Mission/Step 원장, 사람 확인 위치 결정 전까지 닫혀 있다. 모델 없는 고정 작업의 증거 기반 성공 판정과 자동 재발의는 다른 권한이다.
- OMX `PICK_PLACE`의 SOURCE/LOCAL·ROS-SIM 통과는 ARTIFACT/DEVICE/FIELD를 대신하지 않는다. 물체 보유·해제, 드라이버 readback, 물리 정지와 사이트 정지의 독립 가용성을 각각 확인해야 한다.

**근거:** [D-308](../adr/D-308-intent-and-device-action-interpretation-boundary.md), [D-326](../adr/D-326-agent-loop-boundary.md), [D-327](../adr/D-327-semantic-manipulation-actions-and-device-adapters.md), [D-328](../adr/D-328-model-proposed-missions-and-independent-goal-evidence.md), `src/site/fleet/fleet/server/{app,task_service,task_store}.py`, `src/products/omx/adapter/omx_adapter/ros_runtime.py`.
