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

### Passive policy contact diagnostic

The native study kind `pick-place-policy-contact` requires `--approve-study` and
uses the existing policy, command owner and task judge. It adds receive-only
cube/table contact sensors without changing collision geometry or physics.
`policy-contacts.json` preserves published collision pairs, stamps and wrenches;
silence means unknown, not contact absence. Invalid data, truncated capture,
observer/bridge loss or failed cleanup keeps the diagnostic on HOLD.
The opt-in `test/test_omx_sim_contacts_ros.py` checks the installed SDK without
spawning a robot. It does not establish policy success or hardware acceptance.

The contact diagnostic also records `policy-articulation.json` from the instance's
existing JointState topic: seven original joint positions, optional velocities,
source stamps and monotonic receipt times, sampled at most every10ms. Invalid
messages and truncation remain sticky. Before homing and again before policy
launch, the observer must be alive with clean state and a source-stamp advance
received within500ms; a frozen source stamp cannot refresh readiness. Closure
verifies and hashes both artifacts. Sampled state does not guarantee continuous
pose coverage. The SDK test's seven-joint publisher is explicitly synthetic;
actual event geometry still requires producer, clock, frame and time brackets.

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
the requested 1..300 seconds. It writes nominal vendor radians at up to 10 Hz
to native local snapshots keyed by `/omx_commissioning/joint_states`.
The gripper value is an angle, not a measured jaw width. Homing Offset is already
included in Present Position and is not applied a second time.

Every published sample requires the six ordered, matching motor models, torque
off, no hardware errors, and a read window of at most 250 ms. A failed sample
ends the process without publishing that sample; exit 2 also covers cleanup or
early termination. Timestamp is the start of the read, not delivery time.
Private JSONL stdout contains the raw snapshots. Normal duration completion is
exit 0. A controller must not consume this uncalibrated commissioning topic.

The process starts no ROS or DDS communication (D-901). The old `--domain-id`
argument is accepted but unused. Local snapshots trust the same user; they are
not an authorization boundary against privileged processes.
It has no Action server, subscription or register-write path, never
enables torque and never reconnects automatically. Stop it before any subsequent
accepted controller takes the port. It is physical feedback preparation, not an
operational arm control server or mechanical calibration acceptance.
Use the [hardware control plan](../../../docs/plans/2026-10-15-omx-hardware-control.md)
for the remaining native runtime and physical acceptance work.

## Local camera preview recovery

`omx_adapter/camera_source.py` reads an explicitly selected `/dev/v4l/by-id/`
camera through V4L2 MJPEG at 640×480, capturing at most `--max-fps` (default
10 Hz, `ROSY_CAMERA_MAX_FPS` in the unit env) with a one-image buffer. It refuses raw-format fallback, reopens failed capture, and notifies the
`rosy-omx-camera@.service` watchdog so a blocked driver read is restarted.
It measures quality on original pixels, encodes JPEG once and atomically replaces
one native snapshot with its host-receive timestamp; it publishes no ROS Image or CameraInfo.
these previews do not admit an arm operation.

Install the reviewed source snapshot and user unit on the camera host. Each
`~/.config/rosy/omx-camera-<name>.env` binds `ROSY_CAMERA_SOURCE`,
`ROSY_CAMERA_DEVICE`, `ROSY_CAMERA_TOPIC` and `ROSY_CAMERA_FRAME`
to that host's accepted runtime and selected camera. `ROSY_CAMERA_TOPIC` is now
only an opaque local registration key. Native camera, viewer, passive observer and
bridge units use the same `%t/rosy-observations` runtime directory without ROS setup
or DDS. A standalone process must set the same `ROSY_OBSERVATION_DIR` explicitly
to share these unit snapshots; otherwise it uses its private state directory.
Another machine reads `commissioning_view.py`'s loopback HTTP/JPEG
through an SSH localhost forward, or the WebRTC media path once it lands. Keep device identities and
host paths in private configuration. Stop the previous producer for that exact
camera before starting the unit, and verify advancing fresh frames and measured
format after start. Arm drivers and their admission profiles remain separate.

The camera needs OpenCV's `cv2` (`python3-opencv`), NumPy, `core_common` and
the deployed `camera_quality` helper. Native units set their source import paths;
they do not require `rclpy`, `sensor_msgs` or `cv_bridge`. The optional standalone
preview is not provisioned by the disabled adapter profile or workstation image.
For boot activation, enable the user units and verify `loginctl show-user
<camera-user> -p Linger` reports `Linger=yes`. A unit active during login alone
does not prove boot activation. Capture buffer size must read back as one;
host-receive stamps do not measure sensor exposure age. Test actual USB
unplug/replug and cold boot on site before accepting unattended operation.

### Historical DDS preview receiver check (before D-901)

The receiver tuning below records the old transport. D-901 native units do not
use Fast DDS or `camera-view-receive.xml`. A DDS-only collection/simulator adapter
must not be attached to the native camera expecting ROS frames. Stop its existing
device owner and select an explicitly validated native input before use.

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

`record_session.py`는 단일 팔과 `bi_omx_follower`/`bi_omx_leader` 양팔 설정을 받는다. 양팔은 서로 다른 네 개의 영구 serial 경로·장치 ID를 지정하고, 카메라는 follower 부모 설정에만 둔다. 각 자식 follower는 빈 `cameras`와 `use_degrees=false`를 사용한다. `dataset.video`는 생략하거나 `true`로 둔다. LeRobot 0.4.4의 녹화 경로는 `false`일 때 RGB 필드를 제외하므로 설정 검사에서 거부한다. 기존 설정 검사 뒤 `Session.command()`가 원본을 보존한 native 설정을 만들고, 구체적인 자식 OMX 설정의 `type` 태그를 SDK 진입 전에 제거한다.

