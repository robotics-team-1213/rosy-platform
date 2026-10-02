## D-423 카메라 물체는 먼저 거리를 갖고(LiDAR 우선, 바닥 평면 예비), 종류는 작은 검출 모델이 나중에 붙이며, 학습 모델은 작업별 슬롯으로 계속 갈아 끼운다

**Status:** Proposed (2026-10-02, 사용자 승인 방향 2026-10-02 "물체가 무엇이고 얼마나 떨어져 있는지 보고 싶다, 학습한 모델(.pt 등)을 계속 적용·교체할 길을 만들어 달라"). 1단계(거리)는 저장소 코드와 시험만 들인다. 장치 기본값은 바꾸지 않는다(아래 4). 2단계(검출 모델)와 3단계(모델 교체 일반화)는 결정만 하고 구현은 뒤따른다. 학습 출력의 주행 사용은 이 ADR의 범위가 아니다(D-205, D-356 의 별도 문).

## 배경

- **화면은 "OBJ 1 UNKNOWN unranged" 만 보여 준다.** 카메라 관측(`camera/observation`)의 영역은 이미지 전경 덩어리이고(`camera_regions.foreground_regions`), 거리 `m` 은 측정한 핀홀 보정이 있을 때만 붙는다. 실기 `camera.yaml` 의 보정 여섯 값은 일부러 0 이라(측정 전에는 거리를 지어내지 않는다) 실기 영역은 늘 unranged 다. 종류는 어둡다/아니다 두 가지뿐이다.
- **기하는 이미 있다.** D-397 이 URDF 를 NOMINAL 로 정했다: 카메라 `front_camera_link` 높이 0.06343 m, 기울기 8°, 앞 0.03317 m(`camera_nominal.yaml`, `geometry.yaml`), LiDAR 앞 방향 스캔 180°, 위치 x −0.017 m, 높이 0.125 m. 로봇별 `camera_profile`·`lidar_mount` 승인 기록(D-47 부록 보정 저장소)이 이를 다듬는다. 이 경로는 `line_observer_node`·`loc_assist_node` 의 NOMINAL 바닥 평면(D-364 §3)이 이미 쓴다. 카메라 검출 노드만 이 길을 쓰지 않았다.
- **NOMINAL 기울기만으로는 바닥 거리가 길게 나온다.** 8kcn 실측 기울기는 11.2–11.8° 다(2026-10-01). URDF 8° 로 계산하면 0.4 m 앞 물체의 접지점을 약 0.66 m 로 읽는다. 승인된 `camera_profile` 기록이 없으면 바닥 거리는 근사일 뿐이다. LiDAR 는 기울기와 무관하게 거리를 재지만 스캔 평면이 바닥 위 0.125 m 라 그보다 낮은 상자·페인트는 못 본다. 둘은 서로의 빈 곳을 메운다.
- **학습 모델은 차선 하나뿐이다.** D-356/D-373 의 모델 길(`learned/manifest.py` `TASKS = ("lane_seg",)`, `ModelSlot` 이 2 초마다 포인터를 읽어 재시작 없이 교체, `deliver.py`·`intake.py`·`watch.py`·`rosy_ml.py`)은 `/var/lib/rosy/models/shadow` 한 슬롯을 차선 분할에 쓴다. 물체 검출을 붙이려면 작업별 슬롯이 필요하다. 그리고 `.pt` 는 로봇에 올리지 않는다(PyTorch 는 Pi 이미지에 없다).

## 결정

### 1. 영역 거리 — ML 없이, LiDAR 우선, 바닥 평면 예비 (지금 구현)

