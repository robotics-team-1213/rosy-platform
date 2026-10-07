# D-507 10 / D-422 기억 래치 SIM (B4, 2026-10-08)

모델 PC(OMEN, `rosy@100.98.162.71`) Gazebo. 이 노트북과 실차는 쓰지 않았다. 호스트 SIM은 DEVICE가 아니다.

## 무엇을 확인했나

D-507 10항(D-422 기억은 몸 밖의 점만, 진입 때 한 번 판정)이 착지한 코드로 다음 둘을 본다.

1. 수정 전에 `obstacle_ahead`·`clearance_source: memory`·`body_gap_m 0.0`으로 묶였던 출발을 되풀이해도 기억 HOLD가 없다.
2. 실제 상자를 차로 위에 두면 여전히 멈춘다.

## 기전 (원시 기록으로 확인)

B9 묶음(`~/rosy_b9_ws/b9runs_05462b7d9`, main 432445eed 기준이라 수정 전)의 `bend_3`–`bend_6`·`south_c2`·`south_c3`
`events.jsonl`에 `nav.line_obstacle_hold` `clearance_source: memory`, `body_gap_m 0.0`, `stop_gap_m` 0.0215–0.0345가 있다.
`log.jsonl`에서 로봇은 주행 중(`TRACKING`, 선속도 0.03–0.07 m/s, 회전 포함)에 `HOLD obstacle_ahead`로 바뀐 뒤 run 끝까지
(43–86 s) 풀리지 않았다. 기억은 몸의 움직임(odometer)으로만 사라지는데, 기억이 만든 HOLD가 움직임을 멈추므로 스스로 풀리지
않는다. sim LiDAR `range_min`은 0.05 m(`rosy_gz.urdf.xacro`)이고, LiDAR(x −0.017)에서 0.05 m 안의 원판은 Pinky URDF 몸
(앞 0.04205, 뒤 −0.076, 반폭 0.05655, 회전 반경 0.08257) 안에 6.5 mm 이상 여유로 들어간다. 그래서 그때 기억된 점은 모두 몸 안이다
(`body_gap 0.0`과 맞다). 기억에 넣고 꺼내는 곳은 `body_stop._remember_near` 하나이고(`manager.observe_scan_points`에서만 부른다),
읽는 곳(틱, junction, lane_bridge, motion_admit 전진·후진)은 모두 같은 저장소를 읽는다. 고친 곳도 그 한 함수다(35945410f, 32f98d98b).

## 설정

- 작업공간 `~/rosy_b4_ws`: `~/rosy_b9_ws/src/rosy-platform`을 로컬 clone한 뒤 이 브랜치(bundle, a5ab3bb03 = main df016367c +
  시험)를 checkout, `colcon build --symlink-install --packages-up-to gz_sim core control description`(PATH `/usr/bin` 먼저).
- `evidence/b4_run.sh`: D-495 `run_sim.sh`를 고치지 않고 ROS 도메인 80, `GZ_PARTITION rosy_b4`, CORE 포트 8100, 실행 폴더
  `~/rosy_b4_ws/b4`, world 파일 이름 `b4_fleet_real.world`로 띄웠다. D-507 9가 옛 현장 키를 시작 거부하므로 겹의
  `junction_turn_site_accepted`를 `site_floor_map_id: map_v2_fleet_real`로 바꾸고 `bridge_site_no_dropoffs`를 뺐다.
  `RECOVERY=false`(B9와 같음).
- 시작 전 다른 세션: B9 묶음(도메인 79, `rosy_b9`)이 돌고 있어 끝날 때까지 기다린 뒤 시작했다. 다른 세션 프로세스는 건드리지 않았다.
  끝난 뒤 `rosy_b4` 파티션 프로세스만 멈췄다(남은 것 0).
- 실행(`evidence/batch.txt`): B9와 같은 굽이 진입 15회(`trip --plan left:60`, 서쪽 길 (−1.27, 0.24, −90°)), 아래 길 가운데 3회,
  B9에서 래치된 자리 4곳 출발(`latch_b3`–`latch_b6`), 상자 4회(`evidence/b4_box.py`). 요약은 `evidence/b4_analyze.py` →
  `evidence/analysis.json`. 래치 판정: `clearance_source: memory` 정지 사건이 하나라도 있거나, `body_gap_m 0.0`인 `obstacle_ahead`가
  1 s 넘게 이어지면 래치.

## 결과

