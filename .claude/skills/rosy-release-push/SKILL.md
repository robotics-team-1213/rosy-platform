---
name: rosy-release-push
description: Use when current main (CORE, dashboard, ROS nodes) must run on an existing Rosy robot without re-flashing the SD card — build a native payload release on the GitHub ARM64 runner, sign it on the operator PC, push and activate it with rosy-release-push.ps1, then hand-install the image-only native-runtime units the payload does not carry. Also when a dev overlay of newer main crashed CORE on an older release.
---

# Shipping main to a robot as a payload release (D-225)

## Overview

A payload release replaces everything under `/opt/rosy/releases/<id>` (`install/`, the
release's copy of `deploy/robot/native`). It does **not** replace the image layer:
`/opt/rosy/native-runtime/*`, `/etc/systemd/system/*` units, udev rules, `/etc/modprobe.d`,
`/etc/rosy/*`, `config.txt`, kernel modules. Those need a new image, or a bench hand-install
(step 6).

Never use the CORE dev overlay (`deploy/robot/dev`) to put newer main on an older release.
After the D-241..D-243 moves CORE looks up the `pinky_pro` robot package, which an older
release does not ship, so CORE crash-loops and takes the dashboard down.

Verified twice on 2026-09-26: releases 013 and 014 on a Pinky Pro running image release 012.

## Steps

1. **Commit and push.** The runner builds the pushed commit on origin. It must be a clean
   tree on `main`. Local uncommitted files from other sessions do not matter; only the
   pushed commit does.
   ```bash
   git push origin main
   ```
2. **Pick the release id and build.** The format is `YYYY.MM.DD-NNN`. `NNN` continues
   across dates (012 → 013 → 014). Check `/opt/rosy/releases/` on the robot and the
   existing tags. Never reuse an id: an existing id is only re-checked, never overwritten.
   ```bash
   gh workflow run build-native-payload.yml --ref main -f release_id=<id>
   gh run watch <run-id> --exit-status --interval 30
   ```
3. **Download the artifact, then sign from the tarball, not from the artifact folder.**
   The artifact folder drops dotfiles such as `install/.colcon_install_layout`, so signing
   it fails with `CHECKSUM_FILE_MISSING`. Extract `<id>.unsigned.tar.gz` into a folder
   named after the release id. The tarball has no top-level directory.
   ```bash
   gh run download <run-id> -n rosy-native-payload-unsigned-<id>-<sha> -D $P
   mkdir -p $P/x/<id> && python -c "import tarfile,sys; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter='tar')" $P/<id>.unsigned.tar.gz $P/x/<id>
   ```
4. **Compare ROS package versions with the robot** before signing. Every
   `ros-jazzy-*` package present in both `ros-packages.txt` and the robot's `dpkg-query`
   output must have the same version (C++ ABI). Packages that exist only on the runner (gz,
   rqt, rviz, fastrtps) are fine if `required-ros-packages.txt` does not name them.
   Also check that every required package is installed on the robot.
5. **Sign, pack, push, activate.** Run with `PYTHONUTF8=1` on Windows.
   ```bash
   python deploy/release/sign_image_release.py $P/x/<id> --private-key "$LOCALAPPDATA/Rosy/signing/<key>.private.pem" --public-key deploy/release/public-keys/<key>.pem
   python deploy/release/build_payload_release.py pack --release-dir $P/x/<id> --out $P/<id>.tar.gz --modes-from $P/<id>.unsigned.tar.gz --public-key deploy/release/public-keys/<key>.pem
   ```
   ```powershell
   deploy\robot\rosy-release-push.ps1 -Robot <robot-ip> -Tarball <P>\<id>.tar.gz -PrintCommands   # dry run
   deploy\robot\rosy-release-push.ps1 -Robot <robot-ip> -Tarball <P>\<id>.tar.gz
   ```
   - **Success** looks like `current release: <id> (previous: <old>)` followed by
     `CORE readiness: PASS`.
   - `/etc/rosy/runtime.env: Permission denied` is a known harmless defect: the readiness
     step runs as `rosy`, and the file is 0600.
   - **Automatic rollback:** a CORE that fails its 45 s readiness check is rolled back by
     `activate-release.sh`.
   - **Manual rollback:** `-Rollback`.
6. **Hand-install the image-only pieces** (bench only; record it). Take them from the
   release's own copy, `/opt/rosy/current/deploy/robot/native/`. udev and modprobe files are
   not in the payload, so copy them from the repo's `deploy/robot/udev/` and
   `deploy/robot/modprobe/`.
   - First back up every file you replace, for example into
     `/var/lib/rosy-bench-backup/<timestamp>/`.
   - Scripts go to `/opt/rosy/native-runtime/`, units to `/etc/systemd/system/`.
   - Then run `systemctl daemon-reload`, `udevadm control --reload`, and enable any new
     `.path` or `.service` units.
   - Reload a module whose options changed (`modprobe -r` then `modprobe`).
7. **Verify on the live dashboard.** Use `rosy-dashboard-drive` and an administrator code
   from `rosy-device-access`. Check the changed surfaces, log the session out, and delete
   any local token file.

## Pitfalls seen

- **Board-device work collides with other sessions on main.** Merge main into your branch
  first, run the tests there, then fast-forward (see `rosy-land-on-main`).
- **A buzzer test says `busy` while `rosy-boot-display` owns the line**
  (`ROSY_BUZZER_ENABLED=true`). That is the collision guard working. Set it to false,
  restart the boot display, run the test, then restore it. D-260 must resolve this before
  the buzzer defaults on.
- **Dashboard CSP forbids `page.wait_for_function("<string>")`.** It fails with
  `unsafe-eval`. Poll locators from Python instead.

## Related

`rosy-device-access`, `rosy-hw-bringup`, `rosy-land-on-main`, `rosy-dashboard-drive`;
ADR D-225, D-247, D-260.
