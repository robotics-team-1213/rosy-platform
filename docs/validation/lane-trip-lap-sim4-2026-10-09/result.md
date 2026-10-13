# Fleet trip 한 바퀴 SIM 4차, 회전교차로 ring 호 주행 기본 켬 (모델 PC), 2026-10-09

증거 등급은 **ROS-SIM**이다. 폐루프 한 대에 실제 Fleet trip 루프를 돌렸다. 장치·현장 수용이 아니다.

- Gazebo·ROS·pytest는 모델 PC(OMEN)에서만 돌렸다.
- 이 노트북에서는 기록 분석(ROS 없음)과 착지 게이트만 돌렸다.
- 실물 로봇은 건드리지 않았다.

**판정: trip은 지나가지만 D-520 개정 2026-10-09의 SIM 합격선(모든 ring 호 |Δr| ≤ 0.05 m)은 넘지 못했다.**

- 그래서 장치 조건 (1)이 아직 열리지 않는다. 장치에서 `arc_enabled`는 꺼 둔다.
- ring 통과는 lap SIM 3의 0/12에서 12/12(비례 보정), 11/12(비례+적분)로 바뀌었다.
- NE 진입 trip은 8/8이 NW에 닿았다.
- 넘친 것은 두 가지다.
  - lap 각 묶음에서 1회가 0.051–0.056 m였다.
  - NE `ring_n`은 4회 모두 −0.049…−0.052 m로, 섬 쪽(안쪽)이었다.

## 대상과 환경

- 코드는 local main `c6bd5cd38`에 아래 세 브랜치를 얹은 것이다. 오늘 착지한 것과 같은 커밋이다. `git -c core.autocrlf=false archive main`을 풀고 세 브랜치의 `git diff main...<branch>`를 적용했다.
  - `fix/d520-arc-entry-tangent`: 호 진입 회전각이 `turn_target`이다.
  - `feat/d520-arc-radial-tracking`: odom 지도 원 추종이다.
  - `docs/d520-default-on-ring`: `arc_enabled` 기본 켬, 능력 = 켬 ∧ 현장 바닥 선언.
- 작업공간은 `~/rosy_ring4_ws`다. `colcon build --symlink-install --packages-up-to gz_sim core control description`로 지었다.
- 격리 값은 ROS 도메인 93, `GZ_PARTITION rosy_ring4`, CORE 포트 8588, Fleet 8589, 실행 폴더 `ring4`, world `ring4_fleet_real.world`다.
- 다른 세션(`rosy_d507_ws`, `rosy_bend_window_ws` 등)의 프로세스는 건드리지 않았다.
- 하네스는 lap SIM 3의 `ring_run.sh`·`ring_batch.sh`에서 격리 값만 바꾼 것이다([`evidence/ring4_run.sh`](evidence/ring4_run.sh), [`evidence/ring4_batch.sh`](evidence/ring4_batch.sh)).
- 설정은 **출하 기본**이다.
  - CORE 겹은 `obstacle_mode: path`, `ir_guard_enabled: true`, `site_floor_map_id: map_v2_fleet`이다.
  - `arc_enabled`를 켜는 줄이 없다. 기본이 켬이고, 바닥 선언이 있어 능력 `lane_arc: true`다. CORE `/system/capabilities`에서 확인했다.
  - Fleet은 SW·SE·NE 지시에 `exit_segment`를 실었다(`evidence/sends_*.jsonl`).
- 계획:
  - lap은 lap SIM 3과 같다. 서쪽 길 → `B_SW` 굽이 → SW `right` → `ring_s` → SE `straight` → `ring_e` → NE `straight` → `ring_n` → NW `stop`이다.
  - NE 진입은 `east` 차로의 NE 0.27 m 앞 (−0.0838, 0.4504, −109.3°)에서 출발해 NE `right` → `ring_n` → NW `stop`이다. lap SIM 3의 출발 (0.11, 0.509)은 위쪽 모서리에서 `obstacle_ahead`였다.
- 두 묶음을 돌렸다.
  - **P**: 원 추종 비례만(k_y 36, k_θ 12). 12 lap과 NE 4회다.
  - **PI**: 착지한 이득(k_y 64, k_θ 16, k_i 150, |I| ≤ 1.0 1/m). 12 lap과 NE 4회다.

## 결과 (구간별)

구간 정의는 lap SIM 2의 `lap2_segments.py`다. "ring SE 통과"·"ring NE 통과"는 그 호(`ring_e`·`ring_n`)를 CORE가 달린 것이다([`evidence/ring4_arc.py`](evidence/ring4_arc.py)).

