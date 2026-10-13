## D-685 Fleet 자율 대기·조건 회복·검증된 재계획

**Status:** Accepted (2026-10-12)

### Context

사용자는 사람이 거의 개입하지 않는 Fleet을 요청했다. D-674/D-678은 실행 경계를 연결했으나 R5와 교착 재계획이 사람에게 기본 인계된다. 운영자의 최초 승인 범위 안에서는 자동 복구와 지속 관측이 기본이다.

### Decision

1. 기존 site config의 `fleet.stuck_resolver.autonomous_robots`는 승인된 자율 운영 robot ID 목록이다. 기본 빈 목록은 현장 활성화를 주장하지 않기 위한 기존 배포 경계다. CLI → create_app → stuck resolver와 trip/traffic owner에 동일 목록을 연결한다. 새 ROS publisher나 범용 실행기를 만들지 않는다.
2. 해당 로봇의 기존 자동 escalation은 별도 내부 Hold로 기록한다. UI는 `auto_hold:<reason>`을 자동 대기·관측 중으로 표시한다. 실제 human claim, human class와 AI MANUAL, 실행 credential 누락은 승인 범위 밖 예외이며 사람 인계를 유지한다. E-stop은 대기하되 자동 해제하지 않는다.
3. 접수된 WAIT/R5는 같은 사건의 기존 rule/AI admission이 실행 가능한 후보로 바뀔 때만 다시 판단한다. 동일 WAIT를 polling마다 재전송하지 않는다. 시작 시각·rule budget·AI cap·거절 이력은 초기화하지 않는다. 소진과 기한 초과는 대기·관측을 유지한다. 불명 이동은 재발행하지 않는다.
4. 접수 후 unresolved는 이전 규칙을 retire하고 다른 허용 후보만 검토한다. 자율 경로에서는 관측 창 종료 시간만으로 기존 AI 제안을 다시 발행하지 않는다. 접수된 자동 WAIT도 Outcomes/원장에 기록하며 human으로 둔갑시키지 않는다.
5. 결정적 교착 우회 후보는 기존 계획 검사와 CORE/trip 소유권을 유지한 채 자동 확인한다. AI 선택을 위조하거나 AI 예산을 소비하지 않는다. capability/pose await 후 동일 live/hold/route/stop generation 및 승인 범위를 재검사하며 활성 지도는 적용 직전 확인한다. 우회 실패·UNKNOWN은 점유를 유지한 자동 대기다.
6. Fleet 관측 기록은 기기·원본 관측 시각·수신 시각·출처·신선도·사건/명령/결과를 보존하고 분석·재생·학습 데이터 준비에 사용한다. 시스템 판단은 정답 라벨이 아니며 원본 기록과 학습 승격은 구분한다. 학습/배포/현장 활성화는 별도 증거다.

### Existing contracts

D-438/D-577/D-489/D-517의 사람 인계 기본은 명시된 자율 대상의 복구 가능한 사건에 한해 위 계약으로 대체한다. 기존 비대상 경로·human claim·CORE 안전·Action UNKNOWN은 유지한다. D-427/D-429/D-430 소스 소유자와 안전 경계는 유지하며 기록 자료는 소스 드라이브에 저장하지 않는다.

### Consequences

SOURCE 구현과 원격 시험/로컬 머지는 실제 무인 운영 수용이 아니다. 설치 revision·overlay·기기 센서와 시간 정합·물리 정지/복구 수용은 따로 검증한다. [실행 계획](../plans/2026-10-12-fleet-autonomy.md)과 [통합 규칙집](../reference/fleet-rulebook.md)에 범위와 검증을 연결한다.

자율 대상 설정은 durable Task journal과 백그라운드 stuck resolver가 모두 구성된 경우에만 시작한다. 이동 후보는 owner 호출 전에 기존 원장에 `FLEET_STUCK_DISPATCH_PENDING`을 FULL synchronous로 저장하고, 저장/재대조 실패면 전송하지 않는다. 쓰기 await 뒤 law/AI/사람 점유를 다시 확인한다. 이미 전송을 시작한 pending은 확정 receipt 또는 정확한 CORE 사건 종료를 durable 대조한 뒤에만 해제한다. 강제 프로세스 종료로 receipt 기록이 없어도 재시작에서 pending을 동결하며, 기록 손실을 근거로 재발행하지 않는다. 새 코드들은 Fleet 내부 원장 표식이며 CORE receipt를 위조하지 않는다. 저장 매체 자체의 파손은 별도 현장 장애다.
