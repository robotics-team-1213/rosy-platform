---
name: rosy-fast-field-test
description: Use when a model or code change must be seen driving on a real Pinky as fast as possible during development — choosing between an on-robot script loop over the CORE API, a model pointer swap and a payload release, copying a script and model to the robot with a sha256 check, running a dry run then a capped drive, or when the release path is slow (pre-push affected tier, ARM64 build, unknown overlay keys) and someone wants to skip tests to get to the robot.
---

# Fastest path from a change to a real Pinky drive

## Overview

The first field result comes from the path that needs **no release**. The release path runs
beside it the same day. Lesson and the 2026-10-10 numbers:
`docs/solutions/workflow-issues/first-field-result-from-the-no-release-path-release-in-parallel-2026-10-10.md`.
First check that the runtime consumes the output at all:
`docs/solutions/workflow-issues/check-the-runtime-consumes-a-learned-output-before-training-it-2026-10-10.md`.

SSH helper `rssh`, administrator login code and token pairing: `rosy-device-access`.
The person on site rule (D-574) and `rosy-update-hold.ps1` before a drive: `rosy-release-push`.
This repo is public: write `<robot-ip>` in anything tracked.

## Decision table

| Change | Without a release | Needs a release |
|---|---|---|
| New steering/decision logic you can express as "frame/scan in, teleop out" | **On-robot loop** (below) through CORE `POST /api/v1/teleop` (`MANUAL`) | Same logic inside a ROS node |
| New model weights for the output the runtime already reads (`lane_marking` role for paint) | **Model pointer swap** (below) | — |
| New model output the runtime does not read yet (drivable, new class) | On-robot loop reads it itself | Consumer path in the node (e.g. D-597 `learned_paint_target`) |
| Value of an overlay key the **installed** release knows (`line_observer_overrides show`) | `line_observer_overrides apply` (restarts only `rosy-camera`) | — |
| New overlay key or ROS parameter | — | Yes. The installed release's `OPERATOR_KEYS` rejects an unknown key and the **whole** overlay is skipped |
| CORE, dashboard, units, image-layer scripts | — | Yes (`rosy-release-push`) |

## On-robot loop (D-592 pattern)

The loop runs **on the robot** (camera topic about 8 Hz, frame age ~15 ms). Off-board through
the MJPEG preview gets 1-2 fps and frames 0.6-1.1 s old, which fails a 0.5 s stale limit.
CORE stays the only `/cmd_vel` publisher; its body stop and 500 ms teleop watchdog stay on.
The reference tool is `tools/capture/drivable_steer.py` (branch
`feat/drivable-steer-field-test` until it lands). Its `--drive` caps are enforced in argparse:
linear ≤ 0.03 m/s, |angular| ≤ 0.4 rad/s, `--max-s` ≤ 120.

