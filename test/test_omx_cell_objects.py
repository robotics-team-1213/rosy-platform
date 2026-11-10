"""Catalogue-driven objects in the top view (cell_objects): synthetic scenes drawn in arm millimetres, seen
through a parallax-carrying camera, so the measured sizes, splits and vetoes are checked against known truth."""
import json
import math
from pathlib import Path
import sys

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_calibration as cal
    import cell_objects as co
finally:
    sys.path.remove(str(OMX))

CATALOG = co.load_catalog(OMX / "object-catalog.example.json")
CAMERA = {"height_m": 0.5, "center_px": [320, 240]}
RECORD = {"homography": [[5e-4, 0, -0.16], [0, 5e-4, -0.12], [0, 0, 1]], "z_view": 0.0}  # 2 px/mm at z_view
ROI = (60, 60, 580, 420)
TOP = 0.030  # container top above the surface


def scene(rects, colour=(60, 160, 60), surface=(200, 200, 200), patches=()):
    """rects: (cx_mm, cy_mm, length_mm, width_mm, angle_deg) with their tops at TOP; patches: flat (rect, bgr)."""
    img = np.full((480, 640, 3), surface, np.uint8)

    def draw(r, bgr, z):
        cx, cy, length, width, ang = r
        pts = cv2.boxPoints(((cx, cy), (length, width), ang))
        px = [cal.parallax((320 + 2 * x, 240 + 2 * y), 0.0, z, CAMERA) for x, y in pts]
        cv2.fillPoly(img, [np.round(px).astype(np.int32)], bgr)

    for r, bgr in patches:
        draw(r, bgr, 0.0)
    for r in rects:
        draw(r, colour, TOP)
    return img


def seen(img):
    return co.detect(img, ROI, RECORD, CAMERA, CATALOG)


def angle_gap(a, b):
    return abs((a - b + 90) % 180 - 90)


@pytest.mark.parametrize("cells", [1, 2, 3])
@pytest.mark.parametrize("angle", [0, 30, -40])
def test_single_object_measured(cells, angle):
    (o,) = seen(scene([(20, -10, 30 * cells, 30, angle)]))
    assert o["matched"] and o["object"] == f"container-{cells}"
    assert o["centre_mm"] == pytest.approx([20, -10], abs=1.5)
    assert o["length_mm"] == pytest.approx(30 * cells, abs=2) and o["width_mm"] == pytest.approx(30, abs=2)
    if cells > 1:
        assert angle_gap(o["long_axis_deg"], angle) < 3


def test_touching_pair_is_split():
    # a 2-cell and a 3-cell container side by side, as seen on the real camera on 2026-10-28
    found = seen(scene([(-30, 0, 60, 30, 0), (-15, 31, 90, 30, 0)]))
    assert sorted(o["object"] for o in found) == ["container-2", "container-3"]
    assert all(o["split_from"] == 2 and o["matched"] for o in found)


def test_three_side_by_side_rotated():
    u = math.radians(25)
    rects = [(40 + k * 30 * -math.sin(u), 20 + k * 30 * math.cos(u), 90, 30, 25) for k in (-1, 0, 1)]
    found = seen(scene(rects))
    assert [o["object"] for o in found] == ["container-3"] * 3
    assert all(o["split_from"] == 3 for o in found)


def test_non_catalogue_blob_is_never_a_target():
    found = seen(scene([(0, 0, 45, 45, 10), (80, 60, 52, 52, 0)]))  # no side faces drawn here, so the edge piece is shrunk
    assert found and not any(o["matched"] or o["grasp"] for o in found)


def test_a_container_read_short_still_matches_its_cell_count_but_never_a_neighbour():
    # the real top camera read the isolated 60 x 30 container as 47 x 34 mm after the top-face cut (2026-10-28)
    assert co.match({"length_mm": 47.0, "width_mm": 34.0}, CATALOG)["id"] == "container-2"
    assert co.match({"length_mm": 98.0, "width_mm": 32.0}, CATALOG)["id"] == "container-3"
    assert co.match({"length_mm": 45.0, "width_mm": 30.0}, CATALOG) is None  # half way between 1 and 2 cells
    assert co.match({"length_mm": 47.0, "width_mm": 34.0}, CATALOG, strict=True) is None  # a split piece stays strict
    assert co.match({"length_mm": 60.0, "width_mm": 40.0}, CATALOG) is None  # the width stays strict


def test_small_fragment_is_unmatched():
    (o,) = seen(scene([(0, 0, 22, 13, 0)]))
    assert not o["matched"]