| 구간 | lap SIM 3 출하 기본 (12회) | **P (12회)** | **PI (12회)** |
|---|---|---|---|
| 서→남 모서리 | 12/12 | **12/12** | **11/12** |
| 굽이 `B_SW` | 12/12 | **12/12** | **12/12** |
| SW 회전 | 12/12 | **12/12** | **11/12** |
| ring SE 통과 | 0/12 | **12/12** | **11/12** |
| ring NE 통과 | 0/12 | **12/12** | **11/12** |
| NW 정지 | 0/12 | **12/12** | **11/12** |
| trip 완료 (`arrived`) | 0/12 | **12/12** | **11/12** |

| NE 진입 (NE `right` → `ring_n` → NW) | P (4회) | PI (4회) |
|---|---|---|
| NE 회전 → 호 → NW 정지, trip 완료 | 4/4 | 4/4 |
| 호 시작 방향 − 참값 접선 | +14.2…+15.0° | +14.2…+14.8° |
| `ring_n` 최대 \|Δr\| (끝, 안쪽 −) | 0.049–0.050 m | 0.051–0.052 m |

PI lap_06은 `stall`로 끝났다. ring 앞 서→남 모서리 (−1.195, −0.455)에서 `lane_return_sensor_search` → `lane_return_fleet_required`로 섰다. lap SIM 1 원인 C와 같은 자리이고, 호 주행과 무관하다.

## ring 호의 참값 반지름 오차

Δr은 Gazebo 참값 자세에서 ring 중심 (−0.3357, 0.0011)까지의 거리 − 0.2514 m이고, 바깥이 +다. CORE가 그 호를 달린 틱(사유 `lane_arc`·`lane_arc_correcting`)만 셌다.

| 묶음 | `ring_s` 최대 \|Δr\| | `ring_e` 최대 \|Δr\| | `ring_n` 최대 \|Δr\| | > 0.05 m | IR 보정 | `lane_arc_edge` | `near_stop` | `lane_arc_end_unarmed` |
|---|---|---|---|---|---|---|---|---|
| lap SIM 2 호 주행(피드포워드, 6° 회전) | 0.061–0.068 | — | — | 10/12 `lane_arc_edge` | 12 | 10 | — | — |
| **P** | 0.022–0.045 | 0.030–0.056 | 0.015–0.030 | 1/12 (lap_11 `ring_e` 0.056) | 0 | 0 | 0 | 0 |
| **PI** | 0.020–0.044 | 0.022–0.051 | 0.014–0.040 | 1/11 (lap_03 `ring_e` 0.051) | 0 | 0 | 0 | 0 |

- SW 회전 끝 방향 − 참값 접선은 P −0.6…−6.9°, PI −1.1…−6.9°다. lap SIM 2의 호 주행은 −11.8…−16.8°였다. lap SIM 3의 지적대로 `theta` → `turn_target`이 진입 오차를 줄였다.
- `ring_s`의 끝 Δr은 다음 호 `ring_e`의 시작이다. 원과 적분을 이어받으므로 `ring_e`의 최대는 대부분 `ring_s`에서 넘어온 어긋남이다(시작 +0.020…+0.046 m).
- 원 추종은 odom을 잘 따랐다. lap_01 `ring_s`에서 odom 궤적을 호 시작 참값 자세에 맞춰 놓으면 참값 Δr과 1 mm 안에서 같았다. 남은 어긋남은 odom 오차가 아니다. 원을 놓은 기준 방향이 틀린 것이다(아래 원인 1).

## 남은 원인

1. **원의 기준 방향(회전 목표 yaw)이 참값 접선과 다르다.** 호의 원은 odom의 회전 목표 yaw(진입 yaw + `turn_deg`)를 접선으로 놓는다. 그 값이 참값 접선과 다르면 원 추종은 그 돌아간 원을 잘 따라간다.
   - SW: 바깥으로 +0.02…+0.045 m 흐른다. 회전 끝 방향 오차(−1…−7°)와 함께 커진다. lap_02(−0.8°)는 0.023 m, lap_11(−6.9°)은 0.045 m다.
     - 원인은 진입 yaw다. 진입 yaw는 3 m를 달린 odom이고, 모서리 회전을 거치며 참값과 몇 도 어긋난다.
     - `turn_target`의 들어오는 차로 끝 방향(62.7°)도 로봇이 실제로 들어오는 방향(59–60°)과 다르다.
   - NE: 회전 끝이 참값 접선보다 +14–16° 안쪽이다.
     - Fleet `turn_deg`는 −97.4°다. 들어오는 `east` 차로 끝 방향은 마지막 두 현으로 −114.5°이고, 로봇은 −109.3°로 들어온다(+5.2°).
     - `ring_n` 시작 접선은 5 cm lead로 148.0°이고, 참값 원 접선은 142.3°다(+5.7°).
     - 회전 허용 오차(5°)가 더해진다.
     - 그래서 원 전체가 안쪽으로 돌아가 있고, 로봇은 그 원을 따라 섬 쪽으로 −0.05 m 간다.
   - 적분은 이 어긋남을 줄이지 못한다. 기준 원 자체가 틀렸기 때문이다. P에서 PI로 바꿔도 NE는 2 mm 더 안쪽이었다.
   - 고칠 길:
     - (a) 회전 축에서 차로에 대한 로봇 방향을 재는 측정이 있어야 한다. D-520 단계 2의 카메라 원 맞춤(첫 맞춤의 e_θ로 원을 다시 놓기), 또는 Fleet 지도 자세(Rosy Cam)의 방향을 지시에 싣는 것이다.
     - (b) Fleet `exit_segment`가 있는 회전의 나가는 접선을 5 cm lead 대신 원호 적합의 접선으로 쓰는 것. NE +5.7°는 없어진다. 그러나 SW에서는 같은 5.7°가 원을 바깥으로 돌려 바깥 흐름이 커질 것으로 계산된다. 그래서 (a) 없이 따로 넣지 않았다.
