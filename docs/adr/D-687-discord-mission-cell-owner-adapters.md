# D-687 — Discord Mission·Cell Job의 기존 소유자 연결

**Status:** Accepted (source design only, 2026-10-12). D-680의 후속이며 운영 활성화와 장치 수용은 별도다.

## Decision

Console는 현재 사용자의 기존 Mission 후보를 선택하여 관측·selector metadata를 재사용할 수 있다. 서버는 source proposal의 현재 author와 workcell/instance를 확인하고 기존 resolver로 다시 검증한다. 새 관측을 꾸미거나 다른 사용자의 후보를 복사하지 않는다. 직접 candidate metadata 입력은 기존 API 호출자에게 유지하며 source ID와 동시에 사용할 수 없다.

Discord 요청의 기명 소유자가 Console에서 기존 Mission candidate 또는 Cell app document/digest를 확인한다. Fleet는 고정 `discord-{request_id}` key로 기존 proposal 생성·resolve 함수를 호출한다. 일반 Mission의 author는 현재 기명 요청자, Cell Job author는 기존 설정된 service principal이다. observation, recipe, cell, compiler, capability 및 resolution 검증을 그대로 사용하며 Bot/사용자 입력으로 principal을 지정하지 않는다.

Proposal 생성·resolve는 실행 권한이 없다. 성공한 현재 proposal을 기존 tasks DB의 요청 관계에 연결한 후에만 별도의 Console 명시 승인을 허용한다. 관계 예약은 현재 owner/hash/revision을 트랜잭션 안에서 재검사한다. 그 사이 검토가 바뀌면 관계 연결은 거절하며, 생성된 proposal은 실행 전 상태로 남는다. 원래 key에 다른 candidate를 재사용할 수 없다. 같은 연결의 재시도는 같은 원장 ID를 반환한다.

Admission은 관계가 연결된 현재 기명 소유자를 다시 확인하고 기존 Mission admit 함수만 호출한다. 현재 resolver의 evidence/capability 재검사, dispatch generation/fence, resource claim 및 Cell approver≠service author 규칙을 유지한다. 연결된 관계는 다른 후보로 편집할 수 없다. Bot은 operator나 approver가 되지 않는다.

결과는 기존 Mission/Cell Job 원장에서 읽으며 PROPOSED, READY, RUNNING, ACTION_SUCCEEDED, GOAL_CONFIRMED, HOLD를 구분한다. ACTION_SUCCEEDED를 목표 완료로 표현하지 않는다. 원래 메시지의 현재 mapping과 고정 목적지를 회신 생성·claim·발송 전에 재검사하고, 권한 철회는 SUPERSEDED로 기록한다.

## Verification and rollout

Source 복사는 일반 PROPOSED/RESOLVED proposal만 허용한다. source lineage 또는 supersedes metadata가 있는 feedback/replan 후보와 REJECTED/UNRESOLVED/RESOLVING 원본은 409로 거절한다. 원래 attempt·generation·event fence와 successor 책임을 일반 Mission 복사로 우회하지 않는다.

기존 실제 proposal/resolve/admit 경로, 원장 설치와 누락, 다른 owner/service author, hash/revision 변경, 같은 key 충돌, 중복 연결과 실제 rollback을 원격 시험한다. Console는 기존 확인창과 인증 lifetime을 사용한다. 새 source/size 독립 검토, 최신 main 착지, CI·서명 배포, 실제 Discord 요청/회신 readback이 남는다. 위험 사건 어댑터와 실제 FIELD는 이 ADR의 구현 완료로 승격하지 않는다.
