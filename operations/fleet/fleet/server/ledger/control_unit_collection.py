"""Bounded observation aggregation across configured direct children only."""

import asyncio
import logging
import socket
import ssl
import time

import httpx

from core_common.protocol.integrated_control import (
    ControlMapSnapshot, ControlOverview, ControlUnitDetail, ControlUnitSummary,
)
from fleet.server.control_unit_config import canonical_unit_id

log = logging.getLogger(__name__)
MANIFEST_MISMATCH = "CONTROL_UNIT_MANIFEST_MISMATCH"


def classify_peer_failure(exc):
    """Short operator-facing reason for a failed peer refresh (walks the cause chain for dns/tls)."""
    chain, seen = exc, set()
    while chain is not None and id(chain) not in seen:
        seen.add(id(chain))
        if isinstance(chain, socket.gaierror):
            return "dns"
        if isinstance(chain, ssl.SSLError):
            return "tls"
        chain = chain.__cause__ or chain.__context__
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return f"auth {code}" if code in (401, 403) else f"http {code}"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, (httpx.TransportError, ConnectionError)):
        return "connect"
    if isinstance(exc, ValueError) and str(exc) == MANIFEST_MISMATCH:
        return "manifest mismatch"
    if isinstance(exc, ValueError):
        return "scope mismatch" if str(exc).endswith("SCOPE_MISMATCH") else "invalid response"
    return type(exc).__name__


