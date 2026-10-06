"""``rosy-vision`` — CLI front end for the receive-only ingest server.

``rosy-vision receive`` starts :class:`rosy_vision.ingest.IngestServer`,
prints a ``rosyov://`` pairing URI (and an ASCII QR code when the optional
``qrcode`` package is installed), and prints per-source stats once a
second. See docs/adr/D-261-overhead-camera-app-skeleton.md.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import ipaddress
import json
import logging
import os
import secrets
import ssl
import socket
import sys
import time
from pathlib import Path
from typing import Sequence

from core_common.protocol.discovery_txt import HOSTNAME
from rosy_vision import protocol
from rosy_vision.field_calib import FieldCalibrator
from rosy_vision.ingest import STATUS_INTERVAL_S, IngestServer
from rosy_vision import map_worker
from rosy_vision.map_register import load_map_paint
from rosy_vision.pairing_sync import PairedCredentials, PairingSync
from rosy_vision.publish import SightingPublishError, SightingPublisher
from rosy_vision.vision_config import load_vision_sources
from rosy_vision.track.fleet_client import TrackClient
from rosy_vision.track.worker import TrackWorker
from rosy_vision.worker import VisionWorker
from core_common.protocol.vision_preview import VisionLeaseSigner

logger = logging.getLogger("rosy_vision")


def _detect_advertise_host(host: str) -> str:
    """Best-effort LAN IP guess when --advertise-host is not given and --host is a wildcard."""
    if host not in ("0.0.0.0", "::", ""):
        return host
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # no packet actually sent; just picks the outbound route
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostname()
    finally:
        sock.close()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _warn_ip_host(host: str) -> None:
    """Pairing links carry a name by default (D-391); an IP is only a bench / manual fallback."""
    print(
        f"WARNING: {host} is an IP address. The phone stores it as a \"수동 주소\" (manual_host) fallback "
        "that is used only when mDNS cannot find the site, and it breaks when the site subnet changes. "
        "The site certificate also needs this IP as an IP SAN. "
        "Recommended: --host <tls_host>.local (D-391, D-341 13).",
        file=sys.stderr,
    )


def _link_host(args: argparse.Namespace) -> str:
    """Host the pairing link carries: an explicit --advertise-host, else a ``.local`` name (D-391)."""
    if args.advertise_host:
        return args.advertise_host
    if args.tls_host:
        name = args.tls_host.lower()
        if not HOSTNAME.fullmatch(name):
            raise ValueError(f"--tls-host {args.tls_host!r} must be <name>.local; "
                             "use --advertise-host for a site FQDN or an IP")
        return name
    raw = socket.gethostname()
    name = f"{raw}.local".lower()
    if not HOSTNAME.fullmatch(name):
        raise ValueError(f"hostname {raw!r} cannot be a .local name: underscores and dots are not allowed "
                         "in a .local name; pass --tls-host <name>.local")
    return name


def _print_pairing(uri: str) -> None:
    print(f"pairing: {uri}")
    try:
        import qrcode
    except ImportError:
        print("(install the 'qrcode' package to also print an ASCII QR code here)")
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(uri)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def _read_pem(path: Path) -> str:
    """PEM text; a UTF-8 BOM is tolerated. Undecodable bytes become a clean ValueError."""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{path} is not a PEM text file") from None


def _served_pins(path: Path) -> list[str]:
    """Pins of the chain a TLS server serves from ``path``, leaf first."""
    return protocol.pem_cert_pins(_read_pem(path))


_FULLCHAIN_HINT = ("serve leaf + CA: `cat site.crt site-ca.crt > site-fullchain.crt` and point the proxy's "
                   "certificate (Caddy `tls` / Compose secret site_cert) at it; Caddy serves the whole file")


def _choose_ca_pin(served: Path, ca: Path) -> str:
    """The site CA pin, only when the served chain carries that CA above the leaf (D-341 9).

    D-341 9 pins the site CA; a leaf-only pin is not issued. The phone matches only certificates the
    proxy sends, so a CA missing from ``served`` would fail on the phone; refuse it here instead.
    """
    served_pins = _served_pins(served)
    pin = protocol.pem_last_cert_pin(_read_pem(ca))
    if pin == served_pins[0]:
        raise ValueError(f"{ca} is the served leaf, not the site CA (D-341 9 pins the CA, never a leaf)")
    if pin not in served_pins[1:]:
        raise ValueError(f"{served} does not carry the CA from {ca}; the phone would reject the site. "
                         + _FULLCHAIN_HINT)
    return pin


def _receive_pin(served: Path) -> str | None:
    """CA pin for ``receive --tls-cert``: the last certificate when the file is leaf + CA, else none."""
    try:
        served_pins = _served_pins(served)
    except (OSError, ValueError) as exc:
        print(f"no pin in the pairing link: {exc}")
        return None
    if len(served_pins) < 2:
        print("no pin in the pairing link: the served file is leaf-only and D-341 9 pins only the site CA; "
              + _FULLCHAIN_HINT)
        return None
    return served_pins[-1]


def _pair_link(args: argparse.Namespace) -> int:
    """Print a CA-pinned ``rosyov://...&tls=1&pin=`` link for a site TLS proxy."""
    token = os.environ.get(args.token_env)
    if not token:
        print(f"${args.token_env} must hold the phone token for source {args.source!r}", file=sys.stderr)
        return 2
    try:
        pin = _choose_ca_pin(args.pin_cert, args.pin_ca)
    except (OSError, ValueError) as exc:
        print(f"pair-link: {exc}", file=sys.stderr)
        return 2
    if _is_ip(args.host):
        _warn_ip_host(args.host)
    uri = protocol.pairing_uri(args.host, args.port, token, args.source, secure=True, pin=pin)
    print(f"pin: {pin}  (site CA; the phone shows the first 19 characters when it saves the link)")
    _print_pairing(uri)
    return 0


