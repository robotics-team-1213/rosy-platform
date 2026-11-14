"""cell_two_arm: the schedule on fake sessions: progress gates each segment, one arm's failure stops the other, the fold is
checked from where the arms stand, and nothing moves without a person."""
import json
from pathlib import Path
import sys
import time

import pytest

pytest.importorskip("numpy")
pytest.importorskip("yaml")
cv2 = pytest.importorskip("cv2")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
sys.path.insert(0, str(Path(__file__).parents[1] / "middleware/devices/omx/adapter"))
sys.path.insert(0, str(Path(__file__).parents[1] / "contracts/foundation"))
try:
    import cell_two_arm as two
finally:
    for extra in (str(OMX),):
        sys.path.remove(extra)
import numpy as np  # noqa: E402

R = 0.01


def stick(x):
    return [((x, 0.0, 0.0), (x, 0.0, 0.1), R)]


class Cell:
    """A session whose commands take `seconds`; `events` keeps start and end order across both arms."""

    def __init__(self, name, events, seconds=0.02, fail=None):
        self.name, self.events, self.seconds, self.fail, self.commands = name, events, seconds, fail, []

    def act(self, command):
        self.commands.append(command)
        if command == "state":
            return {"ok": True, "state": [0.0] * 6}
        self.events.append((self.name, "start", command))
        time.sleep(self.seconds)
        self.events.append((self.name, "end", command))
        if command == self.fail:
            return {"ok": False, "error": "contact"}
        return {"ok": True}


def cells_of(events, **kw):
    return {"a": Cell("a", events, **kw.get("a", {})), "b": Cell("b", events, **kw.get("b", {}))}


COMMANDS = {"a": [["goto a0"], ["goto a1"], ["park a"]], "b": [["goto b0"], ["goto b1"], ["park b"]]}
# b out, then a out, then both shuttle together, then a folds, then b: the order the free-air trial needs
STEPS = [{"a": None, "b": 0}, {"a": 0, "b": None}, {"a": 1, "b": 1}, {"a": 2, "b": None}, {"a": None, "b": 2}]


def order(events, name, what):
    return next(i for i, e in enumerate(events) if e[0] == name and e[1] == what[0] and e[2] == what[1])


def test_each_segment_waits_for_what_the_schedule_put_before_it():
    events = []
    result = two.execute(cells_of(events), COMMANDS, STEPS, log=lambda row: None)
    assert result == {"done": {"a": 3, "b": 3}, "failed": None, "last": {"a": "park a", "b": "park b"},
                      "stopped": {}, "plan_gen": 0}
    assert order(events, "b", ("end", "goto b0")) < order(events, "a", ("start", "goto a0"))
    assert order(events, "a", ("end", "goto a0")) < order(events, "b", ("start", "goto b1"))
    assert order(events, "a", ("end", "park a")) < order(events, "b", ("start", "park b"))


def test_the_shuttle_segments_really_overlap():
    events = []
    two.execute(cells_of(events), COMMANDS, STEPS, log=lambda row: None)
    assert order(events, "a", ("start", "goto a1")) < order(events, "b", ("end", "goto b1"))
    assert order(events, "b", ("start", "goto b1")) < order(events, "a", ("end", "goto a1"))


def test_a_failure_lets_the_other_finish_its_segment_and_start_no_other():
    events = []
    cells = cells_of(events, a={"fail": "goto a1", "seconds": 0.02}, b={"seconds": 0.08})
    result = two.execute(cells, COMMANDS, STEPS, log=lambda row: None)
    assert result["failed"]["arm"] == "a" and result["failed"]["segment"] == 1 and result["failed"]["error"] == "contact"
    assert ("b", "end", "goto b1") in events and "park b" not in cells["b"].commands and "park a" not in cells["a"].commands


def test_a_failure_in_an_earlier_segment_keeps_the_peer_from_starting():
    events = []
    cells = cells_of(events, b={"fail": "goto b0"})
    result = two.execute(cells, COMMANDS, STEPS, log=lambda row: None)
    assert result["failed"]["arm"] == "b" and cells["a"].commands == []


def test_the_injected_failure_stops_both_like_a_real_one():
    events = []
    cells = cells_of(events)
    result = two.execute(cells, COMMANDS, STEPS, ("b", 1), log=lambda row: None)
    assert result["failed"]["error"] == "injected" and "park a" not in cells["a"].commands and "park b" not in cells["b"].commands


