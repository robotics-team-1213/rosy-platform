"""One folded home, one policy start (2026-11-26): every copy of the home must equal the canonical spec's idle_park."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools/sim"), str(ROOT / "deploy/robot/omx"), str(ROOT / "learning/curation/omx"), str(ROOT / "contracts/learning/src")]

from rosy.contracts.learning.omx_canonical import default_canonical_spec  # noqa: E402
import cell_policy_start_gate as gate  # noqa: E402
import cell_unwedge  # noqa: E402
import data_gate  # noqa: E402
import omx_two_arm_kin as kin  # noqa: E402

SPEC = default_canonical_spec()
IDLE = SPEC["idle_park"]["arm_a"]["norm"]
OMX = ROOT / "deploy/robot/omx"


def test_idle_park_is_the_same_for_both_arms_and_sim_rad_follows_the_norm():
    assert SPEC["idle_park"]["arm_a"] == SPEC["idle_park"]["arm_b"]
    assert kin.canonical_home_norm() == IDLE
    for arm in ("arm_a", "arm_b"):
        assert data_gate.HOME[arm] == tuple(SPEC["idle_park"][arm]["sim_rad"][:5])
    for norm, rad in zip(IDLE, SPEC["idle_park"]["arm_a"]["sim_rad"]):  # sim_rad = norm * pi / 100
        assert rad == pytest.approx(norm * 3.14159265 / 100, abs=2e-5)


def test_real_cell_home_constants_equal_idle_park():
    """Not changed here (real-path safety references); this pins them to the single source."""
    assert cell_unwedge.HOME == IDLE
    assert json.loads((OMX / "cell-profile.example.json").read_text())["home"] == IDLE
    assert json.loads((OMX / "grasp-plan.example.json").read_text())["home"] == IDLE
    assert json.loads((OMX / "sim/ladder-cell.example.json").read_text())["plan"]["home"] == IDLE


def test_twin_home_and_wait_pose_follow_idle_park():
    arm = kin.Arm("arm_a", (0, 0, 0), 0.0)
    assert list(arm.home[:5]) == pytest.approx(list(kin.norm_to_rad(IDLE)))
    assert SPEC["wait_pose"]["home"] == "idle_park"


def test_canonical_start_is_the_entry_end_within_the_jitter():
    """The library entry chunk ends on canonical_start; the gate's own check is the pin, with the spec's jitter as the width."""
    jitter = SPEC["start_jitter_rad"]
    for arm in ("arm_a", "arm_b"):
        norm = SPEC["canonical_start"][arm]["norm"]
        entry = {"chunks": {"entry": [[*IDLE, 48.8], [*norm, 56.0]]}}
        assert gate.library_entry_error(entry, arm) is None
        entry["chunks"]["entry"][-1][0] += 1.2 * jitter * 100 / 3.14159265  # 1.2 jitter widths in pan
        assert gate.START_CODE in gate.library_entry_error(entry, arm)
    assert gate.canonical_start("arm_b")[1] == jitter

