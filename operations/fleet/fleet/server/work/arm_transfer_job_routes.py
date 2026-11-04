"""Installed simulation or device_trial proposal/admission HTTP; no claim release (D-977)."""
import asyncio
import logging
import sqlite3
import time

from fastapi import Depends, HTTPException, Request

from core_common.protocol.arm_transfer import ArmActionId, ArmTransferCapability
from core_common.protocol.arm_transfer_jobs import (
    ArmTransferRequest, ArmTransferRequestKey, ArmTransferJobCreate, ArmTransferJobAdmit, ArmTransferJobResponse,
)
from .local_action_transport import LocalActionUnavailable, UnixLocalActionTransport
from .mission_store import MissionConflict
from .physical_transfer_attestations import PhysicalOperatorAttestations
from .physical_transfer_store import ARM_TRANSFER_PROFILES, PhysicalTransferStore
from .password_session import same_origin


_log = logging.getLogger("fleet.arm_transfer_policy_admission")


def _view(job):
    fields = ("mission_id", "proposal_principal_id", "request_key", "request_digest", "proposal_digest",
              "status", "authority_epoch", "dispatch_generation", "approved_by", "reason")
    return {"job": {**{key: job[key] for key in fields}, "action_kind": "ARM_TRANSFER",
                    "transfer": job["request"],
                    "resource_policy_digest": job["installation"]["capabilities"][0]["resource_policy_digest"],
                    "delegated_by": job.get("delegated_by")}}


class DelegatedArmJobs:
    """In-process ARM owner calls for a control-unit delegation bound to one job (D-965); no HTTP caller."""

    def __init__(self, store, observation):
        self.store, self.observation = store, observation

    def create(self, *, principal, request_key, request, bind=None):
        return self.store.create(principal=principal, request_key=request_key, request=request, bind=bind)

    def view(self, mission_id):
        job = self.store.peek(mission_id)
        return None if job is None else _view(job)["job"]

    def receipt(self, mission_id):
        return None if self.observation is None else self.observation.receipt(mission_id)

    def _observed(self):
        if self.observation is None:
            raise ConnectionError("ARM transfer observer is not installed")
        return self.observation

    def evidence(self, mission_id):
        result = self._observed().evidence(mission_id)
        if result is None:
            raise ValueError("ARM_TRANSFER_PHYSICAL_EVIDENCE_UNAVAILABLE")
        return result

    def request_recheck(self, mission_id, recheck_key, *, principal_id):
        return self._recheck(lambda: self._observed().rechecks.request(mission_id, recheck_key, principal_id=principal_id))

    def read_recheck(self, mission_id, recheck_key):
        return self._recheck(lambda: self._observed().rechecks.read(mission_id, recheck_key))

    @staticmethod
    def _recheck(function):
        try:
            return {"recheck": function()}
        except MissionConflict:
            raise ValueError("ARM_TRANSFER_RECHECK_CONFLICT") from None

    def cancel(self, mission_id, *, reason):
        """Withdraw an unadmitted proposal; cancel a prepared attempt through the existing dispatcher."""
        if self.store.peek(mission_id)["status"] == "PROPOSED":
            self.store.withdraw(mission_id, reason=reason)
            return
        if self.observation is None:
            return
        try:
            self.observation.execution.snapshot(mission_id)
        except KeyError:
            return
        self.observation.dispatcher.cancel(mission_id, reason=reason)


