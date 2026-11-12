"""OMX workcell topology and area-stage planning, separate from AMR road routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from fleet.pipeline.cell_fleet_contract import (
    CellToFleetRReceipt,
    FleetRToCellHandoff,
    INHIBIT_MOTION_PHASES,
    evaluate_handoff_gate,
)


@dataclass(frozen=True)
class OmxWorkcellStation:
    cell_id: str
    station_place: str
    station_xy: tuple[float, float]
    arm_roles: tuple[str, ...]
    mode: str
    src_area: str
    dst_area: str
    handoff_yaw_deg: float
    max_tier: int
    workspace_min_m: tuple[float, float, float] = (-0.05, -0.28, 0.002)
    workspace_max_m: tuple[float, float, float] = (0.28, 0.28, 0.26)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["station_xy"] = list(self.station_xy)
        result["arm_roles"] = list(self.arm_roles)
        result["workspace_min_m"] = list(self.workspace_min_m)
        result["workspace_max_m"] = list(self.workspace_max_m)
        return result


def _place_xy(site_map: Any, graph: Any, place_id: str, fallback: tuple[float, float]) -> tuple[float, float]:
    for source in (graph, site_map):
        places = getattr(source, "places", None)
        if isinstance(places, Mapping):
            place = places.get(place_id)
        else:
            place = next((p for p in (places or ()) if getattr(p, "id", None) == place_id), None)
        if place is not None:
            if isinstance(place, Mapping):
                return float(place["x"]), float(place["y"])
            return float(place.x), float(place.y)
    return fallback


def resolve_omx_cells(site_map: Any = None, graph: Any = None) -> dict[str, OmxWorkcellStation]:
    stations = (
        OmxWorkcellStation("cell_s", "S3", _place_xy(site_map, graph, "S3", (0.6987, -0.2512)),
                           ("arm_s",), "shuttle_pinky_belt", "pinky", "belt", -85.0, 1),
        OmxWorkcellStation("cell_ab", "S5", _place_xy(site_map, graph, "S5", (0.9212, -0.4776)),
                           ("arm_a", "arm_b"), "stack_belt_pallet", "belt", "pallet", -90.0, 3),
    )
    return {station.cell_id: station for station in stations}


def evaluate_omx_cell_station(
    station: OmxWorkcellStation,
    *,
    docked_robot: Mapping[str, Any] | None = None,
    cell_state: Mapping[str, Any] | None = None,
    site_id: str = "world_261026",
    map_version: int | None = None,
) -> dict[str, Any]:
    state = cell_state or {}
    phase = str(state.get("phase", "ARRIVED" if docked_robot is not None else "IDLE"))
    handoff = None
    if docked_robot is not None:
        pose = docked_robot["pose"]
        handoff = FleetRToCellHandoff(
            handoff_lease_id=f"{station.cell_id}:{docked_robot['robot_id']}:{map_version or 0}",
            site_id=site_id, map_version=map_version, station_place=station.station_place,
            cell_id=station.cell_id, robot_id=docked_robot["robot_id"],
            robot_kind=docked_robot.get("robot_kind", "pinky"),
            station_pose_xy_yaw=(float(pose["x"]), float(pose["y"]), float(pose.get("yaw") or 0.0)),
            wheel_brake_locked=bool(docked_robot.get("wheel_brake_locked", True)),
            bed_ready=bool(docked_robot.get("bed_ready", True)),
            v_cmd_mps=float(docked_robot.get("v_cmd_mps", 0.0)),
            cargo_manifest=tuple(docked_robot.get("cargo_manifest", ())),
        )
    receipt = None
    if handoff is not None:
        receipt = CellToFleetRReceipt(
            handoff_lease_id=handoff.handoff_lease_id,
            cell_id=station.cell_id,
            station_place=station.station_place,
            robot_id=handoff.robot_id,
            phase=phase,
            arm_roles_used=station.arm_roles,
            amr_motion_inhibited=phase in INHIBIT_MOTION_PHASES or bool(state.get("amr_motion_inhibited", False)),
            stage_id=state.get("stage_id"),
            goal_evidence_digest=state.get("goal_evidence_digest"),
            reason=state.get("reason"),
        )
    gate = evaluate_handoff_gate(handoff, receipt)
    directive = None
    if gate.get("cell_can_claim") is True and phase not in ("IDLE", "RELEASED", "ABORTED"):
        directive = {
            "schema": "rosy.omx-cell-area-xyz-directive.v1", "cell_id": station.cell_id,
            "arm_roles": list(station.arm_roles), "src_area": station.src_area,
            "dst_area": station.dst_area, "yaw_deg": station.handoff_yaw_deg,
            "tier": int(state.get("tier", 1)),
        }
    return {
        "station": station.to_dict(), "phase": phase,
        "handoff": handoff.to_dict() if handoff is not None else None,
        "receipt": receipt.to_dict() if receipt is not None else None,
        "gate": gate, "stage_directive": directive,
    }
