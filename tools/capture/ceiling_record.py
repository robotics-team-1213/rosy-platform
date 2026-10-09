#!/usr/bin/env python3
"""D-563 3: record the site ceiling camera beside a robot collection drive.

    ceiling_record.py --site <https://site-host:port> --out DIR [--source ceiling_north]
                      [--duration S] [--interval 0.33] (--ca-file CA | --insecure)

Leases the Rosy Cam preview (POST /api/fleet/vision/lease) and fetches raw frames
(no rectification) as fast as --interval and the 0.2 s preview rate limit allow. Writes
DIR/frames/<seq>.jpg and DIR/frames.jsonl rows {seq, captured_at, saved_at, file, width,
height, rotation_deg, lens} (captured_at = X-Frame-Captured-At, site clock; saved_at = this
PC's clock), and once DIR/calibration.json: the approved tracking record for the source
from GET /api/fleet/calibrations (map_to_image, image size, track_bounds_m, lens,
calibration_revision; D-457/D-560) plus the first frame's X-Source-Lens. Stops on Ctrl-C
or after --duration. The site address and token come from args or env (ROSY_SITE_URL,
ROSY_SITE_TOKEN); the token is optional where the site allows the LAN tokenless lease.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class Site:
    def __init__(self, base, token=None, ctx=None, timeout=8.0):
        self.base, self.token, self.ctx, self.timeout = base.rstrip("/"), token, ctx, timeout

    def request(self, path, body=None, bearer=None):
        headers = {"Content-Type": "application/json"}
        if bearer or self.token:
            headers["Authorization"] = "Bearer " + (bearer or self.token)
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode(),
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, context=self.ctx, timeout=self.timeout) as resp:
            return resp.read(), resp.headers


def parse_lens(text):
    """X-Source-Lens 'kind=standard;focal_mm=5.4;hfov_deg=67.8' -> dict, or None."""
    if not text:
        return None
    lens = dict(part.split("=", 1) for part in text.split(";") if "=" in part)
    for key in ("focal_mm", "hfov_deg"):
        if key in lens:
            lens[key] = float(lens[key])
    return lens


def snapshot_calibration(site, source_id):
    raw, _ = site.request("/api/fleet/calibrations")
    records = [r for r in json.loads(raw).get("calibrations", []) if r.get("source_id") == source_id]
    return records[0] if records else None


def record(site, out, *, source_id="ceiling_north", duration=None, interval=0.33, clock=time.time,
           sleep=time.sleep, monotonic=time.monotonic):
    """Fetch frames until duration (s) or KeyboardInterrupt; returns the number saved."""
    out = Path(out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    calibration = {"source_id": source_id, "fetched_at": clock(),
                   "record": snapshot_calibration(site, source_id), "frame_lens": None}

    def write():
        (out / "calibration.json").write_text(json.dumps(calibration, indent=1) + "\n", encoding="utf-8")
    write()  # at start too: a recorder stopped by systemd still leaves the record
    lease, lease_until, last_seq, saved = None, 0.0, None, 0
    start = monotonic()
    with open(out / "frames.jsonl", "a", encoding="utf-8") as log:
        try:
            while duration is None or monotonic() - start < duration:
                tick = monotonic()
                try:
                    if lease is None or tick >= lease_until:
                        doc = json.loads(site.request("/api/fleet/vision/lease", {"source_id": source_id})[0])
                        lease = doc
                        lease_until = tick + float(doc.get("expires_in_s", 60)) - 5.0
                    jpeg, headers = site.request(lease["frame_path"], bearer=lease["lease"])
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        lease = None
                    elif exc.code not in (409, 429, 503):
                        raise
                    sleep(0.25)
                    continue
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    print(f"warning: {exc}", file=sys.stderr)
                    sleep(1.0)
                    continue
                seq = int(headers["X-Frame-Seq"])
                if seq != last_seq:
                    last_seq = seq
                    name = f"frames/{seq:08d}.jpg"
                    (out / name).write_bytes(jpeg)
                    lens = parse_lens(headers.get("X-Source-Lens"))
                    if calibration["frame_lens"] is None and lens is not None:
                        calibration["frame_lens"] = lens
                        write()
                    log.write(json.dumps({
                        "seq": seq, "captured_at": float(headers["X-Frame-Captured-At"]),
                        "saved_at": clock(), "file": name,
                        "width": int(headers.get("X-Frame-Width", 0)),
                        "height": int(headers.get("X-Frame-Height", 0)),
                        "rotation_deg": int(headers.get("X-Frame-Rotation-Deg", 0)),
                        "rectified": headers.get("X-Frame-Rectified"), "lens": lens}) + "\n")
                    log.flush()
                    saved += 1
                sleep(max(0.0, interval - (monotonic() - tick)))
        except KeyboardInterrupt:
            pass
    write()
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", default=os.environ.get("ROSY_SITE_URL"))
    parser.add_argument("--token", default=os.environ.get("ROSY_SITE_TOKEN"))
    parser.add_argument("--source", default="ceiling_north")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--interval", type=float, default=0.33)
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--ca-file")
    tls.add_argument("--insecure", action="store_true", help="do not verify the site's TLS certificate")
    args = parser.parse_args(argv)
    if not args.site:
        parser.error("--site or ROSY_SITE_URL required")
    ctx = None
    if args.site.startswith("https"):
        ctx = ssl.create_default_context(cafile=args.ca_file)
        if args.insecure:
            print("WARNING: --insecure: the site's TLS certificate is not verified", file=sys.stderr)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    def stop(*_):
        raise KeyboardInterrupt  # systemd stop (SIGTERM) ends like Ctrl-C
    signal.signal(signal.SIGTERM, stop)
    saved = record(Site(args.site, args.token, ctx), args.out, source_id=args.source,
                   duration=args.duration, interval=args.interval)
    print(json.dumps({"frames": saved, "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
