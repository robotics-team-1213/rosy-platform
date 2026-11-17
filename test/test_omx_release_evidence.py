"""Release evidence is recorded beside photo verification and never changes a carry."""
import hashlib
import json

from test_omx_act_shadow import run_carry
from test_omx_cell_auto_pick import Cell, auto, simulated_operating_profile  # noqa: F401  (autouse fixture)

ev = auto.cell_release_evidence


def row(grip_pwm, wrist_pwm, present):
    return {"pwm": {"gripper": grip_pwm, "wrist_flex": wrist_pwm}, "present": present}


STILL = [0, 0, 0, 10.0, 0, 55.0]


def test_drop_after_open_and_settled():
    release = [row(300, 40, STILL)] * 5 + [row(20, 30, STILL)] * 5
    lift = [row(10, 25, STILL)] * 12
    got = ev.release_evidence(release, lift)
    assert (got["gripper_pwm_before"], got["gripper_pwm_after"], got["wrist_pwm_peak_after"], got["settled"]) == (300.0, 20.0, 30.0, True)


def test_no_drop_and_still_moving_is_visible():
    release = [row(300, 40, STILL)] * 10
    lift = [row(310, 90, [0, 0, 0, 10.0 + i, 0, 55.0]) for i in range(12)]
    got = ev.release_evidence(release, lift)
    assert got["gripper_pwm_after"] == 300.0 and got["wrist_pwm_peak_after"] == 90.0 and got["settled"] is False


def test_missing_or_bad_trace_is_unavailable_not_an_error():
    assert ev.release_evidence([]) == {"basis": "unavailable"}
    assert ev.release_evidence([{"pwm": None}] * 12, [None]) == {"basis": "unavailable"}
    assert ev.from_steps([{"command": "run release_place"}], "/nowhere/io") == {"basis": "unavailable"}
    assert ev.from_steps(None, None) == {"basis": "unavailable"}


def test_from_steps_slices_receipts_and_rejects_hash_mismatch(tmp_path):
    rel = b"".join(json.dumps(row(300 if i < 5 else 20, 10, STILL)).encode() + b"\n" for i in range(10))
    (tmp_path / "trace.jsonl").write_bytes(b"x\n" + rel)
    receipt = {"status": "ok", "source": "trace.jsonl", "start": 2, "end": 2 + len(rel), "sha256": hashlib.sha256(rel).hexdigest()}
    steps = [{"command": "run release_place", "trace_receipt": receipt}]
    io = tmp_path / "io"
    assert ev.from_steps(steps, io)["gripper_pwm_after"] == 20.0
    assert ev.from_steps([{**steps[0], "trace_receipt": {**receipt, "sha256": "0" * 64}}], io) == {"basis": "unavailable"}


def commands_and_result(tmp_path, monkeypatch, evidence):
    seen = []
    cells = []
    orig = Cell.__init__
    monkeypatch.setattr(Cell, "__init__", lambda self, *a, **k: (orig(self, *a, **k), cells.append(self))[0])
    monkeypatch.setattr(auto.cell_release_evidence, "from_steps", lambda steps, io: seen.append(1) or evidence)
    result = run_carry(tmp_path, monkeypatch)
    # the library path names the run's own work dir; the command sequence is what must not change
    return result, [c.replace(str(tmp_path), "<work>") for c in cells[0].commands], seen


def test_recording_does_not_change_carry_result_or_order(tmp_path, monkeypatch):
    base = tmp_path / "a"
    other = tmp_path / "b"
    base.mkdir(), other.mkdir()
    calm = {"gripper_pwm_before": 300.0, "gripper_pwm_after": 10.0, "wrist_pwm_peak_after": 5.0, "settled": True, "basis": "t"}
    loaded = {"gripper_pwm_before": 300.0, "gripper_pwm_after": 300.0, "wrist_pwm_peak_after": 999.0, "settled": False, "basis": "t"}
    r1, c1, s1 = commands_and_result(base, monkeypatch, calm)
    r2, c2, s2 = commands_and_result(other, monkeypatch, loaded)
    assert s1 and s2 and r1["result"] == r2["result"] == "placed" and c1 == c2
