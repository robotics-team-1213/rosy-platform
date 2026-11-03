"""MuJoCo whole-stack sequence (tools/sim/ship_stack_sequence.py): the error-free stack seats, a re-place recovers a miss."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "sim"))
import ship_stack_sequence as seq  # noqa: E402

BASE = dict(order=(1, 0, 2), open_gap_m=.0315, mu=1., sigma_yaw=0., clearance_mm=2.)


def test_error_free_stack_seats_all_nine_in_the_isaac_order():
    r = seq.run(dict(BASE, sigma_mm=0., seed=0))
    assert r["ok"] and [(b["layer"], b["row"]) for b in r["boxes"][:3]] == [(0, 1), (0, 0), (0, 2)]


def test_one_corrected_re_place_recovers_a_stack_a_single_release_loses():
    # seed 1 at 0.8 mm loses the stack without a seat check (sweep 2026-11-04: 2/24 seated at this error)
    lost = seq.run(dict(BASE, sigma_mm=.8, seed=1, retries=0))
    kept = seq.run(dict(BASE, sigma_mm=.8, seed=1, retries=1))
    assert not lost["ok"] and kept["ok"] and any(b["retried"] for b in kept["boxes"])


def test_v11_ship_error_free_stack_seats_on_the_pins_and_the_camera_holder_stays_clear():
    # snap-together ship v11 + container v2 + wrist camera B holder (2026-11-04)
    r = seq.run(dict(BASE, ship="v11", mu=.5, sigma_mm=0., seed=1, retries=0))
    assert r["ok"] and r["camera_hits"] == 0 and max(b["xy_mm"] for b in r["boxes"]) < .3
