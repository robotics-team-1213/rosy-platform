# Pilot SIM snapshot과 owner 제출의 순번 경쟁

성공 교사 시연 7개를 보존한 뒤 추가 batch 3이 `joint_state_sequence_mismatch`로
HOLD됐다. 준비 자세 명령 58개는 local acceptance를 받았고 **첫 기록 명령**이 거부됐다.
기록 0프레임, cleanup true이며 실패 원본은 보존했다. 수집 watch는 HOLD에서 멈췄고
학습은 제출하지 않았다. 기존 실패를 성공 표본으로 교체하거나 manifest를 고치지 않았다.

- 변경: ROS runtime의 `latest_joint_state` 게시를 owner-locked 전달 안으로 옮겼다.
  Pilot 일반 제출과 자동 hold는 Pilot lock → owner command transaction 순서로
  상태 선택·목표 생성·seat 예약·capture 준비·한 번의 제출을 묶는다.
  기존 순번·freshness·범위·seat 검증과 비동기 action 완료를 유지한다.
  source-intake 진단의 선게시와 admission helper의 ROS I/O 금지 계약도 유지한다.
- 증거: source `f02f041404`의 실제 owner 동시성 회귀는 일반 제출과 자동 hold 모두
  실패했다(`pilot-admission-red/run-1.txt`: 2 failed, ROS module 1 skipped).
  source `db4d8f87ca`의 관련 owner/Pilot/gripper/capture/API 검사는 원격
  `pilot-admission-green/run-1.txt`: **140 passed**, `known_failures.py` **0 NEW**.
- 증거: 별도 실제 Jazzy 환경 `pilot-publication-native-red/run.txt`는 runtime이
  owner 전달 전 미래 순번을 노출하는 실패를 재현했다(**1 failed**).
  수정 source `db4d8f87ca`의 `pilot-publication-native-green-nodes/run.txt`는
  게시 순서, source-stamp 재전송 거부, 느린 watchdog 중 feedback 수신의
  **3 passed, 0 skipped**다. 첫 green 호출은 shell의 복합 `-k` 인자가 분리돼
  exit 4/no tests였으며 통과로 계산하지 않았다. 명시적인 node ID로 다시 실행했다.
- gate 변화: 원격 SOURCE/ROS 회귀 검증이다. 읽기 전용 계약 검토에서 중요한 문제는
  없었다. 수정 source의 fresh-world SIM probe는 실행 중이며 그 결과를 선행 주장하지 않는다.

위 실행 경로는 `C:/DevTemp/learning-execution-20261023/` 아래다.
실제 실패 archive의 command 응답과 teacher 오류는 같은 순번 거부를 기록한다.
실패 순간에 어느 스레드 간격이 발생했는지는 계측하지 않았다. 두 간격은 각각
결정적 회귀로 재현·차단했으며 이것만으로 장시간 수집의 무실패를 주장하지 않는다.

25개 학습 cohort, 모델 학습·재적재, 독립 정책 평가와 실물 수용은 미완료다.
CE: 해당 없음. 두 경쟁과 복구 경계는 source·회귀 시험·이 실행 기록으로 복원할 수
있어 별도 교훈 문서로 중복하지 않는다.
