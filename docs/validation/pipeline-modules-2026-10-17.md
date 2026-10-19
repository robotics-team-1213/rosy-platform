# 병합 후 modules 실패 관찰 · 2026-10-17

**판정:** 보고용 잡의 실패를 확인했다. 주 CI 집계 성공만으로 전체 시험 통과나 staging 준비 완료를 선언하지 않는다. [앞선 점검](pipeline-audit-2026-10-17.md)의 성공 기록은 그 실행의 사실이며 이 실패를 해소하지 않는다.

## 실행 증거

- 대상 소스 SHA `dce4ed4b36bfc86d0413a943630fb174834d271c`, [main CI 39005572546](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39005572546).
- 실패 잡: `test (modules)`, job `117317361286`. 완료된 잡의 로그를 GitHub API로 내려받아 확인했다.
- 실패 항목: `middleware/devices/omx/adapter/test/test_omx_ros_runtime.py::test_slow_feedback_handling_cannot_starve_the_joint_state_subscription`.
- 해당 ROS 시험 묶음은 1 failed / 7 passed. 관절 상태 수신 나이는 약 1.8575초였고 `max_joint_state_age_s=0.5` 조건에서 실패했다.
- 기존 실패 비교: 1 NEW / 0 known / 0 flaky. `known_failures.txt`와 `flaky_quarantine.txt`에 해당 항목이 없다.

직전 점검 소스에서 위 SHA까지 변경한 파일은 PR 안내·날짜별 점검·작업 Log·생성 색인뿐이다. OMX 구현·시험·CI 워크플로는 바뀌지 않았다. 이 사실만으로 기존 실패나 환경 문제로 확정하지 않는다. 원인은 미확정이며 기준선 재현과 런타임 분석이 필요하다.

## 후속 처리

1. OMX 담당자는 같은 소스·ROS 환경·격리 실행 조건에서 상태 수신과 느린 피드백 처리의 진행을 확인한다. 앞선 정상 실행과 이번 실패의 수신 시각·callback 진행·실행기 상태를 비교한다.
2. 수정이 필요하면 새 작업에서 독립 안전 검토와 해당 ROS 시험으로 검증한다. freshness 기준을 늘리거나 시험을 제외해 통과시키지 않는다. 성공 재실행만으로 원인 해결을 판정하지 않는다.
3. 게시 담당은 `ci-result`와 별도로 modules 결과·미해결 항목을 인수인계한다. 비공개 staging은 `HOLD`를 유지하고 실제 배포·장치 수용과 구분한다.

이 기록은 실패 관찰과 후속 조건을 남긴다. 로봇·호스트에 접속하거나 런타임을 변경하지 않았고 원격 시험 PC·노트북 pytest는 실행하지 않았다.
