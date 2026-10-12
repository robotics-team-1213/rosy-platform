# D-728 — 기명 자연어 대화와 기존 조종 owner 연결

- Status: Accepted (source design; implementation and runtime acceptance pending)
- Date: 2026-10-12
- Related: D-720, D-671, D-675, D-517, D-540, D-679

## Decision

사용자가 요구한 결과는 접수 안내나 읽기 전용 상태 worker로 끝나지 않는다.
기명 Discord 사용자가 자연어 인사·상태 질문·후속 대화·명확한 조종 요청을
보내면 실제 AI와 관제가 대화·명확화·안전 보류·기존 실행·결과 회신까지
처리한다. D-720은 원문 결속·예산·UNKNOWN·outbox의 기초로 유지하며,
읽기 전용 조각만으로 이 요구의 완료를 선언하지 않는다.

AI는 현재 소유권에 묶인 제한된 대화 문맥과 신선한 기기/지도/기존 작업
근거를 받아 구조화된 CHAT/STATUS/CLARIFY/CONTROL/REFUSE 결과를 만든다.
기존 `core_common.intent`의 허용 grammar와 Task/Mission/Cell owner를
재사용한다. 모델이 URL·코드·cmd_vel·E-stop 해제나 새 권한을 만들 수 없다.
모델 자유 문장은 장치 상태·실행 성공의 증거가 아니다. 실제 상태와
처리 결과의 회신은 관제 관측·기존 owner receipt/readback을 근거로 만든다.

조종의 기명 권한은 immutable 원문의 현재 operator mapping에서 온다.
모델 분류 자체는 실행 허가가 아니다. 명확한 요청·등록 대상·현재 지도
출처와 revision·기기 capability·law/rule·CORE 안전 조건을 검증하고,
모호함·오프라인·stale·안전 잠금은 구체적인 자연어 명확화/보류로 닫는다.
단순 인사나 상태 요청을 CORE 사건·이동 요청으로 승격하지 않는다.
콘솔에서 다시 누르는 일반 확인은 기본 경로로 추가하지 않으며,
필수 안전 해제·물리 수리·승인 범위 밖 예외에만 사람 개입을 요청한다.

호출/실행 전 영속 예약과 idempotency, 각 await 및 최종 dispatch의 현재
소유권·원문·profile·계획·지도/관측 fence를 지킨다. 실행 불명은 자동으로
다시 보내지 않는다. 진행·보류·장치 결과·목표 검증은 구분하여 같은
대화와 원장에 연결한다. 일반 사건의 기존 calibration/admission과 보호
GLM credential/billing/최초 smoke spent marker를 유지한다.

## Acceptance

- 실제 Discord의 인사와 상태 질문에 접수 이후 자연어 응답이 온다.
- 후속 지시의 대상/문맥은 같은 기명 사용자·채널 안에서 검증한다.
- fake CORE에서 유효한 요청은 기존 owner를 정확히 한 번 호출하고,
  stale·revocation·prompt injection·오프라인·모호함·UNKNOWN은 실행하지 않는다.
- 실제 조종은 연결된 기기의 기존 admission을 통과한 경우만 검사한다.
  장치가 없을 때 모델·원장·회신 검증과 물리 수용을 구분한다.
- 평가/학습 개선은 이 운영 수용 뒤 실제 결과·부작용·독립 기준과 결속한다.
