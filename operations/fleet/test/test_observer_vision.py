"""Tier vision (observer_vision): synthetic orange blobs against the expected heights at a known distance."""
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
from fleet.server.sitemap import observer_vision as tv

CAM = {"hfov_rad": 1.1519, "width": 320, "height": 240}
ORANGE = (0, 128, 255)  # BGR, H about 15
DIST = 0.30


def _img(h, y=60):
    img = np.full((240, 320, 3), 90, np.uint8)
    cv2.rectangle(img, (100, y), (220, y + h - 1), ORANGE, -1)
    return img


def _exp(tier_mm):
    import math
    return 320 / (2 * math.tan(1.1519 / 2)) * tier_mm / 1000 / DIST


def test_one_tier():
    r = tv.classify_tiers(_img(round(_exp(30))), CAM, DIST)
    assert r["tiers"] == 1 and r["confidence"] > 0.8
    assert {"h_px", "expected_px", "blob_bbox"} <= set(r["evidence"])


def test_two_tiers():
    assert tv.classify_tiers(_img(round(_exp(65))), CAM, DIST)["tiers"] == 2


def test_empty_abstains():
    r = tv.classify_tiers(np.full((240, 320, 3), 90, np.uint8), CAM, DIST)
    assert r["tiers"] is None and r["evidence"]["abstain"] == "no_blob"


def test_border_abstains():
    r = tv.classify_tiers(_img(round(_exp(65)), y=0), CAM, DIST)
    assert r["tiers"] is None and r["evidence"]["abstain"] == "border"


def test_midpoint_abstains():
    r = tv.classify_tiers(_img(round((_exp(30) + _exp(65)) / 2)), CAM, DIST)
    assert r["tiers"] is None and r["evidence"]["abstain"] == "margin"


@pytest.mark.parametrize("dist", [None, 0.05, 0.9])
def test_bad_distance_abstains(dist):
    r = tv.classify_tiers(_img(40), CAM, dist)
    assert r["tiers"] is None and r["evidence"]["abstain"] == "distance"
