---
title: Native hardware mode needs profile.yaml shipped and /etc/rosy edits canonicalized; direct file edits brick CORE restart admission
date: 2026-11-03
category: deployment
module: deploy/robot/pinky_pro/native, deploy/robot/pinky_pro/config, middleware/drive/planning/nav2
problem_type: deployment_error
component: deployment
symptoms:
  - "rosy-navigation.service exits at once on native release 2026.10.29-001: 'cannot read Device profile: /etc/rosy/profile.yaml'"
  - "after a hand edit of /etc/rosy/runtime.env (sed), rosy-core restart fails 'A dependency job for rosy-core.service failed'; rosy-sd-provision prints {\"phase\":\"HOLD\",\"reason\":\"OS_STATE_HOLD\"}"
  - "verify_ready fails with 'root setting differs from canonical projection' or 'shared data owner/group/permissions differ'"
  - "SLAM backend starts slam_toolbox with odom_frame 'odom', scan_topic '/scan' although the robot is namespaced"
root_cause: missing_rollout_step
resolution_type: procedure
applies_when:
  - "bringing a native (non-compose) Pinky Pro to ROSY_RUNTIME_MODE=hardware"
  - "changing anything under /etc/rosy or /var/lib/rosy on a provisioned A/B device"
  - "running the SLAM backend (ROSY_NAVIGATION_BACKEND=slam) on the device"
---

## Problem

Native hardware mode on geg6 (release 2026.10.29-001) could not start, and the
obvious fix path (edit `/etc/rosy/runtime.env`, restart) made CORE unable to
restart at all. Each failure surfaced as a different error; none named its cause.

## Cause

- The native payload never installs a device profile. Compose bind-mounts
  `config/profile.hardware.yaml` → `/etc/rosy/profile.yaml`
  (`deploy/robot/pinky_pro/compose.yaml`), but the native deployment path has no
  equivalent install, so `hardware.launch.py` aborts: no profile, no hardware
  graph.
- `/etc/rosy/runtime.env` is a **canonicalized A/B projection file**
  (`os_state_files.ROOT_FILES`). A direct edit diverges live bytes from the
  committed generation; the next `rosy-sd-provision` run fails
  `os_state_ready.verify_ready` → `OS_STATE_HOLD` → `rosy-core.service`
  dependency failure. The ready receipt from boot also goes stale after a new
  generation.
- `validate_shared_owners` pins exact ownership of shared dirs
  (`/var/lib/rosy/maps` = `rosy-io:rosy-core` mode 2750). A bench `chmod 0755`
  for map readability trips the same HOLD.
- On this Jazzy build the launch XML's `load_composable_node` entries are
  silently skipped / lose the namespace, and `write_prefixed_nav2_params`
  prefixes frame **values** but not node **section keys**, so standalone nodes
  keep defaults: slam_toolbox ran with unprefixed `odom`/`/scan` and never
  connected to the namespaced graph.

## Fix (bench procedure, robot-side)

1. Install the profile from the repo:
   `install -m 0644 config/profile.hardware.yaml /etc/rosy/profile.yaml`.
2. Change runtime mode only through the supported path (sudo, `python3 -I -B`):
   `from os_state_config import commit_runtime, common_lock` — read live bytes,
   `expected = shared._generation()[2]['etc/rosy/runtime.env']`, then
   `commit_runtime(root, live, expected=expected)`, then
   `from os_state_ready import publish_ready; publish_ready(root)`.
   Verify with `os_storage_dispatch.py --projected` → `"phase": "PROJECTED"`.
3. Never relax `/var/lib/rosy` permissions; read files as root instead.
4. Run Nav2 nodes standalone (not composed) with params that have **both**
   value prefix and `/rosy_42/<node>` section keys; same for
   `mapper_params.yaml` before starting slam_toolbox.

## Verification (2026-11-03, geg6)

- `readiness: {required: true, ready: true}`, all 9 Nav2 nodes `active [3]`.
- Forward 15 cm goal through CORE: `SUCCEEDED`, odom 0.040 m, LiDAR forward-min
  delta matched within 3–7 mm; reverse teleop −0.040 m matched LiDAR.
- SLAM backend: slam_toolbox active, `map → rosy_42/odom` TF, live map growing;
  a goal into unexplored space fails `STUCK` with `nav_cmd_vel` silent — expected
  for online SLAM without prior exploration.
- Restored: `ROSY_RUNTIME_MODE=motor`, backend `localization` (canonicalized),
  maps dir `rosy-io:rosy-core 2750`, bench readiness block removed, CORE healthy.

## Next

Ship `profile.hardware.yaml` in the native payload install (repo change, not
done in this bench session) and consider a native equivalent of the compose
readiness/profile wiring; until then every native unit hits symptom 1.
