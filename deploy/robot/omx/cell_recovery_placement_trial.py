"""Durable D-911 outcomes for the exact cargo placement sequence."""
import time
import uuid
from pathlib import Path

import cell_attempts
import cell_envelope


def record_placement(backend, candidate, place):
    from cell_recovery_placement_live import SEQUENCE

    gate, config = candidate["assessment"], backend.config
    ledger = Path(config["work_dir"]).expanduser() / "attempts.jsonl"
    cell_attempts.start(ledger, run_id="recovery-place-" + uuid.uuid4().hex, arm_id=backend.args.arm,
                        params=config.get("params_path"))
    intent = cell_attempts.begin(config, gate)
    if intent is None:
        raise OSError("missing D-911 placement intent")
    started = time.time()
    receipt = {"reason": "placement interrupted"}
    try:
        checked = cell_envelope.assess(
            config, backend.calibration, candidate["library"], backend._state(backend.lib_sha, True),
            sequence=(*SEQUENCE, "restore-library " + backend.lib_sha), check_home=False, allow_pending=intent)
        if checked != gate or checked.get("allowed") is not True:
            receipt = {"reason": "placement review changed after planning"}
        else:
            receipt = place(candidate)
        if not isinstance(receipt, dict):
            receipt = {"reason": "invalid placement receipt"}
    except Exception as exc:
        receipt = {"reason": f"{type(exc).__name__}: {exc}"}
        raise
    finally:
        verification = receipt.get("verification") or {}
        passed = (isinstance(verification, dict) and verification.get("inside") is True
                  and verification.get("verified") is True and verification.get("object_id") == backend.cargo["object_id"]
                  and all(receipt.get(key) is True for key in ("supported", "released", "retreated", "verified")))
        tried = {"envelope": gate, "incident_id": backend.args.expected_incident_id,
                 "locate": {"found": True, "source": "confirmed_held_cargo"},
                 "verify": verification, "transfer": {"result": "placed" if passed else "failed"},
                 "placement_receipt": receipt}
        if not passed:
            tried["fail"] = {"stage": "recovery_placement", "class": receipt.get("reason") or "placement unverified"}
        attempt_id = cell_attempts.record(config, backend.calibration, "held_cargo", candidate["target"], 1,
                                          tried, started)
    return {**receipt, "verified": passed, "attempt_id": attempt_id}