def _server_ssl_context(cert: Path | None, key: Path | None) -> ssl.SSLContext | None:
    if bool(cert) != bool(key):
        raise ValueError("--tls-cert and --tls-key must be provided together")
    if cert is None:
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert), keyfile=str(key))
    return context


def _write_latest_jpeg(server: IngestServer, out_dir: Path) -> None:
    for source in server.source_names():
        frame = server.latest_frame(source)
        if frame is None:
            continue
        tmp = out_dir / f"{source}.jpg.tmp"
        tmp.write_bytes(frame.jpeg)
        tmp.replace(out_dir / f"{source}.jpg")


def _format_stats_line(source: str, snap: dict) -> str:
    return (
        f"{source}: frames={snap['frames']} rx_fps={snap['rx_fps']} "
        f"bytes/s={snap['bytes_per_s']} age_ms(p50/max)={snap['age_ms_p50']}/{snap['age_ms_max']} "
        f"dropped_bad_header={snap['dropped_bad_header']} oversize={snap['oversize']} "
        f"last_seq={snap['last_seq']} seq_gaps={snap['seq_gaps']}"
    )


async def _run_receive(args: argparse.Namespace) -> int:
    token = os.environ.get(args.token_env)
    if not token:
        token = secrets.token_urlsafe(24)
        print(f"${args.token_env} is not set; generated a token for this run only")

    try:
        link_host = _link_host(args)
    except ValueError as exc:
        print(f"receive: {exc}", file=sys.stderr)
        return 2
    server = IngestServer({args.source_name: token})
    ws_server = await server.start(args.host, args.port, ssl_context=_server_ssl_context(args.tls_cert, args.tls_key))
    pin = _receive_pin(args.tls_cert) if args.tls_cert else None
    uri = protocol.pairing_uri(link_host, args.port, token, args.source_name,
                               secure=bool(args.tls_cert), pin=pin)
    print(f"listening on {args.host}:{args.port}{protocol.WS_PATH}")
    if _is_ip(link_host):
        _warn_ip_host(link_host)
    else:
        probe = _detect_advertise_host(args.host)
        print(f"IP fallback: {probe if _is_ip(probe) else 'unknown (no route)'}  "
              "(diagnostic only; not in the link)")
        if not args.advertise_host and args.host not in ("0.0.0.0", "::", ""):
            print(f"link host is {link_host} (D-391); use --advertise-host <ip> to pair by IP "
                  "(fallback, needs an IP SAN)")
    _print_pairing(uri)

    stats_file = args.stats_jsonl.open("a", encoding="utf-8") if args.stats_jsonl else None
    save_dir = args.save_latest
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            await asyncio.sleep(STATUS_INTERVAL_S)
            now = time.time()
            sources = server.source_names()
            if not sources:
                print("(no sources connected)")
            for source in sources:
                snap = server.stats(source)
                print(_format_stats_line(source, snap))
                if stats_file is not None:
                    stats_file.write(json.dumps({"ts": now, "source": source, **snap}) + "\n")
                    stats_file.flush()
            if save_dir is not None:
                _write_latest_jpeg(server, save_dir)
    finally:
        if stats_file is not None:
            stats_file.close()
        ws_server.close()
        await ws_server.wait_closed()


