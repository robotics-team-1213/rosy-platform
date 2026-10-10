# 횡단보도 게이트 켬 SIM (D-573 (c), 모델 PC), 2026-10-10

증거 등급은 **ROS-SIM**이다. 장치·현장 수용이 아니다. Gazebo는 모델 PC에서만 돌렸다.

**판정: 게이트는 횡단보도 앞에서 선다(5/5, 6/6). 그러나 이 SIM 월드의 `crosswalks[0]`에서는 빈 횡단보도도 건너지 못한다.** 차로 오른쪽 약 0.10–0.13 m에 늘 있는 LiDAR 반사(벽·경계)가 보기 영역 A 안에 들어와 `person_present`로 계속 서고, 10 s 뒤 `crosswalk_blocked` 막힘이 사람에게 올라간다. 그래서 동료 요구 (1) "게이트 켬 + 빈 횡단보도에서 1 s 넘는 정지 없이 한 바퀴"는 **통과하지 못했다.** 게이트는 기본 꺼짐으로 둔다. 같은 출발(`(-1.26955, 0.24255, -90°)`)이 rosy-2a 모델 랩 SIM의 출발이고 첫 횡단보도가 이 자리라서, 랩 SIM은 따로 돌리지 않았다(첫 횡단보도에서 같은 이유로 선다).

## 대상과 환경

- 코드: `feat/crosswalk-core-gate` `4d68c27c8`(+ 착지 전 문서·리팩터 커밋, CORE 동작 같음)의 `git archive`, `~/rosy_xgate_ws`, `colcon build --packages-up-to gz_sim core control description`.
- 격리: ROS 도메인 63, `GZ_PARTITION rosy_xgate`, CORE 8663, Fleet 8664, launch는 `systemd-run --scope -p MemoryMax=6G`. 같은 시간에 rosy-2a의 도메인 95 SIM과 다른 세션 pytest가 돌았다.
- 하네스: 기준선 [`xwalk_sim.sh`·`xwalk_batch.sh`·`xwalk_run.py`](../crosswalk-stop-baseline-2026-10-10/evidence/)를 격리 값만 바꾸고 overlay에 `crosswalk_gate_enabled: true`를 더한 [`evidence/xgate_sim.sh`](evidence/xgate_sim.sh)·[`evidence/xgate_batch.sh`](evidence/xgate_batch.sh). 변형은 기준선과 같다(empty, legs, fig150, fig100).
- SIM LiDAR `range_min`은 0.05 m라서 `s_wait` = max(g(0.04) 0.028, 0.05 − 0.059 + 0.02) = 0.028 m다(장치 0.15 m면 0.111 m).

## 결과

| 회 | 보행자 | 첫 정지 사유 | 보행자까지 최소 간격(참값) | 끝 |
|---|---|---|---|---|
| empty_01 | 없음 | `camera_line_not_visible`(출발 뒤 선 놓침, 기준선과 같음), 이어 `crosswalk_*` | — | 12 s 섬 |
| legs_01 | 다리 0.60 m | `crosswalk_looking` | 0.103 m | 12 s 섬 |
| fig150_01 | 인형 0.15 m | `crosswalk_looking` | 0.101 m | 12 s 섬 |
| fig100_01 | 인형 0.10 m | `crosswalk_looking` | 0.102 m | 12 s 섬 |
| empty_02 | 없음 | `crosswalk_looking` → `crosswalk_person_present` | — | 12 s 섬, `stuck_waiting_console`(crosswalk_blocked) |
| empty_a0 | 없음 (`crosswalk_approach_default_m: 0`) | `crosswalk_looking` → `crosswalk_person_present` | — | 같음 |
| legs_a0 | 다리 (같은 설정) | `crosswalk_looking` | 0.101 m | 12 s 섬 |

