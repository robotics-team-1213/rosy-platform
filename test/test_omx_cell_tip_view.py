"""cell_tip_view: the stopped jaw tip lands where the frames show the jaws, and a stop keeps a crop around it."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_tip_view as tv  # noqa: E402

# arm_b and the top and side cameras as surveyed 2026-11-03 (learning/envs/isaac/cell_model_inventory.yaml layout)
SPEC = {"base": {"xy": [0.104, 0.153], "yaw_deg": -94.3, "z": 0.084},
        "cameras": {"top": {"eye": [-0.0411, 0.0374, 0.6652], "focus": [0.0722, 0.0401, 0.1783], "up": [0.974, 0.0071, 0.2266], "f_px": 615},
                    "side": {"eye": [-0.5078, 0.0019, 0.1471], "focus": [-0.0082, -0.0166, 0.1445], "up": [0.0061, 0.0257, 0.9997], "f_px": 950}}}
STOP_0017 = (0.065, -0.1068, 0.0155)  # arm_b's tip at the 2026-11-07 00:17 descent stop (FK of the trace, TCP 0.0740)


def test_a_camera_sees_its_focus_at_the_centre():
    for camera in SPEC["cameras"].values():
        assert np.allclose(tv.project(camera, camera["focus"]), (320, 240))


@pytest.mark.parametrize("view, uv", [("top", (258, 345)), ("side", (102, 321))])
def test_the_0017_stop_lands_where_the_frames_show_the_jaws(view, uv):
    """Checked by eye on that stop's frames. A base at the table-top z 0 instead of 0.084 put the side tip 137 px low."""
    assert np.allclose(tv.project(SPEC["cameras"][view], tv.to_cell(STOP_0017, SPEC["base"])), uv, atol=2)


def test_a_crop_is_centred_on_the_tip_even_at_the_edge():
    frame = np.zeros((480, 640, 3), np.uint8)
    frame[0:10, 0:10] = 255
    out = tv.crop(frame, (3, 3), 20)
    assert out.shape == (40, 40, 3) and out[20, 20].tolist() == [255, 255, 255]  # the corner pixel sits at the centre


def test_a_stop_keeps_a_crop_around_the_tip_per_surveyed_camera(monkeypatch, tmp_path):
    import cell_hooks
    import omx_incident

    class Cell:
        def frame(self, camera):
            return np.full((480, 640, 3), 90, np.uint8)

    monkeypatch.setattr(omx_incident, "STILLS", tmp_path)
    monkeypatch.setattr(tv, "fk_tip", lambda state: STOP_0017)
    config = {"arm_id": "arm_b", "cameras": {"top": {}, "side": {}, "wrist": {}}, "tip_view": SPEC}
    cell_hooks.stills(Cell(), config)([0] * 6)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["arm_b-side-tip.jpg", "arm_b-side.jpg", "arm_b-top-tip.jpg",
                                                          "arm_b-top.jpg", "arm_b-wrist.jpg"]
    for p in tmp_path.iterdir():
        p.unlink()
    cell_hooks.stills(Cell(), {k: v for k, v in config.items() if k != "tip_view"})([0] * 6)  # no survey: the frames only
    assert not any(p.name.endswith("-tip.jpg") for p in tmp_path.iterdir())
