"""cell_identity (D-996 3-4): a container's identity comes from read tags only; mismatch holds before the place."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_identity as ci  # noqa: E402

TABLE = {"100": "CNTR-1", "101": "CNTR-2"}
READ_100 = {"state": "read", "tag": 100}
NOTHING = {"state": "unreadable"}


def test_a_tag_counts_only_with_k_votes_and_other_markers_never_vote():
    assert ci.vote([{100, 50}, {100}, {100, 7}, set(), set()], k=3)["tag"] == 100
    assert ci.vote([{100}, {100}, set(), set(), set()], k=3)["state"] == "unreadable"
    assert ci.vote([{50}, {50}, {50}, {7}, {7}], k=3)["state"] == "unreadable"  # arm/ceiling ids are not tags
    assert ci.vote([{100, 101}, {100, 101}, {100, 101}], k=3) == {"state": "mismatch", "tags": [100, 101]}


def test_one_read_face_is_enough_but_two_faces_must_agree():
    assert ci.point(READ_100, NOTHING) == {"state": "read", "tag": 100}
    assert ci.point(NOTHING, NOTHING) == {"state": "unreadable"}
    assert ci.point(READ_100, {"state": "read", "tag": 101}) == {"state": "mismatch", "tags": [100, 101]}
    assert ci.point(READ_100, {"state": "mismatch", "tags": [102, 103]})["state"] == "mismatch"


def test_identity_is_observed_only_when_the_read_tag_is_the_declared_object_ref():
    assert ci.identify([READ_100], "CNTR-1", TABLE) == {"identity": "observed", "object_ref": "CNTR-1"}
    assert ci.identify([READ_100], "CNTR-2", TABLE)["failed"] == "MISMATCH"
    assert ci.identify([{"state": "read", "tag": 150}], "CNTR-1", TABLE)["failed"] == "MISMATCH"  # not in the table
    assert ci.identify([READ_100], None, TABLE)["failed"] == "MISMATCH"  # nothing declared: no match to make
    # no FIFO, no guess: unreadable everywhere stays UNREADABLE even with a declaration
    assert ci.identify([NOTHING, NOTHING], "CNTR-1", TABLE) == {"failed": "UNREADABLE", "object_ref": "CNTR-1"}


def test_the_wrist_holds_a_mismatch_before_the_place_and_an_unreadable_wrist_keeps_the_end():
    held = ci.place_gate(READ_100, {"state": "read", "tag": 101}, "CNTR-1", TABLE)
    assert held["place"] is False and held["hold"] == "MISMATCH"
    assert ci.place_gate(READ_100, NOTHING, "CNTR-1", TABLE)["place"] is True
    assert ci.place_gate(NOTHING, READ_100, "CNTR-1", TABLE)["fact"]["identity"] == "observed"  # the wrist read it
    assert ci.place_gate(NOTHING, NOTHING, "CNTR-1", TABLE)["hold"] == "UNREADABLE"
