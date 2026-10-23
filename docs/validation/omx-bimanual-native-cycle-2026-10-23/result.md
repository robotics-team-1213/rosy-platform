# 양팔 native 12관절 변환·ACT 재적재 검증

제품 소스 `e2e2b062c1c5af3a2b47d3d267f8ff49cd5720e9`에서 실제 LeRobot 0.4.4의
12관절 데이터 읽기 → 검토 구간 분할 → 공식 ACT 2-step 학습 → 새 Python 프로세스
재적재 → 별도 eval 재생이 통과했다. 합성 연결 시험이며 사람 라벨·실물 양팔 성공 근거는 아니다.

## 변경과 회귀 검사

기존 peer 커밋 `6ae680f1ab`, `919a1e0e19`, `9c9a1d7b3c`의 필요한 변경만
현행 main으로 옮겼다. 출력 경로 검사는 main의 공통 `omx_output_paths.in_source_checkout`를 유지했다.
reader는 명시된 `omx_follower` 6관절 또는 `bi_omx_follower` 12관절 순서를 검사한다.
분할 출력은 robot_type을 보존하며 평가기는 같은 train/eval layout으로 관절별 오차를 계산한다.

- RED `82ccea9830`: 기존 main은 유효한 양팔 입력도 거부해 새 회귀 사례가 실패했다.
- GREEN `e2e2b062c1`: 원격 `test_native_review.py`, `test_native_segments.py`,
  `test_native_cycle.py` 73 passed / 1 skipped, known_failures 0 NEW.
  SDK 없는 일반 시험 환경의 round trip skip은 아래 실제 SDK 실행과 구분한다.
- 코드 독립 검토: Important 없음. 최종 착지 검사는 별도 land receipt에 남는다.

## 실제 SDK 실행과 회수 증거

승인된 `remote_sim.py --host model --sha e2e2b062c1 --minutes 30 cmd -- <fixture-command>`로
고정 모델 PC 환경에서 실행했다. ROS·실물 장치에는 접속하지 않았고 Hub는 offline이었다.
완전한 명령·동결 generator payload는 아래 출력의 `inner.sh`와 `run.txt`에 있다.

외부 출력: `C:/DevTemp/learning-execution-20261023/bimanual-main-native-reader-bound-revision/`.
실행 helper: `run_existing_bimanual_native_check.py --sha e2e2b062c1 --log-dir <새 출력>`.
종료 코드0, `out/result.json`의 source_revision이 위 전체 SHA와 일치한다.

| 확인 | 관측 |
|---|---|
| 입력 | HWC RGB, arm_a 6개 다음 arm_b 6개, 합성 원본 2 episodes × 8 frames |
| 분할 | 서로 다른 합성 session/cycle에서 train3 / eval3 frames |
| 학습·재적재 | 공식 ACT 2 steps, 별도 프로세스 재적재 true, action shape `[12]` |
| 평가 | samples3, joint_names와 MAE/상수 기준 배열 각각12개, physical_task_success null |
| 원본·분할 | split receipt SHA 일치, 회수된 train/eval 파일12개 SHA 모두 일치 |
| 모델 | `cycle/trainer/checkpoints/000002/pretrained_model` 파일7개 SHA 모두 receipt와 일치 |
| 경계 | offline_only true, device_execution false, promotion false, independent_policy_trials0 |

정책 revision은 `act-8767d3c7e11adce8`이다. 2-step 결과는 상수 기준보다 낫다는 품질 주장을
하지 않는다. rig/calibration·검토자 표기는 모두 synthetic fixture임을 명시했다.

| 파일 | SHA-256 |
|---|---|
| generator | `f70c4a45faf331ccdd957a8473d96e9e9c386859f26fc8fd4dd3ca09bf4f910a` |
| `out/result.json` | `da0e3b3e620156b8a14dccbf2d0aecb853ad695483af11f2b454e407a2555ad3` |
| `out/cycle/cycle-receipt.json` | `1c24fd26205c7e4d3a23b646ca4a23c10efa6d3f12017677c62e6e0149a42f35` |
| `out/cycle/evaluation.json` | `261bd1f7e630c510ad75c0addf3c1f4a059551d76b84fc3cf5f764d1a2f101c4` |

첫 통합 실행 `bimanual-main-native-reader-model`은 SDK 경로는 통과했지만 외부 fixture의
source_revision이 이전 peer SHA로 고정돼 있어 이 통합 검증의 최종 근거에서 제외했다.
그 출력과 원래 generator를 보존하고 전체 소스 SHA를 주입·검사하는 새 실행을 위에 기록했다.
이전 peer 실행, 잘못된 CHW fixture, 일반 pytest skip을 이번 실제 실행으로 합산하지 않는다.

CE: 해당 없음. 제품 변경과 외부 fixture의 소스 결속은 코드·회귀 검사·이 기록으로 확인할 수 있다.
실제 양팔 수집·사람 검수·과제 성공·장치 수용은 별도이며 이 실행으로 승인하지 않는다.
