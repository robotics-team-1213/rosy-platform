"""Pin the CORE <-> Fleet REST request-model mirrors (D-940 follow-up).

Fleet re-declares several CORE v1 request bodies by hand for its own
deploy-independent server. The wire-shape source of truth is
``core_common.protocol`` (D-18); until the shared models move there, this pins
the relation ``fleet fields ⊆ core fields`` with every reviewed difference
declared in ``KNOWN_DRIFT``. A field added on one side only fails here instead
of silently splitting the wire contract.

Honest holes, not oversight:
- Field *names* only: a narrowed Literal (Fleet's ``decision`` accepts five
  values, CORE seven) or changed constraint is invisible here; the API
  reference and route tests own those.
- Classes not listed in ``MIRRORS`` are not pinned; add a row when a new
  mirror is born rather than widening this scan.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: class name -> (core path, fleet path); both must define the class.
MIRRORS = {
    "GoalRequest": (
        "middleware/core/api/core_api_web/api/v1/navigation.py",
        "operations/fleet/fleet/server/ledger/task_dispatch_routes.py",
    ),
    "LineFollowModeRequest": (
        "middleware/core/api/core_api_web/api/v1/line_follow.py",
        "operations/fleet/fleet/server/ledger/task_dispatch_routes.py",
    ),
    "LineStuckDecisionRequest": (
        "middleware/core/api/core_api_web/api/v1/line_follow.py",
        "operations/fleet/fleet/server/console/console_routes.py",
    ),
}

#: Reviewed, still-open differences: fields CORE accepts that the Fleet copy
#: drops (subset mirror) and fields only Fleet has. Both directions are
#: checked, so a drift that is fixed must leave this table in the same change.
KNOWN_DRIFT = {
    "GoalRequest": {
        "core_only": {"waypoint", "correlation_id", "lease_ttl_s",
                      "expected_boot_id", "expected_owner_generation"},
    },
    "LineFollowModeRequest": {"core_only": {"hold_s"}},  # D-344 §8
    "LineStuckDecisionRequest": {
        "core_only": {"yield_m", "yield_turn_rad", "realign", "expected_stuck"},
    },
}


def _fields(rel_path: str, class_name: str) -> set[str]:
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {stmt.target.id for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)}
    raise AssertionError(f"{class_name} is gone from {rel_path}; update MIRRORS")


def test_fleet_request_models_stay_subset_of_core():
    for name, (core_path, fleet_path) in MIRRORS.items():
        core = _fields(core_path, name)
        fleet = _fields(fleet_path, name)
        drift = KNOWN_DRIFT.get(name, {"core_only": set()})
        core_only, fleet_only = core - fleet, fleet - core
        assert not fleet_only, (
            f"{name}: Fleet declares fields CORE does not accept: {fleet_only}. "
            "Fleet must not widen the robot contract; align the pair or route "
            "the field through core_common.protocol (D-18).")
        assert core_only == drift.get("core_only", set()), (
            f"{name}: undeclared core-only fields {core_only - drift.get('core_only', set())} "
            f"(or a declared drift was fixed: {drift.get('core_only', set()) - core_only}). "
            "Update the model pair and KNOWN_DRIFT in the same change.")
