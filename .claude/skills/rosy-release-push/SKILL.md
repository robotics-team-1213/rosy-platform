---
name: rosy-release-push
description: Use when current main (CORE, dashboard, ROS nodes) must run on an existing Rosy robot without re-flashing the SD card — build a native payload release on the GitHub ARM64 runner, sign it on the operator PC, push and activate it with rosy-release-push.ps1, which then syncs the image layer (native-runtime scripts, rosy units, udev, modprobe) from the new release. Also when a dev overlay of newer main crashed CORE on an older release.
---

# Shipping main to a robot as a payload release (D-225)

## Overview

A payload release replaces everything under `/opt/rosy/releases/<id>` (`install/`, the
release's copy of `deploy/robot/pinky_pro/native`). Activation alone does **not** replace the
image layer. Since D-383 the push script then runs the new release's `sync-image-layer.py`,
which brings `/opt/rosy/native-runtime/*`, the rosy units in `/etc/systemd/system`, udev
rules and `/etc/modprobe.d` up to the release's copy (step 6). `/etc/rosy/*`, `config.txt`,
kernel modules, `/usr/local` Python and the first-boot units still need a new image.

Never use the CORE dev overlay (`deploy/robot/pinky_pro/dev`) to put newer main on an older release.
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
   python deploy/robot/pinky_pro/release/sign_image_release.py $P/x/<id> --private-key "$LOCALAPPDATA/Rosy/signing/<key>.private.pem" --public-key deploy/robot/pinky_pro/release/public-keys/<key>.pem
   python deploy/robot/pinky_pro/release/build_payload_release.py pack --release-dir $P/x/<id> --out $P/<id>.tar.gz --modes-from $P/<id>.unsigned.tar.gz --public-key deploy/robot/pinky_pro/release/public-keys/<key>.pem
   ```
   ```powershell
   deploy\\robot\\pinky_pro\rosy-release-push.ps1 -Robot <robot-ip> -Tarball <P>\<id>.tar.gz -PrintCommands   # dry run
   deploy\\robot\\pinky_pro\rosy-release-push.ps1 -Robot <robot-ip> -Tarball <P>\<id>.tar.gz
   ```
   - **Success** looks like `current release: <id> (previous: <old>)` followed by
     `CORE readiness: PASS`.
   - `/etc/rosy/runtime.env: Permission denied` is a known harmless defect: the readiness
     step runs as `rosy`, and the file is 0600.
   - **Automatic rollback:** a CORE that fails its 45 s readiness check is rolled back by
     `activate-release.sh`.
   - **Manual rollback:** `-Rollback`.
6. **Image-layer sync (automatic, D-383).** After `CORE readiness: PASS` the push runs
   `/opt/rosy/releases/<id>/deploy/robot/native/sync-image-layer.py` twice under `sudo -n`.
   `--dry-run` prints the JSON plan (`changed`, `new`, `unchanged`, `skipped`), then the
   apply runs.
   - The apply backs up every replaced file to `/var/lib/rosy/image-layer-backup/<UTC>-<id>/`
     with a `backup-manifest.json`, and installs atomically. It then runs `daemon-reload` and
     `udevadm control --reload`, and enables new units the image enables (`.path`/`.timer`
     with `--now`).
   - If one of those commands fails, `/var/lib/rosy/image-layer-backup/pending.json` keeps
     it. Re-run the push (or the sync): it re-runs the commands and offers the units again.
   - The push restarts the active units the apply lists in `restart_units`, prints
     `restarted: ...`, and checks CORE readiness again. Restarting `rosy-io` briefly stops
     the motors. `rosy-network`, `rosy-config`, `rosy-release-recover` and
     `rosy-sd-provision` are never restarted live; the push prints them as
     `takes effect next boot`.
   - Changed modprobe options print a warning. They apply at the next module load or reboot.
   - `-Rollback` runs rollback, then the sync from the release that became current, then
     the restarts, then CORE readiness. The sync removes files an earlier sync added that
     this release does not carry (disabling such units first) and restores files it
     replaced, unless someone changed them since. `-SkipImageLayerSync` turns the step
     off. `-PrintCommands` shows the steps without running them.
   - Files the image installed are never removed, even when a later release drops them.
   - Only a release that carries the script can sync. A robot syncs on its first push of
     such a release.

   **Manual fallback.** Use it when the sync failed or the file is outside its allowlist.
   Bench only; record it.
   - Take files from `/opt/rosy/current/deploy/robot/native/`. udev and modprobe files are in
     its `image-layer/udev/` and `image-layer/modprobe/`. A release older than D-383 lacks
     them, so copy them from the repo's `deploy/robot/pinky_pro/udev/` and `modprobe/`.
   - First back up every file you replace, for example into
     `/var/lib/rosy-bench-backup/<timestamp>/`.
   - Scripts go to `/opt/rosy/native-runtime/`, units to `/etc/systemd/system/`.
   - Then run `systemctl daemon-reload`, `udevadm control --reload`, and enable any new
     `.path` or `.service` units.
   - Reload a module whose options changed (`modprobe -r` then `modprobe`).
   - To undo an automatic sync, copy the files back from its backup directory and run the
     same reloads.
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
ADR D-225, D-247, D-260, D-383.
