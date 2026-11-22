"""Job definitions and strict parameter/argv validation for `cell_job_api`."""
from __future__ import annotations

from pathlib import Path
import re

from cell_job_validators import (  # noqa: E402,F401  (re-exported)
    ACTOR,
    ARM,
    FIELD,
    FILE,
    FILTER_COL,
    FILTER_OBJ,
    METRE,
    NAME,
    SAFE_PATH,
    SHA256,
    TASK_FILE,
    _actor,
    _bool,
    _int_range,
    _is_amr_bed_site,
    _match,
    _num,
    _roi,
    _safe_path,
    _task_site_names,
)
from cell_policy_goals import resolve_goal_site

SESSION = {
    "arm_a": "./with-session-arm-a-par.sh",
    "arm_b": "./with-session-arm-b-par.sh",
    "arm_s": "./with-session-arm-s-live.sh",
}
AB_ARMS = {"arm_a", "arm_b"}
PY = 'exec ~/rosy-omx/current-env/bin/python "$OMX/$0" "$@"'
ENV = "set -a; . ~/.config/rosy/omx-observation-bridge.env; set +a; . ./tools-env-current.sh; "


def _goal_site(v):
    try:
        resolve_goal_site(v)
    except (OSError, ImportError) as exc:
        raise ValueError(f"cannot read Cell site map: {getattr(exc, 'strerror', None) or exc}") from exc
    return v


JOBS = {
    "incident_status": {
        "script": "omx_incident.py",
        "argv": ["status", "--arm", "{arm}"],
        "params": {"arm": _match(ARM)},
    },
    "calibrate_check": {
        "script": "cell_calibrate.py",
        "camera": True,
        "argv": ["--config", "{config}", "check"],
        "params": {"config": _match(FILE)},
    },
    "auto_pick_dry_run": {
        "script": "cell_auto_pick.py",
        "camera": True,
        "argv": ["--config", "{config}", "--catalog", "{catalog}", "--roi", "{roi}", "--from", "{source}", "--dest", "{dest}", "--dry-run"],
        "params": {"config": _match(FILE), "catalog": _match(FILE), "roi": _roi, "source": _match(NAME), "dest": _match(NAME)},
        "optional": {"object": _match(FILTER_OBJ), "colour": _match(FILTER_COL), "layers_below": _int_range(0, 5)},
    },
    "pivot_near": {
        "script": "cell_calibrate.py",
        "moving": True,
        "camera": True,
        "argv": ["--config", "{config}", "auto", "--only", "pivot-near", "--targets", "{site}:{x},{y}"],
        "params": {"arm": _match(ARM), "config": _match(FILE), "site": _match(NAME), "x": METRE, "y": METRE},
    },
    "remap": {
        "script": "cell_calibrate.py",
        "moving": True,
        "camera": True,
        "argv": ["--config", "{config}", "auto", "--only", "remap", "regions"],
        "params": {"arm": _match(ARM), "config": _match(FILE)},
    },
    "home": {
        "script": "cell_pipeline.py",
        "moving": True,
        "argv": ["--config", "{config}", "--stage", "home", "--library", "{library}", "--operating-profile", "{operating_profile}"],
        "params": {"arm": _match(ARM), "config": _match(FILE), "library": _match(FILE), "operating_profile": _safe_path},
        "optional": {"operator": _match(NAME), "proposer": _match(NAME)},
    },
    "auto_pick": {
        "script": "cell_auto_pick.py",
        "moving": True,
        "camera": True,
        "argv": ["--config", "{config}", "--catalog", "{catalog}", "--roi", "{roi}", "--from", "{source}", "--dest", "{dest}"],
        "params": {"arm": _match(ARM), "config": _match(FILE), "catalog": _match(FILE), "roi": _roi, "source": _match(NAME), "dest": _match(NAME)},
        "optional": {
            "operator": _match(NAME),
            "proposer": _match(NAME),
            "reviewed_auto": _bool,
            "verify_zones": _bool,
            "object": _match(FILTER_OBJ),
            "colour": _match(FILTER_COL),
            "layers_below": _int_range(0, 5),
        },
    },
    "cell_policy_drive": {
        "script": "cell_policy_drive.py",
        "moving": True,
        "camera": True,
        "commissioning": False,
        "argv": [
            "--config", "{config}",
            "--library", "{library}",
            "--max-chunks", "{max_chunks}",
            "--operator", "{operator}",
        ],
        "params": {
            "arm": _match(ARM),
            "config": _match(FILE),
            "library": _match(FILE),
            "max_chunks": _int_range(1, 6),
            "operator": _actor,
        },
        "optional": {
            "mode": _match(re.compile(r"act|hybrid|taught")),
            "policy_root": _safe_path,
            "policy_revision": _match(SHA256),
            "cell_calibration": _safe_path,
            "n_action": _int_range(1, 1000),
            "max_obs_age_s": _num(0.001, 5),
            "dry_run": _bool,
            "proposer": _actor,
            "goal_site": _goal_site,
            "goal_slot": _int_range(0, 31),
            "act_backend": _match(re.compile(r"auto|torch|openvino")),
            "model_calibration": _safe_path,
            "catalog": _match(FILE),
            "roi": _roi,
            "site": _match(NAME),
            "source_kind": _match(re.compile(r"policy|sim_optimized|scripted_teacher")),
            "paced_chunks": _bool,
        },
    },
    "stack_plan": {
        "script": "cell_stack_plan.py",
        "argv": ["--plan-json", "{plan}"],
        "params": {"plan": _match(TASK_FILE)},
    },
    "task_runner_dry_run": {
        "script": "cell_task_runner.py",
        "camera": True,
        "argv": ["--config", "{config}", "--catalog", "{catalog}", "--task", "{task}", "--dry-run"],
        "params": {"config": _match(FILE), "catalog": _match(FILE), "task": _match(TASK_FILE)},
    },
    "task_runner": {
        "script": "cell_task_runner.py",
        "moving": True,
        "camera": True,
        "reviewed_only": True,
        "argv": ["--config", "{config}", "--catalog", "{catalog}", "--task", "{task}"],
        "params": {"arm": _match(ARM), "config": _match(FILE), "catalog": _match(FILE), "task": _match(TASK_FILE)},
        "optional": {"operator": _match(NAME), "proposer": _match(NAME)},
    },
    "auto_carry": {
        "script": "cell_auto_carry.py",
        "moving": True,
        "camera": True,
        "reviewed_only": True,
        "argv": ["--config", "{config}", "--catalog", "{catalog}", "--roi", "{roi}", "--from", "{source}", "--dest", "{dest}", "--max", "{max}"],
        "params": {"arm": _match(ARM), "config": _match(FILE), "catalog": _match(FILE), "roi": _roi, "source": _match(NAME), "dest": _match(NAME), "max": _int_range(1, 20)},
        "optional": {
            "operator": _match(NAME),
            "proposer": _match(NAME),
            "object": _match(FILTER_OBJ),
            "colour": _match(FILTER_COL),
            "layers_below": _int_range(0, 5),
        },
    },
}