def test_a_waiting_arm_keeps_its_session_from_folding_by_itself(monkeypatch):
    monkeypatch.setattr(two, "KEEP_ALIVE_S", 0.01)
    events = []
    cells = cells_of(events, b={"seconds": 0.1})
    two.execute(cells, COMMANDS, STEPS, log=lambda row: None)
    assert "state" in cells["a"].commands


def test_the_fold_order_comes_from_where_they_stand():
    here = {"a": [stick(0.2)], "b": [stick(0.0)]}
    # a's sweep home passes close to b where b stands; b's sweep home is clear of a
    fold = {"a": [stick(0.2), stick(0.05), stick(0.5)], "b": [stick(0.0), stick(-0.3)]}
    assert two.fold_order(here, fold, 0.05) == ["b", "a"]


def test_no_order_means_nothing_moves():
    here = {"a": [stick(0.03)], "b": [stick(0.0)]}
    fold = {"a": [stick(0.03), stick(0.5)], "b": [stick(0.0), stick(-0.5)]}
    assert two.fold_order(here, fold, 0.05) is None


def test_an_arm_already_home_is_not_folded_and_only_the_other_is_checked():
    here = {"a": [stick(0.5)], "b": [stick(0.0)]}
    assert two.fold_order(here, {"a": None, "b": None}, 0.05) == []
    assert two.fold_order(here, {"a": None, "b": [stick(0.0), stick(-0.2)]}, 0.05) == ["b"]
    assert two.fold_order(here, {"a": None, "b": [stick(0.0), stick(0.48)]}, 0.05) is None


def test_a_fold_with_no_safe_order_sends_nothing(monkeypatch):
    monkeypatch.setattr(two, "poses_of", lambda frames, kin, rigid, tip, item=None: [stick(0.0)])
    monkeypatch.setattr(two, "command_frames", lambda library, command, at: [at])
    events = []
    cells = cells_of(events)
    for cell in cells.values():
        cell.act = (lambda c: lambda command: (c.commands.append(command), {"ok": True, "state": [50.0] * 6})[1])(cell)
    library = {"chunks": {"home": [[0.0] * 6]}}
    result = two.safe_fold(cells, {"a": library, "b": library}, None, {"a": 0, "b": 0}, {"a": 0.0, "b": 0.0}, 0.05, lambda row: None)
    assert result["folded"] is False and "no fold order" in result["person_needed"]
    assert all("park" not in c.commands for c in cells.values())


def test_a_box_that_moved_shows_and_noise_does_not():
    before = np.full((480, 640, 3), 120, np.uint8)
    noisy = before.copy()
    noisy[::40, ::40] = 200
    assert two.scene_moved(before, noisy) == []
    pushed = before.copy()
    cv2.rectangle(pushed, (100, 100), (160, 200), (20, 90, 220), -1)
    area, x0, y0, x1, y1 = two.scene_moved(before, pushed)[0]
    assert area > 3000 and x0 <= 102 and x1 >= 158 and y0 <= 102 and y1 >= 198


def test_it_refuses_to_move_without_a_person():
    with pytest.raises(SystemExit, match="D-911"):
        two.main(["--a", "c", "l", "--b", "c", "l", "--out", "x"])


def test_an_exception_in_one_arm_stops_the_peer_instead_of_leaving_it_waiting():
    events = []
    cells = cells_of(events)

    def boom(command):
        raise ValueError("half a status line")

    cells["b"].act = boom
    result = two.execute(cells, COMMANDS, STEPS, log=lambda row: None)  # b goes first, so a is waiting when b dies
    assert result["failed"]["error"].startswith("ValueError") and cells["a"].commands == []


def test_an_arm_with_no_pinned_profile_does_not_move_and_the_others_commands_are_checked(monkeypatch):
    import cell_robot_profile

    monkeypatch.setattr(cell_robot_profile, "bind_pipeline", lambda c: {**c, "_operating_profile_binding": {"instance_id": c["io"]}})
    configs = {n: {"io": n, "cameras": {}, "operating_profile_path": "p"} for n in "ab"}
    made = two.open_cells(configs, lambda io, cameras, timeout_s, operating_profile: operating_profile)
    assert made == {"a": {"instance_id": "a"}, "b": {"instance_id": "b"}}
    del configs["b"]["operating_profile_path"]
    with pytest.raises(SystemExit, match="arm b.*D-911"):
        two.open_cells(configs, lambda *a, **k: None)


