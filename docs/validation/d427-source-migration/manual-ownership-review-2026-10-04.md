# D-442 U1 MANUAL 소유권 회귀와 독립 리뷰

- 기준: 마이그레이션 후보 `64415a609` 위 `fix/d427-manual`의 이 기록을 담은 커밋.
- 범위: 살아 있는 수동 조작 세션의 자율 주행 진입 거부. binding 래퍼·OMX 선점·Fleet 신호 감독은 별도 작업이다.
- 검증자: 작성 세션과 분리된 `d427_safety_review`.

## 결함 재현

일반 목표, Fleet correlation 목표, 모드 전환, swarm follow는 수동 세션을 가진 상태에서 200으로 NAVIGATION에 들어갔다. ModeMachine도 이를 허용했다. 신규 회귀 시험은 수정 전 **5 failed, 2 passed**였다.

첫 수정의 독립 리뷰에서 두 추가 결함을 발견했다. teleop가 MANUAL 검사 뒤 clip에서 멈춘 사이 NAVIGATION이 전환되고, 뒤늦은 teleop가 성공으로 끝났다. line-follow 거부 전에는 `nav.cancel`이 실행됐다. 두 결함은 각각 수정 전 **1 failed**로 재현했다.

## 최종 수정과 리뷰

ModeMachine은 CommandManager의 실제 `manual_active` 판단으로 MANUAL→NAVIGATION을 거부한다. teleop의 명령 저장과 watchdog 갱신은 `commit_manual`로 같은 모드 잠금에서 MANUAL을 다시 확인한 뒤 반영한다. 검증·clip·이벤트와 transition listener는 잠금 밖에 있다. API guard는 자율 진입 부작용 전에 409 `MODE_CONFLICT`를 반환하며, line-follow OFF 정지는 계속 허용한다.

검증자는 경합 양방향을 독립 실행했다. NAVIGATION이 먼저 전환하면 teleop는 실패하고 수동 세션은 생기지 않는다. 수동 입력 갱신이 잠금을 먼저 잡으면 NAVIGATION이 기다렸다가 거부되며 MANUAL이 유지된다. 양쪽 thread는 교착 없이 종료됐다. 코드 차단 사항이 없는 소스 리뷰 승인이다.

## 로컬 시험

```text
python -m pytest middleware/core/gateway/test/test_manual_navigation_ownership.py
  middleware/core/gateway/test/test_core_logic.py
  middleware/core/gateway/test/test_api.py
  middleware/core/gateway/test/test_swarm_api.py
  middleware/core/gateway/test/test_docking_mode_ownership.py
  middleware/core/gateway/test/test_v1_import_boundary.py -q
167 passed in 124.93s
```

원시 결과와 재현 스크립트: `X:\DevTemp\rosy-d427\resume\manual-green-3.txt`, `review\manual_race_repro.py`, `review\manual_reverse_race_repro.py`.

SOURCE/호스트 회귀 및 소스 리뷰 근거다. ROS-SIM·ARM64·장치·실주행 증거는 **NOT_RUN**이며, D-442의 sim 수용 조건은 남아 있다.
