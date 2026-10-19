# 관제 AI 에이전트 구현 계획

> **For agentic workers:** 구현 시 `superpowers:executing-plans`로 작업별 진행한다. 이 문서는 검토용 초안이며 구현·배포 시작을 뜻하지 않는다.

**Goal:** 운영자가 기존 관제 화면에서 텍스트·음성으로 상황을 묻고 실제 근거에 따른 답과 작업 결과를 받는다.

**Architecture:** Console은 현장 Fleet에만 요청한다. Fleet가 인증·대화 원장·조회·실행 검증을 담당하고, 기존 Decision 의미 계약과 승인된 AI PC broker를 재사용한다. 음성 인식은 최종 텍스트 입력으로 합류한다.

**Tech Stack:** 기존 정적 JavaScript ES modules, FastAPI, SQLite, pydantic, 기존 conversation broker. STT 엔진은 Task 3의 준비 시험에서 확정한다.

**Spec:** [설계안](2026-10-20-operator-ai-design.md)

## Global Constraints

- 첫 배포는 조회 전용. 텍스트 조회 → 음성 입출력 → 기존 실행 연결 순서로 각각 검증·착지한다.
- 새 최상위 디렉터리·별도 챗봇 서버·직접 CORE/ROS 호출을 추가하지 않는다.
- 기존 Discord 신원·원장·실행 검증을 보존한다. Console 신원을 Discord 식별자로 위장하지 않는다.
- API·스키마·인증은 기존 계약이 정본이다. 새 계약은 예약 후 등록하며 공급자 비밀은 브라우저나 공개 문서에 두지 않는다.
- pytest·브라우저 회귀는 커밋한 SHA로 원격 시험 PC에서 실행한다. 로컬 노트북에서는 pytest를 실행하지 않는다.
- 아래 새 파일 이름은 구현 위치 제안이다. 각 단계 시작 시 최신 소유 영역·크기 제한·호출자를 확인한 뒤 확정한다.

## Review Focus

- 계정 변경 직후 도착한 이전 응답과 타인의 대화 조회 → Task 1·2에서 차단 시험.
- 타임아웃 후 재전송·재시작 → Task 1·4에서 모델 호출·실행 중복 금지 시험.
- 오래된 상태와 변경된 지도·모델 승인 → Task 1·4에서 보류 시험.
- 녹음 중 TTS 재생·마이크 거부·음성 미지원 → Task 3에서 텍스트 복귀·재생 중단 시험.
- 실제 모델 없이 통과한 UI·합성 음성 시험 → Task 5에서 별도의 실제 연결·한국어 수용 증거 요구.

## Task 1: Console 대화 접수와 조회 전용 응답

기존 대화 처리가 Discord 접수·회신 원장에 결속된 부분을 먼저 추적한다. 채널 인증과 의미 검증을 분리하는 최소 변경으로 웹 대화를 수용한다. 공용 프레임워크를 새로 만들지 않는다.

**Files:**

- Create: `operations/fleet/fleet/server/assistant/{routes,journal,runtime}.py`
- Modify as needed: `operations/fleet/fleet/server/app.py`, `operations/fleet/fleet/server/channel/conversation/{jobs,worker,runtime}.py`, `operations/decision/src/rosy/decision/conversation/codec.py`
- Contract: `docs/reference/ROSY API & Protocol Reference.md`, `contracts/foundation/core_common/protocol/schemas.py`, 도구로 예약한 ADR
- Test: `operations/fleet/test/test_assistant_requests.py`; 회귀 `test_channel_requests.py`, `test_channel_conversation.py`, `test_conversation_followup.py`

**Interfaces:** Consumes Fleet 인증 principal, 기존 상태 snapshot·conversation provider·codec. Produces 등록된 웹 대화 접수/자기 내역/요청 상태 계약. 접수는 principal·현장·대화에 결속된 중복 방지 식별자와 최종 사용자 텍스트를 받고, 응답은 영속 요청 ID·처리 상태·답변·조회 시각·근거·보류 사유를 제공한다. 외부 경로·필드 이름은 다음 첫 단계에서 확정한다.

- [ ] 기존 호출자·테이블·활성화·outbox를 추적하고 웹 출처, 인증, 요청/응답 한도, 상태 전이, 보존 기간을 ADR/API/스키마에 확정한다. 변경이 foundation/FULL 범위이면 계약 브랜치를 먼저 분리한다.
- [ ] 새 시험에서 타인 대화는 비공개, CSRF/위조 principal 거부, 동일 접수 재전송은 같은 요청, 모델 UNKNOWN 재호출 금지, 오래된 근거/승인 만료는 보류를 검증한다. 이동 요청에서 실행 호출 횟수는 0이어야 한다.
- [ ] 최소 접수·자기 범위 조회·처리 연결을 구현한다. 조회만 허용하고 미지원 요청에는 명확한 안내를 반환한다.
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
- [ ] Node 시험과 원격 브라우저·권한 회귀를 통과한다. 설치한 wheel/sdist의 정적 자산 제공도 검증한다. 텍스트 대화의 실제 모델 스모크를 별도로 기록한 뒤 첫 배포 대상으로 삼는다.

## Task 3: 눌러서 녹음, STT, 선택적 읽어주기

**Files:**

- Create: `operations/site_ui/console/assistant/voice.js`, `operations/fleet/fleet/server/assistant/speech.py`
- Modify: Task 2 panel, Fleet assistant routes/runtime, 승인된 STT adapter·AI PC 배포 파일은 준비 시험 결과로 확정
- Contract/Test: 음성 API reference·스키마, `operations/fleet/test/test_assistant_speech.py`, `operations/fleet/test/web/assistant-voice.test.mjs`, Task 2 브라우저 시험

**Interfaces:** Consumes 사용자 동작으로 시작한 녹음과 인증된 Fleet 요청. Produces 편집 가능한 인식 텍스트. 원음이나 중간 인식 결과는 대화/명령을 접수하지 않는다. TTS는 표시된 최종 답변의 선택적 재생이다.

- [ ] 준비 시험: 운영 브라우저·HTTPS 마이크 권한·한국어 TTS·AI PC 여유와 기존 STT 설치 여부를 확인한다. 실제 한국어 발화에서 로봇명/장소명·소음·무음·취소를 측정해 STT 한 가지를 선택한다. 엔진·버전·처리 호스트·외부 전송 여부·의존성과 음성 길이/크기/디코딩/동시 처리 한도를 기록한 뒤 음성 계약을 확정한다. 브라우저가 외부 STT로 직접 전송하는 대체 경로는 만들지 않는다.
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
