"""cell_zones: two arms over one pallet - own side or the shared middle, never the other side, one arm in the middle."""
import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
import cell_transfer  # noqa: E402
import cell_zones  # noqa: E402

# a map (pixel -> arm metres, as cell_calibrate fits it) of 1 px per mm: x 0.30 m shows at column 300
CAL = {"sites": {"pallet": {"homography": [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 1.0]]}}}
PARAMS = {"zone.split_px": 367.0, "zone.middle_px": 30.0, "zone.wait_s": 1.0}


def zones(tmp_path, side, clock=None, peer=None):
    t = clock or [0.0]
    return cell_zones.Zones({"zone_side": side, "zone_peer": peer, "params": PARAMS}, CAL, lock_dir=tmp_path,
                            incidents=tmp_path / "incidents", clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))


def test_each_arm_enters_its_side_and_never_the_other(tmp_path):
    b, a = zones(tmp_path, "left"), zones(tmp_path, "right")
    assert b.zone_of((0.30, 0.2)) == "left" and b.zone_of((0.37, 0.2)) == "middle" and b.zone_of((0.42, 0.2)) == "right"
    assert b.enter((0.30, 0.2)) == (True, "left")
    ok, why = a.enter((0.30, 0.2))
    assert not ok and "other arm" in why
    b.leave()


def test_the_middle_holds_one_arm_until_it_folds_home(tmp_path):
    b, a = zones(tmp_path, "left"), zones(tmp_path, "right")
    assert b.enter((0.37, 0.2)) == (True, "middle")
    ok, why = a.enter((0.36, 0.2))
    assert not ok and "holds the middle" in why  # waited zone.wait_s, then refused
    b.leave()
    assert a.enter((0.36, 0.2)) == (True, "middle")
    a.leave()


def test_an_arm_without_a_map_has_no_zone_and_is_refused():
    z = cell_zones.Zones({"zone_side": "right", "params": PARAMS}, {"sites": {}})
    ok, why = z.enter((0.1, 0.1))
    assert not ok and "no pallet map" in why


def test_the_rule_is_a_parameter_not_code():
    z = cell_zones.Zones({"zone_side": "left", "params": dict(PARAMS, **{"zone.middle_px": 200.0})}, CAL)
    assert z.zone_of((0.30, 0.2)) == "middle"  # a wider middle in the params file, no code change


class Cell:
    def __init__(self):
        self.commands = []
        self.park = {"ok": True, "settled": True, "state": [0] * 6}

    def act(self, command):
        self.commands.append(command)
        if command.endswith(" park"):
            return self.park
        return {"ok": True, "state": [0] * 6}


def test_the_gate_holds_a_reach_into_the_other_side_before_it_moves_and_frees_the_middle_on_park(tmp_path, monkeypatch):
    monkeypatch.setattr(cell_transfer, "same_session", lambda *a, **k: True)
    monkeypatch.setattr(cell_transfer, "digest", lambda value: "same")
    cell = Cell()
    gate = cell_transfer.Gate(cell, {"zone_side": "left", "params": PARAMS}, CAL)
    gate.zones = zones(tmp_path, "left")
    gate.assessment, gate.scope_sha = {"mode": "automatic", "session_id": "s", "library_sha256": "same"}, "same"
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps({"chunks": {"home": [[0] * 6]},
                               "source": {"pick": {"x": 0.42, "y": 0.2}, "place": {"x": 0.37, "y": 0.2}}}))
    gate.act(f"load {lib}")
    refused = gate.act("goto above_pick")
    assert refused["ok"] is False and "zone" in refused["error"] and not cell.commands[-1].endswith("goto above_pick")
    assert gate.act("goto above_place")["ok"] and gate.zones.held
    other = zones(tmp_path, "right")
    assert other.enter((0.37, 0.2))[0] is False
    gate.act("park")
    assert not gate.zones.held and other.enter((0.37, 0.2)) == (True, "middle")


