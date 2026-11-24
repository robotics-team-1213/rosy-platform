# OMX 실물↔시뮬 반복 루프

양팔 OMX 셀에서 실물을 재 시뮬에 넣고(real→sim), 시뮬에서 통과한 것을 실물에서 확인한 뒤(sim→real), 둘의 차이를 기록해 다음 바퀴를 고른다. 차이 목록은 [sim2real 레지스트리](sim2real-gaps.md)의 OMX 행(G-17~)이다. 분류와 기록 규칙은 D-480, 시뮬이 주장할 수 있는 범위는 D-947을 따른다.

## 언제 한 바퀴 도나

- 셀이 바뀌었을 때(임시판·배·카메라·팔 받침 이동): 1~4단계.
- 매일 밤: `omx_twin_night.py`가 그날 에피소드로 6단계를 돈다.
- 실물이 멈추거나 미끄러졌을 때: 6~7단계, 그 사례가 Isaac 사례가 된다.

## 한 바퀴

| 단계 | 방향 | 하는 일 | 도구 | 남는 것 | 사람 몫 |
|---|---|---|---|---|---|
| 1 관측 | 실물 | 카메라 4대 프레임, 관절 상태 | `omx_real2sim.py capture` | `RUN/frames/` | 없음 |
| 2 측정 | real→sim | 항목마다 병렬로 재서 스냅샷 하나 | `omx_real2sim.py measure --prev` | `snapshot.json`, `overlay.png` | 겹침 그림 확인 |
| 3 차이 | real→sim | 바뀐 항목 → 다시 돌릴 단계와 레지스트리 행 | `omx_real2sim.py diff` / `omx_real2sim.py pipeline` | `changed`, `rerun`, `gaps` | 없음 |
| 4 시뮬 | sim | 바뀐 단계만, Stage 1(MuJoCo) → Stage 2(Isaac Sim 핸드오프) 직렬 파이프라인 | `omx_real2sim.py sim` / `pipeline`, `/console/cell` (`cell_real2sim.py`) | `sim.json`, `pipeline.json`, `rosy.omx-isaac-handoff.v1` | 없음 |
| 5 실물 시도 | sim→real | 시뮬에서 통과한 계획을 감독 시험으로 | 셀 파이프라인, 에피소드 기록 | 에피소드 | 전원 스위치 옆에서 지켜보기(D-911) |
| 6 대조 | sim→real | 실물 에피소드를 쌍둥이에 재생(추종·시야), Isaac 사례와 실물 결과 비교 | `omx_twin.py batch`/`report`, `cell_case_suite.py` | 쌍둥이 보고서, 사례 결과 | 없음 |
| 6b 상수 맞춤 | real→sim | 실물 기록으로 물리 상수를 맞추고, 보류 에피소드에서 나아진 것만 후보로 올린다. `next`가 다음에 잴 상수와 실험을 고른다 | `omx_sysid.py servo`/`friction`/`promote`/`next`, 실험 `cell_step.py`·`cell_push.py --friction` | `fit.json`·`friction.json`, `cell_physics.yaml`의 새 후보(`--choice physics=<이름>`) | 실험 때만 전원 스위치 옆(D-911) |
| 7 기록 | 둘 다 | 차이를 M·R·D로 나눠 레지스트리 행의 상태와 `next`를 고침 | `tools/harness/sim2real_gaps.yaml`, `rosy_harness.py lint` | 행 갱신 커밋 | 실측값이 필요한 행만 |

3단계의 스냅샷은 저장소의 `deploy/robot/omx/sim/cell_snapshots/`에 커밋해야 4단계가 읽는다(시험 PC는 커밋만 받는다).

## 보관 기록으로 실행하기

```text
python tools/sim/omx_loop.py all --run --run-sweep --run-dir RUN --capture CAPTURE --sweep SWEEP --store CANDIDATES.json --attempts ATTEMPTS.jsonl --episodes EPISODES --cell ARM_B_CELL.json --stack-check TIER_PROOF.json --local-twin
```

새 실험에는 빈 `RUN`과 `SWEEP` 경로를 사용한다. `--run`을 빼면 실행 순서를 출력한다. `--local-twin`에는 MuJoCo가 필요하다. 이 옵션을 빼면 등록된 시험 PC에서 보관 에피소드를 재생한다.

