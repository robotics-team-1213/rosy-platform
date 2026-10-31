"""Real-arm session rows become the fixture's estimate-noise range."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_measurement as rm


def test_estimate_rows_give_the_fixture_noise_range_per_kind():
    rows = [dict(kind='estimate', trial=str(i), dx_mm=str(i), dy_mm='0', dz_mm='0') for i in range(1, 11)]
    rows.append(dict(kind='drift', trial='1', dx_mm='0.3', dy_mm='0.4', dz_mm='0'))
    out = rm.summary(rows)
    assert out['estimate']['n'] == 10 and out['estimate']['max_mm'] == 10
    assert out['drift'] == dict(n=1, p50_mm=.5, p95_mm=.5, max_mm=.5)
    assert out['release_estimate_noise_m'] == pytest.approx([.0055, .00955])
