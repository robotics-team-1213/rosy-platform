"""cell_space: an arm may not reserve a corridor that touches another arm's live one; expiry frees a dead holder."""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fcntl")
pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_space as cs  # noqa: E402


def lane(x0, x1):
    mask = np.zeros((100, 200), bool)
    mask[40:60, x0:x1] = True
    return mask


def test_a_corridor_near_another_arms_live_one_is_refused_and_a_far_one_is_not(tmp_path):
    space = cs.Space(tmp_path, margin_px=5)
    assert space.reserve("arm_a", lane(10, 60))["ok"]
    near = space.reserve("arm_b", lane(63, 120))  # 3 px apart: inside the margin
    assert not near["ok"] and near["with"] == "arm_a"
    assert space.reserve("arm_b", lane(80, 150))["ok"]
    assert set(space.live()) == {"arm_a", "arm_b"}


def test_release_and_expiry_free_the_space(tmp_path):
    now = [1000.0]
    space = cs.Space(tmp_path, margin_px=5, clock=lambda: now[0])
    assert space.reserve("arm_a", lane(10, 60), ttl_s=30)["ok"]
    assert not space.reserve("arm_b", lane(30, 90))["ok"]
    now[0] += 31  # arm_a's process died without releasing
    assert space.reserve("arm_b", lane(30, 90))["ok"]
    space.release("arm_b")
    assert space.live() == {}


def test_an_arm_renews_its_own_reservation_and_ids_are_plain_names(tmp_path):
    space = cs.Space(tmp_path)
    assert space.reserve("arm_a", lane(10, 60))["ok"]
    assert space.reserve("arm_a", lane(10, 80))["ok"]  # its own corridor never blocks it
    with pytest.raises(ValueError):
        space.reserve("../x", lane(0, 5))
