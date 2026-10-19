# 관제 AI 에이전트 구현 계획

> **For agentic workers:** `superpowers:executing-plans`로 첫 조회 버전을 구현했다. 구현 상태와 실제 수용을 구별해 이어간다. 실행 연결·모델 승격·배포를 완료로 처리하지 않는다.

현재: 웹 계약·영속 대화·독립 broker 연결·Console 패널을 구현했고 선택적 브라우저 로컬 음성 adapter를 연결했다. 집중 서버/CLI/계약 회귀 167개, 실제 Chromium 회귀 25개, Node 상태/음성 시험 8개가 `dab629c171`의 소스 또는 같은 JavaScript 소스에서 통과했다. 필수 전체 회귀와 설치 검증은 별도 기록을 본다. 실제 모델-PC 평가·AI PC 보호 설치·한국어 음성 수용은 대기이며 장치 작업 실행·결과 알림은 첫 조회 버전 수용 뒤의 Task 4다.

후속 검증: FULL 22개 묶음은 28,557 통과·14 실패·1,950 건너뜀이었으며, 발견한 14개를 수정한 범위의 UI/브라우저 65개·설치/배포 84개·Fleet 통합 121개가 통과했다. Console Node 전체는 342개 통과했다. 서로 다른 SHA와 수정분 시험을 합친 증거이며 최종 SHA의 FULL 재실행으로 표시하지 않는다. 정확한 범위와 미수용 조건은 [검증 기록](../validation/operator-ai-2026-10-20/result.md)에 있다. 아래 미완료 항목은 실제 모델·음성·배포·실행 수용까지 포함한 잔여 작업이다.

**Goal:** 운영자가 기존 관제 화면에서 텍스트·음성으로 상황을 묻고 실제 근거에 따른 답과 작업 결과를 받는다.

**Architecture:** Console은 현장 Fleet에만 요청한다. Fleet가 인증·대화 원장·조회·실행 검증을 담당하고, 기존 Decision 의미 계약과 승인된 AI PC broker를 재사용한다. 음성 인식은 최종 텍스트 입력으로 합류한다.

**Tech Stack:** 기존 정적 JavaScript ES modules, FastAPI, SQLite, pydantic, 기존 forced-command broker transport. 첫 음성 adapter는 브라우저 로컬 한국어 인식/합성이고 지원되는 환경에서만 동작한다.

**Spec:** [설계안](2026-10-20-operator-ai-design.md)

## Global Constraints

- 첫 배포는 조회 전용. 텍스트 조회 → 음성 입출력 → 기존 실행 연결 순서로 각각 검증·착지한다.
- 새 최상위 디렉터리·별도 챗봇 서버·직접 CORE/ROS 호출을 추가하지 않는다.
- 기존 Discord 신원·원장·실행 검증을 보존한다. Console 신원을 Discord 식별자로 위장하지 않는다.
- API·스키마·인증은 기존 계약이 정본이다. 새 계약은 예약 후 등록하며 공급자 비밀은 브라우저나 공개 문서에 두지 않는다.
- pytest·브라우저 회귀는 커밋한 SHA로 원격 시험 PC에서 실행한다. 로컬 노트북에서는 pytest를 실행하지 않는다.
- 아래 새 파일 이름은 구현 위치 제안이다. 각 단계 시작 시 최신 소유 영역·크기 제한·호출자를 확인한 뒤 확정한다.
- 기능·모듈·변경 범위는 설계안의 「기능과 책임」이 정본이다. 대화 원장·장치 원장을 복제하거나 Console 설치로 기존 단일 실행 callback을 덮어쓰지 않는다.

## Task 0: 출처 계약과 단일 처리 소유자 확정

기존 Task 1보다 먼저 수행한다. 이번 보완에서 확인한 실제 결합을 해소할 계약·회귀 기준을 확정해야 UI 구현이 Discord와 이중 실행 경로에 의존하지 않는다.

**Files:** 기존 Decision `conversation/codec.py`, Fleet `channel/conversation/{jobs,runtime}.py`, `channel/execution/runtime.py`와 대응 시험을 읽는다. 변경 범위는 예약 ADR·API·스키마와 회귀 fixture부터 정한다. 공통 구현 이전이 필요하면 매니페스트·패키징 변경을 제품 브랜치와 분리한다.

**Interfaces:** 웹은 현장·principal·대화 출처를 서버가 결속한다. Discord v1 식별자는 기존 adapter가 검증한다. 두 출처는 공통 의미 검증을 사용하되 이력·원문 소유권·응답 목적지를 혼합하지 않는다. 기존 `rosy-conversation-v1`에 웹 데이터를 강제로 넣지 않는다.

