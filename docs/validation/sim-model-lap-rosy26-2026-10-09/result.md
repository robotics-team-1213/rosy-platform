# rosy26 차선 모델 폐루프 한 바퀴 SIM — 2026-10-09

증거 등급은 **ROS-SIM**(모델 PC)이다. 장치·현장 수용이 아니다.

**판정: rosy26 모델(28e8454d, 62db9403)은 learned 도색으로 한 바퀴를 한 번도 돌지 못했다.** 링에 들어가기 전 서쪽 길에서 모두 멈췄다. 같은 코드에서 threshold는 한 바퀴를 돌았다(`arrived`). "도착"한 학습 모델 실행은 62db9403 every_n 2·보정 끔(F) 하나다. 그런데 learned 프레임이 **0/552**이고 전부 `denoise_fallback`이다. 목표 규칙상 이 실행은 세지 않는다.

## 조건

- **코드.** origin/main `a654405f7fff45f559be0eabb07b7b1b4fe0fd74`의 `git archive`다. D-570 ego-motion 재사용과 every_n 1–4가 들어 있다. 작업공간은 `~/rosy_m26_ws`이고, `colcon build --symlink-install --packages-up-to gz_sim core control description`로 지었다. `line_observer_node.py`의 SHA-256은 `e7fe6a71…dffa`다.
- **격리.** ROS domain 97, `GZ_PARTITION=rosy_m26`, CORE 8604, Fleet 8605를 썼다. 실행마다 `systemd-run --user --scope -p MemoryMax=6G -p CPUQuota=800%`로 걸었다. 같은 시간에 다른 세션의 `rosy_d567_ws` Gazebo(domain 95)가 돌고 있었고, 그쪽은 건드리지 않았다. RTF는 0.87–0.98이었다.
- **하네스.** [lane-model-closed-loop-2026-10-09](../lane-model-closed-loop-2026-10-09/result.md)의 launch·run·batch를 다음만 바꿔 썼다([evidence](evidence/)).
  - launch 인자 `learned_paint_every_n`, `learned_paint_motion_compensation`를 더했다.
  - 격리 값을 위와 같이 바꿨다.
  - CORE 겹에 `arc_enabled`를 명시했다.
  - 고정 값은 그대로다. 시작 자세 `(-1.26955, 0.24255, -1.5708)`, 한 바퀴 route(`lap_trip.py` 기본 NW), `map_v2_fleet_real.world` 복사본, `camera_lane_mode keep`, CORE 겹 `obstacle_mode path`·`ir_guard_enabled`·`site_floor_map_id map_v2_fleet`.
- **지연 주입: 했다.** 스크래치 작업공간의 `runner.py` 끝에 SIM 전용 패치를 붙였다([sim_latency_patch.py](evidence/sim_latency_patch.py)). 이 패치는 `ROSY_SIM_PAINT_LATENCY_MS=300`이면 `LaneSegModel.infer_mask`를 벽시계 300 ms가 될 때까지 잠재운다. 확인 결과는 다음과 같다.
  - 직접 호출하면 세 모델 모두 300 ms였다.
  - 실행 중 mask 나이 p50/p90은 n4+300ms가 0.5/0.75 s, n4+0ms가 0.375/0.5 s, n1+0ms가 0.125/0.125 s였다.
  - 제품 코드는 바꾸지 않았다.
- **arc.** 지시대로 `arc_enabled: false`를 먼저 돌렸다(A). 그런데 **threshold도 링에서 실패했다**(SE에서 `junction_unexpected`, ring Δr 0.195 m). lap SIM 3의 0/12와 같은 결과다. 그래서 모델 비교는 출하 기본 `arc_enabled: true`로 돌렸다. 이 조건은 첫 폐루프 하네스와 같다. arc off 모델 실행은 G 하나다. 모델 실행은 모두 링 전에 멈췄으므로 이 선택은 모델 결과를 바꾸지 않는다.
- **모델.**
  - 28e8454d: `/srv/rosy/store/models/accepted/lane-seg-20261006-28e8454d`, ONNX SHA-256 `28e8454d7e18…`.
  - 62db9403: `~/rosy-ml/scratch/rosy26-training-20261006/intake/lane-seg-20261006-62db9403`, `62db9403ab76…`.
  - v11: `~/rosy_d567_ws/model_candidates/v11`, `5f5ddcd984b3…`.
