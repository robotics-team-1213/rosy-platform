#!/usr/bin/env python3
"""Reviewed whole-task evidence for the native cell; no actuator or admission authority."""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from guarded_native import MAX_GAP_S, NAMES

SCHEMA = "rosy.omx-cell-envelope.v1"


def digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _code_digest() -> str:
    from omx_adapter import chunk_library, motion_profile

    root = Path(__file__).resolve().parent
    files = {name: root / name for name in (
        "cell_envelope.py", "cell_pipeline.py", "cell_pipeline_io.py", "cell_attempts.py",
        "guarded_native.py", "chunk_runner.py", "grasp_planner.py", "motion_profile.py", "teach_trajectory.py")}
    files.update({module.__name__: Path(module.__file__) for module in (chunk_library, motion_profile)})
    return digest({name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                   for name, path in files.items()})


def runtime_context(robot_config: dict, bus, fps: int) -> dict:
    """Read before the control loop starts; the session owns this bus without hot reconfiguration."""
    motors = {}
    for name in NAMES:
        motor = bus.motors[name]
        registers = ["Operating_Mode", "PWM_Limit", "Position_P_Gain", "Position_I_Gain",
                     "Position_D_Gain", "Profile_Velocity", "Profile_Acceleration"]
        if motor.model.startswith(("xm", "xl330")):
            registers.append("Current_Limit")
        motors[name] = {"id": motor.id, "model": motor.model,
                        "calibration": asdict(bus.calibration[name]),
                        "registers": {key: bus.read(key, name) for key in registers}}
    return {"scope": "hardware", "session_id": uuid.uuid4().hex,
            "sha256": digest({"robot": robot_config, "motors": motors, "fps": fps, "code": _code_digest()})}