native runner는 보정된 passive leader·follower를 확인하고 현재 자세에서 seed한 뒤 최대 1도/초로 모든 12관절을 전달한다. 데이터의 action은 실제 보낸 값이며, 한 팔의 상태 지연·추종 오차·지속 부하·열/전압 오류가 발생하면 양쪽 leader와 follower 모두 torque OFF를 시도한다. 부모 세션은 오류가 난 장치도 확인 가능한 정상 통신 응답에 한해 OFF와 검증된 baseline cap 복구를 시도하고, 미확인 상태를 안전 종료로 기록하지 않는다. [설정·bus 회귀](../../../docs/validation/omx-paired-recording-2026-10-23/result.md)와 [실제 SDK 녹화 루프·RGB 재읽기](../../../docs/validation/omx-paired-sdk-record-loop-2026-10-23/result.md)의 검증 범위를 본다. 후자는 합성 장치를 사용하며 실물 보정·정지·카메라 시간 및 작업 성공 수용은 별도다.

`record_session.py`로 녹화를 마친 뒤에는 현장 PC에서 `python record_seal.py --session-dir <녹화를 실행한 폴더> --name <새 이름>`을 실행한다. 이 명령은 안전 종료(`safe_end`)·녹화 모드·종료 코드 0인 세션만 받는다. 1팔(`omx_follower`)·2팔(`bi_omx_follower`) LeRobot v3 데이터셋을 `~/rosy-test/omx-collections/<이름>/`에 해시 목록과 함께 복사하고, 원본 녹화는 건드리지 않는다. 그다음 개발 PC에서 `python tools/remote/omx_collection_transfer.py --session <이름>`으로 모델 PC의 `~/rosy-test/omx-il-data/collections/`에 옮긴다. 이 단계는 장치를 움직이지 않고 Hub에 올리지 않는다.
`record_session.py`로 녹화를 마친 뒤에는 현장 PC에서 `python record_seal.py --session-dir <녹화를 실행한 폴더> --name <새 이름> --rig-revision <작업대 배치 이름> --calibration <사용한 보정 JSON>...`을 실행한다. 이름이 세션 ID가 되고 Episode마다 독립 사이클 ID가 붙는다(D-848). 이 명령은 안전 종료(`safe_end`)·녹화 모드·종료 코드 0인 세션만 받는다. 1팔(`omx_follower`)·2팔(`bi_omx_follower`) LeRobot v3 데이터셋을 `~/rosy-test/omx-collections/<이름>/`에 해시 목록과 함께 복사하고, 원본 녹화는 건드리지 않는다. 그다음 개발 PC에서 `python tools/remote/omx_collection_transfer.py --session <이름>`으로 모델 PC의 `~/rosy-test/omx-il-data/collections/`에 옮긴다. 이 단계는 장치를 움직이지 않고 Hub에 올리지 않는다.

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

With `contracts/foundation` on `PYTHONPATH`, run
`python3 deploy/robot/omx/commissioning_view.py`. The read-only tool binds to
`127.0.0.1:8766`; an authenticated SSH forward can expose that same loopback port
on the development PC. It reads existing top/front and commissioning joint
snapshot channels, opens no devices, and issues no actuator commands.
Source/receipt age, decoded picture expiry and disconnected joint feedback are
checked independently. See the [observation evidence](../../../docs/validation/omx-observation-web-2026-10-16.md).

For two followers, run one bounded `hardware_observer.py` process per confirmed
USB serial, with separate `--joint-topic /omx_commissioning/arm_a/joint_states`
and `--joint-topic /omx_commissioning/arm_b/joint_states`. Both retain exclusive
serial access, torque-OFF checks and the duration limit. Names such as `arm_a`
are diagnostic labels; they do not assign physical left/right or calibration.
The viewer reads both streams and three cameras (topic-shaped keys do not start ROS):

```bash
python3 deploy/robot/omx/commissioning_view.py \
  --arm-topic arm_a=/omx_commissioning/arm_a/joint_states \
  --arm-topic arm_b=/omx_commissioning/arm_b/joint_states \
  --camera-topic top=/top_camera/image_raw \
  --camera-topic arm_a_wrist=/arm_a_wrist_camera/image_raw \
  --camera-topic arm_b_wrist=/front_camera/image_raw
```

Each source expires independently; one arm cannot refresh the other arm's
feedback. Shared joint names remain in separate panels. The overhead camera is
shared, with one wrist camera per follower. Cameras with duplicate USB serials
need distinct persistent USB port paths rather than their colliding `by-id`
alias. Keep an explicit device-to-topic manifest and verify the actual images
before assigning physical arm names. This viewer does not admit CORE motion.

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

### One-arm cell check before motion

`cell_check.py --follower <by-id> --leader <by-id>` reads the follower through
`register_probe.py` and the camera readiness state, writes nothing, and prints one
JSON verdict. Each failed check names its fix: a missing board, a busy bus, torque
or a hardware error, voltage out of range, caps left raised (`commissioning_limits.py
--baseline`), or camera readiness not READY. The leader is checked for presence only.
Run it before `joint_tune.py` or `record_session.py`.

### Torque-off commissioning limits