상단 보정을 통과한 스냅샷이 카메라와 임시판·선박·벨트 배치를 결정한다. 운반 시험과 후보에는 스냅샷 해시가 붙는다. 시험을 재사용하려면 같은 스냅샷의 해시가 필요하다. 층 검증 근거가 없는 안착 시도는 미확인으로 기록한다. 재생에서 얻은 시야·관절 추종 차이는 다음 측정 스냅샷에 보정 후보로 남는다.

## 카메라의 작은 픽셀 변화 확인

- R2S의 반복 측정에는 같은 프리셋으로 만든 직전 스냅샷을 `measure RUN --prev SNAPSHOT` 또는 `pipeline RUN --prev SNAPSHOT`에 지정한다. `frames.top`은 현재 촬영본의 해시다. `camera_reference_top`은 현재 카메라 자세와 짝을 이루는 기준 촬영본의 해시다. 원본 프레임은 `ROSY_REAL2SIM_FRAMES`에 보관한다.
- 기준 대비 3 px, 0.3°, 배율 0.5% 중 하나를 넘으면 기존 패드 기준점 PnP를 다시 맞춘다. PnP에는 기준 때 고정한 `camera_reference_lanes` 좌표를 쓴다. 보정이 통과하면 자세와 기준 프레임을 함께 갱신한다. 기준 프레임이 없거나 비교점이 부족하면 자세를 다시 맞춘다. 해상도가 달라지면 촬영 프로필을 먼저 확인한다. `pipeline` 출력의 `previous`는 차이 비교용이고, 실제 카메라 비교 기준은 `camera_motion.reference_top`에 기록한다.
- S2R은 학습 프레임과 현재 녹화 프레임에서 동일한 고정점을 원본 픽셀 좌표로 측정한다. 위·측면 카메라별로 적합에 쓸 점 두 개와 검증에 쓸 점 두 개 이상을 고른다. 검증점은 벨트와 상판처럼 위치와 높이가 다른 작업 구역에서 고른다. 두 프레임의 촬영 프로필과 해상도를 확인한다.

```text
python tools/sim/omx_policy_camera_drift.py TRAIN.jpg LIVE.jpg ANCHORS.json --max-shift-px SHIFT_LIMIT --max-residual-px RESIDUAL_LIMIT
```

`ANCHORS.json`에 `camera`(`top` 또는 `side`), `training_profile`, `live_profile`, `reference_xy`, `live_xy`를 넣는다. 두 좌표 배열의 순서를 맞춘다. 각 좌표를 잰 원본 파일의 해시를 `reference_sha256`과 `live_sha256`에 `sha256:<64자리 hex>` 형식으로 적는다. 허용 이동과 잔차는 검증할 정책의 기준에 맞춰 지정한다. 보고서에는 원본 해시, 좌우·상하 편차, 검증점별 보정 전후 오차, 통과한 이동 보정 행렬이 담긴다. 여러 녹화 쌍에서 확인한 뒤 같은 보류 에피소드로 원본과 보정 후보의 정책 결과를 비교한다. 이 명령은 후보 보고서를 출력한다.

### ACT가 견뎌야 할 시점 변화

실물 시연을 정리할 때 위·옆 영상의 촬영 각도를 유지한다. 소각도 차이가 있는 정상 시연도 같은 카메라 역할·해상도·시각 정렬과 동작 라벨 검사를 거쳐 학습에 쓸 수 있다. 녹화 세션 단위로 학습과 검증 자료를 먼저 나눈다. 변환본의 `meta/camera_views.json`에는 원본 자료 ID와 에피소드 인덱스를 남긴다. 실측 각도가 없으면 각도는 미상으로 기록한다.

Canonical spec에 `camera_angle_jitter_deg`를 추가하면 `collect_dart`에서 시뮬 top·side·손목 카메라의 각 축 회전량을 지정 범위 안에서 뽑는다. 한 시나리오 동안 같은 각도를 사용하며 네 번째 시나리오마다 기본 자세로 촬영한다. 에피소드마다 적용한 각도와 시드를 `meta/camera_views.json`에 남긴다. 이 파일도 데이터 게이트가 영상과 함께 해시로 묶는다. 예를 들어 `0.3`은 축별 ±0.3° 실험이며, 각 카메라의 실측 증거에 맞춰 범위를 선택한다.

