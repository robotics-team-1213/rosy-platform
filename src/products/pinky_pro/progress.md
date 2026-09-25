---
module: pinky_pro
logical_modules: [M06]
owner: 로봇 통합
last_verified: { commit: "uncommitted", date: 2026-09-24 }
gates:
  SOURCE:
    state: GO
    evidence: "profile.yaml·capabilities.yaml가 core/config에서 이 패키지로 옮겨졌고, 모델명·속도 상한·HWA-003 일치 시험 통과 (2026-09-24)"
    cmd: "python -m pytest src/products/pinky_pro/test -q"
  LOCAL:
    state: GO
    evidence: "core 시험이 robot_config_dir('pinky_pro')의 소스 트리 폴백으로 이 패키지 파일을 읽고 통과 (2026-09-24 Windows host)"
    cmd: "python -m pytest src/runtime/core/test src/contracts/core_common/test -q"
  ROS-SIM:
    state: GO
    evidence: "WSL Ubuntu Jazzy 새 작업공간 /root/rosy_ws_d196: colcon build --symlink-install --packages-up-to core pinky_pro 8 packages finished(실패 0); ros2 pkg prefix pinky_pro → share/pinky_pro/config에 capabilities.yaml·profile.yaml; robot_config_dir('pinky_pro') = install/pinky_pro/share/pinky_pro/config; 오버레이 없이 ros2 run core core 부팅 'core up: robot_id=rosy_01 model=Pinky Pro'·api server 8080, SIGINT 정상 종료; 미설치 모델은 ConfigError(--packages-up-to core <name> 안내) (2026-09-24)"
    cmd: "wsl -d Ubuntu -e bash -c 'cd /root/rosy_ws_d196 && source /opt/ros/jazzy/setup.bash && colcon build --symlink-install --packages-up-to core pinky_pro && source install/setup.bash && ls $(ros2 pkg prefix pinky_pro)/share/pinky_pro/config && timeout -s INT 20 ros2 run core core'"
  ARTIFACT:
    state: HOLD
    blocker: "required-ros-packages.txt에 pinky_pro를 올린 뒤의 이미지 빌드와 package inventory(ros2 pkg prefix pinky_pro) 증거 없음"
  DEVICE:
    state: HOLD
    blocker: "새 이미지에서 CORE_READY와 GET /system/capabilities readback 증거 없음"
  FIELD:
    state: PARKED
adrs: [D-196, D-11]
plans:
  - docs/plans/2026-09-24-multi-robot-structure.md
---
## 지금 상태

- Pinky Pro 로봇 패키지다. 코드 없이 HWA-001 프로필(`config/profile.yaml`)과 CAP-001 capabilities(`config/capabilities.yaml`)만 담는다(D-196).
- CORE는 `robot.model`(기본 `pinky_pro`, `ROSY_ROBOT`)로 이 패키지의 `share/pinky_pro/config/`를 찾는다. 소스 트리에서는 `src/products/pinky_pro/config/`로 폴백한다.
- 장치가 실제로 광고하는 모드별 파일(`deploy/robot/config/*.{core,motor,hardware}.yaml`)은 여전히 deploy 소유이고 `/etc/rosy/*.yaml` 절대 경로로 우선한다.

## 다음 gate

1. 이미지 빌드와 inventory에서 `pinky_pro` 확인(ARTIFACT).
2. 장치 CORE_READY와 GET /system/capabilities readback(DEVICE).

## 현재 유효한 금지사항

- `profile.yaml`과 `capabilities.yaml`을 따로 바꾸지 않는다(HWA-003).
- 이 패키지에 코드를 넣지 않는다. core는 이 패키지를 선언 의존하지 않는다.
