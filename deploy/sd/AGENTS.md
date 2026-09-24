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
   python deploy\sd\read-card-diagnostics.py --disk <Number> --out <new empty folder>
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

## Testing

```powershell
python -m pytest test/test_sd_personalization.py test/test_sd_writer_contract.py test/test_sd_write_card_entrypoint.py test/test_media_readback.py test/test_card_diagnostics.py -q
```
