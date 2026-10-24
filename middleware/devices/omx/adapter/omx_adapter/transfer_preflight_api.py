"""Optional read-only v2 owner IPC operation, authorized by Unix peer credentials."""
from __future__ import annotations

from typing import Mapping

from pydantic import TypeAdapter, ValidationError

from core_common.protocol.arm_transfer_preflight import ArmPhysicalRef, ARM_PREFLIGHT_REJECTION_STATUS
from core_common.protocol.schemas import ArmTransferCheckRequest, ArmTransferCheckResult

from .transfer_motion import STATE_INVALID, TransferPlanRejected
from .transfer_preflight import TransferPreflight


class TransferPreflightApi:
    def __init__(self, preflight: TransferPreflight, *, allowed_peer_uids: set[int], journal_id: str) -> None:
        if not isinstance(preflight, TransferPreflight):
            raise ValueError("an installed physical preflight service is required")
        peers = frozenset(allowed_peer_uids)
        if not peers or any(type(uid) is not int or uid < 0 for uid in peers):
            raise ValueError("explicit Fleet peer UIDs are required")
        self.preflight, self.allowed_peer_uids = preflight, peers
        self.journal_id = TypeAdapter(ArmPhysicalRef).validate_python(journal_id)

    @staticmethod
    def _error(status, code, *, reason=None, version=2):
        error = {"code": code}
        if reason is not None:
            error["reason"] = reason
        return {"version": version, "status": status, "error": error}

    def dispatch(self, frame: Mapping, *, peer_uid: int) -> dict:
        version = frame.get("version") if isinstance(frame, Mapping) else None
        reply_version = version if type(version) is int and version in {1, 2} else 2
        if type(peer_uid) is not int or peer_uid not in self.allowed_peer_uids:
            return self._error(403, "PEER_NOT_ALLOWED", version=reply_version)
        if type(version) is not int or version != 2:
            return self._error(400, "UNSUPPORTED_VERSION", version=reply_version)
        if set(frame) != {"version", "operation", "transfer"} or frame["operation"] != "CheckTransfer":
            return self._error(400, "INVALID_REQUEST")
        try:
            request = ArmTransferCheckRequest.model_validate(frame["transfer"])
        except ValidationError:
            return self._error(400, "INVALID_REQUEST")
        catalog = self.preflight.catalog
        if (request.workcell_id, request.instance_id) != (catalog.workcell_id, catalog.instance_id):
            return self._error(404, "ARM_REFERENCE_UNAVAILABLE", reason="REFERENCE_UNAVAILABLE")
        try:
            checked = self.preflight.check_transfer(catalog_digest=request.catalog_digest,
                source=request.source, target=request.target, geometry=request.geometry)
        except TransferPlanRejected as exc:
            code = {"CATALOG_MISMATCH": "ARM_CATALOG_CHANGED",
                    "REFERENCE_UNAVAILABLE": "ARM_REFERENCE_UNAVAILABLE",
                    STATE_INVALID: "ARM_STATE_UNAVAILABLE"}.get(exc.reason, "ARM_TRANSFER_UNPLANNABLE")
            return self._error(ARM_PREFLIGHT_REJECTION_STATUS[code], code, reason=exc.reason)
        except Exception:
            return self._error(503, "ARM_PREFLIGHT_UNAVAILABLE")
        result = ArmTransferCheckResult(
            request=request, journal_id=self.journal_id, profile_revision=checked.profile_revision,
            kinematics_revision=checked.kinematics_revision, calibration_revision=checked.calibration_revision,
            transform_revision=checked.transform_revision, planning_scene_revision=checked.planning_scene_revision,
            source_state_sequence=checked.source_state_sequence,
            state_age_s=checked.checked_at_monotonic_s - checked.observed_at_monotonic_s,
            simulation=True, collision_checked=False)
        return {"version": 2, "status": 200, "check": result.model_dump(mode="json")}
