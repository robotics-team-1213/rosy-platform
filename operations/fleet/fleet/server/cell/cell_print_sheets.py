"""Printable calibration sheets for a work cell, as vector PDF at exact size (2026-10-30).

The arm cell needs printed targets: an ArUco marker on the gripper (the top camera finds it in one frame, 15 mm and up
measured 20/20 within 0.4 px at 1.1 px/mm) and a checkerboard for the cameras' geometry. A raster image printed
through a viewer's "fit to page" comes out scaled; here every square is a PDF rectangle in millimetres on an A4 page,
with a 50 mm bar to check the print with a ruler. No dependency: the ArUco DICT_4X4_100 bit patterns are a table
(extracted from OpenCV 4.10/4.12 ``generateImageMarker``; bit 1 = white, row-major from the top-left).
"""

from __future__ import annotations

A4_MM = (210.0, 297.0)
PT_PER_MM = 72 / 25.4
DICT_4X4_100 = (  # ids 0-49 are DICT_4X4_50's markers, so the ChArUco board (ids 0-34) reads the same
    46386, 3994, 13101, 39238, 21662, 31181, 40494, 50418, 65242, 53078, 63889, 4519, 3767, 10767, 9393, 9790, 18021,
    26112, 27742, 30383, 34443, 45099, 52437, 56706, 65095, 38001, 44260, 42324, 8483, 13423, 17429, 22450, 40655,
    61643, 2222, 2345, 6261, 1279, 3574, 7258, 5912, 10792, 12940, 14514, 9448, 12011, 11583, 19300, 20526, 20499,
    20884, 21864, 23873, 24471, 26625, 26727, 24868, 25065, 27410, 28645, 26591, 32283, 32928, 33604, 35746, 37754,
    33900, 34090, 34204, 40073, 40865, 47996, 48132, 46683, 49096, 47019, 51743, 51554, 55640, 54229, 52376, 51104,
    50487, 59741, 63781, 64443, 60970, 63309, 13685, 35501, 30231, 2767, 1611, 11713, 18904, 17396, 20278, 20435,
    27108, 28871)
# D-996 6: container tags are ids 100-199 of DICT_4X4_250 (its first 100 ids are DICT_4X4_100), same OpenCV source.
CONTAINER_TAGS = (
    31342, 46314, 60751, 64743, 65190, 37, 67, 2696, 2694, 623, 28, 151, 2103, 2609, 2502, 2817, 2555, 2904, 4226,
    6189, 4216, 4211, 4724, 4785, 6905, 4870, 3086, 3313, 1075, 3231, 3826, 3837, 1868, 4004, 1839, 1461, 3985, 2011,
    7908, 5177, 7552, 5576, 8075, 5562, 7601, 8320, 10473, 8866, 10323, 10992, 8951, 10560, 8518, 10681, 11164, 11186,
    14538, 14382, 12295, 14567, 14921, 14949, 12893, 15240, 14621, 15315, 9799, 10112, 12202, 11540, 9694, 9555, 12151,
    13384, 15528, 15425, 13325, 13563, 13978, 15840, 13674, 15625, 15853, 16324, 16236, 14286, 15708, 15734, 14256,
    16151, 16383, 18661, 17000, 18989, 16736, 18769, 16861, 19423, 22607, 23112)
DICT_4X4_250_PRINTABLE = DICT_4X4_100 + CONTAINER_TAGS  # ids 0-199
FIRST_TAG = len(DICT_4X4_100)
# D-933 marker ids: 0-34 the ChArUco board; arm slot n (1-3) owns 15 ids from 50 + 15 (n - 1): its gripper, its two
# base markers, then three surfaces of four. 95-99 are spare. Every arm's markers differ, so cameras that see two arms
# never mix them up. D-954: arms start at 50, past the site's DICT_4X4_50 ids (robots 40-49 ride under the arm camera);
# the whole table is deploy/site/marker-profile.json.example.
ARM_SLOTS, ARM_BLOCK, FIRST_ARM_ID = 3, 15, 50


