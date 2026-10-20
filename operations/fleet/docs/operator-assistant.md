# 통합관제 관제 AI

운영자는 기존 `/console`의 **관제 AI** 단추에서 대화를 연다. 이름 있는 운영자만 이용한다. 대화는 조회·설명을 담당하고 모델 답변은 실행을 승인하지 않는다. 작업 화면에서 목적지를 지정하거나 아래의 구조화된 이동 API로 명시적으로 접수한다. 비상정지는 기존 단추를 사용한다.

## 설정과 활성화

기본은 모델 미설정 상태다. 패널은 연결 준비 중을 표시한다. 설정을 임의로 만들어 모델 승격을 대신하지 않는다.

1. 모델 PC에서 후보 커밋·고정 모델을 검증하고 `python -m deploy.ai_pc.operator_acceptance --source-commit <full-sha> --output <private-output>`으로 독립 평가 증거를 만든다. 이 명령은 모델을 호출하므로 모델 PC의 승인된 평가 환경에서만 실행한다.
2. 기존 D-728 `deploy/site/install_conversation_broker.py` 절차로 **같은 SHA**의 Discord 보호 snapshot·venv·고정 SSH wrapper를 먼저 설치/검증한다. operator 평가 원본은 root 보호된 `/root/rosy-conversation-reviewed/` 아래에 검토된 hash와 함께 둔다. 웹 대화 승인은 별도이며 기존 Discord 평가를 재사용하지 않는다.
3. 그 snapshot의 Python으로 `deploy.site.install_operator_broker.main`을 실행한다. 인자는 `<보호된-평가파일> --proof-sha256 <평가-hash> --conversation-config-sha256 <기존-보호-설정-hash> --check`다. 검사 후 `--check` 없이 설치한다. 업데이트는 `--previous-config-sha256 <검토한-이전-operator-설정-hash>`도 필요하다. source/profile/전체 사례/suite hash/평가 시각을 검증하며, 7일 만료·source 불일치는 설치를 거부한다. readback 실패 시 설정을 복원한다. 기존 Discord·SSH·유료 spent marker는 변경하지 않는다.
4. Fleet의 private 설정에는 host, ssh_port(22 또는 2222), key_file(`/run/rosy-deliberation/broker.key`), known_hosts_file(`/run/rosy-deliberation/known_hosts`), source_commit, semantic_evidence_sha256, valid_until, primary_admitted를 둔다. 명시적 이동 연결은 별도 `execution_enabled`이며 기본 false다. 실제 주소·키·채운 설정은 공개 저장소에 넣지 않는다.
5. 서명된 사이트 후보 배포 절차를 사용한다. Compose 기본/페어링 구성은 기존 Fleet 전용 `/etc/rosy/fleet-deliberation:/run/rosy-deliberation:ro`에서 `--assistant-config-optional /run/rosy-deliberation/operator.json`을 읽는다. 부재는 OFF, 잘못된 파일/권한 오류는 시작 거부다. CLI의 필수 `--assistant-config <private-config>`와 혼용하지 않는다. Discord의 intake 설정·토큰은 기존 경로를 유지한다.
6. 배포 SHA·컨테이너 이미지·HTTPS 로그인·기존 비상정지·두 채널 상태·모델 스모크를 readback한 뒤 운영 준비를 기록한다. 승인 만료/모델 미설정은 HOLD/UNKNOWN이며 자동 재호출하지 않는다. 코드 시험은 실제 설치 수용을 대신하지 않는다.

설치기 실행에는 snapshot의 root·Decision·foundation source 경로가 필요하다. 기존 설치기의 `python_code(snapshot, 'from deploy.site.install_operator_broker import main;sys.exit(main())')`가 생성하는 `-I -B -c` 호출을 같은 보호 venv에서 사용한다. 일반 작업 디렉터리나 임의 PYTHONPATH에서 root 설치를 하지 않는다. 보호 설치·서명된 운영 배포·현장 실행 수용은 이번 소스 변경만으로 완료 처리하지 않는다.

## 명시적 이동 접수와 결과 확인

