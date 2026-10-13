# D-507 보충 지도 기반 굽이 통과 SIM (모델 PC), 2026-10-08

증거 등급: **ROS-SIM (폐루프, 한 대) + 호스트 시험**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(OMEN)에서만 돌렸고
이 노트북에서는 돌리지 않았다. 실물 로봇은 건드리지 않았다.

대상: `feat/d507-bend-odom-pass`. CORE 코드는 `e5735bd5f`(독립 안전 검토 반영본, 파일 md5를 모델 PC와 맞춤), Fleet `trip_ports.py`는
마지막 묶음(B)만 `d201fa9f5`(곧은 접근에서만 보냄). keeper는 main 그대로(게이트 `bend_expected` 끔, CORE→인식 통로 없음).

## 판정 요약

| 목표 (SW 굽이 진입이 굽이를 지나 회전교차로 입구에 닿음) | 결과 |
|---|---|
| 아래 길에서 굽이에 들어간 진입 (최종 코드, 묶음 A+B) | **굽이 통과 18/18**, 회전교차로 입구(SW 노드 0.10 m 안 또는 교차로 감지) **14/18** |
| 넘겨준 자리의 spoke 중심 기준 옆 오차 / 방향 | −0.009…−0.012 m / −3.2…−6.3° (18회) |
| 통과 중 `aborted`·`unresolved` | 0/18 |
| 입구에 못 닿은 4회 | 모두 넘겨준 뒤(차선 추종 중) spoke 위 (−0.62, −0.38)에서 keeper `flipping` → LOST. 굽이 통과 밖(인식) |
| 서쪽 길 출발(서→남 모서리 포함) | 굽이 지시 없는 기준선 5/5, 최종 묶음 B 10/10이 굽이에 닿기 전 모서리 (−1.27, −0.39…−0.41)에서 LOST. 이 SIM의 기존 결함이라 굽이 통과를 재지 못했다 |

B9 게이트 켬 SIM은 0/6, B8(main keeper)은 0/16이었다.

## 설정

- 작업공간 `~/rosy_bendodom_ws`: `~/rosy_b9_ws/src`를 로컬 clone한 뒤 이 브랜치를 bundle로 받아 checkout,
  `colcon build --symlink-install --packages-up-to gz_sim core control description`. 고친 파일은 symlink 설치라 scp 뒤 SIM 재시작으로 반영했다.
- `evidence/bend_run.sh`: B9 하네스(`b9_run.sh` → D-495 `run_sim.sh`)를 바꾸지 않고 ROS 도메인 86, `GZ_PARTITION rosy_bendodom`, CORE 포트 8113,
  실행 폴더 `bendodom`, world 파일 이름 `bendodom_fleet_real.world`로만 바꿨다. `RECOVERY=false`, bridge 켬, `site_floor_map_id: map_v2_fleet`(B9과 같음).
  시작 전 다른 세션(도메인 78 `rosy_d507`, 81 `rosy_bws`)의 프로세스를 확인했고 건드리지 않았다. 끝난 뒤 `GZ_PARTITION=rosy_bendodom` 프로세스만 멈췄다(남은 것 0, 다른 세션의 `gz sim`은 그대로).
  한 번 환경변수 줄을 잘못 써서 probe 하나가 도메인·파티션 없이 돌았다(기본 도메인, 내 CORE 포트로 `PUT mode`만, sim 시계 없음). 내 프로세스라 바로 멈췄다.
- `evidence/bend_probe.py`가 Fleet 역할을 한다: 지도 = lane_graph `map_v2_fleet` + `bend` 장소 하나(꼭짓점 (−0.6924, −0.5091), 들어감 0°, +63.6°,
  반지름 0.15 m), 지도 자세 = Gazebo 참값. 필드는 Fleet 함수 그대로(`trip_ports.bend_geometry`, 묶음 B부터 `straight_approach`), `bend_in_m` = west:rev 위 호 시작점까지 차로 거리,
  `bend_tol_m` 0.12(Fleet 바닥값), 호 시작점 0.6 m 안에서 보내고 7.5 s마다 갱신, `JUNCTION_ODOM_STALE`이면 다음 틱에 다시. 실행마다 장소 id가 다르다(D-495 R1 완료 기억).
  성공 = 굽이 지시가 `bending`/`reacquiring`을 거쳐 `idle`로 끝나고, 그 뒤 SW 노드 0.10 m 안에 들거나 교차로 감지.
