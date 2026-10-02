"""Fleet localization service (D-395 Phase 2 P2-6, contract §3): poll, arbitrate, post.

Every 0.5 s it reads each robot's `/robot/state`. For a robot in CANDIDATES it reads
`/localization/candidates`, builds the arbiter `Context` (anchored LOCALIZED map-frame
peers, see `_track_provenance`, the reference squares and slots from `lane_rules.yaml`, and an overhead sighting no
older than 300 ms) and posts the arbiter's decision. While CORE runs a mission for the
robot (`GET /localization/mission` says `running`) and for 1 s after it ends, Fleet
neither arbitrates nor decides for it. It also runs the §9 monitor
(`POST /localization/suspect`) and times the escalation ladder. Monitor evidence comes from
CANDIDATES reports and from the unmapped objects in each LOCALIZED anchor's status, placed
from the anchor's reported pose (S1 R1), so a mirror lock shows while every robot is LOCALIZED.

**Overhead sightings are off by default.** D-257 §5 still says a sighting does not
enter robot localization; D-395 only *proposes* to amend that, and the amendment is
not accepted. `overhead_cue=True` (CLI `--localization-overhead-cue`) feeds sightings
to the arbiter and the monitor for sim/bench work; leave it off on a live site.

Ladder missions (P2-7): at 10 s `rotate_in_place`, at 45 s `to_square` (when a square
is known; CORE refuses it as `unsupported` today) then `lane_to_stopline`, at 120 s
`needs_human` (console badge "위치 확인 필요"). A rung CORE answers `busy` (the previous
mission still running) is asked again every 2 s while the ladder stays on it. The ladder
clock stops, and no rung or retry goes out, while the arbiter may still decide the robot's
open request (`Arbiter.pending`) or the robot reports `reason: checking`, for at most
30 s per episode (S1 re-run R2, R6). CORE drives every mission; Fleet only
asks (D-2, D-369). Before a mission Fleet holds the robots near the mover through the
console's traffic keep-out (`traffic_hold`), and it never asks a LOCALIZED robot or one
that predates D-395.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Awaitable, Callable, Mapping, Optional, Sequence

import yaml

from core_common.protocol.localization import (CHECKING, DecisionSource, LocalizationDecision,
                                               LocState)
from fleet.localization import cues, service_logic, trust
from fleet.localization.arbiter import Arbiter, Context
from fleet.localization.service_logic import Ladder, Monitor
from fleet.swarm.transport import RobotApiError, RobotClient

logger = logging.getLogger("fleet.localization")

POLL_S = 0.5
#: Each robot call is bounded so one stalled CORE cannot hold up the others (review of lane C).
CALL_TIMEOUT_S = 1.0
#: No decision while a CORE mission moves the robot, nor this long after it ends: a pose
#: decided mid-rotation failed its check at fit 0.18-0.39 (S1 re-run, F1 WSL run).
MISSION_QUIET_S = 1.0


def load_lane_rules(path: Optional[Path]) -> dict:
    """`lane_rules.yaml` as a dict; {} (no squares, no slots) when absent or unreadable."""
    if path is None:
        return {}
    try:
        rules = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        logger.warning("localization: lane rules %s unreadable (%s); no squares or slots", path, exc)
        return {}
    return rules if isinstance(rules, dict) else {}


def default_lane_rules() -> Optional[Path]:
    """map_v2_fleet's lane_rules.yaml when Fleet runs from a source checkout, else None."""
    path = (Path(__file__).resolve().parents[4] / "runtime" / "sensing" / "map" / "map_v2_fleet"
            / "lane_rules.yaml")
    return path if path.is_file() else None


def build_localization_service(console, sightings, *, enabled: bool = True,
                               overhead_cue: bool = False,
                               lane_rules: Optional[Path] = None) -> Optional["LocalizationService"]:
    """CLI wiring: on unless disabled; the overhead cue stays off unless asked for."""
    if not enabled:
        return None
    slots, squares = service_logic.parse_reference_squares(
        load_lane_rules(lane_rules if lane_rules is not None else default_lane_rules()))
    return LocalizationService(console.clients, slots=slots, squares=squares,
                               sightings=sightings, overhead_cue=bool(overhead_cue),
                               traffic_hold=getattr(console, "hold_for_localization", None))


def _pose(state: Mapping) -> Optional[cues.Pose]:
    pose = state.get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"]), float(pose.get("yaw", 0.0))
    except (KeyError, TypeError, ValueError):
        return None


