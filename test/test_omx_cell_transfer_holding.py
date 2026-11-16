"""cell_transfer judges a grasp against where this arm's empty jaws stop (the library's jaw_empty_stop), not the close command."""
import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("numpy")
sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
from cell_transfer import RETURN_HELD, transfer_folded  # noqa: E402
from cell_envelope import SEQUENCE  # noqa: E402


class Cell:
    """Every command succeeds; the jaws read `jaws` from the grasp on, with no runner holding flag."""

    def __init__(self, jaws):
        self.jaws, self.sent = jaws, []

    def act(self, command):
        self.sent.append(command)
        grasped = any(c == "run grasp_pick" for c in self.sent)
        return {"ok": True, "state": [0, 0, 0, 0, 0, self.jaws if grasped else 57.5]}


@pytest.mark.parametrize("stop, carried", [(49.0, False), (45.5, True)])
def test_empty_jaws_end_the_carry_at_the_grasp(tmp_path, stop, carried):
    """2026-11-13 arm_s: jaws at 50.0 after the grasp were empty (this arm's empty stop is 48.8), and the carry went on to
    place nothing and reported 'placed'. Against its own stop the same reading is empty; a lower stop makes it a box."""
    library = tmp_path / "lib.json"
    library.write_text(json.dumps({"gripper_closed": stop, "jaw_empty_stop": stop, "chunks": {}}))
    cell = Cell(jaws=50.0)
    out = transfer_folded(cell, library, sequence=SEQUENCE)
    assert ("goto above_place" in cell.sent) is carried
    assert out["result"] != "empty" if carried else out == {**out, "result": "empty", "at": "run grasp_pick"}


class Strained(Cell):
    """The park after `after` holds with a contact; `error` is the runner's text."""

    def __init__(self, after, error):
        super().__init__(jaws=50.0)  # above this library's empty stop: a box is held
        self.after, self.error = after, error

    def act(self, command):
        out = super().act(command)
        if command == "park" and self.after in self.sent:
            return {**out, "ok": False, "contact": True, "error": self.error}
        return out


def test_a_park_overload_after_a_wrist_refusal_keeps_its_contact_in_the_steps(tmp_path):
    """2026-11-14 arm_s: the wrist refused at above_pick, the park from there overloaded shoulder_lift and the arm sagged onto
    the box; the result said only "misaligned" and nothing stopped the next attempt."""
    library = tmp_path / "lib.json"
    library.write_text(json.dumps({"chunks": {}}))
    cell = Strained("goto above_pick", "contact in park: shoulder_lift lag rose to 2.3 units at PWM -538 of 600")
    out = transfer_folded(cell, library, wrist=lambda: {"verdict": "refuse"})
    park = [s for s in out["steps"] if s["command"] == "park"][-1]  # run_auto stops on it (test_a_park_that_ended_in_contact)
    assert out["result"] == "misaligned" and park["contact"] and "shoulder_lift" in park["error"]


def test_a_park_that_shed_its_load_is_not_backed_up(tmp_path):
    library = tmp_path / "lib.json"
    library.write_text(json.dumps({"gripper_closed": 45.5, "jaw_empty_stop": 45.5, "chunks": {}}))
    cell = Strained("run lift_pick", "contact (overload-hold on shoulder_lift by the guard): lift and elbow shed its load")
    out = transfer_folded(cell, library)
    assert "retreat" not in cell.sent and out["result"] == "contact" and out["at"] == "park"


@pytest.mark.parametrize("jaws, expected", [(53.6, "placed"), (48.9, "empty")])
def test_return_held_places_when_jaws_hold_box_and_folds_when_empty(tmp_path, jaws, expected):
    class HeldCell:
        def __init__(self, hold_jaws):
            self.jaws, self.sent = hold_jaws, []

        def act(self, command):
            self.sent.append(command)
            after_rel = "run release_place" in self.sent
            return {"ok": True, "state": [0, 0, 0, 0, 0, 48.8 if after_rel else self.jaws]}

    library = tmp_path / "lib.json"
    library.write_text(json.dumps({"gripper_closed": 48.8, "jaw_empty_stop": 48.8, "chunks": {}}))
    cell = HeldCell(jaws)
    out = transfer_folded(cell, library, sequence=RETURN_HELD)
    assert out["result"] == expected
    if expected == "placed":
        assert cell.sent == [f"load {library}", *RETURN_HELD]
    else:
        assert "run release_place" not in cell.sent and cell.sent[-1] == "park"