- 요약: `evidence/bend_analyze.py` → `evidence/analysis_*.json`, 묶음 기록 `evidence/batch_*.log`.

## 첫 시도에서 고친 것 (모두 이 브랜치 커밋)

| SIM 관찰 | 고침 |
|---|---|
| 0.064 m 중심선 호를 lookahead 0.05로 좇자 뒤가 회전 바깥 남쪽 둘레 벽(몸 오른쪽 2–4 cm)으로 쓸려 호 시작점에서 D-422 `near_stop` | 추적 lookahead를 D-476 `bridge_lookahead_m`(0.10)으로, 지도 반지름은 차로 안에서 달릴 호(0.15 m, URDF 반폭으로 r ≤ 0.21) |
| 아래 길 남쪽 벽 옆의 D-422 HOLD가 넘겨받기를 일으켜 바로 중단 | 카메라 자신의 HOLD·큰 오차·감지에서만 넘겨받음, 다른 HOLD는 그대로 HOLD |
| 닻 없이 받은 지시가 첫 틱에 `no_anchor` 중단 | 닻이 없으면 호 시작점까지는 지금의 HOLD |
| D-422 깜박임으로 매번 호 앞에서 중단(D-495식 첫 막힘 중단) | 막힌 틱은 0 명령 HOLD `junction_bend_blocked`, 비면 재개, 시간 상한 안 |
| 경로 힌트 `left`로 서→남 모서리의 짧은 손실을 bridge가 잇지 못함 | `bend`는 힌트를 모름으로 둠 |
| 모서리 안에서 보낸 지시: 모서리를 질러 간 만큼 호가 늦어 바깥 4.9 cm에서 IR `bend_basis_lost`(서쪽 출발 2회) | Fleet은 굽이 앞 차로가 15° 안으로 곧을 때만 보냄(`straight_approach`) |

검토 전 코드(r 0.15)의 아래 길 13회: 통과 13/13, 입구 12/13(`evidence/analysis_r15_pre_review.json`).

## 결과 (최종 코드)

묶음 A(`analysis_final_a.json`, 아래 길 13회): 통과 13/13, 입구 9/13. 넘겨받은 자리 x −0.899…−0.955(호 시작점 −0.785, 첫 카메라 `no_boundary`·오독).
D-422 `junction_bend_blocked` HOLD(남쪽 벽 옆)가 최종 아래 길 18회 중 16회에서 1–7번(기록 표본 기준) 있었고 모두 재개했다.
묶음 B(`analysis_final_b.json`): 아래 길 5/5 통과·입구 5/5, 서쪽 10/10은 모서리 LOST(지시 전, `idle`).
기준선(`analysis_baseline.json`, 굽이 지시 없음, 서쪽 5회): 5/5 모서리 LOST.

## 한계

- 한 지도의 한 굽이(63.6°)다. 반지름 0.15는 지도 작성자의 값이고 SIM으로만 골랐다.
- Fleet 지도 자세는 Gazebo 참값이다. 실제 지도 자세 오차(`bend_tol_m` ≥ 0.12)만큼 호 시작점이 틀리면 옆 오차가 약 0.9·δ다(D-507 보충 5).
- 서쪽 출발이 모서리에서 LOST해 모서리를 지나 들어오는 진입(실제 trip 경로)은 측정하지 못했다. 아래 길 출발은 모서리 탈출 잔여를 흉내 내려 왼쪽 0.02 m에서 시작했다.
- 넘겨준 뒤 spoke의 keeper `flipping`(4/18)은 회전교차로 입구 인식 몫이다.
- 호스트 SIM은 DEVICE가 아니다.

## 재현

```bash
# 모델 PC: ~/rosy_bendodom_ws (위 설정)
H=src/rosy-platform/docs/validation/lane-bend-odom-sim-2026-10-08/evidence
RECOVERY=false setsid nohup bash $H/bend_run.sh > sim.out 2>&1 < /dev/null &
setsid nohup bash $H/batch.sh > batch.out 2>&1 < /dev/null &
python3 $H/bend_analyze.py runs --json runs/analysis.json
```

원시 기록(run마다 `log/cmd/keep/actions/events.jsonl`, `summary.json`)은 모델 PC `~/rosy_bendodom_ws/runs*`에 있다.
