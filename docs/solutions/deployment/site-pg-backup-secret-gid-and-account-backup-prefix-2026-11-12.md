---
title: Sealed site backup containers need GID 10001 to read 0440 site-secrets and off-host pull scripts must rename account backups from fleet-backup-*
date: 2026-11-12
category: deployment
module: deploy/site/compose.pg-backup.yaml, deploy/site/compose.account-backup.yaml, deploy/site/site_db.py
problem_type: deployment_error
component: deployment
symptoms:
  - "rosy-pg-backup.service failed with `cat: can't open '/run/secrets/postgres_password': Permission denied` when running as `user: 70:70`"
  - "Off-host pull-rosy-site-backup.ps1 skipped /var/backups/rosy-account because files inside were named `fleet-backup-*.sqlite3` instead of `account-backup-*.sqlite3`"
root_cause: permission_and_naming_contract_mismatch
resolution_type: code_and_config_fix
applies_when:
  - "adding or modifying a sealed Docker Compose service under deploy/site/ that mounts /etc/rosy/site-secrets/*"
  - "writing off-host backup pull or verification scripts for /var/backups/rosy-account or /var/backups/rosy-pg"
---

## Problem

1. When `deploy/site/compose.pg-backup.yaml` was deployed to the live site server (`rosy-fleet-r`) with `user: "70:70"` (`postgres:postgres` inside `postgres:16-alpine`) and `cap_drop: [ALL]`, `rosy-pg-backup.service` immediately failed with:
   `cat: can't open '/run/secrets/postgres_password': Permission denied`.
2. When `pull-rosy-site-backup.ps1` queried `/var/backups/rosy-account` for `account-backup-[0-9]{8}-[0-9]{6}\.sqlite3`, it reported no matching backup even though `rosy-account-backup.timer` had been succeeding daily.

## Cause

1. On the site host, `/etc/rosy/site-secrets/*` files are owned by `root:rosy-fleet` (`0:10001`) with mode `0440` (`deploy/site/README.md`). Because the backup container drops all capabilities (`cap_drop: [ALL]`, no `DAC_OVERRIDE`), UID `70` with GID `70` hits the `other` permission bits (`0`) on `/run/secrets/postgres_password`.
2. `deploy/site/compose.account-backup.yaml` invokes `python3 /etc/rosy/site/site_db.py backup /var/lib/rosy-account/account.sqlite3 /backup`, and `site_db.py` writes `fleet-backup-YYYYMMDD-HHMMSS.sqlite3` regardless of the source DB name. Searching for `account-backup-*` missed the files, while pulling `fleet-backup-*` without renaming would collide with `fleet.sqlite3` backups in a flat off-host backup directory.

## Fix

1. Set `user: "70:10001"` in `deploy/site/compose.pg-backup.yaml` and provision `/var/backups/rosy-pg` on the site host as `chown 70:10001 && chmod 0750 /var/backups/rosy-pg`. UID `70` remains non-root `postgres` while GID `10001` grants group read access to `0440` secrets in `/etc/rosy/site-secrets/`.
2. Update the off-host backup pull script (`pull-rosy-site-backup.ps1`) to match `(account|fleet)-backup-[0-9]{8}-[0-9]{6}\.sqlite3` in `/var/backups/rosy-account` and rename `^fleet-backup-` to `account-backup-` before writing `.gz` and `.sha256` files locally.

## Verification

- `systemctl start rosy-pg-backup.service` and `systemctl start rosy-pg-backup-check.service` on `rosy-fleet-r` succeeded (`postgres backup ok: /backup/postgres-backup-20261112T115837Z.dump (0 h old)`).
- `test/test_site_pg_backup.py` asserts `user: "70:10001"` on both `pg-backup` and `pg-backup-check`.
- Off-host `pull-rosy-site-backup.ps1` pulled and SHA-256 verified all three streams (`fleet-backup-*.sqlite3.gz`, `account-backup-*.sqlite3.gz`, `postgres-backup-*.dump.gz`).

## Next time

- Any sealed `deploy/site/compose*.yaml` service (`cap_drop: [ALL]`) that reads `/etc/rosy/site-secrets/*` must run with GID `10001` (`user: "<uid>:10001"`), and its host bind-mounted output directory must grant write access to `<uid>:10001`.
- When adding a new backup stream that reuses `site_db.py backup`, remember its output filename prefix is `fleet-backup-` unless overridden or renamed by the consumer.
