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

- **Source 검증 완료 — 접수·후보·확인:** 기명 immutable 접수와 기존 Task/Mission/Cell owner adapter 및 Console를 구현했다. same-DB 관계·독립 승인·기존 evidence/fence를 유지하며 Mission feedback source 복사 우회를 거절한다. 운영 수신과 최신 통합 착지는 후속이다.
- **Source 검증 완료 — 결과 회신:** 고정 guild/channel과 원래 message reference, mentions 차단, current mapping, durable opt-in worker와 기존 작업 결과 observer를 구현했다. timeout/5xx와 재시작 SENDING은 UNKNOWN이며 맹목 재전송하지 않는다. 실제 채널 왕복은 후속이다.
- **Source 검증 완료 — 위험 대응:** 현재 line incident의 기명 인수와 원문 관계·회신을 기존 owner의 같은 transaction으로 연결했다. Console는 현재 사건·judgment를 별도 확인하며 기존 조치 화면으로 연결한다. 정지·취소/재개는 기존 소유자의 확인과 장치 admission을 유지한다. 서버90/Chromium10/설치3 증거는 운영 수용과 구분한다.
- **Source 완료 — 최종 구조·착지:** Fleet의 모든 owner adapter를 독립 제한 재판정했으며 파일 상한·+150·이전 추출 의무를 유지한다. 최초 core_common 부모10031 판정 누락과 이후 신규 실패를 수정했으며 기존 실패로 등록하지 않았다. 최신 계정·Cam 계약을 함께 보존한 API v1.216 통합본 `d5cfa0b630`을 local main에 FF했다. 최종 관련 원격457건/NEW0, Node318건/lint0errors이며 배포·실제 왕복은 다음 gate다.
- **다음 — 배포와 실제 경로:** 사용자 승인 범위와 저장소의 push·CI·signed candidate·updater 규칙을 적용한다. 검토 가능한 구현과 local FF를 먼저 끝내고 필요한 명시 승인은 마지막 단계에서 받는다. 비공개 token/config를 Fleet에만 주입한 뒤 실제 대화→Console 확인→원장→회신과 재시작 durable readback을 검증한다.

## 검증과 책임

### 공통 계약의 다음 분리 의무

core_common 부모10,031은 main4dc522986의9,888 대비 Discord canonical DTO136줄과 schema re-export7줄만 추가된 결과다. protocol5,298/domain1,203/기타3,504/root26이며 DB·transport·provider·ROS·process·actuation 권한을 추가하지 않았다. strict 계약은 이미 protocol/channel_requests.py에 분리되어 있다. safety_structure_review의 최초 제한 판정은 기존 package10,000/+150·모든 파일 상한/HARD_TIER·schemas1389 zero-growth 및 기존 protocol/schema 추출 의무를 유지한다. 새 SIZE_UNITS나 scan 제외를 만들지 않는다.

다음 protocol family 확장 전에 실제 core_common/protocol 계약 subpackage 책임 분리를 독립 검토한다. 같은 변경에서 설치 패키지 closure와 기존 소비자·의존 방향·단일 canonical schema facade/re-export identity를 검증하고 부모와 새 unit의 전체 실측을 함께 기록한다. 현재 parent 판정만 늘려 계속 확장하거나 DTO를 runtime 소유자에 옮겨 leaf 계약을 약화시키지 않는다.

### 다음 어댑터의 기존 계약 확인

- 일반 Mission: 기존 proposal/resolve/admit 경로의 원래 기명 proposer, observation/evidence provenance, resource/revision 검증을 유지한다. Discord 원문으로 관측 근거를 만들어내거나 다른 사용자의 Mission ID를 연결하지 않는다.
- Cell Job: 기존 cell-app/proposals는 요청한 operator를 감사하되 설정된 service principal이 proposal을 소유한다. 승인자는 그 service author와 달라야 한다. 요청자와 service author를 같은 사용자로 바꾸지 않고 원래 request key와 기존 승인 결과의 provenance를 확인한다.
- 위험 사건: 기존 line-stuck/claim의 현재 open case, judgment revision, freshness와 기명 인수 계약을 재사용한다. revision 없는 resolver pause를 durable 사건 인수 성공으로 표시하지 않는다. 정지/취소는 해당 기존 소유자의 별도 확인 경로를 사용한다.
- 결과 읽기는 해당 기존 원장에 남기고 Discord는 검증된 관계와 고정 상태 회신만 소유한다. 새로운 Mission/Cell/incident 추가는 현재 Task source 승인과 크기 재판정에 포함되지 않으므로 별도 독립 검토를 받는다.

제품 변경은 이 worktree에서만 한다. 로그와 임시 파일은 X의 기존 discord-fleet-pipeline 세션에 둔다. committed HEAD의 pytest는 원격 PC에서만 실행하고 각 로그를 known_failures와 비교한다. 승인·중복·UNKNOWN·권한·원문 XSS·설치/이미지 closure와 변경된 Console의 실제 browser 경로를 확인한다. safety 경계 변경은 독립 검토를 거친다.

모델 provider 수용과 실제 로봇 주행은 Discord 소스 검증으로 승격하지 않는다. 기명 사용자 요청을 Bot 공용 operator나 임의 principal로 대체하지 않는다. CORE와 OMX의 최종 장치 권한 및 기존 Fleet transaction/fence를 유지한다.

## 진행 기록

