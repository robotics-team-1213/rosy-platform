# Isaac Sim 5.1/6.x integration

`middleware/devices/pinky/description/` remains the robot model source. `prepare_urdf.py` renders its xacro with the simulation collision geometry and without Gazebo plugins. `run_rosy.py` selects the installed 5.1 legacy or 6.x modern importer and creates ROS 2 graphs for one robot: `/rosy_01/cmd_vel` subscription, `/rosy_01/odom`, `/rosy_01/joint_states`, global `/tf`, and one global `/clock` publisher. The USD and URDF are generated artifacts, not repository source.

D-434 keeps the model PC on Isaac Sim 5.1. Its bounded diagnostic runs headless at 640×480 with anti-aliasing disabled. The runner excludes the GUI menu during initial startup; the importer can enable that dependency later. Keep normal extension shutdown so exceptions and failed cleanup remain visible. The SDK repair pins in `requirements-sdk-5.1.txt` apply to a separate SDK environment, not Isaac Lab.

## Requirements

고정 실행 관리의 모델 PC 진입은 `/usr/bin/python3 SOURCE/learning/envs/isaac/run_control.py --binding BINDING.json`이며 stdin JSON의 `catalog`, `check`, `start`, `list`, `status`, `stop`, `artifact`만 받는다. `omx-f-import`와 `pinky-conveyor-roundtrip`의 고정 시나리오를 제공하며 요청으로 경로·임의 명령·호스트·프레임 수를 지정할 수 없다.

접촉 왕복은 OMX-F CAD 집게와 동적 물체가 정지 Pinky 적재면 proxy ↔ 정지 컨베이어 proxy를 오가는 합성 배치다. 실제 접촉·자유 lift·집게 해제 후 안착을 독립 판정하며 보고서 1개와 단계 PNG 5개를 같은 run의 bounded artifact로 보존한다. Learning SIM 화면은 이 등록된 결과를 조회한다. 원래 SDK 실행의 source·run·지문과 실패 기록은 [검증 기록](../../../docs/validation/isaac-pinky-conveyor-roundtrip-2026-10-25/result.md)에 보존했다. 공개 포트의 호스트 회귀와 과거 SDK 관측은 별개다. 실제 카메라 정합·전체 Pinky·이동 벨트·학습 정책·동기화 Episode·실물 수용은 포함하지 않는다.

운영 binding은 같은 계정 소유의 쓰기 제한된 JSON이다. `uid`, 깨끗한 checkout의 절대 `source_root`와 전체 `source_sha`, 기존 `sdk_python`의 절대 경로·`sdk_python_sha256`·`sdk_version`, 설치 설정과 일치하는 `model_code_root`, 미리 만든 외부 `data_root`를 지정한다. 실행기는 SDK 설치나 서비스 enable을 하지 않는다. check는 SDK metadata·GPU 관찰·work/gpu 잠금을 확인하며 SimulationApp을 시작하지 않는다. start는 check의 `input_sha256`을 `expected_input_sha256`으로 고정하고 새 32자리 hex `request_id`를 사용한다. 동일 요청은 같은 run으로 복원한다.

worker는 두 잠금을 SDK child에 상속하고 실행 165초, 로그 16MiB, 관측 파일 합계 256MiB·256개를 감시한다. transient user unit은 180초·12G 상한이다. 종료 코드만으로 성공하지 않으며 보고서와 소유 프로세스·GPU 정리를 확인한다. stop은 현재 revision과 boot·InvocationID·cgroup·PID 시작 시각을 대조하고 pidfd로 소유 worker에만 요청한다. 소유권이나 정리가 불명확하면 `UNKNOWN`으로 남기며 자동 재실행하지 않는다. 입력·최종 결과·artifact manifest를 덮어쓰지 않는다. 원시 SDK 로그는 내부 경로가 있을 수 있어 공개 artifact에 포함하지 않는다. host 회귀는 새 SDK 실행이나 실물 수용의 증거가 아니다.

`import_omx.py`의 선택적 `--report <새 JSON 경로>`는 정상 SDK 정리 후 모델·관절·자산 지문·관측 프레임 수를 기록한다. 기존 파일은 덮어쓰지 않는다. `import_report.verify_report`는 일반 파일·크기·SDK 버전·자산 지문·필수 관절과 프레임 수를 다시 검사한다. 이 보고서는 모델 import 증거이며 `task_success`는 null이다. 물체 파지·정책 평가·실물 수용을 뜻하지 않는다. 고정 시나리오 원격 실행 관리와 접촉 왕복은 별도 공개 단위로 연결한다.