def _vision_ingest(args: argparse.Namespace, configs, *, environ=os.environ):
    """Build the ingest server and the D-341 sync settings, refusing unsafe secret reuse.

    Returns ``(ingest, sync)`` where ``sync`` is ``{"url", "token", "ca_file"}`` when the
    config has ``paired`` sources, else None.
    """
    known_tokens = {config.sighting_token for config in configs}
    known_tokens |= {config.phone_token for config in configs if config.phone_token is not None}
    preview_secret = environ.get("ROSY_VISION_PREVIEW_SECRET")
    if preview_secret and preview_secret in known_tokens:
        raise ValueError("vision preview secret must differ from phone and sighting credentials")
    paired_sources = [config.camera.source_id for config in configs if config.credential == "paired"]
    sync_url = getattr(args, "pairing_sync_url", None)
    sync_env = getattr(args, "pairing_sync_token_env", None)
    sync = None
    if paired_sources:
        if not sync_url or not sync_env:
            raise ValueError("paired sources need --pairing-sync-url and --pairing-sync-token-env "
                             "(D-341 12: Vision reads issued credentials from Fleet)")
        token = environ.get(sync_env)
        if not token:
            raise ValueError(f"pairing sync token environment variable {sync_env} is required")
        if token in known_tokens or token == preview_secret:
            raise ValueError("pairing sync token must differ from phone, sighting and preview secrets")
        ca_file = getattr(args, "pairing_sync_ca", None)
        sync = {"url": sync_url, "token": token, "ca_file": str(ca_file) if ca_file else None}
    elif sync_url or sync_env:
        raise ValueError("--pairing-sync-* is set but site-cameras.yaml has no credential: paired source")
    ingest = IngestServer(
        {config.camera.source_id: config.phone_token for config in configs
         if config.phone_token is not None},
        preview_signer=VisionLeaseSigner(preview_secret) if preview_secret else None,
        map_paint=load_map_paint(args.map_paint) if args.map_paint else None,
        paired=PairedCredentials(paired_sources) if paired_sources else None,
    )
    return ingest, sync


