"""Binds the SLAM fallback supervisor to CORE's real objects (the thin adapter; the policy is core_features/slam_fallback.py)."""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Optional

from core_common.protocol.schemas import NavigationState
from core_features.localization.halt import autonomy_halt
from core_features.localization.slam_fallback import (
    STATE_NAME, STOP_EVIDENCE_NAME, HostReply, Ports, SlamFallback, state_dir)
from core_features.localization.slam_health import Sample

_log = logging.getLogger(__name__)
MACHINE_USER = "core-slam-fallback"       # identifier form: the Host Agent audit names this caller
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
EVIDENCE_FRESH_S = 10.0                  # Fleet-fed gap / map verdict older than this is ignored
VELOCITY_FRESH_S = 1.0                   # an unknown or old velocity is never "zero"


class MapOdomJump:
    """Change of the map->odom translation between two samples, from the two poses CORE already holds (no TF here)."""

    def __init__(self, state) -> None:
        self._state, self._last = state, None

    def __call__(self) -> Optional[float]:
        mx, my, myaw, frame, map_age = self._state.pose_sample()
        odom = self._state.odom_sample()
        if frame != "map" or map_age > 1.0 or odom is None or odom[3] > 1.0:
            self._last = None
            return None
        ox, oy, oyaw, _ = odom
        rot = myaw - oyaw
        tx = mx - (math.cos(rot) * ox - math.sin(rot) * oy)
        ty = my - (math.sin(rot) * ox + math.cos(rot) * oy)
        jump = None if self._last is None else math.hypot(tx - self._last[0], ty - self._last[1])
        self._last = (tx, ty)
        return jump


class Evidence:
    """Fleet-fed extras (slam_camera_gap_m, scan agreement, the periodic map verdict), kept only while fresh."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock, self._lock = clock, threading.Lock()
        self._values: dict = {}

    def note(self, gap_m=None, agreement=None, map_verdict=None) -> None:
        with self._lock:
            self._values = {"gap_m": gap_m, "agreement": agreement, "map_verdict": map_verdict, "at": self._clock()}

    def fresh(self) -> dict:
        with self._lock:
            ok = self._values and self._clock() - self._values["at"] <= EVIDENCE_FRESH_S
            return dict(self._values) if ok else {}


def build_slam_fallback(config: dict, *, state, nav, command, modes, line_follow, docking, swarm, assist, readiness,
                        events, host_client=None, folder: Optional[Path] = None) -> SlamFallback:
    runtime = config.get("runtime") or {}
    backend = str(runtime.get("navigation_backend", "localization")).strip().lower()
    folder = folder or state_dir()
    jump, evidence = MapOdomJump(state), Evidence()
    halt_autonomy = autonomy_halt(nav=nav, line_follow=line_follow, command=command, state=state, modes=modes,
                                  swarm=swarm, docking=docking)
    host_cfg = config.get("host_agent") or {}
    clients = [host_client]  # built on first use: a localization-backend robot never calls the host
    profile = (((config.get("navigation") or {}).get("readiness") or {}).get("profiles") or {}).get("localization")

    def goal_active() -> bool:
        return (nav.nav_state in (NavigationState.PLANNING, NavigationState.NAVIGATING) or bool(line_follow.active)
                or bool(docking.active) or bool(swarm.active))

    def speed():
        age = state.received_age("velocity")
        if age is None or age > VELOCITY_FRESH_S:
            return None
        velocity = state.snapshot().velocity
        return velocity.linear, velocity.angular

    def sample(now: float) -> Sample:
        moving = goal_active() or (speed() or (1.0, 1.0)) != (0.0, 0.0)
        extra = evidence.fresh()
        return Sample(t=now, jump_m=jump(), moving=moving, gap_m=extra.get("gap_m"), agreement=extra.get("agreement"),
                      map_verdict=extra.get("map_verdict"))

    def halt() -> None:
        halt_autonomy()
        command.clear_manual()  # teleop too: velocity must reach zero, whoever asked for it

    def write_file(name: str, data: dict) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / (name + ".tmp")
        temp.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(temp, 0o644)  # the host refuses a file others can write
        os.replace(temp, folder / name)

    def write_evidence(data: dict) -> None:  # monotonic times are only comparable inside one boot
        try:
            boot = BOOT_ID.read_text(encoding="ascii").strip()
        except OSError:
            boot = ""
        write_file(STOP_EVIDENCE_NAME, {**data, "boot_id": boot})

    def read_marker() -> Optional[dict]:
        try:
            return json.loads((folder / STATE_NAME).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):  # present but unreadable or corrupt: that still means "switch owed", so hold
            return {"reason": "marker_unreadable"}

    def write_marker(data: Optional[dict]) -> None:
        if data is None:
            (folder / STATE_NAME).unlink(missing_ok=True)
        else:
            write_file(STATE_NAME, data)

    def host(command_name: str, **params) -> HostReply:
        if clients[0] is None:
            from core_api_web.api.host_agent_client import HostAgentClient
            clients[0] = HostAgentClient(socket_path=host_cfg.get("socket_path", "/run/rosy/host-agent.sock"),
                                         timeout_s=float(host_cfg.get("timeout_s", 5.0)))
        reply = clients[0].request(command_name, role="machine", user_id=MACHINE_USER, params=params or None)
        return HostReply(reply.ok, reply.code, reply.data if isinstance(reply.data, dict) else None, reply.detail)

    def after_switch() -> None:
        if profile:
            readiness.set_required_components(profile)  # CORE still reads backend=slam until its next start

    def request_search() -> None:
        try:
            assist.suspect("slam_fallback")
        except RuntimeError:
            _log.warning("slam fallback: localization suspect transport unavailable")

    ports = Ports(sample=sample, speed=speed, goal_active=goal_active, halt=halt, write_evidence=write_evidence, request=host,
                  localization=assist.raw_status, reports=lambda: assist.reports, request_search=request_search,
                  after_switch=after_switch, events=events, read_marker=read_marker, write_marker=write_marker)
    supervisor = SlamFallback(ports, backend)
    supervisor.evidence = evidence
    assist.hold = supervisor.hold_reason
    state.slam_fallback_provider = supervisor.status
    return supervisor
