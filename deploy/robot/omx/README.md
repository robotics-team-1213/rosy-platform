# OMX-AI Workcell Deployment Preparation

This directory builds a separate ROS 2 Jazzy workstation OCI image for a fixed
OMX-AI workcell. `stack.lock.yaml` pins the official ROBOTIS source set to
immutable revisions. It is not part of the Raspberry Pi product image.

## Current contract

- Target model: OMX-AI.
- Runtime profile: disabled; no joint map, hardware plugin, serial identity,
  camera identity, or motion command is configured.
- Vendor entry point: official ROBOTIS `open_manipulator` ROS 2 packages.
- Development/build candidate: a dedicated workstation OCI image, initially
  amd64. Keep it separate from `deploy/robot/pinky_pro`'s Pinky Pro ARM64 product image.
- Field control candidate: one native systemd instance per workcell under
  D-246. One Ubuntu host may run two instances after graph, device, stop,
  recovery, and concurrent-load validation. The OCI shell below is not an
  accepted field actuator runtime.
- Camera source: unselected. Choose a camera and driver before adding camera
  packages to the runtime image.

See [the implementation plan](../../docs/plans/2026-09-26-omx-ai-workstation-runtime.md)
and [host placement design](../../docs/plans/2026-09-26-site-host-placement-design.md)
for deployment trade-offs, RMW boundaries, and P0-P3 acceptance gates.

## Host inventory and multi-workcell preflight

`host-inventory.yaml.example` is a disabled placement template for one or two
workcells on one host. `host_inventory.load_inventory()` parses the static
`rosy.omx-host-inventory.v1` YAML contract. `hosts` and `workcells` are keyed by
their IDs; every workcell needs an `instance_id`, a known `host_id`, and an
explicit boolean `enabled`. A disabled workcell may omit `follower` and
`leader` or set them to `null`. An enabled workcell needs two distinct,
operator-selected `/dev/serial/by-id/` entries. A selected `camera` identity
is optional until a camera is chosen. Enabled workcells on the same host may
not select the same serial or camera identity.

Keep a filled host inventory in gitignored `private/` or `/etc/rosy/omx/` on
that host. Do not put real serial identities, camera IDs, addresses, or tokens
in the tracked example. The parser does not open devices or register OMX in
Fleet. It is not wired into site Compose or an operational control service.

`preflight.resolve_host_devices(inventory, host_id, probe=...)` reuses the
single-workcell serial preflight for every enabled workcell assigned to one
host. It checks that selected entries resolve to readable and writable
character devices, then rejects real-path aliasing across workcells. Disabled
workcells and workcells on other hosts are not probed or reserved. This is a
software admission check; only a later, separately validated native control
runner may consume the returned per-workcell paths. No camera is opened by
this preflight.

## Native arm software readiness

### Docker-free Gazebo launch

`run_cell_sim.sh` also runs on a native ROS 2 Jazzy simulation host. Build the
locked `open_manipulator_description` and `open_manipulator_bringup` packages
into a user prefix after applying `omx-f-gazebo-headless`, `omx-ai-sim-gates`
and `omx-ai-sim-action-only` from `patches/`, in that order. Use the system
Python matching ROS when building; do not change the host's default Python.
No Docker installation or Docker group membership is needed.

Select a non-site host through `tools/remote/remote_pytest.py --pick sim`
and hold its simulation resource lock for the run, as described in
`tools/remote/AGENTS.md`. Launch inside a bounded user systemd scope with
its own `GZ_PARTITION`, loopback `GZ_IP`, and allocated `ROS_DOMAIN_ID`:

```bash
export OMX_CELL_OVERLAY="$HOME/rosy-test/<prepared-build>/install"
export OMX_CELL_LOG_DIR="$HOME/rosy-test/<run>/logs"
bash deploy/robot/omx/run_cell_sim.sh
```

The overlay must contain `setup.bash`; the compatibility default is
`/opt/omx_ws/install`. `OMX_CELL_ROS_SETUP` optionally selects the ROS setup
script (default `/opt/ros/jazzy/setup.bash`). These are trusted shell inputs.
`OMX_CELL_WORLD` selects a world path without `.sdf`; otherwise the world is
resolved from this checkout. `OMX_CELL_DOMAIN_ID` overrides an inherited
`ROS_DOMAIN_ID`; absent both, the compatibility domain is 77. Discovery stays
localhost-only. A host carrying `~/rosy-jobs/site` is refused before setup.

This starts the Gazebo follower only, with no ROSY command owner or task
admission. Native process/resource separation does not satisfy G2's stronger
network/device/read-only filesystem isolation guard. Keep that guard and
startup HOLD intact; launching Gazebo is not Fleet task or hardware acceptance.

After sourcing the selected native ROS installation, run:

```bash
python3 deploy/robot/omx/hardware_readiness.py --domain-id <workcell-domain> --namespace <workcell-namespace>
```

This read-only probe takes the expected ROS distribution from `stack.lock.yaml`,
checks required package discovery, and observes typed trajectory actions and
the selected namespace's `/arm_controller/follow_joint_trajectory` and
`/joint_states` publisher names for three seconds. Use `--namespace /` for a
root graph. A different cell's action or publisher cannot supply these checks.
It opens no serial device,
starts no controller and sends no goal. Exit 2 means the software path is missing
or discovery failed; exit 0 means only the observed software prerequisites exist.
`motion_admitted` is always false. Publisher names, action presence and package
availability do not establish hardware identity, measured limits or a real stop.

### Supervised register inspection

After physically identifying the follower cable, use the pinned DynamixelSDK
Python package and pyserial on the native host:

```bash
python3 deploy/robot/omx/register_probe.py --device /dev/serial/by-id/<confirmed-follower>
```

This opens the confirmed port exclusively at 1 Mbps and permits only PING and
READ(0,147) packets for IDs 11..16. It rechecks ownership after the exclusive
lock; run as the device owner without privileged competing serial processes.
It never configures motors, enables torque or starts the controller. Models
other than 1060/1200, busy ports, incomplete responses and transport failures
return exit 2. Exit 0 means a complete snapshot, including any reported motor
faults or enabled torque; `motion_admitted` remains false. Raw position limits
are not measured mechanical limits. Keep output private.

The [first follower inspection](../../../docs/validation/omx-follower-registers-2026-10-15/result.md)
found positions outside the vendor startup limits. Do not start the default
launch merely to create an Action server: even inactive initialization writes
configuration. Hardware profile, initialization and physical stop acceptance
remain prerequisites for control.

### Bounded physical joint observation

```bash
python3 deploy/robot/omx/hardware_observer.py --device /dev/serial/by-id/<confirmed-follower> --domain-id <workcell-domain> --duration 120
```

This commissioning process holds the same read-only, exclusive port for at most
the requested 1..300 seconds. It publishes nominal vendor radians at up to 10 Hz
on `/omx_commissioning/joint_states`, separate from synthetic `/joint_states`.
The gripper value is an angle, not a measured jaw width. Homing Offset is already
included in Present Position and is not applied a second time.

Every published sample requires the six ordered, matching motor models, torque
off, no hardware errors, and a read window of at most 250 ms. A failed sample
ends the process without publishing that sample; exit 2 also covers cleanup or
early ROS termination. Timestamp is the start of the read, not publication time.
Private JSONL stdout contains the raw snapshots. Normal duration completion is
exit 0. A controller must not consume this uncalibrated commissioning topic.

