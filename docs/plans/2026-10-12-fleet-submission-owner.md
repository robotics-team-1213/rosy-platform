# D-731 Fleet 제출 책임 분리 및 연결

추가 감사에서 모델 제출에 기존 작동 AI의 BACK floor 재사용이 누락된 것을 확인했다. 실제 6 NEW를 재현하고 기존 `ai_proposal_invalid`를 최종 guard에 연결했다. 기존 R3의 교차로·지도·동료·현장 사실·규칙 예산·거절 제한을 유지한다. resolver chain 없는 직접 제출도 거절한다. 실제 provider/현장 활성화는 여전히 수행하지 않았다.

SOURCE 검토 반영 후 submission은 223줄, 부모 stuck은 3296줄, operating은 318줄이다. 초기 203/294 기준과 기존 부모 기준을 유지한다. 모델 claim과 기존 사건 PENDING은 같은 transaction으로 기록하며 커밋 뒤에만 관제에 표시한다. 감사 기록 실패·HOLD·기한 만료로 롤백되면 제출과 관제 표시가 모두 없고 POST하지 않는다. 실제 durable terminal을 worker가 소비하며 UNKNOWN/REFUSED는 최종 미해결 인수, ACK는 새로운 정상 관측 확인으로 이어진다.

실제 worker의 SOURCE provider → 기존 HttpRobotClient → 모델 ACK → 새 정상 관측 → 영속 closure/report 흐름에서 CLEARANCE_OBSERVED와 UNVERIFIED action credit를 확인한다. 연결 단절과 HTTP ACK 뒤 폐기에서도 durable UNKNOWN·최종 인수 1회·uncertain 재시작 조회·무재전송을 확인한다. 이는 실제 모델·물리 복구 성공이나 독립 현장 평가가 아니다.

기존 loop._answer의 실제 규칙 dispatch를 `stuck/submission/dispatch.py`로 이동한다. 루프의 `_answer`·`_model_answer`는 이 실제 함수의 method binding을 사용한다. 같은 모듈이 기존 HTTP client와 D-724 최종 guard, D-730 원장을 연결한다. `owned.py`는 취소가 SQLite 기록보다 먼저 끝나지 않도록 소유 작업을 기다린다. provider·정답 평가·approval store는 이 모듈이 소유하지 않는다.

초기 실제 모듈은 dispatch 189, owned 13, init 1로 203 physical lines이다. 부모 stuck은 기존 writer를 뺀 3284줄로 원래 3317+150 이하이며 원래 한도를 올리지 않는다. automation·execution·ledger·operating 기존 기준도 유지한다. 독립 SOURCE 검토와 실제 원격 회귀·설치 검증을 병합 전에 수행한다.

호출자는 기존 resolver loop, worker의 검증 후보 후 optional recovery_submit, 기존 ROOT factory다. operating ROOT 설정 없이 legacy 동작과 읽기 전용 worker를 보존한다. SOURCE fixture의 accepted 원본은 현장 증거가 아니다. 기존 결과 관측·피드백·최종 인수와 실제 모델/현장 수용은 전체 목표에 계속 포함한다.
