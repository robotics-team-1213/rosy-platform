"""Reuse repeated contact measurements only at the measured arm point and setup."""
import json
import math
import re
from pathlib import Path

import omx_tcp


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def contact_binding(config, site, calibration, tcp):
    entry = (config.get("sites") or {}).get(site)
    if not isinstance(entry, dict) or not isinstance(calibration, dict):
        return None
    xy = entry.get("place")
    digests = [calibration.get(k) for k in ("reference_top_sha256", "reference_map_sha", "reference_geometry_sha")]
    if (not config.get("arm_id") or not isinstance(xy, (list, tuple)) or len(xy) != 2
            or not all(_finite(v) for v in (*xy, tcp, entry.get("yaw_deg")))
            or not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{%d}" % size, v)
                       for v, size in zip(digests, (64, 12, 12)))):
        return None
    return {"arm": config["arm_id"], "site": site, "place": list(xy), "yaw_deg": entry["yaw_deg"],
            "tcp_x_m": tcp, "reference_top_sha256": digests[0], "reference_map_sha": digests[1],
            "reference_geometry_sha": digests[2]}


def probe_binding(config, site, tcp):
    path = config.get("calibration_path")
    if not path:
        return None
    try:
        calibration = json.loads(Path(path).expanduser().read_bytes())
    except (OSError, ValueError):
        return None
    return contact_binding(config, site, calibration, tcp)


def contact_evidence(config, site, calibration):
    work = config.get("work_dir")
    if not work or not re.fullmatch(r"[A-Za-z0-9_-]+", site):
        return {"status": "missing", "reason": "no site receipt"}
    path = Path(work).expanduser() / f"surface-{site}.json"
    try:
        receipt = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {"status": "missing", "reason": "no site receipt"}
    except (OSError, ValueError):
        return {"status": "candidate", "reason": "unreadable site receipt"}
    candidate = {"status": "candidate", "source": path.name}
    if not isinstance(receipt, dict) or receipt.get("result") != "touched":
        return {**candidate, "reason": "no completed touch"}
    try:
        expected = contact_binding(config, site, calibration, omx_tcp.config_tcp(config))
    except (ValueError, TypeError, OverflowError):
        expected = None
    if (not expected or receipt.get("contact_binding") != expected
            or receipt.get("site") != site or receipt.get("xy") != expected["place"]):
        return {**candidate, "reason": "unbound or changed arm, target, TCP or map reference"}
    samples, z = receipt.get("touches_m"), receipt.get("surface_z")
    if (not isinstance(samples, list) or len(samples) < 2 or not all(_finite(v) for v in samples)
            or not _finite(z) or abs(sum(samples) / len(samples) - z) > 0.00011
            or max(samples) - min(samples) > 0.001500001 or z != config["sites"][site].get("surface_z")):
        return {**candidate, "reason": "missing, inconsistent or unapplied repeated contact"}
    return {"status": "matched_contact", "reason": "repeated descent contact at configured arm point",
            "source": path.name, "measured_z_m": z}