The process pins Fast DDS, clears static peers and requests localhost discovery;
external DDS profiles/discovery-server overrides are rejected. This limits
discovery, not an authorization boundary against other local or privileged
processes. It has no Action server, subscription or register-write path, never
enables torque and never reconnects automatically. Stop it before any subsequent
accepted controller takes the port. It is physical feedback preparation, not an
operational arm control server or mechanical calibration acceptance.
Use the [hardware control plan](../../../docs/plans/2026-10-15-omx-hardware-control.md)
for the remaining native runtime and physical acceptance work.

## Local camera preview recovery

`omx_adapter/camera_source.py` reads an explicitly selected `/dev/v4l/by-id/`
camera through V4L2 MJPEG at 640×480, publishing at most `--max-fps` (default
10 Hz, `ROSY_CAMERA_MAX_FPS` in the unit env) with a one-image queue. It refuses raw-format fallback, reopens failed capture, and notifies the
`rosy-omx-camera@.service` watchdog so a blocked driver read is restarted.
It publishes host-receive timestamps and no CameraInfo or calibrated target;
these previews do not admit an arm operation.

Install the reviewed source snapshot and user unit on the camera host. Each
`~/.config/rosy/omx-camera-<name>.env` binds `ROSY_ROS_SETUP`, `ROSY_CAMERA_SOURCE`,
`ROSY_CAMERA_DEVICE`, `ROSY_CAMERA_TOPIC`, `ROSY_CAMERA_FRAME`, and `ROS_DOMAIN_ID`
to that host's accepted runtime and selected camera. The camera, viewer and
collection units force `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` with no static
peers (D-795): raw Image topics never cross machines. Every DDS consumer of these
frames (`commissioning_view.py`, collection, the pilot simulation) runs on the
camera host; another machine reads `commissioning_view.py`'s loopback HTTP/JPEG
through an SSH localhost forward, or the WebRTC media path once it lands. Keep device identities and
host paths in private configuration. Stop the previous producer for that exact
camera before starting the unit, and verify advancing fresh frames and measured
format after start. Arm drivers and their admission profiles remain separate.

The selected native ROS installation must already provide `rclpy`, `sensor_msgs`,
`cv_bridge`, and OpenCV's `cv2` (`python3-opencv`); verify those imports with
`/usr/bin/python3` after sourcing `ROSY_ROS_SETUP`. The optional standalone
preview is not provisioned by the disabled adapter profile or workstation image.
For boot activation, enable the user units and verify `loginctl show-user
<camera-user> -p Linger` reports `Linger=yes`. A unit active during login alone
does not prove boot activation. Capture buffer size must read back as one;
host-receive stamps do not measure sensor exposure age. Test actual USB
unplug/replug and cold boot on site before accepting unattended operation.

### Native preview receiver transport check

Measure advancing frames at the **consumer**, not just the camera unit's active
state. On the separately observed Lyrical/Fast DDS preview host, a default
receiver later fell below the earlier 10 Hz result while a concurrent receiver
with the publisher's transport settings received about 10 Hz from both cameras:
[receiver comparison](../../../docs/validation/omx-preview-receiver-2026-10-15/result.md).
For that preview environment only, scope this setting to the receiving process
or its private service environment **before** it initializes ROS:

```bash
export FASTDDS_BUILTIN_TRANSPORTS='DEFAULT?max_msg_size=60KB&sockets_size=2MB&non_blocking=true'
```

Keep the quotes in a shell: `&` belongs to the value. Source the selected ROS
environment and supply the explicitly selected workcell domain separately.
This is a measured preview-host configuration, not a global ROS/RMW change or
a replacement for the pinned Jazzy/CycloneDDS development and actuator contract.
It is not consumed by CycloneDDS. Do not apply it to unrelated robot services.

Compare the same subscriber workload with and without the setting; record
duration, received frames/FPS, maximum gaps, nonadvancing/stale stamps, frame
IDs and formats for **both** cameras. A short successful sample does not prove
continuous delivery, USB recovery, boot behavior, calibrated exposure timing,
or AI/Fleet consumption. Complete the long run on the actual consumer before
calling that consumer ready; transport settings alone grant no arm authority.

## Build and shell profiles

The hardware profile takes `OMX_ROS_DOMAIN_ID` from the Compose environment
(default 30). Discovery is fixed to `LOCALHOST` and the container mounts Pinky's
loopback-only Cyclone profile as `/etc/rosy/cyclonedds.xml`: no DDS traffic leaves
this host (D-795). Copy `.env.example` to `.env` beside this README to set the
domain, then pass it with `--env-file deploy/robot/omx/.env` when running Compose from
the repository root. RMW is fixed to `rmw_cyclonedds_cpp` by D-117. The
simulation profile uses a separate configurable domain (default 31) and forces
`LOCALHOST` discovery.

Pinky's domain is derived at device provisioning from `ROSY_ROBOT_NUMBER`
(D-33), so never change Pinky's identity to match the workstation. Matching an
OMX domain to Pinky's value alone does not authorize or guarantee a connection:
the D-273 ROS/RMW and control-boundary decision remains required. Do not use
this workstation profile to join Pinky's actuation graph directly.

Build on a Linux ROS 2 workstation with Docker:

```sh
docker compose -f deploy/robot/omx/compose.yaml build
```

The image fetches only repositories in the lock, checks out full commit SHAs,
installs the locked stack's arm bringup/description/Dynamixel dependencies,
and builds the selected packages with `colcon`. It leaves Gazebo, MoveIt,
vendor GUI, RealSense, and camera packages out of this base image. `hardware` is an inert
interactive shell that receives only the explicitly selected follower and
leader serial ports. Generate the device values on that Linux host with:

```sh
python3 deploy/robot/omx/preflight.py \
  --follower /dev/serial/by-id/<selected-follower-id> \
  --leader /dev/serial/by-id/<selected-leader-id>
```

Pass the resulting `OMX_FOLLOWER_DEVICE` and `OMX_LEADER_DEVICE` values as
environment variables to:

```sh
docker compose --env-file deploy/robot/omx/.env --profile hardware run --rm omx-hardware-shell
```

The preflight refuses guessed `/dev/tty*` paths, missing
or non-character devices, inaccessible devices, and duplicate selections.
Never use privileged mode or mount `/dev` wholesale.

The `simulation` profile starts ROBOTIS's `omx_f_follower_ai_gazebo.launch.py` from the
locked `open_manipulator` revision. That launch uses the vendor OMX-F URDF
with `use_sim:=true`, Gazebo Sim, `gz_ros2_control`, the vendor controllers,
and the `/clock` bridge. It has no serial or camera device grants. Its ROS
domain is isolated from the workstation and remains software-only; it does
not start the physical Dynamixel driver or claim device acceptance. A checked-in
A checked-in patch selects Gazebo server mode and Bullet Featherstone physics
for the gripper mimic constraint, makes simulated `ros2_control` synchronous,
and enables the vendor controller manager's URDF command limits. These are
simulation settings; the native actuator configuration remains unchanged.
The simulation launch also removes the vendor's direct
`/leader/joint_trajectory` remap. In a two-input probe, the leader topic moved
`joint1` to `-0.2` rad while an action to `+0.2` rad reported success. The
simulation therefore exposes the action path without that leader connection.
This does not implement a general command owner for native control.
Patch files are checked out with LF endings so `git apply` works in the Linux
image even when the build context comes from a Windows checkout.

