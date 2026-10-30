"""Calibration print sheets: real-size vector PDF of ArUco gripper markers and a checkerboard, served read-only."""
import base64
import re

import pytest

from fleet.server.cell_print_sheets import DICT_4X4_50, PT_PER_MM, checkerboard_pdf, marker_cells, markers_pdf, sheet
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
    assert len(cells) == 20 + 16 - bin(DICT_4X4_50[0]).count("1")  # border + the bits that are black
    assert (1, 1) in cells if not DICT_4X4_50[0] >> 15 & 1 else (1, 1) not in cells
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
        markers_pdf([50], [20])
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
