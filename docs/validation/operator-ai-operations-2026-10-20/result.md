# 관제 AI 운영 구조·실행 연결·다국어·Discord 검증

2026-10-20, `feat/operator-ai`, D-821/API v1.290. 배포 구성·보호 설치기·명시적 이동 접수와 재현 가능한 시험을 구현했다. **운영 배포 수용은 미완료**다. FULL에서 남은 프로세스 종료 실패 두 건의 원인은 확정하지 못했다. 이전 [조회 버전 기록](../operator-ai-2026-10-20/result.md)은 당시 결과로 보존한다.

제품 소스는 이동 경계 `b0675386a1`, 운영 선택 설정/화면 `a1f0252d0a`, 모델 adapter `b1f18674b2`, 이동 오류 처리 `a8bc6debd0`다. 아래 FULL은 `7b7a367014`이며 이후 수정분은 별도 범위에서 검증했다. 최종 브랜치 전체 SHA의 FULL 통과로 합쳐 표시하지 않는다.

## 구현된 경계

| 책임 | 소유 위치와 동작 |
|---|---|
| 운영 배포 구성 | 기본/페어링 Compose가 기존 Fleet 전용 읽기 전용 mount에서 optional operator 설정을 읽는다. 파일 부재는 OFF, 잘못된 파일은 시작 거부다. |
| AI PC 보호 설치 | `deploy/site/install_operator_broker.py`: 기존 동일 SHA의 Discord snapshot/venv/wrapper에 독립 operator 평가를 결속한다. hash/source/profile/전체 사례/평가 시각을 검사하고 설정만 원자적으로 교체·readback·rollback한다. |
| 실행 접수 | `assistant/execution.py`: 운영자가 선택 로봇과 좌표를 명시한 POST만 기존 `IntentExecution`/Task owner로 접수한다. 별도 worker나 직접 장치 호출을 만들지 않는다. |
| 실행 승인 | 기본 OFF인 execution_enabled, 현재 기명 권한·모델 승인·자기 CONTROL 종단·동일 로봇·30초 유효성을 Task 거래 안에서도 검사한다. 모델은 READ_ONLY이며 action_admissible=false다. |
| 재시도와 결과 | principal/request에서 기존 Task 멱등 키를 만든다. 같은 요청은 같은 Task, 좌표 변경은 409다. 실제 상태/취소/UNKNOWN은 기존 Task API를 사용한다. |
| 언어 | ko-KR/en-US를 원본 요청·모델 입력·서버 응답·근거·로컬 음성 선택에 결속했다. 언어 변경은 인식을 취소한다. locale 없는 기존 요청의 한국어 재시도도 보존한다. |

현재 패널은 기존 작업 화면을 연결한다. 새 이동 API는 구조화된 클라이언트와 통합 시험용 접수 경계다. 자연어 자동 실행·새 목적지 입력 폼·서버 STT/TTS는 구현하지 않았다. 설치/시험 명령과 유지보수 위치는 [운영 안내](../../../operations/fleet/docs/operator-assistant.md), 오픈소스 후보·라이선스·공식 출처·실측 절차는 [모델 평가](../../../operations/fleet/docs/operator-models.md)를 따른다.

## 소프트웨어 시험

모든 pytest·Chromium은 커밋한 SHA를 원격 시험 PC로 전달했다. 노트북 pytest나 로컬 대체 실행은 하지 않았다. Node는 기존 Console loader로 실행했다. 원본 루트는 작업 PC의 `%LOCALAPPDATA%/Temp/operator-ai/`이며 실제 주소/계정/토큰이 포함될 수 있는 원본은 공개 저장소에 넣지 않는다.

| 범위 | SHA | 결과 | 원본 하위 경로 |
|---|---|---|---|
| 새 실행·언어·기존 설치기 집중 | `b0675386a1` | 94 통과 | `operations-green/run-1.txt` |
| optional CLI·signed stack·설치 무변경/rollback | `a1f0252d0a` | 75 통과 | `site-operator-green/run-1.txt` |
| 실제 Chromium, 새 영어 선택 + 기존 queue | `a1f0252d0a` | 26 통과, skip 0 | `operations-browser/run-1.txt` |
| 전체 Console Node | 같은 화면 소스 | 343 통과, skip 0 | 세션 실행 및 원격 Fleet/Node wrapper |
| source manifest·provider·설치 회귀 | `a57d78c070` | 64 통과 | `source-manifest-green/run-1.txt` |
| 읽을 수 있는 원문·고정 모델 출력·설치 | `b1f18674b2` | 11 통과 | `model-adapter-green/run-1.txt` |
| Discord gateway/reply/대화/실행/Console 공존 | `b1f18674b2` | 263 통과 | `discord-coexistence/run-1.txt` |
| 로봇 목록/저장소 장애 HTTP 처리·명시적 실행·시험 규칙 | `a8bc6debd0` | 43 통과 | `navigation-errors-green/run-1.txt` |
| 등록된 FULL 22개 invocation | `7b7a367014` | 28,581 통과, 3 실패, 1,952 skip | `operations-full/run-1.txt` … `run-22.txt` |

