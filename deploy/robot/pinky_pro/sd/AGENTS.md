<!-- Parent: ../AGENTS.md -->

# SD personalization

## Purpose

Windows-side, fail-closed preparation of one verified ROSY OS image for one
Pinky Pro. The signed image remains device-neutral; this directory creates the
one-time per-card provisioning bundle.

## Safety rules

- Public device names are `rosy-pinky-xxxx`; immutable UUID, hardware serial,
  and DDS robot number remain separate identities.
- Never accept a Wi-Fi passphrase on a command line or write it to logs,
  receipts, exceptions, or the common image.
- Disk selection is by a freshly re-probed physical disk number, serial, size,
  and bus type. A drive letter is never sufficient.
- Before disk discovery, verify the Ed25519 signature over `SHA256SUMS`, every
  listed file, manifest identity and the exact `.img.xz` filename/hash with
  `verify-image-release.py`. Signature-file presence alone is never enough.
- Tests and `-PlanOnly` must not invoke an image writer or alter physical media.
- Omitted `-RobotNumber` is drawn at random from the registry's free slots (1-61),
  never a fixed default (D-33). Omitted Fleet values default to
  `https://<this-host>.local` / `rosy-pilot-lan` and the plan says so
  (`robot_number_source`, `fleet_source`); nothing on the robot reads them yet.
- Write a reviewed plan with the operator entry point, not a hand-made wrapper:
  `write-card.ps1 -PlanPath <plan.json> -ReleaseDir <signed release> -WifiProfile <p>`
  (plus `-OperatorPublicKey`, `-ReprovisionReceipt` when needed). It derives every
  path from the plan and release, finds the card by serial, elevates itself, keeps a
  timestamped log and `.exit` marker per attempt, and refuses an existing receipt.
  `-PrintArguments` shows the resolved call without writing.
- For a moved-card `NEW_DEVICE_SETUP`, prefer the guided new-card entry point:
  `setup-moved-device.ps1 -RobotAddress <robot-ip>`. It checks the read-only setup
  page, selects a signed release and saved site Wi-Fi profile, allocates a fresh
  identity through `prepare-rosy-sd.ps1 -PlanOnly`, and delegates media changes to
  `write-card.ps1`. It never accepts/replaces SSH host keys or performs same-card
  rebind. If the operator key pair exists, it adds a user SSH config alias so the
  new device can be reached as `ssh rosy-pinky-xxxx`; host-key checking remains on.
  Keep both the plan review and the writer's exact serial erase confirmation.
- D-188: operators launch with `-Detach` (own elevated window, one UAC prompt,
  returns at once) and follow `card-write-status.ps1 -LogPath <log>` (`-Json` for
  agents; no elevation). Quote its ETA; never guess completion times. The write
  measures the card read rate before the ERASE confirmation and stops a
  non-interactive run on slow media unless `-AcceptSlowMedia`; the plan pins the
  card's `disk_signature`/`disk_guid`. `-ReadbackDevice` and a non-`.exe`
  `-RpiImager` are fixture-only (they need `-DiskInventoryJson`).
