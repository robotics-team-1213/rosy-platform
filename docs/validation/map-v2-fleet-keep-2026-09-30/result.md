# map_v2_fleet real-profile sim: closed-loop 'keep' lane keeping (D-364 §5), 2026-09-30

증거 등급: **ROS-SIM (폐루프 주행)**. 장치·필드 수용이 아니다. 실물 설정(`lane_corner_turning: false`)의
`keep` 동작은 바뀌지 않았고, 모서리 회전은 이 sim launch 에서만 켜진다.

## 무엇을 돌렸나

- 월드: `map_v2_fleet_real.launch.py camera_lane_mode:=keep` (실물 카메라 기하 320x240, fx 281.6, 8°, 0.067 m,
  카펫·흰 벽; `docs/validation/map-v2-fleet-real-profile-2026-09-30/`). 이 launch 는 이미
  `lane_corner_turning: True` 를 준다.
- CORE: sim 전용 overlay — `api_port 8093`(8080 은 다른 sim 이 쓰는 중), `line_follow.obstacle_stop_m 0.10 /
  obstacle_resume_m 0.14`. 장치 기본값(0.20/0.28)은 그대로다. L 모서리에서 둘레 벽이 base_link 앞 ~0.2 m 라
  기본값이면 모서리마다 `obstacle_ahead` 로 선다(run A2).
- 주행: CORE REST — `PUT /api/v1/line-follow/mode {mode: CAMERA_LINE, hold_s: 0.5}`, `POST /hold` 10 Hz,
  끝나면 `mode OFF`. 명령 법칙·속도·게인은 장치 기본값(cruise 0.08, gain 0.8) 그대로다.
- 측정: Gazebo 참 자세(`/world/map_v2_fleet/pose/info`, 모델 `rosy`)를 ~5 Hz(벽시계)로, 차선 중심은
  `lane_graph.yaml` 의 segment 점열(두 경계선 사이의 가운데, 차로 반폭 92.5 mm, 테이프 25 mm).
  - 횡오차 = 가장 가까운 차로 중심선까지 거리.
  - touch = 로봇 발자국(폭 0.10 m)이 테이프에 닿음(|횡오차| > 30 mm), cross = 발자국 가장자리가
    경계선 중심을 넘음(> 42.5 mm), off-lane = 로봇 중심이 선 밖(> 92.5 mm).
- 호스트: WSL, 다른 에이전트의 `rosy_factory` sim 과 같이 돌아 RTF 0.08-0.4. CORE 의 line-follow 는
  sim 시간으로 판단하므로(`use_sim_time`) 느린 RTF 는 주행을 느리게 할 뿐 판단을 바꾸지 않는다.

## 재현

```bash
# WSL, 작업공간 /rosy_realprof_ws (HOME=/). 바뀐 파일만 cat 으로 복사한다(9p tar 는 느리다).
W="/mnt/f/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/pilot-teleop"
for f in src/runtime/sensing/control/sensing/perception/lane_keep.py src/runtime/sensing/control/line_observer_node.py; do
  cat "$W/$f" > /rosy_realprof_ws/$f; done          # --symlink-install 이라 빌드 불필요
bash "$W/docs/validation/map-v2-fleet-keep-2026-09-30/evidence/run_sim.sh"      # 전경 실행, CORE 127.0.0.1:8093
# 다른 셸
source /opt/ros/jazzy/setup.bash; source /rosy_realprof_ws/install/setup.bash
export ROS_DOMAIN_ID=53 GZ_PARTITION=rosy_realprof
python3 "$W/docs/validation/map-v2-fleet-keep-2026-09-30/keep_run.py" --out /rosy_realprof_ws/keep/runs/A8 \
  --spawn=-1.26955,0.24255,-1.5708 --duration 120 --fps 4
```

