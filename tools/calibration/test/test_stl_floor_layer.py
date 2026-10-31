"""D-825 upload prep: keep the floor layer of a Y-up world STL and write it Z-up without a mirror."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stl_floor_layer import floor_layer, main  # noqa: E402


def _tri(normal, *vertices):
    return struct.pack("<12fH", *normal, *[c for v in vertices for c in v], 0)


def _world() -> bytes:
    up = (0.0, 1.0, 0.0)
    tris = [
        # Mat at y=10: the largest upward area, 1000 x 500.
        _tri(up, (0, 10, 0), (1000, 10, 500), (1000, 10, 0)),
        _tri(up, (0, 10, 0), (0, 10, 500), (1000, 10, 500)),
        # Paint 1 mm above it.
        _tri(up, (100, 11, 100), (200, 11, 110), (200, 11, 100)),
        # An arm top 300 mm up, and a side face: both dropped.
        _tri(up, (500, 310, 200), (520, 310, 210), (520, 310, 200)),
        _tri((1.0, 0.0, 0.0), (0, 10, 0), (0, 20, 0), (0, 20, 10)),
    ]
    return b"w".ljust(80) + struct.pack("<I", len(tris)) + b"".join(tris)


def test_keeps_the_floor_band_and_turns_y_up_into_z_up():
    triangles, floor = floor_layer(_world(), above=80.0, y_up=True)

    assert floor == 10.0 and len(triangles) == 3
    paint = triangles[2]
    assert paint[:3] == (0.0, 0.0, 1.0)  # the upward normal now points along +z
    assert paint[3:6] == (100.0, -100.0, 11.0)  # (x, y, z) -> (x, -z, y)


def test_the_turn_is_a_rotation_not_a_mirror():
    (mat, *_), _ = floor_layer(_world(), above=80.0, y_up=True)
    (ax, ay, _), (bx, by, _), (cx, cy, _) = (mat[3:6], mat[6:9], mat[9:12])
    # Winding seen from +z stays counter-clockwise iff the upward normal stays upward.
    assert (bx - ax) * (cy - ay) - (cx - ax) * (by - ay) > 0


def test_over_the_fleet_limit_exits_non_zero(tmp_path, monkeypatch):
    import stl_floor_layer
    source, out = tmp_path / "w.stl", tmp_path / "f.stl"
    source.write_bytes(_world())
    monkeypatch.setattr(stl_floor_layer, "FLEET_MAX_TRIANGLES", 2)
    assert main(["x", str(source), str(out)]) == 1
