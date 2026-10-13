"""Pinky three-channel 12-bit ADC helpers.

The byte contract matches the absorbed C++ ``sensor_adc`` driver. Hardware
access stays in ``ir_adc_node`` so this module remains host-testable.
"""


def decode_adc12(payload: bytes) -> int:
    """Decode the ADC's two-byte, left-aligned 12-bit response."""
    if len(payload) != 2:
        raise ValueError("ADC response must contain exactly two bytes")
    return (payload[0] << 4) | (payload[1] >> 4)