`eval_ladder`는 기본 시야 평가와 동일한 과제 시드에서 각도만 바꿔 한 번 더 평가한다. 각도 난수는 학습과 다른 계열을 사용한다. `camera_robustness.json`으로 기본과 변형 시야의 성공, 접촉, 층별 결과를 비교한다. 실물 시점 수용은 별도 녹화 세션에서 확인한다.

## CAD194 손목 후보 비교

보관 영상에서는 양쪽 집게 끝을 표시한다.
중심 오차, 양쪽 끝의 RMS 오차, 끝 간격을 함께 기록한다.
후보의 중심 오차가 줄어도 끝 간격과 고정 구조물 오차를 확인한다.

보정에 사용하지 않은 실물 표본의 재투영 좌표를 `rosy.omx-wrist-holdout/1` JSON에 기록한다.
그 파일을 `transfer-audit --wrist-evidence FILE`에 지정한다.
이 명령은 입력 좌표의 오차를 계산한다.
각 손목에서 CAD와 대응하는 고정점과 집게 끝을 같은 영상에서 잡는다.
영상 해시와 카메라 역할은 원본에서 별도로 확인한다.
관절 시각, 집게 개구, 배치와 장착 보정의 출처도 확인한다.
보관 영상에서 집게 끝만 비교한 기록은 후보 선별에 쓴다.
현장 적용은 고정점과 집게 끝이 모두 검증된 뒤에 판단한다.

## 판정 기준

| 항목 | 기준 | 넘으면 |
|---|---|---|
| 판 칸 크기 (top 카메라 확인) | 90×30 mm에서 3 mm 이내 | G-19: 카메라를 다시 잰다 |
| 쌍둥이 시야 차이 | top·side 3 px, 손목 5 px (D-947) | G-19·G-20·G-24 |
| 관절 추종 지연 | 실물과 시뮬의 관절별 지연 차이 | G-23 |
| 시뮬 단계 | 이전 바퀴보다 통과 수가 줄지 않음 | 줄어든 단계의 원인을 행으로 |
| 실물 시도 | 시뮬 판정과 실물 결과가 같음 | 다르면 Isaac 사례 추가(G-25) |
| 상수 후보 (6b) | 서보: 보류 에피소드 RMS가 기준 후보보다 낮고 어느 관절도 0.1° 넘게 나빠지지 않음. 마찰: 힘 차이 SNR 3 이상, 운동 방향, 두 적층 높이가 30 % 안에서 일치 | 후보로 올리지 않는다. 마찰은 사람의 기울인 판 시험으로 |

## 규칙

- 사람만 확인할 수 있는 것(줄자 거리, 감독 시험)은 보정 앱의 실측 요청으로 연다(`deploy/robot/omx/cell_requests.py`, D-951 덧붙임, 화면 D-1004). 요청은 후보마다 예측값을 적고, 사람의 답은 어느 후보를 지지하는지만 정한다.
- 잰 값은 이름 있는 선택지로 넣고 설계값을 덮어쓰지 않는다(D-947 2). 예: `temp_lanes=snapshot`, `cell_snapshot=PATH`.
- 물리 상수(서보 kp·kv·감쇠·마찰 손실, 컨테이너 질량·마찰)는 `learning/envs/isaac/cell_physics.yaml`의 후보다. 설계값은 `design`이고, 맞춘 값은 `omx_sysid.py promote`가 새 이름으로 덧붙인다(덮어쓰지 않음). 학습은 `omx_physics.py ranges`의 범위에서 뽑는다. MuJoCo 접촉은 후보 고르기에만 쓰고 접촉 수치는 Isaac 확인값만 인용한다(D-947 5).
- `omx_sysid.py task`는 기준 물리와 후보 물리의 적층 과제 및 파지 결과를 `fit.json`에 남긴다. 이 과제 증거가 없는 맞춤 결과는 승격할 수 없다.
- 차이는 싼 쪽부터 닫는다: 값으로 표현되면 M, 실물 재생이 필요하면 R, 감지·정지로만 다룰 수 있으면 D(D-480 1).
- 레지스트리 행의 상태는 그 근거(스냅샷·검증 기록)와 같은 커밋에서 바꾼다(D-480 7). 실물에서 나온 사례는 M으로 옮긴 뒤에도 지우지 않는다(D-480 6).
- 실물 동작은 모두 감독 시험이다(D-911). 시뮬에서 배운 정책은 D-793 관문 전까지 실물에서 돌리지 않는다(G-28).
- 시뮬 통과는 실물 근거가 아니다. 결과는 기하 근거로만 쓴다(D-947).

