"""auto_pick --from free:<site> [--at-px U,V]: an object outside every site surface, its top height measured by depth."""
import copy

import pytest

import test_omx_cell_auto_pick as tpa
from test_omx_cell_auto_pick import CAMERA, CATALOG, CONFIG, ROI, Cell, auto, biased_map, cal, cell_choices, np, tray_pixel  # noqa: F401  autouse profile fixture
import cell_free_source as cfs
import cell_pivot
from cell_calibrate import learn_bias

CONT = {"x": 0.072, "y": 0.120, "long": 30.0, "length": 60, "width": 30}
SURFACE_Z, HEIGHT_M = 0.045, 0.65  # sites.pinky.surface_z and cameras.top.height_m of the example config


def clipped_config(tmp_path):
    """the plate site's surface polygon stops left of the container: a site pick sees nothing, as the red box beside the belt."""
    config = copy.deepcopy(CONFIG)
    config["sites"]["plate"] = dict(copy.deepcopy(config["sites"]["pinky"]), surface_px=[[160, 205], [300, 205], [300, 420], [160, 420]])
    config["sites"]["drop"] = copy.deepcopy(config["sites"]["pinky"])  # a destination site: a free source never places on its own invented site
    config["plan"]["limits"]["workspace_min_m"][2] = -0.10  # the arm cell's low zone, as an owner would authorise it
    return config


def depth(monkeypatch, cell, top_mm=30.0, per_frame=None, cam_off_mm=0.0, frames=7):
    """Heights as the D435 would give them: 0 on the plate's surface, top_mm over the container's pixels."""
    img = cell.frame("top")
    box = (img == (60, 160, 60)).all(axis=2)
    seen = iter(range(100))
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: (np.zeros((frames, 480, 640), np.uint16), {}))

    def heights(frame, colour, cam):
        h = np.zeros((480, 640))
        h[box] = per_frame[next(seen) % len(per_frame)] if per_frame else top_mm
        return h, np.eye(3), [], (HEIGHT_M - SURFACE_Z) * 1000.0 + cam_off_mm

    monkeypatch.setattr(cfs, "_frame_heights", heights)


def run(tmp_path, cell, config, source, dest="drop", at_px=None, roi=ROI, catalog=CATALOG, z_view=None, **kw):
    path = biased_map(tmp_path)
    data = cal.load(path)
    if z_view is not None:
        data["sites"]["pinky"]["z_view"] = z_view
    for name in config["sites"]:
        data["sites"].setdefault(name, data["sites"]["pinky"])
    config["_free_px"] = at_px
    return auto.run_auto(cell, config, data, path, catalog, roi, source, dest, tmp_path,
                         cell_choices.Choices(tmp_path / "choices.json"), dry_run=True, **kw)


def test_a_site_source_still_sees_nothing_outside_its_polygon(tmp_path):
    result = run(tmp_path, Cell([CONT]), clipped_config(tmp_path), "plate")
    assert result["result"].startswith("stopped") and "free_source" not in result


def test_free_source_finds_the_box_outside_the_polygon_and_plans_at_the_measured_z(tmp_path, monkeypatch):
    cell = Cell([CONT])
    depth(monkeypatch, cell, top_mm=30.0)
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:plate")
    free = result["free_source"]
    assert result["result"] == "planned" and free["site"] == "free:plate" and free["object"] == "container-2"
    assert free["top_z_m"] == pytest.approx(0.075, abs=1e-3) and free["frame_spread_mm"] < 0.1
    assert result["attempts"][0]["plan"]["pick"]["z"] == pytest.approx(0.060, abs=1e-3)  # what the site pick plans
    lower = Cell([CONT])
    depth(monkeypatch, lower, top_mm=5.0)  # the housing under the box is 25 mm lower than the anchor surface
    result = run(tmp_path, lower, clipped_config(tmp_path), "free:plate")
    assert result["result"] == "planned"
    assert result["attempts"][0]["plan"]["pick"]["z"] == pytest.approx(0.035, abs=1.5e-3)
    assert result["free_source"]["top_above_anchor_mm"] == pytest.approx(5.0, abs=0.1)


