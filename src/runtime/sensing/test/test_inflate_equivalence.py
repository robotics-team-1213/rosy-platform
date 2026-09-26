"""D-185 R1: the vectorised OccupancyMap.inflate must reproduce the original exactly.

goal plans every 2 s and inflates the whole map per candidate and radius; the pure-Python
inflate cost 51 ms (200x200) to 128 ms (400x400) on an idle x86 core (2026-09-24).
The result feeds route safety, so every cell, the map attributes and the builtin int
values must be identical.
"""
import math
import random
from array import array

from control.planning.gridmap import FREE, OCC, OCC_THRESH, UNKNOWN, OccupancyMap


def reference_inflate(self, r_cells):
    """Verbatim copy of OccupancyMap.inflate before vectorisation (main 631ff091)."""
    out = OccupancyMap(self.w, self.h, self.res, (self.ox, self.oy), fill=UNKNOWN)
    extent = math.ceil(r_cells)
    for i, v in enumerate(self.data):
        if v >= OCC_THRESH:
            out.data[i] = OCC
        elif v == UNKNOWN:
            out.data[i] = UNKNOWN
        else:
            out.data[i] = FREE
    for i, v in enumerate(self.data):
        if v < OCC_THRESH:
            continue
        c, r = i % self.w, i // self.w
        for dc in range(-extent, extent + 1):
            for dr in range(-extent, extent + 1):
                if dc * dc + dr * dr <= r_cells * r_cells:
                    out.set_cell(c + dc, r + dr, OCC)
    return out


def snapshot(m):
    assert all(type(v) is int for v in m.data)
    return (m.w, m.h, repr(m.res), repr(m.ox), repr(m.oy), m.data)


def random_map(rng, w, h):
    m = OccupancyMap(w, h, rng.choice((.02, .05, .1)), (rng.uniform(-3, 3), rng.uniform(-3, 3)))
    density = rng.choice((0., .002, .02, .1, .5))
    values = (-1, -2, 0, 1, 30, 64, 65, 66, 99, 100, 127)
    m.data = [rng.choice(values) if rng.random() < density else rng.choice((-1, 0, 0, 0, 10))
              for _ in range(w*h)]
    return m


def test_inflate_is_identical_to_the_original():
    rng = random.Random(185)
    radii = (0., .4, 1., 1.5, 2., 2.9999999999999996, 3., .06/.02, .1/.02, 4.5, 7.)
    cases = 0
    for _ in range(120):
        w, h = rng.randint(1, 40), rng.randint(1, 40)
        m = random_map(rng, w, h)
        for r_cells in rng.sample(radii, 3):
            assert snapshot(m.inflate(r_cells)) == snapshot(reference_inflate(m, r_cells)), (w, h, r_cells)
            cases += 1
    assert cases == 360


def test_edge_walls_and_single_cells_match():
    for w, h in ((1, 1), (1, 7), (7, 1), (5, 5)):
        m = OccupancyMap(w, h, .05, (0., 0.), fill=0)
        m.set_cell(0, 0, 100)
        m.set_cell(w-1, h-1, 65)
        for r_cells in (0., 1., 2.5, 10.):
            assert snapshot(m.inflate(r_cells)) == snapshot(reference_inflate(m, r_cells))


def test_inflate_returns_an_independent_map():
    m = OccupancyMap(6, 6, .05, (0., 0.), fill=0)
    m.set_cell(3, 3, 100)
    before = list(m.data)
    first = m.inflate(1.)
    assert type(first.data) is list
    first.set_cell(0, 0, 100)
    assert m.data == before  # mutating a result never reaches the source map
    assert m.inflate(1.).cell(0, 0) == FREE  # results are never shared between calls


def test_real_size_maps_and_radii_beyond_the_map_match():
    rng = random.Random(24)
    for w, h, r_cells in ((200, 200, 2.4), (200, 200, 6.), (30, 5, 50.), (9, 1, 12.)):
        m = random_map(rng, w, h)
        assert snapshot(m.inflate(r_cells)) == snapshot(reference_inflate(m, r_cells)), (w, h, r_cells)


def test_negative_zero_and_invalid_radii_match():
    m = random_map(random.Random(3), 12, 9)
    for r_cells in (-3., -1., -.5, -0., 0.):
        assert snapshot(m.inflate(r_cells)) == snapshot(reference_inflate(m, r_cells)), r_cells
    for r_cells in (math.nan, math.inf, -math.inf):
        expected = _raised(reference_inflate, m, r_cells)
        assert expected is not None and _raised(OccupancyMap.inflate, m, r_cells) is expected, r_cells


def _raised(inflate, m, r_cells):
    """The exception type an invalid radius raises (math.ceil: ValueError or OverflowError)."""
    try:
        inflate(m, r_cells)
    except (ValueError, OverflowError) as error:
        return type(error)
    return None


def test_float_nan_and_int8_data_match():
    # NaN is not < OCC_THRESH, so the original treated it as a growth source (conservative).
    m = OccupancyMap(8, 6, .05, (0., 0.), fill=0)
    m.data = [0.]*48
    m.data[5], m.data[20], m.data[33] = math.nan, 64.99999, 65.
    for r_cells in (0., 1., 2.5):
        assert snapshot(m.inflate(r_cells)) == snapshot(reference_inflate(m, r_cells)), r_cells
    int8 = OccupancyMap(6, 5, .05, (0., 0.))
    int8.data = list(array('b', [-128, 127, -1, 0, 64, 65]*5))
    assert snapshot(int8.inflate(1.5)) == snapshot(reference_inflate(int8, 1.5))