1. **Bundle the committed code and copy it.** The tool imports `contracts/foundation/core_common`
   and `middleware/perception/control`, so ship those with `tools/capture`. Scratch on the PC
   goes to `X:\DevTemp\<topic>\`.
   ```bash
   git archive HEAD contracts/foundation/core_common middleware/perception/control tools/capture \
     -o X:/DevTemp/<topic>/bundle.tar
   rssh 'mkdir -p ~/<topic>/repo ~/<topic>/model ~/<topic>/runs'
   scp -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile="$KH" \
     X:/DevTemp/<topic>/bundle.tar rosy@"$R":<topic>/bundle.tar
   rssh 'tar -xf ~/<topic>/bundle.tar -C ~/<topic>/repo'
   ```
2. **Copy the model with a sha256 check.** `/var/lib/rosy/models` is `root:rosy-camera` 0750;
   the `rosy` user cannot read it. Copy the model folder (`model_manifest.json` and the files it
   lists) to `~/<topic>/model` and compare hashes on both sides. `drivable_steer.py` re-checks
   the manifest hashes at start.
   ```bash
   sha256sum <model-dir>/model.onnx
   scp -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile="$KH" \
     <model-dir>/* rosy@"$R":<topic>/model/
   rssh 'sha256sum ~/<topic>/model/model.onnx'
   ```
3. **Token.** Pair an administrator login code (`rosy-device-access`) and write the token to
   `~/<topic>/token` (0600) on the robot. Never print it or put it in argv
   (`--token-file` / `ROSY_CORE_OPERATOR_TOKEN_FILE`). A development robot with D-548 dev mode
   (`/etc/rosy/dev-mode`) accepts `rosy-dev-operator` instead; never create that marker on a
   field, demo or shared-network robot.
4. **Runner.** Write `~/<topic>/run.sh` on the robot (the 2026-10-10 runner):
   ```bash
   #!/bin/bash
   # usage: run.sh OUTNAME [drivable_steer args...]
   source /opt/ros/jazzy/setup.bash
   set -a; source <(sudo -n cat /etc/rosy/runtime.env); set +a
   export CYCLONEDDS_URI=file:///etc/rosy/cyclonedds.xml
   export PYTHONPATH=/opt/rosy/learned-perception/site-packages${PYTHONPATH:+:$PYTHONPATH}
   chmod 600 ~/<topic>/token
   out=~/<topic>/runs/$1; shift
   mkdir -p "$out"
   cd ~/<topic>/repo
   exec python3 tools/capture/drivable_steer.py --robot 127.0.0.1 --token-file ~/<topic>/token --insecure \
     --model ~/<topic>/model --source ros --topic /${ROSY_NAMESPACE}/camera/front --out "$out" "$@"
   ```
   ONNX Runtime comes from `/opt/rosy/learned-perception/site-packages`. On a loaded Pi 4
   `--threads 2` was fastest (crop128: 171 ms p50; default 227 ms, 4 threads 247 ms).
5. **Dry run first** (nothing sent to CORE). Check the error sign against the overlay frames,
   inference and frame-age p50/p95, and that `stale` stays 0.
   ```bash
   rssh 'bash ~/<topic>/run.sh dry1 --threads 2'
   ```
6. **Drive with caps**, a person on site, and the update hold set. `--record` runs a CORE
   recording for the drive; run the ceiling recording (`tools/capture/ceiling_record.py`)
   beside it.
   ```bash
   rssh 'bash ~/<topic>/run.sh drive1 --threads 2 --drive --record --max-s 60'
   ```
   Every stop reason (low fraction, stale frame, LiDAR guard, time cap) sends zero and ends
   the run with mode `IDLE`. After any crash, check `GET /api/v1/robot/state` shows `IDLE`.
7. **Clean up.** `POST /api/v1/auth/logout` with the token (204), then
   `rssh 'rm -f ~/<topic>/token'`. Copy `~/<topic>/runs/<run>/` (`cycles.jsonl`, `frames/`,
   `summary.json`) to `X:\DevTemp\<topic>\` and write the record under `docs/validation/`.

A new loop of your own follows the same contract: frame or scan in,
`POST /api/v1/mode {"mode": "MANUAL"}`, then `POST /api/v1/teleop {"linear", "angular"}`
every ≤ 0.15 s (watchdog 500 ms), zero teleop and `POST /api/v1/mode {"mode": "IDLE"}` on
every stop path, sending off by default (a `--drive` flag turns it on). Reuse `Core` and
`tls_context` from `tools/capture/edge_drive.py`.

## Model pointer swap

Only changes what the installed runtime already consumes (paint reads the `lane_marking`
role only). Run `deliver.py` from the model PC repo, which owns model work:

```bash
python learning/training/perception/model/deliver.py status <robot-host> --slot paint
python learning/training/perception/model/deliver.py push <robot-host> <revision> --slot paint
python learning/training/perception/model/deliver.py rollback <robot-host> --slot paint
```

`push` needs a passing `intake_report.json`. Nothing reads `paint` unless the overlay sets
`learned_lane_pointer: /var/lib/rosy/models/paint` with `paint_source: learned`
(`line_observer_overrides apply --paint-source learned --model-pointer /var/lib/rosy/models/paint ...`;
the exact root shell line is in `rosy-release-push` Pitfalls). The first paint push leaves no
`paint.previous`, so rollback refuses until a second push.

## Release track, in parallel

Start it while the loop runs, once the user says land and push:

1. Land: `python tools/land.py --tests auto` from the worktree (`rosy-land-on-main`).
2. Push. Before pushing, `git rev-list --count origin/main..main`. The pre-push affected tier
   is measured from `git merge-base <pushed> origin/main`; 97 commits ahead on 2026-10-10 made
   it huge and met two unrelated guard failures. Push each landing the user approved right away
   so this count stays small.
3. Build, sign and ship: `rosy-release-push` (D-553 `robot_cd.py` starts the unsigned ARM64
   build beside CI when main moves on origin). Builds 069-071 took 4m19s-6m36s, then
   download, sign, push and restart per robot.
4. Only after the new release is on the robot, write any new overlay key, then
   `line_observer_overrides show` must say launch loads it.

## Forbidden

- CORE dev overlay (`deploy/robot/pinky_pro/dev/`) of newer main onto an older release: CORE
  crash-loops and takes the dashboard down.
- pytest, browser tests or Gazebo on the laptop (D-584). Use `tools/remote/remote_pytest.py`
  (`--pick sim` for Gazebo). No reachable test host means "not checked", not a pass.
- An overlay key the installed release does not know: the whole overlay is skipped.
- Skipping a gate (`tools/land.py --tests none`, `git push --no-verify`) without the user's
  explicit words. When they say it, report what was skipped.
- Adding someone else's failure to `test/known_failures.txt`; find the introducing commit
  (`prepush-gate-red-from-other-sessions-unpushed-commits-2026-10-10.md`).
- `pkill -f <pattern>` over ssh with the pattern in the same command line: it kills its own
  shell (`pkill-f-over-ssh-kills-its-own-shell-2026-10-10.md`).

## Related

`rosy-device-access`, `rosy-release-push`, `rosy-land-on-main`, `rosy-dashboard-drive`;
ADR D-548, D-553, D-584, D-592, D-597; `docs/validation/d592-drivable-steer-field-test-2026-10-10.md`
(branch `feat/drivable-steer-field-test`).
