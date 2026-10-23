# Pilot SIM snapshot과 owner 제출의 순번 경쟁

성공 교사 시연 7개를 보존한 뒤 추가 batch 3이 `joint_state_sequence_mismatch`로
HOLD됐다. 준비 자세 명령 58개는 local acceptance를 받았고 **첫 기록 명령**이 거부됐다.
기록 0프레임, cleanup true이며 실패 원본은 보존했다. 수집 watch는 HOLD에서 멈췄고
학습은 제출하지 않았다. 기존 실패를 성공 표본으로 교체하거나 manifest를 고치지 않았다.

- 변경: readonly `owner.joint_state`는 owner가 이미 수용한 immutable snapshot을
  반환하며 Pilot의 snapshot·일반 제출·gripper 관측 5곳이 이를 사용한다.
  native `latest_joint_state`는 policy guard의 pending-intake coalescing을 위해
  owner 전달 전에 게시한다. Pilot 일반 제출과 자동 hold는 Pilot lock → owner command transaction 순서로
  상태 선택·목표 생성·seat 예약·capture 준비·한 번의 제출을 묶는다.
  기존 순번·freshness·범위·seat 검증과 비동기 action 완료를 유지한다.
  원본 시각·source-intake 진단과 admission helper의 ROS I/O 금지 계약도 유지한다.
- 증거: source `f02f041404`의 실제 owner 동시성 회귀는 일반 제출과 자동 hold 모두
  실패했다(`pilot-admission-red/run-1.txt`: 2 failed, ROS module 1 skipped).
  source `db4d8f87ca`의 관련 owner/Pilot/gripper/capture/API 검사는 원격
  `pilot-admission-green/run-1.txt`: **140 passed**, `known_failures.py` **0 NEW**.
- 증거: 최초 source `db4d8f87ca`는 runtime 게시를 늦추는 안이었다. 좁은 실제
  Jazzy 3개 검사는 통과했으나, 확장 landing 검사에서 **7 failed, 1532 passed,
  33 skipped**로 중단됐다. 6개는 시험용 owner의 새 transaction API 누락,
  1개는 기존 policy binding attach 중 pending intake 전달 의존성이다.
  기존 policy assertion을 바꾸는 대신 위의 admitted readback 경계로 수정했다.
  자동 main 비교는 잘못 축약된 node ID 때문에 exit 4/no tests여서 main 판정에 쓰지 않았다.
- 증거: 최종 코드 source `187d5b758b`의 `pilot-admitted-state-green/run-1.txt`는
  HTTP probe와 기존 policy attach/coalescing을 그대로 포함해 **173 passed**, **0 NEW**다.
  `pilot-admitted-state-native-green/run.txt`는 실제 Jazzy에서 pending native intake가
  먼저 보이면서도 Pilot은 owner 수용 전 상태를 노출하지 않는지, source-stamp 재전송
  거부와 느린 watchdog 중 feedback 수신을 **3 passed, 0 skipped**로 확인했다.
  이 새 pending/admitted 회귀는 이전 게시 지연안 `77cab202cc`에서 **1 failed**였다
  (`pilot-admitted-state-red/run.txt`).
- gate 변화: 원격 SOURCE/ROS 회귀 검증이다. 읽기 전용 계약 검토에서 중요한 문제는
  없었다. 최종 코드의 확장 landing 검사는 아직 완료하지 않았다.

## 실제 교사 시연과 새 학습 수집

최초 transaction producer `db4d8f87ca`의 fresh-world 교사 시연은 PASS/EXITED0,
cleanup true, 1,586프레임, issue 0이었다. MODEL의 별도 source `22e36a83e7` 검증은
독립 SIM truth·전체 RGB readback·377개 명령 coverage·지원 가능한 718개 학습 chunk를
확인했다(`atomic-teacher-truth-model/out/result.json`). 이 producer는 정책 binding을
사용하지 않는 교사이며, 이 결과를 최종 코드의 학습 정책 실행 검증으로 세지 않는다.

같은 교사 source로 새 25개 cohort를 수집 중이다. 이전 성공 7개와 실패 원장은 새
cohort 밖에 보존한다. 첫 20개 train/마지막 5개 validation을 고정했고, 모든 원본의
독립 truth·RGB·명령 지원 검증 후에만 학습한다. 정책 평가 runtime은 pending-intake를
보존한 최종 수정 source를 사용해야 한다. 최초 게시 지연안을 정책 실행에 사용하지 않는다.

위 실행 경로는 `C:/DevTemp/learning-execution-20261023/` 아래다.
실제 실패 archive의 command 응답과 teacher 오류는 같은 순번 거부를 기록한다.
실패 순간에 어느 스레드 간격이 발생했는지는 계측하지 않았다. 두 간격은 각각
결정적 회귀로 재현·차단했으며 이것만으로 장시간 수집의 무실패를 주장하지 않는다.

25개 학습 cohort, 모델 학습·재적재, 독립 정책 평가와 실물 수용은 미완료다.
CE: 해당 없음. 두 경쟁과 복구 경계는 source·회귀 시험·이 실행 기록으로 복원할 수
있어 별도 교훈 문서로 중복하지 않는다.
