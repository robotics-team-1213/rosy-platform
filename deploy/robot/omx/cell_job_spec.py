"""Job definitions and strict parameter/argv validation for `cell_job_api`."""
from __future__ import annotations

from pathlib import Path
import re

SESSION = {
    "arm_a": "./with-session-arm-a-par.sh",
    "arm_b": "./with-session-arm-b-par.sh",
    "arm_s": "./with-session-arm-s-live.sh",
}
AB_ARMS = {"arm_a", "arm_b"}
ARM = re.compile(r"arm_[abs]")
NAME = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,62}")
FILE = re.compile(r"(cell|catalog|chunks)-[a-z0-9_.-]{1,60}\.json")
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
    "auto_pick": {
        "script": "cell_auto_pick.py",
        "moving": True,
        "camera": True,
        "argv": ["--config", "{config}", "--catalog", "{catalog}", "--roi", "{roi}", "--from", "{source}", "--dest", "{dest}"],
        "params": {"arm": _match(ARM), "config": _match(FILE), "catalog": _match(FILE), "roi": _roi, "source": _match(NAME), "dest": _match(NAME)},
    },
    "cell_policy_drive": {
        "script": "cell_policy_drive.py",
        "moving": True,
        "camera": True,
        "commissioning": False,
        "argv": [
            "--config", "{config}",
            "--library", "{library}",
            "--policy-root", "{policy_root}",
            "--policy-revision", "{policy_revision}",
            "--model-calibration", "{model_calibration}",
            "--cell-calibration", "{cell_calibration}",
            "--max-chunks", "{max_chunks}",
            "--operator", "{operator}",
        ],
        "params": {
            "arm": _match(ARM),
            "config": _match(FILE),
            "library": _match(FILE),
            "policy_root": _safe_path,
            "policy_revision": _match(SHA256),
            "model_calibration": _safe_path,
            "cell_calibration": _safe_path,
            "max_chunks": _int_range(1, 6),
            "operator": _match(NAME),
        },
        "optional": {
            "dry_run": _bool,
            "proposer": _match(NAME),
            "catalog": _match(FILE),
            "roi": _roi,
            "site": _match(NAME),
        },
    },
}


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
        if check.__qualname__.startswith("_match") and FILE.fullmatch(str(checked[name])) and not (workdir / checked[name]).is_file():
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
    if "proposer" in opt_checked and opt_checked["proposer"] == checked.get("operator"):
        raise ValueError("operator must differ from proposer (D-1024)")
    # Until D-1057 reaches R, jobs that can move at an AMR bed need the R claim path.
    if job.get("moving") and any(
        checked.get(name, opt_checked.get(name, "")).startswith(("pinky", "bed"))
        for name in ("source", "site")
    ):
        raise ValueError("AMR bed motion requires R cell-task -> cell_task_worker -> Gate")
    args = []
    for item in job["argv"]:
        whole = FIELD.fullmatch(item)
        if whole and isinstance(checked[whole.group(1)], list):
            args += checked[whole.group(1)]
        else:
            args.append(FIELD.sub(lambda m: checked[m.group(1)], item))
    if opt_checked.get("dry_run"):
        args.append("--dry-run")
    if "catalog" in opt_checked:
        args += ["--catalog", opt_checked["catalog"]]
    if "roi" in opt_checked:
        args += ["--roi", *opt_checked["roi"]]
    if "site" in opt_checked:
        args += ["--site", opt_checked["site"]]
    if job.get("moving"):
        if params.get("person_at_switch") is not True:
            raise ValueError("a moving job needs person_at_switch: true")
        if params["arm"] not in SESSION:
            raise ValueError(f"no session wrapper for {params['arm']}")
        tail = ["--commissioning", "--person-at-switch"] if job.get("commissioning", True) else ["--person-at-switch"]
        return [SESSION[params["arm"]], "bash", "-c", PY, job["script"], *args, *tail]
    return ["bash", "-c", ENV + PY, job["script"], *args]
