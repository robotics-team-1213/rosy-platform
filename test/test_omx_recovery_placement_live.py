"""A held load can be released only at a measured touchdown and home needs visual confirmation."""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "deploy/robot/omx"), str(ROOT / "contracts/foundation"), str(ROOT / "middleware/devices/omx/adapter")]

import cell_recovery_placement_live as live  # noqa: E402


class Runner:
    def __init__(self, touchdown_x):
        self.commands = []
        self.sha = "a" * 64
        self.x = 0
        self.touchdown_x = touchdown_x
        self.held = True
        self.session = {"session_id": "session", "scope": "hardware", "sha256": "c" * 64}

    def act(self, cmd):
        if cmd == "state":
            return {"ok": True, "t": time.time(), "library_sha256": self.sha, "operating_context": self.session,
                    "state": [self.x, 0, 0, 0, 0, 53 if self.held else 58],
                    "target": [self.x, 0, 0, 0, 0, 47 if self.held else 58],
                    "human_hold_latched": False, "holding": self.held}
        self.commands.append(cmd)
        assert cmd == f"checked session {'a' * 64} load original.json"
        self.sha = "a" * 64
        return {"ok": True}

    def checked(self, cmd, gate, timeout=None):
        self.commands.append(cmd)
        if cmd.startswith("load "):
            assert Path(cmd[5:]).is_file()
            self.sha = gate["library_sha256"]
        elif cmd == "run descend_place":
            self.x = self.touchdown_x
        elif cmd == "run release_place":
            self.held = False
        elif cmd == "run lift_place":
            self.x = 0
        return {"ok": True, "settled": True}


@pytest.mark.parametrize(("touchdown", "observed", "occluded", "supported_z", "released", "verified"),
                         [(0.03, True, False, 0, False, False), (0.01, False, False, 0, True, False),
                          (0.01, True, False, -0.0002, False, False), (0.01, True, True, 0, False, False),
                          (0.01, True, False, 0, True, True)])
def test_place_readback_and_after_frame(tmp_path, monkeypatch, touchdown, observed, occluded, supported_z, released, verified):
    import cell_recovery_placement_live_view
    import cell_zone_verification

    backend = object.__new__(live.LivePlacement)
    backend.cell = Runner(touchdown)
    backend.session = backend.cell.session
    backend.target = [0, 0, 0, 0, 0, 47]
    backend.lib_sha = backend.cell.sha
    backend.before = {"camera": "top", "source_seq": 21}
    backend.config = {"work_dir": str(tmp_path), "sites": {"floor": {"auto_roi": [0, 0, 30, 30], "place": [0.01, 0]}}}
    backend.args = SimpleNamespace(library=Path("original.json"))
    backend.cargo, backend.catalog, backend.calibration = {"object_id": "cube", "source_height_evidence_error_m": 0.0002}, [], {}
    backend.ref = object()
    backend._xyz = lambda state: state[:3]
    backend._tilt_error = lambda state: 0
    backend.available = backend.reserve = lambda c: True
    backend.diagnostics = {"floor": {"reason": "target_occluded"}}
    backend._empty_view = lambda c, s, after: None if occluded else {"camera": "top", "source_seq": 22}
    def capture(cell, cam, previous, after):
        assert "run lift_place" in cell.commands and previous["source_seq"] == 21 and after > 0
        return {"image": object(), "source_seq": 23, "camera": cam}, None
    monkeypatch.setattr(cell_zone_verification, "_frame", capture)
    monkeypatch.setattr(cell_recovery_placement_live_view, "verify_arrival", lambda *a: {"verified": observed})
    frame = [0, 0, 0, 0, 0, 58]
    cand = {"target": "floor", "surface": {"status": "matched_contact"}, "target_xyz_m": [0.01, 0, 0],
            "seated_z_m": [-0.001, supported_z],
            "library": {"chunks": {k: [frame] for k in ("above_place", "release_place", "lift_place")}},
            "assessment": {"library_sha256": "b" * 64, "session_id": "session"}}
    out = backend._place(cand)
    assert out["released"] is released and out["verified"] is verified
    assert ("run release_place" in backend.cell.commands) is released
    if occluded:
        assert out["reason"] == "target_occluded" and "run descend_place" not in backend.cell.commands
    assert (backend.cell.sha == backend.lib_sha) is verified
    if verified:
        assert out["after"]["source_seq"] > out["before"]["source_seq"]
        assert out["touchdown_xyz_m"] == cand["target_xyz_m"]


