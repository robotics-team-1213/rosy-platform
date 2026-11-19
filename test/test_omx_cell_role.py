"""cell_role: on its own, supply arm S only rescues fallen containers; load and retrieve are refused (D-996 5)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_role as cr  # noqa: E402


def name(counts, last=None):
    step = cr.next_step(counts, cr.ROLE, last)
    return step and step["name"]


def test_a_fallen_container_is_rescued():
    assert name({"floor": 1, "pinky": 1, "belt": 1}) == "rescue"
    assert name({"floor": 1, "pinky": 1, "belt": 1}, last="rescue") == "rescue"  # still one down: keep rescuing


def test_a_container_on_the_pinky_or_the_belt_is_not_carried_by_the_loop():
    # load is a Fleet ARM_TRANSFER job after the trip arrives; retrieve is refused (D-996 5, D-858 1)
    assert name({"floor": 0, "pinky": 1, "belt": 0}) is None
    assert name({"floor": 0, "pinky": 0, "belt": 1}) is None
    assert name({"pinky": 1, "belt": 1}, last="load") is None


@pytest.mark.parametrize("step", [{"name": "load", "from": "pinky", "to": "belt"},
                                  {"name": "retrieve", "from": "belt", "to": "pinky"}])
def test_a_config_role_naming_load_or_retrieve_is_refused_not_skipped(step):
    role = {"steps": [cr.ROLE["steps"][0], step]}
    with pytest.raises(ValueError, match="Fleet job"):
        cr.next_step({"floor": 0, "pinky": 1, "belt": 1}, role)
    with pytest.raises(ValueError):
        cr.checked_role({"steps": [step]})