The development image also removes the same direct leader trajectory remap
from the vendor's non-simulation `omx_f_follower_ai.launch.py`. This prevents
that particular topic from bypassing an accepted action goal when the inert
hardware shell is used for diagnostics. The patch is copied into the installed
launch after the vendor build. It is not a native systemd runtime or an
admission boundary: other participants in the ROS graph can still address the
controller action or trajectory topic. A per-workcell command owner, graph
isolation, independent stop, and physical readback remain required before
field actuator control (D-281/D-273).
Start it on a Linux workstation with a working Docker engine:

```sh
docker compose --env-file deploy/robot/omx/.env -f deploy/robot/omx/compose.yaml --profile simulation up --build omx-simulation
```

Stop with Ctrl-C. Verify `/joint_states`, controller state, and `/clock` from
inside the container before treating the run as ROS-SIM evidence. This profile
does not yet include a camera simulation, arm command-safety adapter, or
automated stop/fault acceptance. Camera packages and grants remain deferred
until a camera model and persistent identity are selected.

The image tag is a local development tag, not an artifact identity. Record a
content digest and dependency/build manifest before treating it as ARTIFACT
acceptance. A successful host build does not prove ARM64 Pi compatibility,
device access, arm motion, camera timing, or field acceptance.

## Moving a workcell to another host

This is a placement handoff sequence, not permission to start an actuator.
Keep the same `workcell_id` and record a new host/config revision. For each
workcell independently:

1. Stop the old controller instance and verify its process has exited and its
   selected serial/camera devices are no longer held. Mark work in progress
   `UNKNOWN` or HOLD until the device result is independently read back; never
   replay the prior trajectory on the new host.
2. Verify the new host identity, locked vendor/runtime artifact digest, ROS
   graph isolation, selected `/dev/serial/by-id/` devices, camera identity,
   calibration revision, and host-specific credentials. Run
   `resolve_host_devices()` on the new host before any vendor launch.
3. Start the new instance in a no-command state. Read back controller and
   physical stop state, then require an explicit operator decision before new
   work. If either old ownership release or new readback is unclear, keep both
   hosts from issuing commands.
4. Record old/new host IDs, workcell/instance IDs, artifact and config
   revisions, device identities, stop/readback evidence, operator, and time.
   Keep Fleet task SQLite on its site host; do not share-mount it to the OMX
   host or treat its task status as arm completion.

No host transfer or two-arm load test has been performed on physical OMX-AI
hardware. D-281's shared-host placement remains a candidate until measured.

## Reproduce the owner-to-vendor simulation probe

After building the development image from this checkout, run the probe with
the checkout mounted read-only, no network, and no device grants. From the
repository root in PowerShell:

```powershell
$omxCheckout = (Resolve-Path .).Path
$omxRevision = git rev-parse HEAD
docker run --rm --network none `
  --mount "type=bind,source=$omxCheckout,target=/repo,readonly" `
  rosy-omx-workstation:native-action-only-local `
  bash /repo/deploy/robot/omx/probe_vendor_owner_sim.sh
```

The script starts the locked Gazebo follower, runs the opt-in ROS adapter
test, and stops its launch on exit. It rejects serial/video device grants.
The test checks action result/cancel, a competing policy owner, and the
absence of a subscriber to the old leader trajectory topic. This is one
container's ROS-SIM evidence, not a native systemd or physical stop test.

## Pilot에서 OMX-AI Gazebo 연습 (D-390)

작업 PC의 개발용 컨테이너에서만 실행한다. 정본 vendor 이미지는 위 절차대로 먼저 만들고, 저장소 루트에서 Pilot HTTP layer를 만든다.

```powershell
docker build -f deploy/robot/omx/Dockerfile.pilot -t rosy-omx-pilot:local .
$omxCheckout = (Resolve-Path .).Path
$omxRevision = git rev-parse HEAD
docker run --rm --name rosy-omx-pilot-sim --network bridge `
  -p 127.0.0.1:8088:8088 `
  --mount "type=bind,source=$omxCheckout,target=/repo,readonly" `
  --mount type=volume,source=rosy-omx-pilot-recordings,target=/recordings `
  -e "ROSY_SIM_SOURCE_REVISION=$omxRevision" `
  rosy-omx-pilot:local bash /repo/deploy/robot/omx/run_pilot_sim.sh
```

로컬 CLI에서 docker exec rosy-omx-pilot-sim cat /run/rosy-omx-pilot/pairing-code 로 일회용 pairing code를 확인하고 `http://127.0.0.1:8088/pilot`로 접속한다. 관절 버튼 한 번에 0.02 rad, 0.4초 goal 하나만 낸다. 조종권 lease는 10초이며 서버가 갱신 실패·반납을 보면 취소를 요청한다. 취소 응답만으로 정지를 주장하지 않는다. 이 실행은 localhost publish, localhost ROS discovery, read-only checkout을 사용하고 serial/video 장치를 넘기지 않는다. 중단은 Ctrl-C다.

새 컨테이너를 띄운 뒤 실제 ROS goal과 관절 readback을 자동 확인하려면, 다른 터미널에서 `python deploy/robot/omx/probe_pilot_sim_http.py rosy-omx-pilot-sim`를 실행한다. 이 probe는 일회용 코드를 소비하므로 같은 실행에서 브라우저 페어링을 다시 하려면 컨테이너를 재시작해야 한다. 출력에는 코드와 토큰을 표시하지 않는다.

기본 실행은 joint1 조그, 속도에 맞춘 그리퍼 절대 목표(readback + 0.02 rad), 닫기 뒤 열기, 명시 취소를 확인한다. `--stall` 은 D-411 C "쥐고 있음"의 **차단 ROS-SIM 관문**이다: 그리퍼를 열고, 제한 조그로 위에서 내려다보는 집기 자세(기본 x 0.18 m, TCP 높이 `--grasp-z` 0.015 m)로 간 뒤, 손가락 사이에 동적 정육면체(`--cube-size` 0.025 m, `gz service .../create`)를 만들고 닫는다. 끝 상태·ROS 결과 코드·끝까지 걸린 시간·그리퍼 readback·마지막 0.5 s 관절별 최고 속도를 `stall_probe=` JSON 한 줄로 남기고, 쥐고 있음이면 joint1 조그 세 번(각각 SUCCEEDED, 상태 유지)을 확인한다. 통과 0, 미통과 2, 오류 1. 정육면체 크기·집기 높이·컨트롤러 `goal_time`·`stopped_velocity_tolerance`(SIM 패치)는 명목값이며 이 probe 결과로 조정한다. 컨트롤러 목표 판정은 Gazebo 전용 파일 `open_manipulator_bringup/config/omx_f_follower_ai/gazebo_arm_controller_constraints.yaml`(`omx-ai-sim-gates.patch`가 만들고 Gazebo launch 의 `arm_controller` spawner 만 `--param-file` 로 읽는다)에 있고, native launch 가 읽는 `hardware_controller_manager.yaml` 에는 없다. **패치는 이미지 빌드 때 적용되므로 이 값을 바꾸거나 처음 받으려면 이미지를 다시 빌드해야 한다** — 2026-10-03 첫 stall 관문은 이전 이미지에 yaml 을 bind-mount 해서 돌렸다(`$ROSY_SCRATCH/d411-simC`). gz 서비스는 컨테이너 안에서 `/opt/ros/jazzy/setup.bash` 를 source 한 bash 로 부른다. 패치를 고친 뒤에는 다시 빌드하기 전에 `python deploy/robot/omx/check_vendor_patches.py` 로 고정 revision 의 vendor 파일에 Dockerfile 순서대로 모든 패치가 적용되고 결과 launch·YAML·xacro 가 읽히는지 본다(`test/test_omx_vendor_patch_order.py`, 오프라인이면 건너뜀). 뒤 패치는 앞 패치가 적용된 소스에 대해 만든다 — `omx-ai-sim-action-only.patch` 는 `omx-ai-sim-gates.patch` 뒤의 launch 를 기준으로 한다.

