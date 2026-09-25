# 12. ROSY Dataset & Learning Pipeline

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