- Ubuntu 24.04 with ROS 2 Jazzy `xacro` and the separately managed Isaac Sim SDK on a supported NVIDIA GPU host. See [D-434](../../../docs/adr/D-434-model-pc-and-site-pc-roles.md) for the accepted host/version/resource boundary. The GPU runtime is not part of this repository or the Pinky Pi image.
- Source the ROSY Jazzy workspace for `xacro` package lookup. Before running Isaac Sim, configure its ROS 2 bridge. Set `ROS_DOMAIN_ID=41` for `rosy_01`; CORE retains its configured CycloneDDS transport, and the SDK's bridge transport must interoperate with it.
- Choose an output directory outside the repository. On this Windows workspace, generated files belong only under `X:\DevTemp\`; on the Linux GPU host, use a scratch directory outside the checkout.

## Run on the GPU host

```bash
source /opt/ros/jazzy/setup.bash
export ROSY_REPO=/path/to/rosy-platform
export ISAAC_PYTHON=/path/to/isaac-sdk-venv/bin/python
source "$ROSY_REPO/install/setup.bash"
export ROS_DOMAIN_ID=41
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp  # or use the same supported RMW as CORE
python3 "$ROSY_REPO/learning/envs/isaac/prepare_urdf.py" --output /scratch/rosy-isaac/rosy.urdf
"$ISAAC_PYTHON" "$ROSY_REPO/learning/envs/isaac/run_rosy.py" \
  --urdf /scratch/rosy-isaac/rosy.urdf \
  --output-dir /scratch/rosy-isaac/usd --namespace rosy_01 --headless
```

Set `ROSY_REPO` to the real ROSY checkout path and build its Jazzy overlay first. Use the SDK Python, not the system Python; an extracted SDK can also provide `python.sh`. If the importer produces more than one articulation or base footprint prim, inspect the imported USD and pass `--robot-prim` and `--chassis-prim`. The runner stops with a clear error when discovery is ambiguous.

Run a single CORE instance in the same namespace and domain. Verify `/clock`, `/rosy_01/odom`, `/tf`, `/rosy_01/joint_states`, the wheel joint names, and the number of `/rosy_01/cmd_vel` publishers before enabling motion. Configure external ROS nodes with `use_sim_time=true`. Record motion and zero-command behavior from the live simulation, not just the graph declaration. This runner has no LiDAR, camera, map scene, Nav2, Fleet or RL environment.

The soccer training environment deferred by D-98 belongs to `operations/apps/games/games/isaac/` and is not enabled here. See [D-322](../../../docs/adr/D-322-isaac-sim-rosy-integration.md) and the [research note](../../../docs/reference/isaac-sim-integration-research.md).

## Robot model assets

- **Pinky Pro:** The checked in URDF/xacro and 19 meshes live in [`middleware/devices/pinky/description/`](../../../middleware/devices/pinky/description/). `prepare_urdf.py` resolves these files for Isaac Sim. The official `pinklab-art/pinky_pro` model was checked at commit `014a09f289e6988894fbffde2624fdb1e257815b`; 13 meshes match byte for byte and six Collada visuals differ. Keep the ROSY model as the executable source until those visual differences are reviewed. See [`assets/README.md`](assets/README.md).
- **OMX-AI:** [`assets/open_manipulator_description/`](assets/open_manipulator_description/) contains the official ROBOTIS OMX-F follower and OMX-L leader URDFs and their referenced STL meshes. The snapshot is pinned to the same `open_manipulator` revision as `deploy/robot/omx/stack.lock.yaml`, with SHA-256 hashes in `manifest.json` and Apache-2.0 license text.

To prepare one OMX model for the Isaac URDF importer, resolve its local mesh paths into a generated file outside the checkout:

```bash
python3 "$ROSY_REPO/learning/envs/isaac/prepare_omx_urdf.py" \
  --model omx_f --output /scratch/rosy-isaac/omx_f.urdf
```

Use `--model omx_l` for the leader. Before opening Isaac, check the pinned file hashes, vendor URDF references, and the prepared Pinky URDF:

```bash
python3 "$ROSY_REPO/learning/envs/isaac/model_checks.py" \
  --pinky-urdf /scratch/rosy-isaac/rosy.urdf
```

Import and inspect one OMX model with Isaac Sim's own Python. This checks for exactly one articulation and the expected joint names in the generated USD:

```bash
"$ISAAC_PYTHON" "$ROSY_REPO/learning/envs/isaac/import_omx.py" \
  --model omx_f --urdf /scratch/rosy-isaac/omx_f.urdf \
  --output-dir /scratch/rosy-isaac/omx-f-usd --headless
