# D-831 관제 명령 전처리 구현 계획

> **For agentic workers:** superpowers:executing-plans로 현재 세션에서 직접 구현한다. 각 단위는 커밋한 SHA의 원격 RED→GREEN과 마지막 독립 검토를 거친다.

**Goal:** Console·Discord의 승인된 고정 모델 입력에 원문을 보존하는 공통 전처리, 등록 이름 해소, 보수적인 후보 검증과 실제 토큰 계측을 연결한다.

**Architecture:** Decision은 정규화 사본·카탈로그 힌트·행동 후보 검증을 소유하고 Fleet는 신원·원장·최종 거래를 유지한다. AI PC broker는 전처리한 제한 문맥과 실제 사용량을 제공한다. 새 Discord profile은 기존 자동 실행 worker에 연결하지 않고 제안으로만 닫는다. Console은 기존 별도 명시적 좌표 접수를 유지한다. 확인용 새 공개 API는 이 변경에서 추측하지 않는다.

**Tech Stack:** 기존 Python/Pydantic/SQLite·고정 Ollama. 새 형태소 분석기·토크나이저·음성 모델 의존성 없음.

**Spec:** [D-831](../adr/D-831-operator-command-preprocessing.md), D-810/D-821/D-728. 사용자가 ADR 후 즉시 구현을 요청했다.

## Global Constraints

- 원문·요청 ID·locale·인증 신원과 멱등성은 변경하지 않는다. 모델에 실행 권한을 주지 않는다.
- 정규화는 NFC·제한된 수평 공백 처리이며 인용·식별자·숫자/부호/단위를 보존한다.
- 현재 8192 context/1024 생성·한 번의 호출·UNKNOWN 자동 재실행 금지를 유지한다. 문자/바이트를 정확한 토큰 수로 부르지 않는다.
- 새 전처리는 profile/source/입력 digest/카탈로그 hash에 결속한다. 기존 Discord 고정 snapshot/profile의 의미를 바꾸지 않는다.
- 사람의 확인을 표현하는 새 자연어 API·음성 자동 실행은 만들지 않는다. D-831의 새 확인 계약은 별도 공개 계약 설계와 수용이 필요하며 새 Discord profile 실행은 그 전까지 OFF다.
- 로컬 pytest 금지. 커밋 SHA를 `tools/remote/remote_pytest.py`로 시험하고 known-failures와 비교한다.

## Review Focus

- NFD 한글·인용·음수·소수·단위·줄바꿈이 뜻을 유지하며 원문/재시도는 불변인가.
- 이름 충돌·미등록 이름·부정 범위·인용/조건·복합 명령에서 모델이 CONTROL을 잘못 제안해도 접수가 차단되는가.
- `A 말고 B 상태`를 전역 부정 규칙으로 조회까지 막지 않는가.
- 사용량을 모델이 위조할 수 없고 사용량 로그에 원문·사용자/채널 ID를 쓰지 않는가.
- legacy Discord profile/보호 설치·기존 실행 worker와 새 제안 전용 profile이 혼동되지 않는가.

## Task 1: Decision 공통 전처리와 후보 검증

**Files:** `conversation/preprocessing.py`, `conversation/operator.py`, `conversation/codec.py`와 `operations/fleet/test/test_assistant_preprocessing.py`.

**Interfaces:** `prepare(question)`는 원 입력을 바꾸지 않고 버전·정규화 사본·카탈로그 충돌과 모델용 문맥을 반환한다. `control_issue(prepared, steps=1)`는 차단 이유 또는 None을 반환한다. `InferenceUsage`는 실제 입력/생성 토큰·지연·전처리 hash를 검증하며 일반 응답 직렬화에서 제외한다.

- [x] 원문 불변·동일 정규화/서로 다른 요청 hash·인용/부호·별칭 충돌·부정/조건/복수 행동 차단·부정 포함 STATUS 허용을 원격 RED로 확인한다.
- [x] 순수 Decision 모듈과 명시적 선택 검증을 구현하고 해당 테스트를 원격 GREEN으로 확인한다.
- [x] 원문 이력·타인 신원·현재 카탈로그를 임의로 줄이지 않는 회귀를 포함해 커밋한다.

## Task 2: broker·Fleet 연결과 계측

**Files:** `deploy/ai_pc/{operator_broker,deliberation_conversation,operator_acceptance}.py`, 기존 보호 설치기, `assistant/provider.py`, `channel/conversation/runtime.py`, 위 회귀 테스트와 `test/test_operator_preprocessing_benchmark.py`.

**Interfaces:** 새 operator profile과 `d728-semantic-v3-d831`만 공통 전처리를 적용한다. broker가 실제 응답에서 측정한 usage를 내부 답변에 붙이고 Fleet가 검증·개인정보 없는 구조화 로그를 남긴 뒤 일반 답변에서 제거한다. 기존 request/REST 형식은 유지한다.

- [x] broker 입력·측정값 위조·입력+생성 예산·legacy profile 보존·새 Discord worker 미설치를 원격 RED→GREEN으로 검증한다.
- [x] 같은 기존 ko/en 19개 사례의 고정 모델 baseline 사용량·지연을 변경 전 기록한다. 추가 ko/en 부정 범위·별칭/조건/인용 사례를 포함한 변경 후 평가와 구분한다.
- [x] profile/source binding·독립 평가·source closure와 현재 의미 검증을 유지하고 새 모델 다운로드/보호 설치 없이 실제 고정 모델을 평가한다.

## Task 3: 운영 문서·증거·착지

**Files:** 기존 operator 운영 안내, Decision/Fleet/deploy의 소유 로그·생성 색인, `docs/validation/operator-preprocessing-2026-10-21/`.

- [x] 변경 SHA·원격 로그·실제 모델/사용량·실패와 미실행 범위를 기록한다. 실제 절감이 없으면 절감 성공으로 표시하지 않는다.
- [ ] 영향 선택과 해당 모듈 회귀를 원격 실행하고 독립 최종 검토를 받는다. 자기 실패는 고치고 기존 실패 목록/안전 기준을 완화하지 않는다.
- [ ] 기존 사용자 커밋·로컬 병합 요청 범위에서 정식 착지 관문을 통과한다. push·보호 설치·현장 gate는 별도로 남긴다.

## 실행 판단

공통 전처리와 broker/Fleet의 profile binding은 같은 소스 closure로 검증해야 한다. 새 공개 명령/확인 API를 한꺼번에 추가해 FULL/장치 범위를 넓히지 않고, 현재 확인·실행 경계를 보존하는 연결된 단위로 구현한다. ADR의 후속 확인 계약은 미구현으로 명시하며 새 자연어 실행으로 대체하지 않는다.
