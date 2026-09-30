"""``rosy-overhead/1`` wire protocol: pure stdlib, no ROS, no I/O.

Covers the 20-byte binary frame header, the ``hello``/``config`` JSON
messages, and the ``rosyov://`` pairing URI (D-261 A1). Kotlin keeps a
parallel implementation on the Android side; both read the shared test
vectors at ``test/fixtures/protocol/overhead-ingest.v1.json`` so a change to one
side that the other misses fails a test instead of shipping silently.

See docs/plans/2026-09-26-overhead-camera-android-app-design.md §3-4 and
docs/adr/D-261-overhead-camera-app-skeleton.md.
"""

from __future__ import annotations

import base64
import hashlib
import re
import ssl
import struct
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

PROTO = "rosy-overhead/1"
WS_PATH = "/overhead/v1/frames"

HEADER_SIZE = 20
_HEADER_STRUCT = struct.Struct("<4sIIHHHH")
_MAGIC = b"ROF1"
VALID_ROTATIONS = (0, 90, 180, 270)
SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PIN_PREFIX = "sha256/"
PIN_PATTERN = re.compile(r"^sha256/[A-Za-z0-9_-]{43}$")

DEFAULT_CONFIG = {"fps": 3, "width": 1280, "jpeg_quality": 70, "max_bytes": 200000}

CLOSE_BAD_PROTO = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_REPLACED = 4409


class ProtocolError(ValueError):
    """Base for protocol validation failures. ``reason`` is a short machine tag."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


class HeaderError(ProtocolError):
    """A binary frame header failed to parse. ``reason`` matches vectors.json."""


class HelloError(ProtocolError):
    """A ``hello`` message failed validation."""


class PairingError(ProtocolError):
    """A ``rosyov://`` pairing URI failed to parse. ``reason`` matches vectors.json."""


@dataclass(frozen=True)
class FrameHeader:
    seq: int
    age_ms: int
    width: int
    height: int
    rotation_deg: int


def pack_header(header: FrameHeader) -> bytes:
    """Pack a :class:`FrameHeader` into the 20-byte wire format."""
    if header.width <= 0 or header.height <= 0:
        raise HeaderError("size", "width and height must be > 0")
    if header.rotation_deg not in VALID_ROTATIONS:
        raise HeaderError("rotation", f"rotation_deg {header.rotation_deg} not in {VALID_ROTATIONS}")
    return _HEADER_STRUCT.pack(
        _MAGIC, header.seq, header.age_ms, header.width, header.height, header.rotation_deg, 0
    )


def parse_header(data: bytes) -> FrameHeader:
    """Parse the leading 20 bytes of ``data`` into a :class:`FrameHeader`.

    Extra bytes (the JPEG payload) are ignored here; the caller slices them
    off separately. Raises :class:`HeaderError` with ``reason`` in
    ``{"short", "magic", "reserved", "rotation", "size"}``.
    """
    if len(data) < HEADER_SIZE:
        raise HeaderError("short", f"header is {len(data)} bytes, need {HEADER_SIZE}")
    magic, seq, age_ms, width, height, rotation_deg, reserved = _HEADER_STRUCT.unpack(
        data[:HEADER_SIZE]
    )
    if magic != _MAGIC:
        raise HeaderError("magic", f"bad magic {magic!r}")
    if reserved != 0:
        raise HeaderError("reserved", f"reserved field is {reserved}, must be 0")
    if rotation_deg not in VALID_ROTATIONS:
        raise HeaderError("rotation", f"rotation_deg {rotation_deg} not in {VALID_ROTATIONS}")
    if width == 0 or height == 0:
        raise HeaderError("size", "width and height must be > 0")
    return FrameHeader(seq=seq, age_ms=age_ms, width=width, height=height, rotation_deg=rotation_deg)


def validate_hello(message: dict) -> None:
    """Validate a parsed ``hello`` JSON message. Raises :class:`HelloError`."""
    if not isinstance(message, dict):
        raise HelloError("type", "hello message must be a JSON object")
    if message.get("type") != "hello":
        raise HelloError("type", "message type must be 'hello'")
    if message.get("proto") != PROTO:
        raise HelloError("proto", f"proto must be {PROTO!r}")
    source = message.get("source")
    if not isinstance(source, str) or not SOURCE_PATTERN.match(source):
        raise HelloError("source", f"source must match {SOURCE_PATTERN.pattern}")
    sensor = message.get("sensor")
    if not isinstance(sensor, dict):
        raise HelloError("sensor", "sensor must be an object")
    width = sensor.get("width")
    height = sensor.get("height")
    rotation_deg = sensor.get("rotation_deg")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise HelloError("sensor", "sensor.width and sensor.height must be positive integers")
    if rotation_deg not in VALID_ROTATIONS:
        raise HelloError("sensor", f"sensor.rotation_deg must be in {VALID_ROTATIONS}")


LENS_KINDS = ("wide", "standard")