`commissioning_limits.py` is a separate exclusive configuration procedure. It
requires the confirmed follower, six known motors, existing modes and torque/error
zero. An explicit JSON input supplies positive raw PWM/current/profile caps;
`--baseline` supplies the resting caps (PWM 20, Current 50, profiles 1) that
`joint_tune.py` and `record_session.py` require when an earlier session left them raised. Only
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
existing camera configuration's persistent paths. When a role's camera is opened
by a preview unit with another instance name, set that role's `"unit"` (for arm S's
gripper camera in the `front` slot: `"unit": "arm_a_wrist"`); the tuner then checks
`rosy-omx-camera@arm_a_wrist` as the sole owner. The candidates are examples
for the measured cameras, not universal camera defaults. The tuner checks the
actual control ranges. Put `ROSY_CAMERA_PIPELINE_ROOT=<absolute-source-directory>`
in `~/.config/rosy/omx-camera-readiness.env`; that directory must contain
`commissioning_view.py`, `camera_quality.py`, `camera_environment.py`, `camera_readiness.py` and
`camera-view-receive.xml` from the same revision. Use a release directory such as
`~/.local/share/rosy/omx-camera-pipeline/releases/<full sha>/`, not a `~/rosy-test` copy:
`tools/remote/update_status.py` reports a `~/rosy-test` source as `ADHOC`. The viewer loads
`camera-view-receive.xml`, a Fast DDS profile with a 4 MiB UDP receive buffer. On 2026-10-17 it
kept 236 of 236 top/front samples fresh (maximum source age 0.107 s) without any device command.
Keep the existing two preview environment files and producers.

Viewer label-to-source overrides belong in the optional private
`~/.config/rosy/omx-camera-view.env`, rather than an `ExecStart` drop-in. For a
front view supplied by the arm S wrist producer, keep the existing source keys:

```ini
ROSY_VIEW_ARGS="--camera-topic top=/top_camera/image_raw --camera-topic front=/arm_a_wrist_camera/image_raw"
```

These are native snapshot keys (D-901). Arguments are whitespace-separated;
use plain labels and keys without spaces or shell glob characters. Keep the
file mode 0600. Back up the environment and drop-in, wait until no recording or
chunk owner is running, then move the overriding drop-in out of systemd's
directory, install the matching release unit, reload and restart the viewer.
Check advancing fresh top/front frames before restarting readiness. A host on
an older unit without this optional environment file must keep its working
drop-in until the updated unit is deployed.

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

## Native 리더·팔로워 수동 조작과 시연 녹화

실물 USB가 연결된 호스트에서 `record_session.py`를 사용한다. 현재 장치와
일치하는 보정 파일, 별도의 저장 경로, 실제 카메라를 지정한 private 설정을
준비하고 `record_config.py`로 형식을 확인한다. 설정 검사만으로 물리적 준비가
확인되는 것은 아니다. 리더는 사람이 움직이는 수동 상태로 사용한다.

```sh
python deploy/robot/omx/record_config.py /private/record-config.json
python deploy/robot/omx/record_session.py \
  --config /private/record-config.json --caps /private/caps.json --teleop-only
# 시연 녹화는 같은 명령에서 --teleop-only를 뺀다.
```

두 경로 모두 `guarded_native.py`를 실행한다. 연결 중 토크를 켜거나 보정값을
자동으로 덮어쓰지 않는다. 본체 관절은 실제 raw 위치를 읽고, 시작 시 한 번
정한 회전수 차이를 유지한다. 목표와 현재 위치가 100° 이상 다르면 시작을
거절하거나 실행을 중단한다. 이를 무시하는 실행 옵션은 제공하지 않는다.
허용되는 시작 차이도 현재 위치를 먼저 목표로 쓴 뒤 초당 1° 이하로 줄인다.
통신·샘플 간격·범위 오류는 조작을 중단한다. 녹화 action에는 제한 후 실제로
명령한 값을 남긴다.

처음에는 두 팔을 같은 자세로 놓고 팔로워 주변을 비운다. 종료는 `Ctrl+C`이며
기존 세션 도구가 토크 OFF와 출력 상한·카메라 서비스 복원을 수행한다. 토크를
끄면 팔이 처질 수 있으므로 받침을 준비하고, 팔로워 전원 스위치를 바로 끌 수
있는 위치에서 조작한다. 이 제어 루프는 별도의 하드웨어 비상정지를 대신하지 않는다.

완료한 시연의 Learning 입력은 `learning/curation/omx/native_review.py`의
`inspect --source-mode leader_native`로 시작한다. 사람 검토와 분할 뒤 ACT
학습으로 넘기는 절차는 [OMX 데이터 안내](../../../learning/curation/omx/README.md)를
따른다. 조작 연결이나 소프트웨어 시험 통과만으로 학습 데이터 품질·정책 승격을
확정하지 않는다.

### 두 리더·두 팔로워와 한 영상 녹화

동시 조작은 같은 `record_session.py`를 사용하며, 설정의 부모 타입을
`bi_omx_follower` / `bi_omx_leader`로 지정한다. 각 부모의 `arm_a`, `arm_b`에
기존 OMX 장치 설정을 넣고, 네 장치의 ID와 고정 USB 경로를 모두 다르게 둔다.
자식 팔로워의 `cameras`는 빈 객체로 두고, 카메라는 부모 로봇에서 한 번만 연다.
상단 카메라 하나로 두 팔을 함께 촬영할 수 있다. `--teleop-only`를 빼면 같은
네이티브 녹화기가 관절 12개와 영상을 한 데이터셋 에피소드에 저장한다.

집게 실측 범위 보정 전에는 `--teleop-only --body-only`로 본체 다섯 관절씩만
수동 추종할 수 있다. 이 모드는 집게에 위치 명령을 보내거나 토크를 켜지 않고,
집게 토크가 OFF인지 계속 검사한다. 본체는 정상 실행 중 토크를 유지한다.
각 팔의 다섯 관절 모두 실제 위치는 현재 리더 목표의 2.5° 이내, 명령은 0.5°
이내인 상태를 0.5초 유지할 때까지 최대 1°/초로 정렬하고, 이후 최대 10°/초·명령
가속도 10°/초²로 추종한다. 정수 목표에는 모터 1틱 미만의 양자화 차이가 있다.
기존 각도·추적 오차·지연 보호는 유지한다. 집게 위치는 관측값으로만 남고,
이 모드의 녹화는 거절한다. 집게까지 추종하려면 각 장치의 실제 이동 범위를
먼저 보정해야 한다.

