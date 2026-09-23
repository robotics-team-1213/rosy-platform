# Pinky Pro first-device commissioning runbook

Date: 2026-09-21
Scope: first physical connection, install, stationary proof, motor/deadman check,
LiDAR mapping, and a bounded navigation smoke test.

This is a fail-closed G0-G5 procedure. A `GO` means only that its named gate has
valid evidence. ARTIFACT, DEVICE, calibration, and FIELD stay `HOLD` until their
own physical evidence exists. Do not copy Gazebo geometry, robot diameter,
speed, stopping distance, or `map_260905_update_v2` results into a device
certificate.

## 0. Build and sign the G0 release

Do this before powering the target robot. The image build host must be a native
ARM64 Linux machine; an x86/QEMU build is development evidence only. Start from
the exact clean commit that will be commissioned and retain the builder JSON:

```bash
set -euo pipefail
test "$(uname -m)" = aarch64
test -z "$(git status --porcelain)"
RELEASE_ID=2026.09.21-001
SIGNING_KEY_ID=rosy-release-2026-01
REVISION="$(git rev-parse HEAD)"
# Copy this digest from the approved registry-manifest evidence. A mutable tag
# such as ros:jazzy-ros-base is refused.
ROS_IMAGE='ros:jazzy-ros-base@sha256:<64-hex-registry-digest>'
PAYLOAD="/var/tmp/rosy-${RELEASE_ID}-unsigned"
python3 deploy/release/arm64_release_builder.py \
  --repo-root "$PWD" --output "$PAYLOAD" --release-id "$RELEASE_ID" \
  --signing-key-id "$SIGNING_KEY_ID" --ros-image "$ROS_IMAGE" \
  | tee "/var/tmp/${RELEASE_ID}-unsigned-payload-build.json"
```

The builder creates two Docker-save archives and an unsigned manifest. It
refuses non-ARM64 images and checks that both image labels match `$REVISION`.
It never reads a private key. Transfer the complete payload and builder JSON to
the offline signing environment, then sign and verify there. The private key
must remain outside both the payload and the target robot:

When no separate native build host is available, D-145 provides the same
unsigned handoff on GitHub's native ARM64 runner. It still does not sign:

```bash
gh workflow run build-arm64-payload.yml --ref main \
  -f release_id="$RELEASE_ID" \
  -f signing_key_id="$SIGNING_KEY_ID" \
  -f ros_image="$ROS_IMAGE"
# After that exact run succeeds, download its named unsigned artifact.
gh run download RUN_ID --name "rosy-unsigned-${RELEASE_ID}-${REVISION}"
ARCHIVE="rosy-unsigned-${RELEASE_ID}-${REVISION}.tar.zst"
CHECKSUM="${ARCHIVE}.sha256"
HANDOFF="/trusted/rosy-unsigned-${RELEASE_ID}-${REVISION}"
python3 deploy/release/import_unsigned_payload.py "$ARCHIVE" \
  --checksum "$CHECKSUM" --output "$HANDOFF" \
  --release-id "$RELEASE_ID" --git-revision "$REVISION" \
  --signing-key-id "$SIGNING_KEY_ID" \
  | tee "/trusted/${RELEASE_ID}-unsigned-import.json"
PAYLOAD="$HANDOFF/rosy-unsigned-payload"
```

Retain the run URL and job result with the builder JSON. The Actions artifact
expires after seven days, so move the verified archive to the offline signing
environment before then. The importer verifies the outer checksum before
decompression, rejects unsafe archive members, and binds builder, manifest,
provenance, payload hashes, and both `linux/arm64` image configs to the expected
release identity. Its `signed: false` result is a verified handoff, not G0.

```bash
set -euo pipefail
PUBLIC_KEY="/secure/${SIGNING_KEY_ID}.pem"
PRIVATE_KEY="/secure/${SIGNING_KEY_ID}.key"
BUNDLE="/trusted/rosy-release-${RELEASE_ID}.tar.zst"
python3 deploy/release/package_release.py "$PAYLOAD" "$BUNDLE" \
  --public-key "$PUBLIC_KEY" --private-key "$PRIVATE_KEY"
python3 deploy/release/publication.py verify-publication "$BUNDLE" \
  --release-id "$RELEASE_ID" --git-revision "$REVISION" \
  --public-key "$PUBLIC_KEY" --json \
  | tee "/trusted/${RELEASE_ID}-signed-bundle-verification.json"
```