async def _run_vision(args: argparse.Namespace) -> int:
    configs = load_vision_sources(args.config)
    ingest, sync_settings = _vision_ingest(args, configs)
    workers = []
    trackers = []
    # D-484: field_boundary sources calibrate from the boundary quad; orientation
    # comes from the lane paint, so the map paint is required and one extra
    # low-priority worker process serves the registration requests.
    field_configs = [config for config in configs
                     if config.camera.calibration_source == "field_boundary"]
    paint_executor = None
    paint_registrar = None
    if field_configs:
        if not args.map_paint:
            raise ValueError("--map-paint is required for a field_boundary source "
                             "(D-484: the orientation comes from the lane paint)")
        paint_executor = map_worker.start(load_map_paint(args.map_paint))
        registration_loop = asyncio.get_running_loop()

        async def _register(jpeg: bytes):
            return await registration_loop.run_in_executor(
                paint_executor, map_worker.register, jpeg)

        paint_registrar = _register

    async with AsyncExitStack() as stack:
        for config in configs:
            publisher = await stack.enter_async_context(
                SightingPublisher(config.fleet_base_url, config.sighting_token)
            )
            tracker = None
            if getattr(args, "track", False):
                client = await stack.enter_async_context(
                    TrackClient(config.fleet_base_url, config.sighting_token))
                tracker = TrackWorker(camera=config.camera, ingest=ingest, client=client)
                trackers.append(tracker)
            calibrator = None
            if config.camera.calibration_source == "field_boundary":
                calibrator = FieldCalibrator(config.camera.corner_world_m)
            workers.append(VisionWorker(
                source_id=config.camera.source_id,
                ingest=ingest,
                camera=config.camera,
                publisher=publisher,
                tracker=tracker,
                calibrator=calibrator,
                paint_registrar=paint_registrar if calibrator is not None else None,
            ))
        ws_server = await ingest.start(args.host, args.port,
                                       ssl_context=_server_ssl_context(args.tls_cert, args.tls_key))
        print(f"vision pipeline listening on {args.host}:{args.port}{protocol.WS_PATH} "
              f"for {len(workers)} configured sources"
              f"{' with markerless tracking' if trackers else ''}"
              f"{' with field-boundary calibration' if field_configs else ''}", flush=True)
        sync = None
        if sync_settings is not None:
            loop = asyncio.get_running_loop()
            # Own thread (2026-10-01 starvation lesson); only enforcement hops onto the loop.
            sync = PairingSync(ingest.paired, **sync_settings,
                               on_cycle=lambda: loop.call_soon_threadsafe(
                                   ingest.enforce_paired_credentials))
            sync.start()
        stop_tracking = asyncio.Event()
        config_tasks = [asyncio.create_task(tracker.run_config_sync(stop_tracking))
                        for tracker in trackers]
        try:
            while True:
                for worker in workers:
                    try:
                        await worker.process_latest()
                    except SightingPublishError as exc:
                        logger.warning("sighting rejected status=%d code=%s",
                                       exc.status_code, exc.code)
                    except Exception as exc:
                        # Do not log URLs, request bodies, headers, or arbitrary exception text.
                        logger.error("vision frame failed error_type=%s", type(exc).__name__)
                await asyncio.sleep(0.03)
        finally:
            stop_tracking.set()
            await asyncio.gather(*config_tasks, return_exceptions=True)
            for tracker in trackers:
                tracker.close()
            if sync is not None:
                sync.stop()
            ws_server.close()
            await ws_server.wait_closed()
            ingest.close_map_worker()
            if paint_executor is not None:
                paint_executor.shutdown(wait=False, cancel_futures=True)
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rosy-vision")
    sub = parser.add_subparsers(dest="command", required=True)

    receive = sub.add_parser("receive", help="run the receive-only ingest server")
    receive.add_argument("--host", default="0.0.0.0")
    receive.add_argument("--port", type=int, default=8095)
    receive.add_argument("--token-env", default="ROSY_OVERHEAD_TOKEN")
    receive.add_argument(
        "--source-name", default="overhead-1", help="source name shown in the printed pairing URI"
    )
    receive.add_argument("--stats-jsonl", type=Path, default=None)
    receive.add_argument("--advertise-host", default=None,
                         help="explicit host for the pairing link (an IP is a manual fallback, D-391)")
    receive.add_argument("--tls-host", default=None,
                         help="<name>.local for the pairing link; default is this host's name + .local")
    receive.add_argument("--save-latest", type=Path, default=None, metavar="DIR")
    receive.add_argument("--tls-cert", type=Path, default=None)
    receive.add_argument("--tls-key", type=Path, default=None)

    vision = sub.add_parser("vision", help="receive camera frames and publish display-only sightings")
    vision.add_argument("--config", required=True, type=Path, help="site-cameras.yaml")
    vision.add_argument("--host", default="0.0.0.0")
    vision.add_argument("--port", type=int, default=8095)
    vision.add_argument("--tls-cert", type=Path, default=None)
    vision.add_argument("--tls-key", type=Path, default=None)
    vision.add_argument("--pairing-sync-url", default=None,
                        help="Fleet backend base URL for D-341 paired credentials, e.g. https://fleet:8090")
    vision.add_argument("--pairing-sync-token-env", default=None,
                        help="environment variable holding Vision's dedicated pairing sync token")
    vision.add_argument("--pairing-sync-ca", type=Path, default=None,
                        help="CA PEM that verifies Fleet's TLS certificate (the site CA)")
    vision.add_argument("--map-paint", type=Path, default=None,
                        help="site map lane paint STL in map metres (e.g. road_lines.stl); "
                             "enables the D-375 map-proposal view")
    vision.add_argument("--track", action="store_true",
                        help="D-457 markerless tracking: publish anonymous floor detections to Fleet "
                             "(needs an approved paint-fit calibration or all four corner markers)")

    link = sub.add_parser(
        "pair-link",
        help="print a pinned wss pairing link (and QR) for a site TLS proxy; the token comes from --token-env",
    )
    link.add_argument("--host", required=True, help="tls_host the phone dials (<name>.local or site FQDN); an IP is a manual fallback and warns")
    link.add_argument("--port", type=int, required=True, help="published TLS port, e.g. the proxy's 8443")
    link.add_argument("--source", required=True, help="camera source id from site-cameras.yaml")
    link.add_argument("--token-env", default="ROSY_OVERHEAD_TOKEN")
    link.add_argument(
        "--pin-ca", required=True, type=Path,
        help="site CA PEM (site-ca.crt) to pin (D-341 9: the CA, never a leaf)",
    )
    link.add_argument(
        "--pin-cert", required=True, type=Path,
        help="PEM the proxy serves (site-fullchain.crt); must carry the CA above the leaf",
    )

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "receive":
        try:
            asyncio.run(_run_receive(args))
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "vision":
        try:
            asyncio.run(_run_vision(args))
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "pair-link":
        return _pair_link(args)
    print(f"unknown command {args.command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