수동·녹화 세션은 위치 P·D·I 이득을 자동 변경하지 않는다. 명시적인 관절 튜닝과
일상 조작을 분리한다. 두 모드 모두 본체 다섯 관절의 부호 있는 PWM을 5Hz로
읽으며, 마지막 직렬 명령과 실제 위치의 오차가 2°를 넘고 실제 설정 PWM 상한의
90% 이상인 상태가 새 표본에서 1초 지속되면 양팔을 정지한다. 누락·오래된 표본은
정상으로 간주하지 않는다. body-only 시작 정렬에는 최초 허용 각도 차이/1°초 +
5초(최소 5초·최대 105초)의 고정 기한을 둔다. 리더 이동으로 기한을 연장하지 않는다.
출력 상한과 호스트 명령 제한은 실제 접촉 힘이나 정지 거리를 측정한 값이 아니다.

정상 제어는 모터 Alert를 계속 오류로 처리한다. 종료 전용 경로만 통신·명령 오류가
없는 Alert 응답을 제한적으로 읽어 OFF와 기본 캡(PWM20·해당 모델 current50)을
확인·복구한다. EEPROM 쓰기 전 장치 모델·모드·OFF를 검증하고 관절별 실패 후에도
나머지 정리를 계속한다. 하드웨어 오류와 Alert는 영수증에 보존하며 OFF·캡 복구가
확인돼도 오류가 있으면 `safe_end=false`로 남긴다. 토크 ON·목표·이득·재부팅은
이 정리 경로의 허용 쓰기가 아니다.

## 코드 구동 두팔 파이프라인 (D-846)

리더를 손에서 떼어 둔 상태에서 구동하고 팔로워가 그 상대 움직임을 따라가는
파이프라인이다. 결정과 경계는 [D-846](../../docs/adr/D-846-omx-leader-driven-two-arm-pipeline.md)다.
아래 수동 세션과 다른 경로이며, 같은 팔로워 가드·정지 규칙·캡 복구를 그대로 쓴다.

```sh
# 설정은 private에 두고, 포즈 파일은 park 단계가 만든다.
python deploy/robot/omx/two_arm_pipeline.py --config /private/pipeline.json --stage preflight
python deploy/robot/omx/two_arm_pipeline.py --config /private/pipeline.json --stage gap
python deploy/robot/omx/two_arm_pipeline.py --config /private/pipeline.json --stage park
python deploy/robot/omx/two_arm_pipeline.py --config /private/pipeline.json --stage align
# reader를 구동하는 단계는 손을 뗀 증언이 있어야 한다.
python deploy/robot/omx/two_arm_pipeline.py --config /private/pipeline.json --stage drive \
  --pose park --attest "hands-off:<누가>:<시각>"
python deploy/robot/omx/two_arm_pipeline.py --config /private/pipeline.json --stage verify
```

- 단계는 단독 실행 가능하고 결과는 `pipeline-receipts/`에 JSON 영수증으로 남는다.
- `preflight`는 팔로워·리더가 정지 상태이고 팔로워 캡이 resting baseline이며
  다른 프로세스가 버스를 잡지 않았음을 확인한다. 관측 유닛처럼 버스를 점유하는
  프로세스가 있으면 먼저 중지한다.
- `align`이 멈추면 어느 관절이 어느 PWM에서 막혔는지와 다음 행동(팔 지지 또는
  리더를 팔로워 가까이)을 함께 보고한다.
- `drive`는 리더만 구동한다. 팔로워는 자기 가드가 읽은 리더 위치만 따라가며
  파이프라인은 팔로워 목표를 직접 쓰지 않는다. 팔로워는 리더의 절대 자세가
  아니라 시작 시점 차이를 유지한 상대 움직임을 따라간다.
- 리더 구동은 팔로워 정렬 속도(1°/초)를 넘지 않고, 관절별 PWM·전류 캡 안에서
  움직이며, 하드웨어 오류나 캡 고착에서 멈춘다. 어떤 출구에서도 리더 토크를 끄고
  발견한 캡·프로파일을 되돌린다. 집게는 구동하지 않는다.
- 이 파이프라인은 독립 정지가 아니다. 팔 전원 스위치에 사람이 손을 둔다.

2026-10-22 실물 시험에서 A 어깨가 지속 부하로 오류32(과부하)를 발생시켰다.
해당 호스트의 수동 시작기는 fault marker로 차단했으며, 시험한 고출력 프로필의
양팔 현장 수용은 미완료다. 모터 부하 원인을 확인하기 전에는 재부팅으로 오류만
지우고 같은 프로필을 재실행하지 않는다. 당시 잔류 오차는 5° 정지 기준보다 작아
큰 출력을 유지했고 시작 정렬 기한·지속 출력 보호가 없었다. 이득·캡을 높이는
대응도 정렬 실패를 끝내지 못했다. A는 빠른 추종 단계로 진입하기 전에 오류가
났다. 실제 저항의 원인이 중력·하중, 접촉, 마찰, 기준점 차이 중 무엇인지는
확정하지 않았다. 0..4095 캐시는 실측 가동범위·리더/팔로워 기준점 검증을
대신하지 않는다. 새 보호의 소프트웨어 시험과 실제 부하 원인 확인·현장 재수용은
별개다. 상세 증거는 `docs/logs.md`에 남겼다.

네이티브 수동·녹화 경로는 같은 직렬 버스 소유자가 모터 건강 상태를 읽는다.
body-only는 팔마다 본체5개, 전체 모드는 집게 포함6개의 구동 관절을 감시한다.
별도 직렬 감시 프로세스를 병행하지 않는다. 시작 전 토크 OFF 상태에서 실제
온도·전압·PWM 설정 한계를 읽고 검증한다. 실행 중5Hz로 팔 이름·관절 이름·ID,
마지막 직렬 목표/현재 위치·오차, 부호 있는 PWM과 설정 상한 대비 사용률,
온도°C·입력 전압V를 기록하고1Hz로 요약을 출력한다. PWM 사용률은 실제 토크나
모터의 연속 출력 정격이 아니다. 비구동 리더의 전체 상태를 감시한다고 주장하지 않는다.