Copy the bundle, matching public key, unsigned builder JSON, and
`signed-bundle-verification.json` to trusted removable media. Do not proceed to
G0 if either JSON says `ok: false`, if the public-key filename stem differs
from the manifest `signing_key_id`, or if the source revision differs.

## 1. Prepare before power-on

- Two people for G4/G5: one operator and one person at the physical power cut.
- Wheels-off-ground stand, clear floor zone, tape measure/caliper, charger, and
  a wired LAN cable. Keep the E-stop reachable at all times.
- Raspberry Pi 5, arm64 Raspberry Pi OS Lite, camera, LiDAR, and motors must be
  mechanically secured. Do not hot-plug motor power or the CSI ribbon.
- Bring the complete calibration input file. The supplied two-photo checker
  homography marked `approximate_requires_physical_validation` is a candidate,
  not an accepted robot-frame calibration. A truncated chat copy is unusable.
- Create an evidence directory. Raw outputs are never edited after hashing:

```bash
sudo install -d -o "$USER" -g "$(id -gn)" -m 0750 /var/lib/rosy/commissioning
SESSION=/var/lib/rosy/commissioning/pinky-01-$(date -u +%Y%m%dT%H%M%SZ).json
EVIDENCE="${SESSION%.json}.evidence"
mkdir -m 0750 "$EVIDENCE"
```

## 2. Connection choice

### SSH path

Connect the Pi and workstation to the same wired LAN, find the address from the
router/DHCP lease, and pin the host key before transferring anything:

```powershell
ssh-keygen -F pinky-01.local
ssh rosy@pinky-01.local
```

If mDNS is unavailable, use the DHCP address. A changed host key is a stop
condition until the Pi identity is physically confirmed.

Verify the selected LAN before commissioning. `auto` prefers the default-route
interface; use `eth0` explicitly on the wired bench:

```bash
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh --interface eth0
```

From Windows, verify that the API and dashboard are reachable by another host:

```powershell
$ConnectionEvidence = Join-Path $PWD "G0-connection-evidence.json"
./deploy/robot/verify/verify-from-windows.ps1 `
  -PiHost pinky-01.local -NetworkInterface eth0 `
  -BatchMode -ConnectTimeoutSec 5 -EvidencePath $ConnectionEvidence
```

This command does not change network settings or robot state. A JSON `GO` is
connectivity evidence only: it proves bounded key-based SSH plus `/api/v1` and
`/dashboard` reachability over the selected interface. It is not G0 artifact
acceptance and does not advance DEVICE or FIELD. Preserve the file with the
session evidence; the verifier refuses to replace an existing evidence file.

#### One-command stationary validation from Windows

When the signed manifest revision and robot number are known, run this from the
repository root. It joins peer connectivity, API/dashboard reachability, device
readback, exact robot identity, and exact release revision into one verdict. It
does not change runtime mode or send motor commands.

```powershell
$Revision = "<signed-manifest-full-40-character-git-revision>"
$Evidence = Join-Path $PWD ("pinky-01-preflight-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
./deploy/robot/verify/validate-pinky-from-windows.ps1 `
  -PiHost pinky-01.local -PiUser rosy -NetworkInterface eth0 `
  -ExpectedRobotNumber 1 -ExpectedRevision $Revision `
  -EvidenceDirectory $Evidence
