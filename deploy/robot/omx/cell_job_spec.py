"""Job definitions and strict parameter/argv validation for `cell_job_api`."""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit

from cell_job_validators import (  # noqa: E402,F401  (re-exported)
    ACTOR,
    ARM,
    FIELD,
    FILE,
    FILTER_COL,
    FILTER_OBJ,
    IMAGES_SPEC,
    MANIFEST_FILE,
    METRE,
    NAME,
    REPO_ID,
    SAFE_PATH,
    SHA256,
    TASK_FILE,
    VIEW,
    _actor,
    _bool,
    _http_url,
    _int_range,
    _is_amr_bed_site,
    _match,
    _num,
    _repo_id,
    _roi,
    _safe_path,
    _task_site_names,
    _two_arm_task,
    _two_arm_task_sites,
    _workdir_rel_path,
)
from cell_media_job_spec import MEDIA_JOBS  # noqa: E402,F401
from cell_policy_goals import resolve_goal_site

SESSION = {
    "arm_a": "./with-session-arm-a-par.sh",
    "arm_b": "./with-session-arm-b-par.sh",
    "arm_s": "./with-session-arm-s-live.sh",
}
AB_ARMS = {"arm_a", "arm_b"}
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_BELT_SITES = frozenset({"belt", "not_places:belt"})
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
            "max_chunks": _int_range(1, 60),
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
            "endpoint_url": _http_url,
            "token_file": _safe_path,
            "timeout_s": _num(0.05, 2.0),
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
    "recover_hold": {
        "script": "cell_auto_fold.py", "moving": True, "camera": True, "attach_live_hold": True, "commissioning": False,
        "argv": ["--supervised", "--unlatch-hold", "--arm", "{arm}", "--config", "{config}", "--library", "{library}",
                 "--site", "{site}", "--roi", "{roi}", "--out", "cell-job-api/recover-hold-{arm}.json"],
        "params": {"arm": _match(ARM), "config": _match(FILE), "library": _match(FILE), "site": _match(NAME), "roi": _roi},
        "optional": {"operator": _actor, "proposer": _actor, "vlm_url": _http_url, "vlm_config": _safe_path,
                     "vlm_model": _match(re.compile(r"[A-Za-z0-9._:/-]{1,80}")),
                     "vlm_provider": _match(re.compile(r"[A-Za-z0-9_-]{1,32}")), "vlm_timeout": _num(1.0, 30.0)},
    },
    "cell_two_arm_policy": {
        "script": "cell_two_arm_policy_cli.py",
        "moving": True,
        "camera": True,
        "commissioning": True,
        "arms": ("arm_a", "arm_b"),
        "argv": [
            "--config-a", "{config_a}",
            "--config-b", "{config_b}",
            "--endpoint-url", "{endpoint_url}",
            "--revision-a", "{revision_a}",
            "--revision-b", "{revision_b}",
            "--library-a", "{library_a}",
            "--library-b", "{library_b}",
            "--task-a", "{task_a}",
            "--task-b", "{task_b}",
            "--proposer", "{proposer}",
            "--operator", "{operator}",
        ],
        "params": {
            "config_a": _match(FILE),
            "config_b": _match(FILE),
            "library_a": _match(FILE),
            "library_b": _match(FILE),
            "endpoint_url": _http_url,
            "revision_a": _match(SHA256),
            "revision_b": _match(SHA256),
            "task_a": _two_arm_task,
            "task_b": _two_arm_task,
            "proposer": _actor,
            "operator": _actor,
        },
        "optional": {
            "token_file": _safe_path,
            "policy_root_a": _safe_path,
            "policy_root_b": _safe_path,
            "model_cal_a": _safe_path,
            "model_cal_b": _safe_path,
            "cell_cal_a": _safe_path,
            "cell_cal_b": _safe_path,
            "work_dir": _safe_path,
            "goal_a": _int_range(0, 31),
            "goal_b": _int_range(0, 31),
            "model_site_a": _match(NAME),
            "model_site_b": _match(NAME),
            "max_chunks": _int_range(1, 16),
            "timeout_s": _num(0.05, 2.0),
            "margin_m": _num(0.005, 0.2),
            "min_z_m": _num(-0.1, 0.2),
            "dry_run": _bool,
        },
    },
    **MEDIA_JOBS,
}


def job_arms(job: dict, params: dict) -> tuple[str, ...]:
    if job.get("arms"):
        return tuple(job["arms"])
    return (params["arm"],) if params.get("arm") else ()