def test_no_cargo_or_movable_support_cannot_be_selected():
    with pytest.raises(ValueError, match="CARGO_UNKNOWN"):
        live.build_backend(None, None, {"placement_context": None}, None)
    assert live._fixed_site("floor", "arm_s") and live._fixed_site("board", "arm_s")
    assert not live._fixed_site("pinky", "arm_s") and not live._fixed_site("belt", "arm_a")
    assert not live._fixed_site("temp_plate_b", "arm_a") and live._fixed_site("temp_plate_b", "arm_b")
    # a designated slot is registered under its base name; site_surface must accept it for its own arms only
    assert live._fixed_site("ship-h1r0", "arm_a") and live._fixed_site("ship-h1r0", "arm_b")
    assert not live._fixed_site("ship-h1r0", "arm_s") and not live._fixed_site("ship-h9r9", "arm_a")


def test_touchdown_at_nominal_height_can_still_be_in_air():
    source = {"source_tier": 1, "object_id": "cube", "surface": {"status": "matched_contact"}}
    cargo = {"object_id": "cube", "grasp_above_base_m": 0.02, "source_contact": source,
             "source_height_evidence_error_m": 0.0003}
    surface = {"status": "matched_contact", "measured_z_m": 0.01, "repeatability_m": 0.0001}
    limits = live._seating_limits(cargo, surface)
    assert limits == pytest.approx([0.0279, 0.0296])
    candidate = {"target_xyz_m": [0, 0, 0.03], "seated_z_m": limits}
    assert not live._seated([0, 0, 0.03], candidate)
    assert live._seated([0, 0, 0.0295], candidate)
    assert not live._seated([0, 0, 0.027], candidate)
    assert live._seating_limits({**cargo, "source_height_evidence_error_m": 0.002}, surface) is None
    assert live._seating_limits({**cargo, "source_contact": {}}, surface) is None


@pytest.mark.parametrize(("obstacle", "arm_x", "reason"), [(False, 0.04, None), (True, 0.04, "target_occupied"),
                                                          (False, 0.0, "target_occluded")])
def test_entire_footprint_visible_and_empty(monkeypatch, obstacle, arm_x, reason):
    import numpy as np
    import cell_recovery_placement_live_view as view

    cfg = {"sites": {"board": {"place": [0, 0], "surface_z": 0, "z": 0, "yaw_deg": 0, "surface_lab": [196, 128, 128],
                               "auto_roi": [0, 0, 100, 100], "surface_px": [[4, 4], [96, 4], [96, 96], [4, 96]]}},
           "params": {"place.margin_mm": 1}, "cameras": {"top": {"height_m": 1, "center_px": [50, 50]}}}
    monkeypatch.setattr(view, "predicted_pixel", lambda cfg, cal, site, pt: (50 + 1000 * pt[0], 50 + 1000 * pt[1]))
    monkeypatch.setattr(view, "capsules", lambda *a, **kw: [((arm_x, 0, 0.04), (arm_x, 0, 0.08), 0.001)])
    image = np.full((100, 100, 3), 190, np.uint8)
    if obstacle:
        image[46:56, 46:56] = (0, 0, 180)
    cargo = {"length_mm": 12, "width_mm": 12, "held_axis_deg": 0, "grasp_above_base_m": 0.002}
    assert view.empty_surface(cfg, {}, "board", cargo, {"top_height_mm": 8}, None, [0] * 6, image) == reason
    del cfg["sites"]["board"]["surface_lab"]
    assert view.empty_surface(cfg, {}, "board", cargo, {"top_height_mm": 8}, None, [0] * 6, image) == "surface_colour_unmeasured"
