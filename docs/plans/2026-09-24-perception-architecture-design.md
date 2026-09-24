# 카메라 인식 구조 설계: 학습 모델을 끼울 수 있는 차선·장면 인식

- 작성: 2026-09-24
- 상태: 사용자 검토 대기
- 증거 등급: 설계 문서. 이 문서 자체로는 어떤 합격도 주장하지 않는다.
- 결정: [D-199](../adr/D-199-camera-perception-contracts-and-backends.md)(Proposed)가 이 설계의 계약과 백엔드 구조를 기록한다. 폴더 자리는 [D-209](../adr/D-209-perception-folder-and-learned-backend.md)(Accepted)가 정한다.
- 실행 순서: [D-205](../adr/D-205-real-lane-mission-transition-order.md)(Proposed)가 P0–P6 단계, 게이트, 인계 절차를 정한다.
- 관련 문서: D-137(YOLO 보조 검출 계약), D-138(provider), D-143(차선 관측), D-162(장면 문맥), D-136/D-152(영상 대역·CORE는 영상 바이트를 다루지 않음), `2026-09-22-lane-network-junction-spike-design.md`, `2026-09-23-lane-network-parking-design.md`

## 1. 왜 다시 설계하나

### 1.1 지금 인식이 약하다

2026-09-23 Gazebo 순회 1회(route_ab)에서 CORE가 받은 인식 1576건을 등급별로 나누었다.

| 등급 | 뜻 | 비율 |
|---|---|---|
| BOTH | 좌우 선 모두 잡음 | 12% |
| ONE | 한쪽 선만 잡음 | 73% |
| MEMORY | 기억에 의존 | 16% |

오프라인에서 같은 경로를 재현해 원인을 찾았다(`scratchpad/percep/tour_diag.py`).

- **좌우를 뒤바꿔 붙잡는다.** 왼쪽 기억이 실제 오른쪽 선에 겹쳐 붙어 버리면, 진짜 왼쪽 선은 이후 다시 채택되지 않는다. 전체 프레임의 27%에서 라벨이 틀린 선에 붙어 있었다(`lane_bev.py:428-440`).
- **왼쪽 선을 혼자 새로 잡는 경로가 없다.** `_right_boundary`에 해당하는 왼쪽 버전이 없다.
- **오버레이가 기억 격자를 그린다.** 화면에 보이는 초록·파랑 선은 "이번 프레임에 본 선"이 아니라 기억이다. 그래서 오버레이만 봐서는 판단 근거를 알 수 없다.
- **장면을 해석하지 않는다.** 교차로 분기 신호는 계산만 하고 쓰이지 않는다. 코너, 횡단보도, 정지선은 추종기가 알지 못한다.
- **추종기에 로직이 엉켜 있다.** 선 조각 추출, 좌우 판단, 추종이 한 덩어리라 학습 모델을 끼울 자리가 없다.

### 1.2 시뮬레이션이 실물과 다르다

2026-09-19 수동 주행 영상(`data/teleop/learning/`, 7개, 약 12분, 4981프레임)으로 실물 카메라를 추정했다(`scratchpad/camcal/`).

| 항목 | 실물(추정) | 현재 Gazebo |
|---|---|---|
| 기울기 | 8.0° 아래 (±0.4°, 기계적 ±2°) | 25° |
| 좌우 화각 | 59.3° (fx 281.6 ±12 px) | 66° |
| 렌즈 높이 | 약 67 mm (64~69) | 60.2 mm |
| 해상도·비율 | 320x240 (4:3), 8 fps | 320x180, 5 Hz |
| 벽 | 흰 폼보드 + 파란 테이프 (회색값 212) | 청회색, 어두움 |
| 바닥 | 회색 카펫 (회색값 84~102, 질감 sd 13) | 균일한 어두운 바닥 |
| 차선 간격 | 약 195~205 mm(영상 추정). 실측 대기 | 185 mm (CAD) |

- 실물에서는 벽이 테이프만큼 밝거나 더 밝다(프레임의 67%). 밝기 문턱만 쓰는 지금 방식은 벽을 차선으로 오인한다.
- 사용자 결정(2026-09-24): 실물 카메라는 거의 수평이 맞다. 시뮬레이션을 실물에 맞춘다. 트랙 치수는 실물 매트를 자로 잰 값을 따른다.

### 1.3 학습 모델을 끼울 자리가 필요하다