def test_return_held_recovers_stale_middle_lock_by_parking_before_above_place():
    class StaleZoneGate:
        def __init__(self):
            self.commands = []
            self.needs_park = True
            self.released = False

        def act(self, command):
            self.commands.append(command)
            if command == "goto above_place" and self.needs_park:
                return {
                    "command": command, "ok": False,
                    "error": "held: zone: the other arm holds the middle; its guarded owner must park before recovery",
                }
            if command == "park":
                self.needs_park = False
            if command == "run release_place":
                self.released = True
            jaws = 48.8 if self.released else 53.0
            return {"command": command, "ok": True, "settled": True, "state": [0.0, 0.0, 0.0, 0.0, 0.0, jaws]}

    gate = StaleZoneGate()
    out = transfer_folded(gate, "lib.json", closed=48.8, sequence=RETURN_HELD)
    assert out["result"] == "placed", out
    assert gate.commands[:4] == ["load lib.json", "goto above_place", "park", "goto above_place"]


def test_commissioning_replan_refreshes_state_after_slow_park(tmp_path, monkeypatch):
    import types
    import cell_envelope
    import cell_transfer

    clock = [1000.0]
    monkeypatch.setattr(cell_envelope, "time", types.SimpleNamespace(time=lambda: clock[0]))
    profile_path = tmp_path / "robot-profile.json"
    profile_path.write_text(json.dumps({
        "schema": "rosy.omx-cell-robot-profile.v1",
        "device_id": "fixture-device",
        "instance_id": "fixture-arm",
        "robot_config_sha256": "c" * 64,
        "operating_envelope_path": "review.json",
        "work_dir": ".",
    }))
    from cell_robot_profile import load

    binding = load(profile_path)["binding"]
    config = {
        "plan": {"lift_m": 0.04}, "profiles": {}, "sites": {}, "cameras": {},
        "operating_conditions": {
            "installation_revision": "fixture-install", "object_revision": "fixture-obj",
            "payload_max_kg": 0.05, "object_dimensions_m": [0.03, 0.03, 0.03], "environment_revision": "fixture-env",
        },
        "payload": {"kg": 0.03, "source": "fixture scale"},
        "operating_envelope_path": str(tmp_path / "review.json"),
        "work_dir": str(tmp_path),
        "operating_profile_path": str(profile_path),
        "_commissioning": {"person_at_switch": True},
    }
    home = [0.0, 0.0, 0.0, 0.0, 0.0, 48.8]
    original, revised = tmp_path / "original.json", tmp_path / "revised.json"
    spec = {"fps": 30, "chunks": {"home": [home], "above_pick": [home]}}
    original.write_text(json.dumps(spec))
    revised.write_text(json.dumps({**spec, "replan": "adjusted pick"}))

    class SlowParkCell:
        def __init__(self):
            self.commands = []

        def act(self, command):
            raw = command.split(" ", 3)[-1] if command.startswith("checked ") else command
            if raw == "park":
                clock[0] += 3.0  # parking from above_pick exceeds MAX_GAP_S (0.5 s)
            self.commands.append(raw)
            return {
                "command": raw, "ok": True, "settled": True, "state": home, "t": clock[0],
                "operating_context": {"scope": "hardware", "sha256": "a" * 64, "session_id": "s1",
                                      "operating_profile": binding},
            }

    cell = SlowParkCell()
    gate = cell_transfer.Gate(cell, config, {})
    assert gate.open(original, lambda a: None, lambda *a: None) is None
    assert gate.act(f"load {original}")["ok"] is True
    status = gate.act(f"load {revised}")
    assert status["ok"] is True and f"load {revised}" in cell.commands

