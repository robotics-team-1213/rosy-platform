# 통합관제 관제 AI

운영자는 기존 `/console`의 **관제 AI** 단추에서 대화를 연다. 이름 있는 운영자만 이용하며 현재 버전은 조회 전용이다. 이동·작업 요청은 기존 작업 화면에서 진행한다. 비상정지는 기존 단추를 사용한다.

## 설정과 활성화

기본은 모델 미설정 상태다. 패널은 연결 준비 중을 표시한다. 설정을 임의로 만들어 모델 승격을 대신하지 않는다.

1. 모델 PC에서 후보 커밋·고정 모델을 검증하고 `python -m deploy.ai_pc.operator_acceptance --source-commit <full-sha> --output <private-output>`으로 독립 평가 증거를 만든다. 이 명령은 모델을 호출하므로 모델 PC의 승인된 평가 환경에서만 실행한다.
2. AI PC 소유자의 승인 절차로 보호된 source closure와 별도 `/etc/rosy-deliberation/operator.json`을 설치한다. 기존 Discord 평가/config를 웹 대화 승인으로 재사용하지 않는다. 호스트 설정은 source_commit, `OperatorProfile`의 profile, valid_until, semantic_evidence_sha256, files(path→SHA-256)이며 코드 전체와 평가 영수증을 묶는다. 코드 hash 목록에 해당하는 영수증의 source_manifest_sha256이 맞아야 한다. 운영 설치 도구와 root 소유권 검증을 우회한 수동 복사는 지원하지 않는다.
3. Fleet의 private 설정에는 host, ssh_port(22 또는 2222), key_file(`/run/rosy-deliberation/broker.key`), known_hosts_file(`/run/rosy-deliberation/known_hosts`), source_commit, semantic_evidence_sha256, valid_until, primary_admitted를 둔다. 실제 주소·키·채운 설정은 공개 저장소에 넣지 않는다.
4. 기존 Fleet CLI의 `--assistant-config <private-config>`로 선택한다. 구성·보호 broker가 준비되지 않았거나 승인 만료이면 요청은 HOLD/UNKNOWN으로 남고 자동 재호출하지 않는다. 실제 모델 스모크와 로그를 확인한 뒤 운영 준비로 표시한다.

현재 변경은 보호 설치·운영 활성화를 실행하지 않았다. 기존 D-728 설치 도구는 웹 영수증의 신규 설치/갱신까지 자동화하지 않으므로, 이 보호 설치 지원과 독립 평가 완료 전에는 운영에서 `primary_admitted=true`로 켜지 않는다.

## 음성 사용

지원되는 브라우저에서 **음성 입력 준비**로 로컬 한국어 팩을 준비하고 **말하기**를 누른다. **인식 마치기** 뒤 입력문을 수정·전송한다. 인식문이 자동 명령으로 전송되지는 않는다. **답변 읽기/읽기 중단**은 로컬 한국어 음성만 사용한다.

로컬 한국어 인식이 없는 브라우저에서는 텍스트를 사용한다. 상시 청취·클라우드 인식 대체·원음 저장은 없다. 실제 한국어 품질은 아직 수용하지 않았다. 브라우저 지원 조건은 [Microsoft 문서](https://learn.microsoft.com/en-us/microsoft-edge/web-platform/speech-recognition-api)를 참고한다.

## 유지보수 위치

| 변경 | 소유 위치 |
|---|---|
| 입력·응답 계약 | `contracts/foundation/core_common/protocol/assistant.py`, API v1.289 |
| 문맥·대화·영속 상태 | `operations/fleet/fleet/server/assistant/` |
| 모델 입력·검증 | `operations/decision/src/rosy/decision/conversation/operator.py` |
| 고정 추론·평가 | `deploy/ai_pc/operator_broker.py`, `operator_acceptance.py` |
| 화면·음성 | `operations/site_ui/console/assistant/` |

원인 조사 시 요청 ID로 대화 원장 상태, 현재 관측 시각, 모델 승인·source binding을 먼저 확인한다. UNKNOWN을 지우거나 새 키로 자동 재호출하지 않는다. 같은 요청 확인은 같은 ID와 원문을 다시 보내며, 다른 본문이면 409다. 기능 비활성화는 신규 접수를 보류하며 기존 원장과 작업 기록을 삭제하지 않는다.
