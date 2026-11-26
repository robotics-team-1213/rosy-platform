<!-- Parent: ../AGENTS.md -->

# SD personalization

**Parent context:** `../AGENTS.md`

## Purpose

Windows-side, fail-closed preparation of one verified ROSY OS image for one Pinky Pro. The signed image stays device-neutral; this directory creates the one-time per-card provisioning bundle. Entries: `write-card.ps1`, `setup-moved-device.ps1`.

## Safety rules

- Public names are `rosy-pinky-xxxx`; UUID, serial and DDS robot number are separate identities.
- Never accept a Wi-Fi passphrase on a command line or write it to logs, receipts, exceptions, or the common image.
- Select the disk by re-probed serial, size and bus type (`-DiskSerial` or plan `disk_serial`, exactly one USB disk), never by drive letter or disk number. Confirm: `ERASE SERIAL <serial> <device_name>`.
- Before disk discovery, `verify-image-release.py` checks the Ed25519 signature over `SHA256SUMS`, every listed file, manifest identity and exact `.img.xz` name/hash; a signature file's presence is never enough.
- Tests and `-PlanOnly` never invoke an image writer or alter physical media; tests use a stand-in (`-DiskInventoryJson` + `-ReadbackDevice`), never a physical disk.
- Omitted `-RobotNumber` takes the lowest free registry number 40-49 (D-562), never a fixed default (D-33); explicit numbers are 1-61. A write without `-PlanPath` must pass `-RobotNumber`.
- A reviewed plan (`-PlanOnly -PlanPath`) pins robot, release, image hash, SSID, DDS identity and disk; a write refuses on drift or a differing argument.
- D-188: launch with `-Detach`, follow `card-write-status.ps1 -LogPath <log>` (`-Json`); never guess ETA. Slow media stops a non-interactive run unless `-AcceptSlowMedia`.
- After a verified writer exit, compare every decompressed image byte with the disk before the one-time bundle is copied to `rosy-provision/provision.json`; registry and receipt update only then.
- An image write is MEDIA evidence only, not BOOT/DEVICE/FLEET proof.
- `-ReprovisionReceipt` (D-174 F7, D-746) rewrites a card only for a registered robot with a receipt proving a verified earlier write of that number, name and UID; another robot's provision is refused unless `-ReplaceExistingProvision` was in the plan.
- `-OperatorPublicKey <file.pub>` (D-174 F3) adds a public key for a key-only `rosy` account; plan and receipt carry only its fingerprint; a different key than the plan stops the write.
- The ERASE prompt drops typed-ahead keys (2026-09-30 buffered Enter); slow readback (1-3 MB/s) is not a stall.

## Emergency card write (D-389)

Only when the robot needs the card now: `write-card.ps1 ... -Emergency -EmergencyReason '<10-200 ASCII, no double quotes>'` (never with `-PlanOnly`).

- All pre-write gates stay; only the full readback is skipped (MBR disk signature must still match). Receipt: `media_readback.verified=false`; number, name and UID stay reserved.
- Follow-up: before first boot `verify-emergency-card.ps1 -Receipt <receipt> -ReleaseDir <release>`; after boot verify on the device (`dpkg --verify`), then a standard write with `-ReprovisionReceipt`.
- `-Emergency -ResumeAfterWrite` needs `-PlanPath` and a clean `<plan>.attempts.jsonl` history; otherwise rewrite the card.

## Other tools

- `enable-motor-commissioning.ps1` (D-389): operator key, Rosy `known_hosts`, `StrictHostKeyChecking=yes`; a missing key or file stops before the robot.
- `rotate-core-api-credential.ps1` (D-193): CORE API only; rolls back on failure, never prints the value; keep it ASCII.
- Card diagnostics (D-174 F8, D-175): FAT32 `rosy-diag/latest.txt` needs no elevation; for ext4 use `read-card-diagnostics.py --disk <N> --out <empty dir>` in an admin shell, never `wsl --mount`. Copies are raw: secret-scan before sharing.
- `recover-no-drive.py` (D-321): Linux-only, offline ext4; read-only by default, `--apply` needs exact UID/name/number, active release and an off-card backup. Its receipt does not prove motors stay off after reboot.

## Testing

```powershell
python -m pytest test/test_sd_*.py test/test_media_readback.py test/test_card_diagnostics.py test/test_motor_commissioning_ssh.py -q
```