`keep_run.py` 는 log.csv(상태+자세), frames/, frames.csv, events.txt, metrics.json, trajectory.png 를 쓴다.
영상: `python make_video.py RUN_DIR lane_graph.yaml OUT.mp4 --fps 12` (Windows, ffmpeg).
sim 프레임 벤치: `python tools/lane_replay.py --frames RUN_DIR/frames --crop none --keep-bright
--detectors line,between,keep,keep_corner --out X:/...` (`--keep-bright`: 흰 벽이 화면 60% 를 넘는 가제보
프레임을 빈 화면으로 건너뛰지 않는다).

## 반복 (같은 출발: edge_left 랩 출발점 (-1.26955, 0.24255), 남쪽)

| run | 코드 | sim s | 거리 m | 횡오차 평균/최대 mm | touch/cross | 끝 |
|---|---|---|---|---|---|---|
| T0 | 88495b65 이전 (`keep` 원본) | 17.5 | 0.578 | 1.5 / 3.4 | 0/0 | LOST: 좌하 L 모서리 앞, 경계 없음 |
| A1 | + 모서리 회전 | 4.2 | 0.065 | 0.1 / 0.2 | 0/0 | LOST: 첫 횡단보도에서 양쪽 선이 blob 으로 빠짐 |
| A2 | + 한쪽 flank (66188a11) | 240 | 0.658 | 1.4 / 3.4 | 0/0 | 모서리에서 `obstacle_ahead` 로 정지(벽 0.2 m) → sim overlay |
| A3 | + 장애물 overlay | 23.7 | 0.802 | 3.6 / 33.2 | 1/0 | LOST: 회전 중 직진 규칙이 다시 걸려 −32° 로 벽을 봄 |
| A4 | + 회전 중 계속 추종 (dd8bff8f) | 24.3 | 0.712 | 1.7 / 17.4 | 0/0 | LOST: 25° 회전 뒤 새 바깥선을 옆 경계로 읽어 반대로 돔 |
| A5 | + 가파른 선도 모서리 선 (cbc2a665) | 25.9 | 0.730 | 3.7 / 36.3 | 1/0 | LOST: 같은 반대 회전 |
| A6 | 같음, 매 프레임 저장 | 23.4 | 0.705 | 1.9 / 17.3 | 0/0 | 재생으로 원인 확인: 잠긴 방향이 오른쪽으로 뒤집힘 |
| A7 | + 방향 고정·회전 유지 (f84e81e9) | 200 | 1.033 | 12.3 / 61.9 | 2/1 | **첫 L 모서리 통과**, 이어진 셰브런 굽이를 일찍 꺾어 안쪽 벽 앞 `obstacle_ahead` |
| A8 | + 가파른 선은 잠금 소모 (3539738d) | 50.9 | **1.531** | 25.3 / 84.5 | 3/3 | 모서리·하단 직선·셰브런 굽이 통과, SW 진입로 끝(회전교차로 앞)에서 LOST |

다른 출발점:

| run | 출발 | sim s | 거리 m | 횡오차 평균/최대 mm | touch/cross | 끝 |
|---|---|---|---|---|---|---|
| B1 | 하단 직선 (-1.05, -0.509), 동쪽 | 20.9 | 0.509 | 20.5 / 76.4 | 2/2 | 셰브런 굽이 통과(안쪽 자름), SW 진입로 위 (-0.566, -0.425)에서 LOST |
| C1 | 동쪽 도로 하단 직선 (0.70, -0.509), 서쪽 | 16.4 | 0.509 | 1.9 / 20.6 | 0/0 | 직선 통과, x 0.20 에서 LOST: 바깥선이 벽 밑이라 벽 마스크에 먹히고 안쪽 선은 SE 진입로로 열림 |

판정:

- **직선: 통과.** 모든 run 에서 직선 차로의 횡오차는 3.4 mm 이하(T0/A2/A4/A6 서쪽 직선, 횡단보도 포함).
- **L 모서리: 통과하지만 안쪽으로 자른다.** A7/A8 에서 좌하 모서리를 돌았다. 모서리 추종 앞보기 0.12 m 와
  CORE 의 포화 조향(0.7 rad/s) 때문에 안쪽을 자르고, 빠져나온 뒤 하단 직선에서 40-60 mm 안쪽에서
  천천히 수렴한다(발자국이 안쪽 선 중심을 넘은 시간 A8 17.4 s).
