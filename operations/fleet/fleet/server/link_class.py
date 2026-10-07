"""D-499 robot link class. The browser reads the returned word and never an exception name."""

from __future__ import annotations

import httpx

from fleet.swarm.transport import RobotApiError

# Plain HTTP against a TLS-only CORE. Do not add SSLError or ConnectError here.
_PROTOCOL = (httpx.RemoteProtocolError,)


def classify_link(exc: BaseException | None, *, scheme: str,
                  address_status: str | None) -> str | None:
    """Return a closed link word, or None when the row must omit `link`."""
    if exc is None:
        return "up"
    if address_status == "seen_at_other_address":
        return "moved"
    if isinstance(exc, RobotApiError):
        if exc.status == 401:
            return "tls-refused"
        return None
    if scheme.lower() == "http" and isinstance(exc, _PROTOCOL):
        return "protocol"
    return "unreachable"
