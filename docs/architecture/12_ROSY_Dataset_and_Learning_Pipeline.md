# 12. ROSY Dataset & Learning Pipeline

**범위:** Teach→Record→Train 순환의 목표 모델이다. 현행 Fleet SQLite는 작업·이벤트·sighting 기록이며 영상 데이터셋이나 Episode 저장소가 아니다. recorder, dataset store, policy registry는 아직 운영 경로가 아니고 [D-71](../adr/D-71-concept-05-09-12-15-apt-v1.md)의 후속 단계다. 수집이 시작되면 source/device·촬영 시각·작업/명령 ID·보정/모델 revision·실제 결과를 함께 묶는 별도 계약과 보존/접근 정책을 먼저 정한다([D-290](../adr/D-290-rosy-platform-naming-and-site-intent-boundaries.md)).

## 1. Goal

Support a Physical AI loop:

```text
Teach
 -> Record
 -> Train
 -> Deploy
 -> Execute
 -> Evaluate
 -> Record
```

## 2. Data Sources

- OMX-L teleoperation
- OMX-F joint states
- Pinky pose
- camera frames
- gripper state
- task state
- success/failure
- operator actions

## 3. Episode Model

Example:

```text
episode_000124/
  metadata.json
  camera/
  joint_states/
  actions/
  robot_pose/
  gripper/
  result.json
```

## 4. Pipeline

```text
Teleoperation
 -> ROSY Dataset Recorder
 -> Dataset Store
 -> RTX5080 Training
 -> Policy Registry
 -> ROSY Deployment
 -> Runtime Evaluation
```

## 5. Versioning

Every dataset and policy should include:

- version
- source devices
- collection date
- task type
- model version
- calibration version
- validation result