- **셰브런 굽이(약 60°): 통과(A8)**, 역시 안쪽으로 자른다.
- **회전교차로: 실패.** SW 진입로 끝에서 원형 선을 경계로 못 잡아 HOLD→LOST(fail-closed). `keep` 은 직선
  RANSAC 이라 원호를 못 다룬다.
- 한 바퀴(3.06 m, 2026-09-22 edge_left 랩) 는 아직 못 돌았다. 최고 1.531 m.

## 바꾼 것 (모두 `perception/lane_keep.py`, 시험 `test_lane_keep.py` 11 → 18)

1. 모서리 회전(선택, `corner_turning` = 노드의 `lane_corner_turning`, 실물 기본 false): 앞을 가로지르는 선이
   한쪽은 바깥 차로선에서 끝나고(±30 mm) 다른 쪽으로 차로 밖까지 뻗으면 다음 차로의 바깥 경계다. 그 선을
   반폭만큼 로봇 쪽으로 옮긴 중심선을 열린 쪽으로 앞보기 0.12 m 에서 추종하고, 그보다 멀면 직진한다.
   방향은 가로선이 남아 있는 동안 잠그고(자세 없이 프레임 수), 한 번 돌기 시작하면 직진으로 돌아가지 않으며,
   잠금 중에는 35° 넘게 기운(열린 쪽으로) 선도 모서리 선이다. 가파른 선은 잠금을 갱신하지 않고 소모한다.
2. flank 시험을 한쪽 기준으로: 횡단보도 막대는 차로선의 한쪽 flank 만 밝힌다. 양쪽 flank 가 모두
   밝거나(각 0.225×core) 합이 0.6×core 를 넘을 때만 blob.
3. `tools/lane_replay.py`: 검출기 `keep_corner`, `--keep-bright`.

## 녹화 재생 벤치 (공칭 지면, `keep` 기본 = 실물 설정)

| 묶음 | 지표 | 기준(D-364) | 이후(3539738d) | keep_corner |
|---|---|---|---|---|
| pilot 307 | on_line / on_paint / none | 0.102 / 0.015 / 0.332 | 0.083 / 0.015 / 0.332 | 0.063 / 0.015 / 0.332 |
| teleop 576 | on_line / on_paint / none | 0.042 / 0.071 / 0.094 | **0.043** / 0.070 / 0.080 | 0.048 / 0.063 / 0.068 |
| sim A8 202 | on_line / on_paint / none | — | 0.043 / 0.049 / 0.084 | 0.070 / 0.050 / 0.005 |

- teleop on_line 이 한 프레임(0.042 → 0.043) 나빠졌다: `part06` f_00121, 눈부심 속 곡선 한 장. on_paint·none
  은 좋아졌다. 이 한 프레임은 기준 위반으로 기록한다.
- `keep_corner` 의 teleop on_line 증가는 모서리 프레임에서 목표가 화면 가장자리(|error|≈1)로 가고, 하단 띠를
  가로지르는 모서리 선이 어느 열에서나 걸리는 on_line 지표의 성질 때문이다. on_paint 는 좋아진다. 그래도
  실물 기본은 꺼 둔다.
- 입력: pilot = `2026-09-29-obstacle-stop/{obstacle-cleared-run3,obstacle-stop-run1}.mp4` +
  `2026-09-29-lane-auto/rosy-pilot-lane-auto-2026-09-29{,-run2}.mp4` (`--crop pilot-side --fps 4`),
  teleop = `teleop_20260919_151213_part{01,03,06}.mp4` (`--crop none --fps 2`).

## 증거 (저장소 밖, D-226)