class ControlUnitCollection:
    def __init__(self, config, local, peer, *, clock=time.monotonic, stale_after=5.0):
        self.config, self.local, self.peer = config, local, peer
        self.clock, self.stale_after = clock, stale_after
        self.unit = config.topology.unit(config.unit_id)
        self.children = tuple(sorted(u.unit_id for u in config.topology.units.values()
                                     if u.parent == config.unit_id))
        self.scope = self._subtree(config.unit_id)
        self.rows = {}
        self.link_failure = {}  # child -> last logged failure reason; absent while the link is healthy
        self.lock = asyncio.Lock()

    def _subtree(self, root):
        result = {root}
        for unit in self.config.topology.units.values():
            if unit.unit_id == root:
                continue
            try:
                self.config.topology.next_hop(root, unit.unit_id)
            except ValueError:
                continue
            result.add(unit.unit_id)
        return result

    def _missing(self, unit_id, error):
        return ControlUnitSummary(
            unit_id=unit_id, parent=self.config.topology.unit(unit_id).parent,
            availability="UNAVAILABLE", sampled_at=None, age_s=None,
            robots_total=len(self._robots(unit_id)), robots_online=0, tasks_active=0,
            map=None, dispatch=None, error=error,
        )

    def _robots(self, unit_id):
        return {r[6:] for r in self.config.topology.unit(unit_id).resources
                if r.startswith("robot:")}

    def _aged(self, row, received):
        age = None if row.age_s is None else row.age_s + max(0.0, self.clock() - received)
        state = row.availability
        if state == "AVAILABLE" and (age is None or age > self.stale_after):
            state = "STALE"
        return ControlUnitSummary(**(row.model_dump() | {
            "age_s": age, "availability": state,
            "dispatch": row.dispatch if state == "AVAILABLE" else None,
        }))

    def overview(self):
        rows = []
        for unit_id in sorted(self.scope):
            stored = self.rows.get(unit_id)
            rows.append(self._aged(*stored) if stored else
                        self._missing(unit_id, "CONTROL_UNIT_NOT_OBSERVED"))
        return ControlOverview(unit_id=self.unit.unit_id,
                               config_revision=self.config.topology.revision,
                               manifest_digest=self.config.topology.digest or None, units=rows)

    def _failed(self, scope, code):
        now = self.clock()
        for unit_id in scope:
            old = self.rows.get(unit_id)
            row = self._aged(*old) if old else self._missing(unit_id, code)
            row = ControlUnitSummary(**(row.model_dump() | {
                "availability": "STALE" if row.sampled_at is not None else "UNAVAILABLE",
                "dispatch": None, "error": code,
            }))
            self.rows[unit_id] = row, now

    async def refresh_local(self):
        try:
            async with asyncio.timeout(3.0):
                summary, _ = await self.local.read()
            self.rows[self.unit.unit_id] = summary, self.clock()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failed({self.unit.unit_id}, "CONTROL_UNIT_LOCAL_INFORMATION_UNAVAILABLE")

    async def _refresh_child(self, child):
        scope = self._subtree(child)
        started = self.clock()
        try:
            async with asyncio.timeout(3.0):
                value = await self.peer(child, "GET", "overview")
            overview = ControlOverview.model_validate(value)
            if (overview.unit_id != child
                    or overview.config_revision != self.config.topology.revision
                    or {r.unit_id for r in overview.units} != scope
                    or any(r.parent != self.config.topology.unit(r.unit_id).parent
                           or r.robots_total != len(self._robots(r.unit_id))
                           for r in overview.units)):
                raise ValueError("CONTROL_UNIT_INFORMATION_SCOPE_MISMATCH")
            # Same revision string with a different manifest must not pass (an older peer sends no digest).
            if overview.manifest_digest is not None and overview.manifest_digest != self.config.topology.digest:
                raise ValueError(MANIFEST_MISMATCH)
            if self.link_failure.pop(child, None) is not None:
                log.info("control unit peer %s recovered", child)
            now = self.clock()
            for row in overview.units:
                row = ControlUnitSummary(**(row.model_dump() | {
                    "age_s": None if row.age_s is None else row.age_s + max(0.0, now - started),
                }))
                self.rows[row.unit_id] = row, now
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = classify_peer_failure(exc)
            if self.link_failure.get(child) != reason:  # once per transition, not per poll
                self.link_failure[child] = reason
                log.warning("control unit peer %s unavailable: %s (%s)", child, reason, type(exc).__name__)
            self._failed(scope, MANIFEST_MISMATCH if reason == "manifest mismatch"
                         else "CONTROL_UNIT_PEER_INFORMATION_UNAVAILABLE")

    async def refresh(self):
        async with self.lock:
            await asyncio.gather(self.refresh_local(),
                                 *(self._refresh_child(child) for child in self.children))

    async def detail(self, unit_id):
        unit_id = canonical_unit_id(unit_id)  # D-1011 alias
        if unit_id not in self.scope:
            raise ValueError("CONTROL_UNIT_OUTSIDE_SCOPE")
        if unit_id == self.unit.unit_id:
            summary, detail = await self.local.read()
            self.rows[unit_id] = summary, self.clock()
        else:
            child = self.config.topology.next_hop(self.unit.unit_id, unit_id)
            started = self.clock()
            async with asyncio.timeout(3.0):
                value = await self.peer(child, "GET", "units/" + unit_id)
            detail = ControlUnitDetail.model_validate(value)
            elapsed = max(0.0, self.clock() - started)
            detail = ControlUnitDetail(**(detail.model_dump() | {
                "age_s": None if detail.age_s is None else detail.age_s + elapsed,
                "robots": [row.model_dump() | {
                    "state_age_s": None if row.state_age_s is None else row.state_age_s + elapsed,
                } for row in detail.robots],
            }))
        robots = self._robots(unit_id)
        if (detail.unit_id != unit_id or detail.config_revision != self.config.topology.revision
                or {r.robot_id for r in detail.robots} != robots
                or any(t.robot_id not in robots for t in detail.tasks)):
            raise ValueError("CONTROL_UNIT_INFORMATION_SCOPE_MISMATCH")
        if detail.availability == "AVAILABLE" and (
                detail.age_s is None or detail.age_s > self.stale_after):
            detail = ControlUnitDetail(**(detail.model_dump() | {"availability": "STALE", "dispatch": None}))
        elif detail.availability != "AVAILABLE" and detail.dispatch is not None:
            detail = ControlUnitDetail(**(detail.model_dump() | {"dispatch": None}))
        return detail

    async def map(self, unit_id):
        unit_id = canonical_unit_id(unit_id)  # D-1011 alias
        if unit_id not in self.scope:
            raise ValueError("CONTROL_UNIT_OUTSIDE_SCOPE")
        if unit_id == self.unit.unit_id:
            return self.local.map()
        child = self.config.topology.next_hop(self.unit.unit_id, unit_id)
        try:
            async with asyncio.timeout(3.0):
                value = await self.peer(child, "GET", "units/" + unit_id + "/map")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        result = ControlMapSnapshot.model_validate(value)
        if result.unit_id != unit_id or result.config_revision != self.config.topology.revision:
            raise ValueError("CONTROL_UNIT_INFORMATION_SCOPE_MISMATCH")
        return result


async def control_information_loop(collection):
    while True:
        await collection.refresh()
        await asyncio.sleep(1.0)