@pytest.mark.parametrize("hold", [{}, {"facts": {"folded": False}}, {"facts": {"folded": True}, "t": 0}])
def test_a_hold_and_free_session_lock_do_not_prove_peer_clearance(tmp_path, hold):
    """HOLD may follow an unsafe extended end; even an old folded report is not fresh clearance."""
    import fcntl
    import os

    a, b = zones(tmp_path, "right", peer="arm_b"), zones(tmp_path, "left", peer="arm_a")
    left = (0.30, 0.2)
    assert a.enter(left) == (False, "left side belongs to the other arm")  # arm_b in service
    (tmp_path / "incidents").mkdir()
    (tmp_path / "incidents/HOLD-arm_b.json").write_text(json.dumps(hold))
    session = os.open(tmp_path / "session-arm_b.lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(session, fcntl.LOCK_EX)  # arm_b's record_session still runs
    assert a.enter(left)[0] is False
    fcntl.flock(session, fcntl.LOCK_UN)
    os.close(session)
    assert a.enter(left)[0] is False
    assert not a.held
    assert b.enter(left) == (True, "left")
    b.leave()


def held_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(cell_transfer, "same_session", lambda *a, **k: True)
    monkeypatch.setattr(cell_transfer, "digest", lambda value: "same")
    cell = Cell()
    gate = cell_transfer.Gate(cell, {"zone_side": "left", "params": PARAMS}, CAL)
    gate.zones = zones(tmp_path, "left")
    gate.assessment, gate.scope_sha = {"mode": "automatic", "session_id": "s", "library_sha256": "same"}, "same"
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps({"chunks": {"home": [[0] * 6]}}))
    assert gate.act(f"load {lib}")["ok"]
    assert gate.zones.enter((0.37, 0.2))[0]
    return gate, cell


@pytest.mark.parametrize("park", [
    {"ok": True, "state": [0] * 6},
    {"ok": True, "settled": False, "state": [0] * 6},
    {"ok": True, "settled": True, "state": [10] * 6},
    *[{"ok": True, "settled": True, "state": [bad] + [0] * 5}
      for bad in (float("nan"), float("inf"), None)],
    {"ok": True, "settled": True},
    {"ok": True, "settled": True, "state": []},
    {"ok": False, "settled": True, "state": [0] * 6},
])
def test_park_without_confirmed_finite_home_keeps_reservations(tmp_path, monkeypatch, park):
    gate, cell = held_gate(tmp_path, monkeypatch)
    cell.park = park
    gate.act("park")
    assert gate.zones.held
    assert not zones(tmp_path, "right").enter((0.37, 0.2))[0]
    cell.park = {"ok": True, "settled": True, "state": [0] * 6}
    gate.act("park")
    assert not gate.zones.held


def test_real_runner_park_timeout_keeps_middle_until_successful_retry(tmp_path, monkeypatch):
    import chunk_runner

    class BlockedRobot:
        def send_action(self, action):
            pass

        def get_observation(self):
            return dict(zip(chunk_runner.NAMES, [10] + [0] * 5))

    reports = []
    runner = chunk_runner.Runner(BlockedRobot(), {"chunks": {"home": [[0] * 6]}},
                                  fps=30, status=reports.append, clock=lambda: 4.0)
    runner.target, runner.chunk, runner.settle_since = [0] * 6, "park", 0.0
    runner.tick()
    assert reports[-1]["ok"] and reports[-1]["settled"] is False and runner.home_since is None
    gate, cell = held_gate(tmp_path, monkeypatch)
    cell.park = reports[-1]
    gate.act("park")
    assert gate.zones.held
    runner.robot.get_observation = lambda: dict(zip(chunk_runner.NAMES, [0] * 6))
    runner.chunk, runner.settle_since = "park", None
    runner.tick()
    assert reports[-1]["settled"] is True and runner.home_since == 4.0
    cell.park = reports[-1]
    gate.act("park")
    assert not gate.zones.held


@pytest.mark.parametrize("side,xy", [("left", (0.30, 0.2)), ("right", (0.37, 0.2))])
def test_process_exit_does_not_prove_zone_clearance(tmp_path, side, xy):
    import os

    first = zones(tmp_path, "left")
    assert first.enter(xy)[0]
    # Process exit closes descriptors and releases flock without physically folding the arm.
    for fd in first.held.values():
        os.close(fd)
    first.held = {}
    restarted = zones(tmp_path, side)
    assert not restarted.enter(xy)[0]
    assert not restarted.held


def test_takeover_is_a_parameter(tmp_path):
    (tmp_path / "incidents").mkdir()
    (tmp_path / "incidents/HOLD-arm_b.json").write_text("{}")
    z = cell_zones.Zones({"zone_side": "right", "zone_peer": "arm_b", "params": dict(PARAMS, **{"zone.takeover": 0})}, CAL,
                         lock_dir=tmp_path, incidents=tmp_path / "incidents")
    assert z.enter((0.30, 0.2))[0] is False
