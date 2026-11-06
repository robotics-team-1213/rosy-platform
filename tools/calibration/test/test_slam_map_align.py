"""Rigid SLAM-map to site-frame fit: recovery, noise, refusals, ambiguity and the written map."""
import math
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import slam_map_align as sma  # noqa: E402

YAW, T = math.radians(37.0), (1.2, -0.4)
SLAM = [(0.1, 0.2), (1.8, 0.3), (1.5, 3.1), (0.4, 2.6)]


def _site(points, yaw=YAW, t=T, noise=0.0, seed=1):
    rng = random.Random(seed)
    c, s = math.cos(yaw), math.sin(yaw)
    return [(c * x - s * y + t[0] + rng.gauss(0, noise), s * x + c * y + t[1] + rng.gauss(0, noise)) for x, y in points]


def test_known_transform_recovered():
    fit, notes, _ = sma.align(SLAM, _site(SLAM), 0.05)
    assert abs(fit.yaw - YAW) < 1e-9 and abs(fit.tx - T[0]) < 1e-9 and abs(fit.ty - T[1]) < 1e-9
    assert fit.max < 1e-9 and notes == []


def test_noisy_points_pass_inside_gate():
    fit, _, _ = sma.align(SLAM, _site(SLAM, noise=0.01), 0.05)
    assert abs(fit.yaw - YAW) < math.radians(2) and fit.max < 0.05


def test_collinear_and_too_few_refused():
    for pts in (SLAM[:2], [(0, 0), (1, 1), (2, 2), (3, 3)]):
        try:
            sma.align(pts, _site(pts), 0.05)
        except sma.AlignError:
            continue
        raise AssertionError("expected refusal")


def test_mirrored_correspondences_detected():
    mirrored = [(x, -y) for x, y in _site(SLAM)]
    try:
        sma.align(SLAM, mirrored, 0.05)
    except sma.AlignError as exc:
        assert "mirrored" in str(exc)
    else:
        raise AssertionError("expected refusal")


def test_too_large_residual_refused():
    site = _site(SLAM)
    site[0] = (site[0][0] + 0.3, site[0][1])
    try:
        sma.align(SLAM, site, 0.05)
    except sma.AlignError as exc:
        assert "exceeds" in str(exc)
    else:
        raise AssertionError("expected refusal")


def test_points_clustered_about_centre_are_ambiguous():
    # a gate looser than the cluster lets the 180-degree flip fit too: the points cannot fix the heading
    pts = [(0.1, 0.1), (-0.1, -0.1), (0.1, -0.1), (-0.1, 0.1)]
    site = _site(pts, yaw=0.0, t=(0, 0))
    try:
        sma.align(pts, site, 0.5)
    except sma.AlignError as exc:
        assert "AMBIGUOUS" in str(exc)
    else:
        raise AssertionError("expected refusal")
    assert any("AMBIGUOUS" in n for n in sma.align(pts, site, 0.5, allow_ambiguous=True)[1])


def _write_rect_map(folder, w=40, h=60):
    cells = np.full((h, w), 254, np.uint8)
    cells[0, :] = cells[-1, :] = cells[:, 0] = cells[:, -1] = 0
    (folder / "m.pgm").write_bytes(b"P5\n%d %d\n255\n" % (w, h) + cells.tobytes())
    (folder / "m.yaml").write_text("image: m.pgm\nmode: trinary\nresolution: 0.05\norigin: [-1.0, -1.5, 0]\n"
                                   "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")
    return folder / "m.yaml"


def test_rectangle_boundary_is_self_similar(tmp_path):
    grid = sma.load_map(_write_rect_map(tmp_path))
    assert sma.boundary_symmetry(grid.cells) > 0.99
    grid.cells[10:20, 5:9] = 1  # a feature breaks the symmetry
    assert sma.boundary_symmetry(grid.cells) < 0.97


def test_write_rotates_grid_and_keeps_input(tmp_path, capsys):
    src = _write_rect_map(tmp_path)
    before = (src.read_bytes(), (tmp_path / "m.pgm").read_bytes())
    site = _site([(0, 0), (1, 0), (0, 1), (0.5, 0.5)], yaw=math.radians(90), t=(2, 3))
    args = [str(src), "--pair"] + sum((["%s,%s=%s,%s" % (*s, *p)] + ["--pair"] for s, p in zip(site, [(0, 0), (1, 0), (0, 1), (0.5, 0.5)])), [])[:-1]
    assert sma.main(args + ["--write", str(tmp_path / "out.yaml")]) == 0
    assert (src.read_bytes(), (tmp_path / "m.pgm").read_bytes()) == before
    out = sma.load_map(tmp_path / "out.yaml")
    assert out.cells.shape == (40, 60) and out.cells[(out.cells == 1)].sum() > 0  # 90 deg turn swaps width/height
    assert "0.0]" in (tmp_path / "out.yaml").read_text()
    assert sma.main(args + ["--write", str(src)]) == sma.REFUSED
    assert sma.main(args + ["--write", str(tmp_path / "out.yaml")]) == sma.REFUSED  # exists


def test_cli_refuses_with_exit_3(tmp_path):
    src = _write_rect_map(tmp_path)
    bad = ["--pair", "0,0=0,0", "--pair", "1,0=1,0", "--pair", "0,1=0,1.4"]
    assert sma.main([str(src)] + bad) == sma.REFUSED
