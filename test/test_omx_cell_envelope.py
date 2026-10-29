"""Operating evidence binds a whole native task to its actual arm and declared conditions."""
import copy
import importlib
import json
from pathlib import Path
import sys
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"


@pytest.fixture
def envelope():
    sys.path.insert(0, str(OMX))
    try:
        yield importlib.import_module("cell_envelope")
    finally:
        sys.path.remove(str(OMX))


@pytest.fixture
def task(tmp_path, envelope):
    from cell_robot_profile import load

    profile_path = tmp_path / "robot-profile.json"
    profile_path.write_text(json.dumps({"schema": "rosy.omx-cell-robot-profile.v1",
        "device_id": "fixture-device", "instance_id": "fixture-arm", "robot_config_sha256": "c" * 64,
        "operating_envelope_path": "review.json", "work_dir": "."}))
    config = {"plan": {"lift_m": 0.04}, "profiles": {}, "sites": {}, "cameras": {},
              "operating_conditions": {"installation_revision": "fixture-install-1",
                  "object_revision": "fixture-object-1", "payload_kg": 0.05,
                  "object_dimensions_m": [0.03, 0.03, 0.03], "environment_revision": "fixture-scene-1"},
              "operating_envelope_path": str(tmp_path / "review.json"), "work_dir": str(tmp_path),
              "operating_profile_path": str(profile_path)}
    calibration = {"sites": {"tray": {"revision": "fixture-map-1"}}}
    library = {"fps": 30, "chunks": {"home": [[0, 0, 0, 0, 0, 47]],
                                    "lift_pick": [[0, 1, 2, 3, 4, 49]]}}
    state = {"ok": True, "fault": None, "t": 100.0, "state": [0, 0, 0, 0, 0, 47],
             "operating_context": {"scope": "hardware", "sha256": "a" * 64, "session_id": "fixture-session",
                                   "operating_profile": load(profile_path)["binding"]}}
    return config, calibration, library, state


def approve(tmp_path, envelope, task, outcomes=("placed", "placed")):
    config, calibration, library, state = task
    result = envelope.assess(*task, now=100.01)
    rows = [{"schema": "rosy.omx-cell-attempt.v1", "attempt_id": f"trial-{i}",
             "envelope": {**result, "mode": "commissioning", "status": "commissioning", "allowed": True},
             "outcome": outcome,
             "verify": {"inside": outcome == "placed"}, "transfer": {"result": outcome}}
            for i, outcome in enumerate(outcomes)]
    attempts = tmp_path / "attempts.jsonl"
    attempts.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    review = {"task_sha256": result["task_sha256"], "scope": "hardware",
              "reviewed_by": "fixture-reviewer", "evidence_ref": "fixture-physical-checks",
              "attempts_sha256": envelope.digest(rows), "min_attempts": 2,
              "min_success_rate": 1.0, "home_tolerance_units": 0.5}
    binding = state["operating_context"]["operating_profile"]
    document = {"schema": envelope.SCHEMA, "attempts_path": str(attempts), "reviews": [review],
                **{key: binding[key] for key in ("device_id", "instance_id", "profile_sha256")}}
    Path(config["operating_envelope_path"]).write_text(json.dumps(document), encoding="utf-8")
    return attempts, document


def test_no_evidence_holds_even_when_a_library_exists(task, envelope):
    result = envelope.assess(*task, now=100.01)
    assert result["status"] == "unverified" and not result["allowed"]
    assert len(result["task_sha256"]) == 64


def test_reviewed_identical_full_task_can_proceed(tmp_path, task, envelope):
    approve(tmp_path, envelope, task)
    result = envelope.assess(*task, now=100.01)
    assert result["allowed"] and result["status"] == "verified"
    assert result["attempts"] == result["successes"] == 2


def test_an_unbound_or_different_device_profile_cannot_use_even_commissioning(task, envelope):
    config, calibration, library, state = copy.deepcopy(task)
    config["_commissioning"] = {"person_at_switch": True}
    state["operating_context"]["operating_profile"]["device_id"] = "other-device"
    assert envelope.assess(config, calibration, library, state, now=100.01)["reason"] == "profile_mismatch"
    state["operating_context"]["operating_profile"] = None
    assert not envelope.assess(config, calibration, library, state, now=100.01)["allowed"]


def test_a_review_manifest_from_another_profile_is_rejected(tmp_path, task, envelope):
    _, document = approve(tmp_path, envelope, task)
    document["device_id"] = "other-device"
    Path(task[0]["operating_envelope_path"]).write_text(json.dumps(document))
    assert envelope.assess(*task, now=100.01)["reason"] == "review_profile_mismatch"


