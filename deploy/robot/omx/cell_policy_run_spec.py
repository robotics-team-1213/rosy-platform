"""The one-submission ACT run job (2026-11-26): same params as cell_policy_drive plus the operating profile its home stage binds.

A run submitted as home, calibrate_check, a dry run and a drive each opened a session and took the lock again (~100 s
apiece). cell_policy_run does every stage of one run inside one session wrapper. It cannot be a dry run: its dry-run
check is part of the run, so `dry_run` is not a param (the drive job keeps it).
"""
from __future__ import annotations

from cell_job_validators import _safe_path

POLICY_SCRIPTS = ("cell_policy_drive.py", "cell_policy_run.py")  # both take the drive's param checks and arm id


def policy_run_job(drive: dict) -> dict:
    return {**drive, "script": "cell_policy_run.py",
            "argv": [*drive["argv"], "--operating-profile", "{operating_profile}"],
            "params": {**drive["params"], "operating_profile": _safe_path},
            "optional": {k: v for k, v in drive["optional"].items() if k != "dry_run"}}
