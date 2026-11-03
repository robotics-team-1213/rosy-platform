"""joint_push on the arm_b elbow samples of 2026-11-03 13:27 (1 Hz, degrees) and on normal holds."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import joint_push as jp  # noqa: E402


def samples(elbow_target, elbow_present, elbow_pwm, grip=(48.8, 48.8, -40)):
    return [([0, -60, t, 45, 10, grip[0]], [0, -60, p, 45, 10, grip[1]], [0, 0, w, 0, 0, grip[2]])
            for t, p, w in zip(elbow_target, elbow_present, elbow_pwm)]


def test_the_elbow_wind_up_before_the_overload_is_seen_and_flat_holds_are_not():
    home, short = 3134 * 360 / 4096, 3123 * 360 / 4096
    wound = jp.pushing(samples([home] * 4, [short] * 4, [261, 278, 295, 312]), {"elbow_flex": 600})
    assert wound and wound[0] == "elbow_flex"
    assert jp.pushing(samples([home] * 4, [home] * 4, [30] * 4), {"elbow_flex": 600}) is None  # folded, at rest
    hover = samples([212.1] * 4, [212.9] * 4, [-110, -154, -178, -21])  # an extended hold swings, not climbs
    assert jp.pushing(hover, {"elbow_flex": 600}) is None
    assert jp.pushing(samples([home] * 4, [short] * 4, [100, 110, 120, 130]), {"elbow_flex": 600}) is None  # low


def test_jaws_stopped_short_at_load_count_only_in_a_park():
    caught = samples([90] * 2, [90] * 2, [30] * 2, grip=(43.9, 54.6, -290))
    assert jp.pushing(caught, {"gripper": 300}) is None
    assert jp.pushing(caught, {"gripper": 300}, jaws=True)[0] == "gripper"
    closing = [([90] * 5 + [48.8], [90] * 5 + [62.0], [0] * 5 + [-200]), ([90] * 5 + [48.8], [90] * 5 + [58.0], [0] * 5 + [-200])]
    assert jp.pushing(closing, {"gripper": 300}, jaws=True) is None  # still moving