@pytest.mark.parametrize("changed", ["arm", "scope", "map", "height", "payload", "installation", "speed"])
def test_changed_conditions_cannot_reuse_a_review(tmp_path, task, envelope, changed):
    approve(tmp_path, envelope, task)
    config, calibration, library, state = copy.deepcopy(task)
    if changed == "arm":
        state["operating_context"]["sha256"] = "b" * 64
    elif changed == "scope":
        state["operating_context"]["scope"] = "simulation"
    elif changed == "map":
        calibration["sites"]["tray"]["revision"] = "other-map"
    elif changed == "height":
        library["chunks"]["lift_pick"][0][1] += 1
    elif changed == "payload":
        config["operating_conditions"]["payload_kg"] += 0.01
    elif changed == "installation":
        config["operating_conditions"]["installation_revision"] = "other-install"
    else:
        library["fps"] = 25
    assert not envelope.assess(config, calibration, library, state, now=100.01)["allowed"]


@pytest.mark.parametrize("change", [{"t": 99.0}, {"t": 101.0}, {"fault": "contact"},
                                     {"ok": False}, {"operating_context": None},
                                     {"state": [9, 0, 0, 0, 0, 47]}])
def test_current_state_still_gates_a_reviewed_task(tmp_path, task, envelope, change):
    approve(tmp_path, envelope, task)
    config, calibration, library, state = task
    assert not envelope.assess(config, calibration, library, {**state, **change}, now=100.01)["allowed"]


def test_failures_stay_in_the_denominator_and_new_failures_revoke(tmp_path, task, envelope):
    approve(tmp_path, envelope, task, ("placed", "empty"))
    assert not envelope.assess(*task, now=100.01)["allowed"]
    attempts, _ = approve(tmp_path, envelope, task)
    row = {"attempt_id": "automatic-failure", "envelope": envelope.assess(*task, now=100.01),
           "outcome": "failed", "transfer": {"result": "contact"}}
    with attempts.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    assert envelope.assess(*task, now=100.01)["reason"] == "runtime_failure"


def test_commissioning_is_explicit_and_never_a_verified_result(task, envelope):
    config, calibration, library, state = task
    assert not envelope.assess({**config, "_commissioning": {"person_at_switch": False}},
                               calibration, library, state, now=100.01)["allowed"]
    result = envelope.assess({**config, "_commissioning": {"person_at_switch": True}},
                             calibration, library, state, now=100.01)
    assert result["allowed"] and result["status"] == result["mode"] == "commissioning"


def test_a_changed_or_partial_ledger_is_not_accepted(tmp_path, task, envelope):
    attempts, _ = approve(tmp_path, envelope, task)
    with attempts.open("a", encoding="utf-8") as stream:
        stream.write('{"partial":')
    assert not envelope.assess(*task, now=100.01)["allowed"]


def test_a_crashed_attempt_or_other_ledger_cannot_be_ignored(tmp_path, task, envelope):
    attempts, document = approve(tmp_path, envelope, task)
    pending = attempts.with_suffix(".pending.json")
    pending.write_text("{}")
    assert envelope.assess(*task, now=100.01)["reason"] == "incomplete_attempt"
    pending.unlink()
    other = tmp_path / "other.jsonl"
    other.write_bytes(attempts.read_bytes())
    document["attempts_path"] = str(other)
    Path(task[0]["operating_envelope_path"]).write_text(json.dumps(document))
    assert not envelope.assess(*task, now=100.01)["allowed"]


@pytest.mark.parametrize("document", [[], 1, None, {"reviews": [1]}])
def test_malformed_review_shapes_hold_instead_of_crashing(task, envelope, document):
    Path(task[0]["operating_envelope_path"]).write_text(json.dumps(document))
    assert envelope.assess(*task, now=100.01)["reason"] == "evidence_unavailable"


def test_malformed_nested_observations_are_not_a_success(tmp_path, task, envelope):
    attempts, document = approve(tmp_path, envelope, task)
    rows = [json.loads(line) for line in attempts.read_text().splitlines()]
    rows[0]["verify"] = [True]
    attempts.write_text("".join(json.dumps(r) + "\n" for r in rows))
    document["reviews"][0]["attempts_sha256"] = envelope.digest(rows)
    Path(task[0]["operating_envelope_path"]).write_text(json.dumps(document))
    assert envelope.assess(*task, now=100.01)["reason"] == "evidence_unavailable"


def test_runtime_fingerprint_uses_real_calibration_and_readback_including_xl330_current(envelope):
    @dataclass
    class Calibration:
        range_min: int = 0
        range_max: int = 4095

    class Bus:
        motors = {name: SimpleNamespace(id=11 + i, model="xl430-w250" if i < 3 else "xl330-m288")
                  for i, name in enumerate(envelope.NAMES)}
        calibration = {name: Calibration() for name in envelope.NAMES}
        changed = False
        reads = []

        def read(self, register, name):
            self.reads.append((register, name))
            return 300 if self.changed and register == "Current_Limit" else 20

    bus = Bus()
    config = {"id": "fixture-arm", "port": "/dev/serial/by-id/fixture"}
    first = envelope.runtime_context(config, bus, 30)
    assert first["scope"] == "hardware"
    assert envelope.runtime_context(config, bus, 30)["sha256"] == first["sha256"]
    assert ("Current_Limit", "gripper") in bus.reads
    assert ("Current_Limit", "shoulder_pan") not in bus.reads
    bus.changed = True
    assert envelope.runtime_context(config, bus, 30)["sha256"] != first["sha256"]
    bus.changed = False
    bus.calibration["shoulder_pan"].range_min = 1
    assert envelope.runtime_context(config, bus, 30)["sha256"] != first["sha256"]