```

The directory contains raw `G0-connection.json`, `G2-device-readback.json` when
collection succeeds, final `user-validation-summary.json`, and
`SHA256SUMS.txt`. Existing evidence is never replaced. If
`summary.outcome=HOLD`, repair the named `failed_checks`. If non-interactive
`sudo` is unavailable over SSH, the tool still records HOLD evidence and the
operator switches to the Pi local-console procedure.

`GO != motion authorization`. Even a GO result keeps
`motion_authorized: false`; its next gate is `G3_SENSOR_ONLY`. Open the reported
`dashboard_url` for observation. G4 wheels-off-ground work and G5 low-speed
floor motion still require their separate physical conditions and two-person
procedure.

### Local console path

Connect a display and keyboard, sign in locally, and use the same commands
below. The session records `console`; it does not weaken any gate. Network loss
after installation is not a reason to skip readback or safety checks.

G0 stages and verifies the signed bundle before `commission-pinky.py init`, so
the session revision comes from that verified manifest. Run the evidence CLI as
the ordinary owner of `/var/lib/rosy/commissioning`, never through `sudo`; only
the release/runtime commands below need root. For the Local console path, use
`--connection console`. Never attach a password, token, credential, private
key, or `.env` file.

### Changing the site Wi-Fi on the card (D-176)

Power the robot off and put the card in a PC. The boot partition holds
`rosy-config.yaml`, a commented template written with the card. Uncomment the
`wifi:` block, set the SSID and password, save, and boot the robot. At boot
`rosy-config.service` applies the file and rewrites every password on the card
as `"<applied>"`; the Wi-Fi key stays only in the root-only NetworkManager
profile. An invalid file applies nothing: the console banner and
`rosy-diag/` on the boot partition name the error. Identity keys
(`device_name`, `hostname`, ...) are refused here; change identity by
rewriting the card with `-ReprovisionReceipt`.

### Reaching the robot through its own AP (D-176)

With no uplink for 120 s the robot opens the WPA2 AP named after the device
(`rosy-pinky-xxxx`). The password was printed once when the card was written
and is kept in the writer PC's DPAPI store
(`%LOCALAPPDATA%\Rosy\ap\<device>.credential.xml`); a local console also shows
it. Join the AP and connect with the operator key:

```powershell
ssh -i $env:LOCALAPPDATA\Rosy\ssh\rosy-operator-ed25519 rosy@10.42.0.1
```

Pi 5 has one radio, so while the AP is up the site Wi-Fi is not scanned. After
600 s the AP steps aside for another 120 s site Wi-Fi attempt. `ap.mode: relay`
keeps the AP up; `ap.mode: off` never opens it.

## 3. Record contract

For every gate, save raw output under `$EVIDENCE`. `prepare` derives G0-G2 from
the actual release/readback JSON and validates the G3-G5 operator-attested body.
`record` re-derives/rechecks the claims, hashes every supplied file, locks the
session, and appends one gate atomically:

In the examples, `python3 "$COMMISSION" record` is the installed equivalent of
the `commission-pinky.py record` operation.

```bash
COMMISSION=/opt/rosy/deploy/robot/commission-pinky.py
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" status --session "$SESSION"
```

G3-G5 use an exact body file from
[the body templates](pinky-pro-commissioning-body-templates.md). Use each gate's
exact command below: G3 requires the G2 readback plus ten individual state JSON
files, G4 requires eight distinct trial digests, and G5 requires four distinct
role-bound digests. A body file by itself is always refused.

For G3-G5, the exact body is an explicit operator attestation backed by raw
telemetry. It is not a cryptographic sensor signature. G0 is instead derived
from the verified signed manifest and `STAGED` result; G1 from the successful
activation result and device readback; G2 from the readback itself.

The record common fields are filled by `prepare`: `schema_version`, `gate`,
`captured_at`, full lowercase `source_revision`, integer `robot_number`, and
`outcome: "GO"`. A validation error leaves the session unchanged. After G1,
use `/opt/rosy/deploy/robot/commission-pinky.py`; before it, use the copy inside
the same verified release payload.

## 4. Gates

### G0 - signed native artifact

Before installation, prove the release is signed, its manifest matches the full
Git revision, the target is Raspberry Pi 5 arm64 Raspberry Pi OS Lite, and both
`rosy_core` and `rosy_io` use immutable `sha256:` image digests.

```bash
RELEASE_ID=YYYY.MM.DD-NNN
COMMISSION=/trusted/verified-release/deploy/robot/commission-pinky.py
sudo rosy-release stage "/trusted/rosy-release-${RELEASE_ID}.tar.zst" --json \
  | tee "$EVIDENCE/G0-stage.json"
