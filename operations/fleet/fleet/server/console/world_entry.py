"""Fleet launch routes and status endpoint for static or mDNS-discovered Rosy World 3D."""

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

MDNS_HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")


def _world_origin(value):
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) > 126 for c in value):
        raise ValueError("Rosy World URL must be a plain HTTP(S) origin")
    if any(c in value for c in ("@", "\\", "?", "#", "*", "%")):
        raise ValueError("Rosy World URL must not contain credentials or URL suffixes")
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        port = url.port
    except ValueError:
        raise ValueError("Invalid Rosy World URL") from None
    if (
        url.scheme not in ("http", "https")
        or not host
        or url.path
        or url.netloc.endswith(":")
        or port == 0
    ):
        raise ValueError("Rosy World URL must be an origin without a path or query")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        last = host.rsplit(".", 1)[-1]
        if (
            re.fullmatch(r"[0-9]+|0x[0-9a-f]+", last)
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split("."))
        ):
            raise ValueError("Invalid Rosy World hostname") from None
        if url.scheme == "http" and host not in ("localhost",) and not (
            host.endswith(".local") or host.endswith(".ts.net") or host == "world"
        ):
            raise ValueError("Non-local Rosy World HTTP origin requires HTTPS")
    else:
        address = getattr(address, "ipv4_mapped", None) or address
        if address.is_unspecified:
            raise ValueError("Rosy World origin must not be unspecified")
        if url.scheme == "http" and not (address.is_loopback or address.is_private):
            raise ValueError("Public IP Rosy World origin requires HTTPS")
    return value


def _validate_mdns_host(value: str) -> str:
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) > 126 for c in value):
        raise ValueError("ROSY_WORLD_MDNS_HOST must be a single-label .local hostname")
    host = value.strip().lower().rstrip(".")
    if not MDNS_HOSTNAME_RE.fullmatch(host):
        raise ValueError(f"Invalid ROSY_WORLD_MDNS_HOST: {value!r}")
    return host


def _configured_world_origin():
    raw = os.environ.get("ROSY_WORLD_URL")
    if raw is None or not raw.strip():
        return None
    return _world_origin(raw.strip())


def _configured_mdns_target():
    raw_host = os.environ.get("ROSY_WORLD_MDNS_HOST")
    if raw_host is None or not raw_host.strip():
        return None
    host = _validate_mdns_host(raw_host)
    raw_port = (os.environ.get("ROSY_WORLD_MDNS_PORT") or "8140").strip()
    if not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise ValueError(f"Invalid ROSY_WORLD_MDNS_PORT: {raw_port!r}")
    scheme = (os.environ.get("ROSY_WORLD_MDNS_SCHEME") or "http").strip().lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Invalid ROSY_WORLD_MDNS_SCHEME: {scheme!r}")
    return host, int(raw_port), scheme


# Same-origin mode (PR-W2): Caddy serves /world/ behind Fleet forward_auth, so the
# entry URL is a site-relative path, not an origin.
SAME_ORIGIN_PATH = "/world/?view=factory&adapter=real"


def _same_origin_enabled():
    return os.environ.get("ROSY_WORLD_SAME_ORIGIN", "").strip().lower() in ("1", "true", "yes")


def _same_origin_health_url():
    raw = (os.environ.get("ROSY_WORLD_HEALTH_URL") or "http://world:8140/healthz").strip()
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise ValueError("Invalid ROSY_WORLD_HEALTH_URL") from None
    if (
        parts.scheme != "http"
        or parts.username is not None
        or parts.password is not None
        or parts.netloc.endswith(":")
        or port == 0
        or host not in ("world", "127.0.0.1", "localhost")
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/healthz")
    ):
        raise ValueError("ROSY_WORLD_HEALTH_URL must be an internal http://world/healthz URL")
    return f"http://{parts.netloc}/healthz"


def _probe_same_origin_health(health_url):
    parts = urlsplit(health_url)
    try:
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=1.5)
        try:
            conn.request("GET", parts.path or "/healthz", headers={"Connection": "close"})
            resp = conn.getresponse()
            body = resp.read(1024)
        finally:
            conn.close()
        if resp.status != 200:
            return False
        payload = json.loads(body.decode("utf-8"))
    except (OSError, http.client.HTTPException, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("application") == "rosy-world"
        and payload.get("status") == "ready"
    )