## 다음 바퀴에서 할 일 (2026-11-10)

첫 바퀴 결과는 [2026-11-09 검증 기록](../validation/omx-real-sim-loop-2026-11-09/result.md), 두 번째 바퀴(2026-11-10 위 카메라 재측량 및 다리 v7 + 판 v11 스냅샷 `20261110-1231.json`) 결과는 [2026-11-10 검증 기록](../validation/omx-real-sim-loop-2026-11-10/result.md)이다.

| 행 | 상태·할 일 | 누가 |
|---|---|---|
| G-17 | 다리 v7 + 판 v11 배치 스냅샷(`20261110-1231.json`, `temp_lanes=photo-20261110`, 단계 17.0°, 반지름 203.4 mm) 측정 및 1~4단계 검증 완료. 판을 옮기면 다시 잼 | 에이전트 |
| G-18 | 시드 0 층 엇갈림(d90eb37896) 착지 및 `20261110-1231.json`(`ship_pose=photo-20261110`, 선미 x .1780, 중심 y −.0010) 검증 완료. 접안대 재설계 뒤 다시 잼 | 에이전트 |
| G-19 | 2026-11-10 USB3 재연결 이동(−56 px, −17 px, 2.8°)을 다중 평면 61점 PnP(중앙값 0.74 px, hold-out 0.92 px)로 재측량해 `cell_model_inventory.yaml`·`omx_two_arm_sites.py` 반영 및 `top-camera-moved-20261110` 응답 완료 (쌍둥이 `top` 윤곽 변위 `2.8 px <= 3 px`) | 에이전트 |
| G-21 | `20261110-1231.json`에 양팔 받침 축 후보(`fk` vs `plate_centre`) 기록 및 `arm_bases=plate-centre`/`snapshot` 선택지 검증 완료(41/41 단계 및 MuJoCo `stack` 9/9 통과). 놓인 컨테이너 확인 전까지 `tmp-b-1` 보류 유지 | 에이전트, 사람 |
| G-23 | 26개 에피소드(보류 12개) 대조 완료: 에피소드 재생 RMS는 `servo-friction-20261109`가 보류 평균 `0.416°`(전체 `0.419°`, `design 0.452°`·`twin-kp-20261109 0.444°` 대비 최소)이나, 양팔 교사의 `1.5 s` 열린 루프 파지 궤적에서는 `registers-20261109` 계열(`j4/j5 kp=2.92/1.46, force=0.088 N·m`)이 정착 대기 없이 `~15 mm` 지연되어 `0/9`이고 `twin-kp-20261109`·`design`이 `stack` 9/9(`xy 0.1~0.6 mm`)를 통과함 | 에이전트 |
| G-24 | 팔별 손목 카메라 조 윤곽 맞춤(`wrist_camera=photo-20261110`: `arm_a` IoU `0.183 → 0.385`, 윤곽 변위 `26.0 → 12.8 px`; `arm_b` IoU `0.652`, 점수 `0.95`) 반영. D-947 `5 px` 달성을 위한 팔별 약 12자세 hand-eye는 감독 시험으로 남김 | 에이전트, 감독 시험 |
| G-29 | 2026-11-10 실물 프레임의 표면별 중앙값 RGB(바닥·작업대·벨트·하늘색 v11 판·본선) 및 조명(`diffuse`/`ambient`/`specular`) 맞춤 완료(`top` MAD `53.70 → 42.79`, `b_wrist` MAD `76.10 → 72.36`, `top` 윤곽 변위 `6.0 → 2.8 px`) | 에이전트 |
| G-30 | 새 카메라 자세에서 벨트(`end_x_m .2115, centre_y_m -.0226, width 81.8 mm`, `belt_pose=photo-20261110`) 재측정 및 시뮬 검증 완료. 요청 `belt-end-20261108-1928`은 선택적 줄자 확인용으로 열어 둠 | 사람(줄자), 에이전트 |
| G-20 | 알려진 자세 확인 | 사람(감독 시험) |
| G-27 | bar-1을 실물에서 꺼내 보기 | 사람(감독 시험) |