`X:\DevTemp\rosy-pilot-evidence\2026-09-30-sim-keep\`: `sim-keep-A8.mp4`(최고 run, 상태·오차·자세·횡오차
오버레이 + 조감 지도), `trajectory-A8.png`, `metrics-A8.json`, 같은 것의 A7. 원시 로그와 프레임:
WSL `/rosy_realprof_ws/keep/runs/<run>/`, 사본 `X:\DevTemp\sim-keep\runs\`.

## 태블릿에서 보기

- sim: WSL 에서 `evidence/run_sim.sh` (CORE `127.0.0.1:8093`, 카메라 중계 `sim_jpeg_relay.py` → `camera/preview/compressed`;
  `GET /api/v1/vision/front/status`·`/frame?sequence=N` 확인, 320x240 jpeg).
- Windows 는 WSL localhost 전달로 `http://127.0.0.1:8093` 에 바로 닿는다. 태블릿은 pilot 중계로:
  `python tools/pilot_device_bridge.py --robot http://127.0.0.1:8093 --host 0.0.0.0 --port 8094`
  → 태블릿 `http://<이 PC LAN IP>:8094/pilot/` (또는 USB `adb reverse tcp:8094 tcp:8094` 후
  `http://localhost:8094/pilot/`). 로그인은 dev 토큰 `rosy-dev-operator`(조작)·`rosy-dev-viewer`(보기),
  `ROSY_DEV_AUTH=1` 인 이 launch 에서만 유효.

## 알려진 실패·남은 일

- 회전교차로(원호 경계)와 T/Y 분기: `keep` 은 직선만 다룬다. 원호 피팅 또는 곡선 차로 모델이 필요하다.
- 모서리 안쪽 자르기와 느린 수렴: 앞보기·명령 법칙(오차 포화) 조정이 다음 반복이다(장치 기본값 변경 없이 sim
  overlay 로 먼저).
- 벽이 가까우면 벽 밑 테이프가 벽 마스크에 먹힌다(A3 −32° 장면, C1 x 0.20).
- 장애물 정지 0.10 m 는 sim 전용이다. 실물 트랙 모서리에서도 벽이 0.2 m 안이면 같은 정지가 난다 — 장치에서 확인 필요.
- sim 은 흐림·노출 변화가 없다. 녹화 벤치가 실물 쪽 관문이다.

## 2026-09-30 (저녁) keep v2: 경계 추적과 벽 밑 테이프 (feat/lane-keep-v2)

증거 등급: 녹화 재생 벤치(SOURCE) + ROS-SIM 폐루프. 장치·필드 수용이 아니다. 실물 설정 값은 바꾸지 않았다
(`camera_lane_mode: keep`, 모서리 회전 꺼짐); 아래 두 변경은 `keep` 기본 경로에 들어간다.

### 바꾼 것 (`perception/lane_keep.py`, 시험 18 → 23)

1. **경계 추적(약점 1, fc2a81dc)**: 오도메트리 없이 직전 프레임의 경계 목록(앞 0.22 m 횡오프셋, 기울기, 좌·우)을
   기억한다. 이번 선이 직전 경계와 6 cm·20° 안이면 같은 경계로 보고, 반대쪽으로 8 cm 넘게 넘어가기 전까지는 좌·우를
   이어받는다. 한쪽만 보일 때는 추적된 경계를 가장 가까운 경계보다 먼저 고른다. 목표의 프레임당 이동 제한(0.035 m)도
   시도했으나 좌·우가 실제로 바뀌는 순간 목표를 테이프 위로 끌고 가서(on_paint teleop 0.064 → 0.094) 뺐다.
2. **벽 밑 테이프(약점 3, 2d947c18)**: 벽 줄기(지평선 위에서 시작하는 밝은 열)가 어두워질 때만이 아니라 **밝기 계단**
   (3×3 평균, 3 행 사이 V 16 넘게 떨어짐)에서도 끝난다 — 벽 밑에 붙은 테이프는 카펫보다 밝지만 벽보다 어둡다. 벽 판정
   밝기는 바닥 전체의 10 백분위 카펫 기준으로도 묶는다: 벽이 바닥 행 대부분을 채우면 행별 기준이 255 까지 올라 벽을
   못 찾고, 벽 아랫부분이 흰 덩어리로 남아 테이프를 삼켰다(C1 x 0.20, 재생 확인).
