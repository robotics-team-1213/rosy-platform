"""D-370 3항 — Pilot PWA 아이콘은 web_common/icons/pilot.svg 를 tools/icons/render_png.py 로 그린 것이다.

SVG 를 고치고 PNG 를 다시 그리지 않으면 설치 앱 아이콘이 표면 아이콘과 갈라진다. 다시 그리기:
    python tools/icons/render_png.py src/hmi/web_common/icons/pilot.svg src/hmi/pilot/icons/icon-512.png --size 512
    (192 도 같게. maskable 은 같은 그림을 --ground 판 위에 합성해 모서리까지 채운다.)
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
ImageChops = pytest.importorskip("PIL.ImageChops")

PILOT = Path(__file__).resolve().parents[1]
REPO = PILOT.parents[2]
SVG = REPO / "src/hmi/web_common/icons/pilot.svg"
GROUND = "#101214"


def _render(size: int):
    spec = importlib.util.spec_from_file_location("rosy_icon_render", REPO / "tools/icons/render_png.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render(SVG, size)


def _max_diff(a, b) -> int:
    return max(high for _, high in ImageChops.difference(a, b).getextrema())


@pytest.mark.parametrize("size", [192, 512])
def test_any_icons_are_the_rendered_surface_icon(size):
    committed = Image.open(PILOT / f"icons/icon-{size}.png").convert("RGBA")
    assert committed.size == (size, size)
    assert _max_diff(committed, _render(size)) <= 2


def test_maskable_icon_is_full_bleed_on_the_ground_plate():
    committed = Image.open(PILOT / "icons/icon-192-maskable.png").convert("RGB")
    plate = Image.new("RGBA", (192, 192), GROUND)
    plate.alpha_composite(_render(192))
    assert _max_diff(committed, plate.convert("RGB")) <= 2
    assert committed.getpixel((0, 0)) == Image.new("RGB", (1, 1), GROUND).getpixel((0, 0))


def test_manifest_names_and_icons_follow_d370():
    manifest = json.loads((PILOT / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "Rosy Pilot" and manifest["short_name"] == "Rosy Pilot"
    icons = {(icon["src"], icon["sizes"], icon["purpose"]) for icon in manifest["icons"]}
    assert icons == {
        ("/pilot/assets/icons/icon-192.png", "192x192", "any"),
        ("/pilot/assets/icons/icon-512.png", "512x512", "any"),
        ("/pilot/assets/icons/icon-192-maskable.png", "192x192", "maskable"),
    }
