---
title: Upgrading the model-PC Learning Center in place needs the new commit's exact unit written first
date: 2026-10-23
category: deployment
module: deploy/model_pc/install_learning_center.py (rosy-learning-center.service)
problem_type: deployment_error
component: deployment
symptoms:
  - "install_learning_center.py --apply on a new commit: 'refusing to overwrite a conflicting Learning center unit'"
  - "after moving the old unit aside: 'state roots must be new, or owned by this identical installation'"
  - "the Learning Center stayed stopped until the backed-up unit was restored by hand"
root_cause: undocumented_upgrade_procedure
resolution_type: procedure
severity: medium
tags: [learning-center, model-pc, systemd, installer, upgrade, state-roots, rollback]
applies_when: "moving the running rosy-learning-center.service to a new commit while keeping its existing review state and OMX center root"
---

# Upgrading the Learning Center in place needs the new commit's exact unit written first

## Problem
`install_learning_center.py` keeps existing state roots (`--state`, the center `root`) only when the installed unit file is exactly the text this commit would write. With a different existing unit, it refuses to overwrite it. With no unit, it requires brand-new state roots. Neither direct path upgrades a running center while keeping its jobs, datasets and profiles. On 2026-10-23 the old unit was moved aside, the installer refused the existing state, and a shell pipeline (`installer | tail`) reported success. The rollback branch was skipped, so the center was down for 1–2 minutes until the backup was restored by hand.

## Procedure that worked
1. Check that no center job is running: only the `review_app.py` process is in the unit's cgroup, and no `experiment_train`/`experiment_online`/`experiment_export` process exists.
2. Clone the merged commit into `~/.local/share/rosy-learning-center/source/<full sha>`, detached and clean. The commit can come from GitHub into `~/rosy-test/repo` first.
3. Back up the current unit to `rosy-learning-center.service.bak-<old sha>-<date>`.
4. Generate the new unit text with the installer's own `prepare()`. Use the same `--state`, `--center-config`, `--python` and `--port` as the current `ExecStartPre`.
5. Stop the service, write that text over the unit, and run the installer with `--apply`. Branch on the installer's own exit status, not a pipeline's. On failure, copy the backup back, `daemon-reload` and start.
6. Verify: `is-active`, `ExecStart` names `source/<new sha>`, `curl http://127.0.0.1:8769/` returns 200, and the journal has no tracebacks.

Do not create new state roots to get past the refusal. A new root would start an empty center and lose the registered datasets, jobs and profiles.

## Evidence
Model PC, 2026-10-23: the center moved from `0cf9282aa3` to `c643281c44` (PR #154). The first attempt failed, and the restore came back on `0cf9282aa3` with HTTP 200. The second attempt with steps 4–5 returned `INSTALLED`, `active`, `source/c643281c4493` and HTTP 200, with no journal errors.
