---
title: Upgrading the model-PC Learning Center in place needs the new commit's exact unit written first
date: 2026-10-23
last_updated: 2026-11-13
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
applies_when: "history only — the rosy-learning-center.service candidate was retired on 2026-10-31, so the in-place upgrade procedure is kept as history; the install_review_release.py sections still apply to the live protected center (rosy-edge-review, 8768)"
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
Model PC, 2026-10-23: the center moved from its previous installation to `c643281c44` (PR #154). The first attempt failed, and the restore returned the previous installation with HTTP 200. The second attempt with steps 4–5 returned `INSTALLED`, `active`, `source/c643281c4493` and HTTP 200, with no journal errors.

## Installing an accepted D-446 model-code release with `install_review_release.py`
The protected Learning center's review app is installed from an accepted D-446 model-code release, not from a Git clone. Two direct sources are refused:

- The accepted release folder `~/.local/share/rosy/model-code/releases/<seq>-<sha>` holds a `data` symlink. `check_source()` refuses any symlink: `release source contains a symlink`.
- A link-free copy placed inside the installer's `--root` folder is refused too: `source, release root, and review state must be separate`. The source, `--root` and `--state` must not contain one another.

Procedure that worked:
1. Copy the release without `data` to a sibling folder outside `--root`, for example `~/rosy-ml/edge-capture/review-sources/model-code-<seq>-<sha12>`: `mkdir -p <copy> && tar -C ~/.local/share/rosy/model-code/releases/<seq>-<sha> --exclude=./data -cf - . | tar -C <copy> -xf -`.
2. Check the copy against the release: `diff -r --exclude=data <release> <copy>` prints nothing.
3. Back up the review state with the SQLite backup API, not `cp` of a live database: `python3 -c "import sqlite3; sqlite3.connect('<state>/reviews.sqlite3').backup(sqlite3.connect('<backup>.sqlite3'))"`.
4. Run the installer with `--source <copy>` and the service's current `--root`, `--state`, `--python`, `--host 127.0.0.1`, `--port` and `--service`. Read the installer's own exit code (`python3 install_review_release.py ...; echo $?`), not the exit code of a pipe such as `| tail`.
5. After `INSTALLED`, check the HTTPS front by the host's Tailscale name: `curl -sS -o /dev/null -w '%{http_code}\n' https://<host-tailscale-name>:<port>/accounts`. Using the IP address gives a TLS internal error, because the front serves its certificate by name only. That error is not an install failure.

Evidence: protected Learning center, 2026-10-24, sequence 32. The installer exited 1 on the release folder (symlink), 1 on the copy inside `--root` (not separate), then 0 on the sibling copy outside `--root`.

### Earlier manual hotfix recovery using the accepted-sequence floor

On 2026-11-03 a verified hotfix activated successfully on both review services, then the periodic review updater reactivated an older accepted signed release. Immediate HTTP readiness and a matching `current` link had not proved the hotfix would remain active. The updater's environment still allowed that older sequence.

`auto_review_release.apply_locked()` stops when the accepted model-code sequence is at or below `minimum_sequence`. Otherwise an existing `model-code-<sequence>-<commit>` directory is eligible for activation again even when a newer manual review hotfix is active. It does not compare the hotfix's Git ancestry.

Before activating a manual hotfix, inspect the accepted model-code `state.json` and the review updater's `EnvironmentFile`. Back up the environment file and raise `MINIMUM_SEQUENCE` to at least that currently accepted sequence. Do not invent a future sequence or disable signature checks. Keep the updater enabled so a later accepted sequence remains eligible. Then activate the hotfix with the supported installer and verify both the `current` links and the next updater execution. A run that only reports waiting for a learning lock is separate from exercising the sequence guard.

Verification: the old accepted source matched its Git ancestor across 812 installed files; both services had reverted to that release. After advancing the floor from 19 to the accepted 44, the installer restored the hotfix on both services and an explicit updater execution left their links unchanged. That execution reported waiting for the learning lock. A separate read-only `apply_locked()` check with the real accepted state and floor returned `waiting for a newer accepted model-code release`, exercising the sequence guard without activating code. The operational label database was not restored or replaced.

Prevention: for manual hotfixes, include automatic update eligibility and a later activation check in acceptance evidence; an immediate successful restart is insufficient. Restore the backed-up environment only when returning to the corresponding signed release policy, without overwriting newer review labels.

The source rule is also stated in `deploy/model_pc/README.md` beside the project install command.

### Keep individual review UIs pinned without changing the shared floor

Integration status: the per-UI hold implementation has passed the software checks below on its topic branch; canonical landing, publication and operational installation remain pending.

The earlier floor recovery changed the shared updater policy. When only two review UIs must keep a manual source while the other UIs continue following accepted releases, changing that floor or stopping the shared timer affects more than the requested scope. The accepted model-code state is not the authority for an individual UI's manual hold.

Use the review root's `manual-hold.json` through `install_review_release.py --root <review-root> --service <review-service> --hold`, or add `--hold` to its manual installation command. The private marker stays outside the runtime releases directory and binds the service to a hold ID. Repeated hold keeps that ID. Installation failure, rollback and timer restart do not clear it. Only `--unhold <hold-id>` for that root/service resumes automatic activation; the existing accepted source can then become active again. Empty IDs must be treated as a supplied invalid option, not as absence of `--unhold`.

`work.lock` is shared by the review updater, so it does not serialize two UI updates or a manual hold. Both automatic hold-check/installation and manual installation/hold/unhold now use the same per-root exclusive `review-update.lock`. Automatic updates acquire the existing model shared lock first and call the installer's internal locked implementation without acquiring the UI lock again. A malformed, symlinked, non-private or mismatched hold refuses automatic installation.

Bind both installed helpers, `auto_review_release.py` and `install_review_release.py`, to the reviewed public source. A running old helper may already have loaded code that ignores holds: wait for that execution to finish naturally, then require a new natural timer execution to report both expected hold IDs and leave both `current` links unchanged before switching the manual UI. Leave other UI roots and global timer/floor/state settings unchanged. Rolling back only to an old helper would discard the protection. Hold does not fence AI jobs, exports or human edits; the final idle check, writer fence and consistent data backup still precede an actual UI restart.

Software verification on 2026-11-06: initial hold regressions failed 7 cases with 5 existing passes; the deterministic in-flight installation/hold regression failed separately; an empty-ID regression failed while the other 13 cases passed. The pending implementation then passed all 261 cases across `test_model_review_autoupdate.py`, `test_model_review_release.py` and `test_model_pc_autoupdate.py`, with zero skips and zero new failures. This verifies the software boundary and existing installer recovery, not installation of these helpers, protected timer execution or acceptance of the two operational UIs; those remain separate deployment evidence.

### Things the signed release does not carry (2026-10-24/25, sequences 33–35)

- **The installer itself.** The D-446 payload holds the app code (`learning/`, `middleware/`, `contracts/`, `operations/`) but not `deploy/model_pc/`. The center is installed with the copy at `~/rosy-ml/bin/install_review_release.py`. When an installer change is merged (for example `--workspace-links`), copy that file from the same merged commit (`git -c core.autocrlf=false show <sha>:deploy/model_pc/install_review_release.py`), keep the old one as `.before-<date>`, and compare sha256 before installing. Otherwise the new release installs but the old installer drops the new option.
- **The environment.** The updater refuses a release whose `--environment-sha256` differs from the host (`environment fingerprint differs; separate environment release required`). Packages added to `~/rosy-ml/.venv` by another task change the fingerprint. Read it with `rosy_model_code.py fingerprint`, check the change is additive, and sign the same commit again with a higher sequence and the new value. A failed sequence is not retried.
- **Bridge job state.** Changing the bridge config (for example switching `authority` to `state`) makes the next run fail with `job inputs changed; use a new job directory`, because the job state is bound to the input signature. Point the unit's `--out` to a new folder (keep the old one) and `daemon-reload`.

Evidence: sequence 33 was refused for the environment (packages added at 20:14 the same day), sequence 34 (same commit, new environment) applied. Sequence 35 installed on the center only after the `~/rosy-ml/bin` installer was replaced; the unit then carried `--workspace-links`. The bridge recovered after the `--out` move (authority `verified`, delivery `available: true`).

### A model-code work lock need not block an independent review UI hotfix

On 2026-11-05, active collection, review-pipeline and Isaac work held the model-code lock. The signed candidate was supplied normally but the updater returned `held: work lock busy`. The separate review service still needed the verified code from [PR #235](https://github.com/robotics-team-1213/rosy-platform/pull/235), which was queued for merge after its PR CI passed. This was a UI installation problem; model-code activation remained pending.

[D-545](../../adr/D-545-model-pc-review-versioned-release.md) supports a separately versioned review release. `install_review_release.py` checks center jobs but does not acquire the model-code work lock or check GPU idle. Its successful UI install is therefore not model-code acceptance. Before using this path:

1. Preserve the current accepted sequence as the review updater's minimum floor, the model-code current link/state, registered key, environments and configuration. Verify the signed archive and use a link-free source copy outside the review root/state.
2. Check the review service's AI jobs as well as center jobs. `review_ai_jobs.Jobs.close()` stops its worker, so an empty center alone does not establish that a restart preserves active work. Require no queued/running review AI jobs and only the main review process in that unit's cgroup. Confirm unrelated jobs are outside it.
3. Prevent new requests before the final idle check. For a dedicated Tailscale Serve front, record the full configuration, disable only that review HTTPS port, verify all other routes are unchanged, and wait for existing backend connections to drain. The documented `serve --https=<port> off` operation is scoped; do not reset Serve or stop the daemon. Restore the original background/proxy settings in `finally` and compare normalized configuration values. See the [official Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve).
4. With intake isolated, repeat the idle checks and run the supported installer using the existing Python, state, root and service. On failure retain the installer result and restore the prior unit/link. Keep database backups for recovery; do not replace newer human decisions with an older backup during a code rollback.
5. Read back the new current link and source assets, active unit, restored routing, HTTPS authentication entry, configuration and label/history integrity. Installation exit zero alone is insufficient: HTTP 200 with a nonempty response and the restored front must also pass before reporting success.

Verification on that date: helper compatibility was updated from the same verified source, the installer exited zero, the versioned review current link advanced, the authentication entry returned HTTPS 200, all Serve routes/configuration were restored, eight label/history tables matched their pre-upgrade snapshot hashes, and existing configuration and the Isaac process were preserved. The normal review updater subsequently reported waiting for the model-code/learning lock and left the hotfix active; this exercises lock deferral, not the sequence-floor branch. Runtime receipts remain in operator records without publishing raw labels or host configuration.

The signed model-code candidate stayed queued with READY and its timer active. Do not report the held candidate as accepted. UI activation also does not establish learner execution, model quality or physical acceptance; a native-cycle dataset lease is not proof of exclusive GPU ownership.
