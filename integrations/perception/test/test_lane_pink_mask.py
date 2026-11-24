"""D-1013 pink paint source: the magenta guide-tape mask and what must stay out."""

import numpy as np

from perception_runtime.perception.lane_keep_lines import floor_pink_mask, floor_white_mask

H, W = 240, 320
#: The 261026 world's pink diffuse (0.95, 0.15, 0.85 RGB) as rendered BGR.
PINK = (217, 38, 242)
WHITE = (235, 235, 235)   # lane paint stays desaturated
BLUE = (200, 60, 20)      # wall seam tape (H ~120)
SHADOW_PINK = (109, 19, 121)  # the same tape at half brightness


def frame_with(stripe_bgr, column=160, half=8):
    rng = np.random.RandomState(7)
    img = np.clip(105 + rng.normal(0, 6, (H, W, 3)), 0, 255).astype(np.uint8)
    img[:, column - half:column + half] = stripe_bgr
    return img


def test_pink_tape_is_masked_below_the_horizon():
    mask = floor_pink_mask(frame_with(PINK), horizon_row=60.0)
    assert mask[100, 160] == 1
    assert mask[100, 60] == 0
    # The cut is ceil(horizon) + 3 px margin (rows before 63), as in the
    # white mask; the first kept row is 63 itself.
    assert mask[:63, 160].sum() == 0
    assert mask[63, 160] == 1


def test_white_lane_paint_and_blue_tape_stay_out():
    assert floor_pink_mask(frame_with(WHITE), 60.0)[100, 160] == 0
    assert floor_pink_mask(frame_with(BLUE), 60.0)[100, 160] == 0


def test_shadowed_tape_stays_in():
    # A shadow drops V only; the HSV gate keeps the line while brightness
    # thresholds would lose it (the D-1013 reason for a colour source).
    assert floor_pink_mask(frame_with(SHADOW_PINK), 60.0)[100, 160] == 1


def test_white_mask_ignores_the_pink_tape():
    # Both paint kinds can share one frame: the white path rejects saturated
    # pink (MAX_SATURATION), the pink path rejects desaturated white.
    assert floor_white_mask(frame_with(PINK), 60.0)[100, 160] == 0


def test_specks_are_dropped():
    img = frame_with((20, 20, 20))
    img[150:152, 40:42] = PINK      # 4 px < DENOISE_MIN_AREA_PX
    assert floor_pink_mask(img, 60.0)[150:152, 40:42].sum() == 0


#: The real parking-mat tape as rosy_42's front camera saw it on 2026-11-14 (median H 173 S 75 V 208,
#: and its pale tenth, H 170 S 49): far paler than the sim's diffuse. The old H <= 170, S >= 80 gate
#: caught 0 % of it and the white mask took 72 %, so the bay line read as lane paint.
REAL_PINK = (161, 147, 208)
PALE_PINK = (170, 158, 195)
ORANGE = (50, 110, 230)  # the containers (H ~10)


def test_the_real_pale_tape_is_pink_and_not_white_lane_paint():
    for tape in (REAL_PINK, PALE_PINK):
        assert floor_pink_mask(frame_with(tape), 60.0)[100, 160] == 1
        assert floor_white_mask(frame_with(tape), 60.0)[100, 160] == 0


def test_orange_containers_stay_out_of_the_pink_mask():
    assert floor_pink_mask(frame_with(ORANGE), 60.0)[100, 160] == 0


def test_the_robot_s_accepted_floor_paint_record_is_its_gate(tmp_path, monkeypatch):
    from core_common.calibration_store import CalibrationStore
    from perception_runtime.perception import lane_keep_lines as lk

    store = CalibrationStore(tmp_path)
    rid = store.add("rosy-pinky-test", "floor_paint", {"pink_h_low": 165, "pink_h_high": 179,
                    "pink_min_saturation": 30, "pink_min_value": 70}, method="test/1")
    store.set_status("rosy-pinky-test", "floor_paint", rid, "accepted", actor="test")
    monkeypatch.setenv("ROSY_CALIBRATION_ROOT", str(tmp_path))
    monkeypatch.setenv("ROSY_CALIBRATION_ROBOT", "rosy-pinky-test")
    monkeypatch.setattr(lk, "_PINK_GATE", None)
    assert lk.pink_gate() == ((165, 30, 70), (179, 255, 255))
    assert floor_pink_mask(frame_with(REAL_PINK), 60.0)[100, 160] == 1
    assert floor_pink_mask(frame_with(PINK), 60.0)[100, 160] == 0  # H 154 is outside this robot's measured band
    monkeypatch.setattr(lk, "_PINK_GATE", None)