- **집계.** `learned`는 `paint_source_used=learned`이면서 `paint_model_revision`이 그 모델과 같은 keep 프레임만 센다. 조건마다 1회만 돌렸다.

## 결과

| 실행 | 모델 | every_n / 보정 / 지연 / arc | Fleet | learned / keep | 정지 위치 GT (x,y) | 출발 후 이동 | 주된 정지 신호 | 링 최대 \|Δr\| / 최소 대리 여유 |
|---|---|---|---|---:|---|---:|---|---|
| A | threshold | 2 / – / 0 / **off** | stopped `junction_unexpected` (SE) | – | (−0.369, −0.316) | 1.79 m | 링 이탈 | 0.195 m / −0.189 m |
| B | threshold | 2 / – / 0 / on | **arrived** | 0/618 | NW (−0.514, 0.155) | 2.98 m | – | 22.5 mm / −17.2 mm |
| C | **28e8454d** | 4 / on / 300 / on | stopped `junction_unexpected` | 249/255 (97.6%) | (−1.273, −0.176) | 0.58 m | `junction_waiting`(keeper `junction_transverse`) | 링 전 |
| J | 28e8454d | 1 / off / 0 / on | stopped `junction_unexpected` | 188/194 (96.9%) | (−1.271, −0.197) | 0.44 m | 같음 | 링 전 |
| D | **62db9403** | 4 / on / 300 / on | stopped `junction_unexpected` | 176/181 (97.2%) | (−1.270, −0.008) | 0.25 m | `junction_waiting`(횡단보도) | 링 전 |
| G | 62db9403 | 4 / on / 300 / **off** | stopped `junction_unexpected` | 179/185 (96.8%) | (−1.270, 0.017) | 0.23 m | 같음 | 링 전 |
| I | 62db9403 | 1 / on / 300 / on | stopped `junction_unexpected` | 183/191 (95.8%) | (−1.270, −0.012) | 0.26 m | 같음 | 링 전 |
| K | 62db9403 | 4 / on / 0 / on | stopped `junction_unexpected` | 176/178 (98.9%) | (−1.270, 0.012) | 0.23 m | 같음 | 링 전 |
| H | 62db9403 | 1 / off / 0 / on | stopped `junction` (B_SW aborted, stuck) | 245/390 (62.8%) | (−0.903, −0.528) | 1.05 m | `junction_bend_blocked` 43 | 링 전 |
| F | 62db9403 | **2 / off / 300** / on | arrived — **세지 않음** | **0/552** | NW (−0.484, 0.161) | 2.82 m | – | 42.3 mm / −37.0 mm |
| E | v11 (대조) | 4 / on / 300 / on | stopped `stall` | 357/364 (98.1%) | (−1.271, −0.316) | 0.68 m | `camera_reselection_required` 116, `camera_line_not_visible` 51 | 링 전 |

- **이동 거리.** "출발 후 이동"은 lap_trip이 출발 자세로 옮긴 뒤부터 잰 GT 경로 길이다.
- **신호 집계.** 정지 신호 개수에는 출발 전 준비 구간도 들어 있다(`stuck_back_off` 약 10틱).
- **수치 근거.** 전체 수치는 [metrics.json](evidence/metrics.json)이고, [m26_analyze.py](evidence/m26_analyze.py)로 다시 낸다.
- **every_n 2 + 보정 끔(구 기본, F).** 300 ms 지연이면 learned가 0프레임이다. 9dfk 실기 0/84와 같은 현상이다. 이 설정에서는 사실상 denoise로 달린다.
- **every_n 4 + 보정 켬.** learned 비율 ≥95%는 모든 모델에서 지켰다(warped 재사용이 대부분). **비율은 문제가 아니다.**

