"""MuJoCo ship-plate release scene (tools/sim/ship_release_scene.py): nominal seats, a gross offset is flagged, verdict rules."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "sim"))
import ship_release_scene as scene  # noqa: E402


def test_verdict_rules():
    ok = dict(z_mm=0.0, y_mm=0.1, x_mm=0.0, nb_peak_mm=0.1)
    assert scene.verdict(ok, 1) == []
    assert scene.verdict(dict(ok, z_mm=1.4), 1) == ["rode-up"]
    assert scene.verdict(dict(ok, y_mm=0.6), 1) == ["not-in-channel"]
    assert scene.verdict(dict(ok, y_mm=0.6), 2) == []  # no guide on layer 2: 1.5 mm is the limit
    assert scene.verdict(dict(ok, nb_peak_mm=0.5), 2) == ["neighbour"]


@pytest.mark.parametrize("layer", [1, 2])
def test_nominal_release_seats_like_isaac(layer):
    model, fixture = scene.build(layer)
    m = scene.run(model, fixture, layer=layer)
    assert abs(m["z_mm"]) < 0.2 and abs(m["y_mm"]) < 0.2 and m["nb_peak_mm"] < 0.3  # Isaac: 0.2 mm xy, 0.0 z, 0.3 mm neighbour


def test_gross_offset_on_studs_is_not_in_channel():
    model, fixture = scene.build(1)
    m = scene.run(model, fixture, layer=1, dy=0.012)  # 12 mm across: half a box on the neighbouring stud line
    assert scene.verdict(m, 1)
