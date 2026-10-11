# Discord와 Fleet 실제 연동 완료 계획

2026-10-12. Branch: `feat/discord-workflow`.

사용자가 완전한 연동을 목표로 다시 설정하도록 요청했다. 접수와 로그인만으로 완료하지 않는다. D-669 설계, D-671 접수, D-675 Gateway를 기반으로 기존 Fleet 소유자에 연결한다. 모델 CLI와 broker는 별도 세션이 소유하며 이 브랜치에서 구현하지 않는다.

## 완료 기준

1. 지정 채널에서 기명 사용자의 Bot mention 원문을 실제로 수신하고 재시작 후에도 같은 요청을 조회한다.
2. 요청 원문과 hash, 요청자, 구조화 후보 또는 보류 사유, 기존 작업 ID, 확인자를 연결한다. 모호한 요청은 사람에게 확인하며 모델 HOLD를 우회하지 않는다.
3. Fleet Console의 기존 승인 규약을 거쳐 기존 Task/Mission/Cell Job 소유자가 처리한다. 일반 Mission의 owner와 Cell Job의 독립 approver 규칙을 보존한다.
4. 위험 사건은 현재 사건과 revision에 묶인 기존 인수·정지/취소 규약에 연결한다. 자연어 위험 표현으로 해제·rearm·이동 권한을 만들지 않는다.
5. 처리 결과를 원래 Discord 요청에 회신하고 실제 수신을 확인한다. 접수, 승인, 장치 수락, 동작 결과, 목표 증거, UNKNOWN을 구분한다.
6. 실제 배포 SHA, 비공개 설정, 기명 로그인, 원장 readback, Discord 메시지 ID와 회신 상태를 증거로 남긴다. 로봇 오프라인과 FIELD 미확인은 별도 gate로 유지한다.

## 실행 순서

- **진행 중 — 기반 착지:** D-671/D-675 최신 main 통합 회귀를 완료한다. 현재 수신·원장·Console 원문 조회와 source image build가 구현됐다. 운영 수신은 아직 적용 전이다.
- **다음 — 후보와 확인:** 관련 ADR/API/DTO를 먼저 확정한다. 기존 Task 제출과 Mission/Cell Job 승인 호출자를 재사용하고 요청→작업 관계를 기존 tasks DB에 저장한다. 동일 요청·내용으로 재승인이 실행을 중복하지 않는지, 다른 owner·수정된 원문·권한 철회·불명 제출을 검증한다.
- **다음 — 결과 회신:** 기존 알림의 durable outbox와 전송 결과 의미를 검토해 재사용 가능한 경계를 선택한다. 고정 guild/channel과 원래 message reference만 사용하고 mentions를 차단한다. timeout/5xx와 재시작 후 SENDING은 UNKNOWN이며 맹목 재전송하지 않는다. Bot 자기 회신은 intake에서 제외한다.
- **다음 — 위험 대응:** 현재 line incident owner의 사건 조회·인수·정지 계약부터 연결한다. 다른 종류의 위험은 해당 소유자가 있을 때만 연결한다. source/fake 시험과 실제 운영 검증을 분리한다.
- **마지막 — 배포와 실제 경로:** 사용자 승인 범위와 저장소의 push·CI·signed candidate·updater 규칙을 확인한다. 검토 가능한 구현과 local FF를 먼저 끝내고 필요한 명시 승인은 마지막 단계에서 받는다. 비공개 token/config를 Fleet에만 주입한 뒤 실제 대화→Console 확인→원장→회신을 검증한다.

## 검증과 책임

### 다음 어댑터의 기존 계약 확인

- 일반 Mission: 기존 proposal/resolve/admit 경로의 원래 기명 proposer, observation/evidence provenance, resource/revision 검증을 유지한다. Discord 원문으로 관측 근거를 만들어내거나 다른 사용자의 Mission ID를 연결하지 않는다.
- Cell Job: 기존 cell-app/proposals는 요청한 operator를 감사하되 설정된 service principal이 proposal을 소유한다. 승인자는 그 service author와 달라야 한다. 요청자와 service author를 같은 사용자로 바꾸지 않고 원래 request key와 기존 승인 결과의 provenance를 확인한다.
- 위험 사건: 기존 line-stuck/claim의 현재 open case, judgment revision, freshness와 기명 인수 계약을 재사용한다. revision 없는 resolver pause를 durable 사건 인수 성공으로 표시하지 않는다. 정지/취소는 해당 기존 소유자의 별도 확인 경로를 사용한다.
- 결과 읽기는 해당 기존 원장에 남기고 Discord는 검증된 관계와 고정 상태 회신만 소유한다. 새로운 Mission/Cell/incident 추가는 현재 Task source 승인과 크기 재판정에 포함되지 않으므로 별도 독립 검토를 받는다.

