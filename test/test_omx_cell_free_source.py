"""auto_pick --from free:<site> [--at-px U,V]: an object outside every site surface, its top height measured by depth."""
import copy

import pytest

from test_omx_cell_auto_pick import CATALOG, CONFIG, ROI, Cell, auto, biased_map, cal, cell_choices, np  # noqa: F401  autouse profile fixture
import cell_free_source as cfs

CONT = {"x": 0.072, "y": 0.120, "long": 30.0, "length": 60, "width": 30}
SURFACE_Z, HEIGHT_M = 0.045, 0.65  # sites.pinky.surface_z and cameras.top.height_m of the example config


def clipped_config(tmp_path):
    """pinky's surface polygon stops left of the container: a site pick sees nothing, as the red box beside the belt."""
    config = copy.deepcopy(CONFIG)
    config["sites"]["pinky"]["surface_px"] = [[160, 205], [300, 205], [300, 420], [160, 420]]
    config["plan"]["limits"]["workspace_min_m"][2] = -0.10  # the arm cell's low zone, as an owner would authorise it
    return config


def depth(monkeypatch, cell, top_mm=30.0, per_frame=None, cam_off_mm=0.0, frames=7):
    """Heights as the D435 would give them: 0 on pinky's surface, top_mm over the container's pixels."""
    img = cell.frame("top")
    box = (img == (60, 160, 60)).all(axis=2)
    seen = iter(range(100))
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: (np.zeros((frames, 480, 640), np.uint16), {}))

    def heights(frame, colour, cam):
        h = np.zeros((480, 640))
        h[box] = per_frame[next(seen) % len(per_frame)] if per_frame else top_mm
        return h, np.eye(3), [], (HEIGHT_M - SURFACE_Z) * 1000.0 + cam_off_mm

    monkeypatch.setattr(cfs, "_frame_heights", heights)


def run(tmp_path, cell, config, source):
    path = biased_map(tmp_path)
    return auto.run_auto(cell, config, cal.load(path), path, CATALOG, ROI, source, "0.060,0.090", tmp_path,
                         cell_choices.Choices(tmp_path / "choices.json"), dry_run=True)


def test_a_site_source_still_sees_nothing_outside_its_polygon(tmp_path):
    result = run(tmp_path, Cell([CONT]), clipped_config(tmp_path), "pinky")
    assert result["result"].startswith("stopped") and "free_source" not in result


def test_free_source_finds_the_box_outside_the_polygon_and_plans_at_the_measured_z(tmp_path, monkeypatch):
    cell = Cell([CONT])
    depth(monkeypatch, cell, top_mm=30.0)
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:pinky")
    free = result["free_source"]
    assert result["result"] == "planned" and free["site"] == "free:pinky" and free["object"] == "container-2"
    assert free["top_z_m"] == pytest.approx(0.075, abs=1e-3) and free["frame_spread_mm"] < 0.1
    assert result["attempts"][0]["plan"]["pick"]["z"] == pytest.approx(0.060, abs=1e-3)  # what the site pick plans
    lower = Cell([CONT])
    depth(monkeypatch, lower, top_mm=5.0)  # the housing under the box is 25 mm lower than the anchor surface
    result = run(tmp_path, lower, clipped_config(tmp_path), "free:pinky")
    assert result["result"] == "planned"
    assert result["attempts"][0]["plan"]["pick"]["z"] == pytest.approx(0.035, abs=1.5e-3)
    assert result["free_source"]["top_above_anchor_mm"] == pytest.approx(5.0, abs=0.1)


def test_free_source_refuses_without_depth_and_never_guesses_z(tmp_path, monkeypatch):
    cell = Cell([CONT])
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: (None, "depth device missing"))
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:pinky")
    assert result["result"].startswith("refused: free source needs depth") and "attempts" not in result
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: (np.zeros((3, 480, 640), np.uint16), {}))
    monkeypatch.setattr(cfs, "_frame_heights", lambda *a: (None, None, ["missing_depth"], None))
    assert "depth unavailable" in run(tmp_path, cell, clipped_config(tmp_path), "free:pinky")["result"]


def test_free_source_refuses_noisy_depth_and_a_disagreeing_anchor_with_the_numbers(tmp_path, monkeypatch):
    cell = Cell([CONT])
    depth(monkeypatch, cell, per_frame=[10, 30, 5, 35, 20, 40, 15])
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:pinky")
    assert "depth frames disagree" in result["result"] and result["free_source"]["frame_spread_mm"] > cfs.FRAME_SPREAD_MM
    depth(monkeypatch, cell, top_mm=30.0, cam_off_mm=20.0)
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:pinky")
    assert "anchor surface_z disagrees" in result["result"] and result["free_source"]["anchor_ref_diff_mm"] == pytest.approx(20.0, abs=0.5)


def test_free_source_refuses_a_blob_that_matches_no_catalogue_entry(tmp_path, monkeypatch):
    cell = Cell([{"x": 0.072, "y": 0.120, "long": 0.0, "length": 20, "width": 14}])
    depth(monkeypatch, cell)
    assert "no catalogue match" in run(tmp_path, cell, clipped_config(tmp_path), "free:pinky")["result"]


def test_free_source_needs_a_flat_fixed_anchor(tmp_path, monkeypatch):
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    config = clipped_config(tmp_path)
    config["sites"]["pinky"]["track"] = True
    assert "not a fixed flat site" in run(tmp_path, cell, config, "free:pinky")["result"]
    assert "not a site in the config" in run(tmp_path, cell, clipped_config(tmp_path), "free:nowhere")["result"]


def test_job_spec_and_cli_carry_the_free_source_and_pixel(tmp_path):
    import cell_auto_setup as setup
    import cell_job_spec as spec

    for name in ("cell-arm-a-policy.json", "catalog-test.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    base = {"config": "cell-arm-a-policy.json", "catalog": "catalog-test.json", "roi": [340, 40, 470, 180], "source": "free:pallet", "dest": "pallet"}
    argv = spec.build_argv(spec.JOBS["auto_pick_dry_run"], {**base, "at_px": "402,108"}, tmp_path)
    assert argv[argv.index("--from") + 1] == "free:pallet" and argv[argv.index("--at-px") + 1] == "402,108"
    with pytest.raises(ValueError):
        spec.build_argv(spec.JOBS["auto_pick_dry_run"], {**base, "at_px": "402;108"}, tmp_path)
    with pytest.raises(ValueError):
        spec.build_argv(spec.JOBS["auto_pick_dry_run"], {**base, "source": "free:"}, tmp_path)
    args = setup.pick_parser("doc").parse_args(["--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "1", "1", "--dest", "pallet",
                                                "--from", "free:pallet", "--at-px", "402,108", "--dry-run"])
    setup.validate_pick_args(args)
    args.source = "pallet"
    with pytest.raises(SystemExit, match="--at-px"):
        setup.validate_pick_args(args)