def test_free_source_refuses_without_depth_and_never_guesses_z(tmp_path, monkeypatch):
    cell = Cell([CONT])
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: (None, "depth device missing"))
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:plate")
    assert result["result"].startswith("refused: free source needs depth") and not result["attempts"]
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: (np.zeros((5, 480, 640), np.uint16), {}))
    monkeypatch.setattr(cfs, "_frame_heights", lambda *a: (None, None, ["missing_depth"], None))
    assert "depth unavailable" in run(tmp_path, cell, clipped_config(tmp_path), "free:plate")["result"]


def test_free_source_refuses_noisy_depth_and_a_disagreeing_anchor_with_the_numbers(tmp_path, monkeypatch):
    cell = Cell([CONT])
    depth(monkeypatch, cell, per_frame=[10, 30, 5, 35, 20, 40, 15])
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:plate")
    assert "depth frames disagree" in result["result"] and result["free_source"]["frame_spread_mm"] > cfs.FRAME_SPREAD_MM
    depth(monkeypatch, cell, top_mm=30.0, cam_off_mm=20.0)
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:plate")
    assert "anchor surface_z disagrees" in result["result"] and result["free_source"]["anchor_ref_diff_mm"] == pytest.approx(20.0, abs=0.5)


def test_free_source_refuses_a_blob_that_matches_no_catalogue_entry(tmp_path, monkeypatch):
    cell = Cell([{"x": 0.072, "y": 0.120, "long": 0.0, "length": 20, "width": 14}])
    depth(monkeypatch, cell)
    assert "no catalogue match" in run(tmp_path, cell, clipped_config(tmp_path), "free:plate")["result"]


def test_free_source_needs_a_flat_fixed_anchor(tmp_path, monkeypatch):
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    config = clipped_config(tmp_path)
    config["sites"]["plate"]["track"] = True
    assert "not a fixed flat site" in run(tmp_path, cell, config, "free:plate")["result"]
    assert "not a site in the config" in run(tmp_path, cell, clipped_config(tmp_path), "free:nowhere")["result"]
    assert "not a fixed flat site" in run(tmp_path, cell, clipped_config(tmp_path), "free:pinky")["result"]  # a Pinky tray moves


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


NEIGHBOUR = {"x": 0.072 - 0.085, "y": 0.120, "long": 30.0, "length": 60, "width": 30}  # 76 px away: inside the tight ROI (blob + 25 px), its own blob
SMALL = {"x": 0.072 - 0.085, "y": 0.120, "long": 0.0, "length": 20, "width": 14}  # matches no catalogue entry
AT_BOX = (122, 240)  # tray_pixel(0.072, 0.120)


def refusal(tmp_path, cell, config=None, **kw):
    result = run(tmp_path, cell, config or clipped_config(tmp_path), "free:plate", **kw)
    assert result["result"].startswith("refused") and not result["attempts"], result["result"]
    return result["result"]


def test_free_source_refuses_when_another_catalogue_object_stands_in_the_tight_roi(tmp_path, monkeypatch):  # H1
    cell = Cell([CONT, NEIGHBOUR])
    depth(monkeypatch, cell)
    assert "not unique" in refusal(tmp_path, cell, at_px=AT_BOX)


def test_free_source_selects_only_the_measured_blob_and_keeps_the_callers_roi(tmp_path, monkeypatch):  # H1 + M4
    cell = Cell([CONT, SMALL])
    depth(monkeypatch, cell)
    config, path = clipped_config(tmp_path), biased_map(tmp_path)
    data = cal.load(path)
    data["sites"]["plate"] = data["sites"]["pinky"]
    config["_free_px"], out = AT_BOX, {}
    cfg, calib, roi, err = cfs.prepare(cell, config, data, "plate", ROI, CATALOG, out)
    assert err is None and tuple(roi) == tuple(ROI) and out["free_source"]["detect_roi"] != list(ROI)  # the guards keep the whole ROI
    assert cfg["_map_only"] is True
    _, _, objects, _ = auto.observe(cell, cfg, calib, "free:plate", roi, CATALOG)
    assert [o["object"] for o in objects] == ["container-2"]  # the small neighbour is not seen by the pick


