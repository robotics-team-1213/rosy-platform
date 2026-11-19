"""cell_device_intrinsics: a camera's factory K becomes a D-933 record only when tilted board frames of the same stream
find that K on their own; one-pose frames, another stream's K and a non-OpenCV distortion model are refused."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_checkerboard as cb  # noqa: E402
import cell_device_intrinsics as di  # noqa: E402
import cell_frame as cf  # noqa: E402

K = np.array([[618.5, 0, 322.3], [0, 618.7, 236.6], [0, 0, 1.0]])  # the cell D435's 640x480 colour stream
PPM = 2000
ART = cv2.copyMakeBorder(cb.charuco_image((int(0.14 * PPM), int(0.20 * PPM))), 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
TO_M = np.array([[1 / PPM, 0, -30 / PPM], [0, 1 / PPM, -30 / PPM], [0, 0, 1]])
FACTORY = {"kind": "device_factory", "device": "Intel RealSense D435", "serial": "0", "firmware": "5.17.0.10",
           "stream": "color", "size": [640, 480], "fps": 30, "K": K.tolist(), "model": "inverse_brown_conrady",
           "coeffs": [0.0] * 5}
BINDING = {"viewer_label": "top", "topic": "/top_camera/image_raw", "role": "top",
           "device_alias": "/dev/v4l/by-path/test", "usb_id": "8086:0b07", "usb_port": "1-2",
           "usb_interface": "1-2:1.0", "serial": "0", "focus_controls": {},
           "unique_hardware_identity": True, "viewer_invocation_id": "session-1",
           "producer_invocation_id": "producer-1"}


SPOTS = [(x, y) for x in (150, 320, 490) for y in (140, 240, 340)]  # board centres across the image


def frames(folder, tilts, spin_deg=4.0):
    folder.mkdir()
    for n, (tx, ty) in enumerate(tilts):
        R = cv2.Rodrigues(np.radians([tx, ty, spin_deg * n]))[0]
        spot = SPOTS[n % len(SPOTS)]
        ray = np.linalg.solve(K, [spot[0], spot[1], 1.0])
        t = ray * 0.5 / ray[2] + [0.0003 * n, 0, 0] - R @ [0.07, 0.10, 0]  # a hair apart: no two frames byte-equal
        image = cv2.warpPerspective(ART, K @ np.column_stack([R[:, 0], R[:, 1], t]) @ TO_M, (640, 480), borderValue=200)
        path = folder / f"view-{n:03d}.png"
        cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
        path.with_suffix(".json").write_text(json.dumps({"camera": "top", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                         "source_seq": n, "source_stamp": float(n + 1),
                                                         "device_binding": BINDING}))
    return folder


def test_tilted_frames_confirm_the_factory_k_and_cell_frame_accepts_the_record(tmp_path, monkeypatch):
    monkeypatch.setattr(cf, "live_camera_binding", lambda camera, **kwargs: BINDING)
    tilted = frames(tmp_path / "tilted", [(a, b) for a in (-25, -12, 0, 12, 25) for b in (-25, -12, 0, 12, 25)][:25] + [(20, 20)])
    out = di.verify(tilted, "top", FACTORY, 50.0)
    assert out["accepted"] is True, out["checks"]
    assert all(fit["f_off"] < 0.02 for fit in out["checks"]["independent_fits"])
    assert out["source"]["kind"] == "device_factory"
    K_read, dist, size = cf.validated_intrinsics(out)
    assert np.allclose(K_read, K) and not dist.any() and size == [640, 480]
    wrong_serial = di.verify(tilted, "top", dict(FACTORY, serial="another-camera"), 50.0)
    assert wrong_serial["accepted"] is False
    assert "factory_camera_serial_differs_from_frames" in wrong_serial["checks"]["reasons"]

    other_stream = dict(FACTORY, K=[[927.8, 0, 643.5], [0, 928.0, 354.9], [0, 0, 1]])
    assert "rms_above_0_5_px" in di.verify(tilted, "top", other_stream, 50.0)["checks"]["reasons"]
    distorted = dict(FACTORY, coeffs=[0.1, 0, 0, 0, 0])
    assert di.verify(tilted, "top", distorted, 50.0)["checks"]["reasons"] == ["factory_distortion_model_not_opencv"]
    wide = dict(FACTORY, size=[1280, 720])
    assert di.verify(tilted, "top", wide, 50.0)["checks"]["reasons"] == ["frame_size_differs_from_factory_stream"]


def test_one_tilt_across_the_image_cannot_confirm_a_k(tmp_path):
    flat = frames(tmp_path / "flat", [(10, 0)] * 27, spin_deg=0.0)  # parallel planes: f is not observable
    out = di.verify(flat, "top", FACTORY, 50.0)
    assert out["checks"]["rms_px"] < 0.5  # the fixed K explains them, as any nearby K would
    assert out["accepted"] is False and out["checks"]["reasons"] == ["frames_do_not_reproduce_factory_k"]
    with pytest.raises(ValueError, match="CALIBRATION_REQUIRED"):
        cf.validated_intrinsics(out)
    with pytest.raises(ValueError, match="five coefficients"):
        di.verify(flat, "top", {key: value for key, value in FACTORY.items() if key != "coeffs"}, 50.0)
    with pytest.raises(ValueError, match="Brown-Conrady"):
        di.verify(flat, "top", dict(FACTORY, model="ftheta"), 50.0)


def test_frames_in_one_spot_do_not_vouch_for_the_image_edges(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "SPOTS", [(320, 240)])
    centre = frames(tmp_path / "centre", [(a, b) for a in (-25, 0, 25) for b in (-25, 0, 25)] * 3)
    assert di.verify(centre, "top", FACTORY, 50.0)["checks"]["reasons"] == ["board_not_seen_across_image"]
