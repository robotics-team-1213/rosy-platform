import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from cell_bound_home_request import HOME_RECOVERY_REASON, request_current_homes


def test_commissioned_worker_requests_only_its_current_usb_record(monkeypatch):
    arm, incident = "arm_a", "a" * 32
    root = f"home-recovery:{arm}:{incident}"
    item = {"root_task_id": root, "arm_id": arm, "trigger_code": "HOME_RECOVERY_REQUIRED",
            "context_sha256": "a" * 64, "homing_strategies": {"auto_fold": {"allowed": True}}}
    holds = {arm: {"fleet_held": True, "incident_ids": [incident], "unsent_outbox": 0, "fleet_reason": HOME_RECOVERY_REASON}}
    calls = []
    monkeypatch.setattr("cell_bound_home_request.bound_request_due", lambda *_: False)

    def exchange(req, **kwargs):
        calls.append(req)
        return io.BytesIO(json.dumps({"active_failures": [{**item, "root_task_id": "old"}, item]}).encode())

    def run(arms, pending):
        request_current_homes("https://site", "test", None, exchange, arms, holds, pending)

    run([], {})
    run([arm], {arm: {}})
    run([arm], {})
    assert not calls
    monkeypatch.setattr("cell_bound_home_request.bound_request_due", lambda *_: True)
    run([arm], {})
    run([arm], {})
    assert [r.get_method() for r in calls] == ["GET", "POST", "GET", "POST"]
    proposal = json.loads(calls[1].data)
    assert calls[1].data == calls[3].data and proposal["root_task_id"] == root
    assert proposal["expected_context_sha256"] == item["context_sha256"] and proposal["caller_kind"] == "system"
