"""Plan and step files for `omx_two_arm_policy`: two-arm plans by task name, the steps/eval file next to a DAgger model."""
import json
from pathlib import Path


def plan_tasks(plan_dir, names):
    """The two-arm plans of omx_two_arm_plan.py (compare --replay-dir) by task name, for concurrent collection and evaluation."""
    return {name: dict(json.loads((Path(plan_dir) / f"{name}-two-arm.json").read_text(encoding="utf-8")), name=name) for name in names}


def _resolve_steps_file(dagger_model, steps_file, name="steps.json"):
    if steps_file and str(steps_file).strip().lower() != "auto":
        return Path(steps_file)
    for parent in Path(dagger_model).resolve().parents:
        candidate = parent / name
        if candidate.is_file():
            return candidate
    raise ValueError(f"--dagger-model requires --steps-file (or an ancestor {name})")


def _failed_steps_from_eval(dagger_model, eval_file):
    path = _resolve_steps_file(dagger_model, eval_file, name="eval.json")
    rows = json.loads(path.read_text(encoding="utf-8")).get("rows", [])
    return {f"{r['task']}/{r['step']}" if "task" in r else r["step"] for r in rows if r.get("result") != "pass"}
