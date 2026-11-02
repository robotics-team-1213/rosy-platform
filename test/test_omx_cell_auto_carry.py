"""cell_auto_carry: carries until the source is empty, the first carry not placed, or the reviewed count."""
from pathlib import Path
import sys

import pytest

pytest.importorskip("cv2")
pytest.importorskip("numpy")
pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_auto_carry as carry
finally:
    sys.path.remove(str(OMX))

PLACED = {"result": "placed", "attempts": [{"observed": 2}]}
EMPTY = {"result": "stopped: no usable object", "attempts": [{"observed": 0, "refused": []}]}
PACKED = {"result": "stopped: no usable object", "attempts": [{"observed": 2, "refused": [{"why": "tangled blob"}]}]}


def runs(*results):
    left = list(results)
    return lambda: left.pop(0)


def test_carries_until_the_source_has_nothing_left():
    out = carry.carry(runs(PLACED, PLACED, EMPTY), 5)
    assert out["result"] == "source empty" and out["placed"] == 2


def test_objects_left_but_unusable_is_a_stop_not_an_empty_source():
    out = carry.carry(runs(PLACED, PACKED), 5)
    assert out["result"] == "stopped: no usable object" and out["placed"] == 1 and out["last"] is PACKED


@pytest.mark.parametrize("stop", ["held: not a reviewed task", "stopped: empty -> retry", "aborted: temperature"])
def test_the_first_carry_not_placed_ends_the_run(stop):
    out = carry.carry(runs(PLACED, {"result": stop}, PLACED), 5)
    assert out["result"] == stop and out["placed"] == 1


def test_the_reviewed_count_bounds_the_run():
    out = carry.carry(runs(PLACED, PLACED, PLACED), 2)
    assert out["result"] == "done: 2 carries" and out["placed"] == 2


def test_a_dark_view_ends_the_run_before_the_next_carry():
    views = [[], ["top: too dark"]]
    out = carry.carry(runs(PLACED, PLACED), 5, dark=lambda: views.pop(0))
    assert out["result"] == "refused: top: too dark" and out["placed"] == 1


def test_no_commissioning_and_a_count_is_required(capsys):
    with pytest.raises(SystemExit):
        carry.main(["--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "1", "1", "--dest", "belt",
                    "--commissioning", "--max", "3"])
    with pytest.raises(SystemExit):
        carry.main(["--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "1", "1", "--dest", "belt"])
