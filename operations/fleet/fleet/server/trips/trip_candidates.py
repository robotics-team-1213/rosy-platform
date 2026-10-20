"""Candidate admission reuses the trip owner; only a definite busy refusal can fail over."""
import asyncio
import hashlib

from core_common.protocol.schemas import TripJobRequest
from fleet.server.mission_store import MissionConflict, _json
from fleet.server.trip_job_routes import create_trip_job
from fleet.server.trip_ports import TripError


async def create_candidate_trip_job(jobs, candidates, steps, principal_id, request_key, *, validate=None):
    body = TripJobRequest(candidate_robot_ids=candidates, steps=steps, request_key=request_key)
    steps = [step.model_dump(mode="json") for step in body.steps]
    digest = hashlib.sha256(_json({"candidates": body.candidate_robot_ids, "steps": steps}).encode()).hexdigest()
    key = "trip-pool:" + body.request_key
    async with jobs.candidate_lock:
        old = await asyncio.to_thread(jobs.rows.find_request, principal_id, key, digest)
        if old is not None:
            return old
        if validate is not None:
            validate()
        for robot_id in body.candidate_robot_ids:
            try:
                return await create_trip_job(jobs, robot_id, steps, principal_id,
                                             request_key=key, request_digest=digest)
            except TripError as exc:
                if exc.code != "TRIP_ROBOT_BUSY":
                    raise
            except MissionConflict:
                # Another Fleet connection may have committed this request while its lease opened.
                old = await asyncio.to_thread(jobs.rows.find_request, principal_id, key, digest)
                if old is not None:
                    return old
                raise
        raise TripError(409, "TRIP_CANDIDATES_BUSY", {"candidate_robot_ids": body.candidate_robot_ids})
