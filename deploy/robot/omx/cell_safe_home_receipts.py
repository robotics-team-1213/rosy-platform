"""Cell worker capability and durable acknowledgements for guarded home requests."""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any


def _read_ack_map(ack_file: Path) -> dict[str, dict[str, Any]]:
    if not ack_file.is_file():
        return {}
    raw = json.loads(ack_file.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    return {}


def _write_ack_map_atomic(ack_file: Path, ack_map: dict[str, dict[str, Any]]) -> None:
    if not ack_map:
        if ack_file.exists():
            ack_file.unlink()
        return
    ack_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = ack_file.with_name(f"{ack_file.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ack_map), encoding="utf-8")
    os.replace(tmp, ack_file)


def _bound_home_arms(launcher):
    try:
        import cell_auto_fold, cell_auto_fold_stages, omx_incident_auto
        if (cell_auto_fold_stages.BOUND_INCIDENT_OPTION == "--expected-incident-id"
                and "expected_incident_id" in inspect.signature(cell_auto_fold.launch).parameters
                and "expected_incident_id" in inspect.signature(launcher or omx_incident_auto.launch_auto_fold).parameters):
            return omx_incident_auto.configured_fold_arms()
    except (AttributeError, ImportError, ValueError, TypeError):
        pass
    return []


def _home_result_ack(prep_dir, arm, req_id, incident_id):
    path = prep_dir / "incidents" / f"auto-fold-req-{req_id}.result.json"
    if not path.is_file():
        try:
            import omx_incident_fleet
            path = Path(omx_incident_fleet.INCIDENTS) / path.name
        except (ImportError, AttributeError):
            return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    ack = {"arm_id": arm, "request_id": req_id, "outcome": str(record.get("outcome") or "completed")}
    if record.get("detail"):
        ack["detail"] = record["detail"]
    if incident_id:
        ack["incident_id"] = incident_id
        result = record.get("result") or {}
        if (record.get("arm") != arm or record.get("request_id") != req_id or record.get("stage") != "full"
                or (ack["outcome"] == "completed" and not (
                    isinstance(result, dict) and result.get("result") == "cleared"
                    and result.get("bound_incident_id") == result.get("incident_id") == incident_id
                    and isinstance(result.get("evidence"), dict)
                    and result["evidence"].get("incident_id") == incident_id))):
            ack.update(outcome="failed", detail="HOME_RECOVERY_EVIDENCE_MISMATCH")
        elif ack["outcome"] == "completed":
            ack["cleared_incident_id"] = incident_id
    return ack
