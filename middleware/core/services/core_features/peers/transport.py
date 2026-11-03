"""Peer pose sharing — the TLS beacon POST over stdlib urllib (design §4.2)."""
from __future__ import annotations

import json
import ssl
import urllib.request

TIMEOUT_S = 2.0


def post_beacon(url: str, token: str, payload: dict, *, ca_file: str | None = None,
                timeout_s: float = TIMEOUT_S) -> bool:
    """POST one beacon; a failed peer is the caller's next tick, never an exception."""
    context = ssl.create_default_context(cafile=ca_file)
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(request, timeout=timeout_s, context=context) as response:
        return 200 <= response.status < 300
