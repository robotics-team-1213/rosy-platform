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

from rosy_vision import protocol
from rosy_vision.ingest import STATUS_INTERVAL_S, IngestServer
from rosy_vision.publish import SightingPublishError, SightingPublisher
from rosy_vision.vision_config import load_vision_sources
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

    server = IngestServer({args.source_name: token})
    ws_server = await server.start(args.host, args.port, ssl_context=_server_ssl_context(args.tls_cert, args.tls_key))
    advertise_host = args.advertise_host or _detect_advertise_host(args.host)
    pin = _receive_pin(args.tls_cert) if args.tls_cert else None
    uri = protocol.pairing_uri(advertise_host, args.port, token, args.source_name,
                               secure=bool(args.tls_cert), pin=pin)
    print(f"listening on {args.host}:{args.port}{protocol.WS_PATH}")
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


async def _run_vision(args: argparse.Namespace) -> int:
    configs = load_vision_sources(args.config)
    preview_secret = os.environ.get("ROSY_VISION_PREVIEW_SECRET")
    if preview_secret and any(
            preview_secret in {config.phone_token, config.sighting_token} for config in configs):
        raise ValueError("vision preview secret must differ from phone and sighting credentials")
    preview_signer = VisionLeaseSigner(preview_secret) if preview_secret else None
    ingest = IngestServer(
        {config.camera.source_id: config.phone_token for config in configs},
        preview_signer=preview_signer,
    )
    workers = []
    async with AsyncExitStack() as stack:
        for config in configs:
            publisher = await stack.enter_async_context(
                SightingPublisher(config.fleet_base_url, config.sighting_token)
            )
            workers.append(VisionWorker(
                source_id=config.camera.source_id,
                ingest=ingest,
                camera=config.camera,
                publisher=publisher,
            ))
        ws_server = await ingest.start(args.host, args.port,
                                       ssl_context=_server_ssl_context(args.tls_cert, args.tls_key))
        print(f"vision pipeline listening on {args.host}:{args.port}{protocol.WS_PATH} "
              f"for {len(workers)} configured sources", flush=True)
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
            ws_server.close()
            await ws_server.wait_closed()
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
    receive.add_argument("--advertise-host", default=None)
    receive.add_argument("--save-latest", type=Path, default=None, metavar="DIR")
    receive.add_argument("--tls-cert", type=Path, default=None)
    receive.add_argument("--tls-key", type=Path, default=None)

    vision = sub.add_parser("vision", help="receive camera frames and publish display-only sightings")
    vision.add_argument("--config", required=True, type=Path, help="site-cameras.yaml")
    vision.add_argument("--host", default="0.0.0.0")
    vision.add_argument("--port", type=int, default=8095)
    vision.add_argument("--tls-cert", type=Path, default=None)
    vision.add_argument("--tls-key", type=Path, default=None)

    link = sub.add_parser(
        "pair-link",
        help="print a pinned wss pairing link (and QR) for a site TLS proxy; the token comes from --token-env",
    )
    link.add_argument("--host", required=True, help="address the phone dials: site FQDN or IP in the cert SAN")
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