def install_arm_transfer_job_routes(app, *, installation, deployment_profile, task_store, transport,
                                    socket_root, require_proposer, require_viewer, require_named_operator,
                                    observer, console, principals, other_tokens, other_services, registries,
                                    policy_admission_core=None, grant_revisions=None):
    store = reader = None
    commissioning = {}
    if installation is not None:
        if deployment_profile not in ARM_TRANSFER_PROFILES:
            raise ValueError("ARM transfer HTTP requires the simulation or device_trial profile")
        if task_store is None:
            raise ValueError("ARM transfer HTTP requires the shared Mission and API audit journal")
        reader = transport if transport is not None else UnixLocalActionTransport(socket_root)
        if not callable(getattr(reader, "transfer_capability", None)):
            raise ValueError("ARM transfer HTTP requires a capability SDK reader")
        store = PhysicalTransferStore(task_store.path, installation=installation, deployment_profile=deployment_profile)
        if deployment_profile == "device_trial":
            # D-977 2: one arm only; the owner must also match its configured commissioning revision (D-797 3).
            if len(store.installation.policy.participants) != 1:
                raise ValueError("device_trial ARM transfer HTTP opens a single arm only")
            commissioning = {p.instance_id: (grant_revisions or {}).get(p.instance_id, {}).get("commissioning_revision")
                             for p in store.installation.policy.participants}
            if any(not isinstance(v, str) or not v for v in commissioning.values()):
                raise ValueError("device_trial ARM transfer HTTP requires a commissioning_revision for its arm")
    app.state.arm_transfer_job_store = store
    from .physical_transfer_observer import PhysicalObservationService, validate_observer
    from .physical_transfer_observer_routes import install_physical_observer_routes
    from .physical_transfer_execution import PhysicalTransferExecution
    from .physical_transfer_dispatcher import PhysicalTransferDispatcher
    dispatcher = service = None
    if observer is not None:
        validate_observer(observer, None if store is None else store.installation, console=console,
            principals=principals, other_tokens=other_tokens, other_services=other_services, registries=registries)
        dispatcher = PhysicalTransferDispatcher(PhysicalTransferExecution(store), reader, task_store,
                                               deployment_profile=deployment_profile,
                                               commissioning_revisions=commissioning)
        service = PhysicalObservationService(dispatcher, observer)
    app.state.arm_transfer_dispatcher = dispatcher
    app.state.arm_transfer_delegate = None if store is None else DelegatedArmJobs(store, service)
    control = getattr(app.state, "control_unit", None)

    async def check_parent(mission_id):
        current = getattr(app.state, "control_unit", None)
        return None if current is None else await current.check_arm_admission(mission_id)

    if store is None and control is not None:
        from .arm_transfer_relay_routes import install_arm_transfer_relay_routes
        install_arm_transfer_relay_routes(app, control=control, require_viewer=require_viewer,
                                          require_proposer=require_proposer)
        return

    def read_capabilities():
        """Fresh participant capabilities for an admit; the human and policy admits share this read."""
        observed_at = time.time_ns()
        capabilities = []
        for participant in store.installation.policy.participants:
            cap = ArmTransferCapability.model_validate(reader.transfer_capability(
                participant.instance_id, workcell_id=participant.workcell_id))
            if (cap.workcell_id, cap.instance_id) != (participant.workcell_id, participant.instance_id):
                raise LocalActionUnavailable("capability targets a different participant")
            capabilities.append(cap)
        return tuple(capabilities), observed_at

    audit_log = getattr(policy_admission_core, "audit_log", None)
    # D-977: a real arm is approved only by a named operator at the cell; the unattended policy worker stays simulation-only.
    if store is not None and audit_log is not None and deployment_profile == "simulation":
        from .arm_transfer_policy_admission import ArmTransferPolicyWorker, arm_transfer_policy_loop
        worker = ArmTransferPolicyWorker(core=policy_admission_core, store=store, read_capabilities=read_capabilities,
                                         dispatcher=dispatcher, audit_log=audit_log, log=_log)

        @app.on_event("startup")
        async def arm_transfer_policy_start():
            app.state.arm_transfer_policy_task = asyncio.create_task(
                arm_transfer_policy_loop(worker, _log, before_admit=check_parent))

        @app.on_event("shutdown")
        async def arm_transfer_policy_stop():
            task = getattr(app.state, "arm_transfer_policy_task", None)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def installed_store():
        if store is None:
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_JOB_UNAVAILABLE"})
        return store

    async def call(function, *, parent_mission_id=None):
        try:
            if parent_mission_id is None:
                result = await asyncio.to_thread(function)
            else:
                checked_at = await check_parent(parent_mission_id)
                result = await asyncio.to_thread(function, checked_at)
            return ArmTransferJobResponse.model_validate(result)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_TRANSFER_JOB_NOT_FOUND"}) from None
        except PermissionError:
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"}) from None
        except MissionConflict:
            raise HTTPException(409, detail={"code": "ARM_TRANSFER_JOB_CONFLICT"}) from None
        except (LocalActionUnavailable, OSError, sqlite3.Error, ValueError):
            raise HTTPException(503, detail={"code": "ARM_TRANSFER_JOB_UNAVAILABLE"}) from None

    path = "/api/fleet/arm-transfers/jobs"

    def write_origin(request: Request):
        if request.headers.get("origin") is not None and not same_origin(request):
            raise HTTPException(403, detail={"code": "ARM_TRANSFER_JOB_FORBIDDEN"})

    observer_auth = install_physical_observer_routes(app, service=service, task_store=task_store, job_view=_view,
        require_viewer=require_viewer, require_proposer=require_proposer, write_origin=write_origin)
    from .physical_transfer_recovery_routes import install_transfer_recovery_routes
    install_transfer_recovery_routes(app, dispatcher=dispatcher, principals=principals, observer_auth=observer_auth,
        job_view=_view, require_viewer=require_viewer, require_proposer=require_proposer,
        require_named_operator=require_named_operator, write_origin=write_origin)

    if store is not None and deployment_profile == "device_trial":
        from .physical_transfer_attestation_routes import install_operator_attestation_routes
        install_operator_attestation_routes(app, attestations=PhysicalOperatorAttestations(store),
            require_viewer=require_viewer, require_named_operator=require_named_operator, write_origin=write_origin,
            store=store)

    @app.post(path, response_model=ArmTransferJobResponse, tags=["fleet-work"], dependencies=[Depends(write_origin)])
    async def create(body: ArmTransferJobCreate, principal=Depends(require_proposer)):
        rows = installed_store()
        request = ArmTransferRequest.model_validate(body.model_dump(exclude={"request_key"}))
        return await call(lambda: _view(rows.create(principal=principal, request_key=body.request_key, request=request)))

    @app.get(path, response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_key(request_key: ArmTransferRequestKey, principal=Depends(require_viewer)):
        rows = installed_store()
        def read():
            job = rows.get_by_request_key(request_key, principal=principal)
            if job is None:
                raise KeyError(request_key)
            return _view(job)
        return await call(read)

    @app.get(path + "/{mission_id}", response_model=ArmTransferJobResponse, tags=["fleet-work"])
    async def read_id(mission_id: ArmActionId, principal=Depends(require_viewer)):
        rows = installed_store()
        def read():
            job = rows.get(mission_id, principal=principal)
            if job is None:
                raise KeyError(mission_id)
            return _view(job)
        return await call(read)

    @app.post(path + "/{mission_id}/admit", response_model=ArmTransferJobResponse, tags=["fleet-work"],
              dependencies=[Depends(write_origin)])
    async def admit(mission_id: ArmActionId, body: ArmTransferJobAdmit, principal=Depends(require_named_operator)):
        rows = installed_store()
        def approve(checked_at):
            job = rows.get(mission_id, principal=principal)
            if job is None:
                raise KeyError(mission_id)
            if job["proposal_principal_id"] == principal.principal_id:
                raise PermissionError("proposer cannot approve itself")
            capabilities, observed_at = read_capabilities()
            job = rows.admit(mission_id, principal=principal,
                expected_proposal_digest=body.expected_proposal_digest, expected_generation=body.expected_generation,
                capabilities=capabilities, capabilities_observed_at_ns=observed_at,
                delegation_checked_at=checked_at)
            if dispatcher is not None and job["status"] == "READY":
                dispatcher.prepare(mission_id)
                job = rows.get(mission_id, principal=principal)
            return _view(job)
        return await call(approve, parent_mission_id=mission_id)
