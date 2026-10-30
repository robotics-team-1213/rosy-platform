"""cell_marks: a 20 mm marker at the top camera's scale is found in one frame, with its centre and yaw."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
if not hasattr(cv2, "aruco"):
    pytest.skip("OpenCV without aruco", allow_module_level=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_marks  # noqa: E402


def scene_with(marker_id: int, mm: float, angle: float, centre=(320.0, 240.0), px_per_mm: float = 1.1):
    draw_marker = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    big = draw_marker(cell_marks._dictionary(), marker_id, 600)
    big = cv2.copyMakeBorder(big, 100, 100, 100, 100, cv2.BORDER_CONSTANT, value=255)
    M = cv2.getRotationMatrix2D((400, 400), angle, px_per_mm * mm / 600)
    M[:, 2] += (centre[0] - 400, centre[1] - 400)
    scene = np.full((480, 640), 90, np.uint8)
    inside = cv2.warpAffine(np.full_like(big, 255), M, (640, 480)) > 0
    scene[inside] = cv2.warpAffine(big, M, (640, 480), flags=cv2.INTER_AREA)[inside]
    scene = cv2.GaussianBlur(scene, (3, 3), 0.8)
    return cv2.imdecode(cv2.imencode(".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, 80])[1], cv2.IMREAD_GRAYSCALE)


def test_a_20_mm_marker_at_the_top_cameras_scale_gives_centre_and_yaw():
    seen = cell_marks.find(scene_with(1, 20, 30.0, centre=(300.0, 250.0)))
    assert set(seen) == {1}
    assert seen[1]["centre_px"] == pytest.approx([300.0, 250.0], abs=1.0)
    assert seen[1]["side_px"] == pytest.approx(22, abs=2)
    # getRotationMatrix2D turns counter-clockwise on screen: the top edge points at -30 deg in image coordinates
    assert seen[1]["yaw_deg"] == pytest.approx(-30.0, abs=4)


def test_the_print_sheet_holds_each_id_at_each_size_and_reads_back():
    page = cell_marks.sheet((20,), (0, 3), dpi=150)
    assert page.shape == (round(297 * 150 / 25.4), round(210 * 150 / 25.4))
    assert set(cell_marks.find(page)) == {0, 3}
