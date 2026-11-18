"""Goal vector encoding for the two-arm policy (`omx_two_arm_policy_helpers` re-exports it): what tells ACT which container to take."""
from pathlib import Path
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import omx_two_arm_tasks as tasks  # noqa: E402

GOAL_SIZE = 22  # per arm (arm_a, arm_b): active, then the five grasp joints and the five lower joints
# joints: the teacher's IK joints (needs the sim's site geometry); site: which source and target site by name (an admitted job carries
# exactly this on the real cell, 2026-11-17 panel), so ACT can be told which container to take without language or privileged state.
GOAL_MODES = ("joints", "site")


def site_names(layout):
    return sorted(layout.sites)


def goal_size(layout, mode="joints"):
    return GOAL_SIZE if mode == "joints" else 2 * (1 + 2 * len(site_names(layout)))


def goal_block(layout, step, here, mode="joints"):
    """One arm's part of the goal. `site`: 1, then one-hot source and one-hot target over `site_names`. `joints`: 1, then the five joints
    that grasp at the source and lower onto the target, from the teacher's own IK on the nominal sites. Round 1 gave site metres: sites
    36 mm apart differed by 0.36 in an unnormalised input and the model came down 2 cm off."""
    if mode == "site":
        names = site_names(layout)
        out = np.zeros(1 + 2 * len(names), np.float32)
        out[0], out[1 + names.index(step["from"])], out[1 + len(names) + names.index(step["to"])] = 1., 1., 1.
        return out
    if mode != "joints":
        raise ValueError(f"goal mode {mode!r} not in {GOAL_MODES}")
    arm = layout.sim_arms[step["arm"]]
    wps = tasks.waypoints(layout, step, here)
    ok, _, path, note = tasks.solve_chain(arm, wps, arm.home, roll_floor=layout.roll_floor)
    if not ok:
        raise ValueError(f"{step['id']}: {note}")
    per = (len(path) - 1) // (len(wps) - 1)
    grasp, lower = path[per], path[5 * per]  # waypoints 1 and 5: grasp and lower
    return np.array([1., *grasp[:5], *lower[:5]], dtype=np.float32)


def goal_of(blocks, size=GOAL_SIZE):
    """The goal vector from {arm: block}; an arm without a step has zeros (it waits)."""
    out = np.zeros(size, np.float32)
    for arm, block in blocks.items():
        k = sites.ARMS.index(arm) * (size // 2)
        out[k:k + size // 2] = block
    return out


def goal_vector(layout, step, here, mode="joints"):
    return goal_of({step["arm"]: goal_block(layout, step, here, mode)}, goal_size(layout, mode))
