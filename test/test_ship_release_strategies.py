"""Release strategies and container variants on the MuJoCo ship-plate scene: geometry, mass, guarded contact, seat rule."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "sim"))
import ship_container_variants as variants  # noqa: E402
import ship_release_scene as scene  # noqa: E402
import ship_release_strategies as strategies  # noqa: E402


def test_variants_stay_inside_the_90_x_30_x_30_envelope_and_below_the_pad_band():
    for name, v in variants.VARIANTS.items():
        points = []
        for kind, data, *rest in variants.pieces(v):
            if kind == 'box':
                half, centre = data, rest[0]
                points += [(centre[0] + sx * half[0], centre[1] + sy * half[1], centre[2] + sz * half[2]) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
            else:
                points += [tuple(data[i + k] * 1e3 for k in range(3)) for i in range(0, len(data), 3)]
        for axis, limit in enumerate((45, 15, 15)):
            assert max(abs(p[axis]) for p in points) <= limit + 1e-6, name
        # chamfer, relief and groove stay within 3 mm of the bottom: the jaw pads start 18 mm above it (measured in the squeezed scene)
        assert variants.NEST_MM < 3 and v.get("chamfer_mm", 0) <= 1.5


def test_variant_mass_follows_volume():
    for name, ratio in variants.MASS_RATIO.items():
        model, _ = scene.build(1, name, weld=True)
        assert model.body_mass[model.body("box").id] == pytest.approx(0.016 * ratio, rel=2e-3), name


def test_guarded_descent_stops_on_the_plate_and_on_a_dot():
    model, fixture = scene.build(1, weld=True)
    flat = strategies.attempt(model, fixture, layer=1, strategy="guarded", dy=0.0, retry=False)
    assert flat["seated"] and abs(flat["contact_mm"]) < 0.3  # the bottom meets the plate at the seat height
    on_dot = strategies.attempt(model, fixture, layer=1, strategy="guarded", dy=0.0006, retry=False)
    assert on_dot["contact_mm"] > 1.5  # 0.2 mm past the 0.4 mm clearance: the box edge meets a dot top first


def test_seat_rule_flags_height_and_tilt():
    model, fixture = scene.build(1, weld=True)
    r = strategies.Release(model, fixture, layer=1, variant="plain", row=1, dx=0, dy=0.0, yaw_deg=0, mu=1.0, gap=0.0315, start=0.0)
    assert strategies.seated(r)
    r.d.qpos[model.joint("box").qposadr[0] + 2] += 0.001  # 1 mm high
    strategies.mujoco.mj_forward(model, r.d)
    assert not strategies.seated(r)
