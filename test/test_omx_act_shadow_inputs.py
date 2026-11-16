"""The two-arm ACT shadow takes the inputs the policy was trained on, and only reads the cell to get them."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
from test_omx_act_shadow import (  # noqa: E402,F401  (the simulated cell, and its autouse operating-profile fixture)
    CATALOG, CONFIG, CONT2, ROI, Cell, auto, calibrated_map, cal, cell_attempts, cell_choices, no_sleep, simulated_operating_profile,
)

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
shadow_mod = auto.cell_act_shadow
inputs = shadow_mod.inputs
NAMES = ["a", "b"]  # the fake policy's two site names


def binding(goal_size=0, goal_mode="site", views=inputs.VIEWS, shape=(3, 240, 320)):
    seen = []
    return SimpleNamespace(
        image_views=views, image_shape=shape, state_size=12, joint_names=inputs.JOINT_NAMES, goal_size=goal_size,
        goal_mode=goal_mode, goal_sites=tuple(NAMES), policy_revision="rev-two-arm", policy_environment="sim", seen=seen,
        infer=lambda taken: (seen.append(taken), SimpleNamespace(chunk=[[0.0] * 12] * 3))[1])


class ReadOnlyCell:
    """A cell that records every call; the shadow may only ask for frames and the state."""

    def __init__(self, marker, state, cameras=("top", "side", "wrist"), shape=(480, 640)):
        self.marker, self.state, self.cameras, self.shape, self.calls = marker, state, cameras, shape, []

    def frame(self, camera):
        self.calls.append(("frame", camera))
        if camera not in self.cameras:
            raise KeyError(camera)
        image = np.zeros((*self.shape, 3), np.uint8)
        image[..., 0] = self.marker  # blue in BGR, so red once converted to RGB
        return image

    def act(self, command, timeout=None):
        self.calls.append(("act", command))
        return {"ok": True, "state": self.state, "command": command}


def pair(**kwargs):
    return (ReadOnlyCell(10, [0, 0, 0, 0, 0, 0], **kwargs), ReadOnlyCell(20, [10, -10, 20, 0, 5, 75]))


SPEC = {"kind": "two_arm", "site_map": {"src": "a", "dst": "b"}}


def test_assemble_follows_the_trained_layout():
    own, peer = pair()
    taken = inputs.assemble(own, {"arm_id": "arm_b"}, peer, SPEC, binding(goal_size=2 * (1 + 2 * 2)), "src", "dst")
    assert list(taken["images"]) == ["top", "side", "a_wrist", "b_wrist"]
    assert all(image.shape == (240, 320, 3) and image.dtype == np.uint8 for image in taken["images"].values())
    # this cell is arm_b: top/side and b_wrist from it, a_wrist from the peer; BGR in, RGB out
    assert taken["images"]["top"][0, 0].tolist() == [0, 0, 10] and taken["images"]["a_wrist"][0, 0].tolist() == [0, 0, 20]
    assert taken["images"]["b_wrist"][0, 0].tolist() == [0, 0, 10]
    assert taken["meta"]["camera_sources"] == {"top": "arm_b.top", "side": "arm_b.side", "a_wrist": "arm_a.wrist", "b_wrist": "arm_b.wrist"}
    state = taken["state"]  # arm_a (the peer) first, then arm_b: five joints and the gripper each, radians
    assert state.shape == (12,) and state.dtype == np.float32 and abs(state[6:11]).max() < 2e-3 and state[0] > 0.3 and state[1] < -0.3
    assert 1.5 < state[5] < 1.6  # gripper 75 of 0..100 through the cell's to_radians
    goal = taken["goal"]  # arm_b's half only: active, one-hot source "a", one-hot target "b"
    assert goal.shape == (10,) and goal[:5].tolist() == [0] * 5 and goal[5:].tolist() == [1, 1, 0, 0, 1]
    assert own.calls.count(("act", "state")) == 1 and peer.calls.count(("act", "state")) == 1
    assert {kind for kind, _ in own.calls + peer.calls} <= {"frame", "act"} and {c for k, c in own.calls + peer.calls if k == "act"} == {"state"}


@pytest.mark.parametrize("make,needle", [
    (lambda: (pair(cameras=("top", "wrist"))[0], pair()[1]), "side"),
    (lambda: (pair(shape=(0, 0))[0], pair()[1]), "top"),
])
def test_missing_camera_refuses_with_its_name(make, needle):
    own, peer = make()
    with pytest.raises(inputs.Unavailable) as error:
        inputs.assemble(own, {"arm_id": "arm_a"}, peer, SPEC, binding(), "src", "dst")
    assert needle in error.value.missing


def test_one_arm_only_refuses():
    own, _ = pair()
    with pytest.raises(inputs.Unavailable, match="arm_b is not connected") as error:
        inputs.assemble(own, {"arm_id": "arm_a"}, None, SPEC, binding(), "src", "dst")
    assert "state:arm_b" in error.value.missing
    with pytest.raises(inputs.Unavailable, match="arm_s"):  # cell S is no arm of the two-arm policy
        inputs.assemble(own, {"arm_id": "arm_s"}, pair()[1], SPEC, binding(), "src", "dst")


def test_unreadable_state_and_unmapped_goal_refuse():
    own, peer = pair()
    peer.act = lambda command, timeout=None: {"ok": False, "error": "chunk_runner is not running"}
    with pytest.raises(inputs.Unavailable) as error:
        inputs.assemble(own, {"arm_id": "arm_a"}, peer, SPEC, binding(), "src", "dst")
    assert error.value.missing == ["state:arm_b"]
    own, peer = pair()
    with pytest.raises(inputs.Unavailable, match="do not map"):
        inputs.assemble(own, {"arm_id": "arm_a"}, peer, SPEC, binding(goal_size=10), "src", "0.06,0.09")
    with pytest.raises(inputs.Unavailable, match="joints goal"):
        inputs.assemble(own, {"arm_id": "arm_a"}, peer, SPEC, binding(goal_size=22, goal_mode="joints"), "src", "dst")
    spec = dict(SPEC, joint_goals={"src>dst": list(range(11))})
    goal = inputs.assemble(own, {"arm_id": "arm_a"}, peer, spec, binding(goal_size=22, goal_mode="joints"), "src", "dst")["goal"]
    assert goal[:11].tolist() == list(range(11)) and not goal[11:].any()


def test_checkpoint_layout_must_match_the_trained_one(monkeypatch):
    own, peer = pair()
    for bad in (binding(views=("top", "a_wrist")), binding(shape=(3, 480, 640))):
        with pytest.raises(inputs.Unavailable, match="trained layout"):
            inputs.assemble(own, {"arm_id": "arm_a"}, peer, SPEC, bad, "src", "dst")
    monkeypatch.setattr(inputs, "MAX_SPAN_S", -1)  # frames and both states taken further apart than one moment
    with pytest.raises(inputs.Unavailable, match="not one moment"):
        inputs.assemble(own, {"arm_id": "arm_a"}, peer, SPEC, binding(), "src", "dst")


def test_goal_matches_the_sim_policy_helper():
    sys.path.insert(0, str(Path(__file__).parents[1] / "tools/sim"))
    try:
        import omx_two_arm_policy_helpers as helpers
        import omx_two_arm_sites as sites
        layout = sites.Layout()
        names = helpers.site_names(layout)
        source, target = names[0], names[-1]
        step = {"arm": "arm_b", "from": source, "to": target}
        expected = helpers.goal_vector(layout, step, {}, "site")
    except Exception as error:  # the sim stack (MuJoCo/LeRobot) is a lab-PC dependency
        pytest.skip(f"sim helpers unavailable: {type(error).__name__}")
    finally:
        sys.path.remove(str(Path(__file__).parents[1] / "tools/sim"))
    fake = SimpleNamespace(goal_size=expected.size, goal_mode="site", goal_sites=tuple(names))
    got = inputs.goal({"site_map": {"s": source, "t": target}}, fake, "arm_b", "s", "t")
    assert got.tolist() == expected.tolist()


def source_calls(path):
    return [node for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))) if isinstance(node, ast.Call)]


def test_shadow_modules_hold_no_motion_port():
    for name in ("cell_act_inputs.py", "cell_act_shadow.py"):
        calls = source_calls(OMX / name)
        acts = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr in ("act", "checked", "_send")]
        assert all(c.func.attr == "act" and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "state" for c in acts), name
        assert not any(isinstance(c.func, ast.Attribute) and c.func.attr in ("system", "Popen", "run") for c in calls), name
        assert "chunk-cmd" not in (OMX / name).read_text(encoding="utf-8")


def run_two_arm(tmp_path, monkeypatch, config, peer, spec=SPEC, policy=None):
    policy = policy or binding()
    monkeypatch.setattr(shadow_mod, "load", lambda cfg, work: shadow_mod.Shadow(policy, work, None, spec=spec, peer=peer))
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "r1", arm_id=config["arm_id"])  # the gate scopes its ledger by arm
    cell = Cell([CONT2])
    path = calibrated_map(tmp_path, cell)
    result = auto.run_auto(cell, config, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"), sleep=no_sleep, log=lambda row: None, scenario_id="carry-17")
    log = tmp_path / "act-shadow.jsonl"
    assert log.exists(), result  # a carry that never reached the shadow capture says why in its result
    return result, [json.loads(line) for line in log.read_text().splitlines()], policy


def test_carry_rows_hold_four_views_and_both_arms_and_the_ik_outcome_is_unchanged(tmp_path, monkeypatch):
    peer = Cell([CONT2])
    result, rows, policy = run_two_arm(tmp_path, monkeypatch, dict(CONFIG, arm_id="arm_a"), peer)
    assert result["result"] == "placed" and len(rows) == 2 and all("error" not in r for r in rows)
    observation = rows[0]["observation"]
    assert observation["views"] == ["top", "side", "a_wrist", "b_wrist"] and len(observation["positions"]) == 12
    assert len(observation["joint_names"]) == 12 and observation["joint_names"][6] == "arm_b.joint1" and "camera_identity" not in observation
    assert all(len(rows[0]["proposed"]) == 3 and len(q) == 12 for q in rows[0]["proposed"])
    assert [row["ik"]["outcome"] for row in rows] == ["empty", "placed"] and len(policy.seen) == 2
    assert set(peer.commands) == {"state"}  # the other arm was only asked for its state


@pytest.mark.parametrize("config,peer", [(dict(CONFIG, arm_id="arm_a"), None), (dict(CONFIG, arm_id="arm_s"), Cell([CONT2]))])
def test_unavailable_inputs_are_a_row_field_and_never_infer(tmp_path, monkeypatch, config, peer):
    result, rows, policy = run_two_arm(tmp_path, monkeypatch, config, peer)
    assert result["result"] == "placed" and rows and not policy.seen
    assert all("inputs_unavailable" in row["error"] and "proposed" not in row and row["missing"] for row in rows)