고정 SDF 작업대 카메라는 headless OGRE2로 실제 RGB 320×240 영상을 10 simulation FPS로 만든다. 이 영상·과거 관절 상태·ROS가 수락한 목표를 Pilot의 시연 기록 패널로 저장한다. Linux 볼륨을 사용한다. Windows 공유 폴더에 프레임을 직접 쓰면 ROS callback/기록이 지연될 수 있으며 프레임 누락·신선도 실패로 불완전해진다. writer는 별도 스레드이고 조작의 0.5초 신선도 검사는 그대로다. 초기 headless renderer 준비를 위해 vendor broadcaster의 switch-timeout만 60초로 고정하며 실행 중 watchdog은 바꾸지 않는다.

### 기록과 오프라인 변환

- Pilot에서 과제를 입력하고 기록 시작 → 관절 조작 → 과제 결과(성공/실패) 선택 → 기록 종료.
- 과제 결과 미선택·영상 누락·HOLD·취소·lease 만료/반납은 incomplete다. 이런 원본은 export를 거부한다.
- pairing code와 토큰은 export하지 않는다. 원본 manifest/JSONL/PNG는 학습 데이터이므로 로컬에 보관한다.
- 실제 자동 확인: python deploy/robot/omx/probe_pilot_recording.py rosy-omx-pilot-sim.
  성공 기록과 lease 만료에 의한 불완전 기록을 검사하고 코드/토큰은 출력하지 않는다.
- 원본 가져오기: docker cp rosy-omx-pilot-sim:/recordings/<episode-id> $ROSY_SCRATCH/rosy-omx-recordings/.
  Windows 자료·export 출력은 $ROSY_SCRATCH에 둔다. 컨테이너를 삭제해도 이름 있는 recording volume은 유지된다.

별도 Python 3.12 CPU 환경에 torch 2.10.0+cpu / torchvision 0.25.0+cpu를 공식 CPU wheel index로 먼저 설치하고 requirements-lerobot-export.txt를 설치한다. 실제 검증한 transitive inventory는 검증 문서에 기록한다. ROS 런타임에 LeRobot을 설치하지 않는다.

PowerShell 실행 예:

```powershell
$RosyScratch = if ($env:ROSY_SCRATCH) { $env:ROSY_SCRATCH } else { [System.IO.Path]::GetTempPath() }
$env:PYTHONPATH = (Get-Location).Path + '/middleware/devices/omx/adapter;' + (Get-Location).Path + '/contracts/foundation'
& "$RosyScratch/rosy-omx-lerobot-044/Scripts/python.exe" learning/curation/omx/lerobot_export.py `
  $RosyScratch/rosy-omx-recordings/<episode-id> $RosyScratch/rosy-omx-export/<new-output> `
  --repo-id rosy-local/omx-sim
```

export 결과가 verified이고 실제 reader가 모든 frame을 재독출한 경우에만 데이터셋 연계 검증이다. 원본 복사와 해시는 rosy_provenance에 남는다. robot_type=omx_sim_ros, ROS joint 순서와 rad를 유지한다. native OMX follower의 body normalization/degree·gripper 0~100으로 자동 변환하지 않는다. 학습·정책 실행·Hub 업로드·실물 활성화는 별도다.

## Rosy Cell C3: one CELL_TRANSFER in Gazebo (D-402)

`run_cell_sim.sh` starts the locked follower in `integrations/simulation/gazebo/worlds/omx_cell_workcell.sdf`
(or `OMX_CELL_WORLD=<path without .sdf>`) with no command owner. `probe_cell_transfer.py`,
run with `docker exec` in that container, is the single owner process for the run: profile-built
`ArmCommandOwner`, analytic planner, `PickPlaceRunner`, gripper readback and `gz model -p`
block poses (helpers in `cell_sim_tools.py`). Do not start `pilot_sim.server` beside it; the
probe refuses to run if one is present. Commands, stand-in flags, sim aid and results:
[docs/validation/rosy-cell-gazebo-c3-2026-10-02](../../../docs/validation/rosy-cell-gazebo-c3-2026-10-02/README.md).

## Instance namespace (simulation)

`run_cell_owner.py`, `g2_owner.py`, `g2_common.py`, `g2_observer.py` and `probe_cell_transfer.py`
take the arm graph names from `instance_names.py`. `ROSY_OMX_ROS_NAMESPACE` names the instance
graph (for example `/omx_02`); unset means the root graph `/`, the single-arm default. The joint
state topic, the `arm_controller` action and the `controller_manager` service are prefixed with it;
`/clock` stays global. The second-owner refusal now refuses only an owner in the same namespace
(an owner whose namespace cannot be read counts as the same graph). Two arms on one host still need
separate graphs, sockets and devices (D-281); this only stops the root names from being hard-coded
(D-778 §1, D-779).

## Cell owner Fleet fence configuration (simulation)

`run_cell_owner.py` requires `ROSY_FLEET_FENCE_URL` and `ROSY_FLEET_FENCE_TOKEN`
before importing ROS. The URL must name the existing read API on literal loopback,
for example `http://127.0.0.1:8080/api/fleet/dispatch-control`. Fleet must be reachable
in the owner's network namespace; a Docker bridge hostname or a different host is
refused. Keep the existing same-kernel, UID-checked UDS mount for Action/stop/rearm.

Provision a separate named `viewer` in Fleet's existing site-user configuration and
provide its private raw bearer secret as `ROSY_FLEET_FENCE_TOKEN`. Do not use a robot,
operator, registry or pairing credential. No secret is included in this repository,
and this configuration note does not register credentials or start a service.
The client issues uncached GET requests, with a 250 ms socket timeout and 8 KiB body
limit; redirects, invalid/authentication replies, disabled dispatch, lost connectivity
and mismatched epoch/generation refuse. The timeout bounds socket inactivity;
it is not an independent physical stop or a hard end-to-end deadline.

Fleet offloads UDS rearm so its event loop can serve the owner's reverse readback.
Owner initialization still leaves the local stop closed. A named operator must rearm
the existing Fleet API, with unresolved Actions reconciled first. Live ROS/UDS fault
acceptance, seat exclusion and the full two-layer/two-pallet recipe remain open;
host HTTP tests are not Gazebo or physical acceptance.

