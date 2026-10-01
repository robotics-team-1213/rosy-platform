"""Fleet localization service (D-395 Phase 2 P2-6, contract §3): poll, arbitrate, post.

Every 0.5 s it reads each robot's `/robot/state`. For a robot in CANDIDATES it reads
`/localization/candidates`, builds the arbiter `Context` (LOCALIZED map-frame peers,
the reference squares and slots from `lane_rules.yaml`, and an overhead sighting no
older than 300 ms) and posts the arbiter's decision. It also runs the §9 monitor
(`POST /localization/suspect`) and times the escalation ladder.

**Overhead sightings are off by default.** D-257 §5 still says a sighting does not
enter robot localization; D-395 only *proposes* to amend that, and the amendment is
not accepted. `overhead_cue=True` (CLI `--localization-overhead-cue`) feeds sightings
to the arbiter and the monitor for sim/bench work; leave it off on a live site.

Ladder missions (`rotate_in_place`, `to_square`/`lane_to_stopline`) are logged as
"pending P2-7" and never sent: CORE's mission executor is lane B P2-7. Only the last
rung, `needs_human`, is visible: the console badge reads "위치 확인 필요".
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import yaml

from core_common.protocol.localization import LocalizationDecision, LocState
from fleet.localization import cues, service_logic, trust
from fleet.localization.arbiter import Arbiter, Context
from fleet.localization.service_logic import Ladder, Monitor
from fleet.swarm.transport import RobotApiError, RobotClient

logger = logging.getLogger("fleet.localization")

POLL_S = 0.5


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
                               sightings=sightings, overhead_cue=bool(overhead_cue))


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
                 wall: Callable[[], float] = time.time, poll_s: float = POLL_S) -> None:
        self._clients = clients
        self._slots = tuple(slots)
        self._squares = tuple(squares)
        self._sightings = sightings
        self.overhead_cue = overhead_cue
        self._arbiter = arbiter or Arbiter()
        self._clock = clock
        self._wall = wall          # sighting captured_at is site wall time
        self._poll_s = poll_s
        self._monitor = Monitor()
        self._ladder = Ladder()
        self._last_good: dict[str, cues.Pose] = {}
        self._last_decision: dict[str, dict] = {}
        self._known: set[str] = set()

    # --- console --------------------------------------------------------------------

    def view(self, robot_id: str) -> Optional[dict]:
        """Per-robot state for the console badge; None for a robot the service never saw."""
        if robot_id not in self._known:
            return None
        return {**self._ladder.view(robot_id, self._clock()),
                "last_decision": self._last_decision.get(robot_id)}

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
        results = await asyncio.gather(*(clients[rid].state() for rid in ids),
                                       return_exceptions=True)
        states = {rid: r for rid, r in zip(ids, results) if isinstance(r, dict)}
        localized = {rid: p for rid, s in states.items()
                     if trust.classify(s) == trust.TRUSTED and (p := _pose(s)) is not None}
        self._last_good.update(localized)

        observations: dict[str, list] = {}
        for rid, state in states.items():
            status = trust.status_of(state)
            if status is not None and status.state is LocState.CANDIDATES:
                await self._arbitrate(rid, clients[rid], localized, observations, now)
        await self._watch(localized, observations, now)
        for rid, state in states.items():
            status = trust.status_of(state)
            rung = self._ladder.update(rid, status.state if status else None, now)
            if rung is not None:
                self._report_rung(rid, rung)

    # --- steps ----------------------------------------------------------------------

    async def _arbitrate(self, rid: str, client: RobotClient, localized: Mapping[str, cues.Pose],
                         observations: dict, now: float) -> None:
        try:
            report = await client.localization_candidates()
        except Exception as exc:
            logger.debug("localization: %s candidates unreadable: %s", rid, exc)
            return
        if report is None:
            return
        if report.robot_id != rid:
            logger.warning("localization: %s reported candidates for %s; ignored", rid, report.robot_id)
            return
        peers = {o: p for o, p in localized.items() if o != rid}
        context = Context(peers=[p[:2] for p in peers.values()], slots=self._slots,
                          squares=self._squares, last_good=self._last_good.get(rid),
                          sighting=self._sighting(rid, now))
        # The monitor places this robot's unmapped objects from its leading candidate,
        # chosen without the peers cue: a mislocated peer must not pick the observer's pose.
        leader = service_logic.clear_leader(
            report, Context(slots=self._slots, squares=self._squares,
                            last_good=context.last_good, sighting=context.sighting), now)
        if leader is not None:
            for peer, seen in service_logic.peer_observations(report, leader, peers).items():
                observations.setdefault(peer, []).append(seen)
        decision = self._arbiter.observe(report, context, now)
        if decision is not None:
            await self._post_decision(rid, client, decision)

    async def _post_decision(self, rid: str, client: RobotClient,
                             decision: LocalizationDecision) -> None:
        record = {"request_id": decision.request_id, "candidate_index": decision.candidate_index,
                  "cues": [c.value for c in decision.cues], "result": "sent"}
        try:
            await client.localization_decision(decision)
            logger.info("localization: %s decision %s candidate %s cues %s", rid,
                        decision.request_id, decision.candidate_index, record["cues"])
        except RobotApiError as exc:
            record["result"] = exc.code
            logger.info("localization: %s refused decision %s: %s", rid, decision.request_id, exc.code)
        except Exception as exc:
            record["result"] = "unreachable"
            logger.warning("localization: decision %s to %s failed: %s", decision.request_id, rid, exc)
        self._last_decision[rid] = record

    async def _watch(self, localized: Mapping[str, cues.Pose], observations: Mapping[str, list],
               now: float) -> None:
        for rid in list(self._known):
            if rid not in localized:
                self._monitor.forget(rid)
        for rid, pose in localized.items():
            seen = list(observations.get(rid, ()))
            sighting = self._sighting(rid, now)
            if sighting is not None:
                seen.append((sighting.x, sighting.y, sighting.yaw))
            disagreeing = any(service_logic.disagrees(pose, o) for o in seen) if seen else None
            if self._monitor.update(rid, disagreeing, now):
                await self._post_suspect(rid)

    async def _post_suspect(self, rid: str) -> None:
        client = self._clients().get(rid)
        if client is None:
            return
        logger.warning("localization: %s observed > %.2f m / %.0f deg off for %.1f s; suspect",
                       rid, service_logic.SUSPECT_DIST_M, math.degrees(service_logic.SUSPECT_YAW_RAD),
                       service_logic.SUSPECT_HOLD_S)
        try:
            await client.localization_suspect(service_logic.SUSPECT_REASON)
        except Exception as exc:
            logger.warning("localization: suspect to %s failed: %s", rid, exc)

    def _report_rung(self, rid: str, rung: str) -> None:
        missions = service_logic.RUNG_MISSIONS[rung]
        if missions:
            logger.info("localization: %s ladder %s: would request %s (pending P2-7, not sent)",
                        rid, rung, " / ".join(missions))
        else:
            logger.warning("localization: %s still unlocalized after %.0f s: needs_human (위치 확인 필요)",
                           rid, self._ladder.human_s)

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
        self._known = current
