"""cell_transfer judges a grasp against where this arm's empty jaws stop (the library's jaw_empty_stop), not the close command."""
import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("numpy")
sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
from cell_transfer import transfer_folded  # noqa: E402
from cell_envelope import SEQUENCE  # noqa: E402


class Cell:
    """Every command succeeds; the jaws read `jaws` from the grasp on, with no runner holding flag."""

    def __init__(self, jaws):
        self.jaws, self.sent = jaws, []

    def act(self, command):
        self.sent.append(command)
        grasped = any(c == "run grasp_pick" for c in self.sent)
        return {"ok": True, "state": [0, 0, 0, 0, 0, self.jaws if grasped else 57.5]}


@pytest.mark.parametrize("stop, carried", [(49.0, False), (45.5, True)])
def test_empty_jaws_end_the_carry_at_the_grasp(tmp_path, stop, carried):
    """2026-11-13 arm_s: jaws at 50.0 after the grasp were empty (this arm's empty stop is 48.8), and the carry went on to
    place nothing and reported 'placed'. Against its own stop the same reading is empty; a lower stop makes it a box."""
    library = tmp_path / "lib.json"
    library.write_text(json.dumps({"gripper_closed": stop, "jaw_empty_stop": stop, "chunks": {}}))
    cell = Cell(jaws=50.0)
    out = transfer_folded(cell, library, sequence=SEQUENCE)
    assert ("goto above_place" in cell.sent) is carried
    assert out["result"] != "empty" if carried else out == {**out, "result": "empty", "at": "run grasp_pick"}
