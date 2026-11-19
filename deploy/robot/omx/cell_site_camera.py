#!/usr/bin/env python3
"""A third view of a failed attempt: one frame from a site camera (Rosy Cam, ceiling_north) through Fleet's vision lease.

Cell S sees only from above and from the wrist (no side camera); what lies under what, a lean or a tilt is often not in
either view (2026-11-13: a box under the folded jaws took four tries to read). The frame is kept beside the failure row as
evidence for judging its type. Panel decision 2026-11-13: evidence only, never a motion target, calibration, clearance,
safety or hold decision; a missing frame is written as such and the recovery goes on.

  config "evidence_camera": {"fleet_url": "https://...", "token_file": "~/...token", "source_id": "ceiling_north",
                             "ca_file": "~/...pem"}
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.request
from pathlib import Path


def fleet_frame(conf: dict, out_dir: Path, timeout_s: float = 8.0, tries: int = 3, wait_s: float = 2.0) -> dict:
    """{source, path, at} of one saved frame, or {frame: None, why}. A lease from Fleet (camera viewer), then the frame."""
    try:
        ctx = ssl.create_default_context(cafile=str(Path(conf["ca_file"]).expanduser())) if conf.get("ca_file") else None
        token = Path(conf["token_file"]).expanduser().read_text().strip()
        base = conf["fleet_url"].rstrip("/")

        def call(path, bearer, body=None):
            req = urllib.request.Request(base + path, data=body, headers={
                "Authorization": f"Bearer {bearer}", **({"Content-Type": "application/json"} if body else {})})
            with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as r:
                return r.read()

        grant = json.loads(call("/api/fleet/vision/lease", token, json.dumps({"source_id": conf["source_id"]}).encode()))
        why = "no frame"
        for _ in range(tries):  # an idle source answers stale first and streams a few seconds later
            try:
                frame = call(grant["frame_path"], grant["lease"])
                if frame[:2] == b"\xff\xd8":
                    out_dir.mkdir(parents=True, exist_ok=True)
                    path = out_dir / f"{conf['source_id']}-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
                    path.write_bytes(frame)
                    return {"source": conf["source_id"], "path": str(path), "at": time.time()}
                why = "not a JPEG"
            except OSError as exc:
                why = str(exc)[:120]
            time.sleep(wait_s)
        return {"frame": None, "source": conf["source_id"], "why": why}
    except (OSError, ValueError, KeyError) as exc:
        return {"frame": None, "source": conf.get("source_id"), "why": f"{type(exc).__name__}: {str(exc)[:120]}"}
