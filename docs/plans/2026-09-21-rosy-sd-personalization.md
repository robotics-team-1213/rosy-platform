# ROSY SD Card Personalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a fail-closed Windows-to-Pi pipeline that flashes one verified Rosy OS image, assigns a `rosy-pinky-<4-character>` device identity, injects site Wi-Fi without logging the passphrase, prepares the device for authenticated Fleet enrollment, and proves the resulting device through readback.

**Architecture:** Keep the signed base image device-agnostic. A Windows PowerShell orchestrator verifies the physical target and delegates deterministic identity/manifest work to a ROS-free Python module; a one-shot Pi service consumes the per-card bundle before networking and runtime startup. Human device names, immutable UUIDs, hardware serials, and DDS identities remain separate.

**Tech Stack:** PowerShell 7, Python 3.12 standard library, JSON Schema, systemd, NetworkManager, official Ubuntu Server 24.04 arm64 Raspberry Pi image, native ARM64 customization, Raspberry Pi Imager CLI, pytest.

**Decision prerequisite:** D-154 and D-161 are Accepted. Implementation must preserve the common-image, public/device/DDS identity separation, secret-handling, core-only first boot, Fleet bootstrap/DDS-isolation boundary, and evidence-tier boundaries. Task 5's former Raspberry Pi OS/container mechanism is superseded by `2026-09-21-ubuntu-native-ros-runtime.md`; the personalization tasks remain active.

---

### Task 1: Lock the device-name and identity contract

**Files:**
- Modify: `deploy/robot/config/board.yaml`
- Create: `deploy/sd/AGENTS.md`
- Create: `deploy/sd/personalization.py`
- Create: `test/test_sd_personalization.py`
- Modify: `test/test_dds_identity_contracts.py`

**Step 1: Write the failing naming tests**

Test that Pinky names match `^rosy-pinky-[a-hj-km-np-z2-9]{4}$`, the alphabet
contains 31 distinct characters, ambiguous characters never appear, and a
supplied registry collision causes bounded regeneration or a clear failure.
Test that a UUIDv4 `device_uid` is independent of the short name. Do not use a
probabilistic "generate many and hope none collide" test.

```python
def test_pinky_name_is_short_human_identity():
    generated = generate_device_identity("pinky_pro", rng=DeterministicRng())
    assert re.fullmatch(r"rosy-pinky-[a-hj-km-np-z2-9]{4}", generated.device_name)
    assert generated.hostname == generated.device_name
    assert UUID(generated.device_uid).version == 4
```

**Step 2: Run RED**

Run: `python -m pytest test/test_sd_personalization.py test/test_dds_identity_contracts.py -q`

Expected: collection fails because `deploy/sd/personalization.py` does not exist.

**Step 3: Implement the D-154 catalog and minimal generator**

Do not rewrite D-15 or D-154. Declare the accepted identity taxonomy as catalog
data:

```yaml
identity:
  platform: rosy
  model_family: pinky
  device_name_prefix: rosy-pinky
  short_code_length: 4
```

Implement immutable `DeviceIdentity`, `generate_short_code`,
`generate_device_identity`, and `validate_device_identity`. Use `secrets.choice`
in production and injectable randomness in tests.

**Step 4: Preserve the DDS boundary**

Add assertions that the public hostname may be `rosy-pinky-k7m4` while
`ROSY_ROBOT_NUMBER=1` still derives domain `41` and namespace `rosy_01`.
Randomizing hostname must not randomize DDS identity.

**Step 5: Run GREEN**

Run: `python -m pytest test/test_sd_personalization.py test/test_dds_identity_contracts.py -q`

Expected: all identity tests pass.

**Step 6: Commit**

```bash
git add deploy/robot/config/board.yaml deploy/sd/AGENTS.md deploy/sd/personalization.py test/test_sd_personalization.py test/test_dds_identity_contracts.py
git commit -m "feat(deploy): define short Pinky device identities"
```

### Task 2: Define the one-time personalization bundle

