"""mDNS record parsing, validation, and health probing for ROSY World and Fleet."""
from __future__ import annotations

import http.client
import ipaddress
import json
from pathlib import Path
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import threading
from typing import Callable
import urllib.error
import urllib.request

WORLD_SERVICE_TYPE = "_rosy-world._tcp"
FLEET_SERVICE_TYPE = "_rosy-fleet._tcp"
HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")
WORLD_TXT = {
    "product": "rosy",
    "role": "world",
    "proto": "rosy-world/1",
    "tls": "none",
    "worlds_api": "1",
}
FLEET_TXT = {
    "product": "rosy",
    "role": "fleet",
    "proto": "site-v1",
    "tls": "required",
}
HEALTH_MAX_BYTES = 1024


def normalize_local_host(host: str) -> str:
    """Validate and normalize a single-label .local mDNS hostname."""
    if not isinstance(host, str):
        raise ValueError("mDNS hostname must be a string")
    value = host.strip().lower().rstrip(".")
    if not HOSTNAME_RE.fullmatch(value):
        raise ValueError(f"invalid .local mDNS hostname: {host!r}")
    return value


def _lan_ipv4(address: str | None) -> bool:
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except (ValueError, TypeError):
        return False
    return (
        ip.version == 4
        and ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def parse_txt_pairs(text: str) -> list[tuple[str, str]]:
    """Parse Avahi's quoted TXT column keeping duplicates so validators catch them."""
    try:
        items = shlex.split(text)
    except ValueError:
        return []
    return [tuple(item.split("=", 1)) for item in items if "=" in item]


def classify_world(
    host: str | None,
    address: str | None,
    port: object,
    txt: list[tuple[str, str]],
) -> str | None:
    """Classify a resolved _rosy-world._tcp record; returns None if valid, else reason string."""
    if host is not None:
        try:
            normalize_local_host(host)
        except ValueError:
            return "bad_host"
    if address is not None and not _lan_ipv4(address):
        return "bad_address"
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return "bad_port"
    keys = [key for key, _ in txt]
    if len(keys) != len(set(keys)):
        return "duplicate_key"
    values = dict(txt)
    for key in ("product", "role", "proto", "tls"):
        if key not in values:
            return "missing_key"
        if key == "tls":
            if values[key] not in ("none", "required"):
                return "value_mismatch"
        elif values[key] != WORLD_TXT[key]:
            return "value_mismatch"
    if values["tls"] == "required" and values.get("tls_host"):
        try:
            tls_host = normalize_local_host(values["tls_host"])
        except ValueError:
            return "bad_host"
        if host is not None and tls_host != normalize_local_host(host):
            return "tls_host_mismatch"
    return None


def classify_fleet(
    host: str | None,
    address: str | None,
    port: object,
    txt: list[tuple[str, str]],
) -> str | None:
    """Classify a resolved _rosy-fleet._tcp record; returns None if valid, else reason string."""
    if host is not None:
        try:
            normalize_local_host(host)
        except ValueError:
            return "bad_host"
    if address is not None and not _lan_ipv4(address):
        return "bad_address"
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return "bad_port"
    keys = [key for key, _ in txt]
    if len(keys) != len(set(keys)):
        return "duplicate_key"
    values = dict(txt)
    for key, expected in FLEET_TXT.items():
        if key not in values:
            return "missing_key"
        if values[key] != expected:
            return "value_mismatch"
    return None


def parse_avahi_world(output: str) -> list[dict]:
    """Extract deduplicated valid _rosy-world._tcp rows from `avahi-browse -r -t -p -k` output."""
    candidates: dict[tuple[str, str, int], dict] = {}
    for line in output.splitlines():
        columns = line.split(";", 9)
        if (
            len(columns) != 10
            or columns[0] != "="
            or columns[2] != "IPv4"
            or columns[4] != WORLD_SERVICE_TYPE
            or columns[5] != "local"
        ):
            continue
        try:
            port = int(columns[8])
        except ValueError:
            continue
        pairs = parse_txt_pairs(columns[9])
        if classify_world(columns[6], columns[7], port, pairs) is not None:
            continue
        hostname = normalize_local_host(columns[6])
        txt = dict(pairs)
        row = {
            "hostname": hostname,
            "address": columns[7],
            "port": port,
            "scheme": "https" if txt.get("tls") == "required" else "http",
            "txt": txt,
        }
        candidates[(hostname, columns[7], port)] = row
    return list(candidates.values())


def parse_avahi_fleet(output: str) -> list[dict]:
    """Extract deduplicated valid _rosy-fleet._tcp rows from `avahi-browse -r -t -p -k` output."""
    candidates: dict[tuple[str, str, int], dict] = {}
    for line in output.splitlines():
        columns = line.split(";", 9)
        if (
            len(columns) != 10
            or columns[0] != "="
            or columns[2] != "IPv4"
            or columns[4] != FLEET_SERVICE_TYPE
            or columns[5] != "local"
        ):
            continue
        try:
            port = int(columns[8])
        except ValueError:
            continue
        pairs = parse_txt_pairs(columns[9])
        if classify_fleet(columns[6], columns[7], port, pairs) is not None:
            continue
        hostname = normalize_local_host(columns[6])
        row = {
            "hostname": hostname,
            "address": columns[7],
            "port": port,
            "scheme": "https",
        }
        candidates[(hostname, columns[7], port)] = row
    return list(candidates.values())


def select_candidate(candidates: list[dict], expected_hostname: str) -> dict:
    expected = normalize_local_host(expected_hostname)
    matches = [item for item in candidates if item.get("hostname") == expected]
    if not matches:
        raise ValueError(f"expected mDNS host not found: {expected}")
    if len(matches) != 1:
        raise ValueError(f"ambiguous mDNS host advertisement: {expected}")
    return matches[0]


def _fetch_health_bytes(
    host_or_addr: str,
    port: int,
    *,
    scheme: str,
    hostname: str,
    ca_file: Path | None,
    timeout_s: float,
) -> tuple[int, bytes]:
    if scheme == "https":
        context = ssl.create_default_context(cafile=str(ca_file)) if ca_file else ssl.create_default_context()
        with socket.create_connection((host_or_addr, port), timeout=timeout_s) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as secured:
                secured.settimeout(timeout_s)
                secured.sendall(
                    f"GET /healthz HTTP/1.1\r\nHost: {hostname}:{port}\r\nConnection: close\r\n\r\n".encode("ascii")
                )
                resp = http.client.HTTPResponse(secured)
                resp.begin()
                return resp.status, resp.read(HEALTH_MAX_BYTES + 1)
    conn = http.client.HTTPConnection(host_or_addr, port, timeout=timeout_s)
    try:
        conn.request("GET", "/healthz", headers={"Host": f"{hostname}:{port}", "Connection": "close"})
        resp = conn.getresponse()
        return resp.status, resp.read(HEALTH_MAX_BYTES + 1)
    finally:
        conn.close()


def probe_world_health(
    host_or_addr: str,
    port: int,
    *,
    scheme: str = "http",
    hostname: str | None = None,
    ca_file: Path | None = None,
    timeout_s: float = 2.0,
) -> dict:
    """Verify live Rosy World /healthz readiness (preserving .local SNI for TLS)."""
    target_host = hostname or host_or_addr
    try:
        status, raw = _fetch_health_bytes(
            host_or_addr, port, scheme=scheme, hostname=target_host, ca_file=ca_file, timeout_s=timeout_s,
        )
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        raise ValueError(f"World health check failed: {error}") from error
    if status != 200:
        raise ValueError(f"unexpected World health HTTP status: {status}")
    if len(raw) > HEALTH_MAX_BYTES:
        raise ValueError("World health response exceeds size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"invalid World health JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("application") != "rosy-world" or payload.get("status") != "ready":
        raise ValueError("unexpected Rosy World /healthz body")
    return payload


def probe_fleet_health(
    host_or_addr: str,
    port: int,
    *,
    hostname: str,
    ca_file: Path | None = None,
    timeout_s: float = 2.0,
) -> dict:
    """Verify live Fleet HTTPS /healthz readiness (connecting to IPv4 while verifying .local cert SAN)."""
    try:
        status, raw = _fetch_health_bytes(
            host_or_addr, port, scheme="https", hostname=hostname, ca_file=ca_file, timeout_s=timeout_s,
        )
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        raise ValueError(f"Fleet health check failed: {error}") from error
    if status != 200:
        raise ValueError(f"unexpected Fleet health HTTP status: {status}")
    if len(raw) > HEALTH_MAX_BYTES:
        raise ValueError("Fleet health response exceeds size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"invalid Fleet health JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ValueError("unexpected Fleet /healthz body")
    return payload


def _default_browse(service_type: str) -> str | None:
    if not shutil.which("avahi-browse"):
        return None
    try:
        proc = subprocess.run(
            ["avahi-browse", "-r", "-t", "-p", "-k", service_type],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
        )
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _default_resolve(hostname: str, port: int) -> str:
    infos = socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_STREAM)
    if not infos:
        raise ValueError(f"could not resolve {hostname} via mDNS/NSS")
    return str(infos[0][4][0])


def _local_lan_ipv4s() -> list[str]:
    """Return active non-loopback RFC1918 IPv4 addresses on this host for Zeroconf registration."""
    addrs: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            primary = sock.getsockname()[0]
            if _lan_ipv4(primary):
                addrs.append(primary)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            cand = str(info[4][0])
            if _lan_ipv4(cand) and cand not in addrs:
                addrs.append(cand)
    except OSError:
        pass
    if len(addrs) > 1:
        non_bridge = [a for a in addrs if not a.startswith("172.17.")]
        if non_bridge:
            return non_bridge
    return addrs


def _zeroconf_browse(service_type: str, expected_hostname: str, *, timeout_s: float = 1.2) -> dict | None:
    """Browse LAN mDNS via pure-Python Zeroconf (works without D-Bus/avahi-browse CLI)."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return None
    expected = normalize_local_host(expected_hostname)
    found: dict | None = None
    done = threading.Event()
    fq_type = f"{service_type}.local."
    classifier = classify_world if service_type == WORLD_SERVICE_TYPE else classify_fleet

    class _Listener:
        def remove_service(self, _zc, _type, _name):
            return None

        def update_service(self, zc, stype, name):
            self.add_service(zc, stype, name)

        def add_service(self, zc, stype, name):
            nonlocal found
            info = zc.get_service_info(stype, name, timeout=500)
            if not info or not info.server or not info.port:
                return
            server = info.server.strip().lower().rstrip(".")
            if server != expected:
                return
            addrs = [socket.inet_ntoa(raw) for raw in info.addresses if len(raw) == 4]
            lan_addr = next((a for a in addrs if _lan_ipv4(a)), addrs[0] if addrs else None)
            pairs = [
                (
                    k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k),
                    v.decode("utf-8", errors="replace") if isinstance(v, bytes) else ("" if v is None else str(v)),
                )
                for k, v in (info.properties or {}).items()
            ]
            if classifier(server, lan_addr, int(info.port), pairs) is not None:
                return
            txt = dict(pairs)
            found = {
                "hostname": server,
                "address": lan_addr or server,
                "port": int(info.port),
                "scheme": "https" if (service_type == FLEET_SERVICE_TYPE or txt.get("tls") == "required") else "http",
                "txt": txt,
            }
            done.set()

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, fq_type, _Listener())
        done.wait(timeout_s)
    finally:
        zc.close()
    return found


def discover_world_endpoint(
    expected_hostname: str,
    *,
    default_port: int = 8140,
    scheme: str = "http",
    ca_file: Path | None = None,
    verify_health: bool = True,
    browse_fn: Callable[[str], str | None] | None = None,
    resolve_fn: Callable[[str, int], str] | None = None,
) -> str:
    """Resolve `expected_hostname` (.local) via Avahi CLI, Zeroconf, or container NSS."""
    expected = normalize_local_host(expected_hostname)
    browse = browse_fn or _default_browse
    resolve = resolve_fn or _default_resolve
    target_port = int(default_port)
    target_scheme = scheme
    dial_host = expected
    discovered = False

    raw = browse(WORLD_SERVICE_TYPE)
    if raw:
        candidates = parse_avahi_world(raw)
        if candidates:
            selected = select_candidate(candidates, expected)
            target_port = int(selected["port"])
            target_scheme = str(selected["scheme"])
            dial_host = str(selected["address"])
            discovered = True

    if not discovered and browse_fn is None:
        zc_row = _zeroconf_browse(WORLD_SERVICE_TYPE, expected)
        if zc_row is not None:
            target_port = int(zc_row["port"])
            target_scheme = str(zc_row["scheme"])
            dial_host = str(zc_row["address"])
            discovered = True

    if not discovered:
        dial_host = resolve(expected, target_port)

    if verify_health:
        probe_world_health(dial_host, target_port, scheme=target_scheme, hostname=expected, ca_file=ca_file)
    return f"{target_scheme}://{expected}:{target_port}"


def discover_fleet_endpoint(
    expected_hostname: str,
    *,
    default_port: int = 8443,
    ca_file: Path | None = None,
    verify_health: bool = True,
    browse_fn: Callable[[str], str | None] | None = None,
    resolve_fn: Callable[[str, int], str] | None = None,
) -> str:
    """Resolve a separate Fleet host (.local) via Avahi CLI, Zeroconf, or container NSS."""
    expected = normalize_local_host(expected_hostname)
    browse = browse_fn or _default_browse
    resolve = resolve_fn or _default_resolve
    target_port = int(default_port)
    dial_host = expected
    discovered = False

    raw = browse(FLEET_SERVICE_TYPE)
    if raw:
        candidates = parse_avahi_fleet(raw)
        if candidates:
            selected = select_candidate(candidates, expected)
            target_port = int(selected["port"])
            dial_host = str(selected["address"])
            discovered = True

    if not discovered and browse_fn is None:
        zc_row = _zeroconf_browse(FLEET_SERVICE_TYPE, expected)
        if zc_row is not None:
            target_port = int(zc_row["port"])
            dial_host = str(zc_row["address"])
            discovered = True

    if not discovered:
        dial_host = resolve(expected, target_port)

    if verify_health:
        probe_fleet_health(dial_host, target_port, hostname=expected, ca_file=ca_file)
    return f"https://{expected}:{target_port}"


def _health_ok(
    health_url: str,
    *,
    service_type: str = WORLD_SERVICE_TYPE,
    ca_file: Path | None = None,
    tls_host: str | None = None,
) -> bool:
    if service_type == FLEET_SERVICE_TYPE and health_url.startswith("https://") and tls_host:
        from urllib.parse import urlsplit

        parsed = urlsplit(health_url)
        try:
            probe_fleet_health(parsed.hostname or "127.0.0.1", parsed.port or 8443, hostname=tls_host, ca_file=ca_file)
            return True
        except (OSError, ValueError):
            return False
    context = ssl.create_default_context(cafile=str(ca_file)) if (health_url.startswith("https://") and ca_file) else None
    try:
        with urllib.request.urlopen(health_url, timeout=2.0, context=context) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read(HEALTH_MAX_BYTES).decode("utf-8"))
            if service_type == FLEET_SERVICE_TYPE:
                return isinstance(data, dict) and data.get("status") == "ok"
            return isinstance(data, dict) and data.get("application") == "rosy-world" and data.get("status") == "ready"
    except (OSError, urllib.error.URLError, ValueError):
        return False
