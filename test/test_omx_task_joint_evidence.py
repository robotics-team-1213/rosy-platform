"""A supervised attempt copies only the owner's bound, contiguous trace bytes."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(ROOT))
from cell_task_joint_evidence import AttemptJointEvidence  # noqa: E402


def _receipt(source, command, sequence, start, end, data):
    return {"status": "ok", "source": source, "command": command, "sequence": sequence,
            "start": start, "end": end, "sha256": hashlib.sha256(data).hexdigest(),
            "session_id": "session-1", "library_sha256": "lib-1", "reported_at": 5.0 + sequence}


def _status(receipt=None):
    return {"ok": True, "state": [0] * 6, "target": [0] * 6, "t": receipt["reported_at"] if receipt else 1.0,
            "health": {"pwm": [1] * 6}, "operating_context": {"session_id": "session-1"},
            **({"trace_receipt": receipt} if receipt else {})}


@pytest.mark.parametrize(("requested", "reported"), [
    ("run lift_pick", "run lift_pick"),
    ("goto above_pick", "run goto above_pick"),
    ("park", "run park"),
])
def test_owner_trace_is_copied_after_load_baseline_with_task_binding(tmp_path, requested, reported):
    io = tmp_path / "chunk-io-b"
    io.mkdir()
    source = tmp_path / "trace-arm_b.jsonl"
    before = b'{"t":1,"present":[0,0,0,0,0,0],"sent":null,"pwm":{},"owner_session_id":"previous-session","library_sha256":"previous-library"}\n'
    idle = b'{"t":1.5,"present":[0,0,0,0,0,0],"sent":null,"pwm":{},"owner_session_id":"session-1","library_sha256":"lib-1"}\n'
    moving = b'{"t":2,"present":[1,1,1,1,1,1],"sent":[1,1,1,1,1,1],"pwm":{"shoulder":3},"owner_session_id":"session-1","library_sha256":"lib-1"}\n'
    source.write_bytes(before)
    evidence = AttemptJointEvidence(tmp_path / "work", "task-1", "run-1", "lease-1", "lib-1",
                                    session_id="session-1", owner_io=io).start()
    assert evidence.record("load lib", _status(_receipt(source.name, "load lib", 2, 0, len(before), before)))
    with source.open("ab") as stream:
        stream.write(idle + moving)
    status = _status(_receipt(source.name, reported, 4,
                              len(before) + len(idle), len(before) + len(idle) + len(moving), moving))
    status["command"] = reported
    status["pre_state_trace"] = {"t": 8.0, "trace_receipt": _receipt(
        source.name, "state", 3, len(before), len(before) + len(idle), idle)}
    assert evidence.record(requested, status)
    manifest = evidence.stop()
    assert manifest["continuous_trace"] == "captured" and manifest["torque_nm"] == "UNKNOWN"
    assert Path(manifest["owner_trace_path"]).read_bytes() == idle + moving
    rows = [json.loads(line) for line in evidence.path.read_text().splitlines()]
    assert rows[0]["task_id"] == "task-1" and rows[0]["handoff_lease_id"] == "lease-1"


def test_owner_trace_hash_mismatch_fails_before_next_command(tmp_path):
    io = tmp_path / "chunk-io-b"
    io.mkdir()
    source = tmp_path / "trace-arm_b.jsonl"
    source.write_bytes(b"sample\n")
    evidence = AttemptJointEvidence(tmp_path / "work", "task-1", "run-1", "lease-1", "lib-1",
                                    session_id="session-1", owner_io=io).start()
    receipt = _receipt(source.name, "load lib", 2, 0, 7, b"different")
    with pytest.raises(ValueError, match="trace"):
        evidence.record("load lib", _status(receipt))
    assert evidence.stop()["continuous_trace"] == "UNKNOWN"


@pytest.mark.parametrize(("foreign_session", "foreign_library"), [
    ("other", "lib-1"), ("session-1", "other-library"),
])
def test_mixed_writer_tick_is_rejected_even_with_a_valid_segment_hash(tmp_path, foreign_session, foreign_library):
    io = tmp_path / "chunk-io-b"
    io.mkdir()
    source = tmp_path / "trace-arm_b.jsonl"
    baseline = b'{"t":1,"present":[0,0,0,0,0,0],"sent":null,"pwm":{},"owner_session_id":"session-1","library_sha256":"lib-1"}\n'
    foreign = (json.dumps({"t": 2, "present": [0] * 6, "sent": None, "pwm": {},
                           "owner_session_id": foreign_session,
                           "library_sha256": foreign_library}) + "\n").encode()
    moving = b'{"t":3,"present":[1,1,1,1,1,1],"sent":[1,1,1,1,1,1],"pwm":{},"owner_session_id":"session-1","library_sha256":"lib-1"}\n'
    source.write_bytes(baseline + foreign + moving)
    evidence = AttemptJointEvidence(tmp_path / "work", "task-1", "run-1", "lease-1", "lib-1",
                                    session_id="session-1", owner_io=io).start()
    assert evidence.record("load lib", _status(_receipt(source.name, "load lib", 2, 0, len(baseline), baseline)))
    pre = _receipt(source.name, "state", 3, len(baseline), len(baseline) + len(foreign), foreign)
    result = _status(_receipt(source.name, "run lift_pick", 4, len(baseline) + len(foreign),
                              len(baseline) + len(foreign) + len(moving), moving))
    result["pre_state_trace"] = {"t": pre["reported_at"], "trace_receipt": pre}
    with pytest.raises(ValueError, match="owner trace joint sample invalid"):
        evidence.record("run lift_pick", result)
    assert evidence.stop()["continuous_trace"] == "UNKNOWN"


def test_existing_owner_trace_artifact_refuses_attempt(tmp_path):
    evidence = AttemptJointEvidence(tmp_path / "work", "task-1", "run-1", "lease-1", "lib-1")
    evidence.owner_trace_path.parent.mkdir(parents=True)
    evidence.owner_trace_path.write_bytes(b"unbound")
    with pytest.raises(FileExistsError, match="already exists"):
        evidence.start()