| 묶음 | run | 래치 | memory 정지 사건 | 가장 긴 `body_gap 0` HOLD |
|---|---|---|---|---|
| B9(수정 전, 같은 분석기) | 19 | 7 (bend_3–6, south_c1–c3) | 6 | 42.9–86.2 s |
| B4(이 브랜치) 굽이·아래 길·래치 자리 | 22 | 0 | 0 | 0.12 s |

- B4 22 run의 `obstacle_ahead` HOLD는 모두 1.2 s 이하로 풀렸다(사건 0건, `nav.line_obstacle_hold`는 5 s 이어질 때 난다).
- 굽이 15회는 1.18–1.30 m를 달려 굽이까지 갔다(B9 래치 run은 서쪽 길·굽이 안·아래 길에서 멈췄다). 끝 상태는 `junction_aborted` 또는
  `LOST camera_reselection_required`로, B9 keeper 굽이 결함(이 브랜치에 없음)과 횡단보도 `no_boundary`(bend_6, 0.09 m)다. 기억과 무관하다.
- 래치 자리 출발 4곳: `latch_b5`는 1.03 m를 달렸고, `latch_b3`·`b4`·`b6`는 굽이 안이라 keeper가 바로 LOST(0 m)여서 주행 래치를
  재현할 기회가 없었다. 서 있는 동안 기억 HOLD는 없었다.

상자(지름 0.03 m, 높이 0.25 m, 차로 위):

| run | 놓은 방법 | 정지 사건 출처 | 첫 HOLD 때 상자 간격 (gt) | CORE `body_gap_m` | 최소 간격 (gt) | 0 지시까지 | HOLD 유지 |
|---|---|---|---|---|---|---|---|
| box_ahead_1 | 몸 앞 0.30 m, 출발 전 | lidar | 0.057 m | 0.014 | 0.057 m | — (출발 전) | 끝까지 36 s |
| box_ahead_2 | 같음 | lidar | 0.071 m | 0.016 | 0.071 m | — | 끝까지 36 s |
| box_drop_1 | 0.0676 m/s 주행 중 몸 앞 0.08 m | lidar | 0.048 m | 0.014 | 0.048 m | 0.172 s | 끝까지 30 s |
| box_drop_2 | 같음 | lidar | 0.052 m | 0.030 | 0.052 m | 0.146 s | 끝까지 30 s |

- 네 번 모두 닿지 않고 멈췄고 run 끝까지 HOLD였다. 0 지시 지연은 gz 상자 생성 응답 시각부터 첫 `/cmd_vel` 0까지(sim 시간)로,
  상자 생성과 다음 스캔(10 Hz)을 포함한다.
- CORE `body_gap_m`이 지면 진실 간격보다 0.02–0.05 m 작다. sim LiDAR 잡음(σ 0.02 m)의 가장 가까운 점을 쓰기 때문이다(보수 쪽).

## 한계

- 호스트 SIM은 DEVICE가 아니다. sim C1은 `range_min` 아래를 반환하지 않는다. 실기 C1이 0.05–0.12 m에서 무효(0·inf)를 내면
  그 빔은 수정 전에도 기억되지 않았다. 앞쪽은 초음파만 덮는다. DEVICE D9에서 0.06–0.12 m 근거리를 잰다.
- Pinky에서는 이 개정으로 D-422 기억이 사실상 쓰이지 않는다(보이지 않는 곳이 모두 몸 안). `range_min`이 몸 밖까지 닿는 LiDAR에서
  기억이 그대로 동작하는 것은 호스트 시험으로만 확인했다(`test_line_follow_body_stop.py`).
- 래치 자리 4곳 중 3곳은 keeper LOST로 주행하지 못했다.

## 재현

```bash
# 모델 PC: ~/rosy_b4_ws (위 설정), evidence/* 를 ~/rosy_b4_ws/b4/ 에
RECOVERY=false setsid nohup bash b4/b4_run.sh > b4_sim.out 2>&1 < /dev/null &
setsid nohup bash b4/batch.sh > /dev/null 2>&1 < /dev/null &
python3 b4/b4_analyze.py b4runs --json b4runs/analysis.json
python3 b4/b4_analyze.py ~/rosy_b9_ws/b9runs_05462b7d9      # 수정 전 비교
```

원시 기록(run마다 `log.jsonl`, `cmd.jsonl`, `events.jsonl`, `summary.json`)은 모델 PC `~/rosy_b4_ws/b4runs`에 있다.
상자 run 요약은 `evidence/box_*_summary.json`.
