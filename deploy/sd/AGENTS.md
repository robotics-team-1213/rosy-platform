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
- After a verified writer exit, compare every decompressed image byte with the
  selected physical disk before `prepare-rosy-sd.ps1` creates the one-time bundle
  through stdin and copies it atomically to `rosy-provision/provision.json` on the
  selected disk's FAT32 boot partition. Registry and receipt are updated only then.
- An image write is MEDIA evidence only; it is not BOOT, DEVICE, or FLEET proof.

## Testing

```powershell
python -m pytest test/test_sd_personalization.py test/test_sd_writer_contract.py test/test_media_readback.py -q
```
