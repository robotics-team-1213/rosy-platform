"""The map gate (tools/sim/omx_map_gate.py): one frame per map, CAD lengths recomputed from the map, per-item uncertainty."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_map_gate as gate  # noqa: E402
import omx_real2sim as r2s  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402


def test_arm_bases_left_in_the_survey_frame_beside_a_photo_frame_map_are_refused():
    """2026-11-14: the preset held ship, plates and camera in that day's frame and the arm bases in the 11-03 FK frame (26-44 mm)."""
    result = gate.gate(sites.Layout(preset="v24-20261114", arm_bases="surveyed"))
    assert result["verdict"] == "refuse" and result["frame"] is None
    assert any("two frames" in w and "arm_bases" in w for w in result["why"])
    assert any("bridge v7" in w for w in result["why"])  # the same error seen through a printed length: 252 mm against 200


def test_the_preset_is_one_frame_with_its_cad_lengths_and_says_what_is_unconfirmed():
    result = gate.gate(sites.Layout(preset="v24-20261114"))
    assert result["verdict"] == "unconfirmed" and result["frame"] == gate.PHOTO_1114 and not result["why"]
    assert all(c["ok"] for c in result["checks"]) and len(result["checks"]) == 4
    assert any(u.startswith("arm_bases") for u in result["unconfirmed"])  # picked by eye: 2 sigma 6 mm against a 3 mm grasp


def test_the_surveyed_map_breaks_the_dock_span_and_is_refused():
    default = gate.gate(sites.Layout())
    assert default["verdict"] == "unconfirmed" and not default["why"]  # measured-194 default satisfies the dock checks
    result = gate.gate(sites.Layout(arm_bases="surveyed"))
    assert result["verdict"] == "refuse" and result["frame"] == gate.FIXTURE  # one frame, but the plates would sit 174.5 mm apart
    assert any("dock span" in w for w in result["why"])


def test_an_item_that_is_not_measured_never_counts_as_a_second_frame():
    items = gate.provenance(sites.Layout(preset="v24-20261114", belt_pose="fixture", arm_bases="span-190").choices)
    assert items["belt_pose"]["frame"] is None and items["arm_bases"]["frame"] is None
    result = gate.gate(sites.Layout(preset="v24-20261114", belt_pose="fixture"))
    assert result["verdict"] == "unconfirmed" and any("belt_pose (not measured" in u for u in result["unconfirmed"])


def test_real2sim_sim_stops_on_a_refused_map_unless_told(monkeypatch):
    snapshot = "deploy/robot/omx/sim/cell_snapshots/20261110-1231.json"
    started = []
    monkeypatch.setattr(r2s, "sim", lambda *a, **k: started.append(a) or {})
    with pytest.raises(SystemExit, match="contradicts itself"):
        r2s.main(["sim", snapshot, "--sha", "x", "--out", "unused", "--choice", "top_camera=2026-11-10"])  # its own camera moved: Layout refuses that already
    assert not started
    assert r2s.main(["sim", snapshot, "--sha", "x", "--out", "unused", "--choice", "top_camera=2026-11-10", "--unverified-ok"]) == 0 and len(started) == 1


def test_bases_hung_on_the_measured_ship_agree_with_the_bridge_in_an_older_snapshot():
    """No marker sheet is on the plates: the docks tie them to the hull (189.8 mm as measured; 194 is the plan), so the bases follow the ship a frame measured.
    The 11-10 snapshot (another day, another camera pose) then puts each plate's middle lane 200 mm from its arm, as bridge v7 seats it."""
    layout = sites.Layout(cell_snapshot="deploy/robot/omx/sim/cell_snapshots/20261110-1231.json", temp_lanes="snapshot", ship_pose="snapshot",
                          belt_pose="snapshot", top_camera="2026-11-10", arm_bases="docks-photo")
    result = gate.gate(layout)
    assert result["verdict"] == "unconfirmed" and result["frame"] == gate.FIXTURE and all(c["ok"] for c in result["checks"])
    bridge = [c["value_mm"] for c in result["checks"] if c["name"].startswith("bridge v7")]
    assert bridge == pytest.approx([200., 200.], abs=4.)
    assert layout.arms["arm_b"].base[0] == pytest.approx(layout.choices["ship_stern_x_m"] - .0704)
