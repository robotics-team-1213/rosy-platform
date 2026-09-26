# Moved SD card: new-device setup

Date: 2026-09-26
Status: source implementation; same-card operator rebind validated on one Pi; image validation pending
Decision: D-154 new-device path

## Intent

An SD card personalized on one Raspberry Pi may be moved to another Pi. The
second Pi is a **new device**. Boot must never reuse the old device UID, DDS
robot number, CORE API credential, Fleet pairing, or motion authorization.
Site Wi-Fi remains connected so the operator can reach the new Pi. Previous
maps, settings, and logs remain available for later selective restoration.

## Boot path

1. First boot compares the live Pi serial with the completed provisioning
   record. It verifies that the old completion record, hardware binding, and
   device identity agree before treating a difference as a moved card.
2. It creates a root-only, stable `new-device-setup.json` with a fresh
   provisional UUID and name bound to the new serial. Reboots reuse it. A
   third board or an inconsistent old record remains a hard failure.
3. It writes `NEW_DEVICE_SETUP` to the boot state. `rosy-sd-provision` and
   CORE remain blocked. The old data remains on the card but cannot be
   served by CORE; no automatic deletion or transfer occurs. An operator with
   a separately validated new-device bundle may run `rosy-rebind-board.py` to
   archive the old CORE home, logs and identity records on that SD, then apply
   the new registration. The existing site Wi-Fi profile remains in place.
4. The read-only setup server owns port 8080 while CORE is absent.
   `/dashboard` explains the next step; `/api/v1/*` returns 503. It has no
   registration write endpoint and reads only the public boot-status record.
   The LCD/boot summary shows a registration action.

## Registration and prior data

The provisional identity is a candidate, not a registered robot. The
operator preserves the old SD as the previous device's data archive, then
uses the existing signed-image and verified-media writer on a blank card.
The writer must allocate/check the new robot number against its registry,
issue a new CORE credential and Fleet bootstrap, and bind the new card to
this Pi at first boot. It may use the provisional name/UUID if still free.
Selective map or setting restoration is a separate reviewed operation;
credentials, device identity, DDS number, and Fleet pairing are never copied.

The central Fleet server is not implemented, so boot cannot prove global
number or name uniqueness. Automatic staging therefore stops before CORE
rather than inventing a robot number. The live `2026.09.26-017` image
does not contain this change; a newly signed image and physical card
validation are required before claiming device behavior.

## Verification

Host tests cover serial mismatch, stable staging, old-board refusal, state
recovery after an interrupted write, setup-only HTTP, and boot-status
display. Image staging, arm64 build, real Pi boot, media readback, and
registration remain separate gates.
