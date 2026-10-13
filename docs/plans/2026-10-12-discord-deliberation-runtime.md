# Discord Deliberation Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실제 기명 Discord 요청을 현재 관제 근거·고정 숙고형 판단·영속 원장·검증된 답글로 연결한다.

**Architecture:** 기존 ChannelRequests/ChannelReplyOutbox와 Decision schema 2를 사용한다. fleet_status는 읽기 전용이며 기존 incident 모델 worker의 실행 예산과 권한을 우회하지 않는다. 별도 broker 전용 SSH key와 보호된 AI 계정에서 고정 모델·격리·비용 증거를 검사한다.

**Tech Stack:** 기존 Python/FastAPI/SQLite/httpx/SSH, Ollama, isolated OpenCode GLM launcher. 새 의존성과 장치 writer는 추가하지 않는다.

읽기 전용 질의는 별도 `READ_ONLY_QUERY` 필요성 값으로 묶는다. CORE의 `INTERVENE/DO_NOT_INTERVENE/ABSTAIN`과 혼동하지 않으며 일반 도메인에서는 허용하지 않는다. 원문은 기존 goal의 bounded data로 직렬화하고 기존 세 domain의 dataclass 필드·payload·digest는 바꾸지 않는다. status adapter/profile/calibration은 별도 고정 identity다. Discord 답변은 검증된 verdict와 현재 robot별 관측의 deterministic formatter이며 자유 모델 문장을 장치 사실로 전달하지 않는다. 명시적 상태 질의는 한도 내 Qwen을 호출할 수 있으나 정상 CORE 사건의 모델 무호출 규칙은 유지한다. 기존 GLM 단일 spent marker는 새 profile·배포·rollback에서도 보존한다.

## Scope and current evidence

- 현장 서명 후보와 Discord 수신/회신은 실행 중이다. 신규 실제 메시지의 접수·자동 회신과 원래 메시지 reference를 provider에서 읽어 확인했다.
- Qwen 모델의 통제된 읽기 전용 시험은 성공했으나 자동 숙고형 연결 증거는 아니다.
- 기존 Fleet CLI는 incident_model_config를 주입하지 않는다. 보호된 AI 계정은 설치돼 있으나 로그인 계정에 관리자 없이 접근할 권한이 없다.
- 시간 초과의 API 경로를 안전하게 기록하는 diagnostics 변경은 원격 RED 후 GREEN 72 passed/NEW 0이며 독립 source review를 통과했다. 실제 네트워크 시간 초과의 원인을 해결했다고 주장하지 않는다.

## Task 1: Typed read-only domain

Files: `operations/decision/src/rosy/decision/deliberation/__init__.py`, `contracts/profiles.py`, `contracts/judgment.py`, existing `model_tool_catalog.py`; matching Fleet/Decision tests.

1. 기존 사건 domain과 다른 fleet_status 입력, 현재 관측 enum·근거·원문 길이 및 모든 장치 tool 거절의 RED 시험을 커밋한다.
2. `python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<session>/logs/status-red -- <exact tests>`와 known_failures로 실패를 확인한다.
3. fleet_status만 읽기 전용 tool과 검증된 schema에 연결한다. 기존 profile/Problem/판정은 그대로 유지한다.
4. 같은 원격 시험을 통과시키고 exact paths만 커밋한다.

## Task 2: Shared durable channel job

Files: `operations/fleet/fleet/server/channel_deliberation.py`, channel lifecycle/CLI composition, existing reply outbox and tests.

1. owner/hash/profile/현재 관측 변경, reserve-before-call, UNKNOWN no replay, queue bound, shutdown, 결과+회신 rollback의 RED를 작성한다.
2. 기존 tasks DB의 request별 job과 시도·deadline을 예약한다. 기존 원문은 수정하지 않고 claim/Task를 만들지 않는다.
3. 모든 await 뒤 scope를 재확인하고 검증 결과+회신만 같은 transaction으로 저장한다. 현재 CORE 사건은 기존 IncidentCaseStore 예산을 공유한다.
4. 원격 GREEN과 실제 SQLite reopen/중단 fixture를 확인한다.

## Task 3: Fixed broker and privileged install closure

Files: existing `deploy/ai_pc/deliberation_ollama.py`, GLM codec/receipt/launcher; new fixed broker entry and installer; Fleet SSH provider config/client; signed site Compose optional mount.

1. host/command/key/profile drift, oversized I/O, role budget, process cleanup, secret boundary, wrong model/usage/cost의 RED를 작성한다.
2. 고정 role/profile과 16KiB/30초/owned cleanup을 연결한다. 기존 host-control key·임의 URL·HOME 공유는 금지한다.
3. 관리자 명령 전 staging 파일·SHA manifest·rollback·preflight를 완성한다. 보호된 credential은 출력·복사하지 않는다.
4. 소스 static capability는 admission이 아니다. 실측 host/model/sandbox/billing 증거가 없으면 호출하지 않는다.

## Task 4: API, visible status and acceptance

Files: API reference/Foundation schema, existing Console request display, validation record, module logs/indexes.

1. 읽기 전용 결과를 원문 request에 묶어 관제와 Discord에서 확인한다. 접수·모델 결과·장치 실행·목표 완료를 구분한다.
2. 최신 main 통합, lint/remote regression/known_failures/independent review/local FF를 완료한다.
3. 서명 사이트 배포와 별도 AI 지정 SHA 배포 후 각 build/image/profile/관측/job/outbox를 읽어 확인한다.
4. 첫 GLM 실측 호출의 영속 1회 한도를 유지하며 신규 실제 Discord 왕복을 확인한다. 관리자 경계는 완성된 검토 가능 명령을 마지막에 요청한다. 오프라인 장치의 물리 수용은 남겨 둔다.
