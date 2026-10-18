"""Two-arm workcell coordinator: barrier release and coupled stop only (D-778 §5, D-780 §6).

The coordinator is a client of the two arm owners, never a joint writer. It never creates,
forwards or replays a grant, and it keeps no durable state: every tick reads both owners again
(``GetBarrier``), which is also the liveness traffic the owners watch in a tight segment
(D-780 §4). The owner transport is injected (:class:`OwnerClient`), so this module has no ROS
import and is unit-tested with fake owners. ``UnixOwnerClient`` is the same-host UDS transport.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

_LOG = logging.getLogger(__name__)
_HEALTHY = frozenset({"SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED"})
_FAILED = frozenset({"FAILED", "CANCELED", "HOLD"})
_ARRIVED = frozenset({"waiting", "released"})
_ENDED = frozenset({"SUCCEEDED", "FAILED", "CANCELED"})
#: Release refusals meaning the partner Action itself ended (PARTNER_FAILED, not PARTNER_UNKNOWN).
_PARTNER_ENDED_CODES = frozenset({"BARRIER_EXPIRED", "ACTION_NOT_ACTIVE"})


class OwnerClient(Protocol):
    """One owner's UDS: send one request document, return its response document."""

    def request(self, document: Mapping[str, Any]) -> Mapping[str, Any]: ...


class OwnerUnavailable(ConnectionError):
    pass


class UnixOwnerClient:
    """One newline-framed request per connection to an owner's ``control.sock``."""

    MAX_RESPONSE_BYTES = 256 * 1024

    def __init__(self, socket_path: str, *, timeout_s: float = 0.25) -> None:
        self.socket_path = socket_path
        self.timeout_s = timeout_s

    def request(self, document: Mapping[str, Any]) -> Mapping[str, Any]:
        frame = json.dumps(dict(document), sort_keys=True, separators=(",", ":")).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_s)
                connection.connect(self.socket_path)
                connection.sendall(frame)
                received = bytearray()
                while b"\n" not in received and len(received) <= self.MAX_RESPONSE_BYTES:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    received.extend(chunk)
        except OSError as exc:
            raise OwnerUnavailable(str(exc)) from exc
        if b"\n" not in received:
            raise OwnerUnavailable("owner closed without one response frame")
        return json.loads(bytes(received).split(b"\n", 1)[0])