- 사용자 요구: 지금은 규칙 기반으로 가되, 나중에 학습 모델(YOLO, SAM2 등)을 같은 자리에 끼울 수 있어야 한다.
- 현재 저장소에는 모델이 없다. D-137의 보조 검출 계약(`DetectionEvidence`, `ModelRegistry`, Hailo 대상)만 있다.

## 2. 목표와 비목표

### 목표

1. **고정 계약.** 인식 결과를 두 층의 고정 계약으로 내보낸다. 소비자(추종기, CORE, 오버레이, 채점)는 계약만 본다.
2. **교체 가능한 백엔드.** 규칙 기반, 학습 분할, 학습 검출이 같은 계약을 채운다. 둘 이상을 동시에 돌려 비교할 수 있다.
3. **공통 프레임 소스.** Gazebo 카메라, 실물 카메라, 녹화 영상 재생이 같은 인터페이스로 들어온다. 소스마다 카메라 프로필을 가진다.
4. **실물 영상 재생기.** `data/teleop/learning`을 넣으면 백엔드별 인식 결과와 오버레이 영상을 만든다.
5. **정답 생성과 채점, 학습 데이터 수집.** Gazebo 참값과 지도로 같은 계약의 정답을 자동으로 만들어 채점한다. 프레임과 라벨을 학습 데이터로 저장한다.
6. **실물에 맞춘 Gazebo.** 카메라, 벽, 바닥, 트랙 치수를 실물에 맞춘다.
7. **장면 요소 인식과 표시.** 좌우 경계(곡선·코너 포함)와 장면 요소(코너, 교차로 분기, 횡단보도, 정지선, 주차 마커)를 인식해 표시한다. 주행 반영은 단계적으로 한다(사용자 결정).

### 비목표

- 학습 모델 자체의 개발과 학습. 이 설계는 자리와 데이터만 만든다.
- CORE의 명령 권한 변경. CORE만 최종 `/cmd_vel`을 발행한다. control은 증거만 낸다.
- CORE가 영상 바이트나 OpenCV를 다루는 것. 금지(D-66, D-136).

## 3. 구조

```
[프레임 소스]                 [백엔드: 영상 좌표]                      [공통 층: 바닥 좌표]          [소비자]
 GazeboCamera ─┐          ┌─ RuleBackend (클래식 CV)        ─┐
 RobotCamera  ─┼─ Frame ──┼─ LearnedSegBackend (SAM2/YOLO-seg)─┼─ ImageEvidence ─> GroundProjector ─> PerceptionFrame ─┬─> 추종기 → line/observation → CORE
 VideoReplay  ─┘ +Camera  └─ LearnedDetBackend (YOLO)       ─┘   (perception/      + SceneTracker      (perception/frame) ├─> 오버레이·라이브 뷰
                 Profile                                          evidence)                                             ├─> 채점기
 GroundTruthLabeler (Gazebo 참값 + 지도 + 프로필) ───────────────────────────────> PerceptionFrame(backend=ground_truth) ─┘   └─> 데이터셋 저장
```

### 3.1 프레임 소스와 카메라 프로필

- `FrameSource`가 `Frame`을 넘긴다.
  - `Frame{image(BGR, 원래 방향으로 회전 완료), stamp, seq, source_id, profile_id}`
  - 구현은 두 가지다: `RosImageSource`(Gazebo·실물 공통, `camera/front`), `VideoFileSource`(mp4를 프레임 단위로, 재생 속도는 자유).
- `CameraProfile{id, width, height, fx, fy, cx, cy, dist[k1..], pitch_rad, roll_rad, height_m, x_offset_m, rotate_deg, revision}`
  - 실물 프로필 초안: `camcal/out/camera_profile.json`. 렌즈 높이와 앞뒤 위치는 실측으로 확정한다.
  - Gazebo 프로필은 로봇 모델(URDF)에서 계산한다. 로봇 모델에서 다시 계산한 값과 비교하는 가드 테스트를 둔다. `a19ba221`에서 같은 방식으로 0.034 → 0.0285 오류를 잡았다.
  - 프로필은 설정 파일에 두고 revision을 붙인다. 모르는 revision이면 인식을 끈다(D-162와 같은 fail-closed 방식).

### 3.2 계약 1층: ImageEvidence (`perception/evidence`)

모델이 자연스럽게 내는 영상 좌표 결과다. 모델 담당자는 이 층만 맞추면 된다. D-137의 `DetectionEvidence`를 넓힌 것이다.

