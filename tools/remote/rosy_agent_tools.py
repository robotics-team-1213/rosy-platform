"""Tool specifications and JSON schema helpers for `rosy_agent_bridge`."""
from __future__ import annotations

from typing import Any

_VIEWS = ["top", "side", "arm_s_top", "arm_s_wrist", "arm_a_wrist", "arm_b_wrist"]
_CELLS = ["cell_s", "cell_ab"]


def _obj_schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_CELL_TASK_PROPS: dict[str, Any] = {
    "cell_id": {"type": "string", "enum": _CELLS}, "arm_id": {"type": "string"},
    "src_site": {"type": "string"}, "dst_site": {"type": "string"},
    "preset": {"type": "string"}, "robot_id": {"type": "string"},
    "tier": {"type": "integer"}, "tiers": {"type": "array", "items": {"type": "integer"}},
    "execution_mode": {"type": "string", "enum": ["guarded_pick", "act_policy"]},
    "max_chunks": {"type": "integer"}, "displaced_to": {"type": "string"}, "zone_id": {"type": "string"},
    "task_id": {"type": "string"}, "request_key": {"type": "string"}, "auto_admit": {"type": "boolean"},
    "fallback_from_task_id": {"type": "string"}, "fallback_verb": {"type": "string"},
    "failure_bundle_id": {"type": "string"}, "failure_context_sha256": {"type": "string"},
    "expected_context_sha256": {"type": "string"}, "expected_readiness_digest": {"type": "string"},
    "expected_authority_epoch": {"type": "integer"},
    "expected_dispatch_generation": {"type": "integer"}, "expected_stop_generation": {"type": "integer"},
}
_PROPOSE_CELL_TASK_PROPS = {k: v for k, v in _CELL_TASK_PROPS.items() if k not in ("tiers", "auto_admit")}

TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "cell_readiness", "description": "Read OMX cell :8781 /readiness state and cell_state_gen.",
     "inputSchema": _obj_schema({})},
    {"name": "cell_failure_context", "description": "Read latest or named CellFailureContext bundle from :8781.",
     "inputSchema": _obj_schema({"bundle_id": {"type": "string"}, "arm": {"type": "string"}, "kind": {"type": "string"}})},
    {"name": "cell_failure_asset", "description": "Fetch an image, JSON, or trace-tail asset from a :8781 failure bundle.",
     "inputSchema": _obj_schema({"bundle_id": {"type": "string"}, "filename": {"type": "string"}}, ["bundle_id", "filename"])},
    {"name": "cell_frame", "description": "Fetch live cell frame JPEG from :8781 preserving sequence headers.",
     "inputSchema": _obj_schema({"view": {"type": "string", "enum": _VIEWS}}, ["view"])},
    {"name": "cell_queue", "description": "Read :8781 /queue active jobs, optionally with recent /jobs and /failures.",
     "inputSchema": _obj_schema({"include_jobs": {"type": "boolean"}, "include_failures": {"type": "boolean"},
                                 "arm": {"type": "string"}, "limit": {"type": "integer"}})},
    {"name": "cell_upkeep_check", "description": "Run non-motion upkeep_check on :8781.",
     "inputSchema": _obj_schema({"manifest": {"type": "string"}, "out": {"type": "string"}}, ["manifest"])},
    {"name": "cell_dry_run", "description": "Run observe-only auto_pick_dry_run on :8781.",
     "inputSchema": _obj_schema({
         "config": {"type": "string"}, "catalog": {"type": "string"},
         "roi": {"type": "array", "items": {"type": "integer"}},
         "source": {"type": "string"}, "dest": {"type": "string"},
         "object": {"type": "string"}, "colour": {"type": "string"}, "layers_below": {"type": "integer"}, "neighbour_clear_mm": {"type": "number"},
         "at_px": {"type": "string", "description": "U,V pixel of the object top face; with source free:<site>"},
         "one_shot": {"type": "boolean"}, "target_object_ref": {"type": "string"},
         "target_catalog_id": {"type": "string"},
         "target_centroid_mm": {"type": "array", "items": {"type": "number"}},
         "target_source_seq": {"type": "integer"}, "target_observed_at": {"type": "number"},
         "target_ttl_s": {"type": "number"}, "target_tolerance_mm": {"type": "number"},
         "expected_cell_state_gen": {"type": "integer"},
     }, ["config", "catalog", "roi", "source", "dest"])},
    {"name": "fleet_state", "description": "Read Fleet-R /api/fleet/state (registered robots, online status, scope).",
     "inputSchema": _obj_schema({})},
    {"name": "fleet_cell_readiness", "description": "Read Fleet-R cell readiness, digest, and dispatch_generation.",
     "inputSchema": _obj_schema({"cell_id": {"type": "string", "enum": _CELLS}}, ["cell_id"])},
    {"name": "fleet_cell_sites", "description": "List canonical cell sites, zones, and arm assignments from Fleet-R.",
     "inputSchema": _obj_schema({})},
    {"name": "fleet_cell_tasks", "description": "List Fleet-R /api/fleet/pipeline/cell-tasks and cell safety summary.",
     "inputSchema": _obj_schema({"cell_id": {"type": "string", "enum": _CELLS}, "status": {"type": "string"}})},
    {"name": "fleet_propose_cell_task", "description": "Propose a Fleet-R cell task (PROPOSED only). For fallback, supply the failure bundle ID, context digest, readiness digest, and a stable request_key. For policy fallback, copy correlation.fleet_task_id into fallback_from_task_id.",
     "inputSchema": _obj_schema(_PROPOSE_CELL_TASK_PROPS, ["cell_id"])},
    {"name": "fleet_dispatch_cell_task", "description": "Dispatch a Fleet-R cell pick-and-place task (QUEUED immediately when autonomous dispatch or operator permits; falls back to PROPOSED on gated sites).",
     "inputSchema": _obj_schema(_CELL_TASK_PROPS, ["cell_id"])},
    {"name": "job_status", "description": "Poll cell :8781 job or learning :8768 canonical run status.",
     "inputSchema": _obj_schema({"job_id": {"type": "string"}, "plane": {"type": "string", "enum": ["cell", "learning"]}}, ["job_id"])},
    {"name": "cell_open_human_request", "description": "Open an operator person-request on Fleet-R.",
     "inputSchema": _obj_schema({
         "robot_id": {"type": "string"},
         "kind": {"type": "string", "enum": ["unplug_charger", "plug_charger", "move_robot", "clear_area", "other"]},
         "text": {"type": "string"}, "why": {"type": "string"}, "expires_s": {"type": "number"},
     }, ["kind", "text", "why"])},
    {"name": "cell_capture_clip", "description": "Capture bounded non-motion MP4 clip via :8781.",
     "inputSchema": _obj_schema({
         "view": {"type": "string", "enum": _VIEWS}, "duration_s": {"type": "integer"},
         "fps": {"type": "integer"}, "out_dir": {"type": "string"},
     }, ["view", "duration_s"])},
    {"name": "cell_dataset_pipeline", "description": "Run convert_episodes or transfer_dataset offline media job via :8781.",
     "inputSchema": _obj_schema({
         "stage": {"type": "string", "enum": ["convert", "transfer"]}, "episodes": {"type": "string"},
         "out": {"type": "string"}, "repo_id": {"type": "string"}, "collection": {"type": "string"},
         "fps": {"type": "integer"}, "images": {"type": "string"},
         "outcome": {"type": "string", "enum": ["success", "failed", "failure"]},
     }, ["stage"])},
    {"name": "learning_run_job", "description": "Start a canonical offline learning job on :8768.",
     "inputSchema": _obj_schema({
         "kind": {"type": "string"}, "arm_id": {"type": "string"}, "request_id": {"type": "string"}, "params": {"type": "object"},
     }, ["kind", "arm_id", "request_id", "params"])},
    {"name": "learning_stage_bundle", "description": "Fetch canonical bundle-manifest from :8768 and stage policy bundle onto :8781.",
     "inputSchema": _obj_schema({"run_id": {"type": "string"}, "target_dir": {"type": "string"}}, ["run_id", "target_dir"])},
    {"name": "cell_push_dry_run", "description": "Plan a closed-jaw push (5..20 mm of one box) on :8781 without moving: push_dry_run.",
     "inputSchema": _obj_schema({
         "arm": {"type": "string", "enum": ["arm_s", "arm_a", "arm_b"]}, "config": {"type": "string"}, "site": {"type": "string"},
         "roi": {"type": "array", "items": {"type": "integer"}},
         "px_x": {"type": "number"}, "px_y": {"type": "number"}, "dir_x": {"type": "number"}, "dir_y": {"type": "number"},
         "mm": {"type": "number"}, "half_mm": {"type": "number"}, "half_width_mm": {"type": "number"}, "catalog": {"type": "string"},
     }, ["arm", "config", "site", "roi", "px_x", "px_y", "dir_x", "dir_y", "mm"])},
    {"name": "cell_area_dry_run", "description": "Run observe/IK-plan only area_xyz_pick dry_run on :8781.",
     "inputSchema": _obj_schema({
         "arm": {"type": "string", "enum": ["arm_s", "arm_a", "arm_b"]},
         "config": {"type": "string"},
         "pick_area": {"type": "string"}, "pick_x": {"type": "number"}, "pick_y": {"type": "number"}, "pick_z": {"type": "number"},
         "place_area": {"type": "string"}, "place_x": {"type": "number"}, "place_y": {"type": "number"}, "place_z": {"type": "number"},
         "pick_yaw_deg": {"type": "number"}, "place_yaw_deg": {"type": "number"}, "max_attempts": {"type": "integer"},
         "stay_in_hover": {"type": "boolean"}, "no_vision_refine": {"type": "boolean"},
         "catalog": {"type": "string"}, "object": {"type": "string"},
     }, ["arm", "config", "pick_area", "pick_x", "pick_y", "pick_z", "place_area", "place_x", "place_y", "place_z"])},
)
TOOL_SPECS += (
    {"name": "cell_observe", "description": "Non-moving observation pack for one arm (runs camera-only dry-run jobs on the cell and takes its one camera slot; repeat is at most 5): fresh frames, annotated top frame, measured candidates with refusal CODE and suggestions, readiness, live verbs. observable=false (reason only) when a camera is dark, stale or missing.",
     "inputSchema": _obj_schema({"arm": {"type": "string", "enum": ["arm_a", "arm_b", "arm_s"]}, "repeat": {"type": "integer", "maximum": 5},
                                 "layers_below": {"type": "integer"}}, ["arm"])},
    {"name": "cell_verify_after", "description": "Camera verdict for one step: compare the observation pack before with a fresh one this tool takes itself (source cleared, arrived at dest, nothing else moved, arm folded, no incident). A job exit code is never success.",
     "inputSchema": _obj_schema({"before": {"type": "object"}, "step": {"type": "object"}, "job_exit": {"type": "integer"}},
                                ["before", "step"])},
)
TOOL_MAP = {t["name"]: t for t in TOOL_SPECS}
OPERATIONS_MCP_TOOLS = frozenset({
    "cell_readiness", "cell_failure_context", "cell_failure_asset", "cell_frame", "cell_queue",
    "fleet_state", "fleet_cell_readiness", "fleet_cell_sites", "fleet_cell_tasks",
    "fleet_propose_cell_task", "fleet_dispatch_cell_task",
})
