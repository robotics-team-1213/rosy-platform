---
title: Upgrading the model-PC Learning Center in place needs the new commit's exact unit written first
date: 2026-10-23
category: deployment
module: deploy/model_pc/install_learning_center.py (rosy-learning-center.service), deploy/model_pc/install_review_release.py
problem_type: deployment_error
component: deployment
symptoms:
  - "install_learning_center.py --apply on a new commit: 'refusing to overwrite a conflicting Learning center unit'"
  - "after moving the old unit aside: 'state roots must be new, or owned by this identical installation'"
  - "the Learning Center stayed stopped until the backed-up unit was restored by hand"
  - "install_review_release.py --source <accepted D-446 release>: 'release source contains a symlink'"
  - "with a link-free copy inside --root: 'source, release root, and review state must be separate'"
root_cause: undocumented_upgrade_procedure
resolution_type: procedure
severity: medium
tags: [learning-center, model-pc, systemd, installer, upgrade, state-roots, rollback, review-release, d-446, tls]
applies_when: "moving the running rosy-learning-center.service to a new commit while keeping its existing review state and OMX center root, or installing an accepted D-446 model-code release on the protected Learning center with install_review_release.py"
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

## Installing an accepted D-446 model-code release with `install_review_release.py`
The protected Learning center's review app is installed from an accepted D-446 model-code release, not from a Git clone. Two direct sources are refused:

- The accepted release folder `~/.local/share/rosy/model-code/releases/<seq>-<sha>` holds a `data` symlink. `check_source()` refuses any symlink: `release source contains a symlink`.
- A link-free copy placed inside the installer's `--root` folder is refused too: `source, release root, and review state must be separate`. The source, `--root` and `--state` must not contain one another.

Procedure that worked:
1. Copy the release without `data` to a sibling folder outside `--root`, for example `~/rosy-ml/edge-capture/review-sources/model-code-<seq>-<sha12>`: `mkdir -p <copy> && tar -C ~/.local/share/rosy/model-code/releases/<seq>-<sha> --exclude=./data -cf - . | tar -C <copy> -xf -`.
2. Check the copy against the release: `diff -r --exclude=data <release> <copy>` prints nothing.
3. Back up the review state with the SQLite backup API, not `cp` of a live database: `python3 -c "import sqlite3; sqlite3.connect('<state>/reviews.sqlite3').backup(sqlite3.connect('<backup>.sqlite3'))"`.
4. Run the installer with `--source <copy>` and the service's current `--root`, `--state`, `--python`, `--host 127.0.0.1`, `--port` and `--service`. Read the installer's own exit code (`python3 install_review_release.py ...; echo $?`), not the exit code of a pipe such as `| tail`.
5. After `INSTALLED`, check the HTTPS front by the host's Tailscale name: `curl -sS -o /dev/null -w '%{http_code}
' https://<host-tailscale-name>:<port>/accounts`. Using the IP address gives a TLS internal error, because the front serves its certificate by name only. That error is not an install failure.

Evidence: protected Learning center, 2026-10-24, sequence 32. The installer exited 1 on the release folder (symlink), 1 on the copy inside `--root` (not separate), then 0 on the sibling copy outside `--root`.

The source rule is also stated in `deploy/model_pc/README.md` beside the project install command.
