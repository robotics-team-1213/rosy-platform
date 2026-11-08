"""omx_twin's measuring parts without MuJoCo: outline, edge offset, lag, shards and the report."""
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
import omx_twin  # noqa: E402


def square(h=120, w=160, top=40, left=50, size=30):
    m = np.zeros((h, w), bool)
    m[top:top + size, left:left + size] = True
    return m


def test_outline_is_the_border_only():
    edge = omx_twin.outline(square())
    assert edge.sum() == 4 * 30 - 4
    assert not edge[50, 60]


def test_offset_finds_where_the_real_edges_are():
    real = np.zeros((120, 160, 3), np.uint8)
    real[46:76, 54:84] = 255  # the real arm sits 6 down, 4 right of where the sim draws it
    o = omx_twin.offset(omx_twin.edge_strength(real), omx_twin.outline(square()))
    assert (o["dx"], o["dy"]) == (4, 6)
    assert o["score"] > o["score0"]


def test_offset_needs_an_outline():
    assert omx_twin.offset(np.ones((10, 10)), np.zeros((10, 10), bool)) is None


def test_lag_finds_a_known_delay():
    t = np.arange(0, 10, 1 / omx_twin.GRID_HZ)
    ref = np.sin(t)
    follower = np.concatenate([np.full(10, ref[0]), ref[:-10]])  # 10 grid steps = 0.2 s late
    assert omx_twin.lag_s(t, ref, follower) == 0.2


def test_shards_split_every_name_once():
    names = [f"2026110{d}-0{k}0000-strip-to-strip" for d in range(1, 8) for k in range(6)]
    for name in names:
        assert sum(omx_twin.shard_of(name, f"{i}/3") for i in range(3)) == 1


def test_report_flags_a_camera_off_its_limit(tmp_path, capsys):
    row = dict(kp=40.0, gravity_comp=True, rms_deg=[.5] * 5, p95_deg=[1] * 5, mean_deg=[0] * 5, lag_s=[.16] * 5)
    twin = dict(episode="e1", real={"outcome": "failed"},
                tracking=dict(real_lag_s=[.2] * 5, grid=[row], best=dict(kp=40.0, gravity_comp=True, rms_deg=[.5] * 5),
                              best_per_joint=[dict(kp=40.0, gravity_comp=True, rms_deg=.5)] * 5),
                view={"top": dict(median_px=10.8, p90_px=20, median_dx=0, median_dy=6, median_score=2.1, within=False)})
    (tmp_path / "e1").mkdir()
    (tmp_path / "e1/twin.json").write_text(json.dumps(twin))
    assert omx_twin.report([str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "| e1 | failed | top | 10.8 |" in text and "| NO |" in text
    assert "Median best kp per joint (j1-j5): 40 40 40 40 40" in text