## 실물 모방학습 준비

녹화 설정 검사, native 검토·분할, ACT, private Hub 동기화는 [실행 안내](../../../learning/curation/omx/README.md)를 따른다. 실행 PC와 HF 조직은 미정이며 Pilot 실물 활성화는 별도다.

`record_session.py`는 단일 팔과 `bi_omx_follower`/`bi_omx_leader` 양팔 설정을 받는다. 양팔은 서로 다른 네 개의 영구 serial 경로·장치 ID를 지정하고, 카메라는 follower 부모 설정에만 둔다. 각 자식 follower는 빈 `cameras`와 `use_degrees=false`를 사용한다. 기존 설정 검사 뒤 `Session.command()`가 원본을 보존한 native 설정을 만들고, 구체적인 자식 OMX 설정의 `type` 태그를 SDK 진입 전에 제거한다.

native runner는 보정된 passive leader·follower를 확인하고 현재 자세에서 seed한 뒤 최대 1도/초로 모든 12관절을 전달한다. 데이터의 action은 실제 보낸 값이며, 한 팔의 상태 지연·추종 오차·지속 부하·열/전압 오류가 발생하면 양쪽 leader와 follower 모두 torque OFF를 시도한다. 부모 세션은 오류가 난 장치도 확인 가능한 정상 통신 응답에 한해 OFF와 검증된 baseline cap 복구를 시도하고, 미확인 상태를 안전 종료로 기록하지 않는다. 실제 SDK 설정 호출·합성 bus 회귀의 범위는 [검증 기록](../../../docs/validation/omx-paired-recording-2026-10-23/result.md)을 본다. 실물 보정·정지·카메라 시간 및 작업 성공 수용은 별도다.

`record_session.py`로 녹화를 마친 뒤에는 현장 PC에서 `python record_seal.py --session-dir <녹화를 실행한 폴더> --name <새 이름>`을 실행한다. 이 명령은 안전 종료(`safe_end`)·녹화 모드·종료 코드 0인 세션만 받는다. 1팔(`omx_follower`)·2팔(`bi_omx_follower`) LeRobot v3 데이터셋을 `~/rosy-test/omx-collections/<이름>/`에 해시 목록과 함께 복사하고, 원본 녹화는 건드리지 않는다. 그다음 개발 PC에서 `python tools/remote/omx_collection_transfer.py --session <이름>`으로 모델 PC의 `~/rosy-test/omx-il-data/collections/`에 옮긴다. 이 단계는 장치를 움직이지 않고 Hub에 올리지 않는다.

## 재현 가능한 Pilot SIM 준비

코드 위치·Gazebo/Isaac 선택·upstream 차이는 [조사와 계획](../../../docs/plans/2026-10-14-omx-simulation-preparation.md)에 있다.
새 `compose.pilot-sim.yaml`은 hardware 서비스와 독립된 SIM 전용 입력이다.
serial 변수 없이 해석할 수 있고 Pilot의 기존 서버·world·단일 owner를 사용한다.
이 절차의 새 이미지 build와 live 실행은 아직 미확인이다.

**실행 위치:** 노트북에서는 설정 검사만 한다. Gazebo는 D-568/D-571에 따라
`python tools/remote/remote_sim.py --check`로 비현장 PC의 여유를 확인하고,
`python tools/remote/remote_pytest.py --pick sim`으로 예약한 호스트에서만 실행한다.
출력된 host가 현장 PC이거나 `~/rosy-jobs/site`가 있으면 중단한다.
아래 Pilot 구성은 8 CPU/8 GiB 상한이다. placement의 6 CPU 최소 통과만으로
충분하다고 간주하지 말고 다른 작업의 예약을 뺀 8 CPU/8 GiB 여유를 확인한다.
공유 호스트에는 임의로 ROS/Docker를 설치하지 않는다.

이미지 build는 먼저 별도 준비한다. Compose 서비스의 CPU·메모리 상한은 **build에는
적용되지 않는다**. 아래 build 명령은 전체 자원을 독점 예약한 비현장 빌드 호스트에서만
실행한다. 공유 모델/AI PC의 SIM 8 CPU/8 GiB 예약으로 build하지 않는다. 전용 builder가
없으면 이미지 build를 보류한다. 이미지가 다른 PC에 있으면 `docker save`/`docker load`로
전달하고 source lock·패치와 이미지 ID를 대조한다. 이 절차는 registry에 push하지 않는다.

```bash
# On the dedicated build host, from the clean committed checkout:
export ROSY_SIM_SOURCE_REVISION="$(git rev-parse HEAD)"
export COMPOSE_PROJECT_NAME="rosy-omx-sim-$(date +%s)-$$"
omx_compose=deploy/robot/omx/compose.pilot-sim.yaml
docker compose -f "$omx_compose" build vendor &&
docker compose -f "$omx_compose" build pilot
docker image inspect "$COMPOSE_PROJECT_NAME-pilot:local" --format '{{.Id}}'
```

선택한 SIM Linux 호스트의 `~/rosy-test` 아래에 같은 clean committed checkout과
이미지를 준비하고 **위와 같은 COMPOSE_PROJECT_NAME**을 export한다.
그 checkout의 루트에서 전용 터미널로 실행한다. 이 터미널을 닫으면 자기 project만
내리고, 녹화 volume은 남긴다. 기존 작업의 컨테이너를 재시작하거나 종료하지 않는다.

```bash
test ! -e "$HOME/rosy-jobs/site" || exit 1
test -z "$(git status --porcelain)" || exit 1
export ROSY_SIM_SOURCE_REVISION="$(git rev-parse HEAD)"
: "${COMPOSE_PROJECT_NAME:?set the project name used to build the images}"
mkdir -p "$HOME/rosy-jobs" "$HOME/rosy-test/omx-evidence/$COMPOSE_PROJECT_NAME"
omx_out="$HOME/rosy-test/omx-evidence/$COMPOSE_PROJECT_NAME"
omx_lock="$HOME/rosy-jobs/$COMPOSE_PROJECT_NAME.lock"
printf '%s sim 8 8\n' "$$" > "$omx_lock"
omx_compose=deploy/robot/omx/compose.pilot-sim.yaml
cleanup_omx() {
  docker compose -p "$COMPOSE_PROJECT_NAME" -f "$omx_compose" down
  rm -f -- "$omx_lock"
}
trap cleanup_omx EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
set -e -o pipefail
docker compose -f "$omx_compose" config --format json > "$omx_out/compose.json"
docker image inspect "$COMPOSE_PROJECT_NAME-pilot:local" > "$omx_out/pilot-image.json"
docker compose -f "$omx_compose" up -d --no-build --pull never pilot
docker compose -f "$omx_compose" images --format json > "$omx_out/images.json"
docker compose -f "$omx_compose" ps --format json > "$omx_out/containers.json"
docker compose -f "$omx_compose" logs -f pilot | tee "$omx_out/pilot.txt"
```

`down`에 `-v`를 붙이지 않는다. project별 recording volume을 보존한다.
장시간 unattended 실행기는 아니며 터미널·자원 lock의 소유자가 실행 종료를 확인한다.
`remote_sim.py cmd`의 systemd scope는 Docker daemon 자원/수명을 소유하지 않으므로
이 Compose를 그 안에 넣었다는 이유만으로 종료·자원 회수가 보장된다고 판단하지 않는다.

