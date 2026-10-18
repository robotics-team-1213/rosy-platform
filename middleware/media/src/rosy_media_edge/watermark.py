"""In-image capture identity, stable through H.264 and verified with CRC32.

Version 1: network-order 2-byte magic, version, uint32 epoch, uint32 sequence,
uint64 UTC capture milliseconds, CRC32. Bits occupy 4x4 luma cells in a
128x24 top-left strip. Consumers must reject invalid or unreadable identity.
"""

import struct
import zlib


HEADER = struct.Struct('!2sBIIQ')
CELL, COLS, ROWS = 4, 32, 6
WIDTH, HEIGHT = CELL * COLS, CELL * ROWS
SIZE = HEADER.size + 4


def _pixels(rgb, width, height):
    if (not isinstance(width, int) or not isinstance(height, int)
            or width < WIDTH or height < HEIGHT or len(rgb) != width * height * 3):
        raise ValueError('watermark requires packed RGB with room for 128x24 identity')


def stamp_rgb(rgb, width, height, *, epoch, sequence, captured_ms):
    """Mutate only the capture identity strip in a writable packed RGB frame."""
    _pixels(rgb, width, height)
    for value, upper in ((epoch, 2**32), (sequence, 2**32), (captured_ms, 2**64)):
        if type(value) is not int or not 0 <= value < upper:
            raise ValueError('invalid capture identity')
    body = HEADER.pack(b'RM', 1, epoch, sequence, captured_ms)
    packet = body + struct.pack('!I', zlib.crc32(body))
    for bit in range(COLS * ROWS):
        on = bit < SIZE * 8 and packet[bit // 8] & (1 << (7 - bit % 8))
        cell = bytes([235 if on else 16]) * (CELL * 3)
        x, y = (bit % COLS) * CELL, (bit // COLS) * CELL
        for row in range(CELL):
            start = ((y + row) * width + x) * 3
            rgb[start:start + CELL * 3] = cell


def read_rgb(rgb, width, height):
    """Return (epoch, sequence, captured_ms), or None for an invalid watermark."""
    _pixels(rgb, width, height)
    packet = bytearray(SIZE)
    for bit in range(SIZE * 8):
        x, y = (bit % COLS) * CELL + 1, (bit // COLS) * CELL + 1
        samples = []
        for row in range(2):
            for col in range(2):
                start = ((y + row) * width + x + col) * 3
                samples.extend(rgb[start:start + 3])
        value = sum(samples) / len(samples)
        if 80 < value < 175:
            return None
        if value >= 175:
            packet[bit // 8] |= 1 << (7 - bit % 8)
    body = packet[:-4]
    if zlib.crc32(body) != struct.unpack('!I', packet[-4:])[0]:
        return None
    magic, version, epoch, sequence, captured_ms = HEADER.unpack(body)
    return (epoch, sequence, captured_ms) if magic == b'RM' and version == 1 else None