- 기준선(게이트 없음)은 다리·0.15 m 인형 앞에서 D-422 몸 정지로 0.06–0.07 m에 섰고, 0.10 m 인형에 2/2 부딪혔다. 게이트 켬에서는 셋 다 가까운 변 앞(몸 앞–보행자 0.10 m)에서 섰고 부딪힘은 0이다. 0.10 m 인형은 게이트가 보아서가 아니라 횡단보도 앞에서 먼저 서서 피했다. 보기에서 비었다고 나오면 건너서 부딪힌다(D-573 2항 한계 그대로).
- D-407 국소 후진·재접근은 게이트 켬 회에서 없었다.
- 빈 횡단보도 정지 자리에서 라이브 스캔을 게이트 판정으로 다시 돌린 결과([`judge` 재현](evidence/xgate_runs.tgz) 밖의 일회 probe): 로봇 오른쪽 몸 기준 y −0.10…−0.13 m, x 0.05…0.15 m에 반사가 줄지어 있다. 차로 반폭 0.0925 m 바로 바깥의 고정 구조물이다. A의 옆 범위(차로 반폭 0.10 + 구역 여유 약 0.03 m)가 그것을 덮는다. 대기 띠를 0으로 해도 같다.
- 기준선의 "사람 없는 곳 0.3 s `obstacle_ahead`"도 같은 반사로 보인다(empty_a0에서 서 있는 중 `body_gap_m` 0.0이 한 번 나왔다).

## 해야 할 일 (이 브랜치 밖 결정)

1. 카메라만 있는 구역의 옆 범위를 무엇으로 할지: 지금은 차로 반폭 + 구역 여유(앞뒤 오차를 옆에도 씀). 벽이 차로선에 붙은 현장에서는 가짜 영구 대기다. D-573 1항의 Fleet `approach[]`(벽을 피해 그린 띠, 브랜치 (d))가 오기 전에는 이 현장에서 게이트를 켜지 않는다.
2. SIM 월드의 그 구조물이 실제 현장에도 있는지 확인한다(현장 매트 실측, D-573 열린 질문 "대기 띠 크기").
3. CORE `body_gap_m`이 참값보다 0.03–0.04 m 작은 문제(기준선 발견 5)는 이번에 보지 않았다. 게이트 정지 자리는 참값으로 가까운 변 앞 0.03 m 안팎이다.

원시 기록: [`evidence/xgate_runs.tgz`](evidence/xgate_runs.tgz)(각 회 `log.jsonl`·`summary.json` 등), 모델 PC `~/rosy_xgate_ws/runs_gate_default`, `runs_a0`.

## 2차 (같은 날, `692b0a196`): 원인과 보기 영역 수정

**원인.** 반사는 `map_v2_fleet_real.world` 모델 `track_v2_fleet`의 서쪽 벽 `wall_02`(중심 x −1.4025, 두께 5 mm, 높이 0.30 m, 안쪽 면 x −1.400)이다. 차로 중심 x −1.2696에서 0.130 m 오른쪽이다. 이 월드는 실제 2.81 × 1.26 m 트랙과 같은 벽을 둔다(실제 트랙에도 같은 자리에 벽이 있다). 차로 안쪽 경계 사이는 0.158 m(반폭 0.079 m)이므로 벽은 **차로 corridor 밖**(경계에서 0.051 m)이다. 1차 보기 영역은 D-491 corridor 상수 0.10 + 앞뒤 여유를 옆에도 쓴 0.03 + 대기 띠 0.10이라 벽을 덮었다.

**수정.** 옆 범위 = 카메라가 그 구역과 함께 본 D-468 안쪽 경계(구역 가까운·먼 끝에서), 몸 반폭 + 여유보다 좁지 않게, 옆 여유는 `uncertainty_m` + odom 표류만. 경계를 못 보면 D-491 corridor로 돌아간다. `crosswalk_approach_default_m` 기본은 0(카메라 구역은 대기 띠와 옆 벽을 가르지 못한다. 대기 띠는 Fleet 지도 `approach[]`, 브랜치 (d)).

**남은 원인: SIM LiDAR 잡음.** `rosy_gz.urdf.xacro` LiDAR는 `stddev 0.02`, `resolution 0.03`이다. 0.13 m 벽의 반사가 2σ 꼬리로 0.10 m 안까지 들어와(재현: 30 스캔 중 빔 0, y −0.097…−0.115) 보기 창이 1 s를 못 채운다. 같은 이유로 기준선 발견 5(CORE `body_gap_m`이 참값보다 0.03–0.04 m 작음)도 몸 기하가 아니라 잡음 낀 최솟값 편향으로 본다(정지 간격 기하 변경 없음).

| 묶음 | 설정 | empty | legs | fig150 | fig100 |
|---|---|---|---|---|---|
| runs_c | 수정 + SIM 잡음 0.02 | 섬, 깜빡임(person_present↔looking), 막힘 ×2 | 앞에서 섬 0.102 m | 섬 0.101 m | 섬 0.101 m |
| runs_n (실험) | 수정 + 잡음 0.01(작업공간에서만, 커밋 안 함) | 첫 횡단보도 1.44 s 보고 건넘(×2). 곧 y −0.187에서 다시 섬(원인 미확인: 출구 띠 반사 또는 재무장) | 섬 0.101 m, 10 s 뒤 crosswalk_blocked | 섬 0.103 m | **충돌**(0.10 m 인형은 평면 아래: 비었다고 보고 건넘, D-573 2항 한계) |