def test_black_object_on_light_surface():
    (o,) = seen(scene([(10, 10, 60, 30, 15)], colour=(15, 15, 15)))
    assert o["matched"] and o["object"] == "container-2"


def test_shadow_is_not_an_object():
    assert seen(scene([], patches=[((0, 0, 70, 40, 20), (150, 150, 150))])) == []


def test_a_1_cell_and_a_2_cell_touching_at_a_corner_are_found_as_two_targets():
    """2026-10-29 floor: corner to corner they made one unmatched blob that no push could part."""
    img = scene([(-60, 0, 30, 30, 0), (-25.5, 32.5, 60, 30, 45)])
    alone = co.detect(img, ROI, RECORD, CAMERA, CATALOG, params={"objects.split_touching": 0})
    assert len(alone) == 1 and not alone[0]["matched"]
    found = sorted(seen(img), key=lambda o: o["object"] or "")
    assert [o["object"] for o in found] == ["container-1", "container-2"]
    assert all(o["matched"] and o.get("split_from") == "touching" and o["hull_px"] for o in found)
    assert found[0]["centre_mm"] == pytest.approx([-60, 0], abs=3) and found[1]["centre_mm"] == pytest.approx([-25.5, 32.5], abs=3)


def test_a_split_piece_that_matches_is_a_target_while_its_unmatched_neighbour_stays_an_obstacle():
    img = scene([(-60, 0, 30, 30, 0), (-22, 37, 75, 44, 45)])  # the neighbour reads too wide for any catalogue entry
    found = sorted(seen(img), key=lambda o: o["matched"], reverse=True)
    assert len(found) == 2 and found[0]["object"] == "container-1" and found[0]["matched"]
    assert not found[1]["matched"] and found[1]["hull_px"]  # side_clear sees it


def test_a_box_shadow_on_the_yellow_board_is_dropped_but_a_black_plate_stays():
    """2026-10-29: the dark-yellow shadow beside a box on the board read as a fragment and closed the finger gap."""
    yellow, shade, black = (60, 190, 230), (30, 100, 125), (25, 25, 25)
    img = scene([(0, 0, 60, 30, 20)], surface=yellow,
                patches=[((10, 22, 60, 16, 20), shade), ((-90, -70, 90, 70, 0), black)])
    found = seen(img)
    assert [o["object"] for o in found if o["matched"]] == ["container-2"], [(o["object"], o["centre_mm"], o["length_mm"], o["width_mm"]) for o in found]
    assert not any(not o["matched"] and abs(o["centre_mm"][1] - 22) < 8 for o in found)  # no shadow fragment
    mask = co.foreground(img, ROI)
    bx, by = 320 + 2 * -90 - ROI[0], 240 + 2 * -70 - ROI[1]
    assert mask[by, bx] > 0  # the black plate is still foreground: an obstacle for the fingers


def test_objects_found_by_their_own_colour_ignore_the_board_its_shadow_and_a_white_line():
    yellow, shade, white = (60, 190, 230), (30, 100, 125), (235, 235, 235)
    img = scene([(0, 0, 60, 30, 20)], surface=yellow,
                patches=[((10, 22, 60, 16, 20), shade), ((-40, 0, 14, 160, 0), white)])
    found = co.detect(img, ROI, RECORD, CAMERA, CATALOG, object_hsv=[[50, 80, 50], [95, 255, 255]])
    assert [(o["object"], o["matched"]) for o in found] == [("container-2", True)]
    assert found[0]["centre_mm"] == pytest.approx([0, 0], abs=2)


def test_a_darker_side_face_of_the_same_green_is_left_out_by_relative_lightness():
    """Night 2026-10-29: the top camera at its exposure cap; a 2-cell's top and side merged to 58 x 51 mm."""
    top, side = (60, 170, 60), (40, 115, 40)  # the side about 0.68 of the top's lightness
    img = scene([(0, 0, 60, 30, 0)], colour=top, patches=[((0, 21, 60, 12, 0), side)])
    hsv = [[50, 80, 50], [95, 255, 255]]
    merged = co.detect(img, ROI, RECORD, CAMERA, CATALOG, params={"objects.top_v_frac": 0, "objects.side_retry_v_frac": 0}, object_hsv=hsv)
    tops = co.detect(img, ROI, RECORD, CAMERA, CATALOG, params={"objects.top_v_frac": 0.8}, object_hsv=hsv)
    assert merged[0]["width_mm"] > 36 and tops[0]["object"] == "container-2" and tops[0]["width_mm"] == pytest.approx(30, abs=3)