**Files:**
- Create: `deploy/sd/provision.schema.json`
- Modify: `deploy/sd/personalization.py`
- Modify: `test/test_sd_personalization.py`
- Modify: `deploy/release/secret_scan.py`
- Modify: `test/test_image_checks.py`

**Step 1: Write failing schema and secret tests**

Cover exact keys, UUID, device-name pattern, release ID, `pinky_pro`, explicit
robot number 1..61, derived domain/namespace, requested preset, country code,
SSID length, 64-hex WPA PSK, Fleet endpoint/trust profile/pairing-required flag,
creation time, nonce, and payload checksum. Assert that passphrase-like values,
pairing credentials and private keys never appear in serialized receipts,
exceptions, or logs.

**Step 2: Run RED**

Run: `python -m pytest test/test_sd_personalization.py test/test_image_checks.py -q`

Expected: schema/bundle tests fail because the bundle API is absent.

**Step 3: Implement WPA PSK derivation and bundle creation**

```python
def derive_wpa_psk(ssid: str, passphrase: str) -> str:
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("SSID length is invalid")
    if not 8 <= len(passphrase) <= 63:
        raise ValueError("Wi-Fi passphrase length is invalid")
    return hashlib.pbkdf2_hmac(
        "sha1", passphrase.encode("utf-8"), ssid.encode("utf-8"), 4096, 32
    ).hex()
```

Accept the passphrase only in memory. Return redacted result objects and clear
references in `finally` blocks where practical; never promise that Python string
memory can be securely zeroed.

**Step 4: Separate image and per-card secret scans**

Keep the existing rule that the common image cannot contain a site PSK. Add a
specific validator for the transient card bundle that permits only a raw 64-hex
PSK and an optional one-time Fleet pairing credential at schema-defined paths.
It forbids passphrases, reusable tokens and private keys, and neither permitted
secret may appear in a receipt or log.

**Step 5: Run GREEN**

Run: `python -m pytest test/test_sd_personalization.py test/test_image_checks.py -q`

Expected: all bundle and image-boundary tests pass.

**Step 6: Commit**

```bash
git add deploy/sd/provision.schema.json deploy/sd/personalization.py deploy/release/secret_scan.py test/test_sd_personalization.py test/test_image_checks.py
git commit -m "feat(deploy): add one-time SD personalization bundle"
```

### Task 3: Add the Windows credential and disk-safety boundary

**Files:**
- Create: `deploy/sd/prepare-rosy-sd.ps1`
- Create: `test/test_sd_writer_contract.py`
- Modify: `test/AGENTS.md`

**Step 1: Write failing non-destructive tests**

Run PowerShell with fixture disk inventory JSON and `-PlanOnly`. Cover rejection
of boot/system disks, non-USB disks, offline/read-only media, unexpected size,
missing serial, reused robot number/device name, disk changes between probes,
wrong confirmation text, missing image signature/hash, and existing output
receipt. Confirm no writer process is invoked in every rejected case.

**Step 2: Run RED**

Run: `python -m pytest test/test_sd_writer_contract.py -q`

Expected: tests fail because the PowerShell script is absent.

**Step 3: Implement operator-local credential storage**

Store `PSCredential` XML under
`$env:LOCALAPPDATA\Rosy\credentials\<profile>.credential.xml` with DPAPI via
`Export-Clixml`. The username field holds the SSID. Do not accept a plain
`-WifiPassword` argument. Support `-SetWifiCredential` to prompt with
`Read-Host -AsSecureString`, and make normal preparation fail if the named
credential is absent.

**Step 4: Implement two-probe disk selection and confirmation**

The script must resolve `\\.\PhysicalDrive<DiskNumber>`, snapshot immutable disk
facts, print a redacted plan, then require exactly:

```text
ERASE DISK <number> <device-name>
```

Probe the disk again immediately before write and compare number, serial, size,
bus type, boot/system flags, read-only and offline state.

**Step 5: Wrap the verified image writer**

