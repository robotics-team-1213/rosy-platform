"""Validate the shared phased Action receipt without accepting goal completion."""

from typing import Mapping

from core_common.protocol.schemas import (
    DeviceActionReceipt, FleetActionGrant, FleetArmTransferGrant, FleetCellTransferGrant)

#: The fields a device receipt must echo from its Fleet grant. The one rule for every caller.
RECEIPT_IDENTITY = ("mission_id", "step_id", "action_id", "attempt_id", "workcell_id", "instance_id",
                    "request_digest", "authority_epoch", "dispatch_generation")


def receipt_matches_grant(grant: FleetActionGrant | FleetCellTransferGrant | FleetArmTransferGrant,
                          receipt: DeviceActionReceipt) -> bool:
    return (all(getattr(receipt, name) == getattr(grant, name) for name in RECEIPT_IDENTITY)
            and (not isinstance(grant, FleetArmTransferGrant) or receipt.journal_id == grant.owner_journal_id))


def verify_phase_receipt(grant: FleetActionGrant | FleetCellTransferGrant | FleetArmTransferGrant, response: object, *,
                         phase_ids: tuple[str, ...] | None = None) -> DeviceActionReceipt:
    """``phase_ids`` names the ordered phases a success must report; without it, ordinals 0-3."""
    raw = response
    if isinstance(response, Mapping) and "receipt" in response:
        raw = response["receipt"]
    receipt = (raw if isinstance(raw, DeviceActionReceipt)
               else DeviceActionReceipt.model_validate(raw))
    if not receipt_matches_grant(grant, receipt):
        raise ValueError("local Action receipt does not match its Fleet grant")
    if receipt.phase_summaries is None:
        raise ValueError("v2 phased Action receipt is missing phase summaries")
    reported = tuple(phase.phase_id if phase_ids is not None else phase.ordinal
                     for phase in receipt.phase_summaries)
    if receipt.state.value == "SUCCEEDED" and (
            reported != (phase_ids if phase_ids is not None else (0, 1, 2, 3))
            or any(phase.state != "SUCCEEDED" for phase in receipt.phase_summaries)):
        raise ValueError("a successful receipt requires every phase to succeed in order")
    return receipt