1. **바닥 평면은 NOMINAL 프로필에서 만든다.** `camera_detect_node` 에 `camera_ground_mode: nominal` 을 더한다. `nominal_camera_profile_path`(로봇 패키지의 `camera_nominal.yaml`, URDF NOMINAL)를 읽고, 그 로봇의 승인된 `camera_profile` 기록이 이기며(`calibrated_values.calibrated` → `calibration_store.resolve`), 운영자 덮어쓰기(`camera_pitch_rad_override`·`camera_height_m_override`, NaN 이면 없음, `line_observer_node` 와 같음)가 둘을 이긴다. LiDAR 앞 방향도 `lidar_yaw_offset_override` 가 승인 `lidar_mount` 기록을 이긴다. D-364 §3 처럼 두 번 켜야 한다: 모드 `nominal` 과 `allow_nominal_ground: true`. 하나라도 없으면 평면은 없고 영역은 unranged 다. 기존 `pinhole`(측정 여섯 값)·`homography` 모드는 그대로다.
2. **바닥 거리는 영역의 아랫변에서 잰다**(기존 `GroundPlane.region_distance`). 수평선 위·신뢰 범위 밖은 모른다(None).
3. **LiDAR 를 영역의 방위 폭에 붙인다.** 영역 네 꼭짓점의 화소를 같은 평면의 초점·주점·기울기로 로봇 앞 방향 기준 방위로 바꾼다(기울기를 넣은 정확한 식). 스캔의 각 빔은 `lidar_mount` 앞 방향(URDF 180°, 승인 기록이 다듬음)으로 로봇 방위를 얻고, LiDAR 위치(`geometry.yaml` lidar.x_m)에서 카메라 위치(x_offset_m)로 옮겨 카메라 기준 방위와 앞 거리로 바꾼다. 방위 폭 안 빔 중 가장 가까운 앞 거리가 그 영역의 LiDAR 거리다. 카메라 프레임과 스캔 시각 차가 `region_lidar_max_age_s` 보다 크면 쓰지 않는다.
4. **어느 거리를 낼지.** LiDAR 거리 L, 바닥 거리 G(신뢰 범위 제한 없는 값 G\* 도 함께).
   - L 이 있고 G\* 가 없으면(영역 전체가 수평선 위 — 바닥에 닿지 않은 물체) L.
   - L ≤ G\* + 허용오차 면 L. 같은 방위에서 접지점보다 가까운 반사는 그 물체이거나(기울기 오차로 G 가 길게 나온 경우) 더 가까운 물체다. 가까운 쪽이 맞다.
   - L 이 그보다 멀면 물체가 스캔 평면보다 낮다(상자·페인트). 그때는 G(신뢰 범위 안일 때만).
   - 허용오차는 `region_lidar_tolerance_m` + `region_lidar_tolerance_ratio`×G\* 이고 노드 파라미터다.
5. **증거 스키마는 뒤로 호환된다.** 영역에 `s` 키를 더한다: `'L'` LiDAR, `'G'` 바닥 평면. `m` 이 있을 때만 붙고, `m` 이 없으면 여전히 unranged 다. `s` 가 없는 예전 관측은 출처 미표기로 읽는다. 상한 48 영역 최악 크기는 3175 B 에서 약 3.6 KB 로 4 KB 아래에 남는다. 관측 문서에 `ground_source`(`PINHOLE`/`HOMOGRAPHY`/`NOMINAL`)를 붙여 어떤 기하로 쟀는지 남긴다.
6. **화면은 "OBJ 1 UNKNOWN 0.42m L" 처럼 보인다.** `follow_preview` 가 `s` 를 거리 뒤에 붙인다. 종류는 2단계 전까지 UNKNOWN/DARK 그대로다.
7. **기하는 노드 시작 때 한 번 읽는다.** 프로필 파일·승인 기록·덮어쓰기·LiDAR 앞 방향은 `camera_detect_node` 가 시작할 때 읽는다. 새 `camera_profile`·`lidar_mount` 기록을 승인하면 노드를 다시 시작해야 반영된다. `region_lidar_range` 는 NOMINAL 평면이 만들어졌을 때만 `scan` 을 구독하고, 아니면 경고만 남긴다.
8. **영역 거리는 자문 증거다.** 지금 `m` 을 읽는 판단 코드는 없다(`obstacle_risk` 는 `blocked` 만 본다). 이 거리를 정지·감속에 쓰려면 별도 ADR 과 시험이 필요하다(D-137: LiDAR/IR 가 결정한다).

