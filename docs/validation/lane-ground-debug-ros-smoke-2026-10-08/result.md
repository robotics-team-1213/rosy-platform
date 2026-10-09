# keep 디버그 지면값 ROS 콜백 검증 — 2026-10-08

**판정: ROS 콜백 검증 통과.** 소스 SHA `18c7794851fd53d4a6b2bf6eaf6f80cc97d46c3f`의 `LineObserverNode._on_camera`를 WSL Ubuntu ROS 2 Jazzy에서 실행하고, 별도 ROS 구독자로 `line/keep_debug`를 받았다. `ROS_DOMAIN_ID=214`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`였다. [probe.py](probe.py)는 합성 320×240 BGR 카메라 프레임 한 장을 콜백에 직접 건네고, 로봇·카메라·주행 명령을 사용하지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=214 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  python3 docs/validation/lane-ground-debug-ros-smoke-2026-10-08/probe.py
```

수신한 payload는 카메라 stamp `100.0`, `ground=NOMINAL`, `strategy=left_only`를 담았다. `ground_projection`은 `height_m=0.06343`, `pitch_rad=0.139626`, `focal_px=281.6`, `principal_x=160.0`, `principal_y=120.0`, `max_range_m=0.6`, `camera_x_offset_m=0.03317`이었다. Probe가 모든 값을 같은 체크아웃의 `camera_nominal.yaml`과 비교했다. 콜백은 끝까지 실행됐으며 `line/keep_debug`를 발행했다. 원시 로그는 `X:\DevTemp\lane-debug-smoke-tracked.txt`(SHA-256 `2171576FDA945EB9E3015131C8069D1CB9C9AE1F5AA090EA01A4A647667ACB7A`)에 있다.

이 검증은 `37fbfe347`에서 고친 `ground` 인자 충돌이 **현재 소스의 실제 ROS 콜백**에서 재발하지 않고, 녹화에 필요한 숫자가 발행되는지를 확인한다. 이는 별도 ROS 그래프의 합성 프레임 한 장이다. 장치 서비스·MCAP 녹화·보정 승인·분기 주행·D-205 P3/P5 시뮬레이션 게이트·실물 수용의 근거가 아니다. `NOMINAL`은 승인된 카메라 보정을 뜻하지 않는다.
