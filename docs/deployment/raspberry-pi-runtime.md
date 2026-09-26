# Raspberry Pi 5 Robot Runtime

> **Runtime model — native, not Docker (D-161, D-197, D-246).**
> The product runtime is Ubuntu Server 24.04 arm64 + native ROS 2 Jazzy under
> systemd. `rosy-runtime.target` starts CORE; I/O and navigation are explicit,
> commissioned modes. **Docker and Compose are development/CI tooling only** and
> are not installed in the product image — every `docker compose` command in this
> document belongs to that development path, not to the product boot path.
> Per-device variation is expressed with profiles and slices; one robot is never
> switched between two runtime mechanisms. A container sidecar is admitted only
> for a profile-declared workload outside the safety plan (vision/AI), and only
> while every safety gate below still passes with the container runtime absent.

For the first physical Pinky Pro connection, use the ordered, evidence-bound
[G0-G5 commissioning runbook](pinky-pro-first-device-runbook.md). This runtime
reference does not replace its E-stop, lifted-wheel, or physical HOLD gates.

**Target:** Raspberry Pi 5 8GB, Raspberry Pi OS Lite 64-bit, ROSY Phase 1

유선 LAN 없이 SD 카드를 굽고 Wi-Fi로 설치·접속하는 전체 절차는
[Rosy Raspberry Pi 5 Wi-Fi 배포 가이드](raspberry-pi-wifi-image.md)를 먼저
따른다. 이 문서는 하드웨어 런타임과 물리 승인 항목을 상세히 설명한다.

Pinky Pro is the first board. Mode-specific capability overlays and the
commissioning order are in
[Pinky Pro board support](pinky-pro-board-support.md).

This deployment keeps Raspberry Pi OS as the host for the **development/CI
Compose path** and runs the ROS 2 Jazzy userland in isolated containers. The
product path is native — see the runtime model above. In both, `rosy-core` owns
the FastAPI/rclpy middleware
and has no device access. `rosy-motor` owns only the motor bus for commissioning,
while `rosy-io` owns the Pinky Pro motor, LiDAR, and Nav2 adapters in full hardware mode.

> This first runtime slice does not yet package the wiringPi/ws2811 based IMU,
> ADC, LCD, LED, or lamp nodes. Those drivers need a separate Raspberry Pi 5
> compatibility port and physical verification before device access is added.
> The robot-side image also omits the 32 MB visualization meshes; an operator
> workstation that runs RViz should keep the full `description` package.

## 1. Safety boundary

`core` publishes the final `cmd_vel`. `bringup` consumes it and
controls the Dynamixel bus. The driver-side command deadman requests zero RPM
after a 500 ms stale-command threshold and keeps retrying until the driver
accepts the stop. The 30 Hz polling loop adds up to about 34 ms plus serial and
scheduler latency, which must be measured on the Pi. This check is inside
`rosy-io`, so it still runs when FastAPI, `rosy-core`, or DDS fails.

The software deadman is not a safety-certified stop. A hazardous deployment
still needs a hardware E-stop and, where the risk assessment requires it, an
independent controller/watchdog outside the Raspberry Pi.

## 2. Host preparation

1. Follow the [Wi-Fi deployment guide](raspberry-pi-wifi-image.md) to flash
   Raspberry Pi OS Lite 64-bit, configure SSH/Wi-Fi, and run the versioned
   installer. The installer owns `/opt/rosy` as `root:root`; do not change that
   tree to the login user's ownership because systemd executes its runtime
   wrapper as root.
2. Configure the Pi 5 UART4 overlay and reboot. The script does not start the
   motor runtime:

   ```bash
   sudo /opt/rosy/deploy/robot/configure-uart-pi5.sh
   sudo reboot
   ```

   `/dev/ttyAMA4` uses GPIO12/GPIO13. Raspberry Pi UART pins are 3.3 V only;
   use the robot's verified DYNAMIXEL half-duplex interface and never connect
   a 5 V bus signal directly to a GPIO pin. Disable any login console assigned
   to the motor UART.
3. Verify the real device nodes; do not assume numbering from another Pi:

   ```bash
   ls -l /dev/ttyAMA0 /dev/ttyAMA4
   getent group dialout
   id rosy
   ```

The installer creates `/etc/rosy/rosy.yaml` with device-local tokens and mode
`0640`, preserving and revalidating it on later runs. Do not copy the example
configuration over that file. Retrieve the one-time credential handoff as
described in the Wi-Fi guide.

## 3. Runtime configuration

Edit the installer-managed environment as root:

```bash
sudoedit /opt/rosy/deploy/robot/.env
```

