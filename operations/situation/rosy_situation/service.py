"""D-577 3·4·10: `rosy-situation`, the AI PC situation service — reads Fleet, posts facts, never acts.

Every second it reads ``GET /api/fleet/state``, ``/api/fleet/traffic`` and ``/api/fleet/line-stuck`` and the
event cursor ``GET /api/fleet/events?after_id=`` (a new stuck event brings the next read forward), runs the
deterministic analyzers on that snapshot and posts their facts to ``POST /api/fleet/ai/facts`` as the
``ai_observer`` role: at most 32 per request, 2 requests a second, a 256-fact queue that drops the oldest.
Every 2 s it posts ``POST /api/fleet/ai/heartbeat`` with ``owner_mode`` read from a file only the AI PC owner
writes: ``available`` / ``shared`` read and analyze, ``owner_busy`` (also when the file is missing) sends the
heartbeat only. Facts are shadow: Fleet decides with its rules, CORE re-checks (D-516). The service holds no
robot address or token and no Fleet credential beyond ``ai_observer``.

Its input (state JSON, never frames) and output facts are JSONL under ``ROSY_SITUATION_STATE`` (default
``~/.local/state/rosy-situation``), one file per day and kind, kept 7 days; the event cursor survives a restart.
Analyzers: ``analyzers.Analyzer`` (phase (d), the field stuck causes); vision is phase (e).

Run (stdlib only; systemd unit ``deploy/ai_pc/rosy-situation.service``, installed only with owner consent)::

    FLEET_URL=https://fleet.site:8443 FLEET_TOKEN_FILE=~/.config/rosy/situation.token \\
    FLEET_CA=~/.config/rosy/fleet-ca.pem python3 -m rosy_situation.service
"""

from __future__ import annotations

import json
import base64
import logging
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

__version__ = "0.2.0"
PERIOD_S, HEARTBEAT_S = 1.0, 2.0
TIMEOUT_S = 4.0       # /api/fleet/state takes ~2 s on the site (power read waits 0.5 s per robot)
MAX_BATCH, MAX_POSTS_PER_S, QUEUE = 32, 2, 256
KEEP_DAYS = 7
OWNER_MODES = ("available", "shared", "owner_busy")
_LOG = logging.getLogger("rosy_situation")


def analyze(snapshot: dict) -> list[dict]:
    """No analyzers (tests of the transport alone). The service runs ``analyzers.Analyzer``."""
    return []


class Fleet:
    """Bearer HTTP to Fleet with a 4 s timeout per call; errors surface as OSError / HTTPError / ValueError."""

    def __init__(self, url: str, token: str, ca: Optional[str] = None) -> None:
        self._url, self._token = url.rstrip("/"), token
        self._ssl = ssl.create_default_context(cafile=ca) if url.startswith("https") else None

    def call(self, path: str, body: Optional[dict] = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self._url + path, data=data, method="GET" if body is None else "POST",
                                         headers={"Authorization": f"Bearer {self._token}",
                                                  "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_S, context=self._ssl) as response:
            return json.loads(response.read())

    def frame(self, path: str, lease: str) -> dict:
        if not isinstance(path, str) or not re.fullmatch(r"/api/vision/sources/[A-Za-z0-9_-]+/frame", path):
            raise ValueError("invalid Vision frame path")
        if not isinstance(lease, str) or not lease:
            raise ValueError("missing Vision frame lease")
        request = urllib.request.Request(self._url + path, headers={"Authorization": f"Bearer {lease}"})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=self._ssl))
        with opener.open(request, timeout=TIMEOUT_S) as response:
            if response.headers.get_content_type() != "image/jpeg":
                raise ValueError("Vision response is not JPEG")
            if response.headers.get("X-Frame-Rectified") != "map-crop":
                raise ValueError("Vision frame is not a map crop")
            seq = response.headers.get("X-Frame-Seq")
            captured_at = float(response.headers.get("X-Frame-Captured-At") or "nan")
            if not seq or not seq.isdigit() or not math.isfinite(captured_at):
                raise ValueError("Vision frame headers invalid")
            jpeg = response.read(2_000_001)
            if not jpeg or len(jpeg) > 2_000_000:
                raise ValueError("Vision frame size invalid")
            return {"frame_id": f"{path.split('/')[4]}:{seq}",
                    "captured_at": captured_at,
                    "jpeg_b64": base64.b64encode(jpeg).decode("ascii")}


