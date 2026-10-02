---
name: rosy-release-push
description: Use when current main (CORE, dashboard, ROS nodes) must run on an existing Rosy robot without re-flashing the SD card — build a native payload release on the GitHub ARM64 runner, sign it on the operator PC, push and activate it with rosy-release-push.ps1, which then syncs the image layer (native-runtime scripts, rosy units, udev, modprobe) from the new release. Also to publish a release for the robots' automatic update (D-406: canary, withdraw, per-robot hold), and when a dev overlay of newer main crashed CORE on an older release.
---

# Shipping main to a robot as a payload release (D-225)

## Overview

A payload release replaces everything under `/opt/rosy/releases/<id>` (`install/`, the
release's copy of `deploy/robot/pinky_pro/native`). Activation alone does **not** replace the
image layer. Since D-388 the push script then runs the new release's `sync-image-layer.py`,
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
3. **Download, check, sign and pack with one command.** Run with `PYTHONUTF8=1` on Windows.
   ```powershell
   python tools/release/prepare_payload_release.py --run <run-id> --robot <robot-ip>
   ```
   - It finds the run's `rosy-native-payload-unsigned-<id>-<sha>` artifact and downloads it
     with `download_artifact.py`. The work folder is `--out-dir`, default
     `X:\DevTemp\rosy-release-<id>`. Already downloaded? Pass `--artifact-dir <dir>`.
   - It checks that every name in `required-ros-packages.txt` is in `rosy-packages.txt`.
     Both list ROSY workspace packages, not debs.
   - It runs a read-only `dpkg-query -W` over SSH on each `--robot` (repeatable) and prints
     one verdict per robot. The query lists `ros-jazzy-*` packages with their status. Every
     package installed on both sides must have the same version (C++ ABI). Packages that
     exist only on the runner (gz, rqt, rviz, fastrtps) are fine. Only status `ii` counts as
     installed: an `rc` package (removed, config files left) still reports its old version
     and is ignored, and so is an empty version. Comparing zero packages fails.
     `--skip-abi` skips this check.
   - It extracts `<id>.unsigned.tar.gz` into `<out>/x/<id>` through a temp folder and a
     rename. An existing `<out>/x/<id>` is refused: remove it or use a new `--out-dir`.
     It never signs the artifact folder, because that folder drops dotfiles.
   - It signs with `%LOCALAPPDATA%\Rosy\signing\<key>.private.pem` (`--key-name`, default
     `rosy-release-2026-01`), packs `<out>/<id>.tar.gz` with `--modes-from`, and prints
     the two push lines below. It never pushes.
   - Each phase prints its wall time. Release 021 (a 98 MB artifact) took 99 s to download
     and 28 s for everything else.
4. **Manual fallback** (the same steps by hand). The artifact folder drops dotfiles such
   as `install/.colcon_install_layout`, so signing it fails with `CHECKSUM_FILE_MISSING`.
   Sign from the tarball. The tarball has no top-level directory. Compare `ros-packages.txt`
   (`name=version`) with the robot's
   `dpkg-query -W -f='${db:Status-Abbrev}\t${binary:Package}\t${Version}\n' 'ros-jazzy-*'`
   (`status<TAB>name<TAB>version`, keep only `ii` lines) as described in step 3.
   ```bash
   gh run download <run-id> -n rosy-native-payload-unsigned-<id>-<sha> -D $P
   mkdir -p $P/x/<id> && python -c "import tarfile,sys; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter='tar')" $P/<id>.unsigned.tar.gz $P/x/<id>
   python deploy/robot/pinky_pro/release/sign_image_release.py $P/x/<id> --private-key "$LOCALAPPDATA/Rosy/signing/<key>.private.pem" --public-key deploy/robot/pinky_pro/release/public-keys/<key>.pem
   python deploy/robot/pinky_pro/release/build_payload_release.py pack --release-dir $P/x/<id> --out $P/<id>.tar.gz --modes-from $P/<id>.unsigned.tar.gz --public-key deploy/robot/pinky_pro/release/public-keys/<key>.pem
   ```
5. **Push and activate.**
   ```powershell
   deploy\\robot\\pinky_pro\rosy-release-push.ps1 -Robot <robot-ip> -Tarball <P>\<id>.tar.gz -PrintCommands   # dry run
   deploy\\robot\\pinky_pro\rosy-release-push.ps1 -Robot <robot-ip> -Tarball <P>\<id>.tar.gz
   ```
   - **Success** looks like `current release: <id> (previous: <old>)`, then
     `CORE runs the activated release: /opt/rosy/releases/<id>`, then `CORE readiness: PASS`.
   - `WARNING: CORE was still running the previous release after the switch ... restarted
     rosy-core` means the robot's installed activator predates the 2026-10-01 fix (it stopped
     only `rosy-runtime.target`, so CORE kept the old release while readiness passed). The
     push restarted CORE, and the image-layer sync installs the fixed activator, so the
     warning should not come back on that robot.
   - Activation now really stops CORE, so `rosy-navigation` (it `Requires=rosy-core`, not
     part of the target) stops too and stays stopped. Start it again through its approval
     path; it is not part of the runtime target (D-291).
   - `CORE did not start ...` stops the push: no CORE is running. Run `-Rollback` (or read
     `journalctl -u rosy-core` if it was a rollback).
   - `/etc/rosy/runtime.env: Permission denied` is a known harmless defect: the readiness
     step runs as `rosy`, and the file is 0600.
   - **Automatic rollback:** a CORE that fails its 45 s readiness check is rolled back by
     `activate-release.sh`.
   - **Manual rollback:** `-Rollback`.
   - **Calibration guard (D-321 addendum):** before the first remote step the script asks
     CORE `GET /api/v1/calibration/session`. Give it a token through `ROSY_API_TOKEN` or the
     DPAPI device credential (`%LOCALAPPDATA%\Rosy\api\<robot>.credential.xml`); use
     `-ApiToken` only as a last resort, because a command-line token lands in shell history
     and the process list. HTTP 401/403 means the token is wrong, not that CORE is down. An active session **refuses** the push (`REFUSED ... would
     interrupt a running calibration`) — wait for it, ask its owner to end it, or pass
     `-Force` only when you know the calibration is abandoned. No token or no answer only
     warns. `-PrintCommands` skips the check.