def test_a_schedule_starts_only_from_home():
    class At:
        def __init__(self, state):
            self.state = state

        def act(self, command):
            return {"state": self.state}

    home = [0.0, -60.0, 50.0, 50.0, 45.0, 20.0]
    libraries = {n: {"chunks": {"home": [[9.0] * 6, home]}} for n in "ab"}
    near = [v + 1.5 for v in home[:5]] + [80.0]  # the jaws do not count
    assert two.away_from_home({"a": At(home), "b": At(near)}, libraries) == []
    assert two.away_from_home({"a": At(None), "b": At([v + 3.0 for v in home])}, libraries) == ["a", "b"]


CHUNKS = {"home": [[0.0] * 6], "descend_pick": [[1.0] * 6, [2.0] * 6], "lift_pick": [[2.0] * 6, [3.0] * 6],
          "descend_place": [[4.0] * 6], "release_place": [[5.0] * 6], "lift_place": [[6.0] * 6], "grasp_pick": [[2.5] * 6]}
LIBRARY = {"chunks": CHUNKS, "gripper_closed": 20.0}


@pytest.mark.parametrize("last,stopped,sends", [
    ("goto above_pick", None, []),
    ("run descend_pick", None, ["run lift_pick"]),
    ("run grasp_pick", None, ["run lift_pick"]),
    ("run release_place", None, ["run lift_place"]),
    ("goto above_pick", {"command": "run descend_pick", "contact": True}, ["retreat"]),
    ("run lift_pick", {"command": "run lift_place", "contact": True}, []),
    ("run lift_pick", {"command": "park", "contact": True}, []),
    ("run descend_pick", {"command": "goto above_place", "contact": True}, []),
    ("run grasp_pick", {"command": "run lift_pick", "contact": True}, None),  # the retreat pressed the box down
])
def test_an_arm_climbs_out_the_way_it_went_in_before_it_folds(last, stopped, sends):
    out = two.way_out(LIBRARY, last, stopped)
    assert (None if out is None else [c for c, _ in out]) == sends


def test_a_carry_is_one_segment_per_command_and_its_first_loads_the_library(monkeypatch):
    monkeypatch.setattr(two, "segments_of", lambda library, kin, rigid, tip_m: ["one"] * len(two.FOLDED))
    segments, commands = two.carry_route("lib.json", LIBRARY, None, None, 0.0)
    assert len(segments) == len(commands) == 10 and commands[0] == ["load lib.json", "goto above_pick"]
    assert commands[2] == ["run grasp_pick"] and commands[-1] == ["park"]


def test_an_empty_grasp_stops_both_arms():
    events = []
    cells = cells_of(events)
    commands = {"a": [["run grasp_pick"], ["run lift_pick"]], "b": [["goto b0"], ["goto b1"]]}
    steps = [{"a": 0, "b": 0}, {"a": 1, "b": 1}]
    result = two.execute(cells, commands, steps, log=lambda row: None)
    assert result["failed"]["error"] == "empty grasp" and result["last"]["a"] == "run grasp_pick"
    assert "run lift_pick" not in cells["a"].commands and "goto b1" not in cells["b"].commands


class Standing:
    """A session that reports where it stands and keeps what it was told."""

    def __init__(self, state, ok=True):
        self.state, self.ok, self.sent = state, ok, []

    def act(self, command):
        if command != "state":
            self.sent.append(command)
        return {"ok": self.ok or command == "state", "state": self.state, "error": None if self.ok else "held"}


@pytest.fixture
def geometry(monkeypatch):
    seen = {}

    def poses(frames, kin, rigid, tip, item=None):
        seen.setdefault(rigid, []).append((len(frames), item))
        return [stick(rigid)]

    monkeypatch.setattr(two, "poses_of", poses)
    monkeypatch.setattr(two, "command_frames", lambda library, command, at: [at])
    return seen


def fold_both(cells, moved_out, library=LIBRARY):
    return two.safe_fold(cells, {"a": library, "b": library}, None, {"a": 0.0, "b": 1.0}, {"a": 0.0, "b": 0.0}, 0.05,
                         lambda row: None, moved_out)


