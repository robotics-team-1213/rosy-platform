"""Capture Rosy Cam overhead JPEGs and their World bundle metadata."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError

from ceiling_record import Site


def preview_lease(site, source, raw):
    request = {"source_id": source}
    if not raw:
        request["rectification"] = {"mode": "map"}
    return json.loads(site.request("/api/fleet/vision/lease", request)[0])


def read_frame(site, lease, source, raw):
    jpeg, headers = site.request(lease["frame_path"], bearer=lease["lease"])
    if (headers.get_content_type() != "image/jpeg"
            or headers["X-Frame-Rectified"] != ("false" if raw else "map")
            or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9")):
        raise ValueError("Vision did not return a JPEG with the requested projection")
    stamp = float(headers["X-Frame-Captured-At"])
    if abs(time.time() - stamp) > 10:
        raise ValueError("Vision returned an old frame")
    meta = {
        "schema": "rosy.world.field-photo.v1", "source_id": source, "rectified": "none" if raw else "map",
        "captured_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
        "sha256": sha256(jpeg).hexdigest(), "sequence": int(headers["X-Frame-Seq"]),
        "size": [int(headers["X-Frame-Width"]), int(headers["X-Frame-Height"])],
    }
    if not raw:
        meta.update(
            plane=[float(value) for value in headers["X-Frame-Plane"].split(",")],
            calibration_revision=headers["X-Frame-Calibration"],
            observed_fraction=float(headers["X-Frame-Observed-Fraction"]),
        )
    return jpeg, meta


def capture(site, source, raw):
    lease = preview_lease(site, source, raw)
    for attempt in range(1, 9):
        try:
            return read_frame(site, lease, source, raw)
        except HTTPError as error:
            if error.code not in (404, 409, 429, 503) or attempt == 8:
                raise
            time.sleep(.75)


def watch(site, source, output, raw):
    """Update a local display file and preserve camera time across failed polls."""
    next_lease = 0
    previous = None
    last_error = None
    while True:
        problem = None
        try:
            if time.monotonic() >= next_lease:
                lease = preview_lease(site, source, raw)
                next_lease = time.monotonic() + max(1, float(lease["expires_in_s"]) - 10)
            jpeg, meta = read_frame(site, lease, source, raw)
            stamp = datetime.fromisoformat(meta["captured_at"]).timestamp()
            if stamp != previous and abs(time.time() - stamp) < 5:
                with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
                    staged = Path(stream.name)
                    try:
                        stream.write(jpeg)
                        stream.close()
                        os.utime(staged, (stamp, stamp))
                        staged.replace(output)
                        previous = stamp
                    finally:
                        stream.close()
                        staged.unlink(missing_ok=True)
        except HTTPError as error:
            if error.code in (401, 403):
                next_lease = 0
            problem = f"HTTP {error.code}"
        except (OSError, ValueError) as error:
            problem = str(error)
        if problem and problem != last_error:
            print(f"Rosy Cam preview delayed: {problem}", flush=True)
        elif not problem and last_error:
            print("Rosy Cam preview recovered", flush=True)
        last_error = problem
        time.sleep(2 if problem else .65)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default=os.environ.get("ROSY_SITE_URL"))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", type=Path, help="new capture directory")
    target.add_argument("--live-jpeg", type=Path, help="local World data/field-live.jpg")
    parser.add_argument("--raw", action="store_true", help="preserve the original camera JPEG")
    args = parser.parse_args()
    if not args.site or not args.site.startswith("https://"):
        parser.error("provide the HTTPS Fleet address")
    try:
        site = Site(args.site, token=os.environ.get("ROSY_SITE_TOKEN"), timeout=5)
        if args.live_jpeg is not None:
            watch(site, "ceiling_north", args.live_jpeg, args.raw)
            return
        jpeg, meta = capture(site, "ceiling_north", args.raw)
        args.out.mkdir(parents=True, exist_ok=False)
        name = "ceiling-original" if args.raw else "ceiling-plane"
        (args.out / f"{name}.jpg").write_bytes(jpeg)
        sidecar = args.out / f"{name}.json"
        sidecar.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, AttributeError, KeyError, TypeError) as error:
        parser.exit(1, f"Rosy Cam capture failed: {error}\n")
    print(sidecar)


if __name__ == "__main__":
    main()