def moves_arm(job, params):
    return bool(job.get("moving")) and not (
        job["script"] in ("cell_policy_drive.py", "cell_two_arm_policy_cli.py") and params.get("dry_run") is True
    )


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
                and (FILE.fullmatch(str(checked[name])) or MANIFEST_FILE.fullmatch(str(checked[name])) or TASK_FILE.fullmatch(str(checked[name])))
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
    proposer = checked.get("proposer") or opt_checked.get("proposer")
    if proposer and (not operator or proposer.casefold() == operator.casefold()):
        raise ValueError("operator must differ from proposer (D-1024)")
    if job["script"] == "cell_two_arm_policy_cli.py":
        host = (urlsplit(checked["endpoint_url"]).hostname or "").lower()
        if host not in _LOOPBACK_HOSTS and "token_file" not in opt_checked:
            raise ValueError("non-loopback endpoint_url requires token_file")
        src_a, dst_a = _two_arm_task_sites(checked["task_a"])
        src_b, dst_b = _two_arm_task_sites(checked["task_b"])
        na = ("belt" if src_a in _BELT_SITES else src_a, "belt" if dst_a in _BELT_SITES else dst_a)
        nb = ("belt" if src_b in _BELT_SITES else src_b, "belt" if dst_b in _BELT_SITES else dst_b)
        if na[1] == nb[1] or (na[0] == nb[0] and na[0] != "belt") or na[0] == nb[1] or na[1] == nb[0]:
            raise ValueError("task_a and task_b overlap on non-belt site")
        if moves_arm(job, params) and any(_is_amr_bed_site(v) for v in (src_a, dst_a, src_b, dst_b)):
            raise ValueError("AMR bed motion requires R cell-task -> cell_task_worker -> Gate")
    if job["script"] == "cell_policy_drive.py":
        mode = opt_checked.get("mode", "act")
        if opt_checked.get("paced_chunks") and mode != "act":
            raise ValueError("paced_chunks requires mode='act'")
        if "token_file" in opt_checked and "endpoint_url" not in opt_checked:
            raise ValueError("token_file requires endpoint_url")
        if "endpoint_url" in opt_checked:
            if mode == "taught":
                raise ValueError("taught mode cannot use endpoint_url")
            host = (urlsplit(opt_checked["endpoint_url"]).hostname or "").lower()
            if host not in _LOOPBACK_HOSTS and "token_file" not in opt_checked:
                raise ValueError("non-loopback endpoint_url requires token_file")
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
    for option in (
        "site", "goal_site", "goal_slot", "model_calibration", "mode", "policy_root", "policy_revision",
        "cell_calibration", "n_action", "max_obs_age_s", "object", "colour", "layers_below", "source_kind",
        "endpoint_url", "token_file", "policy_root_a", "policy_root_b", "goal_a", "goal_b", "model_cal_a", "model_cal_b",
        "cell_cal_a", "cell_cal_b", "model_site_a", "model_site_b", "work_dir", "max_chunks", "timeout_s",
        "margin_m", "min_z_m", "out", "out_dir", "fps", "images", "outcome", "expected_manifest_sha256",
        "vlm_url", "vlm_model", "vlm_provider", "vlm_config", "vlm_timeout",
    ):
        if option in opt_checked:
            args += ["--" + option.replace("_", "-"), opt_checked[option]]
    if job["script"] == "cell_media_jobs.py":
        args = ["--workdir", str(workdir), *args]
    if job["script"] == "cell_policy_drive.py" and "endpoint_url" in opt_checked:
        args += ["--arm-id", checked["arm"]]
    if moves_arm(job, params):
        arm_list = list(job_arms(job, params))
        if not arm_list or any(a not in SESSION for a in arm_list):
            raise ValueError(f"no session wrapper for {params.get('arm') or arm_list}")
        if job.get("attach_live_hold"):
            return ["bash", "-c", ENV + PY, job["script"], *args]
        reviewed_run = bool(job.get("reviewed_only")) or opt_checked.get("reviewed_auto") is True
        prefix = [SESSION[a] for a in arm_list]
        if reviewed_run:
            if params.get("person_at_switch") is True:
                raise ValueError("reviewed automatic jobs cannot be combined with person_at_switch (D-911)")
            return [*prefix, "bash", "-c", PY, job["script"], *args]
        if params.get("person_at_switch") is not True:
            raise ValueError("a moving job needs person_at_switch: true")
        tail = ["--commissioning", "--person-at-switch"] if job.get("commissioning", True) else ["--person-at-switch"]
        return [*prefix, "bash", "-c", PY, job["script"], *args, *tail]
    return ["bash", "-c", ENV + PY, job["script"], *args]
