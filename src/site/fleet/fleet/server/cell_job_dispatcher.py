"""Fleet dispatch and exact-attempt readback for admitted ordered Cell transfers."""

from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Callable, Mapping

from core_common.protocol.schemas import FleetCellTransferGrant

from .cell_job_store import CellJobStore, cell_transfer_grant_digest
from .local_action_transport import DeviceActionTransport, LocalActionRejected
from .mission_store import MissionConflict
from .task_store import FleetTaskStore


class CellJobDispatcher:
    """Persist one grant before send; never re-submit an unresolved transfer."""

    def __init__(self, store: CellJobStore, tasks: FleetTaskStore,
                 transport: DeviceActionTransport, instances: Mapping[str, str], *,
                 config_revisions: Mapping[str, str], grant_ttl_s: float = 15.0,
                 now: Callable[[], datetime] | None = None) -> None:
        if not instances or len(set(instances.values())) != len(instances):
            raise ValueError("Cell dispatcher requires distinct configured OMX instances")
        if set(config_revisions) != set(instances) or any(
                not isinstance(value, str) or not value.strip() or value != value.strip()
                or len(value) > 128 for value in config_revisions.values()):
            raise ValueError("Cell dispatcher requires a pinned config revision for every workcell")
        if (isinstance(grant_ttl_s, bool) or not isinstance(grant_ttl_s, (int, float))
                or not 1 <= grant_ttl_s <= 60):
            raise ValueError("Action grant TTL must be between 1 and 60 seconds")
        if store.path.resolve() != tasks.path.resolve():
            raise ValueError("Cell journal and dispatch control must share the same database")
        self.store, self.tasks, self.transport = store, tasks, transport
        self.instances, self.config_revisions = dict(instances), dict(config_revisions)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.grant_ttl_s = float(grant_ttl_s)
        self.last_mission = None
        self.store.recover_after_startup()

    def dispatch_next(self) -> dict[str, Any] | None:
        jobs = self.store.dispatch_candidates()
        if not jobs:
            return None
        prior = next((index for index, job in enumerate(jobs)
                      if job["mission_id"] == self.last_mission), -1)
        job = jobs[(prior + 1) % len(jobs)]
        self.last_mission = job["mission_id"]
        if self.instances.get(job["workcell_id"]) != job["instance_id"]:
            return {"mission_id": job["mission_id"], "state": "NOT_CONFIGURED"}
        if job["status"] != "READY":
            return self._reconcile(job)
        try:
            grant = self._grant(job)
            self.store.start_step(job["mission_id"], step_index=job["current_step_index"],
                                  action_id=grant.action_id, attempt_id=grant.attempt_id,
                                  grant=grant.model_dump(mode="json"))
        except MissionConflict as exc:
            self.store.recover_after_startup()
            return {"mission_id": job["mission_id"], "state": self.store.get(job["mission_id"])["status"],
                    "reason": str(exc)}
        except (KeyError, TypeError, ValueError):
            return {"mission_id": job["mission_id"], "state": "GRANT_INVALID"}
        control = self.tasks.dispatch_control()
        if (not control["dispatch_enabled"] or control["authority_epoch"] != grant.authority_epoch
                or control["generation"] != grant.dispatch_generation):
            return self._unknown(grant, "FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT")
        try:
            return self._apply(grant, self.transport.submit(grant))
        except LocalActionRejected:
            return self._unknown(grant, "LOCAL_ACTION_REJECTED", outcome="FAILED")
        except Exception:
            return self._unknown(grant, "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN")

    def _grant(self, job) -> FleetCellTransferGrant:
        step = job["steps"][job["current_step_index"]]
        inputs = step["step"]["inputs"]
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Fleet clock must return timezone-aware time")

        def pose(value):
            return {"x": value["x_m"], "y": value["y_m"], "z": value["z_m"], "yaw": value["yaw_rad"]}

        document = {
            "mission_id": job["mission_id"], "step_id": step["step_id"],
            "action_id": str(uuid.uuid4()), "attempt_id": str(uuid.uuid4()), "request_digest": "0" * 64,
            "workcell_id": job["workcell_id"], "instance_id": job["instance_id"], "action_kind": "CELL_TRANSFER",
            "capability_revision": "cell-transfer-v1", "config_revision": self.config_revisions[job["workcell_id"]],
            "authority_epoch": job["authority_epoch"], "dispatch_generation": job["dispatch_generation"],
            "issued_at": now, "expires_at": now + timedelta(seconds=self.grant_ttl_s),
            "cell_transfer": {
                "job_id": job["job_id"], "recipe_sha256": job["recipe_digest"], "cell_sha256": job["cell_digest"],
                "step_index": job["current_step_index"], "item": inputs["item"], "pallet": inputs["pallet_id"],
                "layer": inputs["layer_index"], "frame": "robot_base",
                "home": pose(inputs["home_pose_base"]), "pick": pose(inputs["source_pose_base"]),
                "place": pose(inputs["destination_pose_base"]),
                "pick_approach_z": inputs["source_approach_z_base_m"],
                "place_approach_z": inputs["destination_approach_z_base_m"], "carry_z": inputs["carry_z_base_m"],
            },
        }
        document["request_digest"] = cell_transfer_grant_digest(document)
        return FleetCellTransferGrant.model_validate(document)

    def _stored_grant(self, job):
        step = job["steps"][job["current_step_index"]]
        grant = FleetCellTransferGrant.model_validate(step["grant"])
        if (grant.mission_id != job["mission_id"] or grant.step_id != step["step_id"]
                or grant.action_id != step["action_id"] or grant.attempt_id != step["attempt_id"]
                or grant.instance_id != job["instance_id"] or grant.workcell_id != job["workcell_id"]
                or grant.authority_epoch != job["authority_epoch"]
                or grant.dispatch_generation != job["dispatch_generation"]
                or grant.request_digest != step["request_digest"]
                or cell_transfer_grant_digest(step["grant"]) != grant.request_digest):
            raise MissionConflict("persisted Cell grant conflicts with its transfer attempt")
        return grant

    def _reconcile(self, job):
        try:
            grant = self._stored_grant(job)
        except (KeyError, TypeError, ValueError):
            step = job["steps"][job["current_step_index"]]
            row = self.store.record_action_result(
                job["mission_id"], step_index=job["current_step_index"],
                action_id=step["action_id"], attempt_id=step["attempt_id"],
                event_id=f"invalid-grant:{step['step_index']}:{step['attempt_id']}",
                outcome="UNKNOWN", result={"reason": "PERSISTED_GRANT_INVALID"},
            )
            return {"mission_id": job["mission_id"], "state": row["status"],
                    "reason": "PERSISTED_GRANT_INVALID"}
        try:
            receipt = self.transport.get(grant)
            if receipt is None:
                return self._unknown(grant, "LOCAL_ACTION_NOT_FOUND_AFTER_SUBMIT")
            return self._apply(grant, receipt)
        except Exception:
            return self._unknown(grant, "LOCAL_ACTION_READBACK_UNKNOWN")

    def _apply(self, grant, receipt):
        row = self.store.record_action_receipt(grant.mission_id, step_index=grant.cell_transfer.step_index,
                                               receipt=receipt)
        step = row["steps"][grant.cell_transfer.step_index]
        state = row["status"]
        if state == "RUNNING":
            state = step["result"]["state"]
        return {"mission_id": grant.mission_id, "action_id": grant.action_id,
                "attempt_id": grant.attempt_id, "state": state, "reason": row["reason"]}

    def _unknown(self, grant, reason, *, outcome="UNKNOWN"):
        row = self.store.record_action_result(
            grant.mission_id, step_index=grant.cell_transfer.step_index,
            action_id=grant.action_id, attempt_id=grant.attempt_id,
            event_id=f"dispatch:{grant.attempt_id}:{reason}", outcome=outcome, result={"reason": reason},
        )
        return {"mission_id": grant.mission_id, "action_id": grant.action_id,
                "attempt_id": grant.attempt_id, "state": row["status"], "reason": row["reason"]}

    def cancel_current(self, mission_id: str, *, reason: str):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 256:
            raise ValueError("cancel reason must be non-empty and at most 256 characters")
        job = self.store.get(mission_id)
        if job is None:
            raise KeyError(mission_id)
        if job["status"] not in {"RUNNING", "HOLD"}:
            raise MissionConflict("only an unresolved Cell transfer may be cancelled")
        grant = self._stored_grant(job)
        try:
            return self._apply(grant, self.transport.cancel(grant, reason=reason))
        except Exception:
            return self._unknown(grant, "LOCAL_ACTION_CANCEL_OUTCOME_UNKNOWN")
