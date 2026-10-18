"""``rosy.omx-sim-reach-task.v1``: reach a fixed joint pose from a seeded random start (SIM only).

Shared by the scripted teacher (``sim_reach_teacher.py``), the batch export
(``learning/curation/omx/sim_batch_export.py``) and the closed-loop evaluator: load this file by
path. Standard library only (``load_cell_limits`` needs PyYAML). No objects, no gripper check.

Fields (radians, seconds):
  schema            "rosy.omx-sim-reach-task.v1"
  task_id           [a-z0-9][a-z0-9._-]{0,63}
  joint_names       the recording's joint order (arm joints and the gripper joint)
  target_positions  {joint: rad | null}; null only where tolerance_rad is null
  tolerance_rad     {joint: rad in (0, 0.2] | null}; null = unchecked and never commanded
  start_sampling    {"seed": int >= 0, "ranges": {joint: [lo, hi] | null}}; a checked joint has a
                    range, an unchecked joint has null. Episode ``k`` samples with seed ``seed + k``.
  max_steps         jogs per episode, 1..500
  jog_step_rad      largest |delta| per jog, (0, 0.05] (BOUNDED_JOG_MAX_STEP_RAD)
  jog_duration_s    the ONE duration of every jog, 0.1..1.0 (act_job.py needs a single duration_s)

``validate_task(doc, cell_limits=...)`` additionally requires every target and range to lie inside
the cell profile limits inset by ``start_state_tolerance_rad`` (the range Pilot offers).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from pathlib import Path

SCHEMA = "rosy.omx-sim-reach-task.v1"
JUDGE = "sim_joint_readback"
MAX_JOG_STEP_RAD = 0.05          # core_common.protocol.controls.BOUNDED_JOG_MAX_STEP_RAD
JOG_DURATION_RANGE_S = (0.1, 1.0)  # OmxSimJog.duration_s
MAX_TOLERANCE_RAD = 0.2
MAX_STEPS = 500
FIELDS = {"schema", "task_id", "joint_names", "target_positions", "tolerance_rad", "start_sampling",
          "max_steps", "jog_step_rad", "jog_duration_s"}
CELL_PROFILE = Path(__file__).resolve().parent / "sim" / "cell_profile.yaml"


def _number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def load_cell_limits(path: Path = CELL_PROFILE) -> dict[str, tuple[float, float]]:
    """Per-joint admission range Pilot offers: cell profile limits inset by the start tolerance."""
    import yaml

    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    inset = float(doc["start_state_tolerance_rad"])
    limits = {name: tuple(spec["position"]) for name, spec in doc["joints"].items()}
    limits[doc["gripper"]["joint"]] = tuple(doc["gripper"]["position"])
    return {name: (float(lo) + inset, float(hi) - inset) for name, (lo, hi) in limits.items()}


def task_errors(doc, cell_limits: dict | None = None) -> list[str]:
    """Every reason ``doc`` is not a valid task (empty when valid)."""
    if not isinstance(doc, dict):
        return ["task must be a JSON object"]
    errors = []
    if set(doc) != FIELDS:
        errors.append(f"fields must be exactly {sorted(FIELDS)}; "
                      f"missing {sorted(FIELDS - set(doc))}, extra {sorted(set(doc) - FIELDS)}")
        return errors
    if doc["schema"] != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not isinstance(doc["task_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", doc["task_id"]):
        errors.append("task_id must match [a-z0-9][a-z0-9._-]{0,63}")
    names = doc["joint_names"]
    if (not isinstance(names, list) or not 1 <= len(names) <= 8
            or any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names)):
        return errors + ["joint_names must be 1-8 distinct non-empty strings"]
    targets, tolerances, sampling = doc["target_positions"], doc["tolerance_rad"], doc["start_sampling"]
    for label, value in (("target_positions", targets), ("tolerance_rad", tolerances)):
        if not isinstance(value, dict) or set(value) != set(names):
            errors.append(f"{label} must name exactly the joint_names")
    if (not isinstance(sampling, dict) or set(sampling) != {"seed", "ranges"}
            or type(sampling.get("seed")) is not int or sampling["seed"] < 0
            or not isinstance(sampling.get("ranges"), dict) or set(sampling["ranges"]) != set(names)):
        errors.append("start_sampling must be {seed: int >= 0, ranges: {joint: [lo, hi] | null}}")
    if errors:
        return errors
    checked = [name for name in names if tolerances[name] is not None]
    if not checked:
        errors.append("at least one joint must be checked")
    for name in names:
        tolerance, target, span = tolerances[name], targets[name], sampling["ranges"][name]
        if tolerance is None:
            if target is not None or span is not None:
                errors.append(f"{name}: an unchecked joint has null target and null range")
            continue
        if not _number(tolerance) or not 0 < tolerance <= MAX_TOLERANCE_RAD:
            errors.append(f"{name}: tolerance_rad must be in (0, {MAX_TOLERANCE_RAD}]")
        if not _number(target):
            errors.append(f"{name}: target must be a finite number")
        if (not isinstance(span, list) or len(span) != 2 or not all(_number(v) for v in span)
                or span[0] >= span[1]):
            errors.append(f"{name}: range must be [lo, hi] with lo < hi")
            continue
        if cell_limits is not None:
            if name not in cell_limits:
                errors.append(f"{name}: not a cell joint")
                continue
            lo, hi = cell_limits[name]
            if _number(target) and not lo <= target <= hi:
                errors.append(f"{name}: target {target} outside the offered range [{lo}, {hi}]")
            if not (lo <= span[0] and span[1] <= hi):
                errors.append(f"{name}: range {span} outside the offered range [{lo}, {hi}]")
    if type(doc["max_steps"]) is not int or not 1 <= doc["max_steps"] <= MAX_STEPS:
        errors.append(f"max_steps must be an integer in 1..{MAX_STEPS}")
    if not _number(doc["jog_step_rad"]) or not 0 < doc["jog_step_rad"] <= MAX_JOG_STEP_RAD:
        errors.append(f"jog_step_rad must be in (0, {MAX_JOG_STEP_RAD}]")
    low, high = JOG_DURATION_RANGE_S
    if not _number(doc["jog_duration_s"]) or not low <= doc["jog_duration_s"] <= high:
        errors.append(f"jog_duration_s must be one number in [{low}, {high}]")
    return errors


def validate_task(doc, cell_limits: dict | None = None) -> dict:
    errors = task_errors(doc, cell_limits)
    if errors:
        raise ValueError("invalid reach task: " + "; ".join(errors))
    return json.loads(json.dumps(doc))


def load_task(path: Path, *, cell_limits: dict | None = None) -> dict:
    return validate_task(json.loads(Path(path).read_text(encoding="utf-8")), cell_limits)


def task_sha256(task: dict) -> str:
    return hashlib.sha256(json.dumps(task, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def checked_joints(task: dict) -> list[str]:
    return [name for name in task["joint_names"] if task["tolerance_rad"][name] is not None]


def episode_seed(task: dict, index: int) -> int:
    return task["start_sampling"]["seed"] + index


def sample_start(task: dict, seed: int) -> dict[str, float]:
    """Deterministic start pose for ``seed``: uniform per checked joint, joint_names order, 4 dp."""
    rng = random.Random(seed)
    start = {}
    for name in checked_joints(task):
        lo, hi = task["start_sampling"]["ranges"][name]
        start[name] = round(rng.uniform(lo, hi), 4)
    return start


def errors_to_target(task: dict, positions: dict) -> dict[str, float]:
    """Signed target - readback per checked joint."""
    return {name: task["target_positions"][name] - positions[name] for name in checked_joints(task)}


def within_tolerance(task: dict, positions: dict) -> bool:
    """The task judge (``sim_joint_readback``): every checked joint within its tolerance."""
    return all(name in positions and abs(error) <= task["tolerance_rad"][name]
               for name, error in errors_to_target(task, positions).items())


def next_jog(task: dict, positions: dict) -> tuple[str, float] | None:
    """Greedy plan: the checked joint with the largest error/tolerance, moved min(step, |error|).

    None when every checked joint is within tolerance.
    """
    worst, ratio = None, 1.0
    for name, error in errors_to_target(task, positions).items():
        share = abs(error) / task["tolerance_rad"][name]
        if share > ratio:
            worst, ratio = name, share
    if worst is None:
        return None
    error = task["target_positions"][worst] - positions[worst]
    return worst, round(math.copysign(min(abs(error), task["jog_step_rad"]), error), 6)