출력 사용률90% 이상은 위치 오차가 작아도 경고한다. 온도가 실제 설정 한계의
5°C 이내이면 사전 경고하며, 이 여유는 검증된 고장 예측 시간이 아니다. 실제 설정
온도 한계 도달·전압 범위 이탈은 정지 사유다. 기존 지속 출력·위치·지연 보호도
유지한다. 센서 읽기·기록 실패와 지연은 정상으로 처리하지 않고 다음 목표 전
정지한다. 이상 발생 후에는 양팔 OFF를 먼저 시도하고 마지막 표본의 시각·나이와
정지 사유를 기록한다. 마지막 정상 표본을 오류 발생 후 새로 읽은 값처럼 표시하지 않는다.

`record_session.py`는 실행마다 별도 `motor-health-*.jsonl` 경로를 자식에 전달하고
`session.json`의 `motor_health_log`와 `motor_health_log_created`에 연결한다. 자식
직접 실행도 고유 로그를 만들며 기존 파일에 이어 쓰지 않는다. 기록은100,000개로
제한하고 한도 소진 시 감시 없이 계속 실행하지 않고 정지한다. 양팔5Hz에서는
약2시간46분 분량보다 짧을 수 있으므로 장시간 작업은 기록 용량도 확인한다.
실제 감시 활성화·읽기 지연·경고에 대한 현장 수용은 별도다.
신선도 검사는 읽기·기록이 반환된 뒤 다음 명령을 거절하는 소프트웨어 보호다.
OS·통신·파일 처리가 멈춘 동안의 독립 정지 기한이나 기구적 낙하 방지를 보장하지 않는다.

지속 부하·추종 중단 발생 시 운영 순서는 다음과 같다.

1. 시작 전에 양팔의 토크가 사라져도 하중이 떨어지지 않도록 받침·기구적 지지를
   준비하고 작업 영역을 비운다. 펌웨어가 자체 OFF할 수 있으므로 사람이 오류 후
   손을 넣어 받치는 것을 낙하 방지 수단으로 삼지 않는다. 지지가 없는 상태에서
   소프트웨어 OFF만으로 안전 정지가 보장된다고 판단하지 않는다.
2. 추종이 멈추거나 출력 포화가 지속되면 리더 입력을 중단한다. 기존 보호는 양쪽
   명령을 중단하고 토크 OFF를 시도한다. 새 목표로 재시도하거나 이득·캡을 자동으로
   올리지 않는다. OFF 요청과 실제 읽기 확인을 구분한다. 확인 불가 시 접근을
   제한하고 작업자가 설치된 전원 차단 수단으로 격리한다.
3. 장치 이름·시각·명령/현재 위치·PWM/캡·하드웨어 오류·종료 영수증을 보존한다.
   온도·전압은 수동 진단값과 측정 시각을 함께 남긴다. 오류32와 과열 오류는
   구분하며, 낮은 온도 한 번만 보고 정상 판정하지 않는다. 해당 녹화는 중단
   자료로 분리하고 성공 시연으로 사용하지 않는다.
4. 전원을 격리하고 하중을 지지한 상태에서 장치 식별·회전 방향·기준점·실측
   가동범위, 장착·케이블·마찰·외부 하중을 점검한다. 각도가 이미 맞는데도 큰
   출력을 요구한다면 정적 부하를 먼저 낮춘다. 속도만 낮추거나 이득·캡을 올리는
   것을 부하 제거로 간주하지 않는다.
5. 원인 조치와 보정 확인 후 별도 commissioning에서 낮은 출력·작은 이동으로
   관절별 응답과 정지·OFF를 확인하고, 양팔 추종을 사람이 재수용한다. fault
   marker 해제·재부팅·재시작은 자동 수행하지 않는다. 식별·보정·부하가 미확정이면
   시작 차단을 유지한다.

현재 자동 보호는 위치 차이·신선도·시작 기한·큰 오차와 지속 PWM의 조합 및
실제 설정 온도·전압 한계 검사다.
작은 오차로 큰 정적 하중을 버티는 경우까지 연속 운전 가능하다고 보증하지 않는다.
오차와 독립적인 연속 출력 운전 예산·온도 상승 추세 기준은 실측 모터 특성과 하중으로
추가 검증해야 한다. [어깨 축소 물리 실험과 대응 근거](../../../docs/validation/omx-load-physics-2026-10-22.md)는
가정한 구동·마찰·열 계수와 실물 미확정 항목을 구분한다.

`bimanual_native.py`는 두 쌍의 보정·위치·시작 목표 검증을 모두 마친 뒤 토크를
켠다. 어느 쌍이든 오류가 나면 두 팔로워를 함께 정지한다. 부모 복구도 두
팔로워에 먼저 OFF를 시도한 뒤 장치별 재시도와 캡 복구를 수행한다. 단일 세션
락을 유지하며 별도 세션 두 개를 동시에 띄우지 않는다.

장치 이름은 `arm_a_leader`, `arm_a_follower`, `arm_b_leader`, `arm_b_follower`로
고정하고, 실제 USB 연결은 기존 `host-inventory.yaml.example` 형식의 private
inventory에 보존한다. 카메라 기준 좌우는 위치 설명이며 카메라가 바뀌어도
장치 이름을 바꾸지 않는다. 기존 보정 캐시는 장치와 일치하는 경우에만 별도
고정 ID로 참조한다. 자동 보정이나 보정값 초기화는 수행하지 않는다.

