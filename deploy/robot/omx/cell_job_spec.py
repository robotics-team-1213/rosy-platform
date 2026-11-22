"""Job definitions and strict parameter/argv validation for `cell_job_api`."""
from __future__ import annotations

import json
from pathlib import Path
import re

from cell_policy_goals import resolve_goal_site

SESSION = {
    "arm_a": "./with-session-arm-a-par.sh",
    "arm_b": "./with-session-arm-b-par.sh",
    "arm_s": "./with-session-arm-s-live.sh",
}
AB_ARMS = {"arm_a", "arm_b"}
ARM = re.compile(r"arm_[abs]")
ACTOR = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}")
NAME = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,62}")
FILE = re.compile(r"(?:object-)?(cell|catalog|chunks)-[a-z0-9_.-]{1,60}\.json")
TASK_FILE = re.compile(r"(?:task|plan)-[a-z0-9_.-]{1,60}\.json")
FILTER_OBJ = re.compile(r"[a-z0-9_,-]{1,120}")
FILTER_COL = re.compile(r"[a-z0-9_,-]{1,64}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_PATH = re.compile(r"[A-Za-z0-9_./~:-]{1,240}")
PY = 'exec ~/rosy-omx/current-env/bin/python "$OMX/$0" "$@"'
ENV = "set -a; . ~/.config/rosy/omx-observation-bridge.env; set +a; . ./tools-env-current.sh; "
FIELD = re.compile(r"\{(\w+)\}")


def _num(lo, hi):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError(f"a number in [{lo}, {hi}]")
        return str(v)

    return check


def _int_range(lo: int, hi: int):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"an integer in [{lo}, {hi}]")
        return str(v)

    return check


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("a boolean")
    return v


def _match(rx):
    def check(v):
        if not isinstance(v, str) or not rx.fullmatch(v):
            raise ValueError(f"must match {rx.pattern}")
        return v

    return check


def _safe_path(v):
    if not isinstance(v, str) or not SAFE_PATH.fullmatch(v) or ".." in Path(v).parts:
        raise ValueError("must be a safe path without '..'")
    return v


def _actor(v):
    if not isinstance(v, str) or not ACTOR.fullmatch(v) or ".." in str(v).replace("\\", "/").split("/"):
        raise ValueError(f"must match {ACTOR.pattern}")
    return v


def _goal_site(v):
    try:
        resolve_goal_site(v)
    except (OSError, ImportError) as exc:
        raise ValueError(f"cannot read Cell site map: {getattr(exc, 'strerror', None) or exc}") from exc
    return v


def _roi(v):
    if not (isinstance(v, list) and len(v) == 4 and all(not isinstance(i, bool) and isinstance(i, int) and 0 <= i <= 1280 for i in v)):
        raise ValueError("four integer pixels")
    return [str(i) for i in v]


METRE = _num(-0.5, 0.5)
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


def _is_amr_bed_site(v: str) -> bool:
    if not isinstance(v, str) or not v:
        return False
    s = v.strip().lower()
    if s.startswith("not_places:"):
        s = s[len("not_places:"):]
    base = re.sub(r"-l[0-9]+$", "", s.split(":", 1)[0])
    return base.startswith(("pinky", "bed")) or base in ("tray", "vehicle_tray")


def _task_site_names(task_path: Path, config_path: Path | None) -> set[str]:
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("task: invalid JSON object") from exc
    if not isinstance(task, dict):
        raise ValueError("task: invalid JSON object")
    names: set[str] = set()

    def _add(val):
        if isinstance(val, str):
            names.add(val)

    for k in ("from", "to", "a", "b", "buffer"):
        _add(task.get(k))
    for k in ("columns", "sources", "destinations"):
        seq = task.get(k)
        if isinstance(seq, list):
            for v in seq:
                _add(v)
    for k in ("layout", "initial", "goal"):
        mp = task.get(k)
        if isinstance(mp, dict):
            for s in mp:
                _add(s)
    smap = task.get("site_map")
    if isinstance(smap, dict):
        for sk, sv in smap.items():
            _add(sk)
            _add(sv)
    steps = task.get("steps")
    if isinstance(steps, list):
        for st in steps:
            if isinstance(st, dict):
                _add(st.get("from"))
                _add(st.get("to"))
    if config_path is not None and config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            sites = cfg.get("sites") if isinstance(cfg, dict) else None
            if isinstance(sites, dict):
                if task.get("kind") in ("goal_stack", "outbound", "rehandle"):
                    if not task.get("layout"):
                        for k, v in sites.items():
                            if isinstance(v, dict) and "layer" not in v and v.get("kind", "temp") == "temp" and _is_amr_bed_site(k):
                                _add(k)
                    try:
                        import cell_task_runner

                        for st in cell_task_runner.plan_steps(task, sites):
                            _add(st.get("from"))
                            _add(st.get("to"))
                    except (ValueError, KeyError):
                        pass
                for s in list(names):
                    base = s.rsplit("-l", 1)[0]
                    for key in (s, base, f"{base}-l0", f"{base}-l1", f"{base}-l2"):
                        alts = (sites.get(key) or {}).get("alternates") if isinstance(sites.get(key), dict) else None
                        if isinstance(alts, list):
                            for a in alts:
                                _add(a)
        except (OSError, ValueError):
            pass
    return names


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
            if "goal_site" not in opt_checked and "model_calibration" not in opt_checked:
                raise ValueError("missing param model_calibration")
    # Until D-1057 reaches R, jobs that can move at an AMR bed need the R claim path.
    if moves_arm(job, params):
        direct_sites = [checked.get(name, opt_checked.get(name, "")) for name in ("source", "dest", "site", "goal_site")]
        task_sites = _task_site_names(workdir / checked["task"], workdir / checked["config"] if "config" in checked else None) if "task" in checked else set()
        if any(_is_amr_bed_site(v) for v in (*direct_sites, *task_sites)):
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
    if "catalog" in opt_checked:
        args += ["--catalog", opt_checked["catalog"]]
    if "roi" in opt_checked:
        args += ["--roi", *opt_checked["roi"]]
    for option in ("site", "goal_site", "model_calibration", "mode", "policy_root", "policy_revision", "cell_calibration", "n_action", "max_obs_age_s", "object", "colour", "layers_below", "source_kind"):
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
