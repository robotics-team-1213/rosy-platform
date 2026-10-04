"""Bounded truecolor PNG validation for OMX v1; no image/runtime dependency."""
import struct
import zlib


def verify_rgb_png(data, width, height):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('PNG signature required')
    offset, chunks, compressed, idat_done = 8, [], bytearray(), False
    header = None
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError('PNG truncated chunk')
        size, kind = struct.unpack('>I4s', data[offset:offset + 8])
        end = offset + 12 + size
        if end > len(data):
            raise ValueError('PNG truncated payload')
        payload = data[offset + 8: end - 4]
        crc = struct.unpack('>I', data[end - 4:end])[0]
        if zlib.crc32(kind + payload) != crc:
            raise ValueError('PNG CRC mismatch')
        if not all(65 <= x <= 90 or 97 <= x <= 122 for x in kind) or kind[2] & 32:
            raise ValueError('PNG invalid chunk type')
        if not chunks and kind != b'IHDR':
            raise ValueError('PNG IHDR must be first')
        if kind == b'IHDR':
            if header is not None or size != 13:
                raise ValueError('PNG invalid IHDR')
            header = struct.unpack('>IIBBBBB', payload)
            w, h, depth, color, compression, filtering, interlace = header
            if (w, h) != (width, height) or depth not in (8, 16) or color != 2:
                raise ValueError('PNG dimensions or RGB encoding differ')
            if compression or filtering or interlace not in (0, 1):
                raise ValueError('PNG unsupported encoding')
        elif kind == b'IDAT':
            if idat_done:
                raise ValueError('PNG noncontiguous IDAT')
            compressed.extend(payload)
        elif kind == b'PLTE':
            if b'PLTE' in chunks or b'IDAT' in chunks or not size or size % 3 or size > 768:
                raise ValueError('PNG invalid palette')
        elif kind == b'IEND':
            if size or b'IDAT' not in chunks or end != len(data):
                raise ValueError('PNG invalid IEND')
        elif not kind[0] & 32:
            raise ValueError('PNG unknown critical chunk')
        # Transparency changes Pillow RGB to RGBA and is outside this profile.
        if kind == b'tRNS':
            raise ValueError('PNG RGB transparency unsupported')
        if kind != b'IDAT' and b'IDAT' in chunks:
            idat_done = True
        chunks.append(kind)
        offset = end
    if not chunks or chunks[-1] != b'IEND':
        raise ValueError('PNG missing IEND')
    w, h, depth, _, _, _, interlace = header
    passes = [(0, 0, 1, 1)] if not interlace else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    strides = []
    for x, y, dx, dy in passes:
        pw, ph = max(0, (w - x + dx - 1) // dx), max(0, (h - y + dy - 1) // dy)
        if pw and ph:
            strides.extend([1 + pw * 3 * (depth // 8)] * ph)
    expected = sum(strides)
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected + 1)
    except zlib.error as error:
        raise ValueError('PNG invalid compressed stream') from error
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('PNG decoded length or stream differs')
    position = 0
    for stride in strides:
        if raw[position] > 4:
            raise ValueError('PNG invalid scanline filter')
        position += stride
