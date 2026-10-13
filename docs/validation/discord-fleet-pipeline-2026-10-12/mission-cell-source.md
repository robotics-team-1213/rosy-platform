# Discord Mission·Cell Job source 증거

Branch `feat/discord-workflow`, source `aa10b5080`. D-687/API v1.213.

기존 proposal/resolve/Cell app document compiler/admit owner 함수를 그대로 재사용한다. 일반 Mission author는 기명 요청자, Cell author는 설정된 서비스이며 approver는 기명 operator다. 현재 원문 hash/revision/mapping과 고정 `discord-{request_id}` key를 검사하여 실행 전 proposal을 관계에 먼저 연결한다. 별도 admission은 기존 resolver의 current evidence/capability, generation/fence/claims와 독립 승인 규칙을 유지한다. 새 writer, rearm, 모델 호출, dispatch 활성화는 없다.

## 원격 증거

- `cb70ac390` RED6: 미구현 prepare/admit 경로404. Model PC, 기존 X session `logs/workflow-missions-red/run-1.txt`.
- `e76f0cf75` 첫 영향군19 NEW는 신규 source의 실패였다. 관계 view가 DB row에 없는 원문 hash를 읽었고, prepare 트랜잭션 안의 ProposalStore.get이 별도 expiry DELETE writer를 열어 self-lock을 일으켰다. 독립 검토도 nested writer를 blocker로 확인했다. 기존 실패 allowlist는 변경하지 않았다.
- `cdde4a0ca`는 같은 트랜잭션 connection의 expiry/provenance read를 ProposalStore에 추가하고 view projection을 수정했다. 두 탭의 resolve 중 HOLD 변경은409이며 Mission은 PROPOSED, claims는 비어 있다. 현재 mapping 역할 철회는 admission403이다. GREEN2의 남은2 NEW는 아직 없는 Mission/Cell result observer였다.
- `aa10b5080` GREEN3: 원격 Model PC101 PASS, exit0, known_failures NEW0. 기존 Task/Mission/Cell app/Cell Job과 request/reply 회귀 포함. `logs/workflow-missions-green-3/run-1.txt`; 자원 floor 충족.
- `1a26cef6c` 최종 영향군112 PASS/NEW0: proposal가 관계 예약 전에 만료되는 경우409, LINKED outbox 실제 INSERT trigger ABORT의 관계/회신 rollback, 오래된 generation 거절을 보강했다. 기존 Task/owner/Cell 규약과 공개 API version pins도 포함한다. `logs/workflow-missions-final/run-1.txt`; 모델·AI PC가 메모리 floor 아래여서 마지막 선택지 Site PC에서 실행했으며 Site 자원 floor는 충족했다. 이는 source/host 시험이며 실제 장치·현장 수용이 아니다.

결과 observer는 기존 원장과 고정 work kind로 상태를 읽고, 상태마다 한 번 intent를 예약한다. ACTION_SUCCEEDED는 장치 동작 완료·목표 확인 대기로 표시하며 GOAL_CONFIRMED와 구분한다. 권한 철회 뒤 새 상태는 SUPERSEDED/빈 content로 기록하고 전송하지 않는다. 실제 전달 시험이 아니라 SQLite/source fixture 증거다.

## 남은 gate

독립 읽기 전용 검토는 `aa10b5080` 및 동일 AST app formatting/DTO re-export의 source/Safety를 승인했다. nested writer blocker는 해소됐다. 실측 Fleet54,370 = Fleet35,654 + Decision1,658 + Console16,813 + Discord245이며 기존54,214+150을6줄 초과하므로 현재 구조 PASS는 아니다. UI/위험 adapter 완료 뒤 최종 제한 재판정을 받아야 하며 +150·파일 상한·hard tier·기존 추출 의무를 완화하지 않는다. app906/TaskStore1035, proposal_store797(기존730+150 내,800 초과시 seam 검토 의무), schemas1385/1389를 보존한다.

최종 source/Safety/size 재검토, Console Mission·Cell 준비/승인 UI, 위험 사건 연결, 최신 main 착지, CI·서명 배포, 실제 Discord 요청·회신 readback은 미완료다. 운영 전송·provider·로봇/OMX 명령을 실행하지 않았다. 기존 전체 모듈 last_verified를 부분 시험으로 갱신하지 않았다.
