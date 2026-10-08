# 한 대 lap SIM 실패 원인 진단 (D-517 M5 선행), 2026-10-08

증거 등급: **기록 분석 + ROS-SIM 재실행(모델 PC, 한 대)**. 장치·현장 수용이 아니다. 제품 코드는 바꾸지 않았다. 실물 로봇은 건드리지 않았다.
대상 main `c065ab992`. 이 main은 lap SIM 2 대상 `47fa82b1a` 뒤로 CORE `line_follow`·perception 코드 변경이 없고, Fleet 변경은
D-517 5 해결기 replan(교통 있을 때만)뿐이다.

## 1. 기록된 실패 분류 (ba6538f37 앞/뒤)

lane-return 이름공간 odom 수정 `72054f6c7`·`033cc89a3`(14:20–14:23, 병합 `ba6538f37`)은 lap SIM 1 대상 `caa74a53c`(17:09)와
lap SIM 2 대상 `47fa82b1a`(21:24) 모두의 조상이다(`git merge-base --is-ancestor`). 두 묶음 기록 어디에도 `pose_stale`이 없다.
**그래서 기록된 실패 중 그 수정 앞의 것은 없고, 이름공간 pose_stale은 원인이 아니다.**

| 묶음 | 대상 | 결과 | 끝난 이유 |
|---|---|---|---|
| lap SIM 1 (20) | `caa74a53c` | 0/20 | A keeper `corner_left` 역주행 11, B Fleet이 `approaching`을 모름 3, C D-468 복귀 소진 4, D 굽이 칸 1, E spoke 후진 1 |
| lap SIM 2 기본 (12) | `47fa82b1a` | 0/12 | `junction_corner_hold` 11, `pose` 1 |
| lap SIM 2 호 (12) | `47fa82b1a` | 1/12 | `lane_arc_edge` 10, `pose` 1, `arrived` 1 |
| lap SIM 2 기록 (3) | `47fa82b1a` | 0/3 | `junction_corner_hold` 2, D-468 `stall` 1 |

A·B·D는 `47fa82b1a` 전에 고쳐졌다(lap SIM 2에서 SW 회전 12/12). 남은 막힘은 모두 `ring_s` 위다.

## 2. `junction_corner_hold`가 서는 자리

- 발생: `middleware/core/services/core_features/line_follow/recovery/junction/gate.py:355-356`(지시 `armed`, 목격 없음)과
  `gate.py:344-348`(만료 뒤 fail closed).
- 조건: `recovery/junction/approach.py:137-148` `_corner_at_expected_line` — keeper 전략이 `corner_left|right`인 프레임이
  `CORNER_LATCH_S` 2 s 안에 있고, `line = expect_in − pivot − travel ≤ CORNER_HOLD_AHEAD_M(0.45, approach.py:41) + tol`.
  지시의 `action`도 차로가 굽는지도 보지 않는다.
- lap SIM 2 기본 12회 SE `straight` 송신 순간(`evidence/ring_entry_error.py`): `line` 0.463–0.484 m, 정지 범위 0.614–0.648 m
  → **ring_s 전체가 정지 범위 안이다**(ring_s 길이 0.374 m). 그 순간 참값은 ring 중심선 +0.047…+0.082 m 바깥,
  **방향이 반시계 접선보다 21.6–35.2° 바깥**이다. keeper가 왼쪽으로 크게 굽는 차로를 보고 `corner_left`를 내는 것은 차로 자체다
  (rec_01·rec_03 keep_debug, lap SIM 2 result.md 1절).

## 3. 위로 한 단계: SW 회전이 ring 접선보다 바깥을 겨눈다

- 지도: SW 노드 (−0.5216, −0.1682), 노드의 ring 접선 −47.7°. CORE 회전 자리(`junction_turning` 참값)는 (−0.48, −0.19),
  ring 위로 약 10.6° 더 간 곳이고 그 접선은 −37°다.
- Fleet `operations/fleet/fleet/routing/execute.py:56-69` `turn_target`: 지도 노드의 접선 회전 −114.6° + `TURN_OVERTURN_DEG`
  6°(execute.py:24, 「ring이 회전 반대로 굽으면 더 돈다」, SIM 4c 임시값) = −120.6°. CORE는 진입 yaw(굽이 출구 58–60°, 지도 spoke보다
  약 4° 오른쪽) + turn_deg를 겨눈다 → 약 −61°. 회전 자리 접선 −37°보다 **약 24° 바깥**(6° 덧돌기 + 4° 진입 yaw + 약 11° 자리 차이).
- 호 주행(D-520, 덧돌기 없음)도 같은 몫에서 호 시작 −11.8…−16.8°였다(lap SIM 2 2절, D-520 단계 1 FAIL과 같은 원인).
- corner hold가 없던 넘겨주기 SIM에서도 SW 회전을 끝낸 10/10이 ring에서 섰다. 즉 hold를 풀기만 하면 실패 이유가 `pose`·`junction`으로
  바뀔 뿐이다.

## 4. SIM 전용인가

- hold 판정(2절)은 **실제 결함**이다. 260919 지도는 현장 바닥이고, ring 위 `straight`에서 지도 차로가 굽는 쪽의 keeper corner를
  오독으로 보는 규칙은 장치에서도 같다.
- 24° 바깥 진입은 지도 기하 + Fleet 규칙 + CORE 회전 자리에서 나오므로 SIM 전용이 아니다. 다만 keeper가 그 오차를 `corner_left`로
  읽는 빈도는 SIM 카메라(높이·pitch가 실물과 다름) 몫이 있다. 실시간 비율·CPU는 원인이 아니다: 정지 자리가 12회 모두 2 cm 안에서 같다.

