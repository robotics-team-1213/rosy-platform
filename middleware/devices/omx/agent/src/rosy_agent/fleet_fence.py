"""Uncached same-host readback of the existing Fleet dispatch-control API."""
from http.client import HTTPConnection
import json
import math
import os
from urllib.parse import urlsplit


def _reject_nonfinite(value):
    raise ValueError("non-finite JSON is not a Fleet control snapshot")


class HttpFleetFenceReadback:
    """Read authority only; commands and stops remain on the UID-checked UDS."""

    MAX_RESPONSE_BYTES = 8192

    def __init__(self, url: str, token: str, *, timeout_s: float = .25):
        try:
            parsed = urlsplit(url)
            port = parsed.port if parsed.port is not None else 80
        except (ValueError, TypeError):
            raise ValueError("invalid Fleet fence endpoint") from None
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
                or parsed.path != "/api/fleet/dispatch-control"
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not 1 <= port <= 65535):
            raise ValueError("Fleet fence requires the exact literal loopback HTTP read endpoint")
        if (not isinstance(token, str) or not token or len(token) > 512
                or any(ord(char) < 33 or ord(char) > 126 for char in token)):
            raise ValueError("a private Fleet viewer credential is required")
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not math.isfinite(timeout_s) or not .01 <= timeout_s <= 1):
            raise ValueError("Fleet readback socket timeout must be between 10 ms and 1 s")
        self._host, self._port, self._token = parsed.hostname, port, token
        self.timeout_s = float(timeout_s)

    def __call__(self, authority_epoch: int, dispatch_generation: int) -> bool:
        if (type(authority_epoch) is not int or authority_epoch < 0
                or type(dispatch_generation) is not int or dispatch_generation < 0):
            return False
        # Direct HTTPConnection neither inherits proxies nor follows redirects.
        connection = HTTPConnection(self._host, self._port, timeout=self.timeout_s)
        try:
            connection.request("GET", "/api/fleet/dispatch-control", headers={
                "Authorization": "Bearer " + self._token, "Accept": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                return False
            body = response.read(self.MAX_RESPONSE_BYTES + 1)
            if len(body) > self.MAX_RESPONSE_BYTES:
                return False
            control = json.loads(body.decode("utf-8"), parse_constant=_reject_nonfinite)
            if not isinstance(control, dict):
                return False
            return (type(control.get("authority_epoch")) is int
                    and type(control.get("generation")) is int
                    and control["authority_epoch"] == authority_epoch
                    and control["generation"] == dispatch_generation
                    and control.get("dispatch_enabled") is True)
        except Exception:
            # No credential, raw response or exception text goes into logs.
            return False
        finally:
            connection.close()


def fleet_fence_from_environment() -> HttpFleetFenceReadback:
    return HttpFleetFenceReadback(
        os.environ.get("ROSY_FLEET_FENCE_URL", ""), os.environ.get("ROSY_FLEET_FENCE_TOKEN", ""))
