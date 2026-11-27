"""Top-view evidence for a cell stop's precision verdict (2026-11-27, user: "dock to the model S top view").

Where the robot's own map pose and the ceiling camera cannot say whether the robot stands where model S was trained,
the arm cell's top camera can. CellTopview reads two fresh, agreeing frames of the cell job API and
topview_decision classifies the offset exactly like named_stop_decision (same limits, same IN_TOLERANCE / HOLD /
REPARK verdicts) with source "cell_topview"; unlike the straight-only SLAM verdict it also corrects sideways
(CORE re-park turns, drives and restores heading, left_m at most REPARK_MAX_LEFT_M). A camera that is not
reachable, stale, unregistered or not agreeing is no evidence: the caller keeps the unchanged SLAM verdict."""

import asyncio
import json
import math
import os
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

from core_common.stop_pose import repark_within_limits, stop_error
from fleet.localization.topview_pose import TopviewError, load_data, observe

CONFIG_ENV = "ROSY_FLEET_CELL_TOPVIEW"
JOBS_ENV = "ROSY_FLEET_CELL_JOBS"
SOURCE = "cell_topview"
KEY = "named_stop_topview"
RECORD_MAX_AGE_S = 10.0  # a verdict older than this is read again, never acted on
STILL_M, STILL_RAD = 0.01, 0.03  # the robot's own pose may move this much between the camera read and the action
AGREE_M, AGREE_RAD = 0.01, 0.05  # two frames of a parked robot agree this well, else it was moving
MIN_MOVE_M = 0.005
HEADING_SANITY_RAD = 0.5  # camera heading vs the robot's own heading; the SLAM yaw here is a few degrees off


