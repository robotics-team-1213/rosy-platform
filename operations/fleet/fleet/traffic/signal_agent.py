"""D-525 rev 4: the AI PC signal controller — it reads the Fleet map situation and only asks for greens.

Every 0.5 s it reads ``GET /api/fleet/traffic`` (signals, each trip robot's ``signal_ahead``) and
``GET /api/fleet/guide`` (D-536 map pose and lane of every robot) and, for every approach of a signal
in ``demand`` mode where a robot waits, sends ``POST /api/fleet/traffic/signals/{id}/demand``
(ttl 2 s). A signal with nobody waiting gets a keep-alive (no approach) so Fleet knows the controller
is alive. It sends nothing else: no robot command, no signal verb. Fleet decides every green (the
zone must be free) and the robots still move only on their D-517 authority.

A robot waits at approach A when either
  (a) its traffic row ``signal_ahead`` names A, it is at most 0.6 m before the stop line, the lamp is
      not green and it does not hold the zone yet, or
  (b) its guide lane is arc A, the next place (the zone entry) is at most 0.6 m ahead, it is inside
      the lane, its pose is LOCALIZED or DEGRADED and it moved under 2 cm since the last poll.
Approaches are asked for in the order their first robot was seen waiting (FIFO).

Run on the AI PC (stdlib only)::

    FLEET_URL=https://fleet.site:8443 FLEET_TOKEN_FILE=~/.config/rosy/signal-agent.token \\
    FLEET_CA=~/.config/rosy/fleet-ca.pem python3 -m fleet.traffic.signal_agent
"""

from __future__ import annotations

import json
import logging
import math
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

NEAR_M = 0.6         # a robot this close to the stop line (zone entry) may be waiting
STILL_M = 0.02       # moved less than this between polls: standing
TTL_S = 2.0          # each demand lives this long on Fleet unless repeated
PERIOD_S = 0.5
_LOG = logging.getLogger("fleet.signal_agent")


def _approaches(traffic: dict) -> dict[str, str]:
    """``{approach: signal_id}`` of signals in demand mode without config errors."""
    return {a["approach"]: row["signal_id"] for row in traffic.get("signals") or []
            if row.get("mode") == "demand" and not row.get("errors") for a in row.get("approaches") or []}


def waiting(traffic: dict, guide: dict, last_xy: dict) -> dict[str, tuple[str, str, float]]:
    """``{robot_id: (signal_id, approach, distance_m)}`` of robots waiting at a demand-mode signal.
    ``last_xy`` is ``{robot_id: (x, y)}`` from the previous poll (rule b's stillness)."""
    approaches = _approaches(traffic)
    out: dict[str, tuple[str, str, float]] = {}
    for row in traffic.get("robots") or []:                       # (a) Fleet's own route view
        ahead = row.get("signal_ahead") or {}
        approach, d = ahead.get("approach"), ahead.get("distance_m")
        if approach in approaches and d is not None and d <= NEAR_M and ahead.get("lamp") != "green" \
                and not ahead.get("may_enter"):
            out[row["robot_id"]] = (approaches[approach], approach, d)
    for record in guide.get("robots") or []:                      # (b) the map situation (D-536)
        robot_id, pose, lane = record.get("robot_id"), record.get("pose"), record.get("lane")
        if robot_id in out or not record.get("online") or not pose or not lane:
            continue
        approach, place = lane.get("arc_id"), lane.get("next_place") or {}
        prev = last_xy.get(robot_id)
        if (approach in approaches and place.get("distance_m") is not None and place["distance_m"] <= NEAR_M
                and abs(lane.get("lateral_m", math.inf)) <= lane.get("width_m", 0.0) / 2
                and pose.get("state") in ("LOCALIZED", "DEGRADED")
                and prev is not None and math.hypot(pose["x"] - prev[0], pose["y"] - prev[1]) < STILL_M):
            out[robot_id] = (approaches[approach], approach, place["distance_m"])
    return out