- [ ] 웹/Discord의 단독 구성과 동시 구성, 같은 principal의 서로 다른 대화, 원문 변경·계정 철회, 과거 v1 레코드 읽기를 계약 사례로 작성한다.
- [ ] 입력 계약 버전·공통 구현 위치·단일 실행 연결·응답 경로와 마이그레이션을 ADR에 확정한다. 기존 테이블을 파괴하거나 기존 원장을 새 worker가 재생하지 않는다.
- [ ] 공통 처리 분리 시 기존 동작의 회귀를 먼저 통과시킨다. 웹 기능이 꺼져 있을 때 기존 v1의 입력·답변·실행 상태가 같아야 한다.
- [ ] 모델 입력/정책 변경에 필요한 평가·승인 증거를 별도로 확보한다. 기존 D-728 승인 파일로 새 웹 프로토콜을 활성화하지 않는다. Console/Discord 동시 설치에서 실행 owner와 callback이 각각 하나임을 검증한 뒤 Task 1로 간다.

## Review Focus

- 계정 변경 직후 도착한 이전 응답과 타인의 대화 조회 → Task 1·2에서 차단 시험.
- 타임아웃 후 재전송·재시작 → Task 1·4에서 모델 호출·실행 중복 금지 시험.
- 오래된 상태와 변경된 지도·모델 승인 → Task 1·4에서 보류 시험.
- 녹음 중 TTS 재생·마이크 거부·음성 미지원 → Task 3에서 텍스트 복귀·재생 중단 시험.
- 실제 모델 없이 통과한 UI·합성 음성 시험 → Task 5에서 별도의 실제 연결·한국어 수용 증거 요구.

## Task 1: Console 대화 접수와 조회 전용 응답

기존 대화 처리가 Discord 접수·회신 원장에 결속된 부분을 먼저 추적한다. 채널 인증과 의미 검증을 분리하는 최소 변경으로 웹 대화를 수용한다. 공용 프레임워크를 새로 만들지 않는다.

**Files:**

- Create: `operations/fleet/fleet/server/assistant/{routes,service,journal,context,runtime}.py` 중 실제 책임이 필요한 파일
- Modify as needed: `operations/fleet/fleet/server/app.py`, `operations/fleet/fleet/server/channel/conversation/{jobs,worker,runtime}.py`, `operations/decision/src/rosy/decision/conversation/codec.py`
- Contract: `docs/reference/ROSY API & Protocol Reference.md`, `contracts/foundation/core_common/protocol/schemas.py`, 도구로 예약한 ADR
- Test: `operations/fleet/test/test_assistant_requests.py`; 회귀 `test_channel_requests.py`, `test_channel_conversation.py`, `test_conversation_followup.py`

**Interfaces:** Consumes Fleet 인증 principal, 기존 상태 snapshot·conversation provider·codec. Produces 등록된 웹 대화 접수/자기 내역/요청 상태 계약. 접수는 principal·현장·대화에 결속된 중복 방지 식별자와 최종 사용자 텍스트를 받고, 응답은 영속 요청 ID·처리 상태·답변·조회 시각·근거·보류 사유를 제공한다. 외부 경로·필드 이름은 다음 첫 단계에서 확정한다.

내부 진입점은 `service.submit(principal, message)`와 `service.read(principal, request_id)`로 모은다. `context.build_context(principal, selection)`이 기존 읽기 소유자의 권한을 거쳐 상태·사건·작업을 제한한다. routes는 HTTP 처리만, runtime은 설치/종료만 맡는다. 모델 호출은 기존 provider를 주입하고 웹/Discord에 모델 처리 로직을 복사하지 않는다.

- [ ] 기존 호출자·테이블·활성화·outbox를 추적하고 웹 출처, 인증, 요청/응답 한도, 상태 전이, 보존 기간을 ADR/API/스키마에 확정한다. 변경이 foundation/FULL 범위이면 계약 브랜치를 먼저 분리한다.
- [ ] 새 시험에서 타인 대화는 비공개, CSRF/위조 principal 거부, 동일 접수 재전송은 같은 요청, 모델 UNKNOWN 재호출 금지, 오래된 근거/승인 만료는 보류를 검증한다. 이동 요청에서 실행 호출 횟수는 0이어야 한다.
- [ ] 최소 접수·자기 범위 조회·처리 연결을 구현한다. 조회만 허용하고 미지원 요청에는 명확한 안내를 반환한다.
- [ ] 정지 원인 질문은 사건 읽기 근거가 있을 때만 원인을 답한다. 사건 없음·타인 작업·오래된 근거·대명사 다중 후보·선택 후 지도 변경 시험을 추가한다. 최근 대화 이력이 끊기는 상황에서도 현재 선택을 재검증하고 추측으로 채우지 않는다.
- [ ] 모델 호출 교체 시험은 같은 service 인터페이스에서 fake provider로 수행하고, context 시험은 기존 소유자 읽기를 대체해 권한·출처·신선도 누락이 거부됨을 검증한다. private DB 메서드나 UI를 통해서만 시험할 수 있는 구조는 피한다.
- [ ] 커밋 후 위 시험과 기존 채널 회귀를 원격 실행한다. 새 실패 0, 기존 Discord 계약 유지가 완료 조건이다.

