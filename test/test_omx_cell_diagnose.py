"""cell_diagnose: the contact height names the cause; the strategy table orders what to change next."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_diagnose as dg  # noqa: E402

FLOOR, TOP, GRASP = 0.006, 0.036, 0.021


def test_the_contact_height_names_the_cause():  # the 2026-10-29 contacts
    assert dg.diagnose("contact", 0.039, FLOOR, TOP, GRASP)["cause"] == "on_top"
    assert dg.diagnose("contact", 0.030, FLOOR, TOP, GRASP)["cause"] == "beside"
    assert dg.diagnose("contact", 0.0224, FLOOR, TOP, GRASP)["cause"] == "surface"
    assert dg.diagnose("empty", None, FLOOR, TOP, GRASP)["cause"] == "empty"
    assert dg.diagnose("contact", None, FLOOR, TOP, GRASP)["cause"] == "unknown"


def test_next_actions_keep_the_table_order_and_end_with_a_person():
    assert dg.next_actions("on_top", {"other_axis", "observe_again"}) == ["other_axis", "observe_again", "ask_person"]
    assert dg.next_actions("surface", set()) == ["ask_person"]  # nothing it can do here: a person decides
    custom = {"beside": ["narrow_jaws", "ask_person"]}  # the table is data: a model or a person can replace it
    assert dg.next_actions("beside", {"narrow_jaws"}, custom) == ["narrow_jaws", "ask_person"]