@pytest.fixture
def runner_context(envelope):
    @dataclass
    class Calibration:
        range_min: int = 0

    bus = SimpleNamespace(
        motors={name: SimpleNamespace(id=i, model="xl430-w250") for i, name in enumerate(envelope.NAMES)},
        calibration={name: Calibration() for name in envelope.NAMES}, read=lambda *args: 20)
    return lambda **kwargs: envelope.runtime_context({"id": "fixture-arm"}, bus, 30, **kwargs)


@pytest.mark.parametrize("name,value", [("runner.pace_lag", 1.7), ("runner.contact_ticks", 3),
                                       ("runner.contact_loaded_max", 2.1)])
def test_changed_runner_params_cannot_reuse_a_review(tmp_path, task, envelope, runner_context, name, value):
    import cell_params

    params = cell_params.load()["values"]
    task[3]["operating_context"]["sha256"] = runner_context(params=params)["sha256"]
    approve(tmp_path, envelope, task)
    assert envelope.assess(*task, now=100.01)["allowed"]
    task[3]["operating_context"]["sha256"] = runner_context(params={**params, name: value})["sha256"]
    assert not envelope.assess(*task, now=100.01)["allowed"]


def test_explicit_default_params_keep_runtime_identity(tmp_path, envelope, runner_context):
    import cell_params

    path = tmp_path / "params.json"
    path.write_text(json.dumps({"schema": cell_params.SCHEMA, "params": {}}))
    assert runner_context(params=cell_params.load(path)["values"])["sha256"] == runner_context()["sha256"]


@pytest.mark.parametrize("value", [None, True, float("nan"), 0, -1])
def test_invalid_payload_never_reaches_approval(task, envelope, value):
    config, calibration, library, state = copy.deepcopy(task)
    config["operating_conditions"]["payload_kg"] = value
    assert not envelope.assess(config, calibration, library, state, now=100.01)["allowed"]


def test_fifo_checked_command_accepts_the_runners_inner_command_ack(tmp_path, envelope, monkeypatch):
    pytest.importorskip("numpy")
    transport = importlib.import_module("cell_pipeline_io")
    assert Path(transport.__file__).resolve() == (OMX / "cell_pipeline_io.py").resolve()
    status = tmp_path / "chunk-status.jsonl"
    status.write_text("")
    sent = []

    def write(fd, payload):
        sent.append(payload.decode().strip())
        with status.open("a") as stream:
            stream.write(json.dumps({"command": "load plan.json", "ok": True}) + "\n")
        return len(payload)

    monkeypatch.setattr(transport.os, "open", lambda *a, **kw: 42)
    monkeypatch.setattr(transport.os, "write", write)
    monkeypatch.setattr(transport.os, "close", lambda fd: None)
    result = transport.FifoCell(tmp_path, {}).checked("load plan.json", {
        "session_id": "fixture-session", "library_sha256": "a" * 64})
    assert result["ok"]
    assert sent == [f"checked fixture-session {'a' * 64} load plan.json"]


@pytest.mark.parametrize("wrong_device", [False, True])
def test_supervised_fifo_motion_cannot_bypass_the_selected_device(tmp_path, task, envelope, monkeypatch, wrong_device):
    import time

    transport = importlib.import_module("cell_pipeline_io")
    state = copy.deepcopy(task[3])
    selected = copy.deepcopy(state["operating_context"]["operating_profile"])
    state.update(t=time.time(), command="state", library_sha256="a" * 64)
    if wrong_device:
        state["operating_context"]["operating_profile"]["device_id"] = "other-device"
    status = tmp_path / "chunk-status.jsonl"
    status.write_text("")
    sent = []
    def write(fd, payload):
        line = payload.decode().strip()
        sent.append(line)
        row = state if line == "state" else {"command": "jog shoulder_pan.pos 1", "ok": True}
        with status.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        return len(payload)
    monkeypatch.setattr(transport.os, "open", lambda *a, **kw: 42)
    monkeypatch.setattr(transport.os, "write", write)
    monkeypatch.setattr(transport.os, "close", lambda fd: None)
    cell = transport.FifoCell(tmp_path, {}, operating_profile=selected)
    result = cell.act("jog shoulder_pan.pos 1")
    if wrong_device:
        assert not result["ok"] and result["fault"] == "profile_mismatch" and sent == ["state"]
    else:
        assert result["ok"] and sent == ["state", f"checked fixture-session {'a' * 64} jog shoulder_pan.pos 1"]


def test_shipped_envelope_and_condition_templates_cannot_enable_automatic_motion(task, envelope):
    document = json.loads((OMX / "cell-envelope.example.json").read_text())
    assert document["schema"] == envelope.SCHEMA and document["reviews"] == []
    template = json.loads((OMX / "cell-pipeline.example.json").read_text())
    config, calibration, library, state = task
    config["operating_conditions"] = template["operating_conditions"]
    assert not envelope.assess(config, calibration, library, state, now=100.01)["allowed"]
