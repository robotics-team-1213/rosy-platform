"""Non-moving cell-config job specs for `cell_job_spec`: register a designated slot, promote it after a passing post_eval."""
from __future__ import annotations

import re

from cell_job_validators import FILE, NAME, _actor, _bool, _match, _num, _workdir_rel_path, resolve_under_workdir


def _true(v):
    if v is not True:
        raise ValueError("must be true: the fixed support and the arm path are visibly clear")
    return v


def check_site_files(job: dict, values: dict, workdir) -> None:
    """Evidence files the job reads must be real files inside the workdir; symlinks are refused (resolve_under_workdir).
    Also: a free source (free:<site>) has no layers_below (the planner would read it from a site that is not in the config)."""
    if str(values.get("source", "")).startswith("free:") and values.get("layers_below") is not None:
        raise ValueError("layers_below is not supported with a free source")
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
        "workdir_files": ("post_eval", "z_evidence", "tier_evidence"),
        "optional": {"post_eval": _workdir_rel_path, "z_evidence": _workdir_rel_path, "tier_evidence": _workdir_rel_path, "dry_run": _bool},
    },
    # Z evidence for a registered (unverified) slot: touches at its registered place with the existing remeasure guards (fixed designated
    # slot, camera alignment and bound map, fresh empty gripper); moving, so person_at_switch and D-911 commissioning stay required.
    # Order for a new slot: site_register -> site_surface -> site_promote(z_evidence=surface-<site>.json) -> post_eval -> site_promote(post_eval=).
    "site_surface": {
        "script": "cell_calibrate.py", "moving": True, "camera": True,
        "argv": ["--config", "{config}", "auto", "--only", "surface", "--remeasure-surface", "{site}", "--surface-clear"],
        "params": {"arm": _match(re.compile(r"arm_a|arm_b")), "config": _match(FILE), "site": _match(NAME), "surface_clear": _true},
    },
}
