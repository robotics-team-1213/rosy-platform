# 기존 모델 기반 Isaac 카메라 차선 강화학습 실행 계획

**Goal:** 기존 인식 모델·keep 조향·CORE 차선 추종으로 native 맵 주행을 확인하고 카메라 관측 yaw gain 정책을 별도로 학습한다.

**Architecture:** 실제 전방 Camera → 고정 LaneSegModel → 기존 learned paint/drivable keep → LineFollowManager → 기존 simulation owner/CORE cmd_vel_cycle. 실측 맵 진행률은 독립 평가이며 이미지의 차선 관측으로 위장하지 않는다. D-650의 한 대 진단이며 기존 두 대 Fleet 목표는 이 단계 뒤 진행한다.

**Tech Stack:** native Isaac SDK 5.1, 기존 ONNX CPU runtime, ROS-free CORE/Perception, 표 형태 Q-learning.

## 1. 모델·관측 계약

- 기존 immutable revision/manifest/file hash, crop·class 역할·실제 모델 파일을 확인한다. rejected 모델을 자동 선택하지 않는다. intake HOLD 후보는 진단용이라고 기록한다.
- 수정: `tools/sim/isaac/camera_lane.py`, `run_map_rl.py`, `map_task.py`와 `learning/envs/isaac/test/test_camera_lane.py`, 기존 SDK entrypoint test.
- 모델 입력은 실제 전방 native pixels다. 고정 모델의 출력과 기존 drivable keep/manager를 사용하며 단순 밝기/정답 경로를 성공 경로로 fallback하지 않는다.
- 새 Q 정책의 error/confidence schema와 모델 revision/SHA를 저장해 기존 경로 Q 표와 혼용을 거절한다.

## 2. 원격 RED/GREEN

- camera stale/역행/추론 실패, quality invalid, manager authority HOLD와 CORE stop을 시험한다.
- yaw gain을 manager tick 이전에 적용해 원래 gate가 검사한 의도와 최종 twist가 일치하는지 검증한다.
- own 파일만 커밋한 뒤 `python tools/remote/remote_pytest.py --log-dir <X-session>/logs/red -- learning/envs/isaac/test/test_camera_lane.py`로 RED를 확인한다. 구현 후 같은 시험과 관련 CORE/Perception 회귀를 GREEN/known_failures로 비교한다. 노트북 pytest는 실행하지 않는다.

## 3. Native 카메라 baseline·학습

- 자원/다른 GPU job·SDK 환경·source hash 확인 후 고정 모델과 카메라의 intrinsics/extrinsics를 기록한다. 카메라 위치는 prepared URDF의 front lens 기준이며 overhead recording camera와 구분한다.
- 짧은 baseline으로 실제 차선 인식·조향·몸 정지를 확인한다. 실패 원인은 image/model/선 선택/CORE gate/물리 응답으로 분리한다. 실패한 baseline을 Q 업데이트나 완주로 보고하지 않는다.
- baseline이 유효하면 같은 camera 관측으로 bounded curriculum을 학습하고 고정 정책의 독립 시드·시작 방향·순서별 완주·물리 stop을 평가한다. 명령과 카메라의 wall/sim 시각을 모두 기록한다.
- 기존 policy/영상은 보존한다. 새 native 영상은 완주·정지·전체 decode/hash 확인 뒤 요청한 private media에 보관한다.

## 4. 검토·통합·후속

- 독립 안전 소스 검토, main 통합 후 원격 영향 시험/NEW 0, lint와 사용자 승인된 착지·push/CI를 확인한다.
- 다음 Fleet 단계는 기존 서버·authority·crosswalk를 재사용하고 두 대 독립 identity/clock을 검증한다. 이번 한 대 camera 결과로 신호 준수/두 대/실물 gate를 올리지 않는다.
