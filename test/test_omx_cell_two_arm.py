"""cell_two_arm: the schedule on fake sessions: progress gates each segment, one arm's failure stops the other, the fold is
checked from where the arms stand, and nothing moves without a person."""
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
    assert result == {"done": {"a": 3, "b": 3}, "failed": None, "last": {"a": "park a", "b": "park b"}, "stopped": {}}
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