Use Raspberry Pi Imager CLI without `--disable-verify`:

```powershell
& $RpiImager --cli --sha256 $ImageSha256 $ImagePath $physicalDrive
if ($LASTEXITCODE -ne 0) { throw "image writer failed" }
```

Capture the Imager version and exit code, not arbitrary debug output. The script
must not construct a shell command string or invoke `cmd /c`.

**Step 6: Run GREEN**

Run: `python -m pytest test/test_sd_writer_contract.py -q`

Expected: all PlanOnly and destructive-boundary tests pass without touching a
physical disk.

**Step 7: Commit**

```bash
git add deploy/sd/prepare-rosy-sd.ps1 test/test_sd_writer_contract.py test/AGENTS.md
git commit -m "feat(deploy): add fail-closed Windows SD writer"
```

### Task 4: Install and consume the bundle on first boot

**Files:**
- Create: `deploy/robot/apply-sd-provision.py`
- Create: `deploy/robot/rosy-sd-provision.service`
- Modify: `deploy/robot/install-pi.sh`
- Modify: `deploy/robot/rosy-runtime.service`
- Modify: `deploy/release/network.py`
- Create: `test/test_first_boot_provisioning.py`
- Modify: `test/test_network_provisioner.py`

**Step 1: Write failing root-fixture tests**

Model a boot filesystem and target root without requiring systemd or
NetworkManager. Test one-time consumption, atomic writes, mode `0600`, hostname,
identity JSON, DDS environment, hardware serial binding, idempotent reboot,
bundle deletion, redacted logs, and refusal of cross-model/release/identity
mismatches.

**Step 2: Run RED**

Run: `python -m pytest test/test_first_boot_provisioning.py test/test_network_provisioner.py -q`

Expected: first-boot tests fail because the consumer is absent.

**Step 3: Implement staged application**

Apply into sibling temporary files and rename only after all validations pass:

- `/etc/hostname`
- `/etc/rosy/identity.json`
- `/opt/rosy/deploy/robot/.env`
- `/etc/NetworkManager/system-connections/rosy-site-sta.nmconnection`

Never replace an existing, different identity. Generate NetworkManager content
directly without passing the PSK on a process command line.

**Step 4: Implement network commit/fallback**

Activate the candidate profile and require association plus an IPv4 address.
On first-device failure, remove the candidate and enter `PROVISIONING_AP`. On a
previously provisioned device, preserve the last working profile and enter
`NETWORK_HOLD`. Keep the runtime stopped in both cases.

**Step 5: Order systemd safely**

Make `rosy-runtime.service` require successful first-boot provisioning. The
provision unit runs after local filesystems and before normal network/runtime
startup. It must remain successful and cheap after the consumed marker exists.

**Step 6: Run GREEN**

Run: `python -m pytest test/test_first_boot_provisioning.py test/test_network_provisioner.py test/test_robot_runtime.py -q`

Expected: all first-boot, network, and runtime contracts pass.

**Step 7: Commit**

```bash
git add deploy/robot/apply-sd-provision.py deploy/robot/rosy-sd-provision.service deploy/robot/install-pi.sh deploy/robot/rosy-runtime.service deploy/release/network.py test/test_first_boot_provisioning.py test/test_network_provisioner.py
git commit -m "feat(deploy): consume SD provisioning on first boot"
```

### Task 5: Build the common bootable image

> **Superseded by D-161:** Execute Tasks 2-7 of
> `2026-09-21-ubuntu-native-ros-runtime.md` instead of the former
> Raspberry Pi OS/container steps below. The text below is retained only for traceability.

**Files:**
- Create: `deploy/image/rpi-image-gen/config/rosy-pinky.yaml`
- Create: `deploy/image/rpi-image-gen/layer/rosy-runtime.yaml`
- Create: `deploy/image/rpi-image-gen/layer-hooks/rosy-runtime/`
- Modify: `deploy/image/build-image.sh`
- Modify: `deploy/image/inputs.lock.yaml`
- Modify: `deploy/image/verify-inputs.sh`
- Modify: `deploy/image/verify-artifacts.sh`
- Modify: `test/test_image_pipeline.py`
- Modify: `test/test_image_checks.py`