def test_a_failed_carry_really_folds_both_climbing_out_first(geometry):
    cells = {"a": Standing([9.0] * 5 + [20.0]), "b": Standing([9.0] * 5 + [40.0])}
    moved_out = {"last": {"a": "run lift_pick", "b": "run descend_pick"}, "stopped": {}}
    result = fold_both(cells, moved_out)
    assert result["folded"] is True and cells["a"].sent == ["park"] and cells["b"].sent == ["run lift_pick", "park"]
    assert geometry[1.0][-1] == (3, two.ITEM) and geometry[0.0][-1] == (1, None)  # climb + fold, the wide jaws' box in the sweep


def test_an_arm_stopped_lifting_stays_while_the_other_folds_and_a_person_is_called(geometry):
    cells = {"a": Standing([9.0] * 6), "b": Standing([9.0] * 6)}
    result = fold_both(cells, {"last": {"a": "run grasp_pick"}, "stopped": {"a": {"command": "run lift_pick", "contact": True}}})
    assert result["folded"] is False and "a person frees it" in result["person_needed"]
    assert cells["a"].sent == [] and cells["b"].sent == ["park"]


def test_a_climb_the_runner_refuses_does_not_fold_that_arm(geometry):
    cells = {"a": Standing([9.0] * 6, ok=False), "b": Standing([9.0] * 6)}
    result = fold_both(cells, {"last": {"a": "run descend_pick"}, "stopped": {}})
    assert result["folded"] is False and "did not climb out" in result["person_needed"] and cells["a"].sent == ["run lift_pick"]


def test_jaws_that_took_the_box_back_are_not_a_placed_box():
    cells = {"a": Standing([0.0] * 5 + [20.5]), "b": Standing([0.0] * 5 + [30.0])}
    assert two.still_holding(cells, {"a": LIBRARY, "b": LIBRARY}) == ["b"]
    assert two.still_holding({"a": Standing(None), "b": Standing([0.0] * 6)}, {"a": LIBRARY, "b": LIBRARY}) == ["a"]


def test_execute_accepts_inferred_holding_and_away_from_home_filters_single_tick_jitter():
    events = []
    cells = cells_of(events)
    cells["a"].holding = False
    orig_act = cells["a"].act

    def act_with_jaw_arrest(command):
        res = orig_act(command)
        if command == "run grasp_pick":
            res = {**res, "holding": False, "state": [0.0, 0.0, 0.0, 0.0, 0.0, 42.0], "gripper_closed": 20.0}
        return res

    cells["a"].act = act_with_jaw_arrest
    commands = {"a": [["run grasp_pick"], ["run lift_pick"]], "b": [["goto b0"], ["goto b1"]]}
    steps = [{"a": 0, "b": 0}, {"a": 1, "b": 1}]
    result = two.execute(cells, commands, steps, log=lambda row: None)
    assert result["failed"] is None and "run lift_pick" in cells["a"].commands

    home = [0.0, -60.0, 50.0, 50.0, 45.0, 20.0]
    spike = [0.0, -60.0, 55.0, 50.0, 45.0, 20.0]
    seq = iter([spike, home, home])

    class JitterAt:
        def act(self, command):
            return {"ok": True, "state": next(seq, home)}

    libraries = {n: {"chunks": {"home": [home]}} for n in "ab"}
    assert two.away_from_home({"a": JitterAt(), "b": Standing(home)}, libraries) == []


def gate_config(tmp_path, name, commissioning=True):
    """A config assess() accepts for this arm (supervised) or refuses (no review and no commissioning flag)."""
    import cell_robot_profile

    profile = tmp_path / f"robot-profile-{name}.json"
    profile.write_text(json.dumps({"schema": "rosy.omx-cell-robot-profile.v1", "device_id": f"device-{name}",
                                   "instance_id": f"follower-{name}", "robot_config_sha256": "c" * 64,
                                   "operating_envelope_path": "review.json", "work_dir": "."}))
    config = {"operating_profile_path": str(profile), "work_dir": str(tmp_path),
              "operating_envelope_path": str(tmp_path / "review.json"),
              "operating_conditions": {"installation_revision": "i1", "object_revision": "o1", "payload_max_kg": 0.05,
                                       "object_dimensions_m": [0.03] * 3, "environment_revision": "e1"},
              "payload": {"kg": 0.03, "source": "catalog"}}
    if commissioning:
        config["_commissioning"] = {"person_at_switch": True}  # the flag cell_two_arm.attest writes
    return config, cell_robot_profile.load(profile)["binding"]


def library_file(tmp_path, name):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"chunks": {"home": [[0.0] * 6], "above_pick": [[1.0] * 6]}, "gripper_closed": 20.0}))
    return path


