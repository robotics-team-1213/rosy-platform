"""Raw Pinky ADC conversion used by the sensing-only IR publisher."""

import pytest

from control.sensing.ir_adc import decode_adc12


def test_decode_adc12_matches_the_existing_cxx_driver_contract():
    assert decode_adc12(bytes([0xAB, 0xC0])) == 0xABC


@pytest.mark.parametrize("payload", [b"", b"\x01", b"\x01\x02\x03"])
def test_decode_adc12_rejects_partial_or_oversized_reads(payload):
    with pytest.raises(ValueError):
        decode_adc12(payload)