FULL은 `affected --base 468013c665 --json`의 두 invocation 배열을 모두 full_invocations로 지정했다. Fleet 묶음 5,638개와 공용/CORE 계약 묶음 6,384개는 통과했다. skip은 통과에 더하지 않았고 실제 Chromium과 실제 모델은 opt-in으로 따로 실행했다.

FULL의 실패 세 건은 `test/known_failures.py`에서 모두 NEW였다.

- `test_ci_dependencies.py::test_no_test_module_defines_a_nose_style_setup_function`: 새 실행 시험의 setup 헬퍼를 execution_fixture로 고쳤다. `a8bc6debd0`의 43개 회귀에 해당 guard 통과를 포함했다.
- `test_jpeg_relay.py::test_reused_pids_from_state_are_never_signalled`: recorder 프로세스가 종료되지 않아 종료 표식을 쓰지 않았다.
- `test_rosy_auto_update_apply.py::test_real_host_kills_the_whole_process_group_on_timeout`: timeout 뒤 자식 프로세스가 여전히 살아 있다고 관측했다.

마지막 두 시험은 변경 전 `468013c665`에서 정확한 node ID로 실행해 2개 모두 통과했다(`process-baseline/run-1.txt`). 관련 시험·recorder·native updater 소스는 기준과 차이가 없었다. 이것만으로 FULL 실패 원인이나 비결정성을 확정하지 않는다. 알려진 실패 목록에 추가하거나 한도를 완화하지 않았고, 실패한 같은 SHA를 반복해 통과 결과로 덮지 않았다. **두 FULL 실패는 미해결이며 전체 통과·운영 GO로 표시하지 않는다.**

## 실제 모델 평가

모델 PC의 기존 `qwen3-vl:8b-instruct` 고정 digest와 8192 context를 확인했다. 다른 모델을 다운로드하거나 운영 profile을 교체하지 않았다. opt-in 시험은 기존 모델을 로드할 수 있고 10분 유지한다. 실제 추론은 가상의 r1 관측만 사용했고 Task/장치/보호 설정을 건드리지 않았다.

| 실제 평가 단계 | 관측과 수정 |
|---|---|
| `a1f0252d0a` | 인사에서 r1의 IDLE 상태를 서술해 기존 CHAT 검증기가 거부했다. 화면에 사용하지 않는 설명을 schema의 Classified 단일 값으로 제한했다. |
| `7b7a367014` | 평가 영수증 생성 시 큰 소스 목록이 추론 패킷용 canonical의 16KB 제한에 걸렸다. 400파일 회귀로 재현하고 기존 배포용 source_digest를 재사용했다. 추론 크기 제한은 유지했다. |
| `a57d78c070` | 10/19 통과, 부정문/분류 실패로 FAIL. 실패 로그를 보존했다. 해당 임시 원본 영수증은 pytest 보존 기간이 지나 회수하지 못했다. |
| `fbeb8abbf7` | 의미 분류 우선순위를 명시해 15/19 통과. 영어 10개는 통과했으나 한국어 네 개가 실패했다. FAIL 영수증도 회수·해시 확인했다. |
| `b1f18674b2` | JSON의 이스케이프된 한국어만 보던 경로에 기존 Discord와 같은 읽을 수 있는 최신 원문을 추가했다. 한국어 9개·영어 10개, 총 19/19 통과 및 영수증 검증 성공. |

각 수정은 서로 다른 source SHA로 평가했다. 사례 기대값을 낮추거나 실패를 제외하지 않았다. schema 회귀의 최초 mock은 metadata가 불완전해 잘못 실패했으며, fixture를 고친 뒤 enum 누락/원문 누락을 각각 유효한 RED로 확인했다. 정확한 언어 분류 성능을 일반화하는 별도 holdout/현장 발화 평가는 하지 않았다. 19개는 고정 개발·수용 사례에 대한 결과다.

PASS 원본은 `model-bilingual-readable/evaluation.json`, FAIL 15/19 원본은 `model-bilingual-priorities/evaluation.json`에 보존했다. 설치할 broker는 영수증에 결속된 정확한 SHA/profile/source 목록과 일치해야 한다. 이 영수증을 AI PC에 설치하거나 Fleet의 primary_admitted를 켜지는 않았다.

## 기존 Discord의 실제 읽기 전용 확인