**Step 1: Write failing image-pipeline tests**

Require the pinned rpi-image-gen commit, Raspberry Pi OS suite, Docker versions,
ROS base digest, source revision, container digests, image hash, SBOM and layer
inventory. Assert the image contains the first-boot consumer/unit/public
verification material but no identity, Wi-Fi profile, PSK or private key.

**Step 2: Run RED**

Run: `python -m pytest test/test_image_pipeline.py test/test_image_checks.py -q`

Expected: tests fail because `build-image.sh` still ends with the intentional
"not implemented" failure.

**Step 3: Implement the pinned rpi-image-gen integration**

Invoke the pinned source tree with an external Rosy config/layer directory.
Keep native `aarch64` refusal, verified inputs, unused output directory, and
atomic staging. Do not add an x86/QEMU release path.

**Step 4: Verify the artifact contract**

`verify-artifacts.sh` must mount or inspect the image read-only and prove Pi 5
boot files, systemd units, runtime payload, permissions, absence of device
identity/secrets, checksums, SBOM, and signed manifest.

**Step 5: Run host contract tests**

Run: `python -m pytest test/test_image_pipeline.py test/test_image_checks.py -q`

Expected: mocked/source contracts pass. This is not `BUILD_GO`.

**Step 6: Run the native ARM64 artifact gate**

Run on the approved native ARM64 build host:

```bash
./deploy/image/verify-inputs.sh deploy/image/inputs.lock.yaml
./deploy/image/build-image.sh --release-id <YYYY.MM.DD-NNN>
./deploy/image/verify-artifacts.sh dist/<YYYY.MM.DD-NNN>
```

Expected: all three commands exit 0, a bootable image and signed companions
exist, and `BUILD_GO` evidence records exact hashes. Until this run exists,
ARTIFACT remains HOLD.

**Step 7: Commit**

```bash
git add deploy/image test/test_image_pipeline.py test/test_image_checks.py
git commit -m "feat(image): build the common Rosy Pinky image"
```

### Task 6: Extend readback and commissioning evidence

**Files:**
- Modify: `deploy/robot/verify/device_readback.py`
- Modify: `deploy/robot/commissioning_session.py`
- Modify: `test/test_device_readback.py`
- Modify: `test/test_pinky_commissioning.py`

**Step 1: Write failing readback tests**

Require `device_uid`, `device_name`, hostname, model, hardware-serial binding,
robot number, domain, namespace, release ID, network mode and SSID. Assert no
PSK, passphrase, credential path or full NetworkManager profile is serialized.

**Step 2: Run RED**

Run: `python -m pytest test/test_device_readback.py test/test_pinky_commissioning.py -q`

Expected: tests fail because the new identity is not in readback/G1/G2.

**Step 3: Add fail-closed comparison**

G1 compares requested device identity and internal DDS identity. G2 compares
device readback with the personalization receipt and signed release. Hostname,
UUID, hardware serial, model, robot number, domain, namespace or release drift
must hold the gate.

**Step 4: Run GREEN**

Run: `python -m pytest test/test_device_readback.py test/test_pinky_commissioning.py -q`

Expected: readback and G0-G5 state-machine tests pass.

**Step 5: Commit**

```bash
git add deploy/robot/verify/device_readback.py deploy/robot/commissioning_session.py test/test_device_readback.py test/test_pinky_commissioning.py
git commit -m "feat(deploy): bind personalized identity into readback"
```

### Task 7: Complete the Pinky-to-Fleet communication path