## 5. 재실행 (main `c065ab992`)

모델 PC, 도메인 96, `GZ_PARTITION rosy_lapdiag`, CORE 8688, Fleet 8689, 출하 기본(lap SIM 2와 같은 겹), 4회, 23:03–23:08.
시작 때 부하 7.8(다른 세션 SIM 2개), 실행 중 10–13.

| run | 끝 | 멈춘 자리 (참값) | SE 송신 때 Δr / 방향 오차 | `line` / 정지 범위 |
|---|---|---|---|---|
| diag_01 | `junction_corner_hold` | (−0.404, −0.305) | +0.056 m / −29.5° | 0.466 / 0.622 m |
| diag_02 | `junction_corner_hold` | (−0.402, −0.306) | +0.053 m / −34.4° | 0.469 / 0.620 m |
| diag_03 | `junction_corner_hold` | (−0.401, −0.306) | +0.051 m / −36.9° | 0.470 / 0.617 m |
| diag_04 | `pose` (`off_lane_m` 0.26) | (−0.421, −0.305) | +0.045 m / −33.6° | 0.480 / 0.612 m |

모서리·굽이·SW 회전 4/4, ring 0/4. 회전 자리 (−0.481…−0.493, −0.186…−0.195). diag_04는 lap_12와 같다(`camera_line_not_visible` →
D-407 `stuck_back_off` → Fleet `pose`). **lap SIM 2 기본 결과가 현재 main에서 그대로 재현된다.** 부하가 3–4에서 10–13으로 바뀌어도
멈춘 자리가 같으므로 CPU·실시간 비율은 원인이 아니다.

사고 기록: 23:03 전의 첫 시도(22:51–22:56)는 CORE 포트 8488을 썼는데 `rosy_ring` 세션(도메인 92)의 CORE가 이미 그 포트를 쥐고
있었다(우리 CORE는 `address already in use`). 그 5분 동안 이 하네스의 mode·junction·trip 호출이 **그 세션의 CORE로 갔다**.
그 세션의 22:51–22:56 기록은 오염되었을 수 있다. 첫 시도의 결과(`junction_unexpected` 4, 로봇 정지)는 버렸고, `diag_run.sh`에
포트 검사를 넣었다.

## 6. 이 정지는 설계대로인가

`junction_corner_hold`는 `fix/junction-corner-hold`(`461259067`…`8fa0df8f6`, API v1.148, Safety-Review 대상)가 lap SIM A
(곧은 spoke 위 SW `right` 지시에서 keeper `corner_left` → 역주행)를 막으려고 넣었다. 그 브랜치의 검증은 단위 시험뿐이고
Gazebo 첫 실행이 lap SIM 2다. 가드는 **설계대로 동작한다**: 창 안 keeper 모서리면 지시 종류와 상관없이 선다. 결함은 규칙의 전제
(「기대선 근처의 keeper 모서리 = 오독」)가 곡선 차로 위 `straight`에서 틀린 것이다. 정지 범위를 줄이는 조정으로는 풀리지 않는다:
ring_s 길이 0.374 m가 keeper 모서리 거리 0.45 m보다 짧다.

## 7. 수정 제안 (결정은 다음 계획, 이 브랜치는 제품 코드를 바꾸지 않음)

1. **먼저(Fleet, 한 곳)**: `routing/execute.py:56-69` `turn_target`이 노드 접선 대신 CORE 회전 자리(노드 + 실제 pivot 거리)의
   다음 차로 접선을 겨누고, ring 진입의 `TURN_OVERTURN_DEG` 6°를 빼고 다시 측정한다(주석이 「ring 따라가기를 고친 뒤 다시 잰다」).
   기대: 진입 오차 24–37° → 수 도. D-520 호 주행 FAIL(호 시작 −12…−17°)도 같은 몫이다. 관할 D-507 4, D-520. CORE 코드는 안 바뀌지만
   현장 로봇의 회전 각이 바뀌므로 SIM 4c 재측정과 독립 검토가 필요하다.
2. 1로 corner hold가 남으면(CORE, Safety-Review 필요): `approach.py:137` `_corner_at_expected_line`이 `straight` 지시에서
   지도 차로가 굽는 쪽의 모서리는 오독으로 보지 않게 한다. CORE는 차로 굽음을 모르므로 Fleet이 지시에 그 부호를 실어야 한다(API 행 추가).
   관할 D-507 3(창) + v1.148 행. lap SIM A 역주행 재발 시험을 같이 돌린다.
3. 남은 것: D-468 모서리 출구 복귀 소진(lap SIM 1 C, lap SIM 2 rec_02), Fleet `pose`가 D-407 후진 중 0.26–0.28 m를 내는 이유.

## 재현

```bash
# 모델 PC: ~/rosy_lapdiag_ws = ~/rosy_lap2_ws/src 복사 + main에서 바뀐 파일 덮어쓰기, PATH=/usr/bin 먼저
# colcon build --symlink-install --packages-up-to gz_sim core control description
H=src/rosy-platform/docs/validation/lane-trip-lap-sim-diag-2026-10-08/evidence   # 또는 ~/rosy_lapdiag_ws/diag
systemd-run --user --scope -p MemoryMax=8G setsid nohup bash $H/diag_run.sh > sim.out 2>&1 < /dev/null &
systemd-run --user --scope -p MemoryMax=8G --setenv=OUTD=runs bash $H/diag_batch.sh $H/diag_batch.txt
# 노트북
python docs/validation/lane-trip-lap-sim2-2026-10-08/evidence/lap2_segments.py runs --json segments.json
python docs/validation/lane-trip-lap-sim-diag-2026-10-08/evidence/ring_entry_error.py runs/sends.jsonl
```
