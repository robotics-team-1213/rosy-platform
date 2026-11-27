"""Guarded AreaXYZ closed-loop fallback job specs for `cell_job_spec`."""
from __future__ import annotations

from cell_job_validators import (
    ARM,
    FILE,
    FILTER_COL,
    FILTER_OBJ,
    METRE,
    NAME,
    _actor,
    _bool,
    _int_range,
    _match,
    _num,
    _roi,
    _workdir_rel_path,
)

Z_METRE = _num(-0.15, 0.35)
YAW_DEG = _num(-180, 180)

PIXEL = _num(0, 1280)
_PUSH = {  # cell_push.py: one closed-jaw push of a top box or a box on a flat surface, 5..20 mm for now
    "script": "cell_push.py",
    "camera": True,
    "argv": ["--config", "{config}", "--site", "{site}", "--roi", "{roi}", "--px", "{px_x},{px_y}",
             "--dir", "{dir_x},{dir_y}", "--mm", "{mm}"],  # no --arm: the config names the arm, as for auto_pick
    "params": {
        "arm": _match(ARM),
        "config": _match(FILE),
        "site": _match(NAME),
        "roi": _roi,
        "px_x": PIXEL,
        "px_y": PIXEL,
        "dir_x": _num(-100, 100),
        "dir_y": _num(-100, 100),
        "mm": _num(5, 20),
    },
    "optional": {
        "half_mm": _num(5, 60),
        "half_width_mm": _num(5, 60),
        "catalog": _match(FILE),
        "operator": _actor,
        "proposer": _actor,
    },
}

AREA_JOBS = {
    "push": {**_PUSH, "moving": True, "commissioning": True},
    "push_dry_run": {**_PUSH, "moving": False, "argv": [*_PUSH["argv"], "--dry-run"]},
    "area_xyz_pick": {
        "script": "cell_area_pick_cli.py",
        "moving": True,
        "camera": True,
        "commissioning": True,
        "argv": [
            "--arm", "{arm}",
            "--config", "{config}",
            "--pick-area", "{pick_area}",
            "--pick-x", "{pick_x}",
            "--pick-y", "{pick_y}",
            "--pick-z", "{pick_z}",
            "--place-area", "{place_area}",
            "--place-x", "{place_x}",
            "--place-y", "{place_y}",
            "--place-z", "{place_z}",
        ],
        "params": {
            "arm": _match(ARM),
            "config": _match(FILE),
            "pick_area": _match(NAME),
            "pick_x": METRE,
            "pick_y": METRE,
            "pick_z": Z_METRE,
            "place_area": _match(NAME),
            "place_x": METRE,
            "place_y": METRE,
            "place_z": Z_METRE,
        },
        "optional": {
            "pick_yaw_deg": YAW_DEG,
            "place_yaw_deg": YAW_DEG,
            "max_attempts": _int_range(1, 3),
            "dry_run": _bool,
            "stay_in_hover": _bool,
            "no_vision_refine": _bool,
            "catalog": _match(FILE),
            "object": _match(FILTER_OBJ),
            "operator": _actor,
            "proposer": _actor,
        },
    },
    "safe_home": {
        "script": "cell_safe_home.py",
        "moving": True,
        "camera": True,
        "recovery_home": True,
        "commissioning": False,
        "argv": [
            "--arm", "{arm}",
            "--config", "{config}",
            "--library", "{library}",
            "--site", "{site}",
            "--roi", "{roi}",
            "--out", "cell-job-api/safe-home-{arm}.json",
        ],
        "params": {
            "arm": _match(ARM),
            "config": _match(FILE),
            "library": _match(FILE),
            "site": _match(NAME),
            "roi": _roi,
        },
        "optional": {"operator": _actor, "proposer": _actor},
    },
    "grasp_plan": {
        "script": "cell_grasp_plan_tool.py",
        "moving": False,
        "camera": True,
        "argv": ["--arm", "{arm}", "--config", "{config}", "--catalog", "{catalog}", "--from", "{source}", "--dest", "{dest}"],
        "params": {
            "arm": _match(ARM),
            "config": _match(FILE),
            "catalog": _match(FILE),
            "source": _match(NAME),
            "dest": _match(NAME),
        },
        "optional": {
            "roi": _roi,
            "object": _match(FILTER_OBJ),
            "colour": _match(FILTER_COL),
            "out": _workdir_rel_path,
        },
    },
    "incident_risk_clear": {
        "script": "omx_incident_pipeline.py",
        "moving": False,
        "camera": True,
        "argv": ["--arm", "{arm}", "--config", "{config}"],
        "params": {
            "arm": _match(ARM),
            "config": _match(FILE),
        },
        "optional": {
            "apply": _bool,
            "reassess": _bool,
            "min_score": _int_range(95, 100),
            "out": _workdir_rel_path,
        },
    },
}
