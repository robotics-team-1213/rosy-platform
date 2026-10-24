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

`omx_adapter/camera_source.py` reads an explicitly selected `/dev/v4l/by-id/` or `/dev/v4l/by-path/`
camera through V4L2 MJPEG at 640×480, publishing at most 10 Hz with a one-image
queue. It refuses raw-format fallback, reopens failed capture, and notifies the
`rosy-omx-camera@.service` watchdog so a blocked driver read is restarted.
It publishes host-receive timestamps and no CameraInfo or calibrated target;
these previews do not admit an arm operation.

Install the reviewed source snapshot and user unit on the camera host. Each
`~/.config/rosy/omx-camera-<name>.env` binds `ROSY_ROS_SETUP`, `ROSY_CAMERA_SOURCE`,
`ROSY_CAMERA_DEVICE`, `ROSY_CAMERA_TOPIC`, `ROSY_CAMERA_FRAME`, and `ROS_DOMAIN_ID`
to that host's accepted runtime and selected camera. Keep device identities and
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

The hardware profile takes `OMX_ROS_DOMAIN_ID` and
`OMX_ROS_AUTOMATIC_DISCOVERY_RANGE` from the Compose environment; defaults are
domain 30 and `SUBNET`. Copy `.env.example` to `.env` beside this README to set
them, then pass it with `--env-file deploy/robot/omx/.env` when running Compose from
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

기본 실행은 joint1 조그, 속도에 맞춘 그리퍼 절대 목표(readback + 0.02 rad), 닫기 뒤 열기, 명시 취소를 확인한다. `--stall` 은 D-411 C "쥐고 있음"의 **차단 ROS-SIM 관문**이다: 그리퍼를 열고, 제한 조그로 위에서 내려다보는 집기 자세(기본 x 0.18 m, TCP 높이 `--grasp-z` 0.015 m)로 간 뒤, 손가락 사이에 동적 정육면체(`--cube-size` 0.025 m, `gz service .../create`)를 만들고 닫는다. 끝 상태·ROS 결과 코드·끝까지 걸린 시간·그리퍼 readback·마지막 0.5 s 관절별 최고 속도를 `stall_probe=` JSON 한 줄로 남기고, 쥐고 있음이면 joint1 조그 세 번(각각 SUCCEEDED, 상태 유지)을 확인한다. 통과 0, 미통과 2, 오류 1. 정육면체 크기·집기 높이·컨트롤러 `goal_time`·`stopped_velocity_tolerance`(SIM 패치)는 명목값이며 이 probe 결과로 조정한다. 컨트롤러 목표 판정은 Gazebo 전용 파일 `open_manipulator_bringup/config/omx_f_follower_ai/gazebo_arm_controller_constraints.yaml`(`omx-ai-sim-gates.patch`가 만들고 Gazebo launch 의 `arm_controller` spawner 만 `--param-file` 로 읽는다)에 있고, native launch 가 읽는 `hardware_controller_manager.yaml` 에는 없다. **패치는 이미지 빌드 때 적용되므로 이 값을 바꾸거나 처음 받으려면 이미지를 다시 빌드해야 한다** — 2026-10-03 첫 stall 관문은 이전 이미지에 yaml 을 bind-mount 해서 돌렸다(`X:\DevTemp\d411-simC`). gz 서비스는 컨테이너 안에서 `/opt/ros/jazzy/setup.bash` 를 source 한 bash 로 부른다. 패치를 고친 뒤에는 다시 빌드하기 전에 `python deploy/robot/omx/check_vendor_patches.py` 로 고정 revision 의 vendor 파일에 Dockerfile 순서대로 모든 패치가 적용되고 결과 launch·YAML·xacro 가 읽히는지 본다(`test/test_omx_vendor_patch_order.py`, 오프라인이면 건너뜀). 뒤 패치는 앞 패치가 적용된 소스에 대해 만든다 — `omx-ai-sim-action-only.patch` 는 `omx-ai-sim-gates.patch` 뒤의 launch 를 기준으로 한다.

고정 SDF 작업대 카메라는 headless OGRE2로 실제 RGB 320×240 영상을 10 simulation FPS로 만든다. 이 영상·과거 관절 상태·ROS가 수락한 목표를 Pilot의 시연 기록 패널로 저장한다. Linux 볼륨을 사용한다. Windows 공유 폴더에 프레임을 직접 쓰면 ROS callback/기록이 지연될 수 있으며 프레임 누락·신선도 실패로 불완전해진다. writer는 별도 스레드이고 조작의 0.5초 신선도 검사는 그대로다. 초기 headless renderer 준비를 위해 vendor broadcaster의 switch-timeout만 60초로 고정하며 실행 중 watchdog은 바꾸지 않는다.