def _reference_full_frame_white_mask(bgr: np.ndarray, horizon_row: float) -> np.ndarray:
    import cv2
    import math
    from perception_runtime.perception import lane_keep_lines as lk

    if bgr.ndim == 2:
        value, saturation = bgr, np.zeros_like(bgr)
    else:
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        value, saturation = hsv[..., 2], hsv[..., 1]
    height, width = value.shape
    top = max(0, min(height, int(math.ceil(horizon_row)) + lk.HORIZON_MARGIN_PX))
    mask = np.zeros((height, width), np.uint8)
    if top >= height:
        return mask
    floor = value[top:].astype(np.float32)
    ref = lk._median_filter_1d(np.percentile(floor, lk.CARPET_PERCENTILE, axis=1), lk.CARPET_ROW_WINDOW)
    ref = np.minimum(ref, float(np.median(floor)) + lk.CARPET_ROW_EXCESS)
    thresh = ref + np.maximum(lk.MIN_CONTRAST, lk.CONTRAST_HEADROOM * (255.0 - ref))
    coloured = saturation[top:] > lk.MAX_SATURATION
    if bgr.ndim == 3:
        coloured |= lk._pink(hsv[top:])
    coloured = cv2.dilate(coloured.astype(np.uint8), np.ones((5, 5), np.uint8))
    mask[top:] = (floor >= thresh[:, None]) & (coloured == 0)
    start = max(0, int(math.floor(horizon_row)) - lk.WALL_START_ABOVE_HORIZON_PX)
    if start < height:
        carpet = float(np.percentile(floor, lk.WALL_CARPET_PERCENTILE))
        w_thresh = min(float(np.median(thresh[:max(1, len(thresh) // 4)])),
                       carpet + max(lk.MIN_CONTRAST, lk.CONTRAST_HEADROOM * (255.0 - carpet)))
        bright = value[start:] >= w_thresh
        smooth = cv2.blur(value, (3, 3)).astype(np.int16)[start:]
        step = np.zeros_like(bright)
        step[lk.WALL_STEP_ROWS:] = (smooth[:-lk.WALL_STEP_ROWS] - smooth[lk.WALL_STEP_ROWS:]) > lk.WALL_TAPE_STEP
        base = lk._median_filter_1d(start + np.cumprod(bright & ~step, axis=0).sum(axis=0), lk.WALL_MEDIAN_COLUMNS)
        mask[np.arange(height)[:, None] < (base[None, :] + lk.WALL_BASE_MARGIN_PX)] = 0
    return mask


def test_floor_white_mask_slice_matches_full_frame_reference_across_horizons():
    img = frame_with(WHITE)
    img[:90, :] = (245, 245, 245)  # bright wall above/crossing the horizon
    gray = img[:, :, 0].copy()
    for horizon in (-10.0, 0.0, 4.0, 80.0, 120.0, 238.0, 300.0):
        assert np.array_equal(floor_white_mask(img, horizon), _reference_full_frame_white_mask(img, horizon))
        assert np.array_equal(floor_white_mask(gray, horizon), _reference_full_frame_white_mask(gray, horizon))


def _reference_denoise_white_mask(bgr: np.ndarray, horizon_row: float) -> np.ndarray:
    import cv2
    from perception_runtime.perception import lane_keep_lines as lk

    img = cv2.medianBlur(bgr, lk.DENOISE_MEDIAN_PX) if lk.DENOISE_MEDIAN_PX > 1 else bgr
    mask = _reference_full_frame_white_mask(img, horizon_row).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (lk.DENOISE_OPEN_PX, lk.DENOISE_OPEN_PX))
    return lk.drop_small_components(cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel))


def test_denoise_white_mask_slice_matches_full_frame_reference_across_horizons():
    from perception_runtime.perception.lane_keep_lines import denoise_white_mask

    img = frame_with(WHITE)
    img[:90, :] = (245, 245, 245)
    img[140:200, 30:45] = WHITE
    for horizon in (-10.0, 0.0, 4.0, 80.0, 120.0, 238.0, 300.0):
        assert np.array_equal(denoise_white_mask(img, horizon), _reference_denoise_white_mask(img, horizon))