def arm_ids(slot: int) -> dict:
    """{"gripper": id, "base": [2 ids], "surfaces": [[4 ids] x 3]} for arm slot 1-4 (D-933)."""
    if not 1 <= int(slot) <= ARM_SLOTS:
        raise ValueError(f"the arm slot is 1-{ARM_SLOTS}")
    first = FIRST_ARM_ID + ARM_BLOCK * (int(slot) - 1)
    return {"gripper": first, "base": [first + 1, first + 2],
            "surfaces": [list(range(first + 3 + 4 * k, first + 7 + 4 * k)) for k in range(3)]}


MARGIN_MM, GAP_MM = 15.0, 12.0


class Page:
    """Drawing in millimetres from the page's top-left; emitted as one PDF content stream."""

    def __init__(self):
        self.ops = []

    def box(self, x, y, w, h, fill=True):
        """A filled box, or (fill=False) a cut line: thin (0.25 pt) solid, centred on the exact cut edge."""
        X, Y = x * PT_PER_MM, (A4_MM[1] - y - h) * PT_PER_MM
        self.ops.append(f"{X:.3f} {Y:.3f} {w * PT_PER_MM:.3f} {h * PT_PER_MM:.3f} re f" if fill else
                        f"q [] 0 d 0.25 w {X:.3f} {Y:.3f} {w * PT_PER_MM:.3f} {h * PT_PER_MM:.3f} re S Q")

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
    bits = DICT_4X4_250_PRINTABLE[marker_id]
    inner = [(1 + k // 4, 1 + k % 4) for k in range(16) if not (bits >> (15 - k)) & 1]
    return [(r, c) for r in range(6) for c in range(6) if r in (0, 5) or c in (0, 5)] + inner


GRIPPER = ("ROSY gripper markers - ArUco DICT_4X4_100",
           "Cut on the thin line, keep the white edge. Glue flat on the gripper body's top face (20 mm).")


def markers_pdf(ids, sizes_mm, words=GRIPPER) -> bytes:
    """Each id at each size."""
    ids, sizes = [int(i) for i in ids], [float(s) for s in sizes_mm]
    if not ids or not sizes:
        raise ValueError("give at least one id and one size")
    if any(not 0 <= i < FIRST_TAG for i in ids):
        raise ValueError(f"gripper markers are ids 0-{FIRST_TAG - 1}")
    return _markers_page([(ids, s, {}) for s in sizes], words)


def arm_pdf(slot: int) -> bytes:
    """One arm slot's page (D-933): its gripper marker at 20 mm, then base and surface markers at 25 mm, labelled."""
    block = arm_ids(slot)
    names = {block["gripper"]: "gripper", **{i: f"base {k + 1}" for k, i in enumerate(block["base"])},
             **{i: f"surface {k + 1}" for k, ids in enumerate(block["surfaces"]) for i in ids}}
    words = (f"ROSY arm {int(slot)} markers - ArUco DICT_4X4_100 (D-933)",
             f"Arm slot {int(slot)} of {ARM_SLOTS}: ids {block['gripper']}-{block['surfaces'][-1][-1]}. Gripper on its top "
             "face; 2 on the arm base; each surface 4, at least 150 mm apart, not in one line. Glue flat.")
    rest = block["base"] + [i for ids in block["surfaces"] for i in ids]
    return _markers_page([([block["gripper"]], 20.0, names), (rest, 25.0, names)], words)


FACES = ("roof", "side")


def container_tags_pdf(ids, size_mm: float = 12.0) -> bytes:
    """D-996 6: each container tag twice, one for the roof and one for the side, at one size (12 mm fits a 1-cell
    container, 20 mm the larger ones). The tag-to-object_ref table is the site's marker profile, never the sheet."""
    ids, size = [int(i) for i in ids], float(size_mm)
    if not ids or any(not FIRST_TAG <= i < len(DICT_4X4_250_PRINTABLE) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"container tags are distinct ids {FIRST_TAG}-{len(DICT_4X4_250_PRINTABLE) - 1}")
    words = ("ROSY container tags - ArUco DICT_4X4_250 (D-996)",
             "Each tag twice: one flat on the roof, one flat on the side of the same container. Matte paper.")
    return _markers_page([([i for i in ids for _ in FACES], size, {}, FACES * len(ids))], words)


def _markers_page(groups, words) -> bytes:
    """groups: (ids, size mm, {id: label}[, label per position]); each group starts a new row."""
    if any(not 0 <= i < len(DICT_4X4_250_PRINTABLE) for ids, *_ in groups for i in ids) or \
            any(not 10 <= size <= 80 for _, size, *_ in groups):
        raise ValueError(f"ids are 0-{len(DICT_4X4_250_PRINTABLE) - 1} and sizes 10-80 mm")
    page, y = Page(), MARGIN_MM
    page.text(MARGIN_MM, y + 5, 14, words[0])
    page.text(MARGIN_MM, y + 11, 9, words[1])
    y += 18
    page.scale_bar(y)
    sizes = sorted({size for _, size, *_ in groups})
    page.text(MARGIN_MM, y + 12, 9, "Cut exactly on the thin line; keep the white edge. Cut squares: " +
              ", ".join(f"{s:g} mm marker {s * 4 / 3:.1f} mm" for s in sizes) + ".")
    y += 21
    for ids, size, names, *faces in groups:
        quiet = size / 6  # one cell of white around the black border, inside the cut line
        x = MARGIN_MM
        for k, marker_id in enumerate(ids):
            if x + size + 2 * quiet > A4_MM[0] - MARGIN_MM:
                x, y = MARGIN_MM, y + size + 2 * quiet + GAP_MM
            if y + size + 2 * quiet + 8 > A4_MM[1] - MARGIN_MM:
                raise ValueError("too many markers for one page")
            cell = size / 6
            for r, c in marker_cells(marker_id):
                page.box(x + quiet + c * cell, y + quiet + r * cell, cell, cell)
            page.box(x, y, size + 2 * quiet, size + 2 * quiet, fill=False)
            label = f"id {marker_id}  {size:g} mm" + (f"  {names[marker_id]}" if marker_id in names else "") + \
                (f"  {faces[0][k]}" if faces else "")
            page.text(x, y + size + 2 * quiet + 5, 9, label)
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
    y += 21
    x, marker_id, cell = (A4_MM[0] - cols * square) / 2, 0, side / 6
    edge = 5.0  # white edge kept around the board when it is cut out and glued to a rigid board
    page.box(x - edge, y - edge, cols * square + 2 * edge, rows * square + 2 * edge, fill=False)
    page.text(x - edge, y + rows * square + edge + 5, 9, f"Cut on the thin line: {cols * square + 2 * edge:g} x "
              f"{rows * square + 2 * edge:g} mm, a {edge:g} mm white edge around the squares.")
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
          "charuco": "ChArUco board for lens calibration", "arm-markers": "one arm slot's gripper, base and surface markers",
          "container-tags": "container tags, roof and side (D-996)"}


def size_mm_of(sizes_mm) -> float:
    if len(sizes_mm) != 1:
        raise ValueError("container tags take one size")
    return float(sizes_mm[0])


def sheet(kind: str, ids=(35,), sizes_mm=(20, 25), cols: int = 8, rows: int = 6, square_mm: float = 15.0, arm: int = 1):
    """(file name, PDF bytes) for one kind in SHEETS."""
    if kind == "gripper-markers":
        return "rosy-gripper-markers.pdf", markers_pdf(ids, sizes_mm)
    if kind == "charuco":
        return "rosy-charuco-7x10-20mm.pdf", charuco_pdf()
    if kind == "arm-markers":
        return f"rosy-arm-{int(arm)}-markers.pdf", arm_pdf(arm)
    if kind == "container-tags":
        return f"rosy-container-tags-{size_mm_of(sizes_mm):g}mm.pdf", container_tags_pdf(ids, size_mm_of(sizes_mm))
    if kind == "checkerboard":
        return f"rosy-checkerboard-{cols}x{rows}-{square_mm:g}mm.pdf", checkerboard_pdf(cols, rows, square_mm)
    raise ValueError(f"unknown sheet {kind}: one of {', '.join(SHEETS)}")
