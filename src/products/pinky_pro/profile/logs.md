# pinky_pro logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-24 · uncommitted · feat(robots): pinky_pro robot package carries the profile CORE loads (D-196)

- 변경: `src/core/core/config/profile.pinky_pro.yaml`와 `capabilities.yaml`을 이 패키지의 `config/profile.yaml`·`config/capabilities.yaml`로 옮겼다. CORE는 `robot.model`(기본 `pinky_pro`, `ROSY_ROBOT`)의 share에서 읽고, 소스 트리에서는 `src/robots/pinky_pro/config`로 폴백한다. 이미지 필수 패키지 목록에 올렸다
- 증거: `python -m pytest src/robots/pinky_pro/test -q` 2 passed; core 시험 전체가 이 파일을 읽고 통과 (2026-09-24 Windows host)
- gate 변화: 신규 기록. SOURCE GO, LOCAL GO, ROS-SIM/ARTIFACT/DEVICE HOLD, FIELD PARKED
- 결정: D-196 Proposed
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(core,robots): clear error for a missing robot package; ship robots in docker/ci (D-196 review)

- 변경: ROS-SIM gate를 GO로 올렸다. 도커 core 단계가 이 패키지를 복사하도록 `.dockerignore` 허용 목록에 넣었고, CI host pytest가 `robots/pinky_pro/test`를 돈다.
- 증거: WSL Ubuntu Jazzy 새 작업공간 `/root/rosy_ws_d196`(기존 `/root/rosy_ws`는 다른 작업의 구 레이아웃이라 건드리지 않음) — `colcon build --symlink-install --packages-up-to core pinky_pro` 8 packages finished; `ls $(ros2 pkg prefix pinky_pro)/share/pinky_pro/config` → `capabilities.yaml profile.yaml`; `robot_config_dir("pinky_pro")` → `/root/rosy_ws_d196/install/pinky_pro/share/pinky_pro/config`; `ros2 run core core` 부팅 `model=Pinky Pro`, api 8080, SIGINT 종료 (2026-09-24).
- gate 변화: ROS-SIM HOLD→GO
- 결정: D-196 Proposed
- 교훈: `wsl -- <cmd>`는 기본 셸(/bin/sh)이 명령줄을 다시 해석해 `$(...)`·`$PATH`가 바깥에서 먼저 펼쳐진다 — `wsl -e bash -c`로 실행한다.