def test_with_top_v_frac_off_an_unmatched_blob_is_measured_again_on_its_top_face():
    """2026-10-30: top_v_frac 0 on the site; a 2-cell across the Pinky tray read 56 x 41.5 mm with its side face."""
    top, side = (60, 200, 60), (35, 105, 35)  # the side about 0.52 of the top's lightness, as measured
    img = scene([(0, -40, 60, 30, 0)], colour=top, patches=[((0, -21, 60, 14, 0), side)])
    hsv = [[50, 80, 25], [95, 255, 255]]
    off = co.detect(img, ROI, RECORD, CAMERA, CATALOG, params={"objects.top_v_frac": 0, "objects.side_retry_v_frac": 0}, object_hsv=hsv)
    (o,) = co.detect(img, ROI, RECORD, CAMERA, CATALOG, params={"objects.top_v_frac": 0}, object_hsv=hsv)
    assert not off[0]["matched"] and off[0]["width_mm"] > 39
    assert o["object"] == "container-2" and o["width_mm"] == pytest.approx(30, abs=3) and o["top_retry"] == 0.75
    assert o["centre_mm"] == pytest.approx([0, -40], abs=2)
    hull = np.asarray(o["hull_px"])
    assert hull[:, 1].max() > 240 - 2 * 25  # the outline still takes in the side face, toward the centre


def test_a_blob_that_matches_is_never_measured_again():
    hsv = [[50, 80, 25], [95, 255, 255]]
    (o,) = co.detect(scene([(20, -10, 60, 30, 30)]), ROI, RECORD, CAMERA, CATALOG, params={"objects.top_v_frac": 0}, object_hsv=hsv)
    assert o["matched"] and "top_retry" not in o


def test_an_objects_outline_takes_in_the_side_faces_the_camera_sees():
    """Top-face detection left a box's own side face out of its outline, and the finger check called it a neighbour."""
    px = np.array([[100.0, 100.0], [140.0, 100.0], [140.0, 130.0], [100.0, 130.0]])  # a top face up and left of the centre
    hull = co.outline(px, [{"object": "container-1"}], CATALOG, CAMERA, 0.0)
    assert cv2.contourArea(hull.astype(np.float32)) > cv2.contourArea(px.astype(np.float32))
    assert hull[:, 0].max() > 140 and hull[:, 1].max() > 130  # extended toward the principal point (320, 240)


@pytest.mark.parametrize("gap", [0.0, 6.0])
def test_five_3_cells_in_a_row_on_the_ship_plate_are_five_targets(gap):
    """2026-11-03 arm_b: five 3-cells laid side by side in the plate's 6 mm cell gaps read as one blob, no match."""
    pitch = 30 + gap
    mm = np.array([(x, k * pitch + y) for k in range(5) for x in np.arange(-45, 45.5, 1.0) for y in np.arange(0, 30.5, 1.0)],
                  np.float32)
    found = co.classify(mm, CATALOG)
    assert [o["object"] for o in found] == ["container-3"] * 5 and all(o["split_from"] == 5 for o in found)
    assert sorted(round(o["centre_mm"][1]) for o in found) == [round(k * pitch + 15) for k in range(5)]


def test_a_row_wider_than_its_gaps_allow_stays_unmatched():
    mm = np.array([(x, y) for x in np.arange(-45, 45.5, 1.0) for y in np.arange(0, 260.5, 1.0)], np.float32)
    assert not any(o["matched"] for o in co.classify(mm, CATALOG))  # 260 mm: past six widths and five 8 mm gaps


def test_a_row_with_one_box_pushed_along_is_still_four_targets():
    """2026-11-03: a row put back by hand, the first box 16 mm along from the others: the blob was 16 mm too long."""
    mm = np.array([(x, k * 36 + y) for k in range(4) for x in np.arange(-45 + (16 if k == 0 else 0), 45.5 + (16 if k == 0 else 0), 1.0)
                   for y in np.arange(0, 30.5, 1.0)], np.float32)
    found = co.classify(mm, CATALOG)
    assert [o["object"] for o in found] == ["container-3"] * 4
    assert sorted(round(o["centre_mm"][0]) for o in found) == [0, 0, 0, 16]


def test_three_3_cells_in_a_row_longer_than_one_box_are_split_along_the_row():
    """2026-11-03: three 3-cells with 6 mm gaps read 113 x 100 mm, the row longer than a box (90)."""
    mm = np.array([(k * 36 + x, y) for k in range(3) for x in np.arange(0, 30.5, 1.0) for y in np.arange(-45, 45.5, 1.0)],
                  np.float32)
    found = co.classify(mm, CATALOG)
    assert [o["object"] for o in found] == ["container-3"] * 3
    assert sorted(round(o["centre_mm"][0]) for o in found) == [15, 51, 87]


