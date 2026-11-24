"""What omx_incident does on its own after a held incident (D-1047, D-1048): judge it with Fleet's rule and clear it at
once, or start cell_auto_fold; and read a motor-health fault record's kind. Split from omx_incident for size."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def note_event(row: dict) -> None:
    """One line of what the cell did by itself (kind, arm, incident_id, result, why, candidate), kept in
    incidents/auto-events.jsonl; cell_camera_telemetry_sync sends the tail to Fleet. Never raises."""
    try:
        import omx_incident_fleet

        path = Path(omx_incident_fleet.INCIDENTS) / "auto-events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({**row, "t": time.time()}, default=str) + "\n")
    except Exception:  # a lost note must never change what the arm does
        pass


def note_auto_clear(arm: str, verdict: dict) -> None:
    """The auto_clear verdict (auto_clear's return) as a Fleet-valid auto-events.jsonl row."""
    why = verdict.get("why")
    if "safety_score" in verdict:
        why = f"score={verdict['safety_score']}/{verdict.get('threshold', 95)} ({verdict.get('decision', '?')}): {why or ''}"[:200]
    note_event({"kind": "auto_clear", "arm": arm, "incident_id": verdict.get("incident_id"),
                "result": bool(verdict.get("cleared")), "why": why})


def _fault_kind(path) -> dict:
    """What a person would read first in a motor-health fault record: its fault and stop reasons (D-1047)."""
    try:
        record = json.loads(Path(path).read_text())
        return {"fault": str(record.get("fault"))[:200], "stop_reasons": list(record.get("stop_reasons") or [])}
    except (OSError, ValueError, AttributeError, TypeError):
        return {"fault": None, "stop_reasons": None}


def launch_auto_fold(arm: str, popen=None, *, stage: str = "full", request_id: str | None = None,
                     expires_at: float | None = None, stop_generation: int | None = None,
                     safety_fence: str | None = None) -> dict:
    """D-1048: start cell_auto_fold for this arm in its own process once this session has let go of the arm. Off unless
    ~/.config/rosy/auto-fold.json names the arm (its wrapper, config, library, site and roi)."""
    import os
    import subprocess

    if stage not in ("full", "release_and_lift", "park_only"):
        return {"started": False, "why": f"invalid stage: {stage}"}
    conf = Path(os.environ.get("ROSY_AUTO_FOLD_CONFIG", str(Path.home() / ".config" / "rosy" / "auto-fold.json")))
    try:
        if arm not in json.loads(conf.read_text(encoding="utf-8")):
            return {"started": False, "why": f"{arm} not in {conf.name}"}
    except (OSError, ValueError):
        return {"started": False, "why": f"no {conf.name}"}
    command = [sys.executable, str(Path(__file__).resolve().parent / "cell_auto_fold.py"), "launch",
               "--arm", arm, "--config-file", str(conf), "--stage", stage]
    if request_id:
        command += ["--request-id", str(request_id)]
    if expires_at is not None:
        command += ["--expires-at", f"{float(expires_at):.3f}"]
    if stop_generation is not None:
        command += ["--stop-generation", str(int(stop_generation))]
    if safety_fence:
        command += ["--safety-fence", str(safety_fence)]
    try:
        (popen or subprocess.Popen)(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"started": True, "stage": stage}
    except OSError as exc:
        return {"started": False, "why": f"{type(exc).__name__}: {exc}"[:160]}


def assessor_token_file() -> Path | None:
    import os

    named = os.environ.get("ROSY_ARM_ASSESSOR_TOKEN_FILE")
    found = [Path(named)] if named else sorted((Path.home() / ".config" / "rosy").glob("*-ai-assessor.token"))
    return next((p for p in found if p.is_file()), None)


def _ensure_core_common() -> None:
    here = Path(__file__).resolve()
    if len(here.parents) > 3:
        extra = here.parents[3] / "contracts" / "foundation"
        if extra.is_dir() and str(extra) not in sys.path:
            sys.path.append(str(extra))


def auto_clear(arm: str, f: dict, link, clear_fn=None, *, remeasured=None, recovery=None, camera_check=None,
               motor_health=None, recent_clears_24h: int = 0, since=None, now=None, incident_id=None,
               binding=None, min_score: int = 95, only=None) -> dict:
    """D-1047 + 95+ risk pipeline: enforce Fleet's hard rules and deterministic safety_score >= 95 before calling the
    AI assessor to clear. Refuses and escalates to a human when any hard veto hits or safety_score < 95."""
    try:
        _ensure_core_common()
        from core_common.protocol.arm_incident.arm_incidents import evaluate_clear_safety

        risk = evaluate_clear_safety(
            f, remeasured=remeasured, recovery=recovery, camera_check=camera_check,
            motor_health=motor_health, recent_clears_24h=recent_clears_24h,
            since=since, now=now, incident_id=incident_id, binding=binding, min_score=min_score,
        )
    except Exception as exc:  # invalid threshold or rule unavailable: fail closed, hold stays
        return {
            "cleared": False, "why": f"rule unavailable: {type(exc).__name__}: {str(exc)[:120]}",
            "safety_score": 0, "risk_score": 100, "threshold": 95, "decision": "escalate_human",
            "hard_vetoes": [{"code": "RULE_UNAVAILABLE", "detail": str(exc)[:120]}], "deductions": [],
        }

    base = {
        "safety_score": risk["safety_score"], "risk_score": risk["risk_score"],
        "threshold": risk["threshold"], "decision": risk["decision"],
        "hard_vetoes": risk["hard_vetoes"], "deductions": risk["deductions"],
    }
    if not risk["allowed"]:
        if risk["hard_vetoes"]:
            first = risk["hard_vetoes"][0]
            why = (risk["policy_reason"] if first["code"] == "POLICY_NOT_CLEARABLE"
                   else f"vetoed (score {risk['safety_score']}/100): "
                        + ", ".join(v["code"] for v in risk["hard_vetoes"]))
        else:
            why = (f"safety score {risk['safety_score']}/{risk['threshold']} below threshold: "
                   + ", ".join(d["code"] for d in risk["deductions"]))
        return {"cleared": False, "why": why, **base}

    token = assessor_token_file()
    if token is None or link is None:
        return {"cleared": False, "why": "no assessor token or Fleet link", **base}

    extra = {}
    if remeasured is not None:
        extra["remeasured"] = remeasured
    if recovery is not None:
        extra["recovery"] = recovery
    if only is not None:
        extra["only"] = only
    try:
        (clear_fn or _clear())(
            arm, f"automatic (D-1047, score={risk['safety_score']}/100): {risk['policy_reason']}",
            token, link, cause="software_or_config", basis="measured", **extra,
        )
        return {"cleared": True, "why": risk["policy_reason"], **base}
    except (SystemExit, Exception) as exc:  # Fleet refused (kind or repeat limit) or unreachable: the hold stays
        return {"cleared": False, "why": f"{type(exc).__name__}: {str(exc)[:160]}", **base}


def _clear():
    from omx_incident import clear

    return clear
