# 정책 공백 시계 역행 수정

D-400의 기존 계약은 정책 시계가 역행하면 즉시 래치하는 것이다. 배포 후보 `da7a93ff81`에서 `100 → 100.4 → 100.3`이 HOLD를 유지하는 결함을 독립 검토자가 확인했다.

수정은 `SafetyManager._policy_gap`에서 활성 공백의 직전 검사 시각과 비교하여 역행을 거부한다. 시각 보정이나 새 정책·watchdog를 만들지 않는다. 거부 시 기존 CommandManager 경로가 ZERO·E-stop 래치를 수행하며 새 publisher나 자동 reset은 추가하지 않는다.

공백 시작보다 앞선 역행과 시작 이후의 부분 역행을 각각 unbound evaluator, observation missing 예외, late answer 경로에서 검사한다. 정상 HOLD·유효 판정 회복·lease 이후 새 공백·malformed/STOP 즉시 래치도 기존 회귀로 확인한다.

1. 시험과 이 계약 기록만 커밋하고 등록된 시험 PC에서 실제 실패를 확인한다.
2. 공통 판단 경로를 최소 수정하고 독립 리뷰를 받는다.
3. 원격 관련 시험과 known-failure 비교, lint, 정확한 커밋의 CI를 통과시킨다.
4. 리뷰 증거를 기록한 배포 커밋을 고정하여 현장 서버의 서명·전환·등록 readback을 확인한다.

로봇 접속·ABI·calibration·canary·실물 안전 수용은 별도이며 이번 시험이나 역사 리뷰로 대체하지 않는다. 모델 PC의 진행 중인 작업은 중단하지 않는다.