Set the actual UART paths and image pins in `.env`. **Do not set the identity
by hand on a fresh unit** — run the installer with `ROSY_ROBOT_NUMBER=<n>` and it
derives `ROS_DOMAIN_ID = 40 + n` and `ROSY_NAMESPACE = rosy_%02d` for you (D-33).
The installer refuses to run without that variable, and refuses to silently
change a unit that is already commissioned as a different number. The installer manages service UID/GID, `ROSY_DATA_PATH`,
`dialout` GID, file ownership, and the safe `ROSY_RUNTIME_MODE=core` default.
Do not use `privileged: true`. `rosy-motor` receives only the motor UART;
`rosy-io` receives the motor and LiDAR UARTs.

`ROSY_NAMESPACE` is also applied to the core TF frame prefix, so topics and
frames stay aligned. The mounted hardware profile advertises motor, encoder, LiDAR, teleop, and
Nav2 goal/return-home. IMU, battery, SLAM, and swarm remain disabled until
those runtimes are packaged and physically accepted. Nav2 still needs a site
map and localization check before it is a field motion path.

For a released robot, replace development image tags with immutable image
digests that were built and accepted for the exact source revision.

### ROS domain isolation and graph visibility

DDNS and ROS DDS domains solve different problems. DDNS gives the dashboard a
stable hostname when an IP address changes. `ROS_DOMAIN_ID` controls which ROS 2
participants discover each other. A DDNS name must never be used as a substitute
for a per-robot DDS domain assignment.

Keep a small deployment registry with one unique `ROS_DOMAIN_ID` and
`ROSY_NAMESPACE` per robot. Both come from one robot number: `ROS_DOMAIN_ID =
40 + N` and `ROSY_NAMESPACE = rosy_%02d`. Linux deployments use domain IDs `0`
through `101`; Rosy rejects values outside that commissioning range, which caps
the robot number at **61**. The number must also be plain decimal with **no leading
zero** — `03` is refused rather than read, because shell arithmetic treats a leading
zero as octal and would derive domain 43 for `03` but domain 48 for `010` (D-33).

#### Commissioning a new unit

```bash
sudo ROSY_ROBOT_NUMBER=3 /opt/rosy/deploy/robot/install-pi.sh
```

The installer writes `ROSY_ROBOT_NUMBER=3`, `ROS_DOMAIN_ID=43` and
`ROSY_NAMESPACE=rosy_03` into `.env` only if they are not already set. Omitting
`ROSY_ROBOT_NUMBER` is a hard failure, not a default — a default is what once
shipped every unit as 42/`rosy_01`.

#### Renumbering a unit that is already commissioned

Re-running the installer with a different number **fails on purpose**, naming both
the existing and the derived value, so a live robot is never renumbered mid-mission.
To renumber deliberately:

1. Stop the runtime: `sudo /opt/rosy/deploy/robot/runtime-mode.sh down`
2. Edit all three keys together — they must stay consistent:
   ```bash
   sudo sed -i 's/^ROSY_ROBOT_NUMBER=.*/ROSY_ROBOT_NUMBER=3/' /opt/rosy/deploy/robot/.env
   sudo sed -i 's/^ROS_DOMAIN_ID=.*/ROS_DOMAIN_ID=43/' /opt/rosy/deploy/robot/.env
   sudo sed -i 's/^ROSY_NAMESPACE=.*/ROSY_NAMESPACE=rosy_03/' /opt/rosy/deploy/robot/.env
   ```
3. Start it again: `sudo /opt/rosy/deploy/robot/runtime-mode.sh up`
4. Confirm the graph moved: `ros2 node list` from another unit must no longer see it.
5. Update the deployment registry.

A unit upgraded from a pre-D-33 release keeps whatever `.env` it already had — it
neither breaks nor self-corrects. `ros2 node list` showing two robots on the same
namespace is the symptom; this procedure is the fix. The bundled CycloneDDS
profile binds discovery to `lo`, so the core and I/O containers on one Pi can
communicate while Wi-Fi peers cannot join the DDS graph. Browser and fleet
clients use FastAPI instead.

The dashboard communication panel reports the configured domain, expected
namespace, loopback isolation, discovered node/topic counts, and a bounded
node-topic map. It warns on duplicate fully-qualified node names, nodes outside
the expected namespace, an invalid domain, or a network-visible DDS profile.
These are collision indicators rather than proof of a remote robot. If a warning
appears, stop motion, compare the device with the deployment registry, correct
`.env`, and restart the complete Rosy runtime so every container receives the
same values.

