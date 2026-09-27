"""Rosy-owned stand-ins for the vendor's closed ``pinkylib`` (D-192).

Only what the product device surface (D-169) uses is here: ``Battery`` on the
I2C-1 ADC. ``LED`` is deliberately absent: the LED is bench-only (D-169), so
``from rosylib import LED`` (``led/led_server.py``) fails with a clear
ImportError instead of a bare "cannot import name".
"""

from .battery import Battery

__all__ = ["Battery"]

_NOT_PROVIDED = {
    "LED": "the LED is bench-only (D-169); rosylib ships no LED driver (D-192)",
}


def __getattr__(name: str):
    if name in _NOT_PROVIDED:
        raise ImportError(f"rosylib.{name} is not provided: {_NOT_PROVIDED[name]}")
    raise AttributeError(f"module 'rosylib' has no attribute {name!r}")
