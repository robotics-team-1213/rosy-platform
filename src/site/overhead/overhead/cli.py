"""``rosy_overhead`` — CLI front end for the receive-only ingest server.

``rosy_overhead receive`` starts :class:`overhead.ingest.IngestServer`,
prints a ``rosyov://`` pairing URI (and an ASCII QR code when the optional
``qrcode`` package is installed), and prints per-source stats once a
second. See docs/adr/D-261-overhead-camera-app-skeleton.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
import time
from pathlib import Path
from typing import Sequence

from overhead import protocol
from overhead.ingest import STATUS_INTERVAL_S, IngestServer


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
    ws_server = await server.start(args.host, args.port)
    advertise_host = args.advertise_host or _detect_advertise_host(args.host)
    uri = protocol.pairing_uri(advertise_host, args.port, token, args.source_name)
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rosy_overhead")
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

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "receive":
        try:
            asyncio.run(_run_receive(args))
        except KeyboardInterrupt:
            pass
        return 0
    print(f"unknown command {args.command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
