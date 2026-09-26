"""emotion.wifi_qr — the Wi-Fi join QR the boot card draws while the AP is open.

A minimal QR Code encoder (ISO/IEC 18004): byte mode, error correction level M,
versions 1-5 (21-37 modules, up to 84 bytes). That is enough for a ROSY AP:
the join string for ``rosy-pinky-xxxx`` and a
``rosy-xxxx-xxxx`` key is 47 bytes (version 4).
A longer payload (a human-set 63-character passphrase and a 32-byte SSID) is
refused with ValueError and the card shows the text alone.

Written here rather than taken from a library: neither the device image
(deploy/image/device-python-requirements.txt, D-189) nor the vendor apt set
ships a QR encoder, and adding one would mean a new hash-locked wheel for a
screen that needs one small, fixed code shape. Pure Python, no ROS, no I/O.

The payload and matrix hold the AP passphrase: they are drawn on the LCD and
nowhere else — never logged, never written to a file or an API (D-176, D-190).
"""

from __future__ import annotations

#: version -> (EC codewords per block, blocks, data codewords per block), level M.
_LEVEL_M = {1: (10, 1, 16), 2: (16, 1, 28), 3: (26, 1, 44), 4: (18, 2, 32), 5: (24, 2, 43)}
#: version -> alignment pattern centre coordinates.
_ALIGNMENT = {1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30)}
MAX_VERSION = 5
_FORMAT_LEVEL_M = 0b00
_FORMAT_MASK = 0b101010000010010
_FORMAT_POLY = 0x537

_ESCAPED = '\\;,:"'


def wifi_payload(ssid: str, passphrase: str) -> str:
    """The ``WIFI:T:WPA;S:<ssid>;P:<psk>;;`` join string phones read (WPA2 personal).

    ``\\ ; , : "`` are backslash-escaped in both fields, as the format asks.
    """
    def escape(value: str) -> str:
        return "".join("\\" + char if char in _ESCAPED else char for char in value)

    fields = (("T", "WPA"), ("S", escape(ssid)), ("P", escape(passphrase)))
    return "WIFI:" + "".join(f"{name}:{value};" for name, value in fields) + ";"


# --- Reed-Solomon over GF(256), primitive polynomial 0x11D ------------------

_EXP = [0] * 512
_LOG = [0] * 256
_value = 1
for _power in range(255):
    _EXP[_power] = _value
    _LOG[_value] = _power
    _value <<= 1
    if _value & 0x100:
        _value ^= 0x11D
for _power in range(255, 512):
    _EXP[_power] = _EXP[_power - 255]