Learning 네이티브 검사와 ACT 평가 경로는 기존 단일 팔 6개 또는
`arm_a.*` 6개 다음 `arm_b.*` 6개인 정확한 양팔 순서를 허용한다. 사람 검토와
실제 장치 수용은 별도로 수행한다. 녹화 기능만으로 Learning 화면의 양팔
프로필 내보내기나 정책의 장치 실행까지 검증됐다고 보지 않는다.

설치 후 연결되는 일치 장치는 `root:plugdev`, `0660`으로 생성된다. 이미 연결된 장치는
관리자가 VID/PID를 확인한 개별 tty sysfs 경로에 `udevadm trigger --action=change <sysfs-path>`를
적용하고 `udevadm settle --timeout=10` 뒤 운영자 계정의 실제 읽기·쓰기 권한을 확인한다.
이 규칙은 리더·팔로워 역할을 지정하거나 serial 포트를 열지 않으며, 토크·관찰·제어 프로세스를
시작하지 않는다. 팔로워 by-id 식별과 단일 버스 소유권 확인은 기존 관찰·시운전 절차를 따른다.

## 검증된 native 셀 작업 범위 (D-911)

최대 도달범위·전체 경로의 계획 가능성·실물로 검증한 운용범위를 구분한다.
`cell_envelope.py`는 native 셀의 자동 파지 앞에서 마지막 항목을 검사한다.
adapter의 시뮬레이션 preflight 통과는 실물 인양 근거가 아니다.
기존 motion guard와 단일 버스 소유권은 그대로 필요하다.

첫 적용은 검증한 **동일 장치·조건·전체 library**만 허용한다. 카메라 추정이나 Z가 조금만
달라져도 다른 경로면 미검증이다. 반경 축소·좌표 반올림·높이 보간으로 이 검사를 우회하지 않는다.
공통 모델의 최대 도달거리를 모든 장치의 안전 반경으로 사용하지 않는다.

설정의 `operating_conditions`에는 확인한 `installation_revision`, `object_revision`,
실측 `payload_kg`, 세 축의 `object_dimensions_m`, `environment_revision`을 넣는다.
팔·그리퍼의 실제 설정/보정과 코드 문맥은 현재 chunk session이 별도 SHA로 보고한다.
장치 readback으로 알 수 없는 베이스·작업대 이동과 물체 교체는 운영자가 revision을 바꿔야 한다.
완성된 실물 설정과 자료는 공개 저장소에 넣지 않는다. 예제의 null은 직접 측정하기 전까지 유지한다.

현장 승인과 준비가 끝난 시험만 개별 stage로 수집한다. 아래는 사용 형식이며 자동 실행 지시가 아니다.

```bash
python deploy/robot/omx/cell_pipeline.py --config <private-cell-config.json> --stage transfer --from pinky --to belt --commissioning --person-at-switch
python deploy/robot/omx/cell_attempts.py summary <work-dir>/attempts.jsonl
```

시험은 기존 chunk session을 사용하며 별도 serial writer를 열지 않는다.
`--commissioning`은 `run` 자동 순환과 함께 쓸 수 없고 JSON에 저장해 사람의 존재를 대신할 수도 없다.
`calibrate`, `reset`, `survey`, `record`도 명시적인 감독 시험 stage다.
실제 파지·물체 이격·유지 시간·처짐·운반·배치의 기준은 시험 전에 정한다.
모터 도달, jaw current 또는 최종 배치 영상 하나만으로 모든 단계를 수용하지 않는다.

summary의 `operating_tasks`는 장치/조건/경로별 감독 시험 수, 성공 수, 관측 성공 비율과
`attempts_sha256`을 제공한다. `unreviewed`인 검토 후보이며 자동 승인 결과가 아니다.
시험 수나 성공률을 원하는 신뢰도와 동일시하지 않는다. 실패·중단을 지워 분모를 줄이지 않는다.

`cell-envelope.example.json`을 작업의 `operating_envelope_path`에 두고, 실제 물리 근거를
검토한 담당자가 해당 작업의 review 한 개를 추가한다. reviews가 비어 있으면 자동 작업은 보류한다.
review의 필드는 다음과 같다.

| 필드 | 값의 근거 |
|---|---|
| `task_sha256` | summary의 정확한 작업 key |
| `scope` | `hardware`; 시뮬레이션 시험은 hardware로 바꾸지 않음 |
| `reviewed_by`, `evidence_ref` | 검토자와 인양·유지·오차 등을 실제로 확인한 증거 참조 |
| `attempts_sha256` | summary의 같은 key에 속한 감독 시험 전체 digest |
| `min_attempts`, `min_success_rate` | 시험 전에 정한 반복·수용 기준; 기본값 없음 |
| `home_tolerance_units` | 해당 장치에서 수용한 시작 home의 몸체 관절 오차, LeRobot 정규화 단위 |

manifest의 `attempts_path`는 실제 `work_dir/attempts.jsonl`이어야 한다. 상대 경로는 manifest
디렉터리 기준이다. 같은 작업의 review를 중복으로 두지 않는다. 성공한 기록만 다른 파일로 복사해
근거로 삼거나 실패 후 과거 파일로 되돌리지 않는다. `evidence_ref`의 물리적 타당성을 소프트웨어가
판독하지 않으므로 검토 책임은 해당 기록을 승인하는 사람에게 있다.

자동 작업 전의 현재 상태·시작 home과 각 명령의 session/library를 다시 확인한다.
다른 library 로드나 수동 jog/grip/goto 개입은 자동 사슬을 무효화한다. 중간 중단 시 무조건
park나 torque-off를 새로 시도하지 않는다. 기존 guard/정지 정책과 하중 상태에 맞는 회수를 따른다.