- The card is identified by its serial, not the Windows disk number, which changes
  as USB devices come and go. `-DiskSerial` (or a reviewed plan's `disk_serial`)
  resolves the number right before each probe and must match exactly one USB disk;
  the confirmation is `ERASE SERIAL <serial> <device_name>`.
- `-ReprovisionReceipt <receipt.json>` (D-174 F7) rewrites a card for an already
  registered robot: the receipt must prove a verified earlier write (writer exit 0,
  readback verified) of exactly that number, name and UID, which it supplies when
  omitted. The new receipt records `supersedes`; registry entries stay unique.
- `-OperatorPublicKey <file.pub>` (D-174 F3) adds one ed25519/ecdsa public key to the
  bundle; first boot creates a key-only `rosy` account (journal groups, NOPASSWD sudo).
  The plan and receipt carry only the `SHA256:` fingerprint, and a write with a
  different key than the reviewed plan stops before the writer. Without the flag
  the bundle keeps its pre-F3 shape, so older images still accept it.
- `-PlanOnly -PlanPath <file>` saves the reviewed plan once (no overwrite). A write
  with the same `-PlanPath` takes robot number, name, UID, preset, model, country and
  Fleet values from the plan, and refuses before the writer if the disk, release, image
  hash, Wi-Fi SSID, DDS identity or registry path drifted, or an explicit argument
  differs from the plan (case-sensitive). An automatic robot number is never drawn
  inside a write: without `-PlanPath` a write must pass `-RobotNumber`.
- After a verified writer exit, compare every decompressed image byte with the
  selected physical disk before `prepare-rosy-sd.ps1` creates the one-time bundle
  through stdin and copies it atomically to `rosy-provision/provision.json` on the
  selected disk's FAT32 boot partition. Registry and receipt are updated only then.
- An image write is MEDIA evidence only; it is not BOOT, DEVICE, or FLEET proof.

## Standard card write

The default, and the only procedure that produces MEDIA evidence:
`write-card.ps1 -PlanPath <plan> -ReleaseDir <release> -WifiProfile <p> -Detach`.
Every gate above runs, then Imager (`--disable-verify`, D-180) and the full
byte-for-byte readback; the receipt says `media_readback.verified: true`.

- The ERASE prompt (`Read-EraseConfirmation`) first drops keys typed before it
  (`Clear-TypeAhead`); an empty line or end of input fails as
  `no console input: ... re-run and type exactly ...`, never as a mismatch
  (2026-09-30: a buffered Enter answered a `-Detach` prompt 0.9 s after it appeared).
- A CPU-starved PC makes the readback crawl (2026-10-01: 1-3 MB/s, 1.5 h ETA;
  CPU 100 %, card disk queue 0). Free CPU or raise the verifier's priority
  (runbook: "readback이 1-3 MB/s로 느릴 때"); a slow readback is not a stall.
- Release artifacts: `tools/release/download_artifact.py` (parallel range download
  with progress and resume) instead of a silent `gh run download`.

## Emergency card write (D-385)

Only when the robot needs the card now and the readback cannot be waited for.
`write-card.ps1 ... -Emergency -EmergencyReason '<why>'` (reason: 10-200
printable ASCII characters, no double quotes; refused before UAC otherwise;
never with `-PlanOnly`).

- Every pre-write gate stays: signature, serial, plan pinning, pre-flight,
  confirmation. Only the full readback is skipped; a cheap check stays (the
  card's MBR disk signature must equal the image's after the write).
- Honest evidence: stages `bundle`/`unverified-no-bundle` and
  `done`/`complete-unverified`; receipt `media_readback.verified=false,
  skipped="emergency"` plus `emergency={reason, at, readback, registry,
  follow_up}`. The robot number, name and UID stay registered (reserved).
- Follow-up, one of: before first boot, `verify-emergency-card.ps1 -Receipt
  <receipt> -ReleaseDir <release>` (elevated, read-only) re-reads the card,
  tolerating `rosy-provision/` and `rosy-config.yaml`, and writes
  `<receipt>.readback.json`; the original receipt is never changed. After boot
  the card cannot match its image: verify on the device instead (re-hash the
  active release against its signed `SHA256SUMS` and run `dpkg --verify`, as on
  rosy-pinky-9dfk), then rewrite it with a standard write and
  `-ReprovisionReceipt <emergency receipt>` when possible.
- `-ReprovisionReceipt` accepts an emergency receipt only for a standard write
  (the new receipt records `supersedes.emergency: true`) and refuses an
  emergency write on an emergency receipt. Other unverified receipts are refused.
- A stand-in card (`-DiskInventoryJson` + `-ReadbackDevice`) is the only way tests
  run either procedure; never point them at a physical disk.

## Motor commissioning SSH (D-385 decision 6)

`enable-motor-commissioning.ps1` connects with the Rosy operator key
(`-KeyPath`, default `%LOCALAPPDATA%\Rosy\ssh\rosy-operator-ed25519`), the Rosy
`-KnownHosts` (default `%LOCALAPPDATA%\Rosy\known_hosts`) and `-RosyUser rosy`,
like `rosy-release-push.ps1`; `StrictHostKeyChecking=yes` stays. A missing key
or known_hosts file stops it before the robot. `-PrintSshArguments` prints the
resolved ssh options without connecting (test: `test/test_motor_commissioning_ssh.py`).

## Rotating the CORE API credential (D-193 5)

`rotate-core-api-credential.ps1 -DeviceName <name> [-BaseUrl http://host:8080]`
rotates the card's administrator token over CORE's API only (no SSH): whoami
(stored value must be this robot's non-expiring administrator) -> add -> DPAPI
store -> whoami with the stored value -> delete the old id. It rolls back the
store and the new id if storing or confirming fails, never prints the value,
and uses HttpClient with the proxy and redirects off. Keep it ASCII (Windows
PowerShell 5.1 reads BOM-less scripts as ANSI).

## Card diagnostics without mounting (D-174 F8, D-175)

When a card fails to boot and SSH is not available, read the card on Windows:

1. Insert it; the FAT32 boot partition mounts by itself. `rosy-diag/latest.txt`
   (the D-175 L1 black box) is readable without elevation.
2. For the journal and the ext4 root, do **not** use `wsl --mount`: it fails on USB
   SD readers (`Wsl/Service/AttachDisk/MountDisk/0x8007000f`) and leaves the disk
   offline until it is re-inserted. Instead, from an **administrator** PowerShell:

   ```powershell
   python -m pip install ext4          # once; pure-Python ext4 reader
   Get-Disk | Where-Object BusType -eq USB | Format-Table Number, SerialNumber, Size
   python deploy\robot\pinky_pro\sd\read-card-diagnostics.py --disk <Number> --out <new empty folder>
   ```

   It opens `\\.\PhysicalDrive<Number>` read-only, finds the Linux root partition in
   the MBR, copies `/var/lib/rosy/**`, `/etc/rosy/**`, `/etc/hostname`, `/etc/passwd`,
   `/etc/systemd/system/**` (symlinks are recorded, not followed), `/var/log/journal/**`,
   `/var/log/cloud-init*.log` into `rootfs/`, the FAT32 `rosy-diag/` into `boot/`, and
   writes `extract-report.json` (sizes, sha256, saved names, denied paths, errors).
   Paths denied by `rosy_diag_redact.is_denied_path` (Wi-Fi connection files,
   `rosy-provision/`, tokens, keys) are never opened. Names Windows cannot store
   (`\x2d` unit escapes) are saved `%`-escaped; the report maps them back.
3. Read the journal in WSL: `journalctl -D <out>/rootfs/var/log/journal/<machine-id> -b -u 'rosy-*'`
   (one `-D` directory; several `--file` arguments fail with "Extraneous arguments").

The copies are raw, not redacted (the journal is binary). Keep them with the card's
evidence; do not commit or share them without a secret scan.

## Powered-off no-drive recovery (D-321)

`recover-no-drive.py` is a Linux-only offline tool for a separately mounted
ext4 root partition. Its default mode is read-only inspection. `--apply` requires
the exact provisioned UID/name/number and active release, plus a backup directory on another
filesystem; it saves the original bytes, writes `core` with no drive flag, and
reads the card back. See `docs/deployment/pinky-offline-no-drive-recovery.md`.
The Windows diagnostics reader cannot write ext4. Neither the tool's receipt
nor a card readback proves that motors stay off after a physical reboot.

## Testing

```powershell
python -m pytest test/test_sd_personalization.py test/test_sd_writer_contract.py test/test_sd_write_card_entrypoint.py test/test_media_readback.py test/test_card_diagnostics.py test/test_rotate_core_api_credential.py test/test_download_artifact.py test/test_motor_commissioning_ssh.py -q
```