### 2. 물체 검출 모델 — 작업 `object_det` (결정, 구현은 뒤)

1. **모델.** Pi 5 CPU 에서 도는 작은 int8 ONNX 검출기(YOLO-nano 급), 입력 320×240, 추론 2–3 Hz 상한(D-185 CPU 예산 안). 카메라 프레임은 센서 QoS(BEST_EFFORT)로 받는다(D-408 의 교훈).
2. **클래스(사용자 선택).** `robot`(다른 Pinky), `obstacle_box`, `cone`, `traffic_light`, `sign`, `person_feet`. 매니페스트가 클래스 목록을 고정하고, 목록이 바뀌면 새 계약 판이다.
3. **출력 계약.** `vision/detections` 에 기존 `core_common/protocol/detections.py` 의 `DetectionEvidence` 로 낸다(D-199 의 고정 계약 위에 백엔드만 교체). 각 검출은 1단계와 같은 방식으로 LiDAR/바닥 거리와 출처를 얻는다. 검출과 1단계 영역은 상자 겹침으로 짝지어 화면에서 "OBJ 1 cone 0.42m L" 이 된다. 짝짓기는 표시용일 뿐이다: 검출의 거리는 검출 상자 자체로 잰다(영역의 거리를 빌리지 않는다). 한 검출이 여러 영역과 겹치면 가장 많이 겹친 하나와만 짝짓고, 겹침이 기준(IoU) 아래면 짝짓지 않아 영역은 UNKNOWN 으로, 검출은 따로 표시한다. 기준값은 2단계 시험에서 정한다.
4. **자문 전용(D-137).** LiDAR/IR 정지 판단이 검출보다 위다. 검출은 정지 사유를 만들지 못하고, 주행 사용은 D-205/D-356 의 문을 따로 통과해야 한다.
5. **학습 데이터.** D-411 Pilot 녹화(로봇 녹화 제어), D-379 카탈로그와 자동 라벨에 LiDAR 군집이 카메라에 투영된 자동 상자(1단계의 방위 변환을 재사용)를 더하고, 사람이 확인·수정한 라벨이 이긴다. 학습은 PC/Colab 에서만 한다(D-356).

### 3. 모델 교체 길의 일반화 (결정, 구현은 뒤)

1. **작업별 슬롯.** `/var/lib/rosy/models/<task>/{shadow,active,previous}` 포인터. 기존 `/var/lib/rosy/models/shadow` 는 `lane_seg` 의 shadow 로 읽고 한 판 동안 둘 다 받는다. 매니페스트 `TASKS` 에 `object_det` 를 더한다.
2. **도구.** `rosy_ml deliver --task <task>`(shadow 로만 보냄), `rosy_ml promote --task`(shadow→active, 이전 active→previous), `rosy_ml rollback --task`(previous→active). 모든 포인터 변경은 지금처럼 로봇에서 root 로 `flock` 아래 하고 `history.jsonl` 에 남으며 hold 규칙을 따른다.
3. **`.pt` 는 PC 에서만 ONNX 로 바꾼다.** TorchScript, state_dict + 저장소의 모델 클래스 등록부, ultralytics export 세 길을 받는다. 변환 뒤 같은 입력으로 원본과 ONNX 출력을 비교하는 동등성 검사를 통과해야 intake 가 받는다(D-408 의 3.6e-6 비교와 같은 방식). int8 양자화는 보정 이미지로 하고 양자화 전후 지표를 매니페스트에 남긴다.
4. **매니페스트 서명.** 릴리스 서명 기반(`tools/release/sign_image_release.py` 의 키·검증)을 재사용해 매니페스트에 서명하고, 로봇의 `ModelSlot` 은 서명이 맞지 않는 번들을 거부한다.
5. **재시작 없는 교체.** `ModelSlot` 이 작업별로 포인터를 2 초마다 읽고, 실패한 교체는 이전 모델을 유지한다(지금 동작).
6. **Pilot "모델" 패널.** 작업별 active/shadow 판, 마지막 교체·실패 사유, 선택적 shadow 겹쳐 보기(검출 상자 점선). 패널은 보기와 promote/rollback 요청만 하고, 요청은 CORE 관리자 API 를 거친다.
7. **주행 사용은 별도 문.** 어떤 학습 출력도 D-205/D-356 의 문을 따로 통과하기 전에는 주행 명령에 들어가지 않는다.