@pytest.mark.parametrize(("bgr", "expected"), [
    ((30, 120, 235), "orange"),
    ((25, 220, 240), "yellow"),
    ((60, 170, 60), "green"),
    ((210, 110, 40), "blue"),
    ((180, 50, 160), "purple"),
    ((35, 35, 220), "red"),
    ((15, 15, 15), "black"),
])
def test_diverse_container_colours_are_tagged(bgr, expected):
    (o,) = seen(scene([(10, -5, 60, 30, 0)], colour=bgr))
    assert o["matched"] and o["object"] == "container-2" and o["colour"] == expected


def test_split_strips_keep_each_containers_own_colour_and_want_filter_selects_target():
    img = scene([(-30, 0, 60, 30, 0)], colour=(30, 120, 235))  # orange container-2
    pts = cv2.boxPoints(((-15, 31), (90, 30), 0))
    px = [cal.parallax((320 + 2 * x, 240 + 2 * y), 0.0, TOP, CAMERA) for x, y in pts]
    cv2.fillPoly(img, [np.round(px).astype(np.int32)], (25, 220, 240))  # touching yellow container-3
    found = sorted(seen(img), key=lambda o: o["object"])
    assert [(o["object"], o["colour"]) for o in found] == [("container-2", "orange"), ("container-3", "yellow")]
    assert co.want_reason({"colour": "yellow"}, found[0]) == "wanted colour yellow, got orange"
    assert co.want_reason({"colour": "yellow", "object": "container-3"}, found[1]) is None
    assert co.want_reason({"object": "container-2"}, found[1]) == "wanted object container-2, got container-3"


