from pathlib import Path

import pytest

from rosy_cell.cell import CellError, load_cell

FIXTURE = Path(__file__).parent / "fixtures" / "cell_demo.yaml"


def test_fixture_builds_frames_and_stations():
    cell = load_cell(FIXTURE.read_text(encoding="utf-8"))
    assert cell.frames["pallet_a"].to_base((0.0, 0.0, 0.0)) == pytest.approx((0.2, 0.0, 0.0))
    assert cell.station_pose("infeed") == pytest.approx((0.0, 0.2, 0.02, 0.0))
    assert cell.approach_clearance_m == 0.05
    assert len(cell.content_hash) == 64


@pytest.mark.parametrize(
    "old, new, problem",
    [
        ("rosy_cell.cell/1", "rosy_cell.cell/9", "schema"),
        ("plane_point: [0.2, 0.1, 0]", "plane_point: [0.2, 0.1, 0.05]", "tilt"),
        ("x_point: [0.3, 0, 0]", "x_point: [0.205, 0, 0]", "pallet_a"),
        ("{frame: base, x: 0.0", "{frame: nowhere, x: 0.0", "unknown frame"),
        ("approach_clearance_m: 0.05", "approach_clearance_m: 0", "approach_clearance_m"),
    ],
)
def test_bad_cells_name_the_problem(old, new, problem):
    text = FIXTURE.read_text(encoding="utf-8").replace(old, new, 1)
    with pytest.raises(CellError) as err:
        load_cell(text)
    assert any(problem in p for p in err.value.problems), err.value.problems