class Session:
    """A runner behind the Gate: `state` carries a live operating context, every motion arrives `checked`. After
    `restart_after` motion commands the runner comes back under a new session, so the Gate holds the rest."""

    def __init__(self, binding, session="sess", state=None, delay_s=0.0, restart_after=None, fault=None):
        self.binding, self.session_id, self.state = binding, session, state or [9.0] * 6
        self.delay_s, self.restart_after, self.commands, self.motion = delay_s, restart_after, [], []
        self.fault = fault

    def act(self, command):
        self.commands.append(command)
        if command == "state":
            return {"ok": True, "state": list(self.state), "t": time.time(), "fault": self.fault,
                    "operating_context": {"scope": "simulation", "sha256": "a" * 64, "session_id": self.session_id,
                                          "operating_profile": self.binding},
                    "health": {"temp_c": [30.0] * 6, "pwm": [10] * 6}}
        motion = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        self.motion.append(motion)
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.restart_after is not None and len(self.motion) >= self.restart_after:
            self.session_id = "sess-restarted"
        return {"ok": True, "state": list(self.state), "settled": True}


def armed(tmp_path, commissioning=("a", "b"), **cells_kw):
    """Both arms' pieces for open_gates: configs, Session cells, one library per arm, and a fresh run folder."""
    configs, cells, libraries = {}, {}, {}
    for n in "ab":
        configs[n], binding = gate_config(tmp_path, n, commissioning=n in commissioning)
        cells[n] = Session(binding, f"sess-{n}", **cells_kw.get(n, {}))
        libraries[n] = [(library_file(tmp_path, f"lib-{n}"), {})]
    run = tmp_path / "run"
    run.mkdir()
    return configs, cells, libraries, run


def gates_of(cells, configs, libraries, run):
    return two.open_gates(cells, configs, {n: {} for n in "ab"}, libraries, {n: two.FOLDED for n in "ab"}, run)


def test_one_held_library_stops_the_whole_run_at_zero_motion(tmp_path):
    configs, cells, libraries, run = armed(tmp_path, commissioning=("a",))
    with pytest.raises(SystemExit, match=r"arm b.*held: .*\(D-911\)"):
        gates_of(cells, configs, libraries, run)
    assert all(c.motion == [] and set(c.commands) <= {"state"} for c in cells.values())  # neither arm moved
    intent = json.loads((run / "intent-a-0.json").read_text())
    assert intent["arm"] == "a" and intent["assessment"]["mode"] == "commissioning"


def test_an_intent_that_cannot_be_written_holds_the_run(tmp_path):
    configs, cells, libraries, run = armed(tmp_path)
    (run / "intent-a-0.json").write_text("{}")  # a pending intent from an earlier attempt is never clobbered
    with pytest.raises(SystemExit, match=r"audit_unavailable.*\(D-911\)"):
        gates_of(cells, configs, libraries, run)
    assert all(c.motion == [] for c in cells.values())


def test_two_libraries_open_one_gate_with_one_durable_intent_each(tmp_path):
    configs, cells, libraries, run = armed(tmp_path)
    libraries["a"].append((library_file(tmp_path, "lib-a2"), {}))
    gates = gates_of(cells, configs, libraries, run)
    assert (run / "intent-a-0.json").exists() and (run / "intent-a-1.json").exists()
    assert gates["a"].assessment["allowed"] is True


def test_a_command_held_mid_motion_stops_the_peer_at_its_segment_and_ends_with_a_person(geometry, tmp_path):
    configs, cells, libraries, run = armed(tmp_path, a={"restart_after": 1}, b={"delay_s": 0.15})
    gates = gates_of(cells, configs, libraries, run)
    commands = {"a": [["goto a0"], ["goto a1"], ["park a"]], "b": [["goto b0"], ["goto b1"], ["park b"]]}
    steps = [{"a": None, "b": 0}, {"a": 0, "b": 1}, {"a": 1, "b": None}, {"a": 2, "b": 2}]
    moved = two.execute(gates, commands, steps, log=lambda row: None)
    assert moved["failed"]["error"] == "held: session_changed"
    assert cells["a"].motion == ["goto a0"]  # the held command never reached the runner
    assert cells["b"].motion == ["goto b0", "goto b1"]  # the segment it was in, and no other
    folded = two.safe_fold(gates, {"a": LIBRARY, "b": LIBRARY}, None, {"a": 0.0, "b": 1.0}, {"a": 0.0, "b": 0.0},
                           0.05, lambda row: None, moved)
    assert folded["folded"] is False and "held: session_changed" in folded["person_needed"]


