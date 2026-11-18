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
    """The auto_clear verdict (auto_clear's return) as an event; the incident id is Fleet's, not known here."""
    note_event({"kind": "auto_clear", "arm": arm, "incident_id": None, "result": bool(verdict.get("cleared")),
                "why": verdict.get("why")})


def _fault_kind(path) -> dict:
    """What a person would read first in a motor-health fault record: its fault and stop reasons (D-1047)."""
    try:
        record = json.loads(Path(path).read_text())
        return {"fault": str(record.get("fault"))[:200], "stop_reasons": list(record.get("stop_reasons") or [])}
    except (OSError, ValueError, AttributeError, TypeError):
        return {"fault": None, "stop_reasons": None}


def launch_auto_fold(arm: str, popen=None) -> dict:
    """D-1048: start cell_auto_fold for this arm in its own process once this session has let go of the arm. Off unless
    ~/.config/rosy/auto-fold.json names the arm (its wrapper, config, library, site and roi)."""
    import os
    import subprocess

    conf = Path(os.environ.get("ROSY_AUTO_FOLD_CONFIG", str(Path.home() / ".config" / "rosy" / "auto-fold.json")))
    try:
        if arm not in json.loads(conf.read_text(encoding="utf-8")):
            return {"started": False, "why": f"{arm} not in {conf.name}"}
    except (OSError, ValueError):
        return {"started": False, "why": f"no {conf.name}"}
    command = [sys.executable, str(Path(__file__).resolve().parent / "cell_auto_fold.py"), "launch", "--arm", arm,
               "--config-file", str(conf)]
    try:
        (popen or subprocess.Popen)(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"started": True}
    except OSError as exc:
        return {"started": False, "why": f"{type(exc).__name__}: {exc}"[:160]}


def assessor_token_file() -> Path | None:
    import os

    named = os.environ.get("ROSY_ARM_ASSESSOR_TOKEN_FILE")
    found = [Path(named)] if named else sorted((Path.home() / ".config" / "rosy").glob("*-ai-assessor.token"))
    return next((p for p in found if p.is_file()), None)


def auto_clear(arm: str, f: dict, link, clear_fn=None) -> dict:
    """D-1047 (user 2026-11-19, "보류 해제를 완전히 자동화"): the same rule Fleet applies (machine_clearable) is checked here
    first; when it allows, the cell's AI assessor clears at once, so a link failure on a rested, torque-OFF arm no longer
    waits for a person. Fleet still re-judges the stored facts and its repeat limit; any refusal leaves the hold."""
    try:
        from core_common.protocol.arm_incidents import machine_clearable

        ok, why = machine_clearable(f)
    except Exception as exc:  # the rule cannot judge: the hold stays
        return {"cleared": False, "why": f"rule unavailable: {type(exc).__name__}"}
    token = assessor_token_file()
    if not ok or token is None or link is None:
        return {"cleared": False, "why": why if not ok else "no assessor token or Fleet link"}
    try:
        (clear_fn or _clear())(arm, f"automatic (D-1047): {why}", token, link, cause="software_or_config", basis="measured")
        return {"cleared": True, "why": why}
    except (SystemExit, Exception) as exc:  # Fleet refused (kind or repeat limit) or unreachable: the hold stays
        return {"cleared": False, "why": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _clear():
    from omx_incident import clear

    return clear
