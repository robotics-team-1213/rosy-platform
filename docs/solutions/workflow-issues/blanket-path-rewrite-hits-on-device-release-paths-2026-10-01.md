---
title: A blanket repo path rewrite also rewrote on-device release paths, and the tests copied the wrong strings
date: 2026-10-01
category: workflow-issues
module: deploy/robot/pinky_pro (image/customize-rootfs.sh, native/rosy-core.service, image/verify-mounted-image.py, image/first-boot/rosy-first-boot.py)
problem_type: build_error
component: development_workflow
symptoms:
  - "image build: FAIL: UART4 motor bus configuration is missing (customize-rootfs.sh looked for ../robot/configure-uart-pi5.sh)"
  - "image build: can't open /opt/rosy/releases/<id>/deploy/robot/pinky_pro/native/native_release.py"
  - "rosy-core.service ExecStartPost pointed at /opt/rosy/current/deploy/robot/pinky_pro/native/wait-core-ready.py, which no release contains"
  - "rosy-first-boot.py raised IndexError: 5 on import from /opt/rosy/first-boot (four parents)"
  - "payload build: PAYLOAD_METADATA_PRESENT: install/share/web_common/manifest.json"
root_cause: missing_validation
resolution_type: code_fix
severity: critical
tags: [folder-move, release-layout, image-build, payload-release, first-boot, contract-tests, d-225]
---

# A blanket repo path rewrite also rewrote on-device release paths, and the tests copied the wrong strings

## Problem
Commit e3b0c95e (2026-09-28) moved `deploy/robot/*` to `deploy/robot/pinky_pro/*`. It rewrote `deploy/robot/` to `deploy/robot/pinky_pro/` across 373 files. That was right for repo paths and wrong for three other kinds of path:

1. **Release-layout paths.** A release keeps its native runtime at `<release>/deploy/robot/native/` (on the device, not a repo path). That is fixed by `build-native-payload.sh` and `REQUIRED_PAYLOAD`, not by the repo layout. The rewrite pointed `customize-rootfs.sh`, `verify-mounted-image.py` and **`rosy-core.service`'s ExecStartPost** at `.../deploy/robot/pinky_pro/native/`, which does not exist on a device. On a new image, CORE would have failed right after start.
2. **Relative hops.** `$(dirname "$0")/../robot/...` and `SCRIPT_DIR/../..` counted one level short after the move. `rosy-first-boot.py` changed `parents[3]` to `parents[5]` in a module-level tuple. The installed copy at `/opt/rosy/first-boot` has four parents, so the import raised IndexError: first boot could never provision.
3. **Identity bytes.** See [payload-runtime-id-hashes-comments-too](payload-runtime-id-hashes-comments-too-2026-10-01.md).

Nothing failed on main for two days. The host tests had been rewritten by the same sed, so they asserted the broken strings. The ARM64 image and payload builds are manual `workflow_dispatch` jobs, so nobody ran them until the next device push.

A separate change broke the builds at the same time: 8bde27d9 installed `share/web_common/manifest.json` (since renamed to shared-assets.json by this fix). D-225 refuses that basename at any depth. The robot's `native_release.py` also drops it from its inventory, so an exemption in the builder would only have moved the failure onto the robot.

## Solution (f974d0e0, 5fd0c12e, 5c0ce600; local main 3e0dff12)
- Fix every relative hop and release-layout path. The /common allowlist is renamed to `shared-assets.json`.
- `test/test_release_layout_paths.py` scans deploy/ and test/ for `opt/rosy/(current|releases/<id>)/deploy/...` and `release / "deploy/..."`. It asserts each one against the payload builder's layout. Mutation check: re-breaking the unit or the verifier turns it red.
- `test/test_first_boot_installed_import.py` runs every first-boot entrypoint's `--help` with `__file__` set to `/opt/rosy/first-boot/<name>`.
- The customizer tests now check that the referenced scripts exist, not that the path string matches.
- A web_common test refuses installed files named `manifest.json`, `SHA256SUMS` or `SHA256SUMS.sig`.
- An independent review (code-reviewer agent) found the first-boot crash after the first two fixes. Without it, image 007 would have failed again after another 30-minute build.

## Prevention
- A folder move must separate three namespaces: **repo paths** (rewrite), **installed or release paths** (never rewrite; they are a device contract), and **identity-hashed bytes** (never touch).
- Tests must resolve a path and check that it exists, or derive it from the producer (the payload builder). A test that repeats the same string as the code is a tautology under sed.
- After any deploy/ move, run both ARM64 builds (`build-pinky-image.yml`, `build-native-payload.yml`) before calling the move done. Host pytest does not exercise the customizer or the payload metadata rules.
- Code that runs installed must not compute checkout-relative paths at import time with fixed `parents[N]`.

Related: [folder-move-widens-path-scoped-contract-tests](folder-move-widens-path-scoped-contract-tests-2026-09-25.md), [installed-layout-import-passes-repo-tests](installed-layout-import-passes-repo-tests-2026-09-22.md).