def test_a_restarted_runner_holds_even_the_park_and_a_person_is_needed(geometry, tmp_path):
    configs, cells, libraries, run = armed(tmp_path)
    gates = gates_of(cells, configs, libraries, run)
    cells["a"].session_id = "sess-restarted"  # the runner came back mid-run: not even the fold's park may pass
    folded = two.safe_fold(gates, {"a": LIBRARY, "b": LIBRARY}, None, {"a": 0.0, "b": 1.0}, {"a": 0.0, "b": 0.0},
                           0.05, lambda row: None, {"last": {}, "stopped": {}})
    assert folded["folded"] is False and "held: session_changed" in folded["person_needed"]


def test_the_arm_waiting_through_the_other_s_fold_keeps_its_session_alive(monkeypatch, geometry, tmp_path):
    monkeypatch.setattr(two, "KEEP_ALIVE_S", 0.01)
    configs, cells, libraries, run = armed(tmp_path, a={"delay_s": 0.2})
    folded = two.safe_fold(cells, {"a": LIBRARY, "b": LIBRARY}, None, {"a": 0.0, "b": 1.0}, {"a": 0.0, "b": 0.0},
                           0.05, lambda row: None, {"last": {}, "stopped": {}})
    assert folded["folded"] is True
    assert cells["b"].commands.count("state") >= 3  # one settled_state read; the rest is the fold-window keep-alive


def test_a_both_step_schedule_needs_a_measured_wait_pose():
    both = {"steps": [{"a": 0, "b": 0}]}
    serial = {"steps": [{"a": 0, "b": None}, {"a": None, "b": 0}]}
    libraries = {n: [("lib", {"chunks": {"home": [[0.0] * 6]}})] for n in "ab"}
    with pytest.raises(SystemExit, match="D-983"):
        two.admit(both, libraries)
    two.admit(serial, libraries)  # it waits at home, a pose the plan's rest check already cleared
    libraries["a"][0][1]["chunks"]["wait"] = [[0.0] * 6]  # a person measured where an arm may hover
    with pytest.raises(SystemExit, match="arm b"):  # one arm's wait does not clear the other's hold
        two.admit(both, libraries)
    libraries["b"][0][1]["chunks"]["wait"] = []  # an empty chunk is no measured pose
    with pytest.raises(SystemExit, match="arm b"):
        two.admit(both, libraries)
    libraries["b"][0][1]["chunks"]["wait"] = [[0.0] * 6]
    two.admit(both, libraries)
    libraries["a"].append(("lib2", {"chunks": {"home": [[0.0] * 6]}}))  # `load` swaps mid-run: every library needs its own
    with pytest.raises(SystemExit, match="arm a lib2"):
        two.admit(both, libraries)
    libraries["a"][1][1]["chunks"]["wait"] = [[0.0] * 6]
    two.admit(both, libraries)


def test_a_replan_lands_only_at_a_joint_boundary_and_reorders_the_rest():
    events = []
    cells = cells_of(events, b={"seconds": 0.12})  # b's half of a both-step is in flight when a's completion replans
    commands = {"a": [["goto a0"], ["goto a1"], ["goto a2"]], "b": [["goto b0"], ["goto b1"], ["goto b2"]]}
    steps = [{"a": 0, "b": 0}, {"a": 1, "b": None}, {"a": None, "b": 1}, {"a": 2, "b": 2}]

    def on_done(name, segment, done):
        a_first = [{"a": i, "b": None} for i in range(done["a"], 3)] + [{"a": None, "b": j} for j in range(done["b"], 3)]
        b_first = [{"a": None, "b": j} for j in range(done["b"], 3)] + [{"a": i, "b": None} for i in range(done["a"], 3)]
        return {"steps": a_first if name == "a" else b_first}  # whichever arm finished keeps the lead

    result = two.execute(cells, commands, steps, log=lambda row: None, on_segment_done=on_done)
    assert result["failed"] is None and result["done"] == {"a": 3, "b": 3} and result["plan_gen"] >= 1
    assert order(events, "a", ("end", "goto a0")) < order(events, "b", ("end", "goto b0"))  # it replanned into a moving peer
    # the replan of a's completion never landed mid-flight: a1 moved only after b finished b0
    assert order(events, "b", ("end", "goto b0")) < order(events, "a", ("start", "goto a1"))
    # the generation that landed is the later replan's (b keeps its lead), not the one it superseded
    assert order(events, "b", ("start", "goto b1")) < order(events, "a", ("start", "goto a1"))
    # admission stayed blocked while a replan was pending, even for a segment the old steps allowed
    assert order(events, "b", ("end", "goto b2")) < order(events, "a", ("start", "goto a2"))