def test_chosen_target_must_be_the_measured_blob_with_the_numbers(tmp_path):  # H1
    config = {"sites": {"free:plate": {"blob_px": [[100, 200], [160, 200], [160, 280], [100, 280]], "free_object": "container-2",
                                       "blob_centre_px": [130.0, 240.0]}}}
    inside = {"object": {"object": "container-2", "hull_px": [[110, 210], [150, 210], [150, 270], [110, 270]]}}
    assert cfs.chosen_error(config, "free:plate", inside) is None
    outside = {"object": {"object": "container-2", "hull_px": [[210, 210], [250, 210], [250, 270], [210, 270]]}}
    assert "not the measured blob" in cfs.chosen_error(config, "free:plate", outside) and "[230.0, 240.0]" in cfs.chosen_error(config, "free:plate", outside)
    other = {"object": {"object": "container-1", "hull_px": inside["object"]["hull_px"]}}
    assert "container-1" in cfs.chosen_error(config, "free:plate", other)


def test_free_source_is_one_attempt_whatever_the_caller_asks(tmp_path, monkeypatch):  # H2
    import builtins
    seen = []
    monkeypatch.setattr(auto, "range", lambda n: seen.append(n) or builtins.range(n), raising=False)
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    assert run(tmp_path, cell, clipped_config(tmp_path), "free:plate", attempts=5)["result"] == "planned"
    run(tmp_path, cell, clipped_config(tmp_path), "plate", attempts=5)
    assert seen == [1, 5]


def test_depth_frames_have_a_floor_and_a_range_gate(tmp_path, monkeypatch):  # H3
    cell = Cell([CONT])
    asked = []
    depth(monkeypatch, cell)
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: asked.append(n) or (np.zeros((n, 480, 640), np.uint16), {}))
    config = clipped_config(tmp_path)
    config["depth_frames"] = 1
    assert run(tmp_path, cell, config, "free:plate")["result"] == "planned" and asked == [cfs.MIN_FRAMES]
    monkeypatch.setattr(cfs, "_depth_frames", lambda config, n: (np.zeros((1, 480, 640), np.uint16), {}))
    assert "at least 5 needed" in refusal(tmp_path, cell)
    depth(monkeypatch, cell, per_frame=[4.5, -4.5] + [0.0] * 13, frames=15)  # spread 3.3 mm passes, range 9 mm does not
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:plate")
    assert "top height range" in result["result"] and result["free_source"]["frame_spread_mm"] < cfs.FRAME_SPREAD_MM


def test_nearest_site_must_agree_with_the_depth_too(tmp_path, monkeypatch):  # M5
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    config = clipped_config(tmp_path)
    config["sites"]["shelf"] = dict(copy.deepcopy(config["sites"]["pinky"]), surface_px=[[60, 272], [158, 272], [158, 330], [60, 330]], surface_z=0.060)
    result = run(tmp_path, cell, config, "free:plate")
    assert "shelf, nearest the object, disagrees" in result["result"] and result["free_source"]["nearest_ref_diff_mm"] == pytest.approx(15.0, abs=0.5)
    config["sites"]["shelf"]["surface_z"] = 0.045  # a configured value that agrees: the pick goes on
    assert run(tmp_path, cell, config, "free:plate")["result"] == "planned"


def test_two_heights_for_one_footprint_refuse(tmp_path, monkeypatch):  # M6
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    tall = [dict(e, id="container-2-tall", top_height_mm=40.0) for e in CATALOG if e["id"] == "container-2"]
    assert "not unique" in refusal(tmp_path, cell, catalog=[*CATALOG, *tall])


def test_free_name_never_reaches_a_bias_file(tmp_path):  # M7
    bias = {"site": "free:plate", "point_m": [0.07, 0.12], "bias_mm": [1.0, 1.0], "kind": "place_look"}
    with pytest.raises(ValueError, match="free source"):
        cell_pivot.save_bias(tmp_path / "bias.json", bias)
    verify = {"found": True, "seen_bias_mm": [1.0, 1.0], "used_bias_mm": [0.0, 0.0]}
    assert learn_bias(CONFIG, tmp_path / "cal.json", "free:plate", (0.07, 0.12), verify) is None
    assert not (tmp_path / "bias.json").exists() and not list(tmp_path.glob("*bias*"))


