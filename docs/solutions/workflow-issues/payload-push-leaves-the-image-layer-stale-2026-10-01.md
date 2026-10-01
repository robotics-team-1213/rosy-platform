---
title: A payload push updates install/ but silently leaves the image layer (units, native-runtime, udev) stale
date: 2026-10-01
category: workflow-issues
module: deploy/robot/pinky_pro (rosy-release-push.ps1, native/activate-release.sh)
problem_type: workflow_issue
component: development_workflow
applies_when: "pushing a payload release to a robot whose image predates changes to deploy/robot/pinky_pro/native units or scripts"
symptoms:
  - "after pushing 2026.09.30-008 to rosy-pinky-8kcn (image 2026.09.27-010), /etc/systemd/system/rosy-io.service still lacked enable_ir:=true"
  - "rosy-navigation.service lacked the new mapping_approval ExecCondition, and /opt/rosy/native-runtime/mapping_approval.py was missing"
  - "CORE readiness PASS gave no hint that any of this was stale"
root_cause: missing_workflow_step
resolution_type: workflow_improvement
severity: medium
tags: [payload-release, image-layer, d-225, d-388, drift, systemd-units, operator-workflow]
---

# A payload push updates install/ but silently leaves the image layer stale

## Context
D-225 payload releases replace `/opt/rosy/releases/<id>`, and `activate-release.sh` switches `/opt/rosy/current`. Nothing copies the release's own `<release>/deploy/robot/native/` (the on-device release layout) into the places the image installed it:
- `/etc/systemd/system/rosy-*`
- `/opt/rosy/native-runtime/`
- udev rules and modprobe confs (these are not in the payload at all)

A pushed robot therefore runs new CORE and ROS code under old unit files and old helper scripts. A card written from the same commit gets both layers new. The two robots then behave differently, and the only signal is a diff.

## Guidance
- After every push, diff the image layer against the release copy. The one-liner used on 2026-09-30:
  `for f in /opt/rosy/current/deploy/robot/native/*; do ... cmp -s "$f" /etc/systemd/system/$b || cmp -s "$f" /opt/rosy/native-runtime/$b ...`
  It reports NEW and DIFF files.
- Read each DIFF before installing it:
  - Some are comment or import-path noise, for example `rosy_config.py`, whose import falls back to `deploy.sd`.
  - Some change behaviour. `rosy-io.service` now starts `ir_adc_node`, and `rosy-navigation.service` gains a gate.
- Back up to `/var/lib/rosy-bench-backup/<ts>-<release>/`, install, run `daemon-reload`, and restart only the changed active units. Then confirm that the new instance's nodes started. `process has died` lines stamped with the old PID come from the old instance shutting down; they are not a failure.
- Automating this is D-388 (`feat/release-image-layer-sync`). The PC-side push runs a sync script shipped **inside the new release**, because old robots run old image-resident `activate-release.sh`. It uses an allowlist, backs up, rolls back with `-Rollback`, and never touches config.txt, the kernel, /usr/local Python or /etc/rosy.
- Base-layer changes (apt, /usr/local Python, config.txt, kernel) still need a card rewrite. The proposed next step is versioned one-time migrations shipped in the release, with Pi 5 `tryboot` for boot-config changes.

## Applicability
This applies to any robot pushed with a payload newer than its image. Until D-388 lands, step 6 of the `rosy-release-push` skill (the hand install) is mandatory, not optional.
