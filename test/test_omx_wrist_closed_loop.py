"""Closed loop of the sim grasp: the wrist camera's view gives the container's top face relative to the jaw without ground truth, and the loop is off unless asked."""
import argparse
import math
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_two_arm_skill as skills  # noqa: E402
import omx_wrist_closed_loop as cl  # noqa: E402

BOX = (0.09, 0.02998, 0.0324)  # the 1x3 container: long, short, height (m)


def _rig():
    """The v21-b wrist camera of the model: quaternion (w, x, y, z) of the camera frame in link5, lens offset, TCP offset, vertical field of view."""
    w, x, y, z = -0.62614427, -0.32854734, 0.32854734, 0.62614427
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                  [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                  [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])
    return cl.WristRig(R, [0.0338, 0., 0.0511], [0.074, -0.0016, 0.], 69.6, name="a_wrist")


R_TCP = np.array([[0., 0., 1.], [0., 1., 0.], [-1., 0., 0.]])  # tool pointing down: TCP x = world -z, TCP z = world x


def _image(rig, e, yaw):
    """What the camera shows of an upright container whose top face centre is e (world axes) above and beside the TCP: its silhouette in container orange on grey."""
    import cv2
    c, s = math.cos(yaw), math.sin(yaw)
    uv = rig.project((cl._corners(BOX) @ np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]]) + e) @ R_TCP)
    img = np.full((*rig.size, 3), 90, np.uint8)
    cv2.fillPoly(img, [cv2.convexHull(np.round(uv).astype(np.int32))], (206, 103, 47))
    return img


@pytest.mark.parametrize("e", [(-.0025, 0., .0126), (-.002, .003, .008), (-.004, -.004, .019)])
def test_the_fit_finds_the_top_face_from_the_image_alone(e):
    """Height and the sideways offset across the jaw (the two that decide a close) come back within 1.5 mm; the offset along the container, which the clipped near end hides, within 5."""
    pytest.importorskip("cv2")
    rig, e = _rig(), np.array(e)
    fit = cl.fit_top_face(_image(rig, e, .1), rig, R_TCP, BOX, cl.E_REF["arm_a"], .1)
    assert fit is not None and fit["score"] > .9
    assert abs(fit["e"][2] - e[2]) < .0015 and abs(fit["e"][1] - e[1]) < .0015 and abs(fit["e"][0] - e[0]) < .005


def test_no_container_in_view_means_no_estimate():
    pytest.importorskip("cv2")
    rig = _rig()
    assert cl.fit_top_face(np.full((*rig.size, 3), 90, np.uint8), rig, R_TCP, BOX, cl.E_REF["arm_a"], 0.) is None


def test_a_point_behind_the_camera_cannot_be_projected():
    assert _rig().project([[0., 0., 0.5]]) is None


def test_closed_loop_is_off_by_default_and_names_its_parts():
    parser = argparse.ArgumentParser()
    skills.options(parser)
    assert parser.parse_args([]).closed_loop == ()
    args = parser.parse_args(["--closed-loop", "wrist,contact"])
    assert args.closed_loop == ("wrist", "contact")
    argv = skills.argv(args)
    assert argv[argv.index("--closed-loop") + 1] == "wrist,contact"
    with pytest.raises(SystemExit):
        parser.parse_args(["--closed-loop", "magic"])


def _one_grasp_row(closed_loop):
    """One 'stack' step 1 grasp (IK driver) in the MuJoCo sim, from a nominal seed."""
    try:
        import mujoco  # noqa: F401
        import omx_two_arm_tasks as tasks
        import omx_two_arm_world as tw
    except Exception as exc:
        pytest.skip(str(exc))
    layout = skills.sites.Layout()
    world = tw.World(layout)
    plan = tasks.get_task(layout, "stack")["steps"][0]
    here = dict(tasks.get_task(layout, "stack")["start"])
    teacher = skills.teaching.Teacher(world, seed=1003)
    teacher.closed_loop = tuple(closed_loop)
    data = teacher.fresh(here)
    driver = type("IkDriver", (), dict(world=world, layout=layout, kind="ik"))()
    try:
        return skills.step(driver, teacher, data, plan, here, "grasp")
    except Exception as exc:  # no GL on this host: the loop cannot render its wrist view, which says nothing about the code
        if closed_loop and ("GL" in str(exc) or "OpenGL" in str(exc) or "EGL" in str(exc)):
            pytest.skip(str(exc))
        raise


def test_the_default_row_has_no_closed_loop_record_and_the_loop_runs_a_row_when_asked():
    """Main has no pose-random, so no success rate is claimed here: off leaves the row as before, on completes a grasp row and reports what it did (grasp_s, cl)."""
    off = _one_grasp_row(())
    assert off["result"] in ("pass", "fail") and "cl" not in off and off["grasp_s"] > 0
    on = _one_grasp_row(("wrist", "contact"))
    assert on["result"] in ("pass", "fail") and on["grasp_s"] > 0 and isinstance(on.get("cl"), dict)