```json
{
  "schema": "rosy.perception.evidence/1",
  "backend": "rule|learned_seg|learned_det",
  "model_revision": "rule-lane-v1 | yolo11n-seg-lane-2026xx",
  "profile_id": "pinky-front-v1",
  "observed_at": 12.34, "seq": 812, "input_width": 320, "input_height": 240, "inference_ms": 4.1,
  "masks": [{"class": "lane_line|stop_line|crosswalk|wall|floor", "encoding": "rle|polygon", "data": "...", "confidence": 0.9}],
  "polylines": [{"class": "lane_line", "points_px": [[u, v], ...], "confidence": 0.8}],
  "detections": [{"class": "crosswalk|stop_line|dock_tag|person|signal", "x": 0.1, "y": 0.5, "w": 0.2, "h": 0.1, "confidence": 0.7, "track_id": null, "attrs": {}}]
}
```

- 클래스는 닫힌 목록이다. 모르는 클래스나 모르는 `model_revision`은 버린다(`ModelRegistry`).
- 좌표는 정규화(0..1)하거나 입력 크기 기준 픽셀로 준다. 어느 쪽인지 명시한다.
- 오래된 증거(0.3 s 초과)는 무효다. `seq`가 건너뛰면 프레임을 잃은 것이다.

### 3.3 계약 2층: PerceptionFrame (`perception/frame`)

로봇 기준(base_footprint, x는 앞, y는 왼쪽, 단위 m) 바닥 좌표다. 모든 소비자는 이것만 본다.

```json
{
  "schema": "rosy.perception.frame/1",
  "backend": "rule|learned_seg|fused|ground_truth",
  "stamp": 12.34, "profile_id": "pinky-front-v1",
  "lane": {
    "left":  {"points": [[x, y], ...], "state": "fresh|memory|none", "confidence": 0.9},
    "right": {"points": [[x, y], ...], "state": "fresh|memory|none", "confidence": 0.8},
    "centre": {"points": [[x, y], ...], "basis": "both|left+width|right+width|memory|none", "confidence": 0.85},
    "width_m": 0.198
  },
  "elements": [
    {"type": "corner", "direction": "left|right", "distance_m": 0.22, "angle_deg": 90, "confidence": 0.7},
    {"type": "junction", "branches": [{"heading_deg": -35}, {"heading_deg": 20}], "distance_m": 0.15, "confidence": 0.6},
    {"type": "crosswalk", "distance_m": 0.31, "confidence": 0.8},
    {"type": "stop_line", "distance_m": 0.4, "confidence": 0.7},
    {"type": "dock_tag", "tag_id": 7, "x": 0.25, "y": 0.0, "yaw": 0.0, "confidence": 0.9}
  ],
  "floor_valid_to_m": 0.9,
  "hazards": ["glare", "motion_blur", "wall_close"]
}
```

- 기존 `line/observation`, `road/observation`, `dock/observation`은 이 계약에서 파생해 계속 발행한다. CORE 쪽 입력은 바뀌지 않는다. 형식 변경 없이 소스만 바뀐다.
- `line/observation`에 등급(`basis`)을 추가할지는 ADR에서 정한다. 지금은 신뢰도로만 추정할 수 있다.

### 3.4 공통 층: GroundProjector와 SceneTracker (control, ROS-free)

1. **GroundProjector.** 프로필로 영상 좌표를 바닥 좌표로 바꾼다. 수평선 위와 `floor_valid_to_m` 밖은 버린다. 실물에서는 벽이 이 단계에서 대부분 빠진다.
2. **SceneTracker.** 시간 방향으로 추적한다.
   - 좌우를 일관되게 붙인다. "왼쪽"은 로봇 기준 y > 0 쪽 선만 가능하다. 한 조각이 양쪽에 걸치면 나눈다. 좌우 모두 혼자 새로 잡는 경로를 둔다. 기억이 좌우 조건과 모순되면 다시 배정한다.
   - 경계별로 곡선을 맞춘다. 골격(skeleton)을 뽑아 polyline이나 원호로 맞추고 곡률을 구한다.
   - 장면 요소를 만든다.
     - 코너: 곡률과 끝점에서 방향·거리·각도를 구한다.
     - 교차로 분기: 기존 OPENS/BRANCH를 확장해 분기 방향과 거리를 구한다.
     - 횡단보도·정지선: 백엔드 검출을 바닥에 투영한다.
     - 주차 마커: `dock_tag`를 흡수한다.
   - 기억과 등급 사다리(BOTH/ONE/MEMORY/STOP)는 여기 하나에만 둔다.
3. **지도 사전정보(선택).** `lane_graph`와 위치 추정은 라벨을 붙이는 보조로만 쓴다. 증거는 항상 카메라다. 위치 추정이 틀리면 지도를 쓰지 않고 카메라만으로 동작한다.

