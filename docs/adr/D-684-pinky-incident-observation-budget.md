# D-684: Pinky 사건 재관측과 지속 예산 원장

- Status: Accepted
- Date: 2026-10-12
- Related: D-640, D-672, D-679, D-681

## Context

차선 사건은 Mission action/attempt와 동일한 scope가 아니다. 기존 `get_mission_status`와 `MissionModelTurnStore`는 Mission의 principal·workcell·action·dispatch fence를 요구하므로 Pinky 재관측이나 정상 종결의 근거로 전용할 수 없다. 기존 D-640 원장은 같은 사건의 다음 generation을 거부하므로 반복 관측 예산의 부모 원장으로 약화해서도 안 된다.

## Decision

Fleet이 opt-in v2 사건 worker와 별도 부모/시도 원장을 소유한다. `StuckResolverLoop.run_once()`의 shared gather 이후 현재 Assessment를 입력으로 삼는다. 정상은 모델·명령 0회로 미개입을 기록한다. 실제 baseline producer가 검증한 선택만 비교 기준으로 사용하며 `WAIT`를 `reobserve`로 추정하지 않는다.

공통 tool catalog에 읽기 전용 `get_incident_status`를 추가한다. arguments는 빈 object이며 호출 scope의 subject/case와 근거를 Fleet이 고정한다. 모델이 로봇·URL·파일 경로를 지정하지 못한다. trusted observation adapter는 기존 polling이 만든 immutable snapshot·Assessment를 소비하고 현재 사건·관측 시간·revision을 반환한다. 재관측은 독립 기존 polling의 새 관측을 기다리거나 별도 CORE 상태 읽기 경로를 사용한다. cached 결과를 새 관측으로 계산하지 않는다. shared gather는 교통·인계·속도 관리 효과가 있으므로 모델의 읽기 도구가 직접 재호출하지 않는다. 이는 기존 Mission dispatcher를 호출하지 않으며 Mission schema·dispatcher에서 사건 도구를 제외한다.

부모 원장은 `(subject_id, case_id)`에 고정 프로파일 SHA·정책 revision·시작 시간·전체 deadline·호출/관측/비용 상한을 보존한다. 시도 원장은 각 입력 hash·관측 revision·종류·상태를 기록한다. 실행 전에 원자적으로 누적 예산을 예약하며 새 관측·재시작·모델 교체로 초기화하지 않는다. 제출 이후 결과 불명은 UNKNOWN으로 보존하고 동일 시도를 재발행하지 않는다. 사건 소유자나 프로파일이 바뀌면 자동 작업을 중단한다.

루프는 기본 판정, 허용된 읽기 재관측, 최신 상태 재검사, 동일 사건의 조건부 재평가, 최종 미해결 인수 순서로 진행한다. 위험 상태에서는 처리 명령을 차단하고 허용된 읽기만 수행할 수 있다. worker는 직접 장치 명령이나 `/cmd_vel`을 발행하지 않는다. 물리 처리 연결은 기존 CORE admission과 독립 수용을 통과한 별도 단계다.

모델 합의와 `success_check.expected_facts`는 종결 receipt가 아니다. 요청 이후의 최신 CORE 관측과 원래 사건의 종결 전이가 함께 확인돼야 한다. 다른 사건·오래된 관측·로스터 이탈·사람 소유 전이는 성공으로 기록하지 않는다. 결과 불명·미지원 처리·전체 예산 소진은 사건과 시도·판정 차이·위험·필요 검토를 기존 인수/outbox에 전달한다.

활성화는 shadow 기록 → 읽기 adapter 수용 → 독립 calibration 프로파일 수용 → 제한 운영 루프로 나눈다. 소스의 정적 `ready`/`isolated` 표식은 실제 호스트 admission receipt를 대신하지 않는다. 미수용 제공자는 호출하지 않는다. D-679 첫 GLM 시험의 1회·30초·1,024 토큰·무재시도 한도는 별도로 보존한다.

## Verification

정상 미호출, 동일 사건 재관측, 다른 사건·사람 인수·만료·위험 명령 거부, 재시작 후 예산 보존, 동시 claim, UNKNOWN 재발행 금지, 선언한 성공과 실제 readback 구분을 원격 시험한다. 실제 AI PC 호출·독립 품질·Pinky 현장 수용은 각각 별도 증거다.
