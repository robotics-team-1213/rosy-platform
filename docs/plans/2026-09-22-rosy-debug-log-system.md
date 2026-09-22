# ROSY Debug Log System Plan (D-174)

> Test-first. Redaction tests come before any collector writes a byte. Shares the
> stage model with D-173 Task 5 and card reading with D-173 Task 8; do those
> interfaces first so the two plans do not fork.

**Goal:** A failed boot is explainable from the card alone (L1), from one SSH
command (L2), and from the running API when CORE is up (L3), with no secrets in
any artifact.

**Acceptance:** an image with F1 deliberately reintroduced shows
`FAILED: rosy-release-recover` + `No module named 'signing'` in
`rosy-diag/latest.txt` on the FAT32 boot partition, and in the L2 bundle; both
pass `deploy/release/secret_scan.py`.

---

## Task 1: Shared redaction and correlation (all layers)

**Files:** `deploy/robot/native/rosy_diag/redact.py`, `test/test_diag_redaction.py`

1. Failing tests: PSK, `psk=`, WPA hex PSK, API/console tokens, PEM private keys,
   `Authorization:` headers, provisioning bundle bodies are removed; ordinary
   journal lines survive byte-for-byte.
2. Reuse `secret_scan.py` patterns; add a deny-list of paths never read
   (`NetworkManager/system-connections`, `rosy-provision/`, `/etc/rosy/*token*`).
3. `Correlation` record: `boot_id`, `release_id`, `device_name`, `device_uid`,
   monotonic and wall time.

## Task 2: L0 journald ledger

**Files:** `deploy/robot/native/journald-60-rosy.conf` (copied by `build-native-payload.sh` into the image overlay at `etc/systemd/journald.conf.d/`),
`deploy/image/build-native-payload.sh`, `test/test_image_customization_contract.py`

1. `Storage=persistent`, `SystemMaxUse=200M`, `RuntimeMaxUse=32M`; contract test.
2. Every ROSY unit logs to the journal only (no private log files); contract test
   over `deploy/robot/native/*.service`.

## Task 3: L1 black box on the boot partition

**Files:** `deploy/robot/native/rosy_diag/boot_report.py`,
`deploy/robot/native/rosy-boot-report.service`, `test/test_boot_report.py`

1. Pure function over (stage from D-173 Task 5, failed units, per-unit tail lines,
   identity, release, network summary) → report dict and a human `latest.txt`.
2. Writer: `/boot/firmware/rosy-diag/boot-<n>-<boot_id>.json` + `latest.txt`,
   atomic write (tmp + rename + fsync), keep last 5, total cap 2 MiB, per-unit tail
   cap 60 lines. Never fails the boot; errors go to the journal.
3. Triggered by `OnFailure=` of recover/first-boot/sd-provision/core and after
   `rosy-runtime.target` reaches active. Test the ordering in the unit contract.

## Task 4: L2 on-device collector

**Files:** `deploy/robot/native/rosy_diag/collect.py` (`rosy-diag collect`),
`test/test_diag_collect.py`

1. Bundle: `journalctl -b -u rosy-*` export (redacted), `systemctl status` of ROSY
   units, provisioning state, release activation journal, `dmesg` tail, network
   summary (addresses, SSID name, no PSK), L1 reports, `manifest.json` with hashes.
2. Bounded size (50 MiB), deterministic file names, redaction on every member;
   secret-scan the finished tar in the test.

## Task 5: L2 Windows puller with card fallback

**Files:** `deploy/robot/collect-rosy-diagnostics.ps1`,
`deploy/sd/read-card-diagnostics.py` (D-173 Task 8), `test/test_collect_diagnostics_contract.py`

1. SSH path: key-only, BatchMode, pinned host key → run `rosy-diag collect`,
   `scp` the bundle into `evidence/<device>/<boot_id>/`, never overwrite.
2. Card path: if SSH is unreachable and a card is inserted, copy FAT32
   `rosy-diag/` without elevation; with `-DeepRead` (elevated) run the read-only
   ext4 extractor for the journal. Document the `wsl --mount` USB limitation.

## Task 6: Refresh device readback for the native runtime

**Files:** `deploy/robot/device_readback.py`, `test/test_device_readback.py`

1. Replace container assumptions with systemd/native release facts; include the
   L1 latest report reference.

## Task 7: L3 read-only API (after L0-L2)

1. API Ref revision first (`/api/v1/system/boot-reports`, admin), then schema and
   route; reuses Task 3 output. Separate PR.

## Task 8: Runbook and acceptance

1. Runbook section "부팅이 조용히 실패했을 때": L1 → L2 → deep read order.
2. Build an image with F1 reintroduced (test-only tag), boot, collect L1 and L2,
   secret-scan both, then record evidence and close D-174 validation.

## Deferred

- L4 central aggregation with the central Fleet (D-170 timing), separate ADR.
