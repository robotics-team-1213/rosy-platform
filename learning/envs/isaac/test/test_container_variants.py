"""Container variants (container_variants.py): hull faces point outward and every variant keeps its envelope and the 30 mm grip faces."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

import container_variants as cv


def points(piece):
    kind, data, *rest = piece
    if kind == 'hull':
        return [tuple(data[i:i+3]) for i in range(0, len(data), 3)]
    half, c = data, rest[0]
    return [tuple((c[t]+s[t]*half[t])/1e3 for t in range(3)) for s in ((x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1))]


def test_hull_triangles_point_outward():
    for name, v in cv.VARIANTS.items():
        for piece in cv.pieces(v, .06):
            pts = points(piece)
            centre = [sum(p[t] for p in pts)/len(pts) for t in range(3)]
            tris = cv.hull_triangles(pts)
            assert tris, name
            for i, j, k in tris:
                a, b, c = pts[i], pts[j], pts[k]
                u, w = [b[t]-a[t] for t in range(3)], [c[t]-a[t] for t in range(3)]
                n = (u[1]*w[2]-u[2]*w[1], u[2]*w[0]-u[0]*w[2], u[0]*w[1]-u[1]*w[0])
                assert sum(n[t]*(centre[t]-a[t]) for t in range(3)) <= 1e-12, name


def test_variants_keep_envelope_and_grip_faces():
    for name, v in cv.VARIANTS.items():
        for length in (.03, .06, .09):
            pts = [p for piece in cv.pieces(v, length) for p in points(piece)]
            for axis, limit in enumerate((length/2, .015, .015)):
                assert max(abs(p[axis]) for p in pts) <= limit+1e-9, (name, length)
            above = [abs(p[1]) for p in pts if p[2] > -.015+.003+1e-9]  # above the 3 mm foot: the 30 mm grip faces
            assert max(above) == .015 or not above, name


def test_step4_cases_carry_the_variant_mass_the_guard_and_the_offset():
    import mapped_stack_fixture as f
    base = f.container_fixture(layers=3, case='nominal-palletizing-v21-ship')
    relief = f.container_fixture(layers=3, case='nominal-palletizing-v21-ship-y100-r290-guard-g315')
    assert relief['container_variant'] == 'r290' and relief['guarded_descent']['step_m'] == .0005
    assert relief['release_offset_m'] == [0., .001] and relief['release_gap_m'] == .0315
    assert relief['cargo_mass_kg'][2] == pytest.approx(base['cargo_mass_kg'][2]*cv.MASS_RATIO['r290'], rel=1e-5)
    assert 'container_variant' not in base and 'guarded_descent' not in base