### 4. 장치 기본값

`camera.yaml` 의 실기 기본은 `camera_ground_mode: pinhole` + 0 여섯 값 그대로다. 1단계를 로봇에서 보려면 사용자 승인 뒤 그 로봇의 설정에 다음을 넣는다: `camera_ground_mode: nominal`, `allow_nominal_ground: true`, `nominal_camera_profile_path: /opt/rosy/current/install/share/pinky_pro/config/camera_nominal.yaml`(Pinky 페이로드의 설치 위치, `pinky_pro` 의 `install(DIRECTORY config ...)`), `region_lidar_range: true`. 그리고 정확한 바닥 거리를 원하면 그 로봇의 `camera_profile` 기록을 운영자가 승인한다(8kcn 기울기 ≈ 11.2°).

## 결과

- 영역이 "얼마나 떨어져 있는지" 를 보이고, 어느 센서가 잰 값인지 화면과 관측에 남는다.
- LiDAR 가 보는 물체는 카메라 기울기 오차와 무관한 거리를 얻고, 낮은 물체는 바닥 평면이 메운다.
- 검출 모델과 차선 모델이 같은 교체 길(작업별 슬롯·서명·동등성 검사·되돌리기)을 쓴다.
- 비용: `camera_detect_node` 가 켜졌을 때 `scan` 을 하나 더 구독한다(최신 메시지만 보관). 프레임마다 빔 변환은 numpy 로 720 빔이다.

## 검증

- 호스트: 방위 변환(가운데·좌우 대칭·기울기), 스캔 → 카메라 기준 변환(앞 방향 180°, 위치 차), 거리 선택 규칙(수평선 위, 일치, LiDAR 가 더 먼 경우, 신선하지 않은 스캔), NOMINAL 평면의 두 번 켜기와 승인 기록 우선, 증거 `s` 키의 뒤 호환, 화면 글자 "0.42m L".
- Gazebo: 상자와 다른 Pinky 를 앞에 두고 `m`/`s` 를 실제 거리와 비교한다. 지금 Gazebo 런치는 `camera_detect_node` 를 띄우지 않는다(카메라는 `rendered_camera_adapter`). 시뮬에서 이 노드를 띄우는 런치만 `accept_simulation_scans: true` 를 넣는다(기본 false; 시뮬 스캔은 `is_robot_scan` 이 버리고, 스캔이 와도 모두 버려지면 노드가 한 번 경고한다).
- 실기: 사용자 승인 뒤 4 의 설정으로 줄자 거리와 비교한다(승인 기록 전후).

## 잇는 결정

D-137(YOLO 자문역, LiDAR/IR 결정), D-199(인식 고정 계약과 교체 백엔드), D-205(실물 차선 전환 순서·학습 출력의 문), D-209(인식·학습 백엔드 자리), D-356/D-373(학습 루프, 모델 전달·섀도), D-379(학습 데이터·자동 라벨), D-384(도로 상태 추정), D-397(URDF NOMINAL, 보정이 다듬음), D-408(학습 페인트 입력, 센서 QoS), D-411(Pilot 로봇 녹화).
