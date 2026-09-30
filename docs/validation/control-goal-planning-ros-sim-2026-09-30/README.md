# Control Goal/Planning ROS-SIM (2026-09-30)

판정: **PASS** — control(sensing)의 planning 계열 `goal_node`를 살아있는
ROS 2 Jazzy 그래프에서 검증했다. 이 실행으로 ROS-SIM 카메라 슬라이스에 이어
**planning 슬라이스**가 닫혔다.

## 방법

- WSL2 Ubuntu 24.04, ROS 2 Jazzy — camera 슬라이스와 같은 트리·빌드
  (`/root/rosy-0930`, `git archive` at `27def3de`; goal_node는 이후 커밋에서
  무변경).
- 합성 입력: 2 m × 2 m 점유 격자(0.02 m/cell — 미지 사분면으로 프론티어 형성,
  벽 블록 배치), TF `map→odom→base_link`(로봇 중앙, 매 프레인 신선),
  `/goal/cmd` explore(t≈2 s) → stop(t≈11 s).
- 수집: `/route`·`/goal_point`·`/goal_node/state` JSONL 18 s.

## 결과

| 항목 | 결과 | 근거 |
|---|---|---|
| 프론티어 탐색 | 미지 경계의 골 발견 — `explore goal=(1.19,1.59) score=61.1 size=40 route=0.65m pose~tf` | `goal-evidence.jsonl` 상태 행 |
| 경로 발행 | **실경로 9건**(map 프레임, ≥2 포즈, 2×2 m 내) + **취소 11건**(빈 Path — "침묵은 정지 명령이 아니다"의 문서화된 취소 메커니즘) | `verify-output.txt` VERDICT: PASS (0 problems) |
| 스톨·탈출 기계 | `stall: (59, 79) benched after 6 plans (<0.03m gain), switched -> explore` — GoalEscape·와치독 작동 | 상태 행 |
| 정지 명령 | `stopped` 상태 + 마지막 route가 빈 취소 Path | 검증 단언 5 |
| advisory-only | 그래프의 twist/cmd_vel/velocity 토픽 **0개** (`goal-twist-count.txt`=0) | `goal-topic-list.txt` |

## 한계

- 합성 격자·TF — 실물 SLAM 지도의 노이즈, 격자 이동, 지연은 DEVICE/FIELD다.
- 골 선정의 점수·예측치(eta)는 합성 기하에서의 것이며 성능 증거가 아니다.
- control ROS-SIM HOLD 중 **planning(goal_node) 슬라이스**만 닫는다.
  남은 것: calibration(병행 세션 진행 중)·safety-policy 그래프, Gazebo
  폐루프, 물리 센서.
