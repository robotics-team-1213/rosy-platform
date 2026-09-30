from __future__ import annotations

import cv2
import numpy as np
import pytest

from rosy_vision.rectify import PreviewRectification, rectify_jpeg


def _jpeg(width=320, height=240):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :width // 2] = (20, 40, 220)
    image[:, width // 2:] = (220, 40, 20)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def test_rectification_defaults_to_identity_without_changing_dimensions():
    raw = _jpeg()
    result = rectify_jpeg(raw, PreviewRectification())
    image = cv2.imdecode(np.frombuffer(result, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert result == raw
    assert image.shape == (240, 320, 3)


def test_rectification_warps_selected_quadrilateral_to_requested_square():
    profile = PreviewRectification(
        corners=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
        output_aspect=1.0,
    )
    result = rectify_jpeg(_jpeg(), profile)
    image = cv2.imdecode(np.frombuffer(result, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (256, 256)
    assert float(image[:, :128, 2].mean()) > float(image[:, 128:, 2].mean())


@pytest.mark.parametrize("corners", [
    ((0, 0), (1, 1), (1, 0), (0, 1)),
    ((0, 0), (1, 0), (1, 0), (0, 1)),
    ((-0.1, 0), (1, 0), (1, 1), (0, 1)),
])
def test_rectification_rejects_crossed_degenerate_and_out_of_range_corners(corners):
    with pytest.raises(ValueError):
        PreviewRectification(corners=corners)


def test_rectification_rejects_non_finite_and_unknown_lease_fields():
    with pytest.raises(ValueError):
        PreviewRectification(k1=float("nan"))
    with pytest.raises(ValueError, match="unknown"):
        PreviewRectification.from_mapping({"corners": [[0, 0]], "unbounded": True})


def test_rectification_rejects_invalid_jpeg_without_falling_back_to_raw_bytes():
    with pytest.raises(ValueError, match="decode"):
        rectify_jpeg(b"not-a-jpeg", PreviewRectification())
