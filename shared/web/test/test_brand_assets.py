"""D-654: platform identity stays shared, installable and distinct from app roles."""
import json
import xml.etree.ElementTree as ET

import pytest

from test_surface_icons import RENDER, TOKENS, WEB

NS = {"svg": "http://www.w3.org/2000/svg"}


def test_platform_tile_uses_the_canonical_mark_and_brand_tokens():
    mark = ET.parse(WEB / "brand/mark.svg").getroot()
    tile = ET.parse(WEB / "brand/platform.svg").getroot()
    assert mark.find("svg:path", NS).get("d") == tile.find("svg:path[@id='rosy-mark']", NS).get("d")
    assert mark.find("svg:path", NS).get("fill") == "currentColor"
    assert tile.find("svg:path[@id='rosy-mark']", NS).get("fill") == TOKENS["--brand-rose"]
    assert tile.find("svg:path[@id='background']", NS).get("fill") == TOKENS["--ground"]
    assets = json.loads((WEB / "shared-assets.json").read_text())["shared_assets"]
    cmake = (WEB / "CMakeLists.txt").read_text()
    for name in ("brand/mark.svg", "brand/platform.svg"):
        assert assets[name] == "image/svg+xml" and name in cmake
    assert 'mask: url("brand/mark.svg")' in (WEB / "components.css").read_text()


@pytest.mark.parametrize("size", [16, 24, 48])
def test_small_mark_has_a_visible_unclipped_silhouette(size):
    pytest.importorskip("PIL")
    alpha = RENDER.render(WEB / "brand/mark.svg", size, mono=True).getchannel("A")
    occupied = sum(value >= 128 for value in alpha.tobytes())
    assert size * size * .1 < occupied < size * size * .6
    left, top, right, bottom = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
    assert 0 < left < right < size and 0 < top < bottom < size
