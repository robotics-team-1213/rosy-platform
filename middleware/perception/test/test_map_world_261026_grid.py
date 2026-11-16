"""map_world_261026 Nav2 grid: free only strictly inside the mat, the wall ring and everything outside it occupied."""
import importlib.util
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "map" / "map_world_261026"
spec = importlib.util.spec_from_file_location("build_world_261026", BUNDLE / "scripts" / "build_world.py")
bw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bw)

FREE, OCC = 254, 0


def cell(grid, x_m, y_m):
    w, h, rows, ox, oy = grid
    i, j = int((x_m - ox) / (bw.GRID_RES_MM / 1000.0)), int((y_m - oy) / (bw.GRID_RES_MM / 1000.0))
    return rows[h - 1 - j][i]


def test_inside_the_mat_is_free_and_the_wall_ring_is_occupied():
    g = bw.map_grid()
    assert cell(g, 0.0, 0.0) == FREE
    assert cell(g, bw.MAT_X / 2 - 0.03, bw.MAT_Y / 2 - 0.03) == FREE
    for x, y in ((bw.MAT_X / 2 + 0.002, 0.0), (-bw.MAT_X / 2 - 0.002, 0.0),
                 (0.0, bw.MAT_Y / 2 + 0.002), (0.0, -bw.MAT_Y / 2 - 0.002)):
        assert cell(g, x, y) == OCC, (x, y)


def test_everything_outside_the_walls_is_occupied_up_to_the_grid_edge():
    w, h, rows, _, _ = bw.map_grid()
    assert all(v == OCC for v in rows[0]) and all(v == OCC for v in rows[-1])
    assert all(r[0] == OCC and r[-1] == OCC for r in rows)
    free = sum(v == FREE for r in rows for v in r)
    # the free area is the mat, to within one 2 cm cell on each side
    assert abs(free * (bw.GRID_RES_MM / 1000.0) ** 2 - bw.MAT_X * bw.MAT_Y) < 0.1 * bw.MAT_X * bw.MAT_Y


def test_grid_is_centred_on_the_mat_frame():
    w, h, _, ox, oy = bw.map_grid()
    res = bw.GRID_RES_MM / 1000.0
    assert abs(ox + w * res / 2) < 1e-9 and abs(oy + h * res / 2) < 1e-9


def test_committed_grid_files_are_what_the_generator_writes(tmp_path):
    bw.write_map(tmp_path)
    for name in ("map_world_261026.pgm", "map_world_261026.yaml"):
        assert (tmp_path / "maps" / name).read_bytes() == (BUNDLE / "maps" / name).read_bytes(), name
