"""auto_pick --map-only: the measured map alone, without a pivot bias region near the object."""
from test_omx_cell_auto_pick import CATALOG, CONFIG, CONT2, ROI, Cell, auto, biased_map, cal, cell_choices, no_sleep, simulated_operating_profile  # noqa: F401  autouse profile fixture
import cell_attempts


def test_map_only_picks_on_the_measured_map_without_a_pivot_region(tmp_path):
    """2026-11-27 arm_b belt: a remap at 02:58 emptied the bias file, so every real pick held 'needs a pivot' although the
    map itself was fresh (0.6 px); the operator may run on the map alone, and the missing region is recorded."""
    path, cell = biased_map(tmp_path), Cell([CONT2])
    cell_attempts.start(tmp_path / "attempts.jsonl")
    result = auto.run_auto(cell, dict(CONFIG, _map_only=True), cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090",
                           tmp_path, cell_choices.Choices(tmp_path / "choices.json"), sleep=no_sleep)
    assert not result["result"].startswith("held: needs a pivot"), result["result"]
    assert any(command.startswith("load ") for command in cell.commands), (result["result"], cell.commands)