## Task 2: 관제 화면 오른쪽 대화 패널

**Files:**

- Create: `operations/site_ui/console/assistant/{panel.js,panel.css}`
- Modify: `operations/site_ui/console/{index.html,console.js}`, `operations/fleet/fleet/server/console/static_routes.py`
- Test: `operations/fleet/test/web/assistant.test.mjs`, `operations/fleet/test/test_assistant_browser.py`
- Reference: `operations/site_ui/console/work/channel-request-view.js`, 기존 auth·polling·페이지 수명 관리

**Interfaces:** Consumes Task 1에 등록한 계약과 Console의 `call()`·인증·수명 관리. Produces `createAssistantPanel({scope, call, el})` 모듈과 대화 표시. 자체 토큰·CORE 주소를 받지 않는다.

- [ ] 순수 상태 전이 시험과 브라우저 시험을 작성한다. 전송·처리 중·보류·실패, 계정 전환 후 늦은 응답 버리기, 모델 응답을 HTML로 실행하지 않기, 네트워크 단절 시 자동 중복 접수 금지를 검증한다.
- [ ] 키보드로 열기·닫기·전송 가능한 패널을 구현한다. 응답 근거와 상태 시각을 표시한다. 기존 공통 컴포넌트·토큰과 CSP를 사용하고 정적 자산 allowlist에 파일을 등록한다.
- [ ] 작은 화면과 확대 화면에서 지도·비상정지 접근을 확인한다. 계정 전환·로그아웃 시 대화 내용을 비운다.
- [ ] 대화 답변 상태와 연결된 작업 상태를 따로 표시한다. 처리 중단·녹음 취소를 로봇 작업 취소로 표시하지 않는 브라우저 시험을 추가한다. 상태·작업 종류별 UI 복제 대신 공통 답변/근거/작업 참조 표시를 사용한다.
- [ ] Node 시험과 원격 브라우저·권한 회귀를 통과한다. 설치한 wheel/sdist의 정적 자산 제공도 검증한다. 텍스트 대화의 실제 모델 스모크를 별도로 기록한 뒤 첫 배포 대상으로 삼는다.

## Task 3: 눌러서 녹음, STT, 선택적 읽어주기

**Files:**

- Create: `operations/site_ui/console/assistant/voice.js`, `operations/fleet/fleet/server/assistant/speech.py`
- Modify: Task 2 panel, Fleet assistant routes/runtime, 승인된 STT adapter·AI PC 배포 파일은 준비 시험 결과로 확정
- Contract/Test: 음성 API reference·스키마, `operations/fleet/test/test_assistant_speech.py`, `operations/fleet/test/web/assistant-voice.test.mjs`, Task 2 브라우저 시험

**Interfaces:** Consumes 사용자 동작으로 시작한 녹음과 인증된 Fleet 요청. Produces 편집 가능한 인식 텍스트. 원음이나 중간 인식 결과는 대화/명령을 접수하지 않는다. TTS는 표시된 최종 답변의 선택적 재생이다.

- [ ] 준비 시험: 운영 브라우저·HTTPS 마이크 권한·한국어 TTS·AI PC 여유와 기존 STT 설치 여부를 확인한다. 실제 한국어 발화에서 로봇명/장소명·소음·무음·취소를 측정해 STT 한 가지를 선택한다. 엔진·버전·처리 호스트·외부 전송 여부·의존성과 음성 길이/크기/디코딩/동시 처리 한도를 기록한 뒤 음성 계약을 확정한다. 브라우저가 외부 STT로 직접 전송하는 대체 경로는 만들지 않는다.
- 현재 소스 선택: 새 STT 서버 대신 `assistant/assistant-voice.js`에 로컬 브라우저 adapter를 먼저 구현했다. 로컬 인식 지원·한국어 팩을 기능 탐지하고 30초·2000자, 전송 전 편집, 계정 변경/페이지 이탈 시 취소를 검증했다. 대상 브라우저의 실제 수용은 미완료다. AI PC `speech.py`와 음성 업로드 계약은 만들지 않았고 브라우저 수용 실패 시 이 단계로 돌아온다.
- [ ] 한도 초과·위조 MIME/손상 음성·디코딩 시간 초과·동시 요청·인증 만료·마이크 거부·TTS 미지원 시험을 작성한다. 취소/실패 후 녹음 자원 해제와 원음 정리를 검증한다.
- [ ] STT 결과를 입력란에 채우고 운영자가 수정·전송하게 한다. 재생 중 녹음 시작 시 TTS를 중단한다. 음성 미지원/실패 시 텍스트 사용을 유지한다.
- [ ] 원격 자동 시험 후 실제 관제 PC에서 10개 이상의 한국어 문장(로봇명·장소명·숫자·후속 질문 포함)을 시험하고 인식문·수정 필요 여부·처리 시간을 기록한다. 확인 없이 실행된 요청 0, 실패 시 텍스트 사용 가능을 필수 통과 조건으로 삼는다.