`POST /api/fleet/assistant/messages/{request_id}/navigation`의 본문은 `{"robot_id":"r1","x":1.0,"y":2.0,"yaw":0.0}` 형태다. 현재 기명 운영자가 자기 CONTROL 종단 요청에 대해 30초 안에 직접 지정한 좌표만 받는다. 대화의 선택 로봇과 본문의 로봇이 같아야 한다. 모델 승인과 `execution_enabled=true`가 모두 필요하고 권한은 Task 거래 안에서 다시 확인한다.

이 경계는 기존 `IntentExecution`과 Task store로 접수한다. 동일 운영자/요청 ID는 같은 Task를 반환하며 변경된 좌표는 409다. 자동 재전송이나 새 worker는 없다. 반환값의 `task.task_id`로 기존 Task 조회/취소 API와 작업 화면을 사용한다. queued/accepted를 도착/완료로 표시하지 않는다. 진행 중인 일의 취소·UNKNOWN은 기존 owner가 판정한다. 현재 패널은 기존 작업 화면을 연결하고 이 API는 구조화된 클라이언트/통합 시험용 접수 경계다. 자연어 자동 실행·여러 단계 작업·새 목적지 입력 폼은 추가하지 않았다.

## 음성 사용

**대화·음성 언어**에서 한국어 또는 English를 선택한다. 지원되는 브라우저에서 **음성 입력 준비**로 해당 로컬 팩을 준비하고 **말하기**를 누른다. **인식 마치기** 뒤 입력문을 수정·전송한다. 언어 변경·계정 변경·페이지 이탈은 인식을 취소한다. 인식문이 자동 명령으로 전송되지는 않는다. **답변 읽기/읽기 중단**은 선택 언어의 로컬 음성만 사용한다.

