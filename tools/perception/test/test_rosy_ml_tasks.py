"""D-423 §3.2: rosy_ml deliver/promote/rollback/status take --task; promote is CLI-only."""
import sys
import types

from test_rosy_ml import _init, rosy_ml


def _seen(monkeypatch):
    seen = []
    fake = types.ModuleType("deliver")
    fake.main = lambda argv, runner=None: seen.append(argv) or 0
    monkeypatch.setitem(sys.modules, "deliver", fake)
    return seen


def test_task_and_slot_reach_deliver(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch=monkeypatch)
    seen = _seen(monkeypatch)
    assert rosy_ml.main(["deliver", "pinky-a", "rev-1", "--task", "object_det"]) == 0
    assert rosy_ml.main(["promote", "pinky-a", "--task", "object_det"]) == 0
    assert rosy_ml.main(["rollback", "pinky-a", "--task", "object_det", "--slot", "active"]) == 0
    assert rosy_ml.main(["status", "pinky-a", "--task", "object_det"]) == 0
    push, promote, rollback, status = seen
    assert push[:3] == ["push", "10.0.0.11", "rev-1"] and push[push.index("--task") + 1] == "object_det"
    assert promote[:2] == ["promote", "10.0.0.11"] and "--operator" in promote
    assert promote[promote.index("--task") + 1] == "object_det"
    assert rollback[rollback.index("--slot") + 1] == "active"
    assert status[status.index("--task") + 1] == "object_det"


def test_defaults_stay_the_lane_shadow(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch=monkeypatch)
    seen = _seen(monkeypatch)
    assert rosy_ml.main(["rollback", "pinky-b"]) == 0
    assert seen[0][seen[0].index("--task") + 1] == "lane_seg"
    assert seen[0][seen[0].index("--slot") + 1] == "shadow"
