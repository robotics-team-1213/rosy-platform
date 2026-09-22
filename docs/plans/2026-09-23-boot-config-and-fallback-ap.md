# Boot Config File and Fallback AP Plan (D-176)

> Test-first. Secrets are scrubbed from the card in the same change that first
> reads them; there is no intermediate commit that applies without scrubbing.

**Goal:** A person edits `rosy-config.yaml` on the card's boot partition to set
Wi-Fi, Fleet and AP policy; the robot applies it at boot and removes the
passwords from the card. With no uplink the robot opens `rosy-pinky-xxxx` with a
per-card random password, reachable at `10.42.0.1`.

---

## Task 1: Config schema and parser

**Files:** `deploy/robot/native/rosy_config.py`, `deploy/robot/native/rosy-config.schema.json`,
`deploy/robot/native/defaults.yaml`, `test/test_rosy_config.py`

1. Layers: image defaults < bundle < `rosy-config.yaml`; identity keys rejected.
2. Fields: `wifi: [{ssid, password, priority}]`, `country`, `ap: {mode: fallback|relay|off, ssid, password}`,
   `fleet: {endpoint, trust_profile}`, `timezone`, `operator_ssh_keys`.
3. Invalid file → typed error list, nothing applied. Stdlib + python3-yaml (already in the image).

## Task 2: Apply and scrub

**Files:** `deploy/robot/native/rosy-config-apply.py`, `rosy-config.service`, `test/test_rosy_config_apply.py`

1. Content hash of the non-secret view decides "changed"; applied hash in `/var/lib/rosy/config/applied.json`.
2. Wi-Fi → NetworkManager profiles (PBKDF2 PSK, 0600) through the injected runner.
3. Rewrite `rosy-config.yaml` with passwords replaced by `<applied>` (mkstemp + fsync + dir fsync on vfat).
4. Root oneshot before `NetworkManager-wait-online.service`; `OnFailure=rosy-boot-status.service`.
5. Add `/boot/firmware/rosy-config.yaml` to the D-175 denied paths.

## Task 3: Per-card AP password in the writer

**Files:** `deploy/sd/personalization.py`, `provision.schema.json`, `prepare-rosy-sd.ps1`,
`deploy/sd/rosy-config.template.yaml`, tests

1. Bundle `network.ap = {ssid, psk}` from a random ≥12-char password (`secrets`).
2. Store the password in the operator's DPAPI store keyed by device name; print it once; never in
   plan/receipt (fingerprint only).
3. Write the commented `rosy-config.yaml` template to the boot partition next to the bundle.

## Task 4: Fallback AP controller

**Files:** `deploy/robot/native/rosy-network.py`, `rosy-network.service`, install `network.py`
via `install-native-runtime.sh`, `test/test_rosy_network_fallback.py`

1. Poll uplink (NM connectivity + default route); open AP after 120 s without uplink when
   `ap.mode=fallback`, close on uplink; `relay` = D-26 `RELAY_AP_STA`; `off` = `NETWORK_HOLD`.
2. Reuse `network.py` profile operations; no CORE involvement.

## Task 5: Show it

**Files:** `rosy-boot-status.py`, tests

1. Console banner shows AP SSID, password and `10.42.0.1` while the AP is open; avahi TXT `network=ap|sta`.
2. Black box records `network=ap` but never the AP password.

## Task 6: Image, docs, acceptance

1. Install units/defaults in `build-native-payload.sh`; enable in `customize-rootfs.sh`; installed-layout test.
2. Runbook: "현장에서 Wi-Fi 바꾸기", "AP로 접속하기".
3. Device acceptance per D-176 Validation.