3. 약점 2(모서리 안쪽 자르기)·4(원호): 이번에는 코드 변경 없음(아래 남은 일).

### 녹화 재생 벤치 (공칭 지면, `keep` 기본 = 실물 설정)

프레임은 `X:\DevTemp\lane-keep-v2\frames\{pilot,teleop}` 에 한 번 풀어 `--frames` 로 돌렸다(영상 경로와 같은 프레임 수·
같은 기준값 재현: pilot 307, teleop 576).

| 묶음 | 지표 | main(3539738d) | + 추적(fc2a81dc) | + 벽 밑 테이프(2d947c18) |
|---|---|---|---|---|
| pilot 307 | on_line / on_paint / none / jump | 0.083 / 0.015 / 0.332 / 0.016 | 0.049 / 0.015 / 0.332 / 0.007 | **0.019 / 0.014 / 0.319 / 0.007** |
| teleop 576 | on_line / on_paint / none / jump | 0.043 / 0.070 / 0.080 / 0.047 | 0.040 / 0.064 / 0.080 / 0.024 | **0.040 / 0.066 / 0.078 / 0.024** |
| sim A8 202 | on_line / on_paint / none / jump | 0.043 / 0.049 / 0.084 / 0.025 | 0.016 / 0.032 / 0.084 / 0.035 | 0.005 / 0.032 / 0.074 / 0.035 |
| sim A8 (keep_corner) | on_line / on_paint / none / jump | 0.070 / 0.050 / 0.005 / 0.060 | 0.045 / 0.035 / 0.005 / 0.070 | 0.035 / 0.035 / 0.005 / 0.055 |

- 실물 두 묶음의 모든 지표가 main 이하. teleop jump 0.047 → 0.024. 남은 teleop 튐은 사람이 선을 가로질러 몬 장면
  (2 fps 에서 한 프레임에 6 cm 넘게 움직이는 가파른 선)이다.
- sim A8 의 jump 는 0.025 → 0.035 로 나빠졌다(모서리 구간 2 프레임). 실물 관문이 아니라 기록만 한다.
- 벽 계단 문턱은 민감하다: 3×3 평균에서 V 13 이면 pilot none 0.342, 16·20 은 0.319·0.329. 5 행 평균 + 12-14 는
  pilot none 0.33-0.36 사이를 오갔다. 16 을 골랐다(이웃 20 도 관문 통과).

### 폐루프 (real-profile sim, 같은 명령 법칙·게인·sim overlay)

호스트 부하: 다른 세션의 WSL 빌드와 같이 돌아 RTF ≈ 0.17. `keep_run.py` 는 sim 시간으로 판단하므로 결과는 같다.

| run | 출발 | 코드 | sim s | 거리 m | 횡오차 평균/최대 mm | touch/cross/off-lane | 끝 |
|---|---|---|---|---|---|---|---|
| A8 | edge_left (-1.26955, 0.24255) 남 | main | 50.9 | 1.531 | 25.3 / 84.5 | 3/3/0 | SW 진입로 끝 LOST |
| **V1A** | 같음 | 2d947c18 | 89.0 | **3.496** | 34.3 / 228.1 | 4/4/2 | 동쪽 고리 안쪽에서 HOLD 반복(시간 끝) |
| B1 | 하단 직선 (-1.05, -0.509) 동 | main | 20.9 | 0.509 | 20.5 / 76.4 | 2/2/0 | SW 진입로 위 LOST |
| V1B | 같음 | 2d947c18 | 44.9 | 1.326 | 33.4 / 147.0 | 3/3/1 | 셰브런 자름 → 회전교차로 고리 안으로 들어가 북쪽(시간 끝) |
| C1 | 동쪽 하단 직선 (0.70, -0.509) 서 | main | 16.4 | 0.509 | 1.9 / 20.6 | 0/0/0 | x 0.20 LOST(벽 마스크) |
| V1C | 같음 | 2d947c18 | 55.0 | 2.001 | 81.1 / 310.2 | 1/1/1 | x 0.20 에서 좌·우 ±1 진동 → 둘레 벽에 붙어 서쪽으로 미끄러짐(시간 끝) |