RX/TX charts are aggregate non-loopback host traffic sampled from
`/proc/net/dev`; they are useful for detecting a busy link but are not per-topic
DDS bandwidth measurements.

### Motor command contract

`bringup.motor_control.MotorController` is the single command boundary
between ROS `cmd_vel` and the two-wheel DYNAMIXEL write. Every call returns one
of four statuses:

| Status | Meaning |
|---|---|
| `APPLIED` | The requested command was valid and the driver accepted it |
| `LIMITED` | The driver accepted a bounded command; the reason and applied twist are logged |
| `REJECTED` | The input was non-numeric, NaN, or infinite; no motion write was attempted |
| `DRIVER_ERROR` | The UART/driver rejected the wheel-RPM transaction |

The planner limits translation and rotation first, then scales both wheels by
the same ratio if either wheel would exceed the RPM ceiling. This preserves the
requested curvature. The DYNAMIXEL driver independently enforces the wheel RPM
ceiling, so bypassing the planner cannot send an excessive direct command.

Configure the conservative commissioning bounds in `.env`:

```dotenv
ROSY_MAX_LINEAR_MPS=0.25
ROSY_MAX_ANGULAR_RPS=2.5
ROSY_MAX_WHEEL_RPM=100.0
ROSY_MOTOR_PROFILE_ACCELERATION=200
```

`ROSY_MOTOR_PROFILE_ACCELERATION` is the raw DYNAMIXEL Profile Acceleration
register value, accepted only from 1 through 32767. It is not an SI acceleration
measurement. Tune it only on the lifted-wheel bench and record the accepted
value for the exact motor model and load.

## 4. Build and start (development/CI Compose path)

> The commands below drive `docker compose`. They are the bench/CI path
> (D-197 1·4항: development and CI only). On a product robot the equivalent is
> `systemctl start rosy-runtime.target` with `deploy/robot/native/` units — no
> Docker daemon, no compose.

Keep `ROSY_RUNTIME_MODE=core` until the UART read-only preflight passes. It
checks the Pi model, `uart4-pi5`, serial-console conflicts, device node, IDs,
and drive-torque state without issuing a movement command:

```bash
cd /opt/rosy/deploy/robot
sudo ./verify-motors.sh
sudo docker compose --env-file .env --profile motor build rosy-motor
sudoedit /opt/rosy/deploy/robot/.env
# Set ROSY_RUNTIME_MODE=motor, save, then:
sudo systemctl restart rosy-runtime.service
sudo docker compose --env-file .env --profile motor ps
sudo docker compose --env-file .env logs --tail 100 rosy-core rosy-motor
```

After motor-only physical acceptance, build the hardware profile and change
`ROSY_RUNTIME_MODE=hardware` to add LiDAR and Nav2. Put the site occupancy
YAML and image in `/var/lib/rosy/maps/` as `site.yaml`. If that pair is
missing, Nav2 loads the packaged demo map; do not treat demo-map goals as
accepted field motion.

The installer already installs boot-time supervision. Verify it after the
interactive checks:

```bash
systemctl is-enabled rosy-runtime.service
systemctl status rosy-runtime.service
```

Docker restart policies own container restarts. The systemd unit owns only the
whole Compose application lifecycle; it must not also restart individual
containers.

## 5. Rosy OS dashboard

Open the dashboard from a machine on the robot network:

```text
http://<raspberry-pi-ip>:8080/dashboard
```

Enter a configured viewer, operator, or administrator API token. The token is
stored only in the browser tab's `sessionStorage`; closing the tab removes it.
Viewer can inspect all dashboard status and trigger the safety stop, operator
can also change robot mode, and only administrator can release an emergency
stop. API authorization remains authoritative even if a UI control is visible.

The dashboard reads host telemetry through these bounded read-only mounts:
`/proc/{uptime,loadavg,stat,meminfo}`, `/sys/class/thermal`, its sysfs target
`/sys/devices/virtual/thermal`, `/etc/os-release`, and `/etc/hostname`. It does not mount the host root,
Docker socket, systemd control socket, or any additional device. Missing host
files appear as unavailable fields instead of failing `rosy-core`.

Mode changes require confirmation in the dashboard and are serialized while a
request is in flight. The NAV button is disabled when
`navigation.goal_navigation` is unavailable (`core` and `motor`); `hardware`
advertises it because Nav2 is launched. The API enforces the same gate.
Navigation velocity samples expire after 500 ms, so changing modes cannot
reactivate an old motion sample.