동작 전 기록한 `attempts.pending.json`이 남으면 완료 여부가 불명확한 작업이다.
기존 검증만으로 재실행하지 말고 receipt·로그·장치와 물체 상태를 확인한다. 미완료 사실을 작업
기록에 보존하고 기존 승인된 회수 절차를 마친 뒤 담당자가 pending을 정리한다.
실제로 수행한 자동 작업이 실패한 경우도 같은 task의 기존 승인은 다시 사용하지 못한다.
원인을 해결하고 영향받은 조건 revision과 근거를 갱신해 재검증한다.

이 범위는 native 셀 자동 파지에 대한 추가 검사다. 다른 low-level 수동 도구나 Fleet 제품 경로의
활성화를 승인하지 않으며, 사람과 함께 작업하는 안전 인증이나 실물 장치 수용을 대신하지 않는다.

## Fleet PC의 상시 관측과 기존 Cell 화면

두 팔의 관절 읽기와 세 카메라의 ROS 구독은 Fleet PC에서 실행한다.
`hardware_observer.py --persistent`는 명시적으로 선택한 토크 OFF 관측이다.
기존 `--duration 1..300`은 시간 제한을 유지한다. 관측 실패·토크 ON·모터 오류가
발견되면 종료하며 `rosy-omx-observer@.service`는 자동 재시작하지 않는다.
`observer.env.example`을 팔마다 다른 by-id 장치와 commissioning 토픽에 결속한다.
이 관절값은 원시 엔코더 변환이며, 보정된 제어 좌표나 실물 구동 수용 증거가 아니다.

`workcell_observation_bridge.py`는 같은 호스트의 선택된 native snapshot만 읽는다.
manifest의 topic 문자열은 로컬 키이며 ROS 발행·구독이나 DDS discovery를 시작하지 않는다(D-901).
원본 capture 시간과 source별 최신값을 Fleet HTTPS와 기존 Vision WSS에 보낸다.
설정은 `observation-bridge.env.example`, source 결속은
`../../site/workcell-observations.yaml.example`을 참고한다. 예제 장치와 digest는
자리 표시자다. private manifest의 다섯 토큰은 서로 달라야 하며 실제 SHA-256과
일치해야 한다. 별도 로컬 뷰어나 SSH 포트 전달은 이 제품 경로에 필요하지 않다.

ROS setup은 필요하지 않다. 해당 Python의 격리 환경에서 OpenCV와 canonical
`core_common.protocol.workcell_observations`, `rosy_vision.protocol`을 확인한다.
기존 사이트 pin의 `websockets==17.0.1`, SDK `dynamixel-sdk==3.8.4`를 사용한다.
다른 Python minor 버전의 compiled site-packages를 통째로 연결하지 않는다.

서버에는 서명·검증된 `compose.workcell.yaml`이 적용된 Fleet/Vision 이미지와
역할별 private 파일이 먼저 필요하다. 정상 사이트 origin의 `/console/cell`에서
인증 후 팔별 freshness와 세 영상을 확인한다. Fleet/Vision 설정과 서명 절차는
[사이트 배포 안내](../../site/README.md)를 따른다.

**Arm S live-file 관측.** ROS가 없는 Arm S는 live/calibration/guard-health 파일을 가진 호스트에서
`rosy-omx-arm-status.service`를 쓴다. `arm-status.env.example`을
`~/.config/rosy/omx-arm-status.env`에 mode 0600으로 복사하고, Fleet manifest의
`source_id`·`arm_id`, 실제 live·calibration·canonical health 경로, HTTPS origin·CA와
해당 팔 전용 토큰을 설정한다. 빈 토큰은 시작을 거부한다. guard의
`ROSY_OMX_MONITOR_OWNER`는 같은 arm_id여야 한다. 유닛을 user systemd 경로에 복사하고
`daemon-reload` 뒤 `enable --now rosy-omx-arm-status.service`로 활성화한다.
같은 source에 기존 ROS observation bridge를 동시에 연결하지 않는다.

이 producer는 파일만 읽고 `ArmSender`로 보낸다. 보정 범위로 변환한 신선한 관절 위치와
정본 `rosy.motor-health.v1`만 사용하며, 누락된 PWM·온도·목표를 만들지 않는다.
guard terminal health는 위치 없이 한 번 보내고, live의 held fault는 terminal로 바꾸지 않는다.
live가 멈추면 위치 전송도 멈추고 Fleet이 2초 뒤 위치를 지운다. 영상은 기존 WSS producer와
Fleet 카메라 패널을 그대로 쓴다. 이 서비스는 serial bus를 열거나 명령을 내리지 않는다.

**자동 업데이트 (D-871).** 카메라, 화질 뷰어·준비 서비스, 관측기, 브리지와 Arm S live-file producer는 하나의 업데이터로 함께 움직인다. 이 업데이터는 `rosy-omx-devices-autoupdate.timer`(10분마다)이고, 쓰는 코드는 셀 도구와 같은 `omx_autoupdate.py`(`kind: service`, `idle_gate: cell`)다.

chunk 파서·transit/park 경로·motion profile의 정본은 설치 패키지의
`omx_adapter.chunk_library`와 `omx_adapter.motion_profile`이다. 기존
`chunk_runner`, `teach_trajectory`, `motion_profile` import는 같은 함수를 내보낸다.
네이티브 배포는 갱신된 예제의 `paths`와 `smoke`를 개인 설정에 반영해야 한다.
예제는 패키지의 기존 `__init__`에 필요한 최소 import 의존 파일도 포함한다.
이 변경은 버스·실행자·토크 동작을 바꾸거나 실물 수용을 뜻하지 않는다.

릴리스에서 스크립트 또는 `record_session.py --chunks`를 실행하는 환경에는
adapter **부모** 경로가 필요하다. 소스 체크아웃에서는 같은 상대 경로를 쓴다.
기존 녹화 중에는 릴리스·환경을 교체하지 않는다.