def _sha(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _state_current(state: dict, now: float) -> bool:
    return (isinstance(state, dict) and state.get("ok") is True and not state.get("fault")
            and _number(state.get("t")) and 0 <= now - state["t"] <= MAX_GAP_S
            and isinstance(state.get("operating_context"), dict)
            and state["operating_context"].get("scope") in ("hardware", "simulation")
            and isinstance(state["operating_context"].get("session_id"), str)
            and bool(state["operating_context"]["session_id"].strip())
            and _sha(state["operating_context"].get("sha256")))


def _conditions(config: dict) -> dict:
    values = config.get("operating_conditions")
    if not isinstance(values, dict):
        raise ValueError("operating_conditions are required")
    for name in ("installation_revision", "object_revision", "environment_revision"):
        if not isinstance(values.get(name), str) or not values[name].strip():
            raise ValueError(f"operating_conditions.{name} is required")
    dimensions = values.get("object_dimensions_m")
    if (not _number(values.get("payload_kg")) or values["payload_kg"] <= 0
            or not isinstance(dimensions, list) or len(dimensions) != 3
            or any(not _number(v) or v <= 0 for v in dimensions)):
        raise ValueError("measured payload_kg and three positive object_dimensions_m are required")
    return values


def assess(config: dict, calibration: dict, library: dict, state: dict, *, now=None) -> dict:
    """Exact paths only: no radius shrink, spatial interpolation or automatic promotion from success."""
    out = {"schema": SCHEMA, "mode": "automatic", "status": "unverified", "allowed": False,
           "reason": "not_reviewed"}
    now = time.time() if now is None else now
    if not _number(now) or not _state_current(state, now):
        return {**out, "reason": "state_unavailable"}
    context = state["operating_context"]
    try:
        conditions = _conditions(config)
        conditions_sha = digest({"conditions": conditions, "calibration": calibration,
                                  "profiles": config.get("profiles"), "cameras": config.get("cameras"),
                                  "sites": config.get("sites"), "plan": config.get("plan")})
        out.update(scope=context["scope"], runtime_sha256=context["sha256"], session_id=context["session_id"],
                   conditions=conditions,
                   conditions_sha256=conditions_sha, library_sha256=digest(library), client_code_sha256=_code_digest())
        out["task_sha256"] = digest({key: out[key] for key in (
            "scope", "runtime_sha256", "conditions_sha256", "library_sha256", "client_code_sha256")})
        if "_commissioning" in config:
            trial = config["_commissioning"]
            if (not isinstance(trial, dict) or set(trial) != {"person_at_switch"}
                    or trial["person_at_switch"] is not True):
                return {**out, "reason": "commissioning_requires_person"}
            return {**out, "mode": "commissioning", "status": "commissioning", "allowed": True,
                    "reason": "supervised_trial"}
        review_path = Path(config["operating_envelope_path"]).expanduser()
        document = json.loads(review_path.read_text(encoding="utf-8"))
        if (not isinstance(document, dict) or document.get("schema") != SCHEMA
                or not isinstance(document.get("reviews"), list)
                or any(not isinstance(r, dict) for r in document["reviews"])):
            raise ValueError("invalid operating envelope")
        matching = [r for r in document["reviews"] if r["task_sha256"] == out["task_sha256"]]
        if not matching:
            return out
        if len(matching) != 1:
            raise ValueError("duplicate task reviews")
        review = matching[0]
        if (review.get("scope") != context["scope"]
                or any(not isinstance(review.get(k), str) or not review[k].strip()
                       for k in ("reviewed_by", "evidence_ref"))):
            raise ValueError("a scoped human review with physical evidence is required")
        required, rate, tolerance = (review.get(k) for k in (
            "min_attempts", "min_success_rate", "home_tolerance_units"))
        if (type(required) is not int or required < 1 or not _number(rate) or not 0 < rate <= 1
                or not _number(tolerance) or tolerance <= 0):
            raise ValueError("review must specify repetition, success and start tolerances")
        positions, home = state.get("state"), library["chunks"]["home"][-1]
        if (not isinstance(positions, list) or len(positions) != 6 or len(home) != 6
                or any(not _number(v) for v in positions + home)
                or max(abs(a - b) for a, b in zip(positions[:5], home[:5])) > tolerance):
            return {**out, "reason": "start_not_home"}
        ledger = Path(document["attempts_path"]).expanduser()
        if not ledger.is_absolute():
            ledger = review_path.parent / ledger
        if ledger.resolve() != (Path(config["work_dir"]).expanduser() / "attempts.jsonl").resolve():
            raise ValueError("review must use this pipeline's active attempt ledger")
        if ledger.with_suffix(".pending.json").exists():
            return {**out, "reason": "incomplete_attempt"}
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        if any(not isinstance(row, dict) or not isinstance(row.get("envelope", {}), dict) for row in rows):
            raise ValueError("invalid attempt row")
        rows = [r for r in rows if (r.get("envelope") or {}).get("task_sha256") == out["task_sha256"]]
        ids = [r["attempt_id"] for r in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate attempt identity")
        if any(r["envelope"].get("mode") == "automatic" and r.get("outcome") == "failed" for r in rows):
            return {**out, "status": "failed", "reason": "runtime_failure"}
        trials = [r for r in rows if r["envelope"].get("mode") == "commissioning"]
        if digest(trials) != review.get("attempts_sha256"):
            return {**out, "reason": "evidence_changed"}
        if any(r.get("schema") != "rosy.omx-cell-attempt.v1" or
               r["envelope"].get("scope") != context["scope"] or
               r["envelope"].get("allowed") is not True or
               r["envelope"].get("status") != "commissioning" for r in trials):
            raise ValueError("trials must retain their attempt schema and scope")
        if any(not isinstance(r.get("verify", {}), dict) or not isinstance(r.get("transfer", {}), dict) for r in trials):
            raise ValueError("invalid trial observations")
        successes = sum(r.get("outcome") == "placed" and (r.get("verify") or {}).get("inside") is True
                        and (r.get("transfer") or {}).get("result") == "placed" for r in trials)
        out.update(attempts=len(trials), successes=successes, evidence_ref=review["evidence_ref"],
                   reviewed_by=review["reviewed_by"])
        if len(trials) < required or successes / len(trials) < rate:
            return {**out, "status": "failed", "reason": "acceptance_not_met"}
        return {**out, "allowed": True, "status": "verified", "reason": "reviewed_exact_task"}
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError):
        return {**out, "reason": "evidence_unavailable"}


def same_session(state: dict, assessment: dict, *, now=None) -> bool:
    """Recheck current owner facts between chunks; this is additional to the existing motion guard."""
    now = time.time() if now is None else now
    return (_number(now) and _state_current(state, now)
            and state["operating_context"] == {"scope": assessment.get("scope"),
                                                "sha256": assessment.get("runtime_sha256"),
                                                "session_id": assessment.get("session_id")})


def review_candidates(rows: list[dict]) -> dict:
    """Inspection only; a candidate's observed success fraction is not a reliability claim or approval."""
    tasks = {}
    for row in rows:
        facts = row.get("envelope") or {}
        key = facts.get("task_sha256")
        if not key:
            continue
        candidate = tasks.setdefault(key, {"status": "unreviewed", "scope": facts.get("scope"),
            "conditions": facts.get("conditions"), "runtime_sha256": facts.get("runtime_sha256"),
            "library_sha256": facts.get("library_sha256"), "trials": [], "automatic_failures": 0})
        if facts.get("mode") == "commissioning":
            candidate["trials"].append(row)
        elif row.get("outcome") == "failed":
            candidate["automatic_failures"] += 1
    for candidate in tasks.values():
        trials = candidate.pop("trials")
        count = sum(r.get("outcome") == "placed" for r in trials)
        candidate.update(attempts=len(trials), successes=count, attempts_sha256=digest(trials),
                         observed_success_fraction=count / len(trials) if trials else None)
    return tasks