판정:

- **좌하 L 모서리와 서쪽·하단 직선(x < -0.8): 거의 같음.** 횡오차 평균/최대 V1A 15.8 / 64.9 mm, A8 19.4 / 62.3 mm. 모서리 안쪽 자르기는 그대로다(약점 2 미해결).
- **거리는 늘었지만 차로 안에 머문 것은 아니다.** V1A 는 셰브런 굽이 뒤 SW 진입로를 따르지 않고 회전교차로 남쪽을 곧게
  가로질러 동쪽 하단 직선에 올랐다(off-lane 2). 동쪽 직선은 다시 0-10 mm 로 지켰고, 동쪽 고리(원호)에서는 안쪽으로
  60 mm 넘게 흘렀다. 3.06 m 한 바퀴(edge_left 경로)는 여전히 못 돌았다.
- **C1: LOST 는 사라졌지만 더 나빠졌다.** 벽 밑 바깥선이 보이게 되자 x 0.20 의 SE 진입로 분기에서 모서리 오른쪽/바깥선
  왼쪽 사이를 ±1.0 으로 오가다 둘레 벽 쪽으로 가서 붙었다(sim 물리가 벽을 따라 미끄러지게 둠, 장애물 정지 0.10 m 는
  라이다 최소 거리 안이라 못 멈춤). 오프라인 4 fps 재생은 계속 오른쪽(모서리)을 내므로 8 fps 라이브의 모서리 잠금
  순서 차이다 — 원인 미확정. **분기에서 fail-closed 가 아니다**: 이 변경을 실물 모서리 회전과 함께 켜면 안 된다.
- 회전교차로: V1B 는 고리 안으로 들어가 북쪽으로 갔다(차로를 지키지 못함, off-lane 1).

### 증거 (저장소 밖, D-226)

`X:\DevTemp\rosy-pilot-evidence\2026-09-30-sim-keep-v2\`: `sim-keep-v2-V1A.mp4`(최고 거리 run, 상태·오차·자세 오버레이 +
조감 지도), `trajectory-V1{A,B,C}.png`, `metrics-V1{A,B,C}.json`. 원시 로그·프레임: WSL `/rosy_realprof_ws/keep/runs/V1{A,B,C}/`,
사본 `X:\DevTemp\lane-keep-v2\runs\`. 벤치 결과 `X:\DevTemp\lane-keep-v2\bench\{base,s1,s3}\`.

### 남은 일 (우선순위)

1. **분기에서 fail-closed**(C1·V1A·V1B): 한쪽 경계만 보이고 그 경계가 차로 밖으로 벌어지는 선(진입로 입구, 둘레선)과
   모서리 선이 동시에 있으면 HOLD 해야 한다. 지금은 모서리 잠금과 한쪽 추종이 번갈아 이긴다. 라이브 디버그 묶음
   (`strategy`)을 `keep_run.py` 가 기록하게 해야 8 fps 라이브 순서를 재현할 수 있다.
2. 모서리 안쪽 자르기(약점 2): 회전 중 오차 상한(CORE 포화 0.7 rad/s 방지)과 모서리 앞보기 조정 — 이번에는 시도하지 못함.
3. 원호(약점 4): 동쪽 고리에서 안쪽으로 흐름. 로봇 가까운 짧은 구간 적합(또는 2차) 필요.
4. 벽 계단 문턱(V 16)은 sim 벽(215)·테이프(192) 대비에서 정했다. 실물 흰 폼보드와 테이프의 대비는 로봇 복귀 뒤 원본
   녹화로 확인해야 한다.