두 번째 터미널도 같은 checkout 루트에서 **위와 같은 project 이름·source SHA·포트**를 설정한다. 기본 HTTP 포트 8088은
기존 probe와 일치한다. 다른 SIM이 이미 사용하면 이를 중단하지 말고 이번 작업을
미루거나 `OMX_PILOT_PORT`를 바꾸되 아래 기존 host probe는 8088 전용임을 유의한다.

```bash
export COMPOSE_PROJECT_NAME=<the-project-name-from-the-first-terminal>
export ROSY_SIM_SOURCE_REVISION="$(git rev-parse HEAD)"
export OMX_PILOT_PORT=8088
omx_compose=deploy/robot/omx/compose.pilot-sim.yaml
omx_container="$(docker compose -f "$omx_compose" ps -q pilot)"
test -n "$omx_container"
python3 deploy/robot/omx/probe_pilot_sim_http.py "$omx_container"
# Each probe consumes the one-time pairing code; start a fresh server for recording.
docker compose -f "$omx_compose" restart pilot
# Wait for the server startup message in the first terminal, then:
python3 deploy/robot/omx/probe_pilot_recording.py "$omx_container"
```

녹화 probe는 기존 조작 probe와 같은 관절 이동·목표 오차 검사를 사용한다.
ROS 성공 응답만으로 시연을 성공 처리하지 않는다. 상태 충돌은 새 상태와 요청 ID로
한 번만 재시도하며, 조종권 갱신 실패나 갱신 worker 종료 불명은 실패로 끝난다.
의도적 lease 만료 시험은 진행 중 갱신 요청의 종료와 오류 확인 뒤에 시작한다.
컨테이너 안에서는 `python3 /repo/deploy/robot/omx/probe_pilot_recording.py --inside`로
같은 probe를 실행할 수 있다. 이 경우 Docker CLI 대신 로컬 pairing code 파일을 읽는다.

각 probe의 stdout/stderr와 exit code를 위 evidence 경로에 보존한다. 실패하면
그대로 기록하고 영상 fps·state skew·owner 검사를 느슨하게 바꾸지 않는다.
녹화 probe의 complete episode와 lease expiry로 생긴 incomplete episode를 구분한다.
`SUCCEEDED`와 실제 joint readback을 함께 보고, 녹화는 frame 수·issues·원본 영상까지
확인한다. incomplete를 학습에 넣지 않는다.

수동 연습은 다시 서버를 restart한 뒤 컨테이너의
`/run/rosy-omx-pilot/pairing-code`를 로컬 CLI로 읽어 `/pilot`에서 페어링한다.
원격 PC일 때는 개발 PC에서 `ssh -N -L 8088:127.0.0.1:8088 <selected-sim-host>`로
터널을 만들고 `http://127.0.0.1:8088/pilot`에 접속한다. 코드는 로그에 저장하지 않는다.
각 관절 조작·그리퍼·영상 확인 후 Pilot 녹화 시작/종료로 시연을 남긴다.

export 전에 자기 컨테이너를 stop해 녹화를 닫고, `docker cp`로 `/recordings/.`를
새 evidence 디렉터리에 복사한다. 다음은 선택한 **complete** 원본 하나의 예다.
`LEROBOT_PYTHON`은 별도 Python 3.12/LeRobot 0.4.4 CPU 환경이며 ROS 환경이 아니다.

```bash
export PYTHONPATH="$PWD/middleware/devices/omx/adapter:$PWD/contracts/foundation"
"$LEROBOT_PYTHON" learning/curation/omx/lerobot_export.py \
  <complete-episode-directory> <new-export-directory> --repo-id rosy-local/omx-sim
```

`rosy_export.json`의 `status=verified`와 reader frame 수를 확인한다.
여러 task/초기 상태에서 수집하고 episode 단위 train/eval을 나눈 뒤
[ACT 학습 안내](../../../learning/training/omx/README.md)를 따른다. 이 SIM export는
`omx_sim_ros`/rad이며 native `omx_follower` 데이터와 혼합하지 않는다.
Hub 업로드는 [기존 registry 도구](../../../learning/registry/policy/README.md)의
검토된 파일·private repo·고정 SHA readback 절차를 따른다. Compose는 upload나
HF 인증을 하지 않는다. 실제 정책의 Gazebo 집기·실물 운용은 별도 검증이다.

## SIM 도달 과제: 자동 교사 → batch export → ACT

과제 파일 `rosy.omx-sim-reach-task.v1`(JSON, 검증기 `sim_reach_task.py`, 예시
`sim/reach_task.example.json`)은 "seed로 뽑은 임의 시작 자세에서 고정 목표 관절 자세 도달"이다.
물체 없음, 그리퍼는 검사·명령하지 않는다(`tolerance_rad`/`target_positions`/범위가 null).
필드: `schema`, `task_id`, `joint_names`(녹화 순서), `target_positions`, `tolerance_rad`,
`start_sampling{seed, ranges}`(episode k = seed + k), `max_steps`, `jog_step_rad`(≤0.05),
`jog_duration_s`(하나의 값, act_job.py의 단일 duration 조건). 목표·범위는 cell profile 한계를
`start_state_tolerance_rad`만큼 줄인 Pilot 제공 범위 안이어야 한다. 예시는 spawn 자세 근처
(joint2 뒤로, TCP 높이 전 범위 ≥0.08 m, 반경 ≥0.175 m, FK 격자 검사)이며 Gazebo 충돌 검사는
아직 하지 않았다.

`sim_reach_teacher.py`는 Pilot HTTP만 쓴다(ROS import 없음, 코드·토큰 미출력). episode마다
녹화 없이 시작 자세로 reset → 녹화 시작 → 오차/허용오차가 가장 큰 관절을 `jog_step_rad` 이하로
greedy jog(각 goal SUCCEEDED + readback 0.01 rad 확인) → 10 frame 꼬리 → 최종 joint readback과
목표 비교로 `task_outcome` success/failure(judge `sim_joint_readback`)를 보내 녹화를 닫는다.
실패한 goal은 재시도하지 않고 failure로 닫은 뒤 실행을 끝낸다(exit 2). 조종권은 0.8 s마다
갱신하고, 갱신 오류는 결과를 보내기 전에 실행을 끝낸다. 결과 파일
`rosy.omx-sim-reach-teacher-results.v1`(episode별 seed, 시작 목표/readback, 최종 관절, 오차,
success, 녹화 id/status/issues)은 evaluator의 teacher baseline이다.

위 Pilot 컨테이너가 준비된 SIM 호스트의 두 번째 터미널에서(새 서버, 사용하지 않은 pairing code):

```bash
python3 deploy/robot/omx/sim_reach_teacher.py "$omx_container" \
  --task deploy/robot/omx/sim/reach_task.example.json --episodes 12 \
  --out "$omx_out/teacher-results.json" --port "$OMX_PILOT_PORT"
docker cp "$omx_container:/recordings/." "$omx_out/recordings"
"$LEROBOT_PYTHON" learning/curation/omx/sim_batch_export.py \
  --results "$omx_out/teacher-results.json" --recordings "$omx_out/recordings" \
  --out "$omx_out/batch" --python "$LEROBOT_PYTHON"
"$LEROBOT_PYTHON" learning/training/omx/act_job.py \
  $(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["act_job_args"]))' \
    "$omx_out/batch/batch-manifest.json") --out "$omx_out/act" --steps 400
```

