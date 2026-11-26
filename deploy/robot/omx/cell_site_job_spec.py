"""Non-moving cell-config job specs for `cell_job_spec`: register a designated slot, promote it after a passing post_eval."""
from __future__ import annotations

import re

from cell_job_validators import FILE, NAME, _actor, _bool, _match, _num, _workdir_rel_path, resolve_under_workdir


def check_site_files(job: dict, values: dict, workdir) -> None:
    """Evidence files the job reads must be real files inside the workdir; symlinks are refused (resolve_under_workdir)."""
    for name in job.get("workdir_files", ()):
        if name in values and not resolve_under_workdir(workdir, values[name]).is_file():
            raise ValueError(f"{name}: no such file in the workdir")

SITE_JOBS = {
    # The arm never moves, so no person_at_switch; operator and proposer are required and must differ (D-1024).
    "site_register": {
        "script": "cell_site_register.py",
        "argv": ["register", "--arm", "{arm}", "--config", "{config}", "--site", "{site}", "--place", "{x}", "{y}",
                 "--surface-z", "{surface_z}", "--yaw-deg", "{yaw_deg}", "--tier-step-m", "{tier_step_m}",
                 "--map-from", "{map_from}", "--source", "{source}", "--evidence", "{evidence}",
                 "--operator", "{operator}", "--proposer", "{proposer}"],
        "params": {
            "arm": _match(re.compile(r"arm_a|arm_b")), "config": _match(FILE), "site": _match(NAME),
            "x": _num(-0.5, 0.5), "y": _num(-0.5, 0.5), "surface_z": _num(-0.2, 0.2), "yaw_deg": _num(-360, 360),
            "tier_step_m": _num(0.01, 0.1), "map_from": _match(NAME), "source": _match(re.compile(r"cad|depth|probe")),
            "evidence": _workdir_rel_path, "operator": _actor, "proposer": _actor,
        },
        "workdir_files": ("evidence",),
        "optional": {"replace": _bool, "dry_run": _bool},
    },
    "site_promote": {
        "script": "cell_site_register.py",
        "argv": ["promote", "--arm", "{arm}", "--config", "{config}", "--site", "{site}",
                 "--operator", "{operator}", "--proposer", "{proposer}"],
        "params": {
            "arm": _match(re.compile(r"arm_a|arm_b")), "config": _match(FILE), "site": _match(NAME),
            "operator": _actor, "proposer": _actor,
        },
        # XY from a cell_post_eval report or job log, Z from a surface touch receipt; the tool needs at least one, measured needs both
        "workdir_files": ("post_eval", "z_evidence"),
        "optional": {"post_eval": _workdir_rel_path, "z_evidence": _workdir_rel_path, "dry_run": _bool},
    },
}
