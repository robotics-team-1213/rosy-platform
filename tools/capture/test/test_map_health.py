"""map_health: synthetic maps (clean, empty, speckle, opening, compare) and the real SLAM maps when present."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import map_health as mh  # noqa: E402

YAML = "image: m.pgm\nresolution: {res}\norigin: [-1.0, -1.0, 0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n"


def write_map(tmp, rows, res=0.05, name="m"):
    """rows of '#' wall, '.' free, '?' unknown; row 0 is the top."""
    val = {"#": 0, ".": 254, "?": 205}
    h, w = len(rows), len(rows[0])
    (tmp / f"{name}.pgm").write_bytes(f"P5\n{w} {h}\n255\n".encode() + bytes(val[ch] for r in rows for ch in r))
    (tmp / f"{name}.yaml").write_text(YAML.format(res=res).replace("m.pgm", f"{name}.pgm"))
    return tmp / f"{name}.yaml"


def room(opening=False):
    rows = ["?" * 30] + ["?#" + "." * 24 + "#?" + "??" for _ in range(24)] + ["?" * 30]
    rows = [r[:30] for r in rows]
    rows[1] = "?" + "#" * 26 + "???"
    rows[-2] = "?" + "#" * 26 + "???"
    if opening:
        rows[1] = "?" + "#" * 5 + "." + "#" * 20 + "???"
        rows[0] = "?" * 6 + "." + "?" * 23
    return rows


def run(tmp, rows, **kw):
    meta, w, h, grid = mh.load(write_map(tmp, rows, **kw))
    rep = mh.analyze(meta, w, h, grid)
    return rep, mh.verdict(rep)


def test_clean_room_ok(tmp_path):
    rep, v = run(tmp_path, room())
    assert rep["enclosed"] and rep["speckle"] == 0 and v["verdict"] == "ok", (rep, v)


def test_empty_fails(tmp_path):
    _, v = run(tmp_path, ["." * 30] * 30)
    assert v["verdict"] == "fail" and "no occupied cells" in v["reasons"]


def test_speckle_fails(tmp_path):
    rows = ["?" * 30] + ["?" + "".join("#" if (r + c) % 3 == 0 and r % 2 == 0 else "." for c in range(28)) + "?"
                         for r in range(28)] + ["?" * 30]
    rep, v = run(tmp_path, rows)
    assert v["verdict"] == "fail" and any("speckle" in x for x in v["reasons"]), rep


def test_opening_warns(tmp_path):
    rep, v = run(tmp_path, room(opening=True))
    assert not rep["enclosed"] and v["verdict"] == "warn", (rep, v)


def test_bad_resolution_fails_unless_allowed(tmp_path):
    meta, w, h, grid = mh.load(write_map(tmp_path, room(), res=0.1))
    rep = mh.analyze(meta, w, h, grid)
    assert mh.verdict(rep)["verdict"] == "fail"
    assert "resolution" not in " ".join(mh.verdict(rep, allow_resolution=0.1)["reasons"])


def test_compare_overlap(tmp_path, capsys):
    a = write_map(tmp_path, room(), name="a")
    b = write_map(tmp_path, room(), name="b")
    assert mh.main([str(a), "--compare", str(b)]) == 0
    assert '"overlap_a_in_b": 1.0' in capsys.readouterr().out
    shifted = write_map(tmp_path, ["?" * 30] * 8 + room()[:22], name="c")
    ma, _, ha, ga = mh.load(a)
    mc, _, hc, gc = mh.load(shifted)
    assert mh.overlap(mh.walls_world(ma, ha, ga), mh.walls_world(mc, hc, gc)) < 0.5


REAL = Path("D:/DevTemp/slam-map")


@pytest.mark.skipif(not (REAL / "fresh1.yaml").exists() or not (REAL / "unwind1_map.yaml").exists(), reason="real maps absent")
def test_real_maps(capsys):
    assert mh.main([str(REAL / "fresh1.yaml"), "--compare", str(REAL / "unwind1_map.yaml")]) == 0
    out = capsys.readouterr().out
    assert '"resolution": 0.05' in out and '"overlap_a_in_b"' in out