**Files:**
- Modify: `src/core/core_common/core_common/protocol/schemas.py`
- Modify: `src/core/core_features/core_features/fleet_agent/agent.py`
- Modify: `src/core/core/core/services.py`
- Modify: `src/core/core/test/test_fleet_agent.py`
- Create: `src/site/fleet/fleet/hub/server.py`
- Modify: `src/site/fleet/fleet/cli.py`
- Modify: `src/site/fleet/fleet/server/console.py`
- Create: `src/site/fleet/test/test_hub_server.py`
- Create: `test/test_fleet_enrollment_contracts.py`
- Modify: `deploy/robot/apply-sd-provision.py`

**Step 1: Write failing identity and connection tests**

Extend the additive hello contract with immutable `device_uid`, public
`device_name`, model, hardware serial and internal `robot_id`. Test that two
Pinky devices with different UUID/name/robot-number tuples register as two
robots even when they share one OS release. Reject duplicate UUID, duplicate
robot number, hardware-serial drift, invalid endpoint trust and a reused or
expired pairing credential.

Test that the robot opens no inbound listener and never exposes its DDS domain
to another robot. With no valid Fleet bootstrap, `FleetAgent` stays disabled
without delaying CORE. With a valid bootstrap it connects outbound, sends hello,
heartbeats at 1 Hz, forwards ordered events, resumes from `since_seq` after
reconnect and uses bounded exponential backoff.

**Step 2: Run RED**

Run:

```bash
python -m pytest src/core/core/test/test_fleet_agent.py src/site/fleet/test/test_hub.py src/site/fleet/test/test_hub_server.py test/test_fleet_enrollment_contracts.py -q
```

Expected: tests fail because the network listener, enabled agent and device
identity fields do not yet exist.

**Step 3: Add the site Hub listener and enrollment exchange**

Implement `fleet hub --listen` on the site PC around the existing pure
`SiteHub.handle()` contract. TLS/trust policy and one-time pairing are required
outside explicit development fixtures. Exchange the one-time credential for a
rotatable long-term device credential stored mode `0600`; remove the one-time
credential from the robot after a successful exchange. Logs and Fleet registry
views may contain IDs and certificate fingerprints, never either credential.

**Step 4: Enable the device-side FleetAgent fail-closed**

Ship the agent code in the common Pinky image but enable it only after the
personalization bootstrap, identity/serial binding and trust checks succeed.
Wire it as a non-blocking CORE service: CORE remains local-first when Fleet is
absent, and no reconnect path may activate motor, mission or formation. Fleet
commands continue through the authenticated robot REST API with correlation ID;
the outbound socket is gather-only for hello, heartbeat and events.

**Step 5: Replace polling only after equivalent state is proven**

Feed Hub registry snapshots into `FleetConsole` while retaining an explicit
fallback during transition. Tests must prove that robot state, event sequence,
offline timeout and reconnect are equivalent before REST polling is removed.

**Step 6: Run GREEN and the two-robot host integration**

Run:

```bash
python -m pytest src/core/core/test/test_fleet_agent.py src/site/fleet/test/test_hub.py src/site/fleet/test/test_hub_server.py test/test_fleet_enrollment_contracts.py -q
python -m pytest src/site/fleet/test -q
```

Then start two distinct host-sim robot endpoints and assert that Fleet shows
both device identities, receives 1 Hz heartbeats, correlates a command for each,
recovers both sessions after Hub restart, and holds the formation when one
connection is cut. This remains SOURCE/SIM evidence, not physical FLEET GO.

**Step 7: Commit**

```bash
git add src/core/core_common/core_common/protocol/schemas.py src/core/core_features/core_features/fleet_agent/agent.py src/core/core/core/services.py src/core/core/test/test_fleet_agent.py src/site/fleet/fleet/hub/server.py src/site/fleet/fleet/cli.py src/site/fleet/fleet/server/console.py src/site/fleet/test/test_hub_server.py test/test_fleet_enrollment_contracts.py deploy/robot/apply-sd-provision.py
git commit -m "feat(fleet): connect personalized Pinky devices outbound"
```

### Task 8: Document, verify, and dry-run the connected SD