For bench commissioning, operator selects `MANUAL`, confirms that the wheels
are lifted and hardware power cut is reachable, and holds a direction button.
The dashboard sends 0.05 m/s translation or 0.35 rad/s rotation at 10 Hz only
while held. Release, pointer cancellation/leave, page hide, focus loss, and
network errors request zero immediately; the core and driver watchdogs remain
the authoritative fallback.

Useful checks:

```bash
curl http://127.0.0.1:8080/dashboard
curl -H 'Authorization: Bearer <viewer-token>' \
  http://127.0.0.1:8080/api/v1/system/runtime
```

Do not place tokens in shell history on production equipment; the commands
above are diagnostic examples. Use a protected environment or interactive
prompt when collecting real evidence.

## 6. Physical acceptance gates

Run tests with the wheels lifted before any floor test.

| Gate | Procedure | Pass evidence |
|---|---|---|
| Configuration | `docker compose --profile motor config` | core plus motor service; only `rosy-motor` has one device; neither is privileged |
| WLAN peer | run `verify-from-windows.ps1` on another Wi-Fi client | Pi `wlan0` IPv4 serves `/api/v1` and `/dashboard` |
| UART preflight | run `verify-motors.sh` while runtime is core-only | IDs 1 and 2 respond at 1 Mbps and report drive torque disabled. A refusal naming `docker compose` is a configuration fault, not a hardware one — the script fails closed when it cannot tell whether the motor runtime is down |
| Core health | query `/api/v1` and authenticated `/api/v1/robot/state` | healthy container; state stream at least 5 Hz |
| Dashboard | open `/dashboard`, authenticate, then inspect `/api/v1/system/runtime` | UI loads without external assets; Pi OS/CPU/RAM/disk/temp values agree with host commands or are explicitly unavailable |
| Motor command | send a bounded low-speed command | expected wheel direction and RPM |
| Command limits | request each axis above its configured limit | log reports `LIMITED`; both wheel RPM values remain at or below the ceiling and preserve curvature |
| Invalid command | inject NaN/infinity in a test publisher | log reports `REJECTED`; immediate zero is attempted and no invalid UART write occurs |
| Encoder rollover | replay values across signed 32-bit rollover | odometry advances by the small wrapped delta without a pose jump |
| Driver deadman | stop `rosy-core` while wheels turn | measured stop latency is recorded and meets the site safety requirement; expected software threshold is 500 ms plus poll/serial latency |
| DDS loss | temporarily give `rosy-core` a different domain | `rosy-io` stops the motors within the timeout |
| I/O failure | stop `rosy-io` while wheels turn | orderly shutdown sends zero RPM and disables torque |
| Abrupt failure | kill `rosy-io` with `SIGKILL` | hardware E-stop/controller prevents persistent motion; otherwise HOLD |
| UART removal | disconnect each test adapter safely | no uncontrolled motion; error is visible and restart is bounded |
| Boot recovery | reboot the Pi | both services return; no motion before a fresh command |
| API latency | measure normal-load requests | p95 internal processing target at or below 100 ms |
| Thermal/resource | run navigation workload for 30 minutes | state at least 5 Hz; no sustained thermal throttling; record CPU/RAM/temp |
| Storage | inspect Docker and journal growth after endurance run | local log rotation active; projected SD-card use is acceptable |

The deployment gate remains **HOLD** until the physical deadman, abrupt-failure,
UART, boot, thermal, and storage rows have recorded device evidence.

## 7. Device readback evidence

After installation, reboot, or release activation, collect the device-owned
readback before changing the runtime mode:

```bash
sudo /opt/rosy/deploy/robot/verify/device-readback.sh --json \
  | sudo tee /var/lib/rosy/events/device-readback-$(date -u +%Y%m%dT%H%M%SZ).json
```

The JSON records the Pi OS identity, robot number/domain/namespace, activation
record, release git revision, immutable container digests, signed checksum
verification result, systemd/core health, ROS node list, and the observed
`cmd_vel` publisher count. It deliberately omits the installer environment and
API credentials. `gates.device_runtime` is `GO` only when the ARM64 identity,
manifest, verified signature, healthy core, and graph checks all pass.
`gates.field` remains `HOLD` until the physical commissioning table has
evidence. A readback is attached to the release evidence; it is not a
substitute for ARM64 registry publication or motor/camera/OMX acceptance.

## 8. Stop and rollback

```bash
cd /opt/rosy/deploy/robot
sudo ./runtime-mode.sh down
```

For an image rollback, set `ROSY_CORE_IMAGE` and `ROSY_IO_IMAGE` to the last
accepted digests, run `docker compose pull`, then start the hardware profile.
Never roll back the robot configuration or waypoint data implicitly with the
container image.
