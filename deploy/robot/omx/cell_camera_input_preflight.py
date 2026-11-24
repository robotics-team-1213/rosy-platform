"""Check the OMX policy camera sources through the local viewer, without commanding an arm."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time

from cell_pipeline_io import FifoCell

_ARMS = ("arm_a", "arm_b")
_VIEWER = "http://127.0.0.1:8767"


def collect(arm, frame_receipt, *, sleep=time.sleep):
    """Require two advancing receipts from each role. This does not measure exposure sync."""
    if arm not in _ARMS:
        raise ValueError("unknown OMX policy arm")
    roles = ("top", "side", f"{arm}_wrist")

    def read(role, previous=None):
        try:
            frame = frame_receipt(role, previous=previous, max_age_s=0.6, timeout_s=2.0)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        evidence = {key: frame[key] for key in ("source_seq", "source_stamp", "camera")}
        if evidence["camera"] != role:
            return {"ok": False, "error": "wrong camera role"}
        if previous is not None and (
            evidence["source_seq"] <= previous["source_seq"]
            or evidence["source_stamp"] <= previous["source_stamp"]
        ):
            return {"ok": False, "error": "camera source did not advance"}
        return {"ok": True, **evidence}

    with ThreadPoolExecutor(max_workers=len(roles)) as pool:
        first = list(pool.map(read, roles))
        sleep(0.15)
        futures = [pool.submit(read, role, frame) if frame["ok"] else None
                   for role, frame in zip(roles, first, strict=True)]
        cameras = {role: (future.result() if future else frame)
                   for role, frame, future in zip(roles, first, futures, strict=True)}
    return {
        "arm": arm,
        "camera_source_ready": all(status["ok"] for status in cameras.values()),
        "cameras": cameras,
        "timestamp_semantics": "viewer_source_stamp_not_exposure_sync",
        "motion_permission": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=_ARMS)
    arm = parser.parse_args(argv).arm
    roles = ("top", "side", f"{arm}_wrist")
    cell = FifoCell(None, {role: f"{_VIEWER}/frame/{role}.jpg" for role in roles})
    result = collect(arm, cell.frame_receipt)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["camera_source_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