**Files:**
- Create: `docs/deployment/rosy-sd-card-personalization.md`
- Modify: `docs/deployment/AGENTS.md`
- Modify: `docs/deployment/raspberry-pi-wifi-image.md`
- Modify: `deploy/AGENTS.md`
- Modify: `deploy/image/AGENTS.md`
- Modify: `deploy/robot/AGENTS.md`
- Modify: `deploy/logs.md`
- Modify: `deploy/progress.md`
- Generated: `deploy/index.md`
- Generated: `docs/index.md`
- Generated: `STATUS.md`

**Step 1: Write the operator runbook**

Document credential enrollment, `-PlanOnly`, exact disk verification,
confirmation phrase, flash, safe eject, first boot, readback, recovery, and
G0-G5 handoff. Use placeholders for SSID/profile and never include a real
password.

**Step 2: Run the full source verification**

Run:

```bash
python -m pytest test/test_sd_personalization.py test/test_sd_writer_contract.py test/test_first_boot_provisioning.py test/test_image_pipeline.py test/test_image_checks.py test/test_network_provisioner.py test/test_pi_wifi_deployment.py test/test_dds_identity_contracts.py test/test_device_readback.py test/test_pinky_commissioning.py test/test_fleet_enrollment_contracts.py src/core/core/test/test_fleet_agent.py src/site/fleet/test -q
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git diff --check
```

Expected: zero failures, zero harness errors, clean whitespace check.

**Step 3: Run a physical-card dry run only**

On the Windows release PC, re-read `Get-Disk` immediately and run:

```powershell
.\deploy\sd\prepare-rosy-sd.ps1 `
  -DiskNumber 1 `
  -RobotNumber 1 `
  -Model pinky_pro `
  -Preset hardware `
  -WifiProfile site-default `
  -ImagePath .\dist\rosy-os-<release>.img.zst `
  -PlanOnly
```

Expected: the intended USB/SD model, serial and size are printed; boot/system
disk flags are false; the generated name matches `rosy-pinky-xxxx`; no secret
appears. Do not remove `-PlanOnly` until Task 5 has real `BUILD_GO` evidence and
the operator confirms the current disk again.

**Step 4: Perform the MEDIA and BOOT gates**

After explicit operator approval, rerun without `-PlanOnly`, type the exact erase
phrase, safely eject, boot the Pinky Pro, and collect first-boot/readback
evidence. A successful write is MEDIA evidence only; BOOT and DEVICE remain
separate.

**Step 5: Perform the DEVICE and FLEET gates separately**

Complete G0-G5 on the physical Pinky. FLEET stays HOLD until at least two
personalized Pinky devices with distinct UUID/name/robot-number tuples are
available. Pair both to the site Hub, verify 1 Hz heartbeat and correlated
commands, restart the Hub to prove reconnect, then interrupt one robot's Fleet
link during a formation and verify the required HOLD behavior. A one-device
HTTP 200, host simulation, or SD readback is not FLEET acceptance.

**Step 6: Record actual gate state and commit**

Promote only gates supported by captured evidence. If native image or Pi proof
is absent, keep ARTIFACT/DEVICE as HOLD.

```bash
git add docs/deployment deploy/AGENTS.md deploy/image/AGENTS.md deploy/robot/AGENTS.md deploy/logs.md deploy/progress.md deploy/index.md docs/index.md STATUS.md
git commit -m "docs(deploy): add Rosy SD personalization runbook"
```

## Execution stop conditions

- Never write the connected SD while `deploy/image/build-image.sh` is still the
  intentional stub or `verify-artifacts.sh` lacks `BUILD_GO` evidence.
- Never use a disk selected only by drive letter; destructive selection is by
  freshly verified physical disk number plus serial and size.
- Never put the site passphrase in a command argument, repository file, receipt,
  console transcript or commissioning evidence.
- Never promote `motor` or `hardware` during first boot.
- Never mark FLEET GO from a single Pinky, REST polling alone, host simulation,
  or an enabled configuration without an observed outbound session.
- Never call Windows/x86 tests, image-write success, SSH, or HTTP 200 physical
  Pinky Pro acceptance.
