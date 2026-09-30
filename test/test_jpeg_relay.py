"""Bench JPEG relay: pure encode/decimation parts, host-testable without rclpy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
RELAY = ROOT / "deploy" / "robot" / "pinky_pro" / "dev" / "jpeg_relay.py"

SPEC = importlib.util.spec_from_file_location("jpeg_relay", RELAY)
assert SPEC and SPEC.loader
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


def _frame(h: int = 240, w: int = 320) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, : w // 2] = (255, 0, 0)  # blue left half in BGR
    img[:, w // 2 :] = (0, 0, 255)  # red right half in BGR
    return img


@pytest.mark.parametrize("backend", ["cv2", "auto"])
def test_bgr8_roundtrip_keeps_colour_order(backend: str) -> None:
    img = _frame()
    jpg = relay.encode_jpeg(img.tobytes(), 320, 240, 320 * 3, "bgr8", 85, backend=backend)
    assert jpg[:2] == b"\xff\xd8"
    out = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert out.shape == (240, 320, 3)
    assert out[120, 40, 0] > 200 and out[120, 40, 2] < 50
    assert out[120, 280, 2] > 200 and out[120, 280, 0] < 50
    assert len(jpg) < img.nbytes // 5


def test_rgb8_is_converted_to_bgr_order() -> None:
    img = _frame()[:, :, ::-1].copy()  # same picture stored as RGB
    jpg = relay.encode_jpeg(img.tobytes(), 320, 240, 320 * 3, "rgb8", 85, backend="cv2")
    out = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert out[120, 40, 0] > 200  # left still blue once decoded as BGR


def test_mono8_and_row_padding() -> None:
    step = 328  # padded rows
    buf = np.full((240, step), 7, dtype=np.uint8)
    buf[:, :320] = 200
    jpg = relay.encode_jpeg(buf.tobytes(), 320, 240, step, "mono8", 85, backend="cv2")
    out = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert out.shape == (240, 320)
    assert abs(int(out.mean()) - 200) <= 2


def test_unsupported_encoding_raises() -> None:
    with pytest.raises(ValueError):
        relay.encode_jpeg(b"\0" * 12, 2, 2, 6, "yuv422", 85, backend="cv2")


def test_decimator_default_passes_everything() -> None:
    d = relay.Decimator(0.0)
    assert all(d.accept(i * 0.01) for i in range(100))


def test_decimator_caps_rate() -> None:
    d = relay.Decimator(2.0)
    kept = sum(d.accept(i / 8.0) for i in range(80))  # 10 s at 8 fps
    assert 19 <= kept <= 21