### 기록과 오프라인 변환

- Pilot에서 과제를 입력하고 기록 시작 → 관절 조작 → 과제 결과(성공/실패) 선택 → 기록 종료.
- 과제 결과 미선택·영상 누락·HOLD·취소·lease 만료/반납은 incomplete다. 이런 원본은 export를 거부한다.
- pairing code와 토큰은 export하지 않는다. 원본 manifest/JSONL/PNG는 학습 데이터이므로 로컬에 보관한다.
- 실제 자동 확인: python deploy/robot/omx/probe_pilot_recording.py rosy-omx-pilot-sim.
  성공 기록과 lease 만료에 의한 불완전 기록을 검사하고 코드/토큰은 출력하지 않는다.
- 원본 가져오기: docker cp rosy-omx-pilot-sim:/recordings/<episode-id> X:/DevTemp/rosy-omx-recordings/.
  Windows 자료·export 출력은 X:에 둔다. 컨테이너를 삭제해도 이름 있는 recording volume은 유지된다.

별도 Python 3.12 CPU 환경에 torch 2.10.0+cpu / torchvision 0.25.0+cpu를 공식 CPU wheel index로 먼저 설치하고 requirements-lerobot-export.txt를 설치한다. 실제 검증한 transitive inventory는 검증 문서에 기록한다. ROS 런타임에 LeRobot을 설치하지 않는다.

PowerShell 실행 예:

```powershell
$env:PYTHONPATH = (Get-Location).Path + '/middleware/devices/omx/adapter;' + (Get-Location).Path + '/contracts/foundation'
X:/DevTemp/rosy-omx-lerobot-044/Scripts/python.exe learning/curation/omx/lerobot_export.py `
  X:/DevTemp/rosy-omx-recordings/<episode-id> X:/DevTemp/rosy-omx-export/<new-output> `
  --repo-id rosy-local/omx-sim
```

export 결과가 verified이고 실제 reader가 모든 frame을 재독출한 경우에만 데이터셋 연계 검증이다. 원본 복사와 해시는 rosy_provenance에 남는다. robot_type=omx_sim_ros, ROS joint 순서와 rad를 유지한다. native OMX follower의 body normalization/degree·gripper 0~100으로 자동 변환하지 않는다. 학습·정책 실행·Hub 업로드·실물 활성화는 별도다.

## Rosy Cell C3: one CELL_TRANSFER in Gazebo (D-402)

`run_cell_sim.sh` starts the locked follower in `integrations/simulation/gazebo/worlds/omx_cell_workcell.sdf`
(or `OMX_CELL_WORLD=<path without .sdf>`) with no command owner. `probe_cell_transfer.py`,
run with `docker exec` in that container, is the single owner process for the run: profile-built
`ArmCommandOwner`, analytic planner, `PickPlaceRunner`, gripper readback and `gz model -p`
block poses (helpers in `cell_sim_tools.py`). Do not start `pilot_sim_server` beside it; the
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

For two followers, run one bounded `hardware_observer.py` process per confirmed
USB serial, with separate `--joint-topic /omx_commissioning/arm_a/joint_states`
and `--joint-topic /omx_commissioning/arm_b/joint_states`. Both retain exclusive
serial access, torque-OFF checks and the duration limit. Names such as `arm_a`
are diagnostic labels; they do not assign physical left/right or calibration.
The viewer subscribes to both streams and three cameras:

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
`commissioning_view.py`, `camera_quality.py`, `camera_environment.py`, `camera_readiness.py` and
`camera-view-receive.xml` from the same revision. Use a release directory such as
`~/.local/share/rosy/omx-camera-pipeline/releases/<full sha>/`, not a `~/rosy-test` copy:
`tools/remote/update_status.py` reports a `~/rosy-test` source as `ADHOC`. The viewer loads
`camera-view-receive.xml`, a Fast DDS profile with a 4 MiB UDP receive buffer. On 2026-10-17 it
kept 236 of 236 top/front samples fresh (maximum source age 0.107 s) without any device command.
Keep the existing two preview environment files and producers.

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

## Fleet PC의 상시 관측과 기존 Cell 화면