def _multiply(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> list[int]:
    """Coefficients of prod (x - a^i), i < degree, highest power first."""
    poly = [1]
    for index in range(degree):
        poly = [a ^ _multiply(b, _EXP[index]) for a, b in zip(poly + [0], [0] + poly)]
    return poly


def reed_solomon(data: list[int], degree: int) -> list[int]:
    """The ``degree`` error correction codewords of ``data``."""
    generator = _generator(degree)
    remainder = list(data) + [0] * degree
    for index in range(len(data)):
        factor = remainder[index]
        if factor:
            for offset, coefficient in enumerate(generator):
                remainder[index + offset] ^= _multiply(coefficient, factor)
    return remainder[len(data):]


def format_bits(mask: int) -> int:
    """The 15 format bits for level M and ``mask`` (BCH(15,5), XOR mask applied)."""
    data = (_FORMAT_LEVEL_M << 3) | mask
    remainder = data << 10
    for shift in range(14, 9, -1):
        if remainder & (1 << shift):
            remainder ^= _FORMAT_POLY << (shift - 10)
    return ((data << 10) | remainder) ^ _FORMAT_MASK


# --- codewords --------------------------------------------------------------


def _codewords(data: bytes) -> tuple[int, list[int]]:
    """(version, final interleaved codeword sequence) for ``data`` in byte mode."""
    for version in range(1, MAX_VERSION + 1):
        ec_length, blocks, block_data = _LEVEL_M[version]
        capacity = blocks * block_data
        if 4 + 8 + 8 * len(data) <= capacity * 8:
            break
    else:
        raise ValueError(f"QR payload of {len(data)} bytes exceeds version {MAX_VERSION}-M")

    bits: list[int] = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> shift) & 1 for shift in range(length - 1, -1, -1))

    put(0b0100, 4)  # byte mode
    put(len(data), 8)  # character count, versions 1-9
    for byte in data:
        put(byte, 8)
    put(0, min(4, capacity * 8 - len(bits)))  # terminator
    put(0, -len(bits) % 8)
    words = [int("".join(map(str, bits[index:index + 8])), 2) for index in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < capacity:
        words.append(pad)
        pad ^= 0xEC ^ 0x11

    data_blocks = [words[index * block_data:(index + 1) * block_data] for index in range(blocks)]
    ec_blocks = [reed_solomon(block, ec_length) for block in data_blocks]
    result = [block[index] for index in range(block_data) for block in data_blocks]
    result += [block[index] for index in range(ec_length) for block in ec_blocks]
    return version, result


# --- matrix -----------------------------------------------------------------

_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Matrix:
    def __init__(self, version: int) -> None:
        self.size = 17 + 4 * version
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.reserved = [[False] * self.size for _ in range(self.size)]
        self._functions(version)

    def set(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.reserved[y][x] = True

    def _functions(self, version: int) -> None:
        size = self.size
        for index in range(size):  # timing patterns
            self.set(6, index, index % 2 == 0)
            self.set(index, 6, index % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):  # finders and separators
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        ring = max(abs(dx), abs(dy))
                        self.set(x, y, ring not in (2, 4))
        centres = _ALIGNMENT[version]
        for cy in centres:
            for cx in centres:
                if (cx, cy) in ((6, 6), (6, size - 7), (size - 7, 6)):
                    continue  # would overlap a finder
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)  # reserve the format areas; drawn again for the chosen mask

    def format(self, mask: int) -> None:
        size = self.size
        bits = format_bits(mask)

        def bit(index: int) -> bool:
            return (bits >> index) & 1 == 1

        for index in range(6):
            self.set(8, index, bit(index))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for index in range(9, 15):
            self.set(14 - index, 8, bit(index))
        for index in range(8):
            self.set(size - 1 - index, 8, bit(index))
        for index in range(8, 15):
            self.set(8, size - 15 + index, bit(index))
        self.set(8, size - 8, True)  # the dark module

    def place(self, codewords: list[int]) -> None:
        size = self.size
        total = len(codewords) * 8
        index = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5  # skip the vertical timing column
            upward = ((right + 1) & 2) == 0
            for vertical in range(size):
                y = size - 1 - vertical if upward else vertical
                for x in (right, right - 1):
                    if self.reserved[y][x]:
                        continue
                    if index < total:
                        self.dark[y][x] = (codewords[index >> 3] >> (7 - (index & 7))) & 1 == 1
                        index += 1
            right -= 2

    def masked(self, mask: int) -> list[list[bool]]:
        rule = _MASKS[mask]
        return [[self.dark[y][x] != (not self.reserved[y][x] and rule(x, y)) for x in range(self.size)]
                for y in range(self.size)]


def _penalty(grid: list[list[bool]]) -> int:
    size = len(grid)
    score = 0
    lines = grid + [list(column) for column in zip(*grid)]
    finder = ([True, False, True, True, True, False, True, False, False, False, False],
              [False, False, False, False, True, False, True, True, True, False, True])
    for line in lines:
        run, previous = 0, None
        for module in line:
            if module == previous:
                run += 1
            else:
                if run >= 5:
                    score += 3 + run - 5
                run, previous = 1, module
        if run >= 5:
            score += 3 + run - 5
        for start in range(size - 10):
            if line[start:start + 11] in finder:
                score += 40
    for y in range(size - 1):
        for x in range(size - 1):
            if grid[y][x] == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                score += 3
    dark = sum(map(sum, grid))
    total = size * size
    score += ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
    return score


def encode(data: bytes | str, mask: int | None = None) -> list[list[bool]]:
    """The QR matrix of ``data`` (True = dark), without the quiet zone.

    ``mask`` pins the mask pattern (tests); by default the lowest-penalty one.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    version, codewords = _codewords(raw)
    matrix = _Matrix(version)
    matrix.place(codewords)
    best: tuple[int, list[list[bool]]] | None = None
    for candidate in (range(8) if mask is None else (mask,)):
        matrix.format(candidate)
        grid = matrix.masked(candidate)
        score = _penalty(grid)
        if best is None or score < best[0]:
            best = (score, grid)
    assert best is not None
    return best[1]
