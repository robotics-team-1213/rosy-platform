"""Camera alignment viewer: fixed landmarks follow a shifted view and fail closed otherwise."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import camera_alignment_view as cav  # noqa: E402


def scene():
    rng = np.random.default_rng(7)
    img = np.full((480, 640), 128, np.uint8)
    for _ in range(300):
        x, y = int(rng.integers(0, 600)), int(rng.integers(0, 440))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(8, 40)), y + int(rng.integers(8, 40))),
                      int(rng.integers(0, 255)), -1)
    return img


def test_points_follow_translation():
    ref = scene()
    cur = cv2.warpAffine(ref, np.float32([[1, 0, 12], [0, 1, 7]]), (640, 480), borderValue=128)
    found = cav.pairs(ref, cur, [(300, 240)])[0]
    assert found is not None
    assert abs(found[0] - 312) < 2 and abs(found[1] - 247) < 2


def test_fails_closed():
    ref = scene()
    assert cav.pairs(ref, ref[:400], [(300, 240)]) == [None]
    assert cav.pairs(ref, np.full_like(ref, 128), [(300, 240)]) == [None]
    assert cav.pairs(ref, ref, [(2, 2)]) == [None]  # patch outside the image


def test_invalid_reference_rejected(tmp_path):
    (tmp_path / "bad.jpg").write_bytes(b"nope")
    profiles = tmp_path / "p.json"
    profiles.write_text('[{"name":"x","view":"v","reference":"bad.jpg","points":[]}]')
    with pytest.raises(ValueError):
        cav.load_profiles(profiles)