### 3.5 백엔드

- **RuleBackend (지금).** 실물 방해 요소를 처음부터 다룬다.
  - 바닥 영역만 본다. 수평선 아래이고 벽 밑선 아래인 곳이다. 벽 밑선은 밝은 영역의 아래쪽 경계로 찾는다.
  - 밝기와 폭으로 선을 거른다. 바닥에서 폭이 15~40 mm인 밝은 띠만 차선으로 본다. 벽처럼 넓은 밝은 영역은 버린다.
  - 반사광 억제. 포화된 픽셀 덩어리 중 선 모양이 아닌 것은 버린다.
  - 흔들린 프레임(라플라시안 분산이 낮은 것)은 신뢰도를 낮춘다.
  - 결과는 ImageEvidence(polylines, masks, detections)로 낸다.
- **LearnedSegBackend / LearnedDetBackend (나중).**
  - 별도 노드나 컨테이너에서 돈다. 기존 설계의 `rosy-vision`과 Hailo 계획을 따른다.
  - ImageEvidence를 발행한다. `model_revision`은 `ModelRegistry`에 등록한 것만 받는다.
  - SAM2처럼 무거운 모델은 기기에서 돌리지 않는다. 오프라인에서 라벨을 만드는 도구로 쓰고, 학습된 가벼운 분할 모델(YOLO-seg 등)이 기기에서 돈다. 이 구분은 모델 담당자와 정한다.
- **Fused (선택).** 여러 백엔드의 ImageEvidence를 SceneTracker가 합친다. 1차에서는 하나만 고른다(설정 `perception.backend`).

### 3.6 정답 생성, 채점, 데이터셋

- **GroundTruthLabeler (Gazebo).**
  - 입력: 참값 위치(`/odom`, OdometryPublisher), 도색 지도(실측 반영 STL/lane_graph), 프로필.
  - 출력 1: 같은 PerceptionFrame(`backend=ground_truth`). 좌우 경계 곡선, 코너 거리, 교차로, 횡단보도, 마커를 담는다.
  - 출력 2: 영상 좌표 라벨. 도색을 카메라로 투영한 클래스별 마스크와 박스다.
- **채점기.** 백엔드 결과와 정답을 프레임마다 비교한다.
  - 경계 횡오차(mm), 좌우 뒤바뀜 비율
  - 등급별 비율과 이론상 상한(보이는 비율) 대비 달성률
  - 요소별 재현율과 정밀도, 거리 오차
  - 결과는 `perception_score.json`에 쓴다.
- **데이터셋 저장.**
  - 위치: `data/perception/<run>/`
  - 내용: `frames/000123.png`, `labels/000123.json`(두 층 모두), `meta.json`(프로필, 세계 revision, 백엔드 revision)
  - 형식은 YOLO-seg와 COCO로 내보낼 수 있게 변환기를 둔다.
  - 용량 정책은 D-186 캡처 폴더 규칙을 따르고, 큰 데이터는 저장소 밖에 둔다.
- **실물 영상 라벨.** 사람이 라벨을 붙이는 경로를 둔다. 형식은 같다. 1차에서는 도구만 준비하고 정량 채점은 하지 않는다. 실물 영상은 정답이 없으므로 다음 자기 일관성 지표만 본다.
  - 차선 폭 일정성
  - 좌우 평행성
  - 좌우 뒤바뀜 표시
  - 프레임 간 흔들림

### 3.7 녹화 영상 재생기

- 명령: `perception_replay.py --video <mp4...> --profile pinky-front-v1 --backend rule [--backend learned_seg] --out <dir>`
- ROS 없이 돈다. Windows 호스트에서도 돈다.
- 출력:
  - 프레임별 `perception.jsonl`
  - 오버레이 mp4: 원본, 영상 좌표 증거, 바닥 좌표 PerceptionFrame, 장면 요소 라벨, 판단 근거를 네 칸으로 보여준다.
  - 자기 일관성 요약
- 백엔드를 둘 이상 주면 나란히 비교한다.
- 오버레이는 지금 결점을 고친다. 로봇 몸체는 따로 표시하고, 기억과 이번 프레임에 본 선을 구분해 그린다.

### 3.8 실물에 맞춘 Gazebo (세계 revision을 올린다)

