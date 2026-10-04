"""Validate the shared phased Action receipt without accepting goal completion."""

from typing import Mapping

from core_common.protocol.schemas import DeviceActionReceipt, FleetActionGrant, FleetCellTransferGrant


def verify_phase_receipt(grant: FleetActionGrant | FleetCellTransferGrant,
                         response: object) -> DeviceActionReceipt:
    raw = response
    if isinstance(response, Mapping) and "receipt" in response:
        raw = response["receipt"]
    receipt = (raw if isinstance(raw, DeviceActionReceipt)
               else DeviceActionReceipt.model_validate(raw))
    expected = (
        grant.mission_id, grant.step_id, grant.action_id, grant.attempt_id,
        grant.workcell_id, grant.instance_id, grant.request_digest,
        grant.authority_epoch, grant.dispatch_generation,
    )
    actual = (
        receipt.mission_id, receipt.step_id, receipt.action_id, receipt.attempt_id,
        receipt.workcell_id, receipt.instance_id, receipt.request_digest,
        receipt.authority_epoch, receipt.dispatch_generation,
    )
    if actual != expected:
        raise ValueError("local Action receipt does not match its Fleet grant")
    if receipt.phase_summaries is None:
        raise ValueError("v2 phased Action receipt is missing phase summaries")
    if receipt.state.value == "SUCCEEDED" and (
            [phase.ordinal for phase in receipt.phase_summaries] != [0, 1, 2, 3]
            or any(phase.state != "SUCCEEDED" for phase in receipt.phase_summaries)):
        raise ValueError("successful phased Action receipt requires four successful phases")
    return receipt