def _bounded(value: object, upper: float) -> bool:
    """True for a real number in (0, upper). Safe for huge ints, inf and NaN (all compare False)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < upper


def parse_hello_lens(message: dict) -> dict | None:
    """Return the optional ``hello.lens`` as ``{"kind", "focal_mm", "hfov_deg"}``, or None.

    The field is additive and informational (camera lens, for a later calibration
    choice): a missing or malformed lens never rejects the hello, so it is not
    part of :func:`validate_hello`. Extra keys inside ``lens`` are ignored.
    """
    lens = message.get("lens") if isinstance(message, dict) else None
    if not isinstance(lens, dict):
        return None
    kind = lens.get("kind")
    focal_mm = lens.get("focal_mm")
    hfov_deg = lens.get("hfov_deg")
    if kind not in LENS_KINDS or not _bounded(focal_mm, 1000) or not _bounded(hfov_deg, 180):
        return None
    return {"kind": kind, "focal_mm": float(focal_mm), "hfov_deg": float(hfov_deg)}


def make_config(
    *, fps: int = 3, width: int = 1280, jpeg_quality: int = 70, max_bytes: int = 200000
) -> dict:
    """Build a ``config`` message. Defaults match vectors.json ``config_default``."""
    return {
        "type": "config",
        "fps": fps,
        "width": width,
        "jpeg_quality": jpeg_quality,
        "max_bytes": max_bytes,
    }


def cert_pin(der: bytes) -> str:
    """``sha256/<base64url, no padding>`` of a certificate's DER bytes (not its SPKI; D-341 9).

    The phone accepts a ``wss://`` chain only when one certificate in the chain the server
    sends hashes to this pin (see :func:`pem_last_cert_pin`).
    """
    digest = hashlib.sha256(der).digest()
    return PIN_PREFIX + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pem_cert_pins(pem_text: str) -> list[str]:
    """Pins of every certificate in a PEM bundle, in file order (leaf first for a served chain)."""
    blocks = re.findall(
        r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", pem_text, flags=re.DOTALL
    )
    if not blocks:
        raise ValueError("no PEM certificate found")
    return [cert_pin(ssl.PEM_cert_to_DER_cert(block)) for block in blocks]


def pem_last_cert_pin(pem_text: str) -> str:
    """Pin the **last** certificate of a PEM bundle.

    Given the file the TLS server serves (``site.crt``), that is the site CA when the file
    carries leaf + CA, and the leaf itself otherwise. Either works with the phone's check;
    a CA pin survives leaf re-issue, a leaf pin does not.
    """
    return pem_cert_pins(pem_text)[-1]


def pairing_uri(
    host: str, port: int, token: str, source: str, *, secure: bool = False, pin: str | None = None
) -> str:
    """Build a ``rosyov://`` pairing URI that :func:`parse_pairing_uri` round-trips."""
    if pin is not None and (not secure or not PIN_PATTERN.match(pin)):
        raise PairingError("pin", "pin needs tls=1 and the form sha256/<43 base64url chars>")
    suffix = "&tls=1" if secure else ""
    if pin is not None:
        suffix += f"&pin={quote(pin, safe='/')}"
    return f"rosyov://{host}:{port}/?t={quote(token, safe='')}&s={quote(source, safe='')}{suffix}"


def parse_pairing_uri(uri: str) -> dict:
    """Parse a ``rosyov://`` pairing URI.

    Returns ``{"host", "port", "token", "source", "secure", "pin", "ws_url"}``. Raises
    :class:`PairingError` with ``reason`` in
    ``{"scheme", "port", "token", "source", "tls", "pin"}`` matching vectors.json.
    """
    split = urlsplit(uri)
    if split.scheme != "rosyov":
        raise PairingError("scheme", f"unexpected scheme {split.scheme!r}")
    try:
        port = split.port
    except ValueError:
        raise PairingError("port", "port out of range 0-65535") from None
    if port is None:
        raise PairingError("port", "port is required")
    host = split.hostname
    if not host:
        raise PairingError("port", "host is required")
    query = parse_qs(split.query)
    token_values = query.get("t")
    if not token_values or not token_values[0]:
        raise PairingError("token", "token (t) is required")
    source_values = query.get("s")
    if not source_values or not source_values[0]:
        raise PairingError("source", "source (s) is required")
    tls_values = query.get("tls", ["0"])
    if tls_values[0] not in {"0", "1"}:
        raise PairingError("tls", "tls must be 0 or 1")
    source = source_values[0]
    secure = tls_values[0] == "1"
    if not SOURCE_PATTERN.match(source):
        raise PairingError("source", f"source must match {SOURCE_PATTERN.pattern}")
    pin_values = query.get("pin")
    pin = pin_values[0] if pin_values else None
    if pin is not None and (not secure or not PIN_PATTERN.match(pin)):
        raise PairingError("pin", "pin needs tls=1 and the form sha256/<43 base64url chars>")
    return {
        "host": host,
        "port": port,
        "token": token_values[0],
        "source": source,
        "secure": secure,
        "pin": pin,
        "ws_url": f"{'wss' if secure else 'ws'}://{host}:{port}{WS_PATH}",
    }
