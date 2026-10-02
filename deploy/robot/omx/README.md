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

기본 실행은 joint1 조그, 속도에 맞춘 그리퍼 절대 목표(readback + 0.02 rad), 닫기 뒤 열기, 명시 취소를 확인한다. `--stall` 은 D-411 C "쥐고 있음"의 **차단 ROS-SIM 관문**이다: 그리퍼를 열고, 제한 조그로 위에서 내려다보는 집기 자세(기본 x 0.18 m, TCP 높이 `--grasp-z` 0.015 m)로 간 뒤, 손가락 사이에 동적 정육면체(`--cube-size` 0.025 m, `gz service .../create`)를 만들고 닫는다. 끝 상태·ROS 결과 코드·끝까지 걸린 시간·그리퍼 readback·마지막 0.5 s 관절별 최고 속도를 `stall_probe=` JSON 한 줄로 남기고, 쥐고 있음이면 joint1 조그 세 번(각각 SUCCEEDED, 상태 유지)을 확인한다. 통과 0, 미통과 2, 오류 1. 정육면체 크기·집기 높이·컨트롤러 `goal_time`·`stopped_velocity_tolerance`(SIM 패치)는 명목값이며 이 probe 결과로 조정한다. 컨트롤러 목표 판정은 Gazebo 전용 파일 `open_manipulator_bringup/config/omx_f_follower_ai/gazebo_arm_controller_constraints.yaml`(`omx-ai-sim-gates.patch`가 만들고 Gazebo launch 의 `arm_controller` spawner 만 `--param-file` 로 읽는다)에 있고, native launch 가 읽는 `hardware_controller_manager.yaml` 에는 없다. **패치는 이미지 빌드 때 적용되므로 이 값을 바꾸거나 처음 받으려면 이미지를 다시 빌드해야 한다** — 2026-10-03 첫 stall 관문은 이전 이미지에 yaml 을 bind-mount 해서 돌렸다(`X:\DevTemp\d411-simC`). gz 서비스는 컨테이너 안에서 `/opt/ros/jazzy/setup.bash` 를 source 한 bash 로 부른다.

고정 SDF 작업대 카메라는 headless OGRE2로 실제 RGB 320×240 영상을 10 simulation FPS로 만든다. 이 영상·과거 관절 상태·ROS가 수락한 목표를 Pilot의 시연 기록 패널로 저장한다. Linux 볼륨을 사용한다. Windows 공유 폴더에 프레임을 직접 쓰면 ROS callback/기록이 지연될 수 있으며 프레임 누락·신선도 실패로 불완전해진다. writer는 별도 스레드이고 조작의 0.5초 신선도 검사는 그대로다. 초기 headless renderer 준비를 위해 vendor broadcaster의 switch-timeout만 60초로 고정하며 실행 중 watchdog은 바꾸지 않는다.

### 기록과 오프라인 변환

- Pilot에서 과제를 입력하고 기록 시작 → 관절 조작 → 과제 결과(성공/실패) 선택 → 기록 종료.
- 과제 결과 미선택·영상 누락·HOLD·취소·lease 만료/반납은 incomplete다. 이런 원본은 export를 거부한다.
- pairing code와 토큰은 export하지 않는다. 원본 manifest/JSONL/PNG는 학습 데이터이므로 로컬에 보관한다.
- 실제 자동 확인: python deploy/robot/omx/probe_pilot_recording.py rosy-omx-pilot-sim.
  성공 기록과 lease 만료에 의한 불완전 기록을 검사하고 코드/토큰은 출력하지 않는다.
- 원본 가져오기: docker cp rosy-omx-pilot-sim:/recordings/<episode-id> X:/DevTemp/rosy-omx-recordings/.
  Windows 자료·export 출력은 X:에 둔다. 컨테이너를 삭제해도 이름 있는 recording volume은 유지된다.

별도 Python 3.12 CPU 환경에 torch 2.7.1+cpu / torchvision 0.22.1+cpu를 공식 CPU wheel index로 먼저 설치하고 requirements-lerobot-export.txt를 설치한다. 실제 검증한 transitive inventory는 검증 문서에 기록한다. ROS 런타임에 LeRobot을 설치하지 않는다.

PowerShell 실행 예:

```powershell
$env:PYTHONPATH = (Get-Location).Path + '/src/products/omx/adapter'
X:/DevTemp/rosy-omx-lerobot-044/Scripts/python.exe -m omx_adapter.lerobot_export `
  X:/DevTemp/rosy-omx-recordings/<episode-id> X:/DevTemp/rosy-omx-export/<new-output> `
  --repo-id rosy-local/omx-sim
```

export 결과가 verified이고 실제 reader가 모든 frame을 재독출한 경우에만 데이터셋 연계 검증이다. 원본 복사와 해시는 rosy_provenance에 남는다. robot_type=omx_sim_ros, ROS joint 순서와 rad를 유지한다. native OMX follower의 body normalization/degree·gripper 0~100으로 자동 변환하지 않는다. 학습·정책 실행·Hub 업로드·실물 활성화는 별도다.
