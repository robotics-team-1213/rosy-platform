"""auto_pick --neighbour-clear-mm: a per-run neighbour margin, bounded so it never goes below the finger."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))


def test_job_spec_passes_the_bounded_margin_and_refuses_one_below_the_finger(tmp_path):
    """2026-11-27 temp_plate_a: a box with 18 / 28 mm free was refused 1 mm under the cell's 14 mm margin line."""
    import cell_job_spec as spec

    for name in ("cell-arm-a-policy.json", "catalog.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    base = {"config": "cell-arm-a-policy.json", "catalog": "catalog.json", "roi": [0, 0, 10, 10], "source": "temp_plate_a", "dest": "pallet"}
    argv = spec.build_argv(spec.JOBS["auto_pick_dry_run"], {**base, "neighbour_clear_mm": 12}, tmp_path)
    assert "--neighbour-clear-mm" in argv and float(argv[argv.index("--neighbour-clear-mm") + 1]) == 12.0
    with pytest.raises(ValueError, match="neighbour_clear_mm"):
        spec.build_argv(spec.JOBS["auto_pick_dry_run"], {**base, "neighbour_clear_mm": 6}, tmp_path)


def test_cli_parses_the_margin():
    import cell_auto_setup as setup

    args = setup.pick_parser("doc").parse_args(["--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "1", "1", "--dest", "pallet",
                                                "--neighbour-clear-mm", "12"])
    assert args.neighbour_clear_mm == 12.0