class Situation:
    def __init__(self, fleet, state_dir: Path, owner_mode_file: Path, *,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 analyzers: Callable[[dict], list] = analyze, vlm=None, executor=None) -> None:
        self.fleet, self.state_dir, self.owner_mode_file = fleet, Path(state_dir), Path(owner_mode_file)
        self.clock, self.wall, self.analyzers = clock, wall, analyzers
        self.queue: deque = deque(maxlen=QUEUE)        # oldest dropped first (D-577 4)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._cursor_file = self.state_dir / "cursor.json"
        try:
            self.cursor = int(json.loads(self._cursor_file.read_text())["after_id"])
        except (OSError, ValueError, KeyError, TypeError):
            self.cursor = 0
        self._last_beat: Optional[float] = None
        self._posts: deque = deque()
        self.input_lag_s: Optional[float] = None
        from rosy_situation.incident_context import ContextDraft
        self.context_draft = ContextDraft()
        self.vlm = vlm
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="rosy-vlm")
        self._profile = None
        self._profile_task = None
        self._case_task = None
        self._case_seen: dict[str, float] = {}
        self._profile_retry_at = 0.0

    def owner_mode(self) -> str:
        try:
            mode = self.owner_mode_file.read_text(encoding="utf-8").strip()
        except OSError:
            return "owner_busy"                       # no owner word: heartbeat only
        return mode if mode in OWNER_MODES else "owner_busy"

    def _log(self, kind: str, record: dict) -> None:
        day = datetime.fromtimestamp(self.wall(), timezone.utc)
        logs = self.state_dir / "logs"
        logs.mkdir(exist_ok=True)
        with open(logs / f"{day:%Y-%m-%d}-{kind}.jsonl", "a", encoding="utf-8") as out:
            out.write(json.dumps(record, separators=(",", ":")) + "\n")
        oldest = f"{day - timedelta(days=KEEP_DAYS):%Y-%m-%d}"
        for path in logs.glob("*.jsonl"):
            if path.name[:10] < oldest:
                path.unlink(missing_ok=True)

    def _heartbeat(self, mode: str) -> None:
        now = self.clock()
        if self._last_beat is not None and now - self._last_beat < HEARTBEAT_S:
            return
        self._last_beat = now
        try:
            self.fleet.call("/api/fleet/ai/heartbeat", {
                "service_version": __version__, "model_profiles": [self._profile] if mode == "available" and self._profile else [],
                "owner_mode": mode,
                "gpu_used_mib": None, "mem_used_mib": None, "input_lag_s": self.input_lag_s})
        except (OSError, ValueError) as exc:
            _LOG.warning("heartbeat failed: %s", exc)

    def _read(self) -> tuple[dict, bool]:
        started = self.clock()
        snapshot = {"observed_at": self.wall()}
        for key, path in (("state", "/api/fleet/state"), ("traffic", "/api/fleet/traffic"),
                          ("line_stuck", "/api/fleet/line-stuck")):
            snapshot[key] = self.fleet.call(path)
        if any((str(row.get("robot_id") or ""), str(row.get("stuck_id") or "")) not in self.context_draft.seen
               for row in (snapshot["line_stuck"].get("pending") or [])):
            context = {"map": None, "cameras": {}}
            try:
                active = self.fleet.call("/api/fleet/site-map/active")
                site_map = active.get("map") or {}
                context["map"] = {"map_id": site_map.get("map_id"),
                                  "version": active.get("version"), "places": site_map.get("places") or []}
            except (OSError, ValueError) as exc:
                _LOG.warning("incident map context unavailable: %s", exc)
            try:
                sightings = self.fleet.call("/api/fleet/sightings")
                for row in sightings.get("sightings") or []:
                    rid = row.get("robot_id")
                    if rid and (rid not in context["cameras"] or
                                row.get("captured_at", 0) > context["cameras"][rid].get("captured_at", 0)):
                        context["cameras"][rid] = {key: row.get(key) for key in
                                                    ("source_id", "seq", "captured_at", "age_ms", "stale")}
            except (OSError, ValueError) as exc:
                _LOG.warning("incident camera context unavailable: %s", exc)
            snapshot["incident_context"] = context
        stuck_event = False
        try:
            events = self.fleet.call(f"/api/fleet/events?after_id={self.cursor}&limit=200")
        except urllib.error.HTTPError as exc:   # no event store on this Fleet: polling alone still works
            if exc.code != 404:
                raise
            events = {"events": [], "next_cursor": self.cursor}
        snapshot["events"] = events.get("events") or []
        stuck_event = any("line_stuck" in str(event.get("type", "")) for event in snapshot["events"])
        self.cursor = int(events.get("next_cursor", self.cursor))
        self._cursor_file.write_text(json.dumps({"after_id": self.cursor}))
        self.input_lag_s = round(self.clock() - started, 3)
        return snapshot, stuck_event

    def _flush(self) -> None:
        while self.queue:
            now = self.clock()
            while self._posts and now - self._posts[0] >= 1.0:
                self._posts.popleft()
            if len(self._posts) >= MAX_POSTS_PER_S:
                return                                   # next step sends the rest
            batch = [self.queue[i] for i in range(min(MAX_BATCH, len(self.queue)))]
            self._posts.append(now)
            try:
                self.fleet.call("/api/fleet/ai/facts", {"facts": batch})
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    return                               # keep them; Fleet's own limit
                _LOG.warning("facts refused %s: %s", exc.code, exc.read()[:200])
            except (OSError, ValueError) as exc:
                _LOG.warning("facts not sent: %s", exc)
                return
            for _ in batch:
                self.queue.popleft()

    def step(self) -> float:
        """One cycle; returns the seconds until the next (0 after a stuck event)."""
        started = self.clock()
        mode = self.owner_mode()
        self._ai(mode)
        self._heartbeat(mode)
        if mode == "owner_busy":
            return PERIOD_S
        try:
            snapshot, stuck_event = self._read()
        except (OSError, ValueError) as exc:             # Fleet unreachable: nothing to say; Fleet runs rules
            _LOG.warning("fleet read failed: %s", exc)
            return PERIOD_S
        self._log("input", snapshot)
        facts = self.analyzers(snapshot) + self.context_draft(snapshot)
        for fact in facts:
            self._log("facts", fact)
        self.queue.extend(facts)
        self._flush()
        for proposal in getattr(self.analyzers, "proposals", ()):   # D-577 개정: Fleet validates, CORE re-checks
            self._log("proposals", proposal)
            try:
                self.fleet.call("/api/fleet/ai/proposals", proposal)
            except urllib.error.HTTPError as exc:
                _LOG.warning("proposal refused %s: %s", exc.code, exc.read()[:200])
            except (OSError, ValueError) as exc:
                _LOG.warning("proposal not sent: %s", exc)
        return 0.0 if stuck_event else max(0.0, PERIOD_S - (self.clock() - started))

    def _ai(self, mode: str) -> None:
        """Poll one model job without delaying Fleet reads, heartbeat or the rule fallback."""
        if self.vlm is None or mode != "available":
            return
        if self._case_task is not None and self._case_task.done():
            try:
                self._case_task.result()
            except Exception as exc:  # noqa: BLE001 - a bad case or model response must not stop Fleet polling
                _LOG.warning("vlm case failed: %s", type(exc).__name__)
            self._case_task = None
        if self._profile_task is not None and self._profile_task.done():
            try:
                self._profile = self._profile_task.result()
            except (OSError, ValueError) as exc:
                _LOG.warning("vlm profile unavailable: %s", exc)
                self._profile = None
            self._profile_task = None
            self._profile_retry_at = self.clock() + 30.0
        if self._profile is None or self.clock() >= self._profile_retry_at:
            if self._profile_task is None and self._case_task is None and self.clock() >= self._profile_retry_at:
                self._profile_task = self._executor.submit(self.vlm.profile)
            return
        if self._case_task is None:
            self._case_task = self._executor.submit(self._ai_cycle)

    def _ai_cycle(self) -> None:
        problems = self.fleet.call("/api/fleet/ai/problems").get("problems") or []
        now = self.clock()
        for problem in problems:
            pid = str(problem.get("problem_id") or "")
            if pid and now - self._case_seen.get(pid, float("-inf")) >= 8.0:
                self._case_seen[pid] = now
                case = self.fleet.call(f"/api/fleet/ai/case/{pid}")
                view = (case.get("views") or {}).get("rosy_cam") or {}
                if view.get("frame_path") and self.owner_mode() == "available":
                    try:
                        case["views"]["rosy_cam"] = self.fleet.frame(view["frame_path"], view["lease"])
                    except (OSError, ValueError, KeyError) as exc:
                        _LOG.warning("Vision frame unavailable: %s", type(exc).__name__)
                        case["views"].pop("rosy_cam", None)
                proposal = self.vlm.judge(case, self.wall())
                if proposal is not None and self.owner_mode() == "available":
                    self.fleet.call("/api/fleet/ai/proposals", proposal)
                    self._log("proposals", proposal)
                break
        if len(self._case_seen) > 256:
            self._case_seen = {pid: at for pid, at in self._case_seen.items() if now - at < 60.0}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = Path(os.path.expanduser(os.environ["FLEET_TOKEN_FILE"])).read_text(encoding="utf-8").strip()
    ca = os.environ.get("FLEET_CA")
    state = Path(os.path.expanduser(os.environ.get("ROSY_SITUATION_STATE", "~/.local/state/rosy-situation")))
    owner = Path(os.path.expanduser(os.environ.get("ROSY_SITUATION_OWNER_MODE", "~/.config/rosy/situation-owner-mode")))
    from rosy_situation.analyzers import Analyzer
    from rosy_situation.vlm import Vlm

    service = Situation(Fleet(os.environ["FLEET_URL"], token, os.path.expanduser(ca) if ca else None), state, owner,
                        analyzers=Analyzer(), vlm=Vlm())
    while True:
        time.sleep(service.step())


if __name__ == "__main__":
    main()