sudo install -o "$USER" -g "$(id -gn)" -m 0640 \
  "/var/cache/rosy/releases/${RELEASE_ID}/manifest.json" \
  "$EVIDENCE/G0-manifest.json"
REVISION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["git_revision"])' \
  "$EVIDENCE/G0-manifest.json")"
python3 "$COMMISSION" init \
  --session "$SESSION" --robot-number 1 --source-revision "$REVISION" \
  --connection ssh --operator "OPERATOR_NAME"
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G0-record.json" \
  --evidence-file "$EVIDENCE/G0-manifest.json" \
  --evidence-file "$EVIDENCE/G0-stage.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G0-record.json" \
  --evidence-file "$EVIDENCE/G0-manifest.json" \
  --evidence-file "$EVIDENCE/G0-stage.json"
```

Stop on any signature, target, revision, or digest mismatch. A Windows source
upload and a locally built candidate do not satisfy G0.

### G1 - install, core only

Install the verified release by its release ID. The installer must finish with
exit code 0 and leave the requested robot identity in `core` mode:

```bash
sudo rosy-release runtime down
sudo rosy-release install --release-id YYYY.MM.DD-NNN --json \
  | tee "$EVIDENCE/G1-install.json"
sudo /opt/rosy/deploy/robot/runtime-mode.sh status \
  | tee "$EVIDENCE/G1-runtime-status.txt"
sudo /opt/rosy/deploy/robot/verify/device-readback.sh \
  | tee "$EVIDENCE/G2-device-readback.json"
COMMISSION=/opt/rosy/deploy/robot/commission-pinky.py
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G1-record.json" \
  --evidence-file "$EVIDENCE/G1-install.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G1-record.json" \
  --evidence-file "$EVIDENCE/G1-install.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json" \
  --evidence-file "$EVIDENCE/G1-runtime-status.txt"
```

For robot 1 the derived values are `ROS_DOMAIN_ID=41` and namespace `rosy_01`.
Never proceed if the installer quarantines the runtime or starts motor/hardware.

### G2 - immutable device readback

```bash
python3 "$COMMISSION" prepare \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G2-record.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json"
```

Record the complete JSON as the G2 `readback`. It must match the G0 revision and
both image digests, report a verified signature, active/healthy CORE, derived
identity, exactly one final `cmd_vel` publisher, and `device_runtime: GO`.

### G3 - stationary CORE proof

Keep wheels lifted and keep E-stop asserted. CORE stays in `IDLE`; do not start
motor or hardware. Capture at least 10 ordered samples over at least 2 seconds.
Every sample must report zero linear/angular velocity and `estop: true` while
the graph still has exactly one final `cmd_vel` publisher.

Create a mode-0600 curl config containing only the operator/viewer authorization
header (never place the token on the command line), then capture the server
states. The body template identifies the fields copied from these raw files:

```bash
install -d -m 0700 "$HOME/.config/rosy"
install -m 0600 /dev/null "$HOME/.config/rosy/viewer.curl"
${EDITOR:-vi} "$HOME/.config/rosy/viewer.curl"  # header = "Authorization: Bearer ..."
for n in 01 02 03 04 05 06 07 08 09 10; do
  curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
    http://127.0.0.1:8080/api/v1/robot/state \
    >"$EVIDENCE/G3-state-${n}.json" || exit 1
  sleep 0.25
done
```

Fill `$EVIDENCE/G3-stationary.json` from those ten states and the G2 publisher
count. G3 refuses the body alone; attach the G2 readback and all ten raw states:

```bash
python3 "$COMMISSION" prepare \
  --session "$SESSION" --body "$EVIDENCE/G3-stationary.json" \
  --record "$EVIDENCE/G3-record.json"
G3_ARGS=()
for path in "$EVIDENCE"/G3-state-*.json; do G3_ARGS+=(--evidence-file "$path"); done
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G3-record.json" \
  --evidence-file "$EVIDENCE/G3-stationary.json" \
  --evidence-file "$EVIDENCE/G2-device-readback.json" "${G3_ARGS[@]}"
