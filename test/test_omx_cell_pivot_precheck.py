"""cell_pivot_precheck: a pivot-near whose plan would fail its guards is refused before any arm command (2026-11-17)."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_calibrate as cc  # noqa: E402
import cell_pivot  # noqa: E402
import cell_pivot_precheck as pp  # noqa: E402

# arm (x, y) -> pixel (200 + 1000 x, 1000 y): arm (0, 0.2) at (200, 200), arm (0, 0.02) at y 20 (the frame top)
H = [[0.001, 0.0, -0.2], [0.0, 0.001, 0.0], [0.0, 0.0, 1.0]]
CAL = {"sites": {"belt": {"homography": H, "z_view": 0.08}}}


def config(**pivot):
    return {"params": None, "plan": {"approach_m": 0.04}, "coarse": {"z_view": 0.118},
            "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240]}},
            "pivot": {"z_view": 0.08, **pivot}, "sites": {"belt": {"yaw_deg": 0.0, "surface_z": 0.006}}}


@pytest.fixture(autouse=True)
def planned_fk_is_the_commanded_yaw(monkeypatch):
    """No planner here: the above_pick row carries the yaw as wrist_roll and FK reads it back."""
    library = lambda cfg, pick, place, check=True: {"names": ["wrist_roll.pos"], "chunks": {"above_pick": [[pick["yaw_deg"]]]}}
    monkeypatch.setattr(pp.cio, "plan_library", library)
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda state, **kw: (0.0, 0.0, 0.0, float(state[0])))


class Cell:
    def __init__(self):
        self.acts = []

    def frame(self, camera):
        return np.zeros((480, 640, 3), np.uint8)

    def act(self, command):
        self.acts.append(command)
        return {"ok": True}


def run(monkeypatch, cfg, xy):
    calls, cell = [], Cell()
    monkeypatch.setattr(cc, "pivot_point", lambda cell, config, cal, site, near: (list(near), False))
    monkeypatch.setattr(cell_pivot, "pivot_calibrate", lambda cell, config, point, yaws, *a: calls.append(yaws) or {"result": "stopped"})
    step = f"pivot-near belt:{xy[0]},{xy[1]}"
    return cc.pivot_near(cell, cfg, CAL, Path("cal.json"), step, Path(".")), calls, cell, step


def test_a_normal_pivot_passes_unchanged(monkeypatch):
    row, calls, cell, step = run(monkeypatch, config(), (0.0, 0.2))
    assert row[step] == "stopped" and calls == [[-80, -40, 0, 40, 80, 120]]


def test_marks_at_the_frame_top_are_refused_with_no_motion(monkeypatch):
    """arm_b belt end: the jaw mark at pivot_z_view projected to image y 1-23 px, 0 marks."""
    row, calls, cell, step = run(monkeypatch, config(), (0.0, 0.02))
    assert row[step].startswith("precheck refused: ") and "of the 640x480 top frame edge" in row[step]
    assert calls == [] and cell.acts == []


def test_a_short_planned_arc_is_refused_and_the_margin_only_adds():
    short = pp.pivot_precheck(config(), CAL, "belt", (0.0, 0.2), [-50, -20, 20, 50], (640, 480))
    assert short and "planned FK yaw arc 100.0 deg < 110 deg" in short[0]
    assert pp.pivot_precheck(config(), CAL, "belt", (0.0, 0.2), [-60, -20, 20, 60], (640, 480)) == []
    assert pp.pivot_precheck(config(arc_margin_deg=15), CAL, "belt", (0.0, 0.2), [-60, -20, 20, 60], (640, 480))


def test_a_geometry_from_another_height_never_takes_the_shortcut(monkeypatch):
    geometry = {"radius_mm": 19.0, "phase_deg": 53.0, "z_view": 0.12}
    row, calls, cell, step = run(monkeypatch, config(geometry=geometry), (0.0, 0.2))
    assert "pivot.geometry was measured at z_view 0.12 m" in row[step] and calls == [] and cell.acts == []
    near = dict(geometry, z_view=0.083)  # within 5 mm: two yaws are enough for the known geometry
    assert pp.pivot_precheck(config(geometry=near), CAL, "belt", (0.0, 0.2), [0, 40], (640, 480)) == []
    legacy = {"radius_mm": 19.0, "phase_deg": 53.0}  # no height recorded: as before
    assert pp.pivot_precheck(config(geometry=legacy), CAL, "belt", (0.0, 0.2), [0, 40], (640, 480)) == []


def test_missing_joint_limits_are_refused_only_with_the_flag():
    yaws = [-80, -40, 0, 40, 80, 120]
    assert pp.pivot_precheck(config(), CAL, "belt", (0.0, 0.2), yaws, (640, 480)) == []
    assert pp.pivot_precheck(config(require_joint_limits=True), CAL, "belt", (0.0, 0.2), yaws, (640, 480))[0] \
        .startswith("joint limits missing")
    limited = dict(config(require_joint_limits=True), joint_min={"wrist_roll.pos": -100}, joint_max={"wrist_roll.pos": 50})
    problems = pp.pivot_precheck(limited, CAL, "belt", (0.0, 0.2), yaws, (640, 480))
    assert problems == []  # 80 and 120 leave the window and are never commanded; -80..40 still span 120 deg
    tight = dict(limited, joint_max={"wrist_roll.pos": 10})
    refused = pp.pivot_precheck(tight, CAL, "belt", (0.0, 0.2), yaws, (640, 480))
    assert refused and refused[0].startswith("3 of 6 yaws plan inside the window, need 4") and "joint_max 10" in refused[0]


def test_an_unknown_frame_size_is_a_problem_not_a_pass():
    assert "top frame size unknown" in pp.pivot_precheck(config(), CAL, "belt", (0.0, 0.2), [-80, 0, 80, 120])[0]
