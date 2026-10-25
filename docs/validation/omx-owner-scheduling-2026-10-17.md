# OMX owner 스케줄링 · 2026-10-17

[feedback 격리 기록](omx-feedback-executor-2026-10-17.md)의 후속 검증이다. 이 기록은 GitHub-hosted Jazzy 시험에 한정하며 실제 로봇·vendor Gazebo·staging을 기동하지 않았다.

## 관측과 보완

진단 소스 commit `cd3bb5dcbc126c2003e1de46d0daa7a4cc544c44`의 [CI 39013248730](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39013248730)에서 host 1549 passed / 17 skipped, native 1 failed / 14 passed, Fleet native 2 passed였다. host의 이동 전 AST 경로는 수정됐지만 stock MTE 4-worker의 정상 완료 조건에서 freshness가 실패했다.

| 같은 실행에서 관측한 항목 | 결과 |
|---|---|
| 설치된 rclpy | 7.1.12. MTE spin hook에 명시적 yield 없음 |
| 완료된 poll 사이 공백 | 약 0.577s, 허용 freshness 0.5s 초과 |
| cancel 진입→반환 | 약 0.165ms |
| sink 대기 중 thread stack | pool worker 네 개는 대기, spin thread는 ready-callback 수집, action thread는 시험 sink 대기 |

긴 cancel·owner 처리 대기는 이 관측에서 확인되지 않았다. 한 시점의 stack으로 GIL 원인을 확정하지 않는다. `ros_owner_executor.OwnerMultiThreadedExecutor`가 부모 hook 뒤 `sleep(0)`으로 worker 실행 기회를 넘기도록 보완하고, 같은 4-worker·0.5s 기준으로 효과를 확인한다.

실제 owner 진입점과 관련 회귀는 같은 helper를 쓴다. worker 수·callback group·poll 주기·HOLD·종료 경로는 유지한다. 보호된 `_spin_once_impl` hook을 쓰므로 ROS/rclpy 버전 변경 시 spin·spin_once·Future 대기·종료 회귀를 다시 확인한다. 직렬 시험은 공식 권고에 따라 ST를 쓰며 앞서 관측한 stock MTE1 실패를 해결로 분류하지 않는다.

## 수집 경로와 완료 조건

별도 액션 노드가 수집 코드의 단일 client 검사에서 외부 client로 취급되는 통합 공백도 확인했다. 정확한 owner 소유 identity를 허용하는 시험과 다른 이름·다른 namespace 거절 시험을 함께 유지한다. 이름 접두사만으로 다른 client를 허용하지 않는다. 이 graph 검사는 DDS 인증을 뜻하지 않는다.

보완 후보 commit `09c2451ac3e432f8e7aea8e20fbd68d326c31df0`의 [CI 39014273721](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39014273721)은 native 18 passed, Fleet native 2 passed, browser 9 passed였다. host는 수집의 내부 client 거절 시험 한 건만 실패했다(1 failed / 1564 passed / 17 skipped). 전체 CI는 실패이며 이 결과로 병합하지 않는다.

후속 수정은 생성한 액션 노드의 고정 identity를 수집 검사에 전달한다. 임시 trace는 제거하고 같은 freshness·완료 poll·timeout HOLD 검사를 다시 실행한다. 수정 대상인 OMX timeout의 자동 재시도 항목만 제거해 첫 실행 통과를 요구하며, 별도 Fleet quarantine은 유지한다.

최종 source/head·독립 검토·개별 CI 결과는 [PR #83](https://github.com/robotics-team-1213/rosy-platform/pull/83)에 기록한다. scheduler 보완의 통과와 수집 통합의 통과를 구분하고, 병합 후 main 전체 CI도 확인한다. 기존 quarantine과 새 실패를 섞어 전체 통과로 표시하지 않는다.

원격 시험 PC는 사용자 지시로 생략했고 노트북 pytest는 실행하지 않았다. 실제 stop·복구·DEVICE/FIELD는 미검증이며 비공개 staging은 HOLD다.