## Task 4: 작업 요청과 기존 실행·결과 연결

**Files:**

- Modify: `operations/fleet/fleet/server/assistant/`, `operations/fleet/fleet/server/channel/execution/`의 필요한 결속 지점, Task 2 panel
- Reuse: 기존 Fleet Task/Mission/Cell/formation owner, `work/channel-request-view.js`
- Test: `operations/fleet/test/test_assistant_execution.py`, 기존 channel execution·semantic admission·followup 회귀

**Interfaces:** Consumes 검증된 의미 제안과 현재 운영자/지도/정지 세대. Produces 기존 owner의 영속 작업 참조와 원장·CORE 근거에 따른 상태. 모델 답변에 완료 상태 결정권을 주지 않는다.

- [ ] 이름 있는 operator만 실행, 불명확한 대상은 명확화, 타인 문맥/변경된 지도/정지 세대/철회된 권한은 보류, 중복 전송/재시작에도 실행 한 번, UNKNOWN 실행은 자동 재시도하지 않음을 시험한다.
- [ ] D-728과 기존 실행 소유자의 승인 규칙을 그대로 연결한다. 모든 요청에 추가 확인 클릭을 새로 요구하지 않는다. 독립 승인이 필요한 작업은 기존 검토 화면으로 연결한다.
- [ ] 접수·실행 중·완료·실패·확인 불가를 원장 근거로 갱신한다. “도착하면 알려줘”는 대화와 작업의 영속 결속을 통해 표시하고 재시작 후에도 결과를 복원한다.
- [ ] 웹과 Discord가 동시에 수용되는 시험에서 같은 작업은 한 owner를 거치고 기존 callback을 덮어쓰지 않음을 검증한다. 결과 알림은 재전송·재시작 후 중복 표시되지 않아야 한다. 답변 중단 뒤 이미 수용된 작업은 기존 owner의 취소 결과 없이 취소 상태로 바뀌지 않아야 한다.
- [ ] 원격 회귀를 통과한 후 승인된 현장 절차로 제한된 작업을 검증한다. 실기 권한이 없는 단계에서는 소스 검증까지만 기록하고 현장 수용은 미완료로 남긴다.

## Task 5: 배포·수용과 인수인계

**Files:** 기존 Fleet/AI PC 배포 문서·설정 예제, `docs/validation/operator-ai-<실행일>/` 증거, 관련 모듈 progress/logs. 실제 주소·계정·키·채운 설정은 `private/`.

- [ ] 배포 기준 SHA와 모델/profile/승인 증거를 기록한다. 모델 미설정·만료 상태에서 Fleet의 기존 관제 기능과 비상정지 사용을 확인한다.
- [ ] 원격 pytest는 `python tools/remote/remote_pytest.py --log-dir <repo-밖-증거폴더> -- <해당-test-paths> -q`로 요청한다. 기존 실패는 `test/known_failures.py`와 비교한다. 브라우저 suite가 skip이면 브라우저 수용을 통과로 표시하지 않는다.
- [ ] 실제 AI PC 연결, 관제 PC 음성, 실행 결과를 각각 기록한다. 상태 조회·원인 질문·후속 질문·불명확한 요청·연결 끊김·로그아웃을 수용 시나리오에 포함한다.
- [ ] 비활성화/rollback은 신규 접수·worker를 멈추되 이미 접수한 작업 원장과 결과를 보존한다. 기존 채널의 재생·UNKNOWN 규칙과 승인 spent marker를 유지한다.
- [ ] 승인된 단계만 별도 배포하고 실제 배포 SHA를 기록한다. 이 계획 작성으로 push·병합·장비 접근 권한을 추가하지 않는다.

## 이번 계획 작성의 검증

관련 소스·소유 영역·기존 대화 계약·웹 자산 제공 규칙을 읽었다. 제품 코드는 수정하지 않았으며 모델 접속·음성 시험·원격 pytest·장비 동작은 수행하지 않았다. 구현 전 최신 main/원격 분기와 기존 Fleet 배포 기준을 다시 맞춰야 한다.

유지보수 보완에서는 Discord 식별자의 스키마/이력 결속, 단일 실행 소유자 설치, 현재 상태 문맥의 제한과 기존 읽기 도구를 추가로 확인했다. 이 근거를 설계안에 기록하고 Task 0·context/service 책임·동시 구성 회귀를 추가했다. 새 기능이 구현되었다는 증거로 사용하지 않는다.
