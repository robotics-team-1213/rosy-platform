"""Marker profile (D-954): the example shares no ids, and the code's own id tables are the example's."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "deploy/site/marker-profile.json.example").read_text(encoding="utf-8"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mp = _load("rosy_marker_profile", "deploy/site/marker_profile.py")
sheets = _load("rosy_cell_print_sheets_for_profile", "operations/fleet/fleet/server/cell/cell_print_sheets.py")


def test_the_example_shares_ids_only_with_the_calibration_board():
    errors, warnings = mp.check(EXAMPLE)
    assert errors == []
    assert warnings and all(w.startswith("charuco_board and ") for w in warnings)


def test_ids_are_compared_across_the_dictionaries_of_one_family():
    profile = {"schema": mp.SCHEMA, "allocations": [
        {"owner": "robots", "dictionary": "DICT_4X4_50", "ids": [40, 49]},
        {"owner": "arm_slot_1", "dictionary": "DICT_4X4_100", "ids": [35, 49]},
        {"owner": "other_family", "dictionary": "DICT_5X5_50", "ids": [40, 49]}]}
    assert mp.check(profile) == (["robots and arm_slot_1 share 4X4 ids 40-49"], [])


@pytest.mark.parametrize("ids", [[45, 55], [5, 4], [-1, 3], [1.0, 2]])
def test_ids_outside_the_dictionary_or_reversed_are_refused(ids):
    row = {"owner": "x", "dictionary": "DICT_4X4_50", "ids": ids}
    errors, _ = mp.check({"schema": mp.SCHEMA, "allocations": [row]})
    assert errors == ["x: ids must be [first, last] within DICT_4X4_50 (0-49)"]


def test_an_arm_without_its_slot_block_is_refused():
    profile = {**EXAMPLE, "arms": {**EXAMPLE["arms"], "4": "C"}}
    assert mp.check(profile)[0] == ["arms names slot 4 but no arm_slot_4 allocation"]


def test_site_cameras_may_name_only_their_owners_ids():
    yaml = pytest.importorskip("yaml")
    cameras = yaml.safe_load((ROOT / "deploy/site/site-cameras.yaml.example").read_text(encoding="utf-8"))
    assert mp.check_cameras(EXAMPLE, cameras) == []
    bad = {"sources": [{"source_id": "c", "corner_marker_ids": [30, 40], "robot_markers": {"rosy_01": 50}}]}
    assert mp.check_cameras(EXAMPLE, bad) == ["c: corner_marker_ids 40 are not field_corners ids",
                                              "c: robot_markers 50 are not robots ids"]


def test_the_code_tables_are_the_example_profile():
    np = pytest.importorskip("numpy")  # noqa: F841 - the Vision model and cell_frame import it
    table = mp.owned(EXAMPLE)
    vision = _load("rosy_vision_track_model_for_profile", "operations/overhead/rosy_vision/track/model.py")
    assert list(vision.ROBOT_MARKER_IDS) == table["robots"]
    sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
    import cell_frame

    assert sheets.ARM_SLOTS == len([o for o in table if o.startswith("arm_slot_")])
    for slot in range(1, sheets.ARM_SLOTS + 1):
        block = sheets.arm_ids(slot)
        assert [block["gripper"], *block["base"], *sum(block["surfaces"], [])] == table[f"arm_slot_{slot}"]
        assert cell_frame.slot_ids(slot) == block


def test_arm_ids_are_three_bits_from_every_ceiling_id_in_any_turn():
    # The ceiling reads DICT_4X4_50 (ids 0-49) with no bit corrected, so an arm marker never reads as a robot.
    def grid(v):
        return tuple(tuple((v >> (15 - 4 * r - c)) & 1 for c in range(4)) for r in range(4))

    def turns(g):
        for _ in range(4):
            yield g
            g = tuple(zip(*g[::-1]))

    ceiling = [grid(v) for v in sheets.DICT_4X4_100[:50]]
    arms = [i for owner, ids in mp.owned(EXAMPLE).items() if owner.startswith("arm_slot_") for i in ids]
    nearest = min(sum(a != b for ra, rb in zip(t, c) for a, b in zip(ra, rb))
                  for i in arms for t in turns(grid(sheets.DICT_4X4_100[i])) for c in ceiling)
    assert nearest >= 3
