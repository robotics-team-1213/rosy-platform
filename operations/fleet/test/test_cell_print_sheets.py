"""Calibration print sheets: real-size vector PDF of ArUco gripper markers and a checkerboard, served read-only."""
import base64
import re

import pytest

from fleet.server.cell_print_sheets import (A4_MM, DICT_4X4_100, PT_PER_MM, arm_ids, charuco_pdf, checkerboard_pdf, marker_cells,
                                            markers_pdf, sheet)
from test_cell_job_api import _setup


def boxes(pdf: bytes):
    """Filled rectangles (x, y, w, h) in mm from the content stream."""
    return [tuple(float(v) / PT_PER_MM for v in m.groups())
            for m in re.finditer(rb"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re f", pdf)]


def test_the_pdf_is_well_formed_with_a_true_a4_page():
    pdf = markers_pdf([0], [20])
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    xref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
    assert pdf[xref:xref + 4] == b"xref"
    for i, offset in enumerate(re.findall(rb"(\d{10}) 00000 n", pdf), 1):  # every object where the table says
        assert pdf[int(offset):].startswith(f"{i} 0 obj".encode())
    assert b"/MediaBox [0 0 595.276 841.890]" in pdf


def test_marker_cells_follow_the_dictionary_bits_and_the_print_is_to_size():
    cells = marker_cells(0)
    assert len(cells) == 20 + 16 - bin(DICT_4X4_100[0]).count("1")  # border + the bits that are black
    assert (1, 1) in cells if not DICT_4X4_100[0] >> 15 & 1 else (1, 1) not in cells
    printed = [b for b in boxes(markers_pdf([0], [20])) if b[2] < 10]  # marker cells (the scale bar is 50 mm)
    assert len(printed) == len(cells) and all(b[2] == pytest.approx(20 / 6, abs=1e-3) for b in printed)
    xs, ys = [b[0] for b in printed], [b[1] for b in printed]
    assert max(xs) + 20 / 6 - min(xs) == pytest.approx(20.0, abs=1e-3)  # the black square is 20 mm
    assert max(ys) + 20 / 6 - min(ys) == pytest.approx(20.0, abs=1e-3)
    assert any(b[2] == pytest.approx(50.0, abs=1e-3) for b in boxes(markers_pdf([0], [20])))  # the check bar


def test_checkerboard_squares_and_bad_input():
    squares = [b for b in boxes(checkerboard_pdf(8, 6, 15)) if b[2] == pytest.approx(15.0, abs=1e-3)]
    assert len(squares) == 24
    with pytest.raises(ValueError):
        markers_pdf([100], [20])
    with pytest.raises(ValueError):
        sheet("arm-markers", arm=5)
    with pytest.raises(ValueError):
        checkerboard_pdf(20, 6, 15)  # 300 mm wide does not fit A4
    with pytest.raises(ValueError):
        sheet("poster")


def test_a_viewer_downloads_a_sheet_and_bad_parameters_are_refused(tmp_path):
    client, _, _ = _setup(tmp_path)
    viewer = {"Authorization": "Bearer viewer-secret"}
    response = client.get("/api/fleet/cell-app/print-sheets/gripper-markers?ids=0&sizes_mm=20", headers=viewer)
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "rosy-gripper-markers.pdf" and body["media_type"] == "application/pdf"
    assert base64.b64decode(body["pdf_base64"]).startswith(b"%PDF")
    assert client.get("/api/fleet/cell-app/print-sheets/checkerboard").status_code == 401
    bad = client.get("/api/fleet/cell-app/print-sheets/gripper-markers?ids=0&sizes_mm=200", headers=viewer)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "CELL_PRINT_SHEET_INVALID"


def raster(pdf: bytes, px_per_mm: float = 300 / 25.4):
    """The filled boxes of a sheet drawn at 300 dpi: what a 100 % print shows (white paper, black boxes)."""
    np = pytest.importorskip("numpy")
    img = np.full((round(A4_MM[1] * px_per_mm), round(A4_MM[0] * px_per_mm)), 255, np.uint8)
    for x, y, w, h in boxes(pdf):
        top = A4_MM[1] - y - h  # PDF y grows up from the bottom edge
        img[round(top * px_per_mm):round((top + h) * px_per_mm), round(x * px_per_mm):round((x + w) * px_per_mm)] = 0
    return img


def test_the_charuco_sheet_is_the_opencv_board_at_true_size():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    aruco = cv2.aruco
    board = aruco.CharucoBoard((7, 10), 0.020, 0.015, aruco.getPredefinedDictionary(aruco.DICT_4X4_50))
    corners, ids, _, _ = aruco.CharucoDetector(board).detectBoard(raster(charuco_pdf()))
    assert ids is not None and len(ids) == 54  # every inner corner, so the layout and id order are OpenCV's
    pts = {int(i): p for i, p in zip(ids.ravel(), corners.reshape(-1, 2))}
    pitch = np.linalg.norm(pts[5] - pts[0]) / 5 / (300 / 25.4)  # corners 0..5 run along the first row
    assert pitch == pytest.approx(20.0, abs=0.1)


def test_arm_slots_own_disjoint_id_blocks_outside_the_charuco_board():
    blocks = [arm_ids(n) for n in range(1, 5)]
    flat = [[b["gripper"], *b["base"], *[i for ids in b["surfaces"] for i in ids]] for b in blocks]
    every = [i for ids in flat for i in ids]
    assert len(every) == len(set(every)) == 60 and min(every) == 35 and max(every) < len(DICT_4X4_100)
    assert [b["gripper"] for b in blocks] == [35, 50, 65, 80]


@pytest.mark.parametrize("slot", [1, 4])
def test_an_arm_sheet_reads_back_as_its_block_at_true_size(slot):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    name, pdf = sheet("arm-markers", arm=slot)
    assert name == f"rosy-arm-{slot}-markers.pdf"
    block = arm_ids(slot)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100))
    corners, ids, _ = detector.detectMarkers(raster(pdf))
    assert sorted(ids.ravel().tolist()) == list(range(block["gripper"], block["gripper"] + 15))
    sides = {int(i): np.linalg.norm(c[0][1] - c[0][0]) / (300 / 25.4) for c, i in zip(corners, ids.ravel())}
    assert sides.pop(block["gripper"]) == pytest.approx(20.0, abs=0.2)
    cuts = [float(v) / PT_PER_MM for v in re.findall(rb"[\d.]+ [\d.]+ ([\d.]+) [\d.]+ re S", pdf)]
    assert sorted(cuts) == pytest.approx([20 * 4 / 3] + [25 * 4 / 3] * 14, abs=1e-3)  # one cut square per marker
    assert all(s == pytest.approx(25.0, abs=0.2) for s in sides.values())
