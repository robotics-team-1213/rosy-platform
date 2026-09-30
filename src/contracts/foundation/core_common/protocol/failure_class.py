"""Client-side connection failure classes (D-370 5.5, D-391 4.1).

The machine source is ``test/fixtures/protocol/failure-classes.v1.json``.
This module maps exactly one observed input (WS close code with optional
reason, HTTP status, transport error kind or discovery outcome) to one class.
Clients keep their own UI states on top of the class; the vector does not
define them.

Standard library only.
"""

from __future__ import annotations

CLASSES = (
    "unreachable", "refused", "unknown_host", "tls_untrusted", "auth_final", "auth_retry",
    "forbidden", "protocol_mismatch", "busy", "conflict", "not_discovered",
)

# D-341 11 transition rule: a receiver older than the 1013 change closes a
# hello timeout as 4400 with one of these reasons; that close is retryable.
# Same list as overhead-ingest.v1.json close_4400_reasons.retry.
CLOSE_4400_RETRY_REASONS = (
    "", "no hello", "hello timeout", "timed out waiting for hello", "receiver busy",
)

WS_CLOSE = {
    4401: "auth_final",
    4403: "forbidden",
    4409: "conflict",
    4503: "auth_retry",
    1013: "busy",
}
HTTP_STATUS = {
    401: "auth_final",
    403: "forbidden",
    409: "conflict",
    429: "busy",
    503: "busy",
}
TRANSPORT = {
    "timeout": "unreachable",
    "no_route": "unreachable",
    "connection_refused": "refused",
    "dns_failure": "unknown_host",
    "tls_handshake": "tls_untrusted",
    "tls_pin_mismatch": "tls_untrusted",
}
DISCOVERY = {"no_match_within_timeout": "not_discovered"}

WS_FALLBACK = "unreachable"
HTTP_4XX_FALLBACK = "protocol_mismatch"
HTTP_5XX_FALLBACK = "busy"


def classify(*, ws_close: int | None = None, reason: str | None = None,
             http_status: int | None = None, transport: str | None = None,
             discovery: str | None = None) -> str:
    """Return the failure class for exactly one input kind.

    Raises ValueError when no input or more than one is given, when
    ``reason`` comes without ``ws_close``, or for an unknown transport or
    discovery value (those vocabularies are closed).
    """
    given = [name for name, value in (("ws_close", ws_close), ("http_status", http_status),
                                      ("transport", transport), ("discovery", discovery))
             if value is not None]
    if len(given) != 1:
        raise ValueError(f"exactly one input kind is required, got {given or 'none'}")
    if reason is not None and ws_close is None:
        raise ValueError("reason is only meaningful with ws_close")

    if ws_close is not None:
        if ws_close == 4400:
            return "busy" if (reason or "") in CLOSE_4400_RETRY_REASONS else "protocol_mismatch"
        return WS_CLOSE.get(ws_close, WS_FALLBACK)
    if http_status is not None:
        if http_status in HTTP_STATUS:
            return HTTP_STATUS[http_status]
        if 400 <= http_status < 500:
            return HTTP_4XX_FALLBACK
        if 500 <= http_status < 600:
            return HTTP_5XX_FALLBACK
        raise ValueError(f"HTTP status {http_status} is not a failure")
    if transport is not None:
        if transport not in TRANSPORT:
            raise ValueError(f"unknown transport failure {transport!r}")
        return TRANSPORT[transport]
    if discovery not in DISCOVERY:
        raise ValueError(f"unknown discovery outcome {discovery!r}")
    return DISCOVERY[discovery]