이전 2026-10-12 배포 기록에서 계정 매핑 충돌과 복구를 확인한 뒤 현재 사이트 컨테이너를 읽었다. 기존 intake 설정·Bot token 파일·서버/채널 binding이 있고, 사용자 매핑은 한 개, replies_enabled는 true였다. 토큰 값이나 실제 ID는 출력/공개 기록에 남기지 않았다.

현재 Bot 자격으로 Discord의 `GET /api/v10/users/@me`와 설정된 채널 GET을 실행해 모두 HTTP 200을 받았다. Bot ID, 채널 ID, 서버 ID가 설정과 일치했다. 외부 메시지 송신·사용자 대화 읽기·설정 변경·재시작은 하지 않았다. 최근 container log에 Discord 행이 없어 Gateway READY나 실제 MESSAGE_CREATE 처리를 관측했다고 주장하지 않는다. 실시간 멘션 수신/응답/작업 결과 통지는 별도 수용 대상이다.

263개 모의 공존 시험에서는 기존 Discord 원장·reply·의미 승인·자연어 실행과 Console의 명시적 Task 접수가 같은 실행 owner를 사용하며 서로의 신원을 위장하거나 callback을 덮지 않는 경로를 확인했다. 실제 Discord 메시지가 실제 장비 작업을 수행했다는 증거는 아니다.

## 남은 운영 조건과 판단

읽기 전용 별도 검토는 `468013c665` → `a1f0252d0a`의 실행 권한/Task 거래/Discord 공존/설치 보호·rollback/음성 취소를 추적해 Critical/Important 발견이 없었다. 이후 모델 입력·소스 해시·HTTP 오류 수정은 위 재현 시험과 실제 모델 평가로 확인했으며 그 검토 범위에 소급 포함하지 않는다.

새 LLM/ASR/TTS 후보는 공식 지원·라이선스와 평가 절차까지 조사했다. AI/모델 PC의 조회 시점 GPU는 RTX 5080 Laptop 16GB였고 기존 Qwen 모델만 설치 목록에 있었다. 시스템 Python에서 STT/TTS 패키지를 찾지 못한 결과는 모든 venv의 부재 증거로 쓰지 않는다. 실제 한국어·영어 녹음, 브라우저 로컬 팩/마이크, ASR/TTS 정확도·지연·동시 처리 실측은 남아 있다.

운영 전에는 미해결 FULL 프로세스 종료 실패 조사, 같은 SHA의 Discord 보호 snapshot/독립 평가·operator 설치 readback, 서명된 사이트 후보/배포/rollback, HTTPS 로그인과 실제 채널 수신·응답, 승인된 장치 이동·취소·UNKNOWN 수용이 필요하다. signed image 빌드·실제 AI PC 설치·Fleet 활성화·실기 이동·외부 메시지 송신·merge/push는 하지 않았다.

선택: 새 실행 서버 대신 기존 Task owner를 재사용했고, LLM은 분류/근거만 제안한다. 다국어는 ko-KR/en-US부터 닫힌 계약으로 시험했고 새 음성 서버 의존성은 추가하지 않았다. 이 선택 때문에 자연어 자동 실행과 서버 음성은 후속 구현/평가가 필요하다. 과거 D-810 기록과 현재의 운영 미수용 상태를 서로 덮어쓰지 않는다.

## 원본 무결성

FULL 디렉터리 digest는 파일명을 사전순 정렬해 `파일명 + NUL + 파일 SHA-256 소문자 hex + LF`를 연결한 UTF-8 문자열의 SHA-256이다. 파일 22개, sha256: `56389f84f06b3de4e3b4fe29a90800cc4c615bef9055171ea64a29fcec2785bd`.

| 원본 | SHA-256 |
|---|---|
| `model-bilingual-readable/evaluation.json` | sha256: `08626828be7187367fbcff97e39d1288754782c974c92dca578a35c3aabd9f37` |
| `model-bilingual-priorities/evaluation.json` | sha256: `016b70551cd0e6fff7a1e939756552c1039a7a78ed4d4d6156c3595449bd06c8` |
| `discord-coexistence/run-1.txt` | sha256: `3c384ade1259bce1c1a4c81db6eb691d2e7331e71d2aab160612f903f3bd051f` |
| `navigation-errors-green/run-1.txt` | sha256: `81d948959da8cdedc4258ce0299a5078cdd00267af55c0cb0b7ff3d50018a43b` |
| `operations-browser/run-1.txt` | sha256: `64576d99c4cef913eb9b9bd4e5a096807fe2289f77eb08a67c7de2e43fc6349d` |
| `source-manifest-green/run-1.txt` | sha256: `0144030f16f5b715cfde9f0496be3897eb00b9036a171a534fbefc85695d6439` |
| `process-baseline/run-1.txt` | sha256: `99db33d5c94c6f7da021687c7391181685cc33299c5435b1c861e2db3be3ec87` |