def moves_arm(job, params):
    return bool(job.get("moving")) and not (job["script"] == "cell_policy_drive.py" and params.get("dry_run") is True)


def build_argv(job: dict, params: dict, workdir: Path) -> list[str]:
    """The job's argv from checked params; ValueError says what is wrong."""
    spec, opt_spec = job["params"], job.get("optional", {})
    if unknown := set(params) - set(spec) - set(opt_spec) - {"person_at_switch", "purpose"}:
        raise ValueError(f"unknown params {sorted(unknown)}")
    checked = {}
    for name, check in spec.items():
        if name not in params:
            raise ValueError(f"missing param {name}")
        try:
            checked[name] = check(params[name])
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from None
        if (check.__qualname__.startswith("_match")
                and (FILE.fullmatch(str(checked[name])) or TASK_FILE.fullmatch(str(checked[name])))
                and not (workdir / checked[name]).is_file()):
            raise ValueError(f"{name}: no such file in the workdir")
    opt_checked = {}
    for name, check in opt_spec.items():
        if name in params:
            try:
                opt_checked[name] = check(params[name])
            except ValueError as exc:
                raise ValueError(f"{name}: {exc}") from None
            if name == "catalog" and not (workdir / opt_checked[name]).is_file():
                raise ValueError(f"{name}: no such file in the workdir")
    operator = checked.get("operator") or opt_checked.get("operator")
    if "proposer" in opt_checked and (not operator or opt_checked["proposer"].casefold() == operator.casefold()):
        raise ValueError("operator must differ from proposer (D-1024)")
    if job["script"] == "cell_policy_drive.py":
        mode = opt_checked.get("mode", "act")
        if opt_checked.get("paced_chunks") and (mode != "act" or "n_action" in opt_checked):
            raise ValueError("paced_chunks requires mode='act' without n_action")
        if "source_kind" in opt_checked:
            sk = opt_checked["source_kind"]
            if mode != "taught" and sk != "policy":
                raise ValueError(f"{mode} mode requires source_kind='policy', got {sk!r}")
            if mode == "taught" and sk == "policy":
                raise ValueError("taught mode cannot use source_kind='policy'")
        if mode != "act" and "goal_site" not in opt_checked:
            raise ValueError(f"{mode} needs goal_site")
        if mode != "taught":
            for required in ("policy_root", "policy_revision", "cell_calibration"):
                if required not in opt_checked:
                    raise ValueError(f"missing param {required}")
            if "goal_site" not in opt_checked and "goal_slot" not in opt_checked and "model_calibration" not in opt_checked:
                raise ValueError("missing param model_calibration")
    # Until D-1057 reaches R, jobs that can move at an AMR bed need the R claim path.
    if moves_arm(job, params):
        direct_sites = [checked.get(name, opt_checked.get(name, "")) for name in ("source", "dest", "site", "goal_site")]
        task_sites = _task_site_names(workdir / checked["task"], workdir / checked["config"] if "config" in checked else None) if "task" in checked else set()
        if any(_is_amr_bed_site(v) for v in (*direct_sites, *task_sites)):
            raise ValueError("AMR bed motion requires R cell-task -> cell_task_worker -> Gate")
        if "goal_slot" in opt_checked:
            from cell_policy_goals import GOALS
            slot = int(opt_checked["goal_slot"])
            if slot < 0 or slot >= len(GOALS):
                raise ValueError("goal_slot outside mapped GOALS")
            if _is_amr_bed_site(GOALS[slot]):
                raise ValueError("AMR bed motion requires R cell-task -> cell_task_worker -> Gate")
    args = []
    for item in job["argv"]:
        whole = FIELD.fullmatch(item)
        if whole and isinstance(checked[whole.group(1)], list):
            args += checked[whole.group(1)]
        else:
            args.append(FIELD.sub(lambda m: checked[m.group(1)], item))
    for flag, opt in (("--dry-run", "dry_run"), ("--paced-chunks", "paced_chunks")):
        if opt_checked.get(opt):
            args.append(flag)
    if job["script"] == "cell_auto_pick.py" and moves_arm(job, params) and opt_checked.get("verify_zones", True):
        args.append("--verify-zones")
    if "catalog" in opt_checked:
        args += ["--catalog", opt_checked["catalog"]]
    if "roi" in opt_checked:
        args += ["--roi", *opt_checked["roi"]]
    for option in ("site", "goal_site", "goal_slot", "model_calibration", "mode", "policy_root", "policy_revision", "cell_calibration", "n_action", "max_obs_age_s", "object", "colour", "layers_below", "source_kind"):
        if option in opt_checked:
            args += ["--" + option.replace("_", "-"), opt_checked[option]]
    if moves_arm(job, params):
        reviewed_run = bool(job.get("reviewed_only")) or opt_checked.get("reviewed_auto") is True
        if reviewed_run:
            if params.get("person_at_switch") is True:
                raise ValueError("reviewed automatic jobs cannot be combined with person_at_switch (D-911)")
            if params["arm"] not in SESSION:
                raise ValueError(f"no session wrapper for {params['arm']}")
            return [SESSION[params["arm"]], "bash", "-c", PY, job["script"], *args]
        if params.get("person_at_switch") is not True:
            raise ValueError("a moving job needs person_at_switch: true")
        if params["arm"] not in SESSION:
            raise ValueError(f"no session wrapper for {params['arm']}")
        tail = ["--commissioning", "--person-at-switch"] if job.get("commissioning", True) else ["--person-at-switch"]
        return [SESSION[params["arm"]], "bash", "-c", PY, job["script"], *args, *tail]
    return ["bash", "-c", ENV + PY, job["script"], *args]