```bash
release="$HOME/.local/share/rosy/omx-devices/current"
export PYTHONPATH="$release/middleware/devices/omx/adapter:$release/contracts/foundation${PYTHONPATH:+:$PYTHONPATH}"
```

- 하는 일: CI를 통과한 main을 `~/.local/share/rosy/omx-devices/releases/<sha12>`에 푼다. `current`를 바꾸고, 이전에 돌던 유닛만 다시 띄운다.
- 바꾸는 조건: 셀이 쉴 때만 바꾼다. 셀이 쉰다는 것은 다음 셋을 모두 만족하는 것이다.
  - 세션 잠금이 없다.
  - 관측기 말고 버스를 연 프로세스가 없다.
  - 관측기 health가 모든 모터 토크 OFF를 보고한다.
- 설치:
  1. `omx-devices-autoupdate.json.example`을 `~/.config/rosy/omx-devices-autoupdate.json`에 복사한다. 이 셀의 팔 수만큼 `devices`, `observers`, `units`를 채운다. Arm S 호스트는 `rosy-omx-arm-status.service`를 `units`와 `unit_files`에 포함하고 `arm-status.env.example`의 current/current-env 경로를 유지한다. Arm S가 없는 호스트는 해당 유닛을 목록에서 뺀다.
  2. env 파일의 코드 경로를 `~/.local/share/rosy/omx-devices/current`와 `current-env`로 바꾼다(`observer.env.example`, `observation-bridge.env.example`). 카메라 env는 `ROSY_CAMERA_SOURCE=.../current/middleware/devices/omx/adapter/omx_adapter/camera_source.py`, `ROSY_CAMERA_PIPELINE_ROOT=.../current/deploy/robot/omx`로 바꾼다.
  3. SHA가 이름에 박힌 drop-in(`95-motor-health-*.conf`)을 지운다. health 파일은 이제 템플릿과 `ROSY_OBSERVATION_ARM_HEALTH`가 정한다.
  4. 첫 실행은 저장소 사본으로 `python3 deploy/robot/omx/omx_autoupdate.py --config ~/.config/rosy/omx-devices-autoupdate.json run`.
  5. 그 뒤 업데이터 유닛 두 개를 복사하고 `systemctl --user enable --now rosy-omx-devices-autoupdate.timer`.
- 관측기가 멈춰 있으면 토크 근거가 없으므로 업데이트는 `follower_torque_not_off`로 보류된다.

실제 owner로 전환할 때는 두 `rosy-omx-observer@arm_a/arm_b` 유닛을 중지하고
각 포트의 FD/버스 해제를 확인한 뒤 별도로 수용된 CORE/OMX owner만 시작한다.
관측 서비스 설치·활성화는 토크 ON, 정책 활성화, 파지 실행을 승인하지 않는다.

## 낮은 출력의 첫 관절 시운전

`joint_tune.py`는 기존 owner/controller를 정지한 뒤 사람이 지켜보며 한 관절씩 사용하는
시운전 도구다. 기본 raw 값은 PWM Limit 20, Current Limit 50(XL330), Goal Current 50,
Profile Velocity/Acceleration 1/1이다. 출력 자동 증가는 없으며 더 높은 값은 명시해야 한다.
XL430에는 Current Limit을 적용하지 않는다. 이 기본값은 `record_session.py`의 별도 cap 파일을
대신하지 않으며, 실측된 안전 토크나 힘을 뜻하지 않는다.

시간 기반 프로파일과 목표값 쓰기로 토크가 켜지는 Drive Mode를 거부한다. 설정 readback,
설정 후 현재 위치 재확인, 토크 ON 후 처짐·연속 정지 확인을 통과해야 다음 목표를 쓴다.
정지 시간 초과, 비정상 시계, 0.25초를 넘는 피드백 공백은 중단 사유다. 카메라 캡처 뒤에도
관절 상태를 다시 확인한다. 이 Python 검사와 카메라 I/O는 물리 정지의 최대 지연을 보장하지 않는다.

종료 시 토크 OFF를 readback으로 확인한 뒤에만 설정을 복원한다. 확인에 실패하면 복원을
건너뛰고 unsafe end를 보고한다. 낮은 출력이나 토크 OFF 때 하중 관절이 처질 수 있으므로
실물 첫 구동에는 관절 지지, 외부 정지 수단, 관절별 실측 수용이 필요하다.

## OpenRB USB 접근 권한

기존 `plugdev` 운영자에게 OpenRB USB serial(USB VID/PID `2f5d:2202`) 접근을 부여한다.
보드별 일회성 ACL과 달리 교체·추가·재연결에도 적용한다. 다른 USB 제품에는 적용하지 않는다.
실행 계정이 이미 `plugdev`에 속하는지 확인한 뒤 관리자가 한 번 설치한다.

```bash
id -nG
udevadm verify deploy/robot/omx/99-rosy-openrb-access.rules
sudo install -o root -g root -m 0644 deploy/robot/omx/99-rosy-openrb-access.rules /etc/udev/rules.d/99-rosy-openrb-access.rules
sudo udevadm control --reload-rules
```

설치 후 연결되는 일치 장치는 `root:plugdev`, `0660`으로 생성된다. 이미 연결된 장치는
관리자가 VID/PID를 확인한 개별 tty sysfs 경로에 `udevadm trigger --action=change <sysfs-path>`를
적용하고 `udevadm settle --timeout=10` 뒤 운영자 계정의 실제 읽기·쓰기 권한을 확인한다.
이 규칙은 리더·팔로워 역할을 지정하거나 serial 포트를 열지 않으며, 토크·관찰·제어 프로세스를
시작하지 않는다. 팔로워 by-id 식별과 단일 버스 소유권 확인은 기존 관찰·시운전 절차를 따른다.
