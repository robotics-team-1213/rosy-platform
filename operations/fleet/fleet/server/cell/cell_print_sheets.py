"""Printable calibration sheets for a work cell, as vector PDF at exact size (2026-10-30).

The arm cell needs printed targets: an ArUco marker on the gripper (the top camera finds it in one frame, 15 mm and up
measured 20/20 within 0.4 px at 1.1 px/mm) and a checkerboard for the cameras' geometry. A raster image printed
through a viewer's "fit to page" comes out scaled; here every square is a PDF rectangle in millimetres on an A4 page,
with a 50 mm bar to check the print with a ruler. No dependency: the ArUco DICT_4X4_50 bit patterns are a table
(extracted from OpenCV 4.12 ``generateImageMarker``; bit 1 = white, row-major from the top-left).
"""

from __future__ import annotations

A4_MM = (210.0, 297.0)
PT_PER_MM = 72 / 25.4
DICT_4X4_50 = (
    46386, 3994, 13101, 39238, 21662, 31181, 40494, 50418, 65242, 53078, 63889, 4519, 3767, 10767, 9393, 9790, 18021,
    26112, 27742, 30383, 34443, 45099, 52437, 56706, 65095, 38001, 44260, 42324, 8483, 13423, 17429, 22450, 40655,
    61643, 2222, 2345, 6261, 1279, 3574, 7258, 5912, 10792, 12940, 14514, 9448, 12011, 11583, 19300, 20526, 20499)
MARGIN_MM, GAP_MM = 15.0, 12.0


class Page:
    """Drawing in millimetres from the page's top-left; emitted as one PDF content stream."""

    def __init__(self):
        self.ops = []

    def box(self, x, y, w, h, fill=True, dash=False):
        X, Y = x * PT_PER_MM, (A4_MM[1] - y - h) * PT_PER_MM
        stroke = "[2 2] 0 d 0.3 w" if dash else "[] 0 d 0.5 w"
        self.ops.append(f"{X:.3f} {Y:.3f} {w * PT_PER_MM:.3f} {h * PT_PER_MM:.3f} re f" if fill else
                        f"{stroke} {X:.3f} {Y:.3f} {w * PT_PER_MM:.3f} {h * PT_PER_MM:.3f} re S")

    def text(self, x, y, size_pt, s):
        s = s.encode("ascii", "replace").decode().replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        self.ops.append(f"BT /F1 {size_pt} Tf {x * PT_PER_MM:.3f} {(A4_MM[1] - y) * PT_PER_MM:.3f} Td ({s}) Tj ET")

    def scale_bar(self, y):
        self.box(MARGIN_MM, y, 50.0, 2.0)
        self.text(MARGIN_MM, y + 7, 9, "This bar must measure 50 mm. If not, print again at 100 % (actual size), no fit-to-page.")

    def pdf(self, title: str) -> bytes:
        content = "\n".join(["0 g 0 G"] + self.ops).encode()
        w, h = A4_MM[0] * PT_PER_MM, A4_MM[1] * PT_PER_MM
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
                   b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.3f} {h:.3f}] /Resources << /Font << /F1 5 0 R >> >> "
                   f"/Contents 4 0 R >>".encode(),
                   b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                   b"<< /Title (" + title.encode("ascii", "replace") + b") /Producer (ROSY cell print sheets) >>"]
        out, offsets = bytearray(b"%PDF-1.4\n"), []
        for i, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


