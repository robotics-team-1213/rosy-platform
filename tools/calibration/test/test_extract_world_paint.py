"""261026 world STL -> lane paint: the mat is the largest upward face, paint is the 1 mm layer on it."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extract_world_paint import extract  # noqa: E402


def _stl(*triangles):
    body = b"\0" * 80 + struct.pack("<I", len(triangles))
    for normal_y, vertices in triangles:
        body += struct.pack("<12fH", 0.0, normal_y, 0.0, *[c for v in vertices for c in v], 0)
    return body


# Y-up millimetres: a 1000 x 400 mat at y=10, paint 1 mm above it, a wall that faces sideways.
MAT = [(1.0, ((0, 10, 0), (1000, 10, 0), (1000, 10, 400))), (1.0, ((0, 10, 0), (1000, 10, 400), (0, 10, 400)))]
PAINT = (1.0, ((100, 11, 100), (200, 11, 100), (200, 11, 120)))
WALL = (0.0, ((0, 0, 0), (0, 50, 0), (0, 50, 400)))


def test_paint_is_kept_in_the_ros_site_frame_without_a_mirror():
    scene = extract(_stl(*MAT, PAINT, WALL))
    assert scene["mat_height_mm"] == 10.0
    assert scene["mat_size_m"] == pytest.approx((1.0, 0.4))
    assert scene["paint_area_m2"] == pytest.approx(100 * 20 / 2 * 1e-6)
    (a, b, c), = scene["lines"]
    # Centred on the mat, mm -> m, Z-up: +x stays +x, +z becomes -y (R_x(+90 deg), never a mirror).
    assert a == pytest.approx((-0.4, 0.1, 0.001))
    assert b == pytest.approx((-0.3, 0.1, 0.001))
    assert c == pytest.approx((-0.3, 0.08, 0.001))


def test_a_world_without_paint_or_a_bad_size_is_refused():
    with pytest.raises(ValueError, match="no lane paint"):
        extract(_stl(*MAT))
    with pytest.raises(ValueError, match="not a binary STL"):
        extract(_stl(*MAT)[:-1])
