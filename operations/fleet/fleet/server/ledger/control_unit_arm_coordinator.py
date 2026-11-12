"""Cell-local ARM job binding, admission parent check, and projection for control-unit delegations (D-965)."""

from hashlib import sha256
from time import monotonic

from core_common.protocol.control_units import ControlArmTransferCandidate
from fleet.server.control_unit_store import TERMINAL

# ARM job status -> delegation state; the cell's own ARM admit moves PROPOSED onward (D-965).
ARM_STATES = {"PROPOSED": "QUEUED", "READY": "ACCEPTED", "RUNNING": "RUNNING",
              "ACTION_SUCCEEDED": "RUNNING", "GOAL_CONFIRMED": "COMPLETED", "HOLD": "HOLD"}


def is_arm_request(request):
    return isinstance(request, ControlArmTransferCandidate) or (isinstance(request, dict) and "transfer" in request)


class ControlUnitArmCoordinator:
    def __init__(self, service):
        self._service = service

    @staticmethod
    def _key(row):
        return row["origin_id"], row["delegation_id"]

    def propose_arm(self, row, principal):
        """The direct parent's service principal proposes; only the cell's ARM admit approves."""
        jobs = self._service.arm_jobs()
        if jobs is None:
            raise ValueError("CONTROL_UNIT_ARM_JOBS_UNAVAILABLE")
        transfer = dict(row["request"]["transfer"])
        transfer.pop("request_key")
        key = self._key(row)
        request_key = "control:" + sha256("\0".join(key).encode()).hexdigest()
        try:
            jobs.create(principal=principal, request_key=request_key, request=transfer,
                        bind=lambda connection, identity: self._service.store.bind_local(
                            *key, identity, connection=connection))
        except PermissionError:
            raise ValueError("CONTROL_UNIT_ARM_PROPOSAL_FORBIDDEN") from None
        return self._service.store.get(*key)

    async def check_arm_admission(self, mission_id, *, clock=monotonic):
        rows = self._service.store.for_local_task(mission_id)
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("CONTROL_UNIT_AMBIGUOUS_ARM_BINDING")
        row = rows[0]
        if (not is_arm_request(row["request"]) or row["owner_unit"] != self._service.unit.unit_id
                or row["config_revision"] != self._service.topology.revision or row["cancel_requested"]
                or row["status"] in TERMINAL):
            raise ValueError("CONTROL_UNIT_ARM_ADMISSION_REFUSED")
        await self._service._parent_current(row)
        return clock()

    async def arm_detail(self, origin, identity, kind, *, key=None, principal_id=None):
        """D-965: evidence or a recheck of the ARM job this cell bound to the delegation; never a new action."""
        row = self._service.store.get(origin, identity)
        if (row["owner_unit"] != self._service.unit.unit_id
                or not is_arm_request(row["request"]) or not row["local_task_id"]):
            raise ValueError("CONTROL_UNIT_ARM_JOB_NOT_BOUND")
        jobs = self._service.arm_jobs()
        if jobs is None:
            raise ConnectionError("CONTROL_UNIT_ARM_JOBS_UNAVAILABLE")
        mission = row["local_task_id"]
        if kind == "evidence":
            return jobs.evidence(mission)
        if kind == "request_recheck":
            return jobs.request_recheck(mission, key, principal_id=principal_id)
        return jobs.read_recheck(mission, key)

    def cancel_local_arm(self, row, *, jobs, job):
        if job["status"] == "PROPOSED":
            # Withdrawn to HOLD; the ARM admit also refuses a canceled delegation, so it can never run.
            jobs.cancel(job["mission_id"], reason=row.get("cancel_reason") or "control-unit-cancel")
            return True, self._service._local_result(
                row, "CANCELED", {"job": jobs.view(row["local_task_id"]), "receipt": None})
        if not row["result"].get("cancel_sent"):
            jobs.cancel(job["mission_id"], reason=row.get("cancel_reason") or "control-unit-cancel")
            job = jobs.view(row["local_task_id"])
        return False, job

    def project_local_arm(self, row):
        jobs = self._service.arm_jobs()
        job = None if jobs is None else jobs.view(row["local_task_id"])
        if job is None:
            raise ValueError("CONTROL_UNIT_BOUND_ARM_JOB_MISSING")
        if row["cancel_requested"]:
            done, outcome = self.cancel_local_arm(row, jobs=jobs, job=job)
            if done:
                return outcome
            job = outcome
        # The origin app reads job and receipt only through this projection (D-965); cancel_sent is not a stop.
        result = {"job": job, "receipt": jobs.receipt(job["mission_id"])}
        if row["cancel_requested"]:
            result["cancel_sent"] = True
        return self._service._local_result(row, ARM_STATES[job["status"]], result)
