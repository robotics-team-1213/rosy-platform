"""An out-of-reach refusal names the move that would bring the object inside the park reach (2026-11-19)."""
import math
import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_auto_pick_plan as plan  # noqa: E402

CONFIG = {"plan": {"limits": {"park_reach_m": 0.2}}}
RAW = (-0.0156, 0.2214)  # 03:54 observation: 222 mm


def test_the_fix_moves_the_object_toward_the_arm_base():
    reach = plan.past_park_reach(CONFIG, RAW)
    assert reach == 222
    fix = plan.reach_fix(CONFIG, RAW, reach)
    assert fix["reach_mm"] == 222 and fix["limit_mm"] == 200 and fix["object_arm_xy_m"] == [-0.0156, 0.2214]
    dx, dy = fix["need_arm_dxdy_m"]
    assert math.hypot(dx, dy) == pytest.approx(0.052, abs=1e-3)  # 222 - 200 + 30 mm
    assert dx > 0 and dy < 0  # opposite to raw_m: toward the origin
    assert dx / dy == pytest.approx(RAW[0] / RAW[1], abs=1e-3)


def test_it_is_offered_only_when_reach_is_the_only_refusal():
    fix = {"reach_mm": 222}
    assert plan.reach_fix_of([{"object": "box", "reach_fix": fix}, {"object": None, "why": "no catalogue match"}]) == {"reach_fix": fix}
    assert plan.reach_fix_of([{"object": "box", "reach_fix": fix}, {"object": "cube", "why": "tangled blob"}]) == {}
    assert plan.reach_fix_of([]) == {}