제품 변경은 이 worktree에서만 한다. 로그와 임시 파일은 X의 기존 discord-fleet-pipeline 세션에 둔다. committed HEAD의 pytest는 원격 PC에서만 실행하고 각 로그를 known_failures와 비교한다. 승인·중복·UNKNOWN·권한·원문 XSS·설치/이미지 closure와 변경된 Console의 실제 browser 경로를 확인한다. safety 경계 변경은 독립 검토를 거친다.

모델 provider 수용과 실제 로봇 주행은 Discord 소스 검증으로 승격하지 않는다. 기명 사용자 요청을 Bot 공용 operator나 임의 principal로 대체하지 않는다. CORE와 OMX의 최종 장치 권한 및 기존 Fleet transaction/fence를 유지한다.

## 진행 기록

- D-687/API1.213의 Mission·Cell prepare/admit backend와 기존 원장 결과 observer를 구현했다. source `aa10b5080` 관련101 PASS/NEW0, Model PC floor 충족. 실제 기존 owner/독립 승인, prepare 중 다른 탭 HOLD, 권한 철회와 상태별 회신 intent를 포함한다. 초기 새 view/self-lock 실패를 고쳤고 기존 실패 목록은 바꾸지 않았다. [증거](../validation/discord-fleet-pipeline-2026-10-12/mission-cell-source.md). Console 준비·승인 UI, 위험 사건 연결과 운영 왕복은 여전히 후속이다.

- D-680 source design과 원래 메시지 회신 transport를 작성했다. 접수 회신 intent와 원문 receipt의 atomic commit, bounded retry/UNKNOWN/fence, 전송 전 권한·목적지 재검사와 기본 OFF worker를 구현했다.
- Source `4bb95bc516` 원격 67 PASS/NEW 0. 변경 파일 style 0 errors. [증거](../validation/discord-fleet-pipeline-2026-10-12/reply-source.md).
- 다음 작업: 실제 opt-in lifespan 전송 경로 시험, Console 확인과 기존 작업 관계·처리 결과 회신, 위험 사건 어댑터. 운영 배포와 실제 대화 왕복 수용은 미완료다.
- 기명 Console 검토와 기존 주행 Task 관계 원장/API v1.211을 구현했다. source `f26b367324` 원격 관련67 PASS/NEW 0. [증거](../validation/discord-fleet-pipeline-2026-10-12/workflow-source.md). 이는 backend 경계이며 Console 확인·제출 UI와 실제 전체 경로는 다음 단계다.
- Console 확인·후보 저장·기존 goal 명시 확인·Task 관계 저장과 검토/Task 결과 회신 intent를 구현했다. Source `3861935d44` 관련192 PASS/NEW0, 실제 Chromium `b45e54d05a` 6 PASS/NEW0. UI는 별도 owner이며 기존 confirmedAction/current safety gate/고정 idempotency key를 재사용한다. 검토와 회신 예약은 atomic이고 UNKNOWN을 완료로 바꾸지 않는다. 기존 단독 Gateway 착지는 main 유입 경로 변수명 secret-scan 오거절로 중단됐으며 최소 이름 수정과 관련 회귀를 C에 통합했다. 실제 배포·전송·장치 명령 없음.
- 독립 검토의 두 blocker를 보강했다: 현재 원문 mapping을 회신 생성/claim/발송 전에 다시 확인하고, API1.212 submit에서 기존 Task 생성과 현재 검토 검증/관계 예약을 같은 트랜잭션으로 묶었다. 두 단계 goal→link UI는 폐기했다. Owner 관련45 PASS/NEW0, 두 탭 review race와 Task 재시도49 PASS/NEW0; source `49490991a8` 최종 영향군/Chromium/재검토는 진행 중이다. 제한 크기 재판정, Mission/Cell Job/위험 사건 adapter, 실제 opt-in 통합, local FF/CI/서명 배포/왕복을 이어서 처리한다.