## 실패 원인 (영상·마스크·keep_debug)

인용한 8장은 [evidence/diag](evidence/diag/)에 있다. 전체 영상은 `X:\DevTemp\sim-model-lap\diag\<실행>\`에 있다. 왼쪽 그림은 실제 실행 당시의 keep_debug 후보다(초록 선택, 빨강 transverse/거절, 노랑 기타). 오른쪽 그림은 같은 프레임에 그 모델을 다시 추론한 마스크(자홍)다. `timeline.json`은 프레임별 전략·이유·mask 나이를 담는다. 같은 프레임을 threshold와 다른 모델에 넣은 재생은 [m26_pair.py](evidence/m26_pair.py)로 했다(새 마스크, warp·route context 없음).

### 1. 28e8454d: 흰 벽면·벽 밑단을 도색으로 칠한다 → 오른쪽 경계 왜곡 → 가짜 `junction_transverse` (모델)

- **위치.** 실행 C와 J 모두 B_SW 굽이 약 0.25 m 앞, y ≈ −0.18…−0.20에서 멈췄다. J는 매 프레임 새 마스크(나이 0.125 s)였다. 그래서 **재사용·warp·지연 탓이 아니다.**
- **오른쪽 경계.** threshold B는 같은 자리에서 `both`였고 오른쪽 경계 방향은 −0.2°였다([B 0053.625](evidence/diag/B_threshold_arcon_y-0.17_0053.625.png)). 28e8454d는 오른쪽 테이프와 함께 벽 밑단 띠와 흰 벽면 덩어리까지 칠한다([J 0041.500](evidence/diag/J_28e8454d_n1_lat0_0041.500.png)). 그 결과 오른쪽 경계가 −21…−25°로 기울었다.
- **멈춤 경과.** 굽이 바깥의 가로 테이프가 transverse(87°, 0.27–0.34 m)로 들어왔다. 짧아진 왼쪽 선이 끊기자 keeper가 `none / junction_transverse`를 냈다([J 0042.000](evidence/diag/J_28e8454d_n1_lat0_0042.000.png)). CORE는 `junction_waiting`이 됐다. Fleet은 아직 B_SW를 무장하지 않은 자리라서 `junction_unexpected`로 trip을 멈췄다.
- **분류.** 주원인은 모델 오검출(흰 벽·밑단, 지면이 아닌 화소)이다. 부원인은 keeper가 한 프레임의 `junction_transverse`를 최종 판단으로 넘기는 민감도다. 실물 현장도 흰 벽이므로 장치에서도 같은 위험이 있다(실물 미확인).

### 2. 62db9403: 벽 쪽 오른쪽 차선을 거의 못 칠한다 → 한쪽선 + 횡단보도 모서리 선택 → `junction_transverse` (모델 + keeper)

- **재현.** 다섯 변형 가운데 네 번(D, G, I, K)이 y ≈ 0의 주차 spur 횡단보도에서 멈췄다. every_n·보정·지연·arc와 무관하다.
- **경과.**
  - 출발부터 keep이 계속 `left_only`였다([D 0039.500](evidence/diag/D_62db9403_early_0039.500.png)). 오른쪽(벽에 붙은) 테이프 마스크는 조각뿐이다.
  - 횡단보도에 들어서자 keeper가 줄무늬 앞 모서리를 왼쪽 경계로 골랐다(15–22°; [D 0041.875](evidence/diag/D_62db9403_n4comp_lat300_0041.875.png)).
  - 이어 transverse가 들어오면서 `junction_transverse`가 됐다([D 0042.125](evidence/diag/D_62db9403_n4comp_lat300_0042.125.png)).
- **같은 프레임 재생.** threshold와 28e8454d는 `both` 또는 `xwalk`였다. 62db9403만 `left_only`였다가 `none`으로 떨어졌다.
- **H(n1, 지연 0) 예외.** 횡단보도를 넘고 B_SW 굽이까지 갔다. 그곳에서 `junction_bend_blocked` → stuck으로 abort됐다. 그 실행은 37%가 fallback이었다.
- **분류.** 주원인은 모델 미검출(벽에 붙은 차선)이다. 부원인은 keeper가 한쪽선일 때 횡단보도 모서리를 경계로 고르는 것이다.

### 3. v11(대조): 굽이 바깥 테이프를 못 칠한다 → `no_boundary` → 재선택 정지 (모델)

- **위치.** 실행 E는 y ≈ −0.37, B_SW 굽이 바로 앞에서 오른쪽 짧은 사선만 남기고 `no_boundary`가 됐다([E 0047.875](evidence/diag/E_v11_n4comp_lat300_0047.875.png)). 이후 back-off → `camera_reselection_required`로 stall했다.
- **같은 프레임 재생.** threshold와 28e8454d는 `corner_left`, 62db9403은 `corner_ahead`였다. v11만 `none`이었다.
- **첫 하네스와의 차이.** 첫 하네스에서 v11은 도착했다. 이번 차이는 every_n 4 + 지연 300 ms 조건, 또는 실행 1회의 산포다(구분하지 않았다).

## 한 바퀴를 돌게 할 가능성이 가장 큰 변경

1. **학습 데이터: 흰 벽면·벽 밑단 음성 예시, 벽에 붙은 차선 테이프 양성 예시.** 두 rosy26 모델의 실패가 정확히 이 둘이다. 28e8454d는 벽을 칠하고, 62db9403은 벽 옆 테이프를 놓친다. 이 장면은 실물 현장(흰 벽)에서도 생긴다.
   - 해당 사건 프레임은 각 실행 `rec/frames.npz`에 있다.
   - D-475 사람 검수 경계로 라벨을 붙여 기존 모델을 같은 설정으로 미세조정한다.
   - 그다음 이 하네스로 C/D/J를 다시 돌린다.
   - SIM 영상은 진단용으로만 쓴다. 학습 세션과 평가 세션은 분리한다.
2. **(검증 필요) 지면이 아닌 도색 화소 차단.** LiDAR가 잰 벽 거리보다 먼 지면 투영 도색 점을 keeper에서 버린다. 흰 벽 오검출이 경계 적합을 기울이는 경로를 모델과 무관하게 막는다. 28e8454d를 이 상태로 SIM에서 돌리면 서쪽 길을 지나갈 가능성이 가장 크다. 이 기록에는 LiDAR 스캔이 없어서 오프라인 검증은 못 했다. 다음 실험은 이 차단 하나만 넣은 C/J 재실행이다.
3. **설정.** 실기에서는 every_n 2 + 보정 끔을 쓰지 않는다(learned 0%). every_n 4 + 보정 켬은 learned ≥95%를 낸다. 이번 실패의 원인도 아니었다(J·K와 C·D가 같은 자리에서 멈춤).
4. **keeper 민감도(부차).** 한 프레임의 `junction_transverse`나 한쪽선 상태의 횡단보도 모서리 선택이 trip 전체를 멈춘다. 이 점은 threshold에는 드러나지 않는다. 모델을 고치기 전에 이것만 완화하는 것은 경계 안전 근거가 없어 권하지 않는다.

## 남은 것

- **반복.** 조건당 1회다. 그래도 실패 위치는 모델마다 2–5개 변형에서 같았다.
- **arc off 완주.** arc off는 threshold도 링을 못 돈다. 그래서 "arc off 완주"는 CORE 링 주행(D-520 장치 조건)이 먼저 풀려야 의미가 있다.
- **원본 위치.** 원본 `frames.npz`는 모델 PC `~/rosy_m26_ws/runs/<실행>/rec/`에 남겼다. 로그 묶음(프레임 제외)은 [runs_no_frames.tgz](evidence/runs_no_frames.tgz)(SHA-256 `2527bab81974f48ad7f5f925e898459cc8eca2904b05f8fd1057b67244e5bca5`)다.