2. **곡률 응답.** Gazebo는 0.08 m/s 호에서 명령보다 약 15 % 덜 돈다. P만으로 명령 곡률이 피드포워드보다 0.3–0.65 1/m 높게 유지됐다(lap_01 `cmd` 0.33–0.37 rad/s, 피드포워드 0.318). 적분이 이 일정한 어긋남을 맡는다. 원인 1이 크게 남아 SIM에서는 효과가 드러나지 않았다.
3. **반지름 선택은 원인이 아니다.** 지도 차로 중심 0.2514 m와 칠한 두 선 가운데 0.250 m는 1.4 mm 다르다.
4. **IR은 한 번도 보정하지 않았다(0/32).** 원 추종이 IR 문턱(약 0.0625 m) 전에 잡았다. IR 보정 + 원 다시 놓기 경로는 SIM 증거가 없고 SOURCE 시험만 있다.

## 검토

독립 code-reviewer(Claude Opus 5.5, opus)가 2026-10-09에 검토했다.

- `fix/d520-arc-entry-tangent`: APPROVE WITH NOTES.
- `feat/d520-arc-radial-tracking`: 1차 REQUEST CHANGES였다. 회전에서 지난 호의 원을 다시 쓰는 결함이었다. 고친 뒤 APPROVE WITH NOTES다.
- `docs/d520-default-on-ring`: 1차 REQUEST CHANGES였다. 장치 계획이 바닥 선언과 함께 호를 끄도록 강제하지 않았다. 고친 뒤 APPROVE WITH NOTES다. 열린 점: 계획 밖 로봇 overlay는 코드로 막지 않는다(D-520 개정 「남는 위험」).

## 한계

- 한 대, 한 지도(260919 SIM), 한 출발 두 곳이다. ring은 반시계(κ > 0)뿐이다. κ < 0은 SOURCE 시험만 있다.
- Fleet 지도 자세는 Gazebo 참값이다.
- 호스트 SIM은 DEVICE가 아니고, 카펫 odom yaw(D-500)는 여기 없다.

## 재현

```bash
# 모델 PC: ~/rosy_ring4_ws (main + 세 브랜치 diff, colcon build; pydeps·pyextra·pyfleet은 lap SIM 3 것의 링크)
setsid nohup bash ring4_run.sh > sim.out 2>&1 < /dev/null &
OUTD=runs_lap4 bash ring4_batch.sh lap4_batch.txt; OUTD=runs_ne4 bash ring4_batch.sh ne4_batch.txt   # P
setsid nohup bash ring4_runI.sh > runI.out 2>&1 < /dev/null &                                         # PI
python3 ring4_arc.py runs_lap4i --json arc_lap4i.json
python3 src/rosy-platform/docs/validation/lane-trip-lap-sim2-2026-10-08/evidence/lap2_segments.py runs_lap4i --json segments_lap4i.json
```

P 묶음은 `lane_arc.py`를 비례만으로 둔 커밋 `28e6c5fcf`(브랜치 `feat/d520-arc-radial-tracking`)이다. PI 묶음은 그 브랜치의 `d2839cce5` 소스(원 재사용 고침 전)다. 원 재사용 고침(`db44904d3`)은 회전에서만 갈라지고, 이 계획의 회전(SW·NE)은 앞 호가 없으므로 같은 경로다.

증거 파일:

- `evidence/arc_*.json`(호별 Δr·시작 방향·IR·멈춤), `segments_*.json`
- `sends_*.jsonl`(Fleet 송신), `batch_*.log`

원시 기록(run마다 `log/cmd/keep/actions/events/trip.jsonl`, `summary.json`)은 저장소 밖에 있다. `X:\DevTemp\lap-sim4\lap4_runs_full.tgz`(2,278,632 bytes, SHA-256 `b9c78a24ff1a68b033f59b9c866be70bf276aced0503204f6e82757fed5055a8`)와 모델 PC `~/rosy_ring4_ws`다.