- **운영 왕복 확인:** 수정본 `04baa6e258`의 CI·후보 빌드·서명과 기존 updater 설치를 확인했다. 실제 Bot 멘션 원문이 기명 Fleet 접수로 남고, Console에서 오프라인 HOLD를 재검토한 revision2의 회신이 원래 Discord 메시지에 SENT/attempts1로 도착했다. 이후 Fleet 재시작에서도 요청·검토·메시지 ID와 시도 횟수가 유지됐고 중복 회신은 없었다. 기존 첫 접수/검토의 TLS 실패 이력은 보존했다. [TLS 원인·수정·운영 증거](../validation/discord-fleet-pipeline-2026-10-12/public-ca.md). 실제 로봇 주행·팔 작업·위험 사건 개입·모델 활성화는 이 오프라인 HOLD 왕복과 별도 수용 범위다.

- 사건 Console sourceed7eba9644 실제 Chromium10 PASS/NEW0. 기존 native claim의 잘못된 scope.listener 호출을 guard로 고쳐 현재 판단 사건 표시를 복구했다. wheel/sdist/source COPY closure3 PASS/NEW0, Fleet54,852 제한 독립 판정은 기록했다. 최종 크기/API군94 PASS/NEW1은 core_common10031 첫 부모 판정 누락이며 구조 전체 PASS로 표시하지 않는다. [증거](../validation/discord-fleet-pipeline-2026-10-12/incident-console.md). 동일 오류 독립 재확인과 공통 계약 책임 판정을 마치고 최종 착지·운영 왕복으로 진행한다.

- D-693/API1.214 현재 사건 인수를 기존 named claim 소유자에 연결했다. 실제 기존 owner/SQLite 90 PASS/NEW0, source 독립 검토 승인. 같은 트랜잭션의 claim·원문 관계·회신 rollback과 stale/closed/다른 담당/권한 변경, 원래 사건 CLOSED intent를 확인했다. [증거](../validation/discord-fleet-pipeline-2026-10-12/incident-source.md). Console 사건 선택·명시 확인 UI와 Chromium을 이어서 구현한다. 구조 parent NOTPASS/최종 재판정, 설치·최신 main 착지·배포·실제 왕복은 남아 있다.

- Mission·Cell Console를 기존 owner 경로에 연결했다. 실제 Chromium 작업 화면8 PASS와 Cell 전체53 PASS, source lineage 거절 포함52 PASS/NEW0. 피드백 후보의 source fence가 복사로 소실되는 독립 검토 blocker는 일반 후보만 허용하여 해결했다. 최신 main4dc522986 통합 source48d3aa835f의 실제 owner/GLM 영향109 PASS/NEW0, lint0errors. [증거](../validation/discord-fleet-pipeline-2026-10-12/mission-cell-console.md). 구조 최종 재판정은 미완료다. D-693 현재 사건 인수의 동일 트랜잭션 관계·회신 계약을 작성했으며 구현→시험→최종 검토→local FF→운영 왕복을 계속한다.

- D-687/API1.213의 Mission·Cell prepare/admit backend와 기존 원장 결과 observer를 구현했다. source `aa10b5080` 관련101 PASS/NEW0, Model PC floor 충족. 실제 기존 owner/독립 승인, prepare 중 다른 탭 HOLD, 권한 철회와 상태별 회신 intent를 포함한다. 초기 새 view/self-lock 실패를 고쳤고 기존 실패 목록은 바꾸지 않았다. [증거](../validation/discord-fleet-pipeline-2026-10-12/mission-cell-source.md). Console 준비·승인 UI, 위험 사건 연결과 운영 왕복은 여전히 후속이다.

- D-680 source design과 원래 메시지 회신 transport를 작성했다. 접수 회신 intent와 원문 receipt의 atomic commit, bounded retry/UNKNOWN/fence, 전송 전 권한·목적지 재검사와 기본 OFF worker를 구현했다.
- Source `4bb95bc516` 원격 67 PASS/NEW 0. 변경 파일 style 0 errors. [증거](../validation/discord-fleet-pipeline-2026-10-12/reply-source.md).
- 다음 작업: 실제 opt-in lifespan 전송 경로 시험, Console 확인과 기존 작업 관계·처리 결과 회신, 위험 사건 어댑터. 운영 배포와 실제 대화 왕복 수용은 미완료다.
- 기명 Console 검토와 기존 주행 Task 관계 원장/API v1.211을 구현했다. source `f26b367324` 원격 관련67 PASS/NEW 0. [증거](../validation/discord-fleet-pipeline-2026-10-12/workflow-source.md). 이는 backend 경계이며 Console 확인·제출 UI와 실제 전체 경로는 다음 단계다.
- Console 확인·후보 저장·기존 goal 명시 확인·Task 관계 저장과 검토/Task 결과 회신 intent를 구현했다. Source `3861935d44` 관련192 PASS/NEW0, 실제 Chromium `b45e54d05a` 6 PASS/NEW0. UI는 별도 owner이며 기존 confirmedAction/current safety gate/고정 idempotency key를 재사용한다. 검토와 회신 예약은 atomic이고 UNKNOWN을 완료로 바꾸지 않는다. 기존 단독 Gateway 착지는 main 유입 경로 변수명 secret-scan 오거절로 중단됐으며 최소 이름 수정과 관련 회귀를 C에 통합했다. 실제 배포·전송·장치 명령 없음.
- 독립 검토의 두 blocker를 보강했다: 현재 원문 mapping을 회신 생성/claim/발송 전에 다시 확인하고, API1.212 submit에서 기존 Task 생성과 현재 검토 검증/관계 예약을 같은 트랜잭션으로 묶었다. 두 단계 goal→link UI는 폐기했다. Owner 관련45 PASS/NEW0, 두 탭 review race와 Task 재시도49 PASS/NEW0; source `49490991a8` 최종 영향군/Chromium/재검토는 진행 중이다. 제한 크기 재판정, Mission/Cell Job/위험 사건 adapter, 실제 opt-in 통합, local FF/CI/서명 배포/왕복을 이어서 처리한다.