def decide(traffic: dict, guide: dict, memory: dict, now: float) -> tuple[list[dict], dict]:
    """Pure: the demands to send this poll, oldest waiting approach first, and the next ``memory``
    (``since``: robot -> (signal, approach, first seen); ``xy``: robot -> (x, y)). A demand-mode signal
    with nobody waiting gets a keep-alive ``{signal_id, approach: None}``."""
    seen = waiting(traffic, guide, memory.get("xy", {}))
    old = memory.get("since", {})
    since = {r: (s, a, old[r][2] if r in old and old[r][:2] == (s, a) else now) for r, (s, a, _d) in seen.items()}
    first: dict[tuple[str, str], tuple[float, str, float]] = {}
    for robot_id, (signal_id, approach, d) in seen.items():
        key, t = (signal_id, approach), since[robot_id][2]
        if key not in first or (t, robot_id) < first[key][:2]:
            first[key] = (t, robot_id, d)
    sends = [{"signal_id": s, "approach": a, "reason": f"robot {r} waiting {d:.2f} m"}
             for (s, a), (_t, r, d) in sorted(first.items(), key=lambda kv: (kv[1][0], kv[0]))]
    asked = {s for s, _a in first}
    sends += [{"signal_id": s, "approach": None, "reason": ""}
              for s in sorted(set(_approaches(traffic).values()) - asked)]
    xy = {r["robot_id"]: (r["pose"]["x"], r["pose"]["y"]) for r in guide.get("robots") or [] if r.get("pose")}
    return sends, {"since": since, "xy": xy}


class Fleet:
    def __init__(self, url: str, token: str, ca: Optional[str]) -> None:
        self._url, self._token = url.rstrip("/"), token
        self._ssl = ssl.create_default_context(cafile=ca) if url.startswith("https") else None

    def _call(self, path: str, body: Optional[dict] = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self._url + path, data=data, method="GET" if body is None else "POST",
                                         headers={"Authorization": f"Bearer {self._token}",
                                                  "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=2.0, context=self._ssl) as response:
            return json.loads(response.read())

    def read(self) -> tuple[dict, dict]:
        return self._call("/api/fleet/traffic"), self._call("/api/fleet/guide")

    def demand(self, send: dict) -> None:
        body = {"ttl_s": TTL_S, **({"approach": send["approach"], "reason": send["reason"]} if send["approach"] else {})}
        self._call(f"/api/fleet/traffic/signals/{urllib.parse.quote(send['signal_id'], safe='')}/demand", body)


def run(fleet: Fleet, clock=time.monotonic, sleep=time.sleep, polls: Optional[int] = None) -> None:
    memory: dict = {}
    logged: Optional[list] = None
    while polls is None or polls > 0:
        start = clock()
        try:
            sends, memory = decide(*fleet.read(), memory, start)
        except (OSError, ValueError) as exc:          # Fleet unreachable: send nothing, Fleet falls back to cycle
            _LOG.warning("fleet read failed: %s", exc)
            sends = []
        asks = [(s["signal_id"], s["approach"], s["reason"]) for s in sends if s["approach"]]
        if asks != logged:
            _LOG.info("demands: %s", asks or "none (keep-alive)")
            logged = asks
        for send in sends:
            try:
                fleet.demand(send)
            except urllib.error.HTTPError as exc:      # e.g. 409 SIGNAL_NOT_DEMAND: an operator changed the mode
                _LOG.warning("demand %s refused: %s %s", send, exc.code, exc.read()[:200])
            except OSError as exc:
                _LOG.warning("demand %s failed: %s", send, exc)
        if polls is not None:
            polls -= 1
        sleep(max(0.0, PERIOD_S - (clock() - start)))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = Path(os.path.expanduser(os.environ["FLEET_TOKEN_FILE"])).read_text(encoding="utf-8").strip()
    ca = os.environ.get("FLEET_CA")
    run(Fleet(os.environ["FLEET_URL"], token, os.path.expanduser(ca) if ca else None))


if __name__ == "__main__":
    main()
