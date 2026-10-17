"""Uncached same-host readback of the existing Fleet dispatch-control API."""
from http.client import HTTPConnection, HTTPSConnection
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import ssl
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
        # Direct HTTP(S)Connection neither inherits proxies nor follows redirects.
        connection = self._connection()
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

    def _connection(self):
        return HTTPConnection(self._host, self._port, timeout=self.timeout_s)


class HttpsFleetFenceReadback(HttpFleetFenceReadback):
    """D-785: the same read through the site HTTPS proxy, for a site Fleet that is TLS-only.

    The address is a literal IP (no DNS); the server must present a certificate for
    ``tls_server_name`` that chains to the pinned site CA file only (no system trust store).
    """

    def __init__(self, url: str, token: str, *, ca_file: str, tls_server_name: str, timeout_s: float = .5):
        try:
            parsed = urlsplit(url)
            port = parsed.port if parsed.port is not None else 443
            literal = ipaddress.ip_address(parsed.hostname or "")
        except (ValueError, TypeError):
            raise ValueError("Fleet HTTPS fence requires a literal IP endpoint") from None
        if (parsed.scheme != "https" or parsed.path != "/api/fleet/dispatch-control"
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not 1 <= port <= 65535
                or literal.is_unspecified or literal.is_multicast):
            raise ValueError("Fleet HTTPS fence requires the exact literal-IP dispatch-control read endpoint")
        if (not isinstance(tls_server_name, str) or not tls_server_name or len(tls_server_name) > 253
                or any(not (char.isalnum() or char in "-.") for char in tls_server_name)):
            raise ValueError("an explicit TLS server name is required")
        ca = Path(ca_file) if isinstance(ca_file, str) and ca_file else None
        if ca is None or not ca.is_absolute() or not ca.is_file():
            raise ValueError("an absolute pinned site CA file is required")
        super().__init__(f"http://127.0.0.1:{port}/api/fleet/dispatch-control", token, timeout_s=timeout_s)
        self._host, self._port = str(literal), port
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # check_hostname + CERT_REQUIRED
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cafile=str(ca))
        self._context, self._server_name = context, tls_server_name

    def _connection(self):
        return _PinnedHttpsConnection(self._host, self._port, self._server_name,
                                      timeout=self.timeout_s, context=self._context)


class _PinnedHttpsConnection(HTTPSConnection):
    """TCP to the literal IP; SNI and hostname verification against the site TLS name."""

    def __init__(self, host, port, server_name, **kwargs):
        super().__init__(host, port, **kwargs)
        self._server_name = server_name

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._server_name)


def fleet_fence_from_environment() -> HttpFleetFenceReadback:
    url, token = os.environ.get("ROSY_FLEET_FENCE_URL", ""), os.environ.get("ROSY_FLEET_FENCE_TOKEN", "")
    if url.startswith("https://"):  # D-785: site Fleet behind the TLS proxy
        return HttpsFleetFenceReadback(url, token, ca_file=os.environ.get("ROSY_FLEET_FENCE_CA", ""),
                                       tls_server_name=os.environ.get("ROSY_FLEET_FENCE_TLS_NAME", ""))
    return HttpFleetFenceReadback(url, token)
