"""cell_role: supply arm S rescues fallen containers first, then loads the Pinky's onto the belt and retrieves."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_role as cr  # noqa: E402


def name(counts, last=None):
    step = cr.next_step(counts, cr.ROLE, last)
    return step and step["name"]


def test_a_fallen_container_is_rescued_before_anything_else():
    assert name({"floor": 1, "pinky": 1, "belt": 1}) == "rescue"
    assert name({"floor": 1, "pinky": 1, "belt": 1}, last="rescue") == "rescue"  # still one down: keep rescuing


def test_load_and_retrieve_follow_the_containers_and_alternate():
    assert name({"floor": 0, "pinky": 1, "belt": 0}) == "load"
    assert name({"floor": 0, "pinky": 0, "belt": 1}) == "retrieve"
    assert name({"pinky": 1, "belt": 1}, last="load") == "retrieve"  # one on each: take turns
    assert name({"pinky": 1, "belt": 1}, last="retrieve") == "load"
    assert name({"floor": 0, "pinky": 0, "belt": 0}) is None


def test_the_role_is_data():
    only_load = {"steps": [{"name": "load", "from": "pinky", "to": "belt"}]}
    assert cr.next_step({"floor": 3, "pinky": 1}, only_load)["name"] == "load"
