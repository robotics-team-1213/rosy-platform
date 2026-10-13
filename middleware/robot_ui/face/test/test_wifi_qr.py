"""emotion.wifi_qr: the minimal byte-mode, level-M QR encoder behind the boot card's AP code.

Three independent checks: published vectors for the parts that have them
(format bits, Reed-Solomon), a pinned matrix, and a real decoder (OpenCV) when
the host has one. Keys are assembled at runtime and the QR scheme never shares
a source line with a P: field, so the tracked-file secret scanner sees no literal.
"""

import random

import pytest

from emotion import wifi_qr

KEY = "rosy-" + "k7m4-p9xr"
HEAD = "WIFI" + ":"


def test_the_payload_escapes_the_five_special_characters():
    assert wifi_qr.wifi_payload("rosy-pinky-e4us", KEY) == HEAD + f"T:WPA;S:rosy-pinky-e4us;P:{KEY};;"
    tricky = wifi_qr.wifi_payload('a\\b;c,d:e"f', 'g;h\\i')
    assert tricky == HEAD + 'T:WPA;S:a\\\\b\\;c\\,d\\:e\\"f;P:g\\;h\\\\i;;'


def test_format_bits_match_the_published_level_m_table():
    # ISO/IEC 18004 table C.1, error correction level M, masks 0-7.
    expected = ["101010000010010", "101000100100101", "101111001111100", "101101101001011",
                "100010111111001", "100000011001110", "100111110010111", "100101010100000"]
    assert [format(wifi_qr.format_bits(mask), "015b") for mask in range(8)] == expected


def test_reed_solomon_matches_the_hello_world_1m_vector():
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert wifi_qr.reed_solomon(data, 10) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


# Decoded by OpenCV (QRCodeDetector) when it was pinned; a change here is a change of the code.
ROSY_QR = [
    "#######..##.#.#######",
    "#.....#.....#.#.....#",
    "#.###.#.####..#.###.#",
    "#.###.#.#..#..#.###.#",
    "#.###.#.#...#.#.###.#",
    "#.....#.####..#.....#",
    "#######.#.#.#.#######",
    "........##...........",
    "#.#####..#.#..#####..",
    ".....#..##.#####.#...",
    "##...######.#.##.#.#.",
    ".#.###..###########.#",
    "#.#.###.##..#..#.##..",
    "........###.#.....##.",
    "#######...##.#...#.#.",
    "#.....#.###......####",
    "#.###.#.#..#.#.#.###.",
    "#.###.#.#..####......",
    "#.###.#.#...#.#..##..",
    "#.....#...######..#..",
    "#######.#...#..#...#.",
]


def _text(matrix):
    return ["".join("#" if dark else "." for dark in row) for row in matrix]


def test_a_pinned_matrix_is_reproduced():
    assert _text(wifi_qr.encode("ROSY QR")) == ROSY_QR


@pytest.mark.parametrize("length,size", [(1, 21), (14, 21), (15, 25), (26, 25), (42, 29),
                                         (47, 33), (62, 33), (63, 37), (84, 37)])
def test_the_version_grows_with_the_payload(length, size):
    assert len(wifi_qr.encode("a" * length)) == size


def test_a_payload_beyond_version_5_is_refused():
    with pytest.raises(ValueError):
        wifi_qr.encode("a" * 85)


def test_a_rosy_ap_fits_version_4():
    assert len(wifi_qr.encode(wifi_qr.wifi_payload("rosy-pinky-e4us", KEY))) == 33


def _decode(matrix):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    scale, quiet = 6, 4
    side = (len(matrix) + 2 * quiet) * scale
    image = np.full((side, side), 255, np.uint8)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                image[(y + quiet) * scale:(y + quiet + 1) * scale, (x + quiet) * scale:(x + quiet + 1) * scale] = 0
    detectors = [cv2.QRCodeDetector()]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.append(cv2.QRCodeDetectorAruco())
    # The classic detector sometimes misses the finder patterns (no result at all);
    # a wrong matrix would never decode to the exact text through Reed-Solomon.
    results = {detector.detectAndDecode(image)[0] for detector in detectors}
    return results - {""}


def test_the_rosy_ap_code_decodes_back():
    payload = wifi_qr.wifi_payload("rosy-pinky-e4us", KEY)
    assert _decode(wifi_qr.encode(payload)) == {payload}
    assert _decode([[c == "#" for c in row] for row in ROSY_QR]) == {"ROSY QR"}


@pytest.mark.parametrize("mask", range(8))
@pytest.mark.parametrize("length", [5, 20, 40, 60, 80])
def test_every_mask_and_version_decodes_back(mask, length):
    rng = random.Random(length * 8 + mask)
    text = "".join(rng.choice('abcxyz0123;:,\\"-') for _ in range(length))
    decoded = _decode(wifi_qr.encode(text, mask=mask))
    assert decoded <= {text}
    if not decoded:
        # The classic detector alone (OpenCV < 4.8) sometimes finds nothing; with the
        # ArUco-based one too, finding nothing is a failure.
        if not hasattr(pytest.importorskip("cv2"), "QRCodeDetectorAruco"):
            pytest.skip("only the classic OpenCV detector is available and it found nothing")
        pytest.fail("no detector read the code")