```

If a sample moves, E-stop clears, the mode changes, or publisher count differs
from one: stop, preserve the raw output, and do not create a GO record.

### G4 - lifted-wheel motor and deadman

Hazardous gate: it is never auto-executed by `commission-pinky.py`.

```bash
install -m 0600 /dev/null "$HOME/.config/rosy/operator.curl"
install -m 0600 /dev/null "$HOME/.config/rosy/admin.curl"
${EDITOR:-vi} "$HOME/.config/rosy/operator.curl" # operator Authorization header
${EDITOR:-vi} "$HOME/.config/rosy/admin.curl"    # administrator Authorization header
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sudo /opt/rosy/deploy/robot/verify/verify-motors.sh \
  | tee "$EVIDENCE/G4-motor-preflight.txt"
sudo ROSY_RUNTIME_MODE=motor /opt/rosy/deploy/robot/runtime-mode.sh up
```

Only after the torque-free preflight passes: confirm wheels lifted, physical cut
reachable, IDs 1 and 2 both respond, then switch deliberately to motor mode.
Run two deadman trials each for forward, reverse, clockwise, and
counter-clockwise. Each command release must reach final zero velocity within
0.65 s. Any timeout, unexpected direction, vibration, runaway, or missing ID is
an immediate E-stop and power-cut condition.

For each of the eight trials, use the authenticated dashboard's momentary
manual control at the lowest configured speed. Keep E-stop asserted while
selecting the direction; the safety operator explicitly releases it only for
the trial. Record `/rosy_01/odom` with ROS timestamps while the control is held.
The second terminal records the host stop time and stops only CORE to create a
real command-loss condition (replace `forward-1` for every trial):

```bash
timeout 30 docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-motor \
  ros2 topic echo --csv /rosy_01/odom \
  >"$EVIDENCE/G4-forward-1-odom.csv" &
printf '%s stop_core forward 1\n' "$(date +%s.%N)" \
  >>"$EVIDENCE/G4-deadman-events.txt"
docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml stop --timeout 0 rosy-core
# Wait for measured odometry to reach zero; immediately press E-stop if it does not.
sudo ROSY_RUNTIME_MODE=motor /opt/rosy/deploy/robot/runtime-mode.sh up
```

Reassert E-stop before restarting CORE and before changing direction. Compute
`stop_latency_s` from the recorded `stop_core` timestamp to the first
sustained-zero odometry timestamp. Do not type a passing value from visual
estimation alone.

After the trials:

```bash
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sha256sum "$EVIDENCE"/G4-*-odom.csv >"$EVIDENCE/G4-odom-SHA256SUMS"
# Fill G4-evidence-manifest.json with all eight matching trial values and digests.
python3 "$COMMISSION" prepare \
  --session "$SESSION" --body "$EVIDENCE/G4-motor.json" \
  --record "$EVIDENCE/G4-record.json"