batch export는 teacher success이면서 녹화 complete·issues 없음·`task_outcome=success`·과제
관절 순서·모든 행 `jog_duration_s`·같은 world/calibration/camera/fps/limits인 episode만
`lerobot_export.py` CLI로 하나씩 export하고, 나머지는 `refused`에 이유와 함께 남긴다
(frame_gap/skew로 incomplete가 된 녹화 포함; 보간·재라벨 없음). eval은 export된 episode 중 seed가
가장 큰 것, 나머지가 train이다. train 2개 + eval 1개 미만이면 `status=insufficient`, exit 2.

한 번에: `python3 tools/sim/run_sim_reach_pipeline.py --task deploy/robot/omx/sim/reach_task.example.json
--episodes 12 --run "$omx_out/run" --container "$omx_container" --lerobot-python "$LEROBOT_PYTHON"
--steps 400` (`--dry-run`으로 명령만 출력, `--from-stage`로 재개). train 뒤 서버를 restart하고
`learning/evaluation/omx/sim_closed_loop.py`(held-out episode index N부터)와 `sim_reach_eval.py`를
경로로 부른다. 없으면 skip 메시지를 출력한다. 이 모두는 SIM 연구 증거이며 승격·실물 근거가 아니다.

### Read-only startup register review

The same `register_probe.py` READ(0,147) snapshot now includes pending goal
position/current, profile velocity/acceleration, current/PWM limits, position PID
and signed bus watchdog state (-1 is the documented watchdog fault).
XL430 model 1060 has no current-control registers; those fields stay null.
These are register observations, not accepted mechanical limits or stop evidence.

The inspected Fleet LeRobot `OmxFollower.connect(calibrate=False)` still calls
`configure()`, whose `torque_disabled()` context enables torque in `finally`.
Do not use that method as a passive preflight. The installed-source inspection,
actual torque-off snapshots and remaining initialization requirements are recorded
in [the startup validation](../../../docs/validation/omx-native-startup-2026-10-16.md).

### Local camera and commissioning feedback viewer

After sourcing the camera ROS environment and selecting its ROS domain, run
`python3 deploy/robot/omx/commissioning_view.py`. The read-only tool binds to
`127.0.0.1:8766`; an authenticated SSH forward can expose that same loopback port
on the development PC. It subscribes to existing top/front images and the
commissioning joint topic, opens no devices, and issues no actuator commands.
Source/receipt age, decoded picture expiry and disconnected joint feedback are
checked independently. See the [observation evidence](../../../docs/validation/omx-observation-web-2026-10-16.md).

### Prepare an initialization-description candidate

```bash
python3 deploy/robot/omx/preserved_description.py expanded.urdf new-candidate-directory
```

This offline command removes explicit GPIO initialization register parameters,
sets torque/reboot selection to zero and preserves declared metadata/interfaces.
It creates a new directory with description.urdf and receipt.json, refusing an
existing output. It never starts hardware. The pinned driver still has activation
writes and write services; this candidate does not prove a read-only driver or
accepted physical runtime. See [evidence and remaining checks](../../../docs/validation/omx-preserved-description-2026-10-16.md).

### Driver lifecycle error and owner-boundary patches

The development Dockerfile applies `hardware-lifecycle-errors.patch` and
`hardware-owner-command-path.patch` to the locked driver before compilation.
Startup rejects failed initial command writes and exhausted torque enable retries.
Failed activation attempts disable both motor groups and keep ERROR even if cleanup
fails. Stop attempts both groups and reports disable failures. Direct register,
reboot and torque command services are omitted; the read service remains.

The locked-source compiled-method check runs on a lab host with g++ and patch:
pass `ROSY_OMX_VENDOR_ROOT=<locked-checkout-relative-to-host-home>` before
`test/test_omx_driver_lifecycle.py` in the remote pytest arguments. Without an
explicit source checkout this hardware-free integration check skips. It compiles
actual vendor method bodies with communication doubles and never opens a device.
A passing result proves error propagation, not physical stopping or safe load retention.
See [validation and remaining checks](../../../docs/validation/omx-driver-lifecycle-2026-10-16.md).

`hardware-export-dependencies.patch` also exports the driver's public CMake
dependencies `std_srvs` and `realtime_tools`, allowing downstream consumers to
link its installed target. A real ROS initialization probe rejected a fixed
nonexistent port and destructed normally; it never used a real serial port.
See [native initialization evidence](../../../docs/validation/omx-native-init-negative-2026-10-16/result.md).

`hardware-init-no-reboot.patch` additionally removes the hidden InitDxlComm fault
reboot while preserving its error return. GPIO Reboot=0 alone did not cover it.
The temporary Linux `probe_exclusive_open.cpp` helper checks the literal
`ROSY_OMX_PROBE_PORT`, independently measured decimal `ROSY_OMX_PROBE_DEVICE_ID`,
kernel exclusivity and sole fuser ownership before returning the SDK descriptor.
It requires a non-root account; ordinary file opens use SYS_openat to avoid a
loader-lock deadlock during ROS library constructors. It is for a bounded native
probe, with pre/post snapshots and packet evidence, and is not an actuator runtime.
The loaded driver must be bound to the patched artifact under the actual child
environment. See [the actual passive-read result and failed attempts](../../../docs/validation/omx-native-passive-read-2026-10-16/result.md).

`hardware-write-errors.patch` rejects unhealthy pre-status and propagates buffered
or multiwrite failures immediately. `hardware-fault-stop.patch` connects error and
shutdown callbacks to the existing stop implementation; a fault remains terminal
even after cleanup succeeds. The installed framework calls on_error directly on
write failure, so on_deactivate alone did not provide that stop attempt.
The native consumer probe and inherited-callback negative control are recorded in
[the write/fault validation](../../../docs/validation/omx-cyclic-write-fault-2026-10-16/result.md).
These changes establish error propagation and software cleanup attempts; physical
stopping, load retention and hardware owner admission still require actual evidence.

`hardware-torque-uncertainty.patch` retains uncertain ON/OFF attempts until an
acknowledged result, so lost enable acknowledgments cannot suppress cleanup.
`hardware-status-readback.patch` requires exactly one Torque Enable and Hardware
Error Status state interface per motor before opening the bus. The candidate
generator adds these read interfaces and rejects ambiguous names. Read failures
or invalid fields return ERROR immediately; publication uses successful physical
reads instead of command caches or default zero/off values. Legacy descriptions
without those fields require migration. Native PTY rejection and torque-off read
evidence, including an unresolved one-tick goal-register change that failed the
preservation check, are recorded in [measured-status validation](../../../docs/validation/omx-measured-status-2026-10-16/result.md).

### Torque-off commissioning limits

`commissioning_limits.py` is a separate exclusive configuration procedure. It
requires the confirmed follower, six known motors, existing modes and torque/error
zero. An explicit JSON input supplies positive raw PWM/current/profile caps. Only
non-increasing supported caps may change, with durable original/intent records,
one exact unicast write, acknowledgment and full readback before each next write.
It never writes goals, torque, modes or offsets and never retries or rolls back an
uncertain result. Existing output directories are refused.