해당 언어 로컬 인식이 없는 브라우저에서는 텍스트를 사용한다. 상시 청취·클라우드 인식 대체·원음 저장은 없다. 실제 한국어/영어 발화 품질은 별도 수용 대상이다. 브라우저 지원 조건은 [Microsoft 문서](https://learn.microsoft.com/en-us/microsoft-edge/web-platform/speech-recognition-api)를 참고한다. 서버 음성 모델 후보와 실측 절차는 [다국어 모델 평가](operator-models.md)에 있다.

## 유지보수 위치

### D-831 전처리

인용문 안의 조합형 한글도 검색용 NFC 사본에서 검사한다. 등록 이름에 유의미한 공백이 있으면 입력 사본 정규화를 생략한다. 원문과 모델용 인용문은 보존하며 [추가 Unicode 검증](../../../docs/validation/operator-preprocessing-2026-10-21b/result.md)을 따른다.

Console의 `d831-preprocessing-v1`과 Discord의 `d728-semantic-v3-d831`은 공통 Decision `conversation/preprocessing.py`를 사용한다. 원문·요청 ID·신원·멱등성은 그대로 두고 해석용 사본의 NFC와 제한된 수평 공백만 정리한다. 인용문과 등록 이름의 공백·식별자·부호·단위는 보존한다. 같은 정규화 결과라도 서로 다른 원문을 한 요청으로 합치지 않는다.

등록 이름은 유일한 canonical ID로만 해소한다. 공백 정리로 충돌하는 이름, 미해결 지시어, 부정·조건·인용된 동작, 복합 행동 후보는 재질문한다. 이 규칙은 실행을 허가하지 않는 보수적인 차단이며 완전한 형태소/의미 분석기가 아니다. `A 말고 B 상태`처럼 부정 범위가 있는 조회는 해당 로봇의 근거로 답한다. 현재 사실·관측 시각·최근 이력은 요약으로 버리지 않는다.

새 Discord 프로파일은 자동 실행 worker를 설치하지 않는다. 제안은 원장과 응답에만 기록한다. 자연어 확인 계약은 별도 구현 대상이며 Console의 기존 명시적 좌표 접수 경계는 유지한다. 기존 Discord 프로파일은 기존 입력/실행 경로를 유지한다. 새 프로파일 설치에는 같은 SHA의 독립 ko/en 평가와 전처리 소스가 포함된 보호 snapshot이 필요하다.

broker는 실제 `prompt_eval_count`, `eval_count`, 경과 시간과 전처리 digest를 내부 응답에 붙인다. Fleet는 digest를 다시 검사하고 `operator_inference` 구조화 로그에 입력 hash·profile/source와 사용량만 기록한다. 원문·운영자/채널 ID는 사용량 로그에 넣지 않으며 일반 답변에서 사용량 필드를 제외한다. 모델이 직접 반환한 사용량은 거절한다.

입력은 실제 응답 계측에서 7168토큰, 생성은 1024토큰 이하를 검증한다. 정확한 사전 토크나이저는 없으므로 이 검사는 호출 전 상한이나 backend의 무잘림을 보장하지 않는다. 과다 사용량·잘못된 계측은 결과를 거절하고 자동 재호출하지 않는다. 고정 모델 평가에서 질문 사본 제거가 분류를 악화시켜 JSON 원문과 읽기용 정규화 사본은 유지했다. 절감률은 [검증 기록](../../../docs/validation/operator-preprocessing-2026-10-21/result.md)의 실제 동일 사례 결과만 사용한다.

| 변경 | 소유 위치 |
|---|---|
| 입력·응답 계약 | `contracts/foundation/core_common/protocol/assistant.py`, API v1.290 |
| 문맥·대화·영속 상태 | `operations/fleet/fleet/server/assistant/` |
| 모델 입력·검증 | `operations/decision/src/rosy/decision/conversation/operator.py` |
| 공통 정규화·등록 이름·행동 후보 차단 | `operations/decision/src/rosy/decision/conversation/preprocessing.py`, `codec.py` |
| 고정 추론·평가 | `deploy/ai_pc/operator_broker.py`, `operator_acceptance.py` |
| 명시적 이동 연결 | `operations/fleet/fleet/server/assistant/execution.py` → 기존 `IntentExecution`/Task owner |
| 보호 설치 | `deploy/site/install_operator_broker.py`, 기존 D-728 설치기 |
| 화면·음성 | `applications/fleet/web/assistant/` |

원인 조사 시 요청 ID로 대화 원장 상태, 현재 관측 시각, 모델 승인·source binding을 먼저 확인한다. UNKNOWN을 지우거나 새 키로 자동 재호출하지 않는다. 같은 요청 확인은 같은 ID와 원문을 다시 보내며, 다른 본문이면 409다. 기능 비활성화는 신규 접수를 보류하며 기존 원장과 작업 기록을 삭제하지 않는다.

## 원격 시험

`tools/remote/remote_pytest.py --log-dir <저장소-밖-폴더> -- <대상> -q`로 커밋한 SHA를 시험한다. 실행/권한은 `test_assistant_execution.py`, `test_assistant_navigation_routes.py`, 배포는 `test/test_operator_broker_install.py`, `test/test_conversation_broker_install.py`, 언어는 `test_assistant_languages.py`, `test_assistant_options.py`다. Fleet 시험 파일은 `operations/fleet/test/` 아래에 있다. `test_channel_natural_execution.py`, `test_channel_conversation.py`, `test_conversation_followup.py`, `test_discord_gateway.py`, `test_discord_replies.py`를 함께 시험한다. 브라우저는 `ROSY_RUN_BROWSER_TESTS=1`로 `test_assistant_browser.py`와 기존 queue 회귀를 실행한다.

실제 모델 시험은 모델 PC만 선택해 `ROSY_RUN_OPERATOR_MODEL_TESTS=1 ROSY_OPERATOR_EVALUATION_OWNER=model_pc ROSY_OPERATOR_SOURCE_COMMIT=<전체-SHA> test/test_operator_model_acceptance.py -q -s`를 원격 runner에 전달한다. 기존 고정 모델을 8192 context로 로드할 수 있고 10분 유지한다. 새 모델 다운로드·보호 설정 설치·장치 명령은 없다. 출력 receipt는 임시 평가 증거이며 운영 승격을 자동 수행하지 않는다.