G4_ARGS=()
for path in "$EVIDENCE"/G4-*-odom.csv; do G4_ARGS+=(--evidence-file "$path"); done
[[ $((${#G4_ARGS[@]} / 2)) -eq 8 ]] || { echo 'need 8 G4 odom files' >&2; exit 1; }
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G4-record.json" \
  --evidence-file "$EVIDENCE/G4-motor.json" \
  --evidence-file "$EVIDENCE/G4-evidence-manifest.json" \
  --evidence-file "$EVIDENCE/G4-motor-preflight.txt" \
  --evidence-file "$EVIDENCE/G4-deadman-events.txt" \
  "${G4_ARGS[@]}"
```

### G5 - controlled hardware mapping/navigation

Lower the robot only in a cleared, supervised area. Keep E-stop asserted, start
hardware mode, then verify one `cmd_vel` publisher and fresh LiDAR before the
operator explicitly releases E-stop. Start with the lowest accepted physical
motion envelope; simulator speeds are not evidence.

Create separate mode-0600 operator and administrator curl configs as in G3.
The administrator credential is required only to release the software E-stop;
keep the physical power cut reachable. Then run:

```bash
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sudo ROSY_RUNTIME_MODE=hardware ROSY_NAVIGATION_BACKEND=slam \
  /opt/rosy/deploy/robot/runtime-mode.sh up
timeout 10 docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-io \
  ros2 topic hz --window 50 /rosy_01/scan \
  | tee "$EVIDENCE/G5-lidar-rate.txt"
curl --config "$HOME/.config/rosy/admin.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/safety/release \
  | tee "$EVIDENCE/G5-estop-release.json"
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/slam/start \
  | tee "$EVIDENCE/G5-slam-start.json"
# In terminal A, record at most 15 minutes of raw physical telemetry. The
# commissioning directory is the only evidence write mount in rosy-io.
sudo timeout --signal=INT --kill-after=10s 900s \
  docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-io \
  ros2 bag record --storage mcap \
  --output "$EVIDENCE/G5-telemetry" \
  /rosy_01/scan /rosy_01/odom /rosy_01/cmd_vel /rosy_01/map /tf /tf_static
# In terminal B, drive only through the supervised dashboard while mapping.
# Stop terminal A with Ctrl-C after the route is covered; timeout remains the
# hard upper bound and allows rosbag2 to close metadata cleanly.
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' -d '{"name":"pinky_01_physical_001"}' \
  http://127.0.0.1:8080/api/v1/slam/save \
  | tee "$EVIDENCE/G5-map-save.json"
test -s /var/lib/rosy/maps/pinky_01_physical_001.yaml
test -s /var/lib/rosy/maps/pinky_01_physical_001.pgm
cp --no-clobber /var/lib/rosy/maps/pinky_01_physical_001.yaml \
  "$EVIDENCE/G5-map.yaml"
cp --no-clobber /var/lib/rosy/maps/pinky_01_physical_001.pgm \
  "$EVIDENCE/G5-map.pgm"
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/slam/stop \
  | tee "$EVIDENCE/G5-slam-stop.json"
curl --config "$HOME/.config/rosy/operator.curl" --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' -d '{"x":0.25,"y":0.0,"yaw":0.0}' \
  http://127.0.0.1:8080/api/v1/navigation/goal \
  | tee "$EVIDENCE/G5-goal.json"
```

Capture a fresh LiDAR rate, a fresh occupancy map ID, and one short Nav2 goal.
The goal must finish `SUCCEEDED`, with no observed collision. Finish at zero
velocity with E-stop asserted. `map_260905_update_v2` may be used as a route
reference only after coordinate/frame and clearance checks; the first physical
map gets a new evidence-bound ID.

Assert E-stop again before final capture. Fill the invalid-until-measured G5
body template, record, then take hardware down:

```bash
curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/safety/stop \
  | tee "$EVIDENCE/G5-estop-stop.json"
curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
  http://127.0.0.1:8080/api/v1/robot/state >"$EVIDENCE/G5-final-state.json"
curl --config "$HOME/.config/rosy/viewer.curl" --fail-with-body --silent --show-error \
  http://127.0.0.1:8080/api/v1/navigation/state >"$EVIDENCE/G5-navigation-state.json"
MCAP_FILE="$(find "$EVIDENCE/G5-telemetry" -maxdepth 1 -type f -name '*.mcap' -print -quit)"
test -n "$MCAP_FILE" && test -s "$MCAP_FILE"
test -s "$EVIDENCE/G5-telemetry/metadata.yaml"
docker compose --env-file /opt/rosy/deploy/robot/.env \
  -f /opt/rosy/deploy/robot/compose.yaml exec -T rosy-io \
  ros2 bag info "$EVIDENCE/G5-telemetry" \
  | tee "$EVIDENCE/G5-telemetry-info.txt"
{
  cat "$EVIDENCE/G5-map-save.json"
  sha256sum "$EVIDENCE/G5-map.yaml" "$EVIDENCE/G5-map.pgm"
} >"$EVIDENCE/G5-map-artifacts.txt"
sha256sum "$MCAP_FILE" "$EVIDENCE/G5-telemetry/metadata.yaml" \
  "$EVIDENCE/G5-map.yaml" "$EVIDENCE/G5-map.pgm" \
  >"$EVIDENCE/G5-artifact-SHA256SUMS"
sha256sum "$EVIDENCE/G5-lidar-rate.txt" "$EVIDENCE/G5-telemetry-info.txt" \
  "$EVIDENCE/G5-map-artifacts.txt" \
  "$EVIDENCE/G5-navigation-state.json" "$EVIDENCE/G5-final-state.json" \
  >"$EVIDENCE/G5-role-SHA256SUMS"
# Fill G5-hardware.json with the measured duration/topics and the four artifact
# digests. Fill G5-evidence-manifest.json with five role digests and exact body
# role values. G5-telemetry-info.txt comes from `ros2 bag info G5-telemetry`;
# G5-map-artifacts.txt contains the map-save response and YAML/PGM sha256 lines.
python3 "$COMMISSION" prepare \
  --session "$SESSION" --body "$EVIDENCE/G5-hardware.json" \
  --record "$EVIDENCE/G5-record.json"
python3 "$COMMISSION" record \
  --session "$SESSION" --record "$EVIDENCE/G5-record.json" \
  --evidence-file "$EVIDENCE/G5-hardware.json" \
  --evidence-file "$EVIDENCE/G5-evidence-manifest.json" \
  --evidence-file "$EVIDENCE/G5-lidar-rate.txt" \
  --evidence-file "$EVIDENCE/G5-final-state.json" \
  --evidence-file "$EVIDENCE/G5-navigation-state.json" \
  --evidence-file "$EVIDENCE/G5-map-save.json" \
  --evidence-file "$EVIDENCE/G5-goal.json" \
  --evidence-file "$MCAP_FILE" \
  --evidence-file "$EVIDENCE/G5-telemetry/metadata.yaml" \
  --evidence-file "$EVIDENCE/G5-map.yaml" \
  --evidence-file "$EVIDENCE/G5-map.pgm" \
  --evidence-file "$EVIDENCE/G5-telemetry-info.txt" \
  --evidence-file "$EVIDENCE/G5-map-artifacts.txt"
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
```

## 5. Calibration checklist

All four items remain `HOLD` until measured on this assembled Pinky Pro:

1. Measure the actual robot diameter/footprint at its widest rotating envelope,
   including protrusions and cable sweep. Validate by slow 360-degree rotation.
2. Measure command-to-stop distance repeatedly by direction and battery state.
   Tune adaptive speed from measured free clearance minus robot radius, stopping
   distance, localization uncertainty, and a safety margin; do not use a fixed
   maximum 8 cm clearance rule.
3. Validate camera intrinsics first. Then collect checkerboard and ArUco floor
   targets at multiple lateral positions and near/mid/far distances. The image
   homography coordinates must be converted from board-relative lateral-right
   into the declared robot frame before promotion.
4. Keep candidate and independent holdout captures separate. Record camera
   mount height/pitch, image size, focus, target size, lighting, RMSE by range,
   and raw image digests. Reject a homography that extrapolates beyond its
   validated floor region or fails physical tape-measure checks.

When clearance becomes insufficient, the planner may stop, reverse into its
already observed free corridor, rotate, and re-plan. It must include the full
measured footprint and swept path; it must not reverse into unknown occupancy.

## 6. Recovery and end-of-day evidence

On any unexplained state, collision, sensor staleness, command timeout, or loss
of supervision:

```bash
# Press/hold the physical E-stop first.
sudo /opt/rosy/deploy/robot/runtime-mode.sh down
sudo systemctl disable --now rosy-runtime.service
sudo rosy-release status --json
```

Use `sudo rosy-release recover --json` for an interrupted transaction. Use
`sudo rosy-release rollback --json` only for an explicit previous signed
release. Do not clear a recovery hold until its cause is understood.

At the end, keep the session, every referenced raw evidence file, camera/LiDAR
captures, and map artifacts together. Verify all recorded SHA-256 values from a
second copy. A session ending before G5 is resumable and remains `HOLD`; never
edit it to look complete.