```

These are importable geometry and joint models; `run_rosy.py` is a Pinky mobile-base runner and does not supply an OMX articulation controller, cameras, calibrated workcell, or trained policy. Datasets and model weights depend on a selected manipulation task and are not part of the robot description snapshot.

### GPU-host acceptance still required

[Latest-main headless evidence](../../../docs/validation/isaac-latest-core-main-2026-10-11/result.md) records the current CORE source, remote regression and measured motion/stop results. Rotation tracking remains below the acceptance band, so the complete ROS-SIM/RL gate stays HOLD.

The Pinky URDF places wheel joint origins at ±0.04055 m, a geometric center separation of **0.0811 m**; the wheel collision cylinders sit a further ±0.008 m out, a contact separation of **0.0971 m**. The Gazebo drive plugin and the Isaac controller both use that URDF nominal **0.0971 m** as `wheelDistance` (D-397, `middleware/devices/pinky/profile/config/geometry.yaml`); a robot's accepted `wheel_odometry` calibration record refines it on the device. On the GPU host, import the USD, confirm wheel axis/sign and ground contact, then compare commanded yaw with `/odom` and observed rotation. Also confirm one `/clock` publisher, TF frame IDs, command topic ownership, and zero-command/command-loss stopping before Nav2 or an extended run. The runtime receipt watchdog and zero target readback do not replace measured physical stopping or yaw tracking. Keep motion acceptance separate from an import or host test.

## 한 대 실제 맵 CPU RL 진단

[D-638](../../../docs/adr/D-638-isaac-single-pinky-cpu-rl-diagnostic.md)의 `run_map_rl.py`는 `260919 MAP FILE.STL`에서 생성한 curved 경로와 30cm 외곽 벽을 사용한다. 기존 Drive `PathFollower`의 yaw 후보에 CPU Q-learning gain을 적용하고 기존 CORE `CommandManager`·`cmd_vel_cycle`로 최종 출력한다. 한 대 native SDK 진단이며 D-606 Isaac Lab, ROS-SIM 및 두 대 Fleet·신호 수용과 구분한다.

모델 PC의 격리 SDK Python에서 준비한 URDF와 새 출력 디렉터리를 지정한다. 운영 `ROSY_CONFIG`/`ROSY_NAMESPACE` 환경은 거부한다. 실행 전후 source 파일 해시, 자원 여유와 소유 작업의 종료를 확인한다.

```bash
"$ISAAC_PYTHON" "$ROSY_REPO/tools/sim/isaac/run_map_rl.py" \
  --urdf /scratch/rosy-isaac/rosy.urdf \
  --output-dir /scratch/rosy-isaac/map-rl-new-run \
  --source-revision "$(git -C "$ROSY_REPO" rev-parse HEAD)" --train-episodes 6
```

baseline, 짧은 구간 학습, 정책을 고정한 평가 시드 202/303 순서로 실행한다. 실제 pose의 ordered progress·이탈·물리 정지를 판정하고 trace·Q table·결과를 출력한다. 학습 업데이트 없이 기존 규칙만 완주한 결과는 학습 성공으로 처리하지 않는다. [검증 결과](../../../docs/validation/isaac-map-rl-2026-10-11/result.md)를 따른다. 내부 날짜별 일지는 Git 제외 경로 `private/isaac/{plans,journal,results,templates}/`에, 원시 로그는 관리된 X: 세션과 모델 PC scratch에 보관한다.

### 실제 화면 녹화와 네 시작 방향

기존 실행의 policy.json을 고정해서 시작 경로 방향 대비 0/+90/180/-90도에서 각각 전체 경로를 평가한다. 재학습 없이 기존 CORE·Drive와 물리 stop/reset을 사용한다. 저장 정책의 gain·state·유한 Q·학습 횟수를 검증하며 동일 입력 bytes를 보관한다.

```bash
"$ISAAC_PYTHON" "$ROSY_REPO/tools/sim/isaac/run_map_rl.py" \
  --urdf /scratch/rosy-isaac/rosy.urdf \
  --output-dir /scratch/rosy-isaac/directions-new-run \
  --source-revision "$(git -C "$ROSY_REPO" rev-parse HEAD)" \
  --policy-file /scratch/rosy-isaac/map-rl-new-run/policy.json --record-video
```

SDK 호스트의 기존 ffmpeg가 필요하다. --record-video는 headless Isaac 상공 카메라의 실제 RGBA를 960×540 H.264 MP4로 저장한다. simulation 약0.2초마다 실제 frame을 받아 25fps로 표시하므로 5배속이며 위치 보간을 만들지 않는다. .frames.jsonl에는 native Fabric renderer receipt·시각·실제 pose가 남고 encoder 오류나 stale frame은 실패다. 영상은 isaac-eval-<seed>.mp4, 정책·영상 hash와 방향별 완주·정지는 result.json을 따른다. 카메라는 녹화 관측용이며 로봇 센서/인식 수용을 뜻하지 않는다.

네 시작 방향 검사이며 역순 경로·모든 각도·두 대 Fleet·신호·횡단보도 통제 수용과 구분한다. 실행 순서는 [녹화 계획](../../../docs/plans/2026-10-11-isaac-direction-video.md)을 따른다.