- rosy-2a 랩 SIM(게이트 켬, 한 바퀴, 개입 0)은 **돌리지 않았다.** 잡음 0.02 월드에서는 첫 횡단보도에서 서므로 결과가 정해져 있고, 잡음 0.01 실험에서도 건넌 직후 다시 섰다.
- 해야 할 일: (1) 실물 C1의 근거리 거리 잡음을 재서 SIM 잡음을 맞출지 정한다. (2) 건넌 직후 두 번째 정지의 원인(실행기 로그에 `line_follow.crosswalk`를 넣어 재무장인지 출구 띠인지 본다). (3) 벽이 corridor 경계에서 잡음 2σ 안에 있는 현장에서 "A 안 반사 = 사람" 규칙을 어떻게 둘지는 D-573 설계 질문이다.

원시 기록: [`evidence/xgate_runs2.tgz`](evidence/xgate_runs2.tgz).

## 3차 (D-573 개정 2, `a9f966bc4`): 측정 잡음, 가장자리 지속 필터, 랩

**실물 C1 잡음(8kcn rosy_40, 읽기 전용, 2026-10-10).** 정지(odom 속도 0, `cmd_vel` 0) 62 s, 681 스캔, 720 빔, 11 Hz. 빔별 표준편차: 0.2 m 안 중앙값 0.6 mm(p90 0.9), 0.2–0.3 m 1.6 mm(p90 2.3), 0.3–0.5 m 2.0 mm(p90 3.1, 최대 3.4), 1–2 m 1.7 mm(p90 4.6). 이 C1은 `range_min` 0.05 m를 보고한다. 로봇 주변 173 빔이 0.2 m 안(0.146 m)에 반사가 있었다(둘레 물체, 배치는 보지 않았다). 원자료 [`evidence/c1_8kcn_static_scan_60s.jsonl.gz`](evidence/c1_8kcn_static_scan_60s.jsonl.gz). 로봇에는 아무것도 쓰지 않았다(ssh로 흘려받음).

**SIM 설정(이 시나리오만).** `SIGMA=0.0035`: 작업공간 사본의 `rosy_gz.urdf.xacro` LiDAR `stddev` 0.0035, 거리 `resolution` 0.001(출하 0.02/0.03은 실측보다 약 6–10배 크다).

**고친 것(조사 결과).**
1. 가장자리 3σ 띠의 반사는 같은 칸이 최근 3 스캔 중 2 번일 때만 사람이다(개정 2). 더 깊은 반사는 바로 사람이다.
2. "건넌 직후 다시 섬"의 원인: 줄무늬 위·뒤에서는 카메라가 차로 경계를 보내지 않아, 구역 처음 영상의 경계 + 이동 거리 × 0.05의 표류 여유(먼 끝에서 약 0.035 m)가 차로 옆 0.115 m의 남쪽 트랙 벽에 닿았다. 몸 앞이 구역에 들어간 뒤에는 남은 구역을 몸을 중심으로 한 본 차로 폭으로, 출구 띠를 몸 자신의 경로로 본다(스캔과 같은 odom이라 표류 여유가 필요 없음). 최신 차로 경계는 구역 corridor를 좁히기만 한다. 각 수정마다 이전 게이트에서 실패하는 시험을 더했다.

| 묶음 | empty | legs | fig150 | fig100 |
|---|---|---|---|---|
| runs_h (최종) | 1 회 통과(보기 1.4 s). 2 회째는 출발 직후 `camera_line_not_visible`로 섬(기준선에도 있는 선 놓침, 게이트 아님) | 앞에서 섬 0.099 m, 10 s 뒤 `crosswalk_blocked` | 섬 0.102 m | 충돌(평면 아래, 알려진 한계) |

**랩(rosy-2a 조건, 게이트 켬).** `lap_trip.py` 기본(D-513 출발 → NW, 한 바퀴). `runs_hlap/lap_gate_h1`: **arrived**, 횡단보도 정지 1 회 1.42 s(`crosswalks[0]`), 사람 개입 0. 출발 직후 D-407 `lane_lost` 막힘 1 회가 스스로 후진·복구했다(게이트 끄고 돈 기준선의 출발 선 놓침과 같은 자리, 게이트와 무관).

