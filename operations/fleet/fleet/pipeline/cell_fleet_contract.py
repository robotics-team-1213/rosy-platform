"""Authority and handoff contract between site AMR Fleet and OMX Workcell Fleet."""

from dataclasses import asdict, dataclass
from typing import Any, Iterable

CONTRACT_VERSION = 'rosy.fleet-r-cell-contract.v1'
FLEET_R_AUTHORITY = (
    'site_map', 'lane_graph', 'road_nav2', 'corridor_arbitration',
    'charge_bays', 'traffic_signals', 'handoff_station_arrival',
)
FLEET_CELL_AUTHORITY = (
    'omx_arm_ik', 'gripper_pinch', 'wrist_servo_vision', 'area_xyz_directive',
    'pallet_tier_stacking', 'arm_claim_grant',
)
HANDOFF_PHASES = (
    'IDLE', 'ARRIVED', 'CLAIMED', 'ARM_IN_BED_ZONE', 'TRANSFER_DONE',
    'RELEASED', 'ABORTED',
)
INHIBIT_MOTION_PHASES = frozenset({'CLAIMED', 'ARM_IN_BED_ZONE'})


@dataclass(frozen=True)
class FleetRToCellHandoff:
    """Fleet-R station arrival facts offered to the cell for a leased handoff."""

    handoff_lease_id: str
    site_id: str
    map_version: int | None
    station_place: str
    cell_id: str
    robot_id: str
    robot_kind: str
    station_pose_xy_yaw: tuple[float, float, float]
    wheel_brake_locked: bool = True
    bed_ready: bool = True
    v_cmd_mps: float = 0.0
    cargo_manifest: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CellToFleetRReceipt:
    """Cell progress and motion interlock receipt for the AMR handoff."""

    handoff_lease_id: str
    cell_id: str
    station_place: str
    robot_id: str
    phase: str
    arm_roles_used: tuple[str, ...] = ('arm_s',)
    amr_motion_inhibited: bool = False
    stage_id: str | None = None
    goal_evidence_digest: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_handoff_gate(
    handoff: FleetRToCellHandoff | None,
    receipt: CellToFleetRReceipt | None,
) -> dict[str, Any]:
    """Evaluate cell entry and Fleet-R departure from the shared bed zone."""
    cell_can_claim = bool(
        handoff is not None
        and handoff.wheel_brake_locked
        and handoff.bed_ready
        and abs(handoff.v_cmd_mps) <= 1e-4
    )
    inhibited = bool(
        receipt is not None
        and (receipt.amr_motion_inhibited or receipt.phase in INHIBIT_MOTION_PHASES)
    )
    can_depart = not inhibited and (
        receipt is None or receipt.phase in ('IDLE', 'RELEASED')
    )
    return {
        'contract_version': CONTRACT_VERSION,
        'handoff_lease_id': handoff.handoff_lease_id if handoff else None,
        'station_place': handoff.station_place if handoff else (receipt.station_place if receipt else None),
        'cell_id': handoff.cell_id if handoff else (receipt.cell_id if receipt else None),
        'robot_id': handoff.robot_id if handoff else (receipt.robot_id if receipt else None),
        'phase': receipt.phase if receipt else 'IDLE',
        'cell_can_claim': cell_can_claim,
        'amr_motion_inhibited': inhibited,
        'amr_can_depart': can_depart,
        'reason': receipt.reason if receipt else None,
    }


def validate_boundary_separation(
    fleet_r_keys: Iterable[str] = (), cell_keys: Iterable[str] = (),
) -> dict[str, Any]:
    fleet_violations = sorted(set(fleet_r_keys) & set(FLEET_CELL_AUTHORITY))
    cell_violations = sorted(set(cell_keys) & set(FLEET_R_AUTHORITY))
    return {
        'contract_version': CONTRACT_VERSION,
        'valid': not fleet_violations and not cell_violations,
        'fleet_r_violations': fleet_violations,
        'fleet_cell_violations': cell_violations,
        'rosy_fleet_r_owns': list(FLEET_R_AUTHORITY),
        'rosy_fleet_cell_owns': list(FLEET_CELL_AUTHORITY),
    }


def contract_spec_dict() -> dict[str, Any]:
    return {
        'contract_version': CONTRACT_VERSION,
        'rosy_fleet_r_owns': list(FLEET_R_AUTHORITY),
        'rosy_fleet_cell_owns': list(FLEET_CELL_AUTHORITY),
        'handoff_phases': list(HANDOFF_PHASES),
        'inhibit_motion_phases': sorted(INHIBIT_MOTION_PHASES),
    }
