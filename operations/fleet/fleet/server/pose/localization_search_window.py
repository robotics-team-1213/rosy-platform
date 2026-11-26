"""Suggest a center for a missing native candidate search, never an injection."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Mapping

from core_common.protocol.localization import CandidateReport

from fleet.localization import cues, relative_search_prior as evidence, trust

LOG = logging.getLogger("fleet.localization")
REPORT_AGE_S = 5.0
ATTEMPT_INTERVAL_S = 2.0
ATTEMPTS_PER_RECOVERY = 2


@dataclass(frozen=True)
class NativeCandidatePrior:
    scope: tuple[tuple[str, str], int]
    observed: float
    odom: tuple[float, float, float]
    odom_epoch: int
    report: CandidateReport


class SearchWindowAdvisor:
    def __init__(self):
        self.read_reference = None
        self._reports = {}
        self._attempts = {}
        self.operator_anchors = {}

    def forget(self, robot_id):
        self._reports.pop(robot_id, None)
        self._attempts.pop(robot_id, None)

    def has_prior(self, robot_id, now):
        prior = self._reports.get(robot_id)
        if self.read_reference is None or prior is None or not 0 <= now - prior.observed <= REPORT_AGE_S:
            return False
        last_scope, last_at, count, accepted = self._attempts.get(robot_id, (None, -math.inf, 0, False))
        return (now - last_at >= ATTEMPT_INTERVAL_S
                and (last_scope != prior.scope or (not accepted and count < ATTEMPTS_PER_RECOVERY)))

    def observe_report(self, robot_id, frame, state, report, now):
        odom = evidence.fresh_odom(state, 0.)
        prior = self._reports.get(robot_id)
        scope = (frame, state.get("map_generation"))
        if report.pickup:
            self._reports.pop(robot_id, None)
            return
        status = trust.status_of(state)
        if (status is None or status.request_id != report.request_id
                or frame is None or type(scope[1]) is not int or odom is None
                or not evidence.stationary(state, 0.) or not evidence.fresh_native_stamp(state, report.stamp, REPORT_AGE_S)):
            self._reports.pop(robot_id, None)
            return
        if (prior is None or prior.scope != scope
                or (prior.report.request_id, prior.report.stamp) != (report.request_id, report.stamp)):
            self._reports[robot_id] = NativeCandidatePrior(scope, now, *odom, report)

    async def consider(self, svc, rid, client, frame, state, frames, anchors, now):
        prior = self._reports.get(rid)
        if (svc._sightings is None or frame is None or self.read_reference is None or prior is None
                or (frame, state.get("map_generation")) != prior.scope
                or not 0 <= now - prior.observed <= REPORT_AGE_S):
            return
        try:
            target = await svc._bounded(self.read_reference(rid))
            state = target.state
        except Exception:
            return
        status = trust.status_of(state)
        age = svc._clock() - target.started_mono
        if (status is None or status.state not in (trust.LocState.SUSPECT, trust.LocState.UNKNOWN)
                or state.get("mode") != "IDLE" or not evidence.stationary(state, age)
                or not evidence.fresh_native_stamp(state, prior.report.stamp, REPORT_AGE_S - age)
                or ((state.get("map_id"), state.get("map_grid_id")), state.get("map_generation")) != prior.scope):
            return
        odom = evidence.fresh_odom(state, age)
        if odom is None:
            return
        pose, epoch = odom
        if (epoch != prior.odom_epoch or math.dist(pose[:2], prior.odom[:2]) > .02
                or abs(cues.wrap(pose[2] - prior.odom[2])) > .08):
            return

        active_map = svc._current_active_map_id()
        if not active_map:
            return
        image = evidence.synchronous_markers(svc._sightings.snapshot().get("sightings", ()), rid, active_map, svc._wall())
        if image is None:
            return
        _, markers, _, _ = image
        if rid not in markers:
            return
        fit = svc._binding_fit_for_state(rid, state, expected_site_map=active_map)
        references = {}
        if fit is not None:
            center = (*fit.inverse(markers[rid][:2]), cues.wrap(markers[rid][2] - fit.yaw))
        else:
            peer_ids = [key for key in anchors if key in self.operator_anchors and frames.get(key) == frame and key in markers]
            if len(peer_ids) != 2:
                return
            receipts = await asyncio.gather(*(svc._bounded(self.read_reference(p)) for p in peer_ids), return_exceptions=True)
            refs = []
            for peer_id, receipt in zip(peer_ids, receipts):
                if isinstance(receipt, BaseException):
                    return
                peer_state = receipt.state
                native = evidence.fresh_reference(peer_state, svc._clock() - receipt.started_mono)
                if native is None:
                    return
                scope = ((peer_state.get("map_id"), peer_state.get("map_grid_id")), peer_state.get("map_generation"))
                if type(scope[1]) is not int or scope != self.operator_anchors.get(peer_id):
                    return
                references[peer_id] = (scope, receipt)
                refs.append((markers[peer_id], native))
            center = evidence.relative_center(markers[rid], refs)
            if center is None:
                center = evidence.short_baseline_center(markers[rid], refs, prior.report)
        if center is None or not evidence.supports_heading(center, prior.report):
            return
        await self._submit(svc, rid, client, prior, center, now, active_map, image, target, references, fit)

    async def _submit(self, svc, robot_id, client, prior, center, now, active_map, image, target, references, fit):
        scope = prior.scope
        last_key, last_at, count, accepted = self._attempts.get(robot_id, (None, -math.inf, 0, False))
        if now - last_at < ATTEMPT_INTERVAL_S or (scope == last_key and (accepted or count >= ATTEMPTS_PER_RECOVERY)):
            return
        count = count + 1 if scope == last_key else 1
        self._attempts[robot_id] = (scope, now, count, False)
        try:
            caps = await svc._bounded(client.capabilities())
            captured_at, _, source_id, revision = image
            current = svc._clock()
            age = current - target.started_mono
            if ((caps.get("localization") or {}).get("search_window") is not True
                    or svc._current_active_map_id() != active_map
                    or svc._sightings.approved_sighting_revision(source_id, active_map) != revision
                    or (fit is not None and svc._binding_fit_for_state(
                        robot_id, target.state, expected_site_map=active_map) != fit)
                    or not 0 <= svc._wall() - captured_at <= evidence.MAX_FRAME_AGE_S
                    or not evidence.stationary(target.state, age)
                    or evidence.fresh_odom(target.state, age) is None
                    or not evidence.fresh_native_stamp(target.state, prior.report.stamp, REPORT_AGE_S - age)
                    or any(self.operator_anchors.get(rid) != anchor_scope
                           or evidence.fresh_reference(receipt.state, current - receipt.started_mono) is None
                           for rid, (anchor_scope, receipt) in references.items())):
                return
            result = await svc._bounded(client.localization_search_window(scope[0][1], center))
        except Exception as exc:
            LOG.debug("localization: %s search window unavailable: %s", robot_id, type(exc).__name__)
            return
        if isinstance(result, Mapping) and result.get("accepted") is True:
            self._attempts[robot_id] = (scope, now, count, True)
            LOG.info("localization: %s native search window accepted", robot_id)
