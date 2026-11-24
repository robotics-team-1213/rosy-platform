#!/usr/bin/env python3
"""Advertise ROSY World over mDNS (_rosy-world._tcp) and resolve both World and Fleet endpoints via .local."""
from __future__ import annotations

import argparse
from pathlib import Path
import signal
import socket
import sys
import tempfile
import threading

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from world_mdns_probe import (  # noqa: E402
    FLEET_SERVICE_TYPE,
    FLEET_TXT,
    HEALTH_MAX_BYTES,
    HOSTNAME_RE,
    WORLD_SERVICE_TYPE,
    WORLD_TXT,
    _default_browse,
    _default_resolve,
    _fetch_health_bytes,
    _health_ok,
    _lan_ipv4,
    _local_lan_ipv4s,
    _zeroconf_browse,
    classify_fleet,
    classify_world,
    discover_fleet_endpoint,
    discover_world_endpoint,
    normalize_local_host,
    parse_avahi_fleet,
    parse_avahi_world,
    parse_txt_pairs,
    probe_fleet_health,
    probe_world_health,
    select_candidate,
)


def render_world_service(
    port: int,
    *,
    tls: bool = False,
    tls_host: str | None = None,
    name: str = "ROSY World %h",
) -> str:
    """Render an Avahi service XML definition for _rosy-world._tcp."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("invalid ROSY World port")
    metadata = dict(WORLD_TXT)
    metadata["tls"] = "required" if tls else "none"
    if tls and tls_host:
        metadata["tls_host"] = normalize_local_host(tls_host)
    elif not tls and tls_host:
        raise ValueError("tls_host requires tls=True")
    records = "".join(
        f"    <txt-record>{key}={value}</txt-record>\n" for key, value in metadata.items()
    )
    return (
        '<?xml version="1.0" standalone="no"?>\n'
        '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
        "<service-group>\n"
        f'  <name replace-wildcards="yes">{name}</name>\n'
        "  <service>\n"
        f"    <type>{WORLD_SERVICE_TYPE}</type>\n"
        f"    <port>{port}</port>\n"
        f"{records}"
        "  </service>\n"
        "</service-group>\n"
    )


def publish_world_service(
    output: Path,
    port: int,
    *,
    tls: bool = False,
    tls_host: str | None = None,
    name: str = "ROSY World %h",
) -> None:
    """Atomically write an Avahi service XML file with 0644 permissions for Avahi daemon visibility."""
    payload = render_world_service(port, tls=tls, tls_host=tls_host, name=name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=".rosy-world-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temp = Path(stream.name)
        stream.write(payload)
    try:
        temp.chmod(0o644)
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)


class _XmlAdvertiser:
    """Atomic Avahi XML advertiser/withdrawer gated on live health checks."""

    def __init__(self, xml_path: Path, port: int, *, tls: bool = False, tls_host: str | None = None) -> None:
        self.xml_path = xml_path
        self.port = port
        self.tls = tls
        self.tls_host = tls_host
        self.active = False

    def update(self, ready: bool) -> None:
        if ready and not self.active:
            publish_world_service(self.xml_path, self.port, tls=self.tls, tls_host=self.tls_host)
            self.active = True
        elif not ready and self.active:
            self.close()

    def close(self) -> None:
        self.active = False
        self.xml_path.unlink(missing_ok=True)


class _ZeroconfAdvertiser:
    """Non-root multicast DNS-SD advertiser using pure-Python Zeroconf (works without D-Bus/root)."""

    def __init__(
        self,
        port: int,
        *,
        hostname: str | None = None,
        tls: bool = False,
        addresses: list[str] | None = None,
        service_type: str = WORLD_SERVICE_TYPE,
        service_name: str | None = None,
    ) -> None:
        raw_host = (hostname or f"{socket.gethostname().split('.')[0]}.local").strip()
        self.hostname = normalize_local_host(raw_host)
        self.port = int(port)
        self.tls = bool(tls)
        self.addresses = addresses
        self.service_type = service_type
        self.service_name = service_name
        self._zc = None
        self._info = None

    def update(self, ready: bool) -> None:
        if not ready:
            self.close()
            return
        if self._zc is not None:
            return
        from zeroconf import ServiceInfo, Zeroconf

        ips = self.addresses if self.addresses is not None else _local_lan_ipv4s()
        if not ips:
            raise ValueError("no LAN IPv4 address found for Zeroconf registration")
        short = self.hostname.removesuffix(".local")
        is_fleet = self.service_type == FLEET_SERVICE_TYPE
        props = dict(FLEET_TXT if is_fleet else WORLD_TXT)
        props["tls"] = "required" if self.tls else "none"
        if self.tls:
            props["tls_host"] = self.hostname
        instance = self.service_name or (f"ROSY Fleet {short}" if is_fleet else f"ROSY World {short}")
        info = ServiceInfo(
            f"{self.service_type}.local.",
            f"{instance}.{self.service_type}.local.",
            addresses=[socket.inet_aton(ip) for ip in ips],
            port=self.port,
            properties=props,
            server=f"{self.hostname}.",
        )
        zc = Zeroconf()
        try:
            zc.register_service(info)
        except BaseException:
            zc.close()
            raise
        self._zc = zc
        self._info = info

    def close(self) -> None:
        zc, info = self._zc, self._info
        self._zc = None
        self._info = None
        if zc is not None:
            try:
                if info is not None:
                    zc.unregister_service(info)
            except Exception:
                pass
            finally:
                zc.close()


def advertise_loop(
    *,
    port: int,
    health_url: str,
    avahi_services_dir: Path,
    tls: bool = False,
    tls_host: str | None = None,
    hostname: str | None = None,
    mode: str = "auto",
    interval_s: float = 5.0,
    stop_event: threading.Event | None = None,
    service_type: str = WORLD_SERVICE_TYPE,
    service_name: str | None = None,
    ca_file: Path | None = None,
) -> int:
    use_zeroconf = mode == "zeroconf"
    if mode == "auto":
        try:
            import zeroconf  # noqa: F401
            use_zeroconf = True
        except ImportError:
            use_zeroconf = False
    advertiser = (
        _ZeroconfAdvertiser(
            port, hostname=hostname or tls_host, tls=tls,
            service_type=service_type, service_name=service_name,
        )
        if use_zeroconf
        else _XmlAdvertiser(avahi_services_dir / "rosy-world.service", port, tls=tls, tls_host=tls_host)
    )
    stopped = stop_event or threading.Event()
    previous: bool | None = None
    try:
        while not stopped.is_set():
            ready = _health_ok(health_url, service_type=service_type, ca_file=ca_file, tls_host=tls_host or hostname)
            advertiser.update(ready)
            if ready != previous:
                kind = "zeroconf" if use_zeroconf else "xml"
                print(
                    f"rosy-world mDNS ({kind}): {'advertising ' + service_type if ready else 'withdrawn, target not ready'}",
                    flush=True,
                )
                previous = ready
            stopped.wait(max(1.0, float(interval_s)))
    finally:
        advertiser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pub = sub.add_parser("publish", help="write atomic Avahi service XML for _rosy-world._tcp")
    pub.add_argument("--port", type=int, required=True)
    pub.add_argument("--tls", action="store_true")
    pub.add_argument("--tls-host")
    pub.add_argument("--output", type=Path, default=Path("/etc/avahi/services/rosy-world.service"))

    adv = sub.add_parser("advertise", help="advertise _rosy-world._tcp or _rosy-fleet._tcp only while /healthz is ready")
    adv.add_argument("--port", type=int, required=True)
    adv.add_argument("--health-url", default="http://127.0.0.1:8140/healthz")
    adv.add_argument("--avahi-services-dir", type=Path, default=Path("/etc/avahi/services"))
    adv.add_argument("--hostname", default="", help="optional .local hostname override")
    adv.add_argument("--mode", choices=("auto", "zeroconf", "xml"), default="auto")
    adv.add_argument("--service-type", choices=(WORLD_SERVICE_TYPE, FLEET_SERVICE_TYPE), default=WORLD_SERVICE_TYPE)
    adv.add_argument("--name", help="optional DNS-SD service instance name")
    adv.add_argument("--tls", action="store_true")
    adv.add_argument("--tls-host")
    adv.add_argument("--ca-file", type=Path)
    adv.add_argument("--interval", type=float, default=5.0)

    disc = sub.add_parser("discover", help="discover World or Fleet endpoint by .local hostname")
    disc.add_argument("--role", choices=("world", "fleet"), required=True)
    disc.add_argument("--expect-hostname", required=True)
    disc.add_argument("--port", type=int)
    disc.add_argument("--scheme", choices=("http", "https"), default="http")
    disc.add_argument("--ca-file", type=Path)
    disc.add_argument("--no-probe", action="store_true")

    args = parser.parse_args()
    if args.command == "publish":
        publish_world_service(args.output, args.port, tls=args.tls, tls_host=args.tls_host)
        return 0
    if args.command == "advertise":
        stop_event = threading.Event()
        for kind in (signal.SIGINT, signal.SIGTERM):
            signal.signal(kind, lambda *_: stop_event.set())
        return advertise_loop(
            port=args.port,
            health_url=args.health_url,
            avahi_services_dir=args.avahi_services_dir,
            tls=args.tls,
            tls_host=args.tls_host,
            hostname=(args.hostname.strip() or None),
            mode=args.mode,
            interval_s=args.interval,
            stop_event=stop_event,
            service_type=args.service_type,
            service_name=(args.name.strip() if args.name else None),
            ca_file=args.ca_file,
        )
    if args.role == "world":
        endpoint = discover_world_endpoint(
            args.expect_hostname,
            default_port=args.port or 8140,
            scheme=args.scheme,
            ca_file=args.ca_file,
            verify_health=not args.no_probe,
        )
    else:
        endpoint = discover_fleet_endpoint(
            args.expect_hostname,
            default_port=args.port or 8443,
            ca_file=args.ca_file,
            verify_health=not args.no_probe,
        )
    print(endpoint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