- **카메라.** 기울기, 높이, 화각, 320x240, 8 Hz를 프로필에서 생성한다. 필요하면 k1 왜곡을 넣는다.
- **벽.** 흰색 무광(diffuse 0.8~0.85)에 파란 테이프 조각을 붙인다.
- **바닥.** 회색 카펫(diffuse 0.35~0.4)에 잔무늬 질감(sd 약 13)을 준다. 벽 밑에 반사 띠는 선택이다.
- **도색.** 흰 무광(diffuse 0.75~0.8)이다.
- **치수.** 실측값으로 STL, lane_graph, lane_rules를 다시 만든다. CAD 원본은 보존한다.
- **방해 요소(선택, 2차).** 벽 너머 사람·의자 모형.
- **재검증.** 이 세계에서 교차로, 순회, 주차 합격을 다시 받는다. 이전 합격(25° 세계)은 이 세계에서는 무효로 표시한다.

## 4. 단계와 합격 기준

| 단계 | 내용 | 합격 기준 |
|---|---|---|
| P0 | 실측값 반영: 프로필 확정, 트랙 치수 | 사용자 실측값 반영. 영상 BEV에서 차선 간격이 실측 ±5 mm 이내 |
| P1 | 계약과 ADR: ImageEvidence, PerceptionFrame, ModelRegistry 확장, 소스·프로필 | 스키마 테스트, 모르는 revision·클래스 거부 테스트, ADR 초안 |
| P2 | 녹화 영상 재생기 + 현재 로직을 RuleBackend로 감싼 기준선 | teleop 7개로 오버레이 영상 생성. 기준선 자기 일관성 수치 기록 |
| P3 | 새 RuleBackend + SceneTracker(좌우 일관, 곡선, 장면 요소) | teleop 영상에서 뒤바뀜 표시가 기준선보다 줄어듦. 벽 오인 0에 가깝게(수치는 P2 기준선을 보고 정함) |
| P4 | 실물에 맞춘 Gazebo + 정답 생성기 + 채점 + 데이터셋 저장 | 채점 가능한 요소 정의. 이론상 상한 대비 BOTH 달성률 ≥ 80%, 경계 횡오차 중앙값 ≤ 10 mm(수치는 P4 첫 측정 뒤 사용자와 확정) |
| P5 | 추종기를 PerceptionFrame으로 전환, 새 세계에서 교차로·순회·주차 재검증 | 기존 합격 기준(교차로 36/36, 순회 3/3, 주차 20 mm/5°)을 새 세계에서 다시 통과 |
| P6 | 장면 요소를 주행에 단계적으로 반영 | 요소별로 별도 승인. 예: 코너 감속, 횡단보도 서행 |
| (이후) | 학습 백엔드 끼우기 | 모델 담당자가 ImageEvidence를 발행하면 재생기·채점기로 규칙 기반과 비교 |

## 5. 사용자가 정할 것과 남은 위험

- **실측(대기).** 차선 간격, 선 폭, 횡단보도 규격, 원형 지름, 렌즈 높이와 앞뒤 위치, 매트 전체 크기, 벽 높이.
- **주차 마커(재결정 필요).** 경사 마커는 "25° 카메라는 6 cm 위를 못 본다"는 전제에서 골랐다. 실물 카메라(8°)는 벽 높이의 세로 태그도 잘 본다. 실측 뒤 선택지를 다시 제시한다.
- **학습 모델의 실행 위치.** Pi 5 CPU만 쓸지, Hailo를 붙일지 정해야 한다. 지금 계획은 Hailo가 있어야 한다는 전제다(D-137).
- **위험.**
  - 영상 추정의 절대 척도는 ±5% 수준이다. 실측으로 줄인다.
  - 주점(cx, cy)은 추정할 수 없어 영상 중앙으로 가정했다.
  - 8 fps와 흔들림 때문에 코너 거리 추정의 시간 해상도가 낮다.
  - 실물 조명 변화는 녹화 영상 12분으로만 표본을 얻었다.

## 6. 기존 코드와의 관계

- **옮긴다.** `lane_bev.py`, `lane_boundaries.py`의 선 추출과 기억 로직은 RuleBackend와 SceneTracker로 옮긴다. 옮긴 뒤에는 추종기(`route_camera.py`, `route_hybrid.py`)에 인식 로직이 남지 않는다.
- **흡수한다.** `road.py`(정지선·횡단보도)와 `dock_tag.py`(마커)는 RuleBackend의 검출기로 흡수한다. 기존 발행 토픽은 호환을 위해 유지한다.
- **다시 쓴다.** 오프라인 렌더러 `lane_sim.py`와 테스트는 프로필 기반으로 바꾼다. 25° 전용 상수(`CAM_X`, `CAM_TILT` 등)는 프로필에서 읽는다.