def test_layers_below_is_refused_for_a_free_source(tmp_path):  # F1
    import cell_auto_setup as setup
    import cell_job_spec as spec

    argv = ["--config", "c.json", "--catalog", "k.json", "--roi", "0", "0", "1", "1", "--dest", "pallet", "--from", "free:pallet", "--layers-below", "1", "--dry-run"]
    with pytest.raises(SystemExit, match="layers-below"):
        setup.validate_pick_args(setup.pick_parser("doc").parse_args(argv))
    for name in ("cell-arm-a-policy.json", "catalog-test.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    base = {"config": "cell-arm-a-policy.json", "catalog": "catalog-test.json", "roi": [340, 40, 470, 180], "source": "free:pallet", "dest": "pallet"}
    with pytest.raises(ValueError, match="layers_below"):
        spec.build_argv(spec.JOBS["auto_pick_dry_run"], {**base, "layers_below": 1}, tmp_path)
    assert spec.build_argv(spec.JOBS["auto_pick_dry_run"], {**base, "source": "pallet", "layers_below": 1}, tmp_path)


def test_at_px_far_outside_the_roi_is_refused(tmp_path, monkeypatch):  # F3
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    assert "no object within 25 px" in refusal(tmp_path, cell, at_px=(600, 100))


def test_free_source_refuses_an_xy_destination(tmp_path, monkeypatch):  # F4
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    assert "needs a destination site" in refusal(tmp_path, cell, dest="0.060,0.090")


def test_amr_bed_names_are_no_anchor(tmp_path, monkeypatch):  # F5
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    config = clipped_config(tmp_path)
    config["sites"]["tray"] = copy.deepcopy(config["sites"]["plate"])
    result = run(tmp_path, cell, config, "free:tray")
    assert "not a fixed flat site" in result["result"]


def test_several_blobs_need_a_pixel_and_a_cut_off_blob_is_refused(tmp_path, monkeypatch):  # L8
    cell = Cell([CONT, SMALL])
    depth(monkeypatch, cell)
    assert "no --at-px" in refusal(tmp_path, cell)
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    assert "touches the ROI border" in refusal(tmp_path, cell, roi=(110, 205, 300, 420))


def test_grasp_depth_of_the_anchor_is_kept(tmp_path, monkeypatch):  # L9
    cell = Cell([CONT])
    depth(monkeypatch, cell)
    config = clipped_config(tmp_path)
    config["sites"]["plate"]["grasp_depth_m"] = 0.020
    result = run(tmp_path, cell, config, "free:plate")
    assert result["result"] == "planned" and result["free_source"]["grasp_z_m"] == pytest.approx(0.055, abs=1e-3)
    assert result["attempts"][0]["plan"]["pick"]["z"] == pytest.approx(0.055, abs=1.5e-3)  # the planner reads it from the free site


def test_parallax_puts_a_low_box_at_its_true_xy(tmp_path, monkeypatch):
    """The map is fitted at z_view 0.075; a box whose top is 25 mm lower shows displaced by the parallax and must still read at its true place."""
    shown = lambda x, y: tuple(cal.parallax(tray_pixel(x, y), 0.075, 0.050, CAMERA))  # noqa: E731
    monkeypatch.setattr(tpa, "tray_pixel", shown)
    cell = Cell([CONT])
    depth(monkeypatch, cell, top_mm=5.0)
    result = run(tmp_path, cell, clipped_config(tmp_path), "free:plate", z_view=0.075)
    free = result["free_source"]
    assert result["result"] == "planned" and free["top_z_m"] == pytest.approx(0.050, abs=1e-3)
    assert free["centre_mm"] == pytest.approx([1000 * (CONT["x"] + tpa.BIAS[0]), 1000 * (CONT["y"] + tpa.BIAS[1])], abs=2.0)  # the map reads true + BIAS
    assert free["xy_from_height_error_mm"] > 0.3
