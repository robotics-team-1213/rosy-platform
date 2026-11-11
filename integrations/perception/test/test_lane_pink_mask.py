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
