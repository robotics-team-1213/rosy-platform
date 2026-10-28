# OMX owner executor 이식 결정 · 2026-10-19

## 결정

로컬 main과 origin main이 갈라진 뒤 같은 문제(issue #68, 느린 action event 처리 중 joint-state intake·watchdog 지연)를 두 쪽이 다르게 처리했다.

| 쪽 | 기록 | 판정 |
|---|---|---|
| 로컬 main | [omx-feedback-verification-2026-10-18](../omx-feedback-verification-2026-10-18/result.md) | 계측·비계측·수정하지 않은 main 표본 20회 통과. 원인 미확정, 생산 코드 변경 없음 |
| origin | PR #83 (78a4bea23c), [feedback 격리](../omx-feedback-executor-2026-10-17.md), [owner 스케줄링](../omx-owner-scheduling-2026-10-17.md) | GitHub-hosted Jazzy에서 실패 재현(owner 수신 나이 1.05–1.51s, poll 공백 약 0.577s) 뒤 별도 action executor와 owner worker yield로 보완 |

사용자가 #83 채택을 결정했다. 로컬 main의 비재현 기록은 지우지 않는다. 두 기록은 모순이 아니다. 로컬 시험 PC의 20회 통과는 결함이 없다는 증거가 아니고, origin CI의 재현은 그 환경의 스케줄링 공백을 보였다. 이 이식은 예방 보완을 채택하는 것이며 간헐 실패의 원인을 확정하지 않는다.

## 이식 범위

- #83: `omx_adapter/ros_trajectory_action.py`(action client를 별도 event 노드와 SingleThreadedExecutor로), `omx_adapter/ros_owner_executor.py`(`OwnerMultiThreadedExecutor`), `ros_runtime.py`, owner 진입점(`collection_ros.py`, `g2_owner.py`, `run_cell_owner.py`, `probe_cell_transfer.py`, `pilot_sim_server.py`), 관련 시험, 검증 기록 3건, 릴리스 키 안내.
- main 전용 보완: `deploy/robot/omx/run_hardware_owner.py`는 origin에 없어 #83이 다루지 않았다. 같은 executor와 종료 시 `runtime.destroy()`를 적용했다.
- main의 후속 작업 보존: `test_slow_feedback_handling_cannot_starve_the_joint_state_subscription`의 선택적 `ROSY_OMX_FEEDBACK_TRACE` hook을 유지했다. publisher가 별도 프로세스(`ros_feedback_peer.py`)로 옮겨 같은 프로세스의 `publish` trace 지점만 없어졌다. `g2_owner.py`는 main의 startup 경로와 평평한 `pilot_sim_api`·`pilot_sim_runtime` import를 유지했다.
- #69: 별도 프로세스 fake vendor와 시험 재구성, control-seat 분실 응답 시험의 시계 고정, D-427 journal 원문 fixture. `safety_review_exempt.json`과 origin 이력 별칭 기록은 로컬 이력과 무관해 제외했다.
- #78의 #83 이후 순효과(Fleet `[normal]` quarantine 항목 하나)는 넣지 않았다. 근거가 다른 이력의 origin CI(38969322695)뿐이고, 이 변경이 그 시험이 다루는 코드를 바꾸며, 새 중복·분실 dispatch를 FLAKY로 가릴 수 있다(Safety-Review N1). 어떤 커밋도 `test/flaky_quarantine.txt`를 바꾸지 않도록 브랜치를 다시 만들었다. OMX timeout 항목도 #83이 고쳐 넣지 않았다.

## 시험 기준 변화

#83의 starvation 시험은 freshness를 0.2s에서 0.5s로 바꾸고 sink를 그 3배 이상 막는다. 직렬(ST)과 4-worker 두 경우, timeout 중 HOLD 경우를 더했다. main 기록의 "freshness 0.2s 유지" 조건과 다르므로 리뷰에서 이 완화와 추가 검사의 균형을 확인한다.

## 검증

실물 owner 기동·DEVICE/FIELD 수용은 범위 밖이다. 독립 Safety-Review는 `009ddcfd85`(재작성 전, 백업 ref `backup/port-omx-owner-executor-009ddcfd85`)에 APPROVE WITH NOTES였다. 필수 N1(quarantine 제거)과 권고 세 건(hardware owner 종료의 try/finally, `_spin_once_impl` 호출 확인, owner 최대 수신 간격과 publisher 최대 간격 비교)을 반영했다. `pilot_sim` 단위 분리가 main에 들어가기 전에는 착지하지 않는다.

## 원격 시험

`tools/remote/remote_pytest.py --sha <commit>`로 AI 시험 PC에서 실행했다. 로그는 저장소 밖 `$ROSY_SCRATCH`에 두고 해시만 적는다.

| 실행 | commit | 결과 |
|---|---|---|
| `rosy_harness.py affected --base main` 전체 선택 | `a768ad4520`(재작성 뒤 `d43439bb90`) | 1662개 중 1 failed / 21 skipped. 실패는 `contracts/motion::test_ratchet_rows_are_the_measured_counts_and_only_go_down`(아래 D-766). `known_failures.py`: 1 new, 0 known. SHA256 `2b4806c6cfbca8c43f49b14d28f8a96fb82ccfbdaac3786823830e5146d8b472` |
| `ROSY_OMX_NATIVE_RUNTIME_TESTS=1 test/test_omx_native_ros_runtime.py` (Jazzy) | `c7c863d6f3`(재작성 뒤 `7d968024d7`) | `test_omx_ros_runtime.py` 18 passed(직렬·4-worker·timeout 중 HOLD 포함), policy runtime 2 passed, core arm 4 passed. LeRobot 사례 1건 실패. SHA256 `f5d3256ceb1d608e0f77c7c8891e242d81e48779646bfd1b2da05ef39edcc98e` |
| 같은 native 묶음, 수정하지 않은 main | `056f817652` | 같은 LeRobot 사례만 실패("isolated LeRobot 0.4.4 environment required" skip을 wrapper가 실패로 셈). 기존 환경 공백이며 이 이식의 실패가 아니다. SHA256 `28b3690987b311b4dc56f5b46e08993a4848f49c571636571b54134cf9a18c93` |

`a768ad4520`의 첫 native 실행에서 #83 hunk의 import 순서 때문에 `test_policy_runtime_ros`·`test_core_arm_ros`가 `ModuleNotFoundError: omx_adapter`로 실패했다. `c7c863d6f3`에서 고쳤다. 재작성 전·후 커밋은 `test/flaky_quarantine.txt` 한 줄만 다르다.

### 리뷰 반영 뒤 재실행 (`4f8f412b01`)

| 실행 | 결과 |
|---|---|
| affected 전체 선택(재작성으로 `test_known_failures.py`·`test_readme_agent_start.py`가 빠진 선택) | 1656개 중 1 failed / 21 skipped. 실패는 같은 D-766 ratchet 시험 하나. `known_failures.py`: 1 new, 0 known. SHA256 `14d9b1e80391af1bab56e0768ebd22bafc8ab3800b4f93921bff3626b380bf26` |
| native Jazzy 묶음 | `test_omx_ros_runtime.py` 18 passed(새 `_spin_once_impl` 호출 확인과 owner 최대 수신 간격 검사 포함), core arm 4 passed, policy runtime 2 passed. LeRobot 사례만 main과 같은 환경 공백으로 실패. SHA256 `2757dc9090fcdcc2d507980e28ae063fc42c3575a19890e68fbcf0c0bb189812` |

### `test_omx_fleet_ros_actionserver.py`

native wrapper 대상이 아니므로 `tools/remote/remote_sim.py ... cmd -- python3 -m pytest <file>`로 Jazzy 환경에서 실행했다. 브랜치(`4f8f412b01`)와 수정하지 않은 main(`056f817652`) 모두 두 사례(`[normal]`, `[generation-change]`)가 같은 위치에서 실패했다. 5초 안에 시험 내부 publisher의 joint state가 runtime에 오지 않았다(`runtime.latest_joint_state is None`, 201행). FastDDS 지정 재실행과 다른 시험 PC에서도 같았다. 이 실행 환경에서는 시험이 dispatch 단계까지 가지 못하므로, 이 결과는 Fleet dispatch의 통과도 회귀도 아니다. 원인(remote_sim 격리 graph와 시험 publisher의 관계)은 조사하지 않았다. host pytest에서는 rclpy가 없어 건너뛴다. SHA256 `12f15cb44e7d365976e4b4dd9c18367a87cd0739ac65b07b576cce55dc1c79d8`(브랜치), `945f7c6e3e25e7e968953e4a71820607be09cb9ca734a1b51cf936f8c1740c59`(main).

## 착지 차단: D-766 크기

`omx_adapter` 단위가 10,077줄로 한도 10,000을 넘는다(main은 이 변경 전 한도 바로 아래). `size_range.py main HEAD`가 `e0b4b65664`를 거절한다. `pilot_sim`을 `omx_adapter/pilot_sim/` 하위 단위로 나누는 변경은 아직 `fix/merge-origin-main`에만 있다. 그 나누기(또는 별도 나누기 브랜치)를 먼저 착지한 뒤 이 브랜치를 그 위에 다시 맞춘다.

## 2026-10-19 현재 main 기준 재이식 검증

- 현재 main에는 pilot_sim 하위 단위가 이미 존재한다. 과거 10,077줄 blocker를 재현했다고 주장하지 않으며 크기 기준을 높이지 않았다.
- 자체 a48b283c20은 nested Pilot 경로, main의 watchdog 관찰, G2 전용 clock·진단 종료 순서를 보존한다. 독립 계약 리뷰에서 G2 fixture와 hardware action executor 종료 실패 시 context/lock 조기 해제 두 문제를 수정했다. 정확한 staged diff SHA256 0ec900450767bdb29a430b23d711d6dabd0d216443848ad9d12c487c338328af에 대해 최종 소스 승인했다.
- 원격 focused 95passed/skip0, known_failures NEW/known/flaky0. 원격 native 첫5묶음은 LeRobot 환경 기본 경로 부재 때문에 1failed/4passed였다. 준비된 model-PC LeRobot0.4.4 환경을 명시한 재실행은 긴 native scratch 경로의 AF_UNIX 길이 제한으로 Fleet2사례가 실패했다. 이를 성공으로 세지 않는다.
- omx-native-qualified의 첫 cmd wrapper는 pytest가 실행되지 않아 exit0도 검증으로 세지 않는다. omx-native-qualified-executed는 실제 실행했으나 Fleet socket 경로 실패였다.
- 최종 omx-native-complete는 같은 committed SHA, 승인된 model-PC remote_sim 경로, 격리된 localhost DDS와 기존 LeRobot 환경을 사용했다. 표준 /tmp를 사용하여 UDS 경로 한도를 지켰다. wrapper5passed/skip0, 내부 runtime18 + Fleet2 + policy4 + CORE2 + 실제 LeRobot socket1 =27passed, 실물 동작0이다. 마지막 SDK 사례의 ROS destroyable callback 정리 경고는 로그에 남았으며 실패로 변환하거나 숨기지 않았다.
- 전체 native landing 관문은 별도 수행한다. 운영 서비스·토크·로봇·Gazebo task·DEVICE/FIELD 수용은 실행하지 않았다.