def frame_age_s(headers) -> float:
    """Age of a frame on the cell host's own clock (Date is whole seconds, so it is rounded up: never too fresh)."""
    try:
        stamp = float(headers["X-Source-Stamp"])
        served = parsedate_to_datetime(headers["Date"]).timestamp() + 1.0
        seq = int(headers["X-Frame-Seq"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TopviewError("frame_unstamped") from exc
    if not math.isfinite(stamp) or seq < 0:
        raise TopviewError("frame_unstamped")
    return served - stamp


def _http_get(url: str, token: str, timeout: float = 1.5):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.read(), dict(reply.headers)
    except (OSError, urllib.error.URLError) as exc:
        raise TopviewError("camera_unreachable") from exc


class CellTopview:
    def __init__(self, data, fetch, *, sleep=asyncio.sleep):
        self.data, self._fetch, self._sleep = data, fetch, sleep

    @classmethod
    def from_env(cls, environ=os.environ):
        """None when no top-view data is configured; a bad configuration raises (the caller logs and runs without)."""
        path = environ.get(CONFIG_ENV)
        if not path:
            return None
        data = load_data(path)
        jobs = environ.get(JOBS_ENV)  # the same host file the cell job proxy reads: url and token_file per cell
        cell = (json.loads(Path(jobs).read_text(encoding="utf-8")).get("cells") or {}).get(data.cell) if jobs else None
        if not cell:
            raise ValueError(f"{CONFIG_ENV}: cell {data.cell!r} is not in {JOBS_ENV}")
        url = f"{str(cell['url']).rstrip('/')}/frame/{data.view}.jpg"

        async def fetch():
            token = Path(cell["token_file"]).read_text(encoding="utf-8").strip()
            return await asyncio.to_thread(_http_get, url, token)

        return cls(data, fetch)

    def covers(self, place_id) -> bool:
        return place_id == self.data.place

    async def _one(self, robot_id):
        jpeg, headers = await self._fetch()
        if not -1.0 <= frame_age_s(headers) <= self.data.max_frame_age_s:
            raise TopviewError("frame_stale")
        return int(headers["X-Frame-Seq"]), await asyncio.to_thread(observe, self.data, jpeg, robot_id)

    async def read(self, robot_id) -> dict:
        """Mean of two fresh frames with different sequence numbers that agree; TopviewError otherwise."""
        seen = {}
        for _ in range(4):
            seq, obs = await self._one(robot_id)
            seen[seq] = obs
            if len(seen) == 2:
                break
            await self._sleep(0.25)
        if len(seen) < 2:
            raise TopviewError("frame_not_advancing")
        a, b = seen.values()
        if math.hypot(a["dx"] - b["dx"], a["dy"] - b["dy"]) > AGREE_M or abs(a["dyaw"] - b["dyaw"]) > AGREE_RAD:
            raise TopviewError("frames_disagree")
        mean = {key: (a[key] + b[key]) / 2 for key in ("dx", "dy", "dyaw")}
        return {**mean, "sigma_m": max(a["sigma_m"], b["sigma_m"]), "sigma_rad": max(a["sigma_rad"], b["sigma_rad"]),
                "inliers": min(a["inliers"], b["inliers"]), "rms_px": max(a["rms_px"], b["rms_px"]),
                "marker_id": a["marker_id"] or b["marker_id"]}


def topview_decision(place, obs) -> dict:
    limits = place.precision_stop
    error = stop_error((place.x, place.y, place.yaw), (place.x + obs["dx"], place.y + obs["dy"], place.yaw + obs["dyaw"]))
    longitudinal, lateral, heading = error["longitudinal_m"], error["lateral_m"], error["heading_rad"]
    margin = max(limits.position_uncertainty_m, obs["sigma_m"])
    result = {"source": SOURCE, "error": error, "evidence_ref": limits.evidence_ref,
              "observation": {key: obs[key] for key in ("dx", "dy", "dyaw", "sigma_m", "inliers", "rms_px", "marker_id")}}
    if abs(heading) + max(limits.heading_uncertainty_rad, obs["sigma_rad"]) > limits.heading_rad:
        return {**result, "decision": "HOLD", "reason": "heading_outside_limits"}  # a re-park cannot turn the robot
    if abs(longitudinal) + margin <= limits.longitudinal_m and abs(lateral) + margin <= limits.lateral_m:
        return {**result, "decision": "IN_TOLERANCE"}
    c, s = math.cos(heading), math.sin(heading)  # the target offset in the robot's own forward / left axes
    forward, left = longitudinal * c + lateral * s, -longitudinal * s + lateral * c
    move = max(abs(forward), abs(left))
    if move > limits.max_correction_m or not repark_within_limits(forward, left):
        return {**result, "decision": "HOLD", "reason": "outside_repark_limits"}
    if move < MIN_MOVE_M:
        return {**result, "decision": "HOLD", "reason": "correction_below_resolution"}
    return {**result, "decision": "REPARK", "forward_m": round(forward, 4), "left_m": round(left, 4)}


def _still(pose, was) -> bool:
    return (isinstance(pose, dict) and all(type(pose.get(k)) in (int, float) for k in ("x", "y", "yaw"))
            and math.hypot(pose["x"] - was["x"], pose["y"] - was["y"]) <= STILL_M
            and abs(math.remainder(pose["yaw"] - was["yaw"], math.tau)) <= STILL_RAD)


def heading_agrees(place, obs, site_yaw) -> bool:
    """The tray axis is undirected: the robot's own heading must rule out a robot standing turned around."""
    return abs(math.remainder(site_yaw - (place.yaw + obs["dyaw"]), math.tau)) <= HEADING_SANITY_RAD


def current_verdict(record, snapshot, now, place_id=None):
    """The stored verdict of this stop while it is young and the robot has not moved since the camera read; else None."""
    if (not isinstance(record, dict) or record.get("place") != place_id or now is None or not 0 <= now - record["read_at"] <= RECORD_MAX_AGE_S
            or not _still((snapshot or {}).get("pose"), record["pose"])):
        return None
    return record["decision"]