def marker_cells(marker_id: int) -> list[tuple[int, int]]:
    """Black cells (row, col) of a 6 x 6 marker: the 1-cell black border plus the 4 x 4 bits that are 0."""
    bits = DICT_4X4_50[marker_id]
    inner = [(1 + k // 4, 1 + k % 4) for k in range(16) if not (bits >> (15 - k)) & 1]
    return [(r, c) for r in range(6) for c in range(6) if r in (0, 5) or c in (0, 5)] + inner


GRIPPER = ("ROSY gripper markers - ArUco DICT_4X4_50",
           "Cut on the dashed line, keep the white edge. Glue flat on the gripper body's top face (id 0, 20 mm).")
SURFACE = ("ROSY surface markers - ArUco DICT_4X4_50 (D-933)",
           "Arm base: ids 35-36. Each surface: 4 markers, at least 150 mm apart, not in one line. Glue flat.")


def markers_pdf(ids, sizes_mm, words=GRIPPER) -> bytes:
    ids, sizes = [int(i) for i in ids], [float(s) for s in sizes_mm]
    if not ids or not sizes or any(not 0 <= i < len(DICT_4X4_50) for i in ids) or any(not 10 <= s <= 80 for s in sizes):
        raise ValueError("ids are 0-49 and sizes 10-80 mm")
    page, y = Page(), MARGIN_MM
    page.text(MARGIN_MM, y + 5, 14, words[0])
    page.text(MARGIN_MM, y + 11, 9, words[1])
    y += 18
    page.scale_bar(y)
    y += 16
    for size in sizes:
        quiet = size / 6  # one cell of white around the black border, inside the cut line
        x = MARGIN_MM
        for marker_id in ids:
            if x + size + 2 * quiet > A4_MM[0] - MARGIN_MM:
                x, y = MARGIN_MM, y + size + 2 * quiet + GAP_MM
            if y + size + 2 * quiet + 8 > A4_MM[1] - MARGIN_MM:
                raise ValueError("too many markers for one page")
            cell = size / 6
            for r, c in marker_cells(marker_id):
                page.box(x + quiet + c * cell, y + quiet + r * cell, cell, cell)
            page.box(x, y, size + 2 * quiet, size + 2 * quiet, fill=False, dash=True)
            page.text(x, y + size + 2 * quiet + 5, 9, f"id {marker_id}  {size:g} mm")
            x += size + 2 * quiet + GAP_MM
        y += size + 2 * quiet + GAP_MM
    return page.pdf(words[0].split(" - ")[0])


def charuco_pdf() -> bytes:
    """OpenCV 4.12 CharucoBoard((7, 10), 0.020, 0.015, DICT_4X4_50), 140 x 200 mm: the top-left square black,
    markers centred on the white squares with ids 0-34 row by row from the top-left (D-933 lens calibration)."""
    cols, rows, square, side = 7, 10, 20.0, 15.0
    page, y = Page(), MARGIN_MM
    page.text(MARGIN_MM, y + 5, 14, "ROSY ChArUco board - 7 x 10 squares (D-933)")
    page.text(MARGIN_MM, y + 11, 9, "squares 20 mm, markers 15 mm, DICT_4X4_50 ids 0-34. Matte paper on a flat rigid board; tilt it 20-40 deg.")
    y += 18
    page.scale_bar(y)
    y += 16
    x, marker_id, cell = (A4_MM[0] - cols * square) / 2, 0, side / 6
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                page.box(x + c * square, y + r * square, square, square)
                continue
            mx, my = x + c * square + (square - side) / 2, y + r * square + (square - side) / 2
            for mr, mc in marker_cells(marker_id):
                page.box(mx + mc * cell, my + mr * cell, cell, cell)
            marker_id += 1
    return page.pdf("ROSY ChArUco board")


def checkerboard_pdf(cols: int = 8, rows: int = 6, square_mm: float = 15.0) -> bytes:
    """cols x rows squares (inner corners cols-1 x rows-1), the top-left square black; 8 x 6 x 15 mm is
    cell_checkerboard's wrist-camera board."""
    cols, rows, square = int(cols), int(rows), float(square_mm)
    if cols < 3 or rows < 3 or not 5 <= square <= 60 or cols * square > A4_MM[0] - 2 * MARGIN_MM or \
            rows * square > A4_MM[1] - 2 * MARGIN_MM - 50:
        raise ValueError("the board must fit an A4 page (at least 3 x 3 squares of 5-60 mm)")
    page, y = Page(), MARGIN_MM
    page.text(MARGIN_MM, y + 5, 14, f"ROSY checkerboard - {cols - 1} x {rows - 1} inner corners, {square:g} mm squares")
    page.text(MARGIN_MM, y + 11, 9, "Glue on a flat rigid board, matte paper. Lay it flat on the floor for the camera calibration.")
    y += 18
    page.scale_bar(y)
    y += 16
    x = (A4_MM[0] - cols * square) / 2
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                page.box(x + c * square, y + r * square, square, square)
    return page.pdf("ROSY checkerboard")


SHEETS = {"gripper-markers": "ArUco markers for the gripper", "checkerboard": "checkerboard for camera calibration",
          "charuco": "ChArUco board for lens calibration", "surface-markers": "ArUco markers for the arm base and surfaces"}


def sheet(kind: str, ids=(0, 1), sizes_mm=(20, 25), cols: int = 8, rows: int = 6, square_mm: float = 15.0):
    """(file name, PDF bytes) for one kind in SHEETS."""
    if kind == "gripper-markers":
        return "rosy-gripper-markers.pdf", markers_pdf(ids, sizes_mm)
    if kind == "charuco":
        return "rosy-charuco-7x10-20mm.pdf", charuco_pdf()
    if kind == "surface-markers":
        return "rosy-surface-markers-25mm.pdf", markers_pdf(ids, (25,), SURFACE)
    if kind == "checkerboard":
        return f"rosy-checkerboard-{cols}x{rows}-{square_mm:g}mm.pdf", checkerboard_pdf(cols, rows, square_mm)
    raise ValueError(f"unknown sheet {kind}: one of {', '.join(SHEETS)}")
