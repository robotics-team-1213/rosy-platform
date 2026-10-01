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

## 2026-10-01 · uncommitted · fix(pinky_pro): device CORE line_follow LiDAR forward 180 deg (D-344 §11)

- 변경: `config/core.yaml` 신설 — `line_follow.lidar_forward_deg: 180.0`. rosy_default 는 0 그대로라 실물·새 이미지·페이로드 모두 앞 물체 정지(±20°, 0.20/0.28 m)가 로봇 뒤를 보고 있었다(8kcn 만 2026-09-29 손 핫픽스). rplidar_link yaw π 라 정면은 스캔 180°. 승인된 lidar_mount 기록(D-47 추가, lidar_mount.py)이 있으면 그것이 이긴다(실측 ≈181–182°). 손값은 180 유지.
- 증거: `test_pinky_lidar_forward_device.py` 5 passed — rosy-runtime.env + ROSY_DEPLOYMENT=device + 첫 부팅 오버레이로 load_config → 180, 기본값 0 유지, 오버레이 우선, omx 는 0. 변이(블록 삭제) 시 `assert 0.0 == 180.0` 실패.
- gate 변화: SOURCE/LOCAL GO. DEVICE HOLD(페이로드 배포 전; 실물 미접촉).
- 결정: D-344 §11, D-47 추가(2026-10-01), D-196.
- 교훈: 제품 기본값을 주석으로만 적어 두면(“Pinky Pro device: 180”) 어떤 배포 경로도 그 값을 싣지 않는다.

## 2026-10-01 · edca9b2e · feat(profile): 생성 `geometry.yaml`, 카메라 NOMINAL을 URDF 값으로 (D-397)
- 변경: `config/geometry.yaml` 신설(`tools/calibration/urdf_nominal.py` 생성). `camera_nominal.yaml` 피치 0.1396 → 0.139626, 높이 0.067 → 0.06343, x 0.034 → 0.03317. `core.yaml` 180은 그대로, 드리프트 테스트로 묶음.
- 증거: `tools/calibration/test/test_urdf_nominal.py`.
- gate 변화: SOURCE/LOCAL. DEVICE HOLD — 보정 없는 로봇의 차선 투영 척도 약 5 % 변화(재생: target-on-paint 1.5 → 5.5 %).
- 결정: D-397 Proposed.