**두 번째 횡단보도(`crosswalks[1]`, 동쪽 길 서행).** 출발 (0.9736, −0.5087, −178.3°) → SE. 정지 1 회 1.43 s 뒤 건넜다. 그 뒤 x ≈ 0.2에서 카메라 선 놓침 → `lane_lost` 되풀이 → trip `stall`. 같은 출발을 게이트 끄고 돌린 `runs_off/cw2_off_01`도 x 0.003에서 `junction_stop`/`lane_lost`로 `stall`이다. 이 경로는 내가 고른 출발·목적지라 trip 자체가 끝까지 가지 못한다. 게이트 켬에서 선 놓침 자리가 다른 것(건너는 속도 0.04 m/s)은 1회씩이라 판단하지 않았다.

원시 기록: [`evidence/xgate_runs3.tgz`](evidence/xgate_runs3.tgz).

## 4차 (안전 검토 반영, `0c1df8e9d`)

- 고침: 어느 빔도 지나지 않는 상자 = UNKNOWN(M1), 차로 corridor 밖·`MAX_TURN_RAD` 넘게 틀어지면 무장 해제(M2), `obstacle_mode: path` 필수(M4), D-577 열린 항목 1이 닫힐 때까지 꺼 둠(발견 3).
- 짧은 재실행(`runs_s`, `runs_slap`, 측정 잡음): empty 2/2 보고 건넘, legs·fig150 앞에서 섬(0.101 m), fig100 충돌(알려진 한계). 랩 **arrived**, 횡단보도 정지 1 회 1.55 s, D-407 막힘 0, 사람 개입 0.
- 첫 시도는 모델 PC가 06:06에 정상 종료·재부팅되어(journal: systemd 정리, 매일 같은 시각) 중간에 끊겼다. 다시 돌렸다.
- runs_n의 y −0.187 재정지: 구역 처음 영상의 경계 + 표류 여유가 벽에 닿은 것(2차·3차 분석). `a9f966bc4`에서 고쳤고 runs_h·runs_s에는 없다.
- 하지 않은 것(MINOR): LaserScan 헤더 시각으로 스캔 나이 재기, 곡선에서 출구 띠를 몸 방향으로 두기.

원시 기록: [`evidence/xgate_runs4.tgz`](evidence/xgate_runs4.tgz).

## D-573 개정 3 (`feat/crosswalk-clear-5s` `80b3858c3`): 5 s 계속 비면 건넘

- 같은 하네스를 작업공간 `~/rosy_xclear_ws`, ROS 도메인 67, `GZ_PARTITION rosy_xclear`, CORE 8667, Fleet 8668로 격리했다(`xgate_*.sh`의 `xgate`→`xclear` 치환본, `SIGMA=0.0035`). 모델 PC는 `remote_pytest.py --pick sim`이 골랐다.
- 하네스만 고침(저장소 아님): D-601 `TRIP_LANE_CAMERA_UNAVAILABLE` 때문에 작업공간 `lap_fleet.py`에 `TripConfig(lane_camera_check=False)`를 넣었다(SIM에는 앞 카메라 미리보기가 없다).
- 설정은 기본값(`crosswalk_clear_s` 5.0, `crosswalk_look_min_scans` 40, `crosswalk_report_s` 10).

| 회 | 보행자 | `looking` 시작 → `crossing` (sim s) | 끝 |
|---|---|---|---|
| empty_01 | 없음 | 266.2 → 271.7 (5.5 s) | 지나감, 막힘 없음 |
| empty_02 | 없음 | 360.0 → 365.3 (5.3 s) | 지나감, 막힘 없음 |
| legs_01 | 다리 0.60 m | 297.2 → 건너지 않음, 297.6 `person_present` | 섬(보행자까지 0.094 m), 307.4 `crosswalk_blocked` |
| fig150_01 | 인형 0.15 m | 328.0 → 건너지 않음, 328.3 `person_present` | 섬(0.096 m), 338.1 `crosswalk_blocked` |

- `looking` 시작에서 건넘까지 5 s를 넘는 부분은 완전히 선 것을 odom으로 확인하는 시간이다. 출발 직후 `camera_line_not_visible`·`stuck_back_off`는 기준선에도 있는 선 놓침이고 게이트와 관계없다.
- 원시 기록: [`evidence/xclear_runs.tgz`](evidence/xclear_runs.tgz).