두 팔의 관절 읽기와 세 카메라의 ROS 구독은 Fleet PC에서 실행한다.
`hardware_observer.py --persistent`는 명시적으로 선택한 토크 OFF 관측이다.
기존 `--duration 1..300`은 시간 제한을 유지한다. 관측 실패·토크 ON·모터 오류가
발견되면 종료하며 `rosy-omx-observer@.service`는 자동 재시작하지 않는다.
`observer.env.example`을 팔마다 다른 by-id 장치와 commissioning 토픽에 결속한다.
이 관절값은 원시 엔코더 변환이며, 보정된 제어 좌표나 실물 구동 수용 증거가 아니다.

`workcell_observation_bridge.py`는 같은 호스트의 관측 토픽만 구독한다.
원본 capture 시간과 source별 최신값을 Fleet HTTPS와 기존 Vision WSS에 보낸다.
설정은 `observation-bridge.env.example`, source 결속은
`../../site/workcell-observations.yaml.example`을 참고한다. 예제 장치와 digest는
자리 표시자다. private manifest의 다섯 토큰은 서로 달라야 하며 실제 SHA-256과
일치해야 한다. 별도 로컬 뷰어나 SSH 포트 전달은 이 제품 경로에 필요하지 않다.

Python은 호스트 ROS ABI와 맞아야 한다. Jazzy setup을 먼저 source하고, 해당 Python의
격리 환경에서 시스템 `rclpy`, `sensor_msgs`, OpenCV와 canonical
`core_common.protocol.workcell_observations`, `rosy_vision.protocol`을 확인한다.
기존 사이트 pin의 `websockets==17.0.1`, SDK `dynamixel-sdk==3.8.4`를 사용한다.
다른 Python minor 버전의 compiled site-packages를 통째로 연결하지 않는다.

서버에는 서명·검증된 `compose.workcell.yaml`이 적용된 Fleet/Vision 이미지와
역할별 private 파일이 먼저 필요하다. 정상 사이트 origin의 `/console/cell`에서
인증 후 팔별 freshness와 세 영상을 확인한다. Fleet/Vision 설정과 서명 절차는
[사이트 배포 안내](../../site/README.md)를 따른다.

**자동 업데이트 (D-871).** 카메라, 화질 뷰어·준비 서비스, 관측기, 브리지는 하나의 업데이터로 함께 움직인다. 이 업데이터는 `rosy-omx-devices-autoupdate.timer`(10분마다)이고, 쓰는 코드는 셀 도구와 같은 `omx_autoupdate.py`(`kind: service`, `idle_gate: cell`)다.

- 하는 일: CI를 통과한 main을 `~/.local/share/rosy/omx-devices/releases/<sha12>`에 푼다. `current`를 바꾸고, 이전에 돌던 유닛만 다시 띄운다.
- 바꾸는 조건: 셀이 쉴 때만 바꾼다. 셀이 쉰다는 것은 다음 셋을 모두 만족하는 것이다.
  - 세션 잠금이 없다.
  - 관측기 말고 버스를 연 프로세스가 없다.
  - 관측기 health가 모든 모터 토크 OFF를 보고한다.
- 설치:
  1. `omx-devices-autoupdate.json.example`을 `~/.config/rosy/omx-devices-autoupdate.json`에 복사한다. 이 셀의 팔 수만큼 `devices`, `observers`, `units`를 채운다.
  2. env 파일의 코드 경로를 `~/.local/share/rosy/omx-devices/current`와 `current-env`로 바꾼다(`observer.env.example`, `observation-bridge.env.example`). 카메라 env는 `ROSY_CAMERA_SOURCE=.../current/middleware/devices/omx/adapter/omx_adapter/camera_source.py`, `ROSY_CAMERA_PIPELINE_ROOT=.../current/deploy/robot/omx`로 바꾼다.
  3. SHA가 이름에 박힌 drop-in(`95-motor-health-*.conf`)을 지운다. health 파일은 이제 템플릿과 `ROSY_OBSERVATION_ARM_HEALTH`가 정한다.
  4. 첫 실행은 저장소 사본으로 `python3 deploy/robot/omx/omx_autoupdate.py --config ~/.config/rosy/omx-devices-autoupdate.json run`.
  5. 그 뒤 업데이터 유닛 두 개를 복사하고 `systemctl --user enable --now rosy-omx-devices-autoupdate.timer`.
- 관측기가 멈춰 있으면 토크 근거가 없으므로 업데이트는 `follower_torque_not_off`로 보류된다.

실제 owner로 전환할 때는 두 `rosy-omx-observer@arm_a/arm_b` 유닛을 중지하고
각 포트의 FD/버스 해제를 확인한 뒤 별도로 수용된 CORE/OMX owner만 시작한다.
관측 서비스 설치·활성화는 토크 ON, 정책 활성화, 파지 실행을 승인하지 않는다.
