"""D-1079: uncertain-motion markers, admission-deadline release window, and generation fencing."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import logging
import time

from core_common.protocol.evidence import STALE_POSE_S
from fleet.server.named_stop_motion import STOPPED_NAVIGATION, confirmed_estop, measured_stop_proof
from fleet.swarm.api.ports import RobotApiError
from fleet.swarm.motion_ingress import (ADMIT_DEADLINE_PATHS, MOTION_RELEASE_MARGIN_S,
                                         PREPARED_GOALS, starts_or_sustains_motion)
from rosy.world.state.projections.map_pose_samples import parse_utc

logger = logging.getLogger("fleet.goal_lease")

_prepared_wire = ContextVar("prepared_stop_wire", default=None)
_repark_wire = ContextVar("named_stop_repark_wire", default=None)
_REPARK_PATH = "/api/v1/motion/repark/run"


class UncertainMotion:
    _navigation_stopped: type[BaseException] = RuntimeError

    @contextmanager
    def _check_motion_wire(self, robot_id, method, path, body, *, sent_at, timeout_s):
        if (method.upper() == "POST" and path in PREPARED_GOALS) or starts_or_sustains_motion(method, path, body):
            if (reason := getattr(self, "station_stop_reason", lambda _: None)(robot_id)):
                raise RobotApiError(robot_id, 409, reason, "the assigned station operation is awaiting external release")
        if method.upper() == "POST" and path in PREPARED_GOALS:
            permit = _prepared_wire.get()
            if permit is None or permit[0] is not self or permit[1:] != (robot_id, (body or {}).get("plan_id")):
                raise RobotApiError(robot_id, 409, "NAMED_STOP_SITE_RESERVED", "prepared motion needs the site reservation")
            yield
            return
        claim = self._named_stop_motion
        if (path == "/api/v1/navigation/goal/lease" and claim is not None and claim.robot_id == robot_id
                and (body or {}).get("correlation_id") == claim.correlation_id):
            yield
            return
        if method.upper() == "POST" and path == _REPARK_PATH:
            permit = _repark_wire.get()
            if (claim is None or permit is None or permit[0] is not self or permit[1] is not claim
                    or claim.robot_id != robot_id or permit[2] is not body
                    or claim.repark_correlation_id != body.get("correlation_id")):
                raise RobotApiError(robot_id, 409, "NAMED_STOP_SITE_RESERVED", "repark needs the exact site reservation")
            yield
            return
        if not starts_or_sustains_motion(method, path, body):
            yield
            return

        def unresolved():
            payload = (body or {}) if path in ADMIT_DEADLINE_PATHS else {}
            boot_id = payload.get("expected_boot_id")
            owner_generation = payload.get("expected_owner_generation")
            self._mark_uncertain_motion(robot_id, sent_at=sent_at, timeout_s=timeout_s,
                                        admit_within_s=payload.get("admit_within_s"),
                                        boot_id=str(boot_id) if boot_id is not None else None,
                                        owner_generation=(owner_generation if type(owner_generation) is int
                                                          and owner_generation >= 0 else None))

        try:
            with self.motion_request():
                yield unresolved
        except self._navigation_stopped as exc:
            raise RobotApiError(robot_id, 409, "NAMED_STOP_SITE_RESERVED", str(exc)) from exc

    @contextmanager
    def motion_request(self):
        self.check_motion()
        self.motion_epoch += 1
        self._motion_requests += 1
        try:
            yield
        finally:
            self._motion_requests -= 1

    def _mark_uncertain_motion(self, robot_id, *, sent_at, timeout_s, admit_within_s,
                               boot_id=None, owner_generation=None):
        previous = self._uncertain_motion.get(robot_id)
        if boot_id is None or owner_generation is None:
            admit_within_s = None
        release_after = (None if admit_within_s is None else
                         sent_at + timeout_s + admit_within_s + MOTION_RELEASE_MARGIN_S)
        if previous is not None:
            if previous.get("boot_id") is not None and boot_id is not None and previous["boot_id"] != boot_id:
                release_after = None
            elif previous.get("boot_id") is not None and boot_id is None:
                boot_id = previous["boot_id"]
            if previous.get("owner_generation") is not None and (
                    owner_generation is None or previous["owner_generation"] > owner_generation):
                owner_generation = previous["owner_generation"]
        # A later bounded failure cannot erase an earlier unbounded or longer uncertainty.
        if previous is not None and (previous["release_after"] is None or release_after is None
                                     or previous["release_after"] > release_after):
            sent_at, timeout_s, admit_within_s = (previous[key] for key in
                ("sent_at", "timeout_s", "admit_within_s"))
            release_after = None if release_after is None else previous["release_after"]
        self.motion_epoch += 1
        self._uncertain_motion[robot_id] = {
            "since": self._clock(), "wall_time": time.time(),
            "sent_at": sent_at, "timeout_s": timeout_s, "admit_within_s": admit_within_s,
            "release_after": release_after, "boot_id": boot_id, "owner_generation": owner_generation,
            "fenced_generation": None, "fenced_at": None, "fenced_wall_time": None,
            "wire_version": self._wire_versions.get(robot_id, 0), "motion_epoch": self.motion_epoch,
        }
        if release_after is None:
            logger.warning("uncertain motion of %s: 기한 없는 CORE라 해제 불가 (or motion without admission deadline)",
                           robot_id)

    async def _verify_uncertain_release_fence(self, robot_id, client) -> bool:
        marker = self._uncertain_motion.get(robot_id)
        if marker is None or marker["release_after"] is None or self._clock() < marker["release_after"]:
            return False
        expected_boot = marker.get("boot_id")
        expected_gen = marker.get("owner_generation")
        if not isinstance(expected_boot, str) or not expected_boot or type(expected_gen) is not int or expected_gen < 0:
            return False
        get = getattr(client, "_get", None)
        if not callable(get):
            return False
        view = await get("/api/v1/navigation/state")
        owner = view.get("owner") if isinstance(view, dict) else None
        if not isinstance(owner, dict):
            self._invalidate_admit_deadline(client)
            return False
        boot_id, gen = owner.get("boot_id"), owner.get("owner_generation")
        if boot_id != expected_boot or type(gen) is not int or gen < 0:
            self._invalidate_admit_deadline(client)
            return False
        fenced_gen = marker.get("fenced_generation")
        if fenced_gen is None or gen <= expected_gen:
            if view.get("navigation") not in STOPPED_NAVIGATION:
                return False
            cancel = getattr(client, "navigation_cancel", None)
            if not callable(cancel):
                return False
            try:
                reply = await cancel(advance_generation=True)
            except TypeError:
                return False
            reply_owner = reply.get("owner") if isinstance(reply, dict) else None
            if not isinstance(reply_owner, dict):
                return False
            if reply_owner.get("boot_id") != boot_id:
                self._invalidate_admit_deadline(client)
                return False
            new_gen = reply_owner.get("owner_generation")
            if type(new_gen) is not int or new_gen <= max(expected_gen, gen):
                return False
            marker["fenced_generation"] = new_gen
            marker["fenced_at"] = self._clock()
            marker["fenced_wall_time"] = time.time()
            return True
        if gen != fenced_gen or view.get("navigation") not in STOPPED_NAVIGATION:
            marker["fenced_generation"] = None
            marker["fenced_at"] = None
            marker["fenced_wall_time"] = None
            return False
        return True

    @staticmethod
    def _invalidate_admit_deadline(client) -> None:
        clear = getattr(client, "_clear_admit_capability", None)
        if callable(clear):
            clear()
        elif hasattr(client, "_admit_deadline"):
            client._admit_deadline = False

    @contextmanager
    def _motion_readback(self, robot_id, client):
        """Only proof from an observation started after this marker, with no intervening send, can clear it."""
        marker = self._uncertain_motion.get(robot_id)
        started, wire = self._clock(), self.peer_wire_state([robot_id])[robot_id]
        pending = self.pending.get(robot_id)

        def confirmed(reason, *, sampled_at=None):
            fenced_at = marker.get("fenced_at") if marker is not None else None
            fenced_wall = marker.get("fenced_wall_time") if marker is not None else None
            if (marker is None or self._uncertain_motion.get(robot_id) is not marker
                    or started <= marker["since"] or marker["release_after"] is None
                    or started < marker["release_after"] or fenced_at is None
                    or wire[1] or pending
                    or self.peer_wire_state([robot_id])[robot_id] != wire or self.pending.get(robot_id)
                    or self._clients.get(robot_id) is not client
                    or sampled_at is not None and (sampled_at <= marker["wall_time"]
                                                   or fenced_wall is not None and sampled_at <= fenced_wall)):
                return
            del self._uncertain_motion[robot_id]
            logger.warning("uncertain motion of %s resolved: %s", robot_id, reason)

        yield confirmed

    async def read_motion_state(self, robot_id, client):
        """Bypass shared/heartbeat caches for uncertainty recovery; keep the normal state response."""
        marker = self._uncertain_motion.get(robot_id)
        with self._motion_readback(robot_id, client) as confirmed:
            fenced = marker is not None and await self._verify_uncertain_release_fence(robot_id, client)
            after = (max(marker["wall_time"], marker.get("fenced_wall_time") or marker["wall_time"])
                     if marker is not None else time.time())
            state = await client.state()
            now = time.time()
            # CORE sample time vs Fleet wall time: clock skew can pass within STALE_POSE_S if after < stamp <= now.
            if fenced and measured_stop_proof(state, robot_id, after, now) is not None:
                if await self._verify_uncertain_release_fence(robot_id, client):
                    confirmed("CORE measured standstill")
            elif fenced and isinstance(state, dict) and state.get("robot_id") == robot_id and confirmed_estop(state):
                stamp = parse_utc(state["evidence"]["velocity"]["sampled_at"])
                if stamp is not None and after < stamp <= now and now - stamp < STALE_POSE_S:
                    if await self._verify_uncertain_release_fence(robot_id, client):
                        confirmed("CORE confirmed E-stop with measured zero velocity")
        return state
