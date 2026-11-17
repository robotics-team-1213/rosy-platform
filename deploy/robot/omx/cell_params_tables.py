"""Read-only servo, attempt-history, and arm-incident table builders for `cell_params_web.py`."""
from __future__ import annotations

import json
from pathlib import Path

ATTEMPTS_SHOWN = 12


def servo_table(name: str, caps: Path, profile: Path | None = None) -> dict:
    """One arm's servo values for the page; a file a session would refuse shows its reason instead."""
    try:
        import guarded_native
        import session_caps

        layers = session_caps.servo_layers(caps, model=session_caps.model_tuning(),
                                           robot=session_caps.robot_tuning(profile))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SystemExit) as exc:
        return {"name": name, "error": f"{caps.name}: {exc}"}
    return {"name": name, "path": str(caps), "profile": str(profile) if profile else None,
            "motors": [{"id": motor, "joint": joint, "values": layers[motor]}
                       for motor, joint in zip(layers, guarded_native.NAMES)]}


def attempts_table(name: str, path: Path) -> dict:
    """Recent auto-pick / tier-stacking attempts from attempts.jsonl (read-only)."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"name": name, "path": str(p), "rows": []}
    rows = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"name": name, "path": str(p), "error": f"{p.name}: {exc}", "rows": []}
    for raw in reversed(lines[-ATTEMPTS_SHOWN:]):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        steps = [
            {"command": s.get("command"), "ok": s.get("ok"), "holding": s.get("holding"),
             "verdict": s.get("verdict"), "error": s.get("error"), "current_ma": s.get("gripper_current_ma")}
            for s in ((row.get("transfer") or {}).get("steps") or [])
        ]
        rows.append({
            "attempt_id": row.get("attempt_id"),
            "t_utc": row.get("t_utc"),
            "run_id": row.get("run_id"),
            "from": row.get("from"),
            "to": row.get("to"),
            "tier": row.get("tier"),
            "outcome": row.get("outcome"),
            "holding": row.get("holding"),
            "gripper_current_ma": row.get("gripper_current_ma"),
            "verify": row.get("verify"),
            "fail_stage": row.get("fail_stage"),
            "fail_class": row.get("fail_class"),
            "plan": row.get("plan"),
            "object": row.get("object") or (row.get("auto") or {}).get("object") or (row.get("locate") or {}).get("object"),
            "diagnosis": row.get("diagnosis"),
            "steps": steps,
        })
    return {"name": name, "path": str(p), "rows": rows}


def incidents_table(arms: list[str]) -> list[dict]:
    """Current local and Fleet hold status for each configured arm."""
    import omx_incident

    out = []
    for arm in arms:
        try:
            out.append(omx_incident.status(arm))
        except Exception as exc:
            out.append({"arm": arm, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    return out
