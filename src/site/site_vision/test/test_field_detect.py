"""D-360 field proposal on synthetic images only (the repo is public; no lab photos)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from site_vision.field_detect import FieldProposal, detect_field, detect_field_jpeg

W, H = 1280, 720
# A 2:1 field seen at an angle: top edge shorter than the bottom edge.
QUAD = np.array([(380, 150), (930, 170), (1090, 600), (220, 580)], dtype=np.float64)


def _scene(quad=QUAD, *, wall=14, lanes=True, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    image = np.full((H, W, 3), (105, 108, 110), dtype=np.uint8)  # grey carpet
    pts = quad.astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(image, [pts], True, (238, 240, 242), wall, lineType=cv2.LINE_AA)
    if lanes:
        centre = quad.mean(axis=0).astype(int)
        cv2.circle(image, tuple(int(v) for v in centre), 90, (236, 238, 240), 8, cv2.LINE_AA)
        mid_top = ((quad[0] + quad[1]) / 2).astype(int)
        mid_bottom = ((quad[2] + quad[3]) / 2).astype(int)
        cv2.line(image, tuple(int(v) for v in mid_top), tuple(int(v) for v in mid_bottom),
                 (236, 238, 240), 6, cv2.LINE_AA)
    if noise:
        jitter = rng.normal(0, noise, image.shape)
        image = np.clip(image.astype(np.float64) + jitter, 0, 255).astype(np.uint8)
    return image


def _outer_corners(quad, wall):
    """The detector traces the wall's outer edge, which sits wall/2 outside the drawn line."""
    centroid = quad.mean(axis=0)
    out = []
    for i in range(4):
        prev, cur, nxt = quad[i - 1], quad[i], quad[(i + 1) % 4]
        # Offset both adjacent edges outward by wall/2 and intersect.
        def outward(a, b):
            d = (b - a) / np.hypot(*(b - a))
            n = np.array([d[1], -d[0]])
            if n @ (a - centroid) < 0:
                n = -n
            return a + n * wall / 2, d
        p1, d1 = outward(prev, cur)
        p2, d2 = outward(cur, nxt)
        t, _ = np.linalg.solve(np.array([d1, -d2]).T, p2 - p1)
        out.append(p1 + t * d1)
    return np.array(out)


def _assert_corners(proposal: FieldProposal, expected, tol):
    got = np.array(proposal.corners)
    assert got.shape == (4, 2)
    err = np.hypot(*(got - expected).T)
    assert np.all(err <= tol), (got.round(1).tolist(), expected.round(1).tolist(), err.round(2))


def test_perspective_quad_is_proposed_in_consistent_corner_order():
    result = detect_field(_scene())
    assert result.proposal is not None, result.reason
    _assert_corners(result.proposal, _outer_corners(QUAD, 14), tol=3.0)
    assert result.proposal.confidence >= 0.9
    assert result.proposal.shape == "rectangle"
    assert 1.5 < result.proposal.aspect_ratio < 2.5
    assert result.image_size == (W, H)
    assert result.elapsed_ms >= 0


def test_corner_order_is_stable_when_the_quad_is_listed_from_another_vertex():
    rolled = np.roll(QUAD, 2, axis=0)[::-1]
    result = detect_field(_scene(rolled))
    assert result.proposal is not None, result.reason
    _assert_corners(result.proposal, _outer_corners(QUAD, 14), tol=3.0)


def test_square_field_is_flagged_square():
    square = np.array([(440, 160), (840, 160), (840, 560), (440, 560)], dtype=np.float64)
    result = detect_field(_scene(square, lanes=False))
    assert result.proposal is not None, result.reason
    assert result.proposal.shape == "square"
    assert abs(result.proposal.aspect_ratio - 1.0) < 0.05


def test_sensor_noise_does_not_move_the_corners_much():
    result = detect_field(_scene(noise=18.0, seed=3))
    assert result.proposal is not None, result.reason
    _assert_corners(result.proposal, _outer_corners(QUAD, 14), tol=4.0)


def test_partial_occlusion_of_one_wall_still_proposes_with_lower_confidence():
    clean = detect_field(_scene()).proposal
    image = _scene()
    # A dark object (a person, a robot) covering a quarter of the bottom wall.
    cv2.rectangle(image, (520, 540), (760, 640), (30, 30, 30), -1)
    result = detect_field(image)
    assert result.proposal is not None, result.reason
    _assert_corners(result.proposal, _outer_corners(QUAD, 14), tol=4.0)
    assert result.proposal.confidence < clean.confidence


@pytest.mark.parametrize("kind", ["blank", "noise", "blobs", "clipped"])
def test_no_field_means_no_proposal(kind):
    rng = np.random.default_rng(7)
    if kind == "blank":
        image = np.full((H, W, 3), 110, dtype=np.uint8)
    elif kind == "noise":
        image = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
    elif kind == "blobs":
        image = np.full((H, W, 3), 110, dtype=np.uint8)
        for _ in range(12):
            x, y = int(rng.integers(40, W - 40)), int(rng.integers(40, H - 40))
            cv2.circle(image, (x, y), int(rng.integers(5, 25)), (240, 240, 240), -1)
    else:  # the field runs past the right edge of the frame
        clipped = np.array([(300, 120), (1400, 120), (1400, 620), (300, 620)], dtype=np.float64)
        image = _scene(clipped)
    result = detect_field(image)
    assert result.proposal is None
    assert result.reason and result.reason != "ok"


def test_jpeg_entry_point_and_payload_shape():
    ok, encoded = cv2.imencode(".jpg", _scene(), [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok
    result = detect_field_jpeg(encoded.tobytes())
    assert result.proposal is not None, result.reason
    payload = result.proposal.to_dict()
    assert set(payload) == {"corners", "corners_normalized", "confidence", "aspect_ratio", "shape"}
    assert len(payload["corners"]) == 4
    for u, v in payload["corners_normalized"]:
        assert 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0
    tl, tr, br, bl = payload["corners"]
    assert tl[0] < tr[0] and bl[0] < br[0] and tl[1] < bl[1] and tr[1] < br[1]


@pytest.mark.parametrize("bad", [b"", b"not a jpeg"])
def test_bad_jpeg_raises_value_error(bad):
    with pytest.raises(ValueError):
        detect_field_jpeg(bad)
