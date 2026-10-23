# 그리퍼 실패 관측 보완의 원격 회귀 검증

검증 source `dec89620017b673719429abd09461dacc9f57f19`.
기준 `ef04e5999d8c3ba506332c90a928eae6f4f2900c`의 teacher·contact predicate·gripper
contract는 실패 native source a566과 동일했다. 다른 세션의 main 변경은 보존했다.

## 변경과 독립 검토

기존 `grip()`이 이미 읽은 snapshot의 observation·전체 관절 위치·q·판정 범위·기존 시각과
phase/선행 command만 예외 시 결과에 추가한다. 실패 handler는 새 joint/object/clock을
읽지 않는다. 순수 serializer의 오류는 오류 종류로 제한하고 verifier 예외를 그대로
다시 던진다. 성공 경로의 failure 필드는 null이다. 기존 판정·목표·정리 절차는 유지한다.

독립 `review_learning_bounds`가 실제 diff와 시험을 검토했고 Important 지적은 없다.
처음 nonfinite fixture가 dataclass 생성 단계에서 거부되는 문제는 유효 observation과
비정상 진단 scalar를 구분하도록 고쳤다. 해당 수정도 재검토한 뒤 production commit의
Safety-Review trailer를 기록했다. 실제 계약이 비정상 observation을 수용한다고 주장하지 않는다.

## 실제 실행 결과

모두 공식 `tools/remote/remote_pytest.py --sha <위 source> --log-dir <외부 scratch> --`
경로로 실행했다. 로컬 pytest/ROS/ML은 실행하지 않았다.

| 범위 | 결과 | 종료 |
|---|---|---|
| `test/test_omx_teacher_gripper_failure.py test/test_omx_teacher_watchdog_receipt.py` | 14 PASS, skip 없음 | 0 |
| `middleware/devices/omx/adapter/test/test_omx_gripper_contract.py middleware/devices/omx/adapter/test/test_pilot_sim_gripper.py` | 18 PASS, skip 없음 | 0 |

두 로그 모두 `test/known_failures.py` 비교에서0 new/0 known/0 flaky다.
첫 범위는 실제 nested `grip` body와 실제 verifier로 held·stale·release 거부,
held/open 성공, 동일 예외 객체 유지, 단 한 번의 joint read와 정확한 실패 표본 보존,
잘못된/비정상/직렬화 실패 진단, 기존 최종 종료 처리를 확인한다.

| 보존 로그 | 크기 | SHA256 |
|---|---:|---|
| `teacher-gripper-red/run-1.txt` — c31f5c88b0, 7 FAIL/2 PASS | 9675 | sha256:8e4a6d620f8e17e7ad29e611fb36d286331cc8e2bc9077957c04dedbe71105ab |
| `teacher-gripper-red-full-snapshot/run-1.txt` — 90b4bb3d0e, 7 FAIL/2 PASS | 9675 | sha256:956e673b9d5faca447e9cf91969439b21cbb9fe5c3f4d8e6c91357fad741957c |
| `teacher-gripper-green/run-1.txt` | 80 | sha256:fe9dca0451129aaabdd76ea13e310b61a52091a146a1f9fe5b72b851eb33547f |
| `teacher-gripper-contract/run-1.txt` | 80 | sha256:341d5dca33250b815baddbafb6001e174c20bf1716bb74f3d612e77777db8938 |

로그는 소유 세션의 외부 scratch `learning-execution-20261023` 아래에 보존했다.
짧은 GREEN 로그는 pytest progress만 담고 있으며 실행 명령·source·종료값은 공식 remote
runner의 실행 관측과 이 기록으로 연결한다. 독립 native 실행 receipt가 아니다.

## 完了していない範囲

새 field를 출력한 native 실행은 미실시이며 실패 순간의 물리 상태도 미확인이다.
이 변경으로 grasp 물리 원인이나 이전 stale-state 원인이 해결됐다고 주장하지 않는다.
두 고정 cohort는 HOLD로 유지하며 admission·학습·독립 정책 평가·Hub 전달·
실물 수용의 근거로 삼지 않는다. 공식 main 통합은 별도 실제 결과를 확인한 뒤 기록한다.
CE: 미해결 — 진단 회귀 통과와 물리 원인 해결을 구분한다.
