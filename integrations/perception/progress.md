---
module: perception_runtime
owner: CONTROL
last_verified: { commit: uncommitted, date: 2026-11-03 }
gates:
  SOURCE:
    state: GO
    evidence: "Split out of control with byte-identical module bodies (imports only); architecture guards and the moved pure tests pass"
    cmd: "python tools/remote/remote_pytest.py integrations/perception/test"
  LOCAL:
    state: GO
    evidence: "integrations/perception/test, middleware/perception/test and test/learning on the remote test PCs"
    cmd: "python tools/remote/remote_pytest.py integrations/perception/test middleware/perception/test test/learning"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-356, D-373, D-427, D-630]
plans: []
---
## 지금 상태

라이브러리 패키지다. 로봇 런타임 관문(ROS-SIM~FIELD)은 이를 쓰는 `control`이 진다. 로봇 이미지의 colcon 설치는 Pinky Dockerfile `--packages-select`와 `required-ros-packages.txt`에 등록했지만, 실제 이미지 빌드와 실물 기동은 아직 확인하지 않았다.