PWM and Current Limit writes persist in EEPROM; originals remain in the journal
and successful lower caps stay installed. RAM profiles require fresh readback
after restart. The tool does not authorize activation or establish physical limits.
See [actual configuration, tests and remaining work](../../../docs/validation/omx-bounded-commissioning-2026-10-16/result.md).

A bounded native controller probe additionally loaded the actual state broadcaster
and six-joint trajectory controller with all torque selections zero. The current
owner received real encoder states and rejected a stale command into HOLD before
dispatch. Controller-specific `params_file` forwarding is required on the installed
framework; generated ROS parameter YAML must avoid aliases. This establishes the
torque-off feedback path, while operational admission and powered stopping remain
unaccepted. See [execution and preserved failures](../../../docs/validation/omx-native-controller-feedback-2026-10-16/result.md).

### Stop-only commissioning fallback

`commissioning_stop.py` requires the confirmed by-id path, its expected device
identity, an explicit subset of follower IDs, and an output directory. The native
controller must release the serial device first. The helper acquires exclusive
ownership, checks the opened device identity, and permits only one exact
Torque Enable=0 write per selected motor. It attempts the remaining selected
motors after an individual failure, never retries an uncertain write, and then
reads all six motors. Clean success requires acknowledged writes, selected
motors OFF/error-free, successful port cleanup, and a durable receipt.

Stop attempts precede output creation so a full filesystem cannot suppress them.
An existing record is preserved; recording failure makes the invocation fail.
The helper cannot write ON, goals, modes, offsets, reboot or EEPROM settings.
`stop_verified` describes the selected motors' electrical readback; it does not
prove standstill or load support. The tool does not open the operational profile.

An isolated transient systemd probe killed the native main process with all
torque selections zero. `KillMode=control-group` released the controller's port
before an independent `ExecStopPost` invoked the helper for the gripper. Actual
OFF acknowledgment and all-six OFF/error-free readback passed. This verifies
process-death handover while unpowered; a powered stop remains unverified.
See [source, tests and actual stop-only execution](../../../docs/validation/omx-independent-stop-2026-10-16/result.md).
## Environment-aware camera readiness

`rosy-omx-camera-view.service` subscribes to the existing camera topics and serves
the original frames and their quality on localhost port8767. It opens no camera
device. `rosy-omx-camera-readiness.service` reads that viewer and adjusts only
V4L2 controls of the already selected, single-owner camera devices.

Copy `camera-readiness.json.example` to the private
`~/.config/rosy/omx-camera-readiness.json`, replacing both identities with the
existing camera configuration's persistent paths. The candidates are examples
for the measured cameras, not universal camera defaults. The tuner checks the
actual control ranges. Put `ROSY_CAMERA_PIPELINE_ROOT=<absolute-source-directory>`
in `~/.config/rosy/omx-camera-readiness.env`; that directory must contain
`commissioning_view.py`, `camera_quality.py`, `camera_environment.py`, and `camera_readiness.py` from the
same revision. Keep the existing two preview environment files and producers.

Install the two user units in `~/.config/systemd/user/`, then run:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rosy-omx-camera-readiness.service
```

The readiness unit starts the read-only viewer and its existing preview
dependencies. It writes baseline, attempted/applied settings and a current
`readiness.json` under `~/.local/state/rosy/omx-camera-environment/`. Control writes
start only after durable originals, measured control-range checks, and fresh
advancing frames. Candidates settle before assessment. Both cameras require
three confirmations; the receipt expires after750ms. A consumer must check the
expiry, profile hash and current policy as well as `photometric_ready`.

The web view shows brightness/contrast status on each frame. Use an SSH localhost
forward to port8767; do not expose it publicly. An `INSUFFICIENT` assessment is a
valid automatic outcome, not permission to ignore missing scene information.
Bright gain noise can still pass a simple photometric screen; independent object,
jaw clearance, calibration and motion-owner checks remain necessary.

`systemctl --user stop rosy-omx-camera-readiness.service` restores the original
camera controls. Both process cleanup and independent `ExecStopPost` attempt
restoration. A changed profile requires a new state directory after confirming
restoration; never delete a baseline to suppress a mismatch. Failure stops the
tuner (`Restart=no`); inspect `restoration.json` and device/producer identity
before restarting. Preview capture remains owned by the original producers.

Policy v3 distinguishes normal, underexposed, overexposed, mixed lighting,
low contrast and low spatial signal. The recovery state machine debounces both
entry and exit over three advancing samples. Separate `candidates` (dark) and
`bright_candidates` (overexposure) allow sustained dark-to-bright-to-dark recovery.
Mixed lighting and missing structure do not trigger blind gain increases.
Temporal brightness changes hold recovery; this is not a power-frequency flicker detector.

Each confirmed condition starts an environment epoch. Best controls and exhausted
candidates belong to that epoch. Settings require readback, a1s host-receive
settling boundary, and5s cooldown measured after application completes. This
does not establish sensor exposure synchronization. Recovery attempts, including
partial failures and best selection, reserve a persistent budget before writes:
six batches per minute across the two cameras. Budget exhaustion waits; clock
rollback or invalid records stop recovery. Final baseline restoration is exempt.

`environment.jsonl` retains state transitions with run/profile identity,
environment epoch and control generation. This is an observation history, not a
completed binding to collected episodes or training manifests. Preserve the old
v2 `omx-camera-readiness/` baseline when upgrading to v3's new state directory;
stop/restore the old tuner before changing the profile, sources or unit.

Repeated polls of the exact same still-fresh frame/quality are `WAITING_FRAME`.
They preserve distinct-frame confirmations without counting or refreshing READY,
temporal samples or controls. Real expiry, backwards identity or contradictory
quality resets confirmation. Poll frequency is not an assumed camera frame rate.

The broader operating envelope, ownership and remaining dataset/evaluation
contracts are in the [environment plan](../../../docs/plans/2026-10-17-omx-environment-readiness.md).

Actual camera-only execution and deployment evidence:
[2026-10-16 record](../../../docs/validation/omx-lowlight-automation-2026-10-16/result.md).
Environment v3 execution and migration:
[2026-10-17 record](../../../docs/validation/omx-environment-readiness-2026-10-17/result.md).


## 다음 날 실물 수집 준비

`collection_cli.py`가 기존 native ROS owner를 사용하는 bounded teacher 수집과
장치에 연결하지 않는6개 `rehearsal-suite`를 제공한다. disabled profile/teacher/acceptance 예시,
독립 환경·owner 감시, 원본 시각·RGB·reference·native event 보존과 비활성 systemd unit을 포함한다.
실측 수용 뒤 check→preflight→첫1회 수집→검증 전송→사람 검토→모델 PC 학습을 진행한다.
[실행 절차](../../../docs/plans/2026-10-17-omx-next-day-collection.md)와
[소프트웨어 검증·양쪽 PC 배치](../../../docs/validation/omx-next-day-collection-2026-10-17/result.md)를 따른다.
예시 값과 모의 실행은 물리 수용이나 실제 데이터가 아니다.
