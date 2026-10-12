# D-731 Fleet 제출 책임 분리 및 연결

기존 loop._answer의 실제 규칙 dispatch를 `stuck/submission/dispatch.py`로 이동한다. 루프의 `_answer`·`_model_answer`는 이 실제 함수의 method binding을 사용한다. 같은 모듈이 기존 HTTP client와 D-724 최종 guard, D-730 원장을 연결한다. `owned.py`는 취소가 SQLite 기록보다 먼저 끝나지 않도록 소유 작업을 기다린다. provider·정답 평가·approval store는 이 모듈이 소유하지 않는다.

초기 실제 모듈은 dispatch 189, owned 13, init 1로 203 physical lines이다. 부모 stuck은 기존 writer를 뺀 3284줄로 원래 3317+150 이하이며 원래 한도를 올리지 않는다. automation·execution·ledger·operating 기존 기준도 유지한다. 독립 SOURCE 검토와 실제 원격 회귀·설치 검증을 병합 전에 수행한다.

호출자는 기존 resolver loop, worker의 검증 후보 후 optional recovery_submit, 기존 ROOT factory다. operating ROOT 설정 없이 legacy 동작과 읽기 전용 worker를 보존한다. SOURCE fixture의 accepted 원본은 현장 증거가 아니다. 기존 결과 관측·피드백·최종 인수와 실제 모델/현장 수용은 전체 목표에 계속 포함한다.
