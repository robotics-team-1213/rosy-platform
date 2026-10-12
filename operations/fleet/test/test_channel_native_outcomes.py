"""A CORE ACK and a Fleet claim are separate from exact native completion."""

import asyncio
import json
from uuid import uuid4

from test_channel_natural_execution import fixture


HOME_TEXT = "40번 홈으로 복귀해줘"
HOME_PLAN = {"do": "home", "robot": "rosy_40"}


def _operation(run_id, boot_id, correlation_id, *, phase="SUBMITTED", result=None):
    return {
        "run_id": str(run_id), "boot_id": str(boot_id), "kind": "home",
        "correlation_id": correlation_id, "phase": phase, "result": result,
        "reason": None,
    }


def _home_with_native_ack(tmp_path):
    f = fixture(tmp_path, HOME_TEXT, HOME_PLAN)
    run_id, boot_id = uuid4(), uuid4()
    sent = []

    async def post(path, body):
        sent.append((path, body))
        cid = body.get("correlation_id") if isinstance(body, dict) else None
        return {"accepted": True, "mode": "NAVIGATION",
                "operation": _operation(run_id, boot_id, cid)}

    f.client._post = post
    asyncio.run(f.worker.step(f.receipt["request_id"]))
    return f, run_id, boot_id, sent


def test_direct_ack_persists_core_run_and_caller_identity_without_completion(tmp_path):
    f, run_id, boot_id, sent = _home_with_native_ack(tmp_path)
    step = f.journal.view(f.receipt["request_id"])["steps"][0]

    assert len(sent) == 1
    assert isinstance(sent[0][1], dict) and sent[0][1].get("correlation_id")
    assert step["state"] == "ACCEPTED"
    assert json.loads(step["receipt_json"])["operation"] == _operation(
        run_id, boot_id, sent[0][1]["correlation_id"])
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40")


def test_terminal_result_does_not_advance_until_exact_quiescence(tmp_path):
    f, run_id, boot_id, sent = _home_with_native_ack(tmp_path)
    cid = sent[0][1].get("correlation_id") if isinstance(sent[0][1], dict) else None
    state = {
        "lookup": "FOUND",
        "operation": _operation(run_id, boot_id, cid, phase="TERMINAL", result="SUCCEEDED"),
        "owner": {"boot_id": str(boot_id), "owner_generation": 4, "owner_run_id": None},
        "quiescence": {
            "boot_id": str(boot_id), "requested_run_id": str(run_id),
            "owner_run_id": None, "observed_at": "2026-10-12T12:00:00Z",
            "owner_generation": 4, "transport_generation": 8,
            "admitting": False, "pending_submission": True,
            "actuating_callback": False, "lease_active": False, "quiescent": False,
        },
    }
    reads = []

    async def get(path):
        reads.append(path)
        return state

    f.client._get = get
    rid = f.receipt["request_id"]
    asyncio.run(f.worker.step(rid))
    assert f.journal.view(rid)["steps"][0]["state"] != "COMPLETED"
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40")

    state["quiescence"]["pending_submission"] = False
    state["quiescence"]["quiescent"] = True
    asyncio.run(f.worker.step(rid))
    assert reads and all("run_id=" + str(run_id) in path for path in reads)
    assert f.journal.view(rid)["steps"][0]["state"] == "COMPLETED"
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40") == []
    assert len(sent) == 1


def test_expired_origin_allows_read_only_closure_but_no_new_rpc(tmp_path):
    f, run_id, boot_id, sent = _home_with_native_ack(tmp_path)
    cid = sent[0][1].get("correlation_id") if isinstance(sent[0][1], dict) else None

    async def get(path):
        assert "run_id=" + str(run_id) in path
        return {
            "lookup": "FOUND",
            "operation": _operation(run_id, boot_id, cid, phase="TERMINAL", result="SUCCEEDED"),
            "owner": {"boot_id": str(boot_id), "owner_generation": 2, "owner_run_id": None},
            "quiescence": {
                "boot_id": str(boot_id), "requested_run_id": str(run_id),
                "owner_run_id": None, "observed_at": "2026-10-12T12:00:00Z",
                "owner_generation": 2, "transport_generation": 3,
                "admitting": False, "pending_submission": False,
                "actuating_callback": False, "lease_active": False, "quiescent": True,
            },
        }

    f.client._get = get
    f.clock[0] += 121
    asyncio.run(f.worker.step(f.receipt["request_id"]))
    assert f.journal.view(f.receipt["request_id"])["steps"][0]["state"] == "COMPLETED"
    assert f.store.resource_claims(resource_kind="robot", resource_id="rosy_40") == []
    assert len(sent) == 1
