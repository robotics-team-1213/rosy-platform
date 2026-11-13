"""Two-stage descent: faster above the last descend_near_m, today's pace (and contact judgement) below."""
import json
from pathlib import Path
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path[:0] = [str(OMX), str(Path(__file__).parents[1] / "middleware/devices/omx/adapter")]
import descend_profile  # noqa: E402
import grasp_planner as gp  # noqa: E402
from omx_adapter.z_profile import _fk_tcp_xyz_mm  # noqa: E402
from teach_trajectory import too_fast  # noqa: E402


def descents(**extra):
    plan = json.loads((OMX / "grasp-plan.example.json").read_text())
    point = dict(x=0.14, y=0.02, z=0.03, yaw_deg=0.0)
    plan = dict(plan, pick=point, place=point, keep_out=None, descend_guard_frac=0.30)
    old = gp.Planner(plan).library()["chunks"]["descend_pick"]
    new = gp.Planner(dict(plan, **extra)).library()["chunks"]["descend_pick"]
    return old, new


def entry_speed(frames, near_mm=10.0):
    z = [_fk_tcp_xyz_mm(f[:5], unit="norm")[2] for f in frames]
    return next((a - b) * 30 for a, b in zip(z, z[1:]) if b - z[-1] <= near_mm)


def test_a_two_stage_descent_is_faster_but_enters_the_last_cm_at_todays_speed_and_ends_on_the_same_pose():
    old, new = descents(descend_far_guard_frac=0.85)
    assert len(new) < len(old) - 30  # over a second sooner at 30 Hz
    assert entry_speed(new) == pytest.approx(entry_speed(old), abs=0.5)
    assert new[-1] == old[-1] and not too_fast(new, 30)
    z = [_fk_tcp_xyz_mm(f[:5], unit="norm")[2] for f in new]
    assert all(b <= a + 1e-6 for a, b in zip(z, z[1:]))  # never back up


def test_without_the_key_or_with_no_room_for_the_ramps_the_descent_is_todays():
    old, same = descents()
    assert same == old
    _, short = descents(descend_far_guard_frac=0.85, descend_near_m=0.039)  # near zone eats the whole approach
    assert short == old


def test_the_profile_never_streams_past_its_far_speed():
    frames = [[0.0, float(k), 0.0, 0.0, 0.0, 0.0] for k in range(1, 41)]
    out = descend_profile.two_stage(frames, 30, 4.0, 1.0, 30, start=[0.0] * 6)
    steps = [b[1] - a[1] for a, b in zip([[0.0] * 6] + out, out)]
    assert max(steps) <= 4.0 / 30 + 1e-6 and min(steps) >= -1e-9 and out[-1] == frames[-1]
    assert max(steps[-15:]) <= 1.0 / 30 + 1e-6  # the last frames run at the near speed or slower
