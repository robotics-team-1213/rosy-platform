# D-821 관제 AI 보호 배포·명시적 이동 연결·다국어 평가

**Status:** Accepted for implementation (2026-10-20). 실제 모델·음성·장치·운영 배포 수용은 별도다.

## Context

D-810의 웹 대화는 조회 전용이며 Discord 실행 소유자를 설치하지 않는다. 사용자는 운영 배포와 실행 연결을 시험할 구조, 한국어·영어 모델 후보 조사와 기존 Discord 점검을 요청했다. 모델 문장을 실행 승인이나 실제 완료 근거로 쓸 수 없다.

## Decision

- 대화는 `READ_ONLY`, `action_admissible=false`를 유지한다. 기명 운영자가 원본 CONTROL 대화에 연결해 로봇·유한 좌표를 명시적으로 POST한 이동만 기존 `IntentExecution` → `FleetTaskService`에 접수한다. 새 worker·직접 CORE 호출·Discord 식별자 대용은 없다.
- 실행 연결은 독립 `execution_enabled=false` 기본값이다. 현재 권한·모델 승인·원본 소유권·CONTROL 종단·선택 로봇·30초 유효성을 접수 전과 Task 거래에서 다시 검사한다. 같은 principal/request는 같은 기존 Task 멱등 키를 쓴다. 좌표 변경은 충돌이며 실행 결과는 기존 Task API의 관측으로 확인한다. 대화 결과를 완료로 바꾸지 않는다.
- 기존 동일 SHA의 Discord 보호 설치와 SSH wrapper를 재사용한다. 추가 operator 설치기는 source closure와 독립 평가의 hash/profile/사례/시각을 검증하고 operator 설정만 원자적으로 교체·readback·rollback한다. Discord 설정과 SSH 권한은 바꾸지 않는다. `--check`는 설치·추론을 하지 않는다.
- locale은 우선 `ko-KR`, `en-US`로 닫는다. 텍스트·모델 입력·근거·고정 응답과 브라우저 로컬 음성 선택에 사용한다. 원음은 업로드하지 않고 언어 변경은 인식을 취소한다. 기존 locale 없는 요청은 한국어로 읽어 멱등 재시도를 보존한다.
- 기존 승인 모델 digest를 유지하고 profile revision을 `d821-multilingual-v1`로 구분한다. 후보 모델·STT/TTS의 공식 지원/라이선스를 조사하되 실측 평가 없이 운영 승격하지 않는다. 독립 평가에 두 언어와 부정/인용/타인 정보/안전 우회 사례를 포함하고 7일 유효 기간을 검증한다.

## Consequences

통합관제와 Discord는 대화 신원이 분리되면서 같은 Task/장치 실행 소유자를 거친다. 이 단계의 자연어 모델은 실행 계획이나 자유 형식 완료를 생성하지 않는다. 목적지 입력은 기존 작업 화면/구조화된 클라이언트에서 담당한다. 새 모델과 서버 음성 엔진의 실제 설치·한국어/영어 발화 품질·외부 Discord 송수신·장비 동작은 각각 증거가 필요하다.