def discover_world_via_mdns(host: str, port: int, scheme: str) -> str | None:
    """Resolve `host` (.local) via Zeroconf ServiceBrowser or container NSS and confirm `/healthz`."""
    target_port = port
    target_scheme = scheme
    dial_host = host
    zc_addr: str | None = None
    try:
        from zeroconf import ServiceBrowser, Zeroconf

        matched = threading.Event()
        result: dict[str, object] = {}

        class _Listener:
            def remove_service(self, _zc, _type, _name):
                return None

            def update_service(self, zc, stype, name):
                self.add_service(zc, stype, name)

            def add_service(self, zc, stype, name):
                info = zc.get_service_info(stype, name, timeout=500)
                if not info or not info.server or not info.port:
                    return
                if info.server.strip().lower().rstrip(".") != host:
                    return
                props = {
                    (k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k)):
                    (v.decode("utf-8", errors="replace") if isinstance(v, bytes) else ("" if v is None else str(v)))
                    for k, v in (info.properties or {}).items()
                }
                if props.get("product") != "rosy" or props.get("role") != "world":
                    return
                result["port"] = int(info.port)
                result["scheme"] = "https" if props.get("tls") == "required" else scheme
                for raw_addr in info.addresses:
                    if len(raw_addr) == 4:
                        cand = socket.inet_ntoa(raw_addr)
                        if not cand.startswith("172.17."):
                            result["addr"] = cand
                            break
                        result.setdefault("addr", cand)
                matched.set()

        zc = Zeroconf()
        try:
            ServiceBrowser(zc, "_rosy-world._tcp.local.", _Listener())
            matched.wait(0.8)
        finally:
            zc.close()
        if matched.is_set():
            target_port = int(result["port"])
            target_scheme = str(result["scheme"])
            if isinstance(result.get("addr"), str):
                zc_addr = str(result["addr"])
    except Exception:
        pass
    if zc_addr is not None:
        dial_host = zc_addr
    else:
        try:
            infos = socket.getaddrinfo(host, target_port, socket.AF_INET, socket.SOCK_STREAM)
            if infos:
                dial_host = str(infos[0][4][0])
        except OSError:
            return None
    try:
        if target_scheme == "https":
            context = ssl.create_default_context()
            with socket.create_connection((dial_host, target_port), timeout=1.5) as raw:
                with context.wrap_socket(raw, server_hostname=host) as secured:
                    secured.settimeout(1.5)
                    secured.sendall(
                        f"GET /healthz HTTP/1.1\r\nHost: {host}:{target_port}\r\nConnection: close\r\n\r\n".encode("ascii")
                    )
                    resp = http.client.HTTPResponse(secured)
                    resp.begin()
                    status, body = resp.status, resp.read(1024)
        else:
            conn = http.client.HTTPConnection(dial_host, target_port, timeout=1.5)
            try:
                conn.request("GET", "/healthz", headers={"Host": f"{host}:{target_port}", "Connection": "close"})
                resp = conn.getresponse()
                status, body = resp.status, resp.read(1024)
            finally:
                conn.close()
        if status != 200:
            return None
        payload = json.loads(body.decode("utf-8"))
        if isinstance(payload, dict) and payload.get("application") == "rosy-world" and payload.get("status") == "ready":
            return f"{target_scheme}://{host}:{target_port}"
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        return None
    return None


class _MdnsWorldLocator:
    def __init__(self, host: str, port: int, scheme: str, *, ttl_s: float = 10.0, discover_fn=None) -> None:
        self.host = host
        self.port = port
        self.scheme = scheme
        self.ttl_s = ttl_s
        self.discover_fn = discover_fn or discover_world_via_mdns
        self._cached_origin: str | None = None
        self._checked_at: float = -1e9

    def resolve(self) -> str | None:
        now = time.monotonic()
        if (now - self._checked_at) < self.ttl_s:
            return self._cached_origin
        self._cached_origin = self.discover_fn(self.host, self.port, self.scheme)
        self._checked_at = now
        return self._cached_origin


