"""Capture identity must travel in the image, including epoch resets."""

from pathlib import Path
import runpy

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'src/rosy_media_edge/watermark.py'


def implementation():
    assert SOURCE.is_file(), 'D-789 capture watermark implementation is missing'
    return runpy.run_path(str(SOURCE))


def test_watermark_roundtrips_identity_and_preserves_rest_of_image():
    module = implementation()
    rgb = bytearray([96] * (640 * 480 * 3))
    module['stamp_rgb'](rgb, 640, 480, epoch=7, sequence=81, captured_ms=1792244423123)
    assert module['read_rgb'](rgb, 640, 480) == (7, 81, 1792244423123)
    assert rgb[640 * 25 * 3:] == bytearray([96] * (640 * (480 - 25) * 3))


def test_watermark_rejects_unstamped_corrupt_and_truncated_images():
    module = implementation()
    rgb = bytearray([128] * (640 * 480 * 3))
    assert module['read_rgb'](rgb, 640, 480) is None
    module['stamp_rgb'](rgb, 640, 480, epoch=1, sequence=2, captured_ms=1000)
    # Change a whole bit cell so a plausible-looking frame fails CRC.
    for y in range(4):
        for x in range(4):
            i = (y * 640 + x) * 3
            rgb[i:i + 3] = bytes([235, 235, 235])
    assert module['read_rgb'](rgb, 640, 480) is None
    with pytest.raises(ValueError):
        module['stamp_rgb'](bytearray(10), 640, 480, epoch=1, sequence=2, captured_ms=1)


def test_watermark_survives_brightness_error_but_keeps_epoch_distinct():
    module = implementation()
    rgb = bytearray(640 * 480 * 3)
    module['stamp_rgb'](rgb, 640, 480, epoch=12, sequence=1, captured_ms=2000)
    rgb = bytearray(min(255, x + 25) for x in rgb)
    assert module['read_rgb'](rgb, 640, 480) == (12, 1, 2000)
    module['stamp_rgb'](rgb, 640, 480, epoch=13, sequence=1, captured_ms=2001)
    assert module['read_rgb'](rgb, 640, 480) == (13, 1, 2001)


@pytest.mark.parametrize('changes', [dict(epoch=-1), dict(sequence=2**32), dict(captured_ms=-1)])
def test_watermark_rejects_invalid_identity(changes):
    module = implementation()
    values = dict(epoch=1, sequence=1, captured_ms=1)
    values.update(changes)
    with pytest.raises(ValueError):
        module['stamp_rgb'](bytearray(640 * 480 * 3), 640, 480, **values)
