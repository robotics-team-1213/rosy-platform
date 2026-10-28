## D-895 원래 시도를 보존한 단일 이송 복구 후손

**Status:** Accepted for implementation (2026-10-27, 사용자 설계 승인). 내부 simulation 경로의 구현 결정이다. 공개 API·무인 재시도·장치 활성화·실물 수용·학습 승격은 승인하지 않는다.

### Context

현재 물체 이송은 Fleet이 제안·독립 운영자 승인·claims·단일 attempt·독립 관측을 소유한다(D-856). Action 결과와 task 결과는 별도다. owner FAILED/HOLD/UNKNOWN은 물체 헛잡음·낙하의 정답이 아니며, 종료 후 관측이 부족한 것을 물리 실패로 승격하지 않는다. 기존 표의 PK는 mission_id, 관측 표의 PK는 (mission_id, phase)다. 같은 행을 초기화해 재발행하면 원래 효과·증거·정지 경계를 잃는다.

### Decision

1. 기존 원장의 append-only 이벤트 두 개로 원래 미션과 새 복구 미션을 연결한다. 각 미션은 기존 단일 attempt를 유지한다. root의 복구 자식은 하나이며 자식의 재복구는 거절한다. 기존 attempt·grant·관측을 교체하지 않는다. schema 이관이나 별도 retry DB를 만들지 않는다.
2. 원래 제안자와 그와 다른 이름 있는 운영자가 정확한 부모 grant digest·최신 owner receipt event·최신 task assessment digest·generation·복구 시료에 결속해 새 승인을 요청한다. observer는 제안·승인자가 될 수 없다. 원래 승인만으로 새 시도를 승인하지 않는다.
3. owner FAILED와 부모 HOLD, 또는 owner SUCCEEDED/ACTION_SUCCEEDED와 같은 grant의 최신 task failed 판정만 후보가 된다. owner HOLD·UNKNOWN·취소·진행 중·성공 완료·task unknown은 재시도로 해소하지 않는다. 원래 효과가 불명이면 기존 Action을 대조한다.
4. receipt 수신 뒤 새 독립 World 시료 두 개가 원래 action/attempt·owner journal/session·설치·출처·시각에 결속돼야 한다. 기존 PRE_DISPATCH validator로 물체 source pose, 집게 open/empty, 모든 팔의 정지·구역 비점유를 검증한다. 이 문맥은 복구 전제 확인이며 원래 제출이나 물리 실패 원인 정답이 아니다. 기존 증거보다 새로운 ID·sequence·시각을 요구한다.
5. 동일 BEGIN IMMEDIATE에서 현재 dispatch enabled·부모 epoch/generation·전체 원래 claims·신선한 capabilities를 재검사하고, 새 제안 생성 → 부모 HOLD → 정확한 부모 claims 해제 → 기존 admission으로 자식 claims 확보·승인 → 양방향 계보 이벤트를 기록한다. 최종 시료·capabilities 시각도 재검사한다. 실패하면 전부 rollback한다. 정지나 세대 변경을 새 승인으로 우회하지 않는다.
6. 정확한 재전송은 인증·설치·전체 요청 digest를 확인한 뒤 기존 자식의 현재 상태만 대조한다. 이미 소비한 시료가 오래됐다는 이유로 예산을 초기화하지 않는다. 다른 요청·다른 제안자/승인자·다른 근거로 같은 root를 다시 소비하지 않는다.
7. 내부 dispatcher가 커밋된 READY 자식을 명시적으로 prepare한다. 기존 tick은 attempt 없는 READY 작업을 발견하지 못한다. 자식은 새 action/attempt·새 PRE_DISPATCH 시료·기존 send/owner 검사를 거친다. 준비 실패·정지·불명 결과는 유지하며 새 attempt를 자동 생성하지 않는다. 복구 후손을 가진 부모는 새 observer context 후보에서 제외한다.
8. 검수 export는 원래/자식의 root 계보를 보존한다. 운영자 실행 승인과 학습 라벨 검수 승인은 별도다. 원본 영상·실제 행동·사람 정답이 없는 metadata는 행동 시연으로 승인하지 않는다. 합성 시료와 fake owner를 사용한 호스트 시험은 Gazebo 과제·실물·모델 품질 수용을 대신하지 않는다.

### 기존 경계와의 관계

| 결정 | 유지하는 경계 |
|---|---|
| D-427 | 기존 Fleet work/evidence holder와 기존 SQLite 원장을 사용한다. 새 최상위 폴더·writer 서비스를 만들지 않는다. |
| D-429 | World는 관측을 제공하고 Fleet만 승인·claim·원장 트랜잭션을 소유한다. Decision/모델이 직접 명령하지 않는다. |
| D-430 | CORE/OMX owner의 실행·정지·lease·generation·freshness 검사를 유지한다. 새 최종 writer나 암묵적 재무장을 만들지 않는다. |
| D-330 | 불명 효과의 자동 재발행을 금지한다. 정지·재시작 뒤 원래 효과 대조와 명시적 발행 허가를 우회하지 않는다. |

### Consequences and verification

같은 미션 안에 다중 attempt를 이관하는 대신 명시적 복구 후손으로 경험을 묶는다. 데이터 분할은 root 단위를 유지해야 한다. 현재 공개 observer ingress·화면에는 실패 작업의 복구 시료·승인 경로를 추가하지 않는다. 내부 trusted-host producer와 명시 승인 호출을 통합 검증하고, 공개 활성화는 별도 계약으로 진행한다.

원격 회귀는 중복·동시 요청·재시작·예산 소진·최신 판정·다른 attempt·stale/보유/이동/점유 시료·권한·fence/claims 변경·원장 실패 rollback·새 자식의 기존 제출/완료·계보 export를 확인한다. 원래 grant는 보존된 유효시간으로 읽고, 새 grant만 현재 executor 설정을 사용한다.