6. **Image-layer sync (automatic, D-388).** After `CORE readiness: PASS` the push runs
   `/opt/rosy/releases/<id>/deploy/robot/native/sync-image-layer.py` twice under `sudo -n`.
   `--dry-run` prints the JSON plan (`changed`, `new`, `unchanged`, `skipped`), then the
   apply runs.
   - The apply backs up every replaced file to `/var/lib/rosy/image-layer-backup/<serial>-<UTC>-<id>/`
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
     its `image-layer/udev/` and `image-layer/modprobe/`. A release older than D-388 lacks
     them, so copy them from the repo's `deploy/robot/pinky_pro/udev/` and `modprobe/`.
   - First back up every file you replace, for example into
     `/var/lib/rosy-bench-backup/<timestamp>/`.
   - Scripts go to `/opt/rosy/native-runtime/`, units to `/etc/systemd/system/`.
   - Then run `systemctl daemon-reload`, `udevadm control --reload`, and enable any new
     `.path` or `.service` units.
   - Any `systemctl restart` of `rosy-core`/`rosy-runtime.target` ends a calibration drive:
     run `deploy/robot/pinky_pro/rosy-calibration-guard.ps1 -Robot <robot-ip>` first
     (exit 3 = a session is active).
   - Reload a module whose options changed (`modprobe -r` then `modprobe`).
   - To undo an automatic sync, copy the files back from its backup directory and run the
     same reloads.
7. **Verify on the live dashboard.** Use `rosy-dashboard-drive` and an administrator code
   from `rosy-device-access`. Check the changed surfaces, log the session out, and delete
   any local token file.

## Automatic rollout (D-406)

Robots with `rosy-auto-update.timer` fetch signed releases from GitHub themselves and apply
them only when idle. This PC still decides what ships: nothing reaches a robot until it is
published here.

- **Off by default (2026-10-02).** Until the first two-robot device validation, a robot
  auto-updates only when `/var/lib/rosy/updates/config.json` says so. Turn it on per robot
  over ssh (and off again by writing `false` or deleting the file):
  ```bash
  rssh 'sudo -n install -d -m 0755 /var/lib/rosy/updates && echo "{\"enabled\": true, \"repo\": \"livsbittt/rosy-os\"}" | sudo -n tee /var/lib/rosy/updates/config.json'
  ```
  Put a hold on any robot a peer is testing on first (`rosy-update-hold.ps1 -Robot <ip> -Hold ...`).

- **Publish.** After step 3, instead of pushing:
  ```powershell
  python tools/release/publish_payload_release.py --tarball <P>\<id>.tar.gz --canary <canary-ip> --robot <other-ip>
  ```
  It creates GitHub Release `payload-<id>` on `livsbittt/rosy-os` (tag on the tarball's
  `source-revision.txt`) with the tarball, `rollout.json` and `rollout.json.sig`. The rollout
  names the canary by hostname (`ssh hostname`) and is signed with the release key, then
  verified before upload. An existing tag is refused; `--resume` re-attaches to it.
- **Canary.** The command polls the canary's `rosy_auto_update.py status --json` every 30 s
  and prints each phase. A commit of this id re-signs the rollout with `canary_ok=true`;
  the other robots apply after `published_at + wave_delay_s` (default 600 s). A rollback or
  refusal of this id, or no commit within `--canary-timeout-min` (default 30), re-signs it
  with `withdrawn=true` and exits non-zero. If the PC stops mid-watch, the others wait;
  rerun with `--release-id <id> --canary <ip> --resume` (Ctrl+C prints that command and the
  `--withdraw` one). Only one publish per release id runs at a time (`publish-<id>\.lock`
  in the work folder). Before its final upload the watch re-reads the rollout on GitHub:
  a release withdrawn meanwhile stays withdrawn.
- **Withdraw by hand:** `--release-id <id> --withdraw --reason "<why>"`. Robots that already
  applied it stay on it; roll them back with a newer release or `-Rollback`.
- **Hold** a robot before a test, drive or seal, and release it after:
  ```powershell
  deploy\robot\pinky_pro\rosy-update-hold.ps1 -Robot <ip> -Hold -Reason "G4 recording" -Hours 4
  deploy\robot\pinky_pro\rosy-update-hold.ps1 -Robot <ip> -Release
  deploy\robot\pinky_pro\rosy-update-hold.ps1 -Robot <ip> -Status
  ```
  A hold always expires (at most 168 h). The reason allows letters, digits, space and
  `. , : _ / ( ) + = @ -`. A held robot still stages the release.
- Audit lines go to `X:\DevTemp\rosy-rollout-evidence\<date>\rollout.jsonl`.
- **Use a manual push (steps 5-6) when** the robot has no updater yet (its first D-406
  release arrives by push), it is offline from GitHub, you need a release on one robot only,
  or you are rolling back. The push takes the same claim as the updater
  (`rosy_claim.py acquire --purpose push`) and releases it at the end; `claimed by another
  job` means an update is running, so wait. A robot without the helper only warns.

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
ADR D-225, D-247, D-260, D-388, D-406.
