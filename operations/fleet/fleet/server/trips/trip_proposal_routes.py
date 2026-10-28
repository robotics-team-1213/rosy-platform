"""D-908: simulation-only neutral trip proposal/read/admit HTTP. A proposal claims nothing; admission makes the
same TRIP step-ledger job as ``POST /api/fleet/trip-jobs``, approved by an operator other than the proposer."""
import asyncio
import sqlite3

from fastapi import Depends, HTTPException, Path, Request

from core_common.protocol.schemas import TripProposalAdmit, TripProposalCreate, TripProposalResponse, TripRequestKey
from fleet.server.mission_store import MissionConflict
from fleet.server.password_session import same_origin
from fleet.server.trip_candidates import create_candidate_trip_job
from fleet.server.trip_ports import TripError
from fleet.server.trip_proposals import TripProposalStore

PATH = "/api/fleet/trip-proposals"


def install_trip_proposal_routes(app, *, cell_job_store, jobs, check, require_proposer, require_viewer,
                                 require_named_operator):
    """``jobs`` is None outside the simulation profile: every route then answers 503 like the ARM routes."""
    store = TripProposalStore(cell_job_store) if jobs is not None and cell_job_store is not None else None
    app.state.trip_proposal_store = store

    async def call(function):
        if store is None:
            raise HTTPException(503, detail={"code": "TRIP_PROPOSAL_UNAVAILABLE"})
        try:
            return TripProposalResponse.model_validate({"proposal": await function()})
        except KeyError:
            raise HTTPException(404, detail={"code": "TRIP_PROPOSAL_NOT_FOUND"}) from None
        except PermissionError:
            raise HTTPException(403, detail={"code": "TRIP_PROPOSAL_FORBIDDEN"}) from None
        except MissionConflict:
            raise HTTPException(409, detail={"code": "TRIP_PROPOSAL_CONFLICT"}) from None
        except TripError as exc:
            raise HTTPException(exc.status, detail={"code": exc.code, "detail": exc.detail}) from exc
        except (OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, detail={"code": "TRIP_PROPOSAL_UNAVAILABLE"}) from None

    def write_origin(request: Request):
        if request.headers.get("origin") is not None and not same_origin(request):
            raise HTTPException(403, detail={"code": "TRIP_PROPOSAL_FORBIDDEN"})

    @app.post(PATH, response_model=TripProposalResponse, tags=["fleet-work"], dependencies=[Depends(write_origin)])
    async def create(body: TripProposalCreate, principal=Depends(require_proposer)):
        async def run():
            check(body.candidate_robot_ids, [step.model_dump(mode="json") for step in body.steps])
            steps = [step.model_dump(mode="json") for step in body.steps]
            return await asyncio.to_thread(store.create, principal.principal_id, body.request_key,
                                           body.candidate_robot_ids, steps)
        return await call(run)

    @app.get(PATH, response_model=TripProposalResponse, tags=["fleet-work"])
    async def read_key(request_key: TripRequestKey, principal=Depends(require_viewer)):
        async def run():
            found = await asyncio.to_thread(store.get, principal_id=principal.principal_id, request_key=request_key)
            if found is None:
                raise KeyError(request_key)
            return found
        return await call(run)

    @app.get(PATH + "/{proposal_id}", response_model=TripProposalResponse, tags=["fleet-work"])
    async def read_id(proposal_id: str = Path(min_length=1, max_length=64), principal=Depends(require_viewer)):
        async def run():
            found = await asyncio.to_thread(store.get, proposal_id=proposal_id)
            if found is None:
                raise KeyError(proposal_id)
            if found["proposal_principal_id"] != principal.principal_id and not (
                    principal.role == "operator" and principal.permits_site("fleet.operate", {"operator"})):
                raise PermissionError("only the creator or a named operator may read a proposal")
            return found
        return await call(run)

    @app.post(PATH + "/{proposal_id}/admit", response_model=TripProposalResponse, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def admit(body: TripProposalAdmit, proposal_id: str = Path(min_length=1, max_length=64),
                    principal=Depends(require_named_operator)):
        async def run():
            found = await asyncio.to_thread(store.get, proposal_id=proposal_id)
            if found is None:
                raise KeyError(proposal_id)
            if found["proposal_principal_id"] == principal.principal_id:
                raise PermissionError("the proposer cannot admit its own trip")
            if found["proposal_digest"] != body.expected_proposal_digest:
                raise MissionConflict("trip proposal changed")
            if found["status"] == "ADMITTED":  # a retry after a lost response: the same record, no second job
                return found
            generation = await asyncio.to_thread(store.dispatch_generation)
            if generation is None or generation != body.expected_generation:
                raise MissionConflict("dispatch generation is closed or changed")
            job = await create_candidate_trip_job(
                jobs, found["candidate_robot_ids"], found["steps"], found["proposal_principal_id"],
                found["request_key"], validate=lambda: check(found["candidate_robot_ids"], found["steps"]),
                approved_by=principal.principal_id)
            return await asyncio.to_thread(store.admitted, proposal_id, approver=principal.principal_id,
                                           generation=generation, mission_id=job["mission_id"])
        return await call(run)
