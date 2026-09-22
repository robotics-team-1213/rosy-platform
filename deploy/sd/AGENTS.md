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

## Testing

```powershell
python -m pytest test/test_sd_personalization.py test/test_sd_writer_contract.py test/test_media_readback.py -q
```