class WorkcellCoordinator:
    """Poll two owners, release barriers both arms reached, stop the partner of a failed arm."""

    def __init__(self, owners: Mapping[str, OwnerClient], *,
                 now: Callable[[], datetime] | None = None) -> None:
        if len(owners) != 2:
            raise ValueError("a two-arm workcell coordinator talks to exactly two owners")
        self.owners = dict(owners)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._known: dict[str, set[str]] = {instance: set() for instance in self.owners}
        self._stopped: set[tuple[str, str]] = set()
        self._ended: dict[str, dict[str, dict[str, Any]]] = {}

    def _call(self, instance_id: str, document: Mapping[str, Any]) -> Mapping[str, Any]:
        response = self.owners[instance_id].request(document)
        if not isinstance(response, Mapping):
            raise OwnerUnavailable("owner response is not an object")
        return response

    def _read(self, instance_id: str) -> dict[str, dict[str, Any]] | None:
        """Every paired Action this owner holds, or None when the owner is unreachable."""
        try:
            listed = self._call(instance_id, {"version": 2, "operation": "GetBarrier"})
            if listed.get("status") != 200:
                return None
            views = {item["action_id"]: dict(item) for item in listed.get("actions", ())}
            for action_id in self._known[instance_id] - set(views):
                # A known Action left the unresolved list: read its final state by id.
                single = self._call(instance_id, {"version": 2, "operation": "GetBarrier",
                                                  "action_id": action_id})
                if single.get("status") == 200:
                    views[action_id] = dict(single["action"])
                else:
                    views[action_id] = {"action_id": action_id, "action_state": "UNKNOWN"}
        except (OwnerUnavailable, OSError, ValueError, KeyError, TypeError):
            _LOG.warning("owner %s is unreachable from the coordinator", instance_id)
            return None
        return views

    def tick(self) -> list[dict[str, Any]]:
        """One poll of both owners; returns the decisions taken (for logs and tests)."""
        views = {instance: self._read(instance) for instance in self.owners}
        pairs: dict[str, dict[str, dict[str, Any]]] = {}
        for instance, actions in views.items():
            if actions is None:
                continue
            self._known[instance] = {action_id for action_id, view in actions.items()
                                     if view.get("action_state") in _HEALTHY | {"UNKNOWN", "HOLD"}}
            for view in actions.values():
                if view.get("pair_id"):
                    pairs.setdefault(view["pair_id"], {})[instance] = view
        # A partner that ended (SUCCEEDED, FAILED, ...) leaves its owner's unresolved list; keep
        # its last state for the pair instead of reading its absence as PARTNER_UNKNOWN.
        for pair_id, arms in pairs.items():
            remembered = self._ended.setdefault(pair_id, {})
            for instance, view in arms.items():
                if view.get("action_state") in _ENDED:
                    remembered[instance] = view
            for instance, view in remembered.items():
                arms.setdefault(instance, view)
        self._ended = {pair_id: self._ended[pair_id] for pair_id in pairs
                       if any(view.get("action_state") in _HEALTHY | {"UNKNOWN", "HOLD"}
                              for view in pairs[pair_id].values())}
        decisions: list[dict[str, Any]] = []
        for pair_id, arms in pairs.items():
            decisions += self._coordinate(pair_id, arms, views)
        return decisions

    def _partner_problem(self, view: Mapping[str, Any], arms, views) -> str | None:
        partner = view.get("partner_instance_id")
        other = arms.get(partner)
        if other is not None and other.get("action_state") == "SUCCEEDED":
            return None  # the partner finished; nothing to couple to
        if views.get(partner) is None:
            return "PARTNER_LINK_LOST"
        if other is None or other.get("action_state") == "UNKNOWN":
            return "PARTNER_UNKNOWN"
        if other.get("action_state") in _FAILED:
            return "PARTNER_FAILED"
        return None

    def _stop_once(self, instance: str, view: Mapping[str, Any], reason: str) -> list[dict[str, Any]]:
        if (instance, view["action_id"]) in self._stopped:
            return []
        return [self._stop(instance, view, reason)]

    def _coordinate(self, pair_id: str, arms: dict[str, dict[str, Any]], views) -> list[dict[str, Any]]:
        decisions = []
        for instance, view in arms.items():
            problem = self._partner_problem(view, arms, views)
            if (problem is not None and view.get("action_state") in _HEALTHY
                    and view.get("coupling_now") == "tight"):
                decisions += self._stop_once(instance, view, problem)
        if len(arms) != 2 or any(view.get("action_state") not in _HEALTHY for view in arms.values()):
            return decisions
        (first, left), (second, right) = sorted(arms.items())
        if left.get("partner_instance_id") != second or right.get("partner_instance_id") != first:
            return decisions
        right_barriers = {item["barrier_id"]: item for item in right.get("barriers", ())}
        for barrier in left.get("barriers", ()):
            other = right_barriers.get(barrier["barrier_id"])
            if (other is None or barrier["state"] not in _ARRIVED or other["state"] not in _ARRIVED
                    or "waiting" not in {barrier["state"], other["state"]}):
                continue
            decisions += self._release_pair(barrier["barrier_id"], (
                (first, left, barrier, other, right), (second, right, other, barrier, left)))
        return decisions

    def _release_pair(self, barrier_id: str, sides) -> list[dict[str, Any]]:
        """Release a barrier both arms reached. Both owners must report an open fence first; if one
        side ends up released while the other is refused, a tight segment is stopped at once."""
        decisions, released, refused = [], [], []
        open_both = all(view.get("fence_open") is True for _, view, *_ in sides)
        for instance, view, mine, theirs, partner in sides:
            if mine["state"] == "released":
                released.append((instance, view, mine))
            elif not open_both or refused:  # after one refusal, release nobody else this tick
                refused.append((instance, "PARTNER_UNKNOWN"))
            else:
                result = self._release(instance, view, mine, theirs, partner)
                decisions.append(result)
                if result["status"] == 200:
                    released.append((instance, view, mine))
                else:
                    refused.append((instance, "PARTNER_FAILED" if result.get("code") in _PARTNER_ENDED_CODES
                                    else "PARTNER_UNKNOWN"))
        if refused and released:
            reason = refused[0][1]
            for instance, view, mine in released:
                if mine.get("coupling_after") == "tight":
                    decisions += self._stop_once(instance, view, reason)
        return decisions

    def _release(self, instance, view, mine, theirs, partner) -> dict[str, Any]:
        request = {"version": 2, "operation": "ReleaseBarrier", "action_id": view["action_id"],
                   "pair_id": view["pair_id"], "barrier_id": mine["barrier_id"],
                   "authority_epoch": view["authority_epoch"],
                   "dispatch_generation": view["dispatch_generation"],
                   "partner_arrival": {"instance_id": partner["instance_id"],
                                       "action_id": partner["action_id"],
                                       "arrived_at": theirs["arrived_at"]}}
        try:
            response = self._call(instance, request)
            status, code = response.get("status"), (response.get("error") or {}).get("code")
        except (OwnerUnavailable, OSError, ValueError):
            status, code = None, None
        return {"decision": "release", "instance_id": instance, "action_id": view["action_id"],
                "barrier_id": mine["barrier_id"], "status": status, "code": code}

    def _stop(self, instance: str, view: Mapping[str, Any], reason: str) -> dict[str, Any]:
        request = {"version": 1, "operation": "StopLocal", "workcell_id": view["workcell_id"],
                   "instance_id": instance, "authority_epoch": view["authority_epoch"],
                   "dispatch_generation": view["dispatch_generation"],
                   "requested_at": self.now().astimezone(timezone.utc).isoformat(), "reason": reason}
        try:
            status = self._call(instance, request).get("status")
        except (OwnerUnavailable, OSError, ValueError):
            status = None
        if status == 200:
            self._stopped.add((instance, view["action_id"]))
        return {"decision": "stop", "instance_id": instance, "action_id": view["action_id"],
                "reason": reason, "status": status}

    def run(self, *, period_s: float, stop: threading.Event) -> None:
        """Tick until ``stop``; ``period_s`` must stay well under the owners' liveness bound."""
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                _LOG.exception("coordinator tick failed")
            stop.wait(period_s)


__all__ = ["OwnerClient", "OwnerUnavailable", "UnixOwnerClient", "WorkcellCoordinator"]