def test_a_refused_replan_stops_both_arms_for_a_person():
    events = []
    cells = cells_of(events)
    result = two.execute(cells, COMMANDS, STEPS, log=lambda row: None, on_segment_done=lambda name, segment, done: None)
    assert result["failed"]["error"] == "replan_none" and result["done"] == {"a": 0, "b": 1}
    assert cells["a"].commands == [] and cells["b"].commands == ["goto b0"]  # b goes first: its completion refused the replan


def test_no_replan_hook_runs_once_the_run_has_failed():
    calls = []

    def hook(name, segment, done):
        calls.append((name, segment))
        return {"steps": STEPS}

    result = two.execute(cells_of([]), COMMANDS, STEPS, ("b", 0), log=lambda row: None, on_segment_done=hook)
    assert calls == [] and result["failed"]["error"] == "injected"  # b's own injected failure fired first


class OneCaller:
    """A session that fails the run if two threads are inside it at once, the race the per-arm lock prevents."""

    def __init__(self, state, seconds=0.05):
        self.state, self.seconds, self.commands, self.inside, self.raced = state, seconds, [], False, False

    def act(self, command):
        if self.inside:
            self.raced = True
            raise AssertionError("two threads entered one session")
        self.inside = True
        try:
            self.commands.append(command)
            if command != "state":
                time.sleep(self.seconds)  # motion holds the session: the window a keep-alive must never slip into
            return {"ok": True, "state": list(self.state)} if command == "state" else {"ok": True}
        finally:
            self.inside = False


def test_the_keep_alive_never_enters_an_arm_that_is_climbing_or_folding(monkeypatch, geometry):
    monkeypatch.setattr(two, "KEEP_ALIVE_S", 0.01)
    cells = {n: OneCaller([9.0] * 5 + [20.0]) for n in "ab"}
    result = fold_both(cells, {"last": {"a": "run descend_pick", "b": "run descend_pick"}, "stopped": {}})
    assert result["folded"] is True and not any(c.raced for c in cells.values())


def test_a_safety_abort_during_the_climb_out_or_fold_ends_with_a_person_not_a_crash(geometry):
    import cell_auto_safety

    class Aborts:
        """A session stopped by its monitor mid-command: the Guarded wrapper parks the arm and raises."""

        def __init__(self, at):
            self.at, self.sent = at, []

        def act(self, command):
            if command != "state":
                self.sent.append(command)
            if command == self.at:
                raise cell_auto_safety.Aborted("pwm stall")
            return {"ok": True, "state": [9.0] * 6} if command == "state" else {"ok": True}

    for at in ("run lift_pick", "park"):  # the climb out, then the fold itself
        cells = {"a": Aborts(at), "b": Standing([9.0] * 6)}
        result = fold_both(cells, {"last": {"a": "run descend_pick"}, "stopped": {}})
        assert result["folded"] is False and result["person_needed"] == "a did not fold: Aborted: pwm stall"
        assert cells["b"].sent == []  # the peer stays where it stands: its fold was only cleared against a folded


def test_a_latched_fault_holds_the_climb_out_for_a_person_not_as_a_recovery(geometry, tmp_path):
    configs, cells, libraries, run = armed(tmp_path)
    gates = gates_of(cells, configs, libraries, run)
    cells["a"].fault = "overload-hold"  # latched by the failure that stopped the run; `run lift_*` is no recovery
    folded = two.safe_fold(gates, {"a": LIBRARY, "b": LIBRARY}, None, {"a": 0.0, "b": 1.0}, {"a": 0.0, "b": 0.0},
                           0.05, lambda row: None, {"last": {"a": "run descend_pick"}, "stopped": {}})
    assert folded["folded"] is False and "a did not climb out: held: fault" in folded["person_needed"]
    assert cells["a"].motion == [] and cells["b"].motion == []  # the climb never ran and the peer never folded