class LocalizationService:
    def __init__(self, clients: Callable[[], Mapping[str, RobotClient]], *,
                 slots: Sequence[cues.Slot] = (), squares: Sequence[tuple[float, float]] = (),
                 sightings=None, overhead_cue: bool = False, arbiter: Optional[Arbiter] = None,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time, poll_s: float = POLL_S,
                 call_timeout_s: float = CALL_TIMEOUT_S,
                 traffic_hold: Optional[Callable[[str], Awaitable[Sequence[str]]]] = None) -> None:
        self._clients = clients
        self._slots = tuple(slots)
        self._squares = tuple(squares)
        self._sightings = sightings
        self.overhead_cue = overhead_cue
        self._arbiter = arbiter or Arbiter()
        self._clock = clock
        self._wall = wall          # sighting captured_at is site wall time
        self._poll_s = poll_s
        self._timeout_s = call_timeout_s
        #: Holds the robots near a mover before its mission (console traffic keep-out).
        self._traffic_hold = traffic_hold
        self._monitor = Monitor()
        self._ladder = Ladder()
        self._last_good: dict[str, cues.Pose] = {}
        self._last_decision: dict[str, dict] = {}
        self._last_mission: dict[str, dict] = {}
        self._last_report: dict[str, object] = {}
        #: robot_id -> (rung, Fleet time of the busy refusal) still to be retried.
        self._busy_rung: dict[str, tuple[str, float]] = {}
        #: robot_id -> mission kinds CORE refused as `unsupported` in this ladder episode.
        self._unsupported: dict[str, set] = {}
        #: Anchor provenance (S1 finding 3): anchored robots, the decided pose of an anchoring
        #: decision sent and not yet seen LOCALIZED, and each LOCALIZED robot's last pose.
        self._anchors: set[str] = set()
        self._pending: dict[str, cues.Pose] = {}
        self._localized_at: dict[str, tuple[cues.Pose, float]] = {}
        #: robot_id -> ((request_id, stamp), Fleet monotonic time first seen).
        self._report_seen: dict[str, tuple] = {}
        #: anchor robot_id -> (objects_stamp, Fleet monotonic time first seen) (S1 R1).
        self._objects_seen: dict[str, tuple] = {}
        #: Robots whose CORE mission was `running` at the last poll, and the Fleet time
        #: until which a robot whose mission ended stays without decisions.
        self._mission_running: set[str] = set()
        self._quiet_until: dict[str, float] = {}
        self._known: set[str] = set()

    # --- console --------------------------------------------------------------------

    def view(self, robot_id: str) -> Optional[dict]:
        """Per-robot state for the console badge; None for a robot the service never saw."""
        if robot_id not in self._known:
            return None
        return {**self._ladder.view(robot_id, self._clock()),
                "last_decision": self._last_decision.get(robot_id),
                "last_mission": self._last_mission.get(robot_id)}

    # --- loop -----------------------------------------------------------------------

    async def run(self) -> None:
        logger.info("localization service: polling every %.1f s, %d squares, overhead sighting cue %s",
                    self._poll_s, len(self._squares),
                    "ON (D-257 amendment not accepted: bench use only)" if self.overhead_cue
                    else "OFF (D-257 amendment not accepted)")
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("localization service tick failed")
            await asyncio.sleep(self._poll_s)

    async def tick(self) -> None:
        now = self._clock()
        clients = dict(self._clients())
        self._forget_removed(set(clients))
        ids = sorted(clients)
        results = await asyncio.gather(*(self._bounded(clients[rid].state()) for rid in ids),
                                       return_exceptions=True)
        states = {rid: r for rid, r in zip(ids, results) if isinstance(r, dict)}
        localized = {rid: p for rid, s in states.items()
                     if trust.classify(s) == trust.TRUSTED and (p := _pose(s)) is not None}
        self._last_good.update(localized)
        self._track_provenance(states, localized, now)
        anchors = {rid: p for rid, p in localized.items() if rid in self._anchors}

        unlocalized = [rid for rid, state in states.items()
                       if (status := trust.status_of(state)) is not None
                       and status.state is not LocState.LOCALIZED]
        quiet = await asyncio.gather(*(self._mission_quiet(rid, clients[rid], now) for rid in unlocalized))
        quiet = {rid for rid, q in zip(unlocalized, quiet) if q}

        observations: dict[str, list] = {}
        await asyncio.gather(*(
            self._arbitrate(rid, clients[rid], localized, anchors, observations, now)
            for rid, state in states.items()
            if rid not in quiet
            and (status := trust.status_of(state)) is not None and status.state is LocState.CANDIDATES))
        self._observe_from_anchors(states, localized, anchors, observations, now)
        await self._watch(localized, observations, now)
        for rid, state in states.items():
            status = trust.status_of(state)
            rung = self._ladder.update(rid, status.state if status else None, now,
                                       paused=self._decision_pending(rid, status))
            if rid not in self._ladder.robots():
                self._unsupported.pop(rid, None)          # the ladder episode ended
            retry = self._busy_rung.get(rid)
            if (rung is None and retry is not None and not self._ladder.holding(rid)
                    and retry[0] == self._ladder.view(rid, now)["rung"]
                    and now - retry[1] >= service_logic.BUSY_RETRY_S):
                rung = retry[0]
            if rung is not None:
                self._busy_rung.pop(rid, None)
                await self._climb(rid, clients[rid], rung, status, now)

    # --- steps ----------------------------------------------------------------------

    def _decision_pending(self, rid: str, status) -> bool:
        """S1 re-run R2/R6: the ladder waits while a decision may still come for the robot's
        open request (an arbiter lead or cue, or one just sent) or its 3 s check runs."""
        if status is None or status.state is not LocState.CANDIDATES:
            return False
        return status.reason == CHECKING or self._arbiter.pending(rid, status.request_id)

    async def _bounded(self, call):
        return await asyncio.wait_for(call, self._timeout_s)

    def _track_provenance(self, states: Mapping[str, dict], localized: Mapping[str, cues.Pose],
                          now: float) -> None:
        """Anchors (S1 finding 3): LOCALIZED at the pose of a Fleet decision that a world
        cue, `source: human` or anchored peers carried. The track is 180-degree symmetric,
        so robots mirrored together agree with each other; only an anchor may be a peer.

        Provenance resets when the robot is seen outside LOCALIZED (an unreadable poll
        keeps it) and when its pose jumps while LOCALIZED (a pose injected past Fleet).
        A robot first seen LOCALIZED, or LOCALIZED away from the decided pose, has
        unknown provenance and is not an anchor until it re-localizes."""
        for rid in states:
            pose = localized.get(rid)
            previous = self._localized_at.get(rid)
            if pose is None:
                self._anchors.discard(rid)
                self._localized_at.pop(rid, None)
                continue
            self._localized_at[rid] = (pose, now)
            if previous is None:
                decided = self._pending.pop(rid, None)
                if decided is not None and not service_logic.disagrees(decided, pose):
                    self._anchors.add(rid)
                    logger.info("localization: %s LOCALIZED by a Fleet decision: anchor", rid)
                else:
                    logger.info("localization: %s LOCALIZED without a Fleet-known decision: "
                                "not an anchor, not a peer", rid)
            elif rid in self._anchors and service_logic.jumped(previous[0], pose, now - previous[1]):
                self._anchors.discard(rid)
                logger.warning("localization: %s pose jumped while LOCALIZED: no longer an anchor", rid)

    def anchors(self) -> set:
        """Robots whose LOCALIZED pose Fleet can trace to a world cue (tests, console)."""
        return set(self._anchors)

    async def _mission_quiet(self, rid: str, client: RobotClient, now: float) -> bool:
        """True while CORE runs a mission for `rid` and MISSION_QUIET_S after it ends:
        no arbiter, no decision, no report read (its candidates predate the motion).
        A CORE without missions (an API error such as 501) runs none; an unreadable
        status is quiet for this poll, since Fleet cannot tell the robot is still."""
        try:
            status = await self._bounded(client.localization_mission_status())
        except RobotApiError:
            status = {}
        except Exception as exc:
            logger.debug("localization: %s mission status unreadable: %s", rid, exc)
            return True
        if status.get("state") == "running":
            self._mission_running.add(rid)
            return True
        if rid in self._mission_running:
            self._mission_running.discard(rid)
            self._quiet_until[rid] = now + MISSION_QUIET_S
        return now < self._quiet_until.get(rid, -math.inf)

    async def _arbitrate(self, rid: str, client: RobotClient, localized: Mapping[str, cues.Pose],
                         anchors: Mapping[str, cues.Pose], observations: dict, now: float) -> None:
        try:
            report = await self._bounded(client.localization_candidates())
        except Exception as exc:
            logger.debug("localization: %s candidates unreadable: %s", rid, exc)
            return
        if report is None:
            return
        if report.robot_id != rid:
            logger.warning("localization: %s reported candidates for %s; ignored", rid, report.robot_id)
            return
        self._last_report[rid] = report
        peers = {o: p for o, p in localized.items() if o != rid}       # watched by the monitor
        context = Context(peers=[p[:2] for o, p in anchors.items() if o != rid], slots=self._slots,
                          squares=self._squares, last_good=self._last_good.get(rid),
                          sighting=self._sighting(rid, now))
        # The monitor places this robot's unmapped objects from its leading candidate,
        # chosen without the peers cue: a mislocated peer must not pick the observer's pose.
        leader = service_logic.clear_leader(
            report, Context(slots=self._slots, squares=self._squares,
                            last_good=context.last_good, sighting=context.sighting), now)
        # D-395 rev. 3: clocks are not synced, so freshness runs on Fleet's clock from the
        # first time Fleet saw this report; a re-fetch of the same report keeps that time.
        key = (report.request_id, report.stamp)
        seen = self._report_seen.get(rid)
        if seen is None or seen[0] != key:
            seen = self._report_seen[rid] = (key, now)
        fresh = now - seen[1] <= service_logic.REPORT_FRESH_S
        if leader is not None and fresh:
            for peer, seen in service_logic.peer_observations(report.unmapped_objects, leader, peers).items():
                observations.setdefault(peer, []).append(((rid, *key), seen))
        decision = self._arbiter.observe(report, context, now)
        if decision is not None:
            c = report.candidates[decision.candidate_index]
            await self._post_decision(rid, client, decision, (c.x, c.y, c.yaw))

    async def _post_decision(self, rid: str, client: RobotClient,
                             decision: LocalizationDecision, pose: cues.Pose) -> None:
        record = {"request_id": decision.request_id, "candidate_index": decision.candidate_index,
                  "cues": [c.value for c in decision.cues], "result": "sent"}
        try:
            await self._bounded(client.localization_decision(decision))
            logger.info("localization: %s decision %s candidate %s cues %s", rid,
                        decision.request_id, decision.candidate_index, record["cues"])
            # Context.peers holds anchors only, so a `peers` cue is anchored too.
            if decision.source is DecisionSource.HUMAN or any(
                    k in service_logic.WORLD_CUES or k == "peers" for k in record["cues"]):
                self._pending[rid] = pose
        except RobotApiError as exc:
            record["result"] = exc.code
            logger.info("localization: %s refused decision %s: %s", rid, decision.request_id, exc.code)
        except Exception as exc:
            record["result"] = "unreachable"
            logger.warning("localization: decision %s to %s failed: %s", decision.request_id, rid, exc)
        self._last_decision[rid] = record

    def _observe_from_anchors(self, states: Mapping[str, dict], localized: Mapping[str, cues.Pose],
                              anchors: Mapping[str, cues.Pose], observations: dict, now: float) -> None:
        """D-395 rev. 4 §5 follow-up (S1 R1): a LOCALIZED anchor's status carries what its
        lidar sees; placed from its reported map pose, it is evidence about every other
        LOCALIZED robot. Anchors only: a mirror-locked robot places a correct one on its
        twin, and an observer is never evidence about itself. Each (anchor, objects_stamp)
        is one observation, fresh for REPORT_FRESH_S after Fleet first saw it."""
        for rid, pose in anchors.items():
            status = trust.status_of(states.get(rid))
            if status is None or status.objects_stamp is None:
                self._objects_seen.pop(rid, None)
                continue
            seen = self._objects_seen.get(rid)
            if seen is None or seen[0] != status.objects_stamp:
                seen = self._objects_seen[rid] = (status.objects_stamp, now)
            if now - seen[1] > service_logic.REPORT_FRESH_S:
                continue
            targets = {o: p for o, p in localized.items() if o != rid}
            for target, observed in service_logic.peer_observations(
                    status.unmapped_objects, pose, targets).items():
                observations.setdefault(target, []).append((("objects", rid, status.objects_stamp), observed))

    async def _watch(self, localized: Mapping[str, cues.Pose], observations: Mapping[str, list],
                     now: float) -> None:
        """`observations`: robot -> [(evidence key, observed pose)]; a key is one report."""
        for rid in list(self._known):
            if rid not in localized:
                self._monitor.forget(rid)
        suspects = []
        for rid, pose in localized.items():
            seen = list(observations.get(rid, ()))
            sighting = self._sighting(rid, now)
            if sighting is not None:
                seen.append((("overhead", round(sighting.captured_at, 3)),
                             (sighting.x, sighting.y, sighting.yaw)))
            evidence = [(key, service_logic.disagrees(pose, o)) for key, o in seen]
            if self._monitor.update(rid, evidence, now):
                suspects.append(rid)
        await asyncio.gather(*(self._post_suspect(rid) for rid in suspects))

    async def _post_suspect(self, rid: str) -> None:
        client = self._clients().get(rid)
        if client is None:
            return
        logger.warning("localization: %s observed > %.2f m / %.0f deg off in %d reports; suspect",
                       rid, service_logic.SUSPECT_DIST_M, math.degrees(service_logic.SUSPECT_YAW_RAD),
                       service_logic.SUSPECT_REPORTS)
        try:
            await self._bounded(client.localization_suspect(service_logic.SUSPECT_REASON))
        except Exception as exc:
            logger.warning("localization: suspect to %s failed: %s", rid, exc)

    async def _climb(self, rid: str, client: RobotClient, rung: str, status, now: float) -> None:
        """One ladder rung: ask CORE for the rung's mission, or raise needs_human."""
        if rung == "needs_human":
            logger.warning("localization: %s still unlocalized after %.0f s: needs_human (위치 확인 필요)",
                           rid, self._ladder.human_s)
            return
        if status is None or status.state is LocState.LOCALIZED:
            return          # legacy (null) or LOCALIZED robots never get a mission
        target = service_logic.square_target(self._last_report.get(rid), self._squares)
        refused = self._unsupported.setdefault(rid, set())
        kinds = [k for k in service_logic.RUNG_MISSIONS[rung]
                 if k not in refused and (k != "to_square" or target is not None)]
        if not kinds:
            return
        try:
            held = list(await self._traffic_hold(rid)) if self._traffic_hold is not None else []
        except Exception as exc:
            logger.warning("localization: %s mission skipped, traffic hold failed: %s", rid, exc)
            self._last_mission[rid] = {"kind": kinds[0], "rung": rung, "held": [],
                                       "result": "traffic_hold_failed"}
            return
        for kind in kinds:
            distance, limit = service_logic.MISSION_LIMITS[kind]
            record = {"kind": kind, "rung": rung, "held": held, "result": "sent"}
            self._last_mission[rid] = record
            try:
                await self._bounded(client.localization_mission(
                    kind, max_distance_m=distance, max_time_s=limit,
                    target=target if kind == "to_square" else None))
                logger.info("localization: %s ladder %s: %s sent (held %s)", rid, rung, kind, held)
                return
            except RobotApiError as exc:
                record["result"] = exc.code
                logger.info("localization: %s refused %s: %s %s", rid, kind, exc.code, exc)
                if exc.code == "busy":
                    self._busy_rung[rid] = (rung, now)
                if exc.code != "unsupported":
                    return
                refused.add(kind)          # final for this ladder episode (S1: 13-20 re-asks)
            except Exception as exc:
                record["result"] = "unreachable"
                logger.warning("localization: mission %s to %s failed: %s", kind, rid, exc)
                return

    def _sighting(self, rid: str, now: float) -> Optional[cues.Sighting]:
        """A fresh (<= 300 ms) overhead sighting, only while the D-257 flag is on."""
        if not self.overhead_cue or self._sightings is None:
            return None
        for row in self._sightings.snapshot().get("sightings", ()):
            if row.get("robot_id") != rid:
                continue
            try:
                age = self._wall() - float(row["captured_at"])
                x, y, yaw = float(row["x"]), float(row["y"]), float(row["yaw"])
            except (KeyError, TypeError, ValueError):
                return None
            if not 0.0 <= age <= cues.OVERHEAD_FRESH_S:
                return None
            return cues.Sighting(x, y, yaw, captured_at=now - age)
        return None

    def _forget_removed(self, current: set) -> None:
        for rid in self._known - current:
            self._monitor.forget(rid)
            self._ladder.forget(rid)
            self._last_good.pop(rid, None)
            self._last_decision.pop(rid, None)
            self._last_mission.pop(rid, None)
            self._last_report.pop(rid, None)
            self._busy_rung.pop(rid, None)
            self._unsupported.pop(rid, None)
            self._report_seen.pop(rid, None)
            self._objects_seen.pop(rid, None)
            self._mission_running.discard(rid)
            self._quiet_until.pop(rid, None)
            self._anchors.discard(rid)
            self._pending.pop(rid, None)
            self._localized_at.pop(rid, None)
        self._known = current