class _SameOriginWorldProbe:
    def __init__(self, health_url: str, *, ttl_s: float = 10.0, probe_fn=None) -> None:
        self.health_url = health_url
        self.ttl_s = ttl_s
        self.probe_fn = probe_fn or _probe_same_origin_health
        self._reachable = False
        self._checked_at: float = -1e9

    def reachable(self) -> bool:
        now = time.monotonic()
        if (now - self._checked_at) < self.ttl_s:
            return self._reachable
        self._reachable = self.probe_fn(self.health_url)
        self._checked_at = now
        return self._reachable


def install_world_routes(app, web_root, csp, *, mdns_discover_fn=None, read_guard=None,
                         same_origin_probe_fn=None):
    static_origin = _configured_world_origin()
    same_origin = (
        _SameOriginWorldProbe(_same_origin_health_url(), probe_fn=same_origin_probe_fn)
        if static_origin is None and _same_origin_enabled()
        else None
    )
    # Precedence: an explicit ROSY_WORLD_URL wins, then same-origin, then mDNS.
    mdns_target = None if same_origin is not None else _configured_mdns_target()
    locator = (
        _MdnsWorldLocator(*mdns_target, discover_fn=mdns_discover_fn)
        if mdns_target is not None
        else None
    )
    template = (web_root / "learning.html").read_text(encoding="utf-8")
    headers = {
        "Cache-Control": "no-store",
        "Content-Security-Policy": csp,
        "Referrer-Policy": "no-referrer",
    }

    def _current_status():
        if static_origin is not None:
            return {
                "configured": True,
                "mode": "static",
                "mdns_host": None,
                "url": f"{static_origin}/?view=factory",
                "reachable": True,
            }, f"{static_origin}/?view=factory"
        if same_origin is not None:
            reachable = same_origin.reachable()
            return {
                "configured": True,
                "mode": "same_origin",
                "mdns_host": None,
                "url": SAME_ORIGIN_PATH if reachable else None,
                "reachable": reachable,
            }, (SAME_ORIGIN_PATH if reachable else None)
        if locator is not None:
            resolved = locator.resolve()
            target = f"{resolved}/?view=factory" if resolved else None
            return {
                "configured": True,
                "mode": "mdns",
                "mdns_host": locator.host,
                "url": target,
                "reachable": resolved is not None,
            }, target
        return {
            "configured": False,
            "mode": "unconfigured",
            "mdns_host": None,
            "url": None,
            "reachable": False,
        }, None

    @app.get("/api/fleet/world-entry", include_in_schema=False, dependencies=list(read_guard or ()))
    def world_entry_status():
        body, _ = _current_status()
        return JSONResponse(body, headers=headers)

    @app.get("/console/world", include_in_schema=False)
    def open_world(request: Request):
        if request.url.query:
            raise HTTPException(status_code=400, detail="World entry does not accept query parameters")
        # Anonymous browsers log in first: the World shell behind Caddy has no login UI
        # of its own. Bearer clients are left to the proxy's forward_auth gate.
        sessions = getattr(app.state, "password_sessions", None)
        if (
            sessions is not None
            and not request.headers.get("authorization", "").startswith("Bearer ")
            and sessions.authenticate(request) is None
        ):
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse(
                    "/console/login?return=/console/world", status_code=303, headers=headers
                )
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "valid site credential required"},
                headers={"Cache-Control": "no-store"},
            )
        body, target = _current_status()
        if not target:
            hints = {
                "mdns": f"mDNS 호스트 {body['mdns_host']}의 Rosy World 3D에 아직 연결할 수 없습니다.",
                "same_origin": (
                    "같은 자리(same-origin) Rosy World 3D가 아직 준비되지 않았습니다."
                    " world 서비스가 살아나면 이 주소는 곧바로 3D 화면으로 이동합니다."
                ),
            }
            hint = hints.get(body["mode"]) or (
                "Rosy World 3D 연결 주소(ROSY_WORLD_URL 또는 ROSY_WORLD_MDNS_HOST)가 아직 등록되지 않았습니다."
            )
            doc = template.replace('data-host-focus="{{focus}}"', 'data-host-focus="world"')
            doc = doc.replace("로봇 학습 센터", "Rosy World 3D")
            doc = doc.replace(
                "이 호스트의 운영 연결이 아직 등록되지 않았습니다. 담당자가 보호된 Learning 원본을 등록하면 이 주소는 곧바로 Learning 화면으로 이동합니다.",
                hint,
            )
            return HTMLResponse(doc, status_code=503, headers=headers)
        return RedirectResponse(target, status_code=303, headers=headers)