def test_enroll_measures_and_saves_a_custom_object_for_detection(tmp_path):
    img = scene([(15, -20, 48, 42, 10)], colour=(210, 110, 40))  # 48x42 mm blue non-standard cargo block
    assert not any(o["matched"] for o in seen(img))  # unmatched before enrollment
    cat_path = tmp_path / "catalog.json"
    cat_path.write_text(Path(OMX / "object-catalog.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    entry = co.enroll(img, ROI, RECORD, CAMERA, "cargo-drum", top_height_mm=30.0, mass_kg=0.024)
    assert entry["id"] == "cargo-drum" and entry["colour"] == "blue" and entry["mass_kg"] == 0.024
    assert entry["length_mm"] == pytest.approx(48, abs=2.5) and entry["width_mm"] == pytest.approx(42, abs=2.5)
    updated = co.save_catalog_entry(cat_path, entry)
    (o,) = co.detect(img, ROI, RECORD, CAMERA, updated)
    assert o["matched"] and o["object"] == "cargo-drum" and o["colour"] == "blue"
    # A colour-constrained catalogue entry does not match an orange block of the same size
    orange_img = scene([(15, -20, 48, 42, 10)], colour=(30, 120, 235))
    (mismatch,) = co.detect(orange_img, ROI, RECORD, CAMERA, updated)
    assert not mismatch["matched"] and mismatch["colour"] == "orange"


def test_auto_pick_choose_filters_by_wanted_colour_and_object_id(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(OMX))
    import cell_auto_pick as auto
    import cell_auto_setup as setup
    import cell_choices

    args = setup.parser("test").parse_args(["--config", "c.json", "--catalog", "cat.json", "--roi", "60", "60", "580", "420",
                                            "--dest", "belt", "--object", "container-2", "--colour", "yellow", "--dry-run"])
    assert args.want_object == "container-2" and args.want_colour == "yellow"
    img = scene([(-40, 0, 30, 30, 0)], colour=(60, 170, 60))  # green container-1 (nearer start)
    pts = cv2.boxPoints(((30, 0), (60, 30), 0))
    px = [cal.parallax((320 + 2 * x, 240 + 2 * y), 0.0, TOP, CAMERA) for x, y in pts]
    cv2.fillPoly(img, [np.round(px).astype(np.int32)], (25, 220, 240))  # yellow container-2
    objs = co.detect(img, ROI, RECORD, CAMERA, CATALOG)
    for o in objs:
        o["raw_m"] = [c / 1000 for c in o["centre_mm"]]
    # With want={"colour": "yellow", "object": "container-2"}, green container-1 is refused and yellow container-2 is kept
    reasons = {o["object"]: co.want_reason({"colour": "yellow", "object": "container-2"}, o) for o in objs}
    assert reasons["container-1"] == "wanted object container-2, got container-1"
    assert reasons["container-2"] is None
    assert getattr(auto, "choose") is not None


def test_skewed_non_square_objects_at_varied_positions_are_picked_and_placed_sequentially(tmp_path, monkeypatch):
    """Non-square 2-cell (60x30), 3-cell (90x30), and custom (48x30) objects at different positions and skewed angles
    are detected by colour/size, grasped across their tilted short axis, and placed at the destination."""
    monkeypatch.syspath_prepend(str(OMX))
    import test_omx_cell_auto_pick as ap_test
    from cell_robot_profile import load

    prof = tmp_path / "robot-profile.json"
    prof.write_text(json.dumps({"schema": "rosy.omx-cell-robot-profile.v1", "device_id": "sim-device",
        "instance_id": "sim-arm", "robot_config_sha256": "c" * 64,
        "operating_envelope_path": "review.json", "work_dir": "."}))
    monkeypatch.setitem(ap_test.CONFIG, "operating_profile_path", str(prof))
    monkeypatch.setitem(ap_test.CONFIG, "work_dir", str(tmp_path))
    monkeypatch.setitem(ap_test.CONFIG, "operating_envelope_path", str(tmp_path / "review.json"))
    monkeypatch.setitem(ap_test.SESSION, "operating_profile", load(prof)["binding"])

    class MultiColourCell(ap_test.Cell):
        def frame(self, camera):
            img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
            img[40:200, 150:510] = (90, 70, 55)
            for o in self.objects:
                if o is not self.held:
                    ap_test.draw(img, o, colour=o.get("bgr", (60, 160, 60)))
            return img

    path = ap_test.biased_map(tmp_path)
    # Pre-save the map bias so each carry plans and executes directly
    ap_test.cell_pivot.save_bias(ap_test.cell_pivot.bias_path(path), {
        "site": "pinky", "point_m": [0.072, 0.105], "bias_mm": [1000 * ap_test.BIAS[0], 1000 * ap_test.BIAS[1]],
        "radius_mm": 18.8, "phase_deg": 53.0, "rms_mm": 0.4, "n": 6,
    })
    catalog = [dict(e, mass_kg=0.03) for e in CATALOG] + [{
        "id": "cargo-box", "kind": "blue custom box", "length_mm": 48, "width_mm": 30, "top_height_mm": 30,
        "tolerance_mm": 8, "length_tolerance_mm": 8, "colour": "blue", "mass_kg": 0.025,
        "grasp": {"close_across": "short_side", "jaw_axis_deg_from_long": 90},
    }]
    choices = ap_test.cell_choices.Choices(tmp_path / "choices.json")
    scenarios = [
        ({"x": 0.078, "y": 0.124, "long": 28.0, "length": 60, "width": 30, "bgr": (25, 220, 240)}, "yellow", "container-2", "0.060,0.088"),
        ({"x": 0.070, "y": 0.120, "long": -22.0, "length": 90, "width": 30, "bgr": (30, 120, 235)}, "orange", "container-3", "0.060,0.090"),
        ({"x": 0.074, "y": 0.118, "long": 18.0, "length": 48, "width": 30, "bgr": (210, 110, 40)}, "blue", "cargo-box", "0.058,0.092"),
    ]
    for item, want_col, want_id, dest_xy in scenarios:
        # Place a distractor object of another colour/size alongside the target so want-filtering + finger room both act
        distractor = {"x": -0.015, "y": 0.145, "long": -12.0, "length": 30, "width": 30, "bgr": (60, 170, 60)}
        cell = MultiColourCell([distractor, item], true_closing=90.0)
        cfg = {**ap_test.CONFIG, "want": {"colour": want_col, "object": want_id}}
        res = ap_test.auto.run_auto(cell, cfg, cal.load(path), path, catalog, ap_test.ROI, "pinky", dest_xy,
                                    tmp_path, choices, sleep=ap_test.no_sleep, log=lambda row: None)
        assert res["result"] == "placed", f"{want_id} ({want_col}) failed: {res}"
        attempt = res["attempts"][-1]
        assert attempt["chosen"]["object"] == want_id and attempt["chosen"]["colour"] == want_col
        assert angle_gap(attempt["long_axis_deg"], item["long"]) < 4.0
        tx, ty = (float(v) for v in dest_xy.split(","))
        assert math.dist((cell.objects[1]["x"], cell.objects[1]["y"]), (tx, ty)) < 0.006




