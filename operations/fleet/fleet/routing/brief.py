"""Facts a person can hand to an AI or another system. Not a command.

The bundle names the planner that produced it, the fields the caller filled, and
what that planner holds. The other planners are listed with the fields they
accept, whether Fleet runs them, and a ``note`` about what the answer does.
``plan_only`` does not move. ``one_point_goal`` is one short point on the
existing goal path. ``not_this_runtime`` is not used here. An AI may read the
bundle and return a fact or a candidate. Fleet still decides, and CORE still moves.
"""

from __future__ import annotations

#: Words that would make this bundle a command. A route fact must not carry them.
_COMMANDS = frozenset({"command", "decision", "WAIT", "YIELD", "RESUME", "ABORT", "MANUAL"})

#: What each planner will read. ``live`` means Fleet runs that planner.
PLANNERS = (
    {
        "id": "lane_graph",
        "live": True,
        "motion": "line_follow",
        "give": ("to", "via", "arrive_yaw", "speed_cap", "blocked_edges", "extra_cost"),
        "note": "plan_only",
    },
    {
        "id": "lane_step",
        "live": True,
        "motion": "short_point",
        "give": ("edges",),
        "note": "one_point_goal",
    },
    {
        "id": "nav2",
        "live": False,
        "motion": "open_floor",
        "give": ("x", "y", "yaw"),
        "note": "not_this_runtime",
    },
    {
        "id": "grid",
        "live": False,
        "motion": "occupancy",
        "give": ("goal",),
        "note": "not_this_runtime",
    },
)


def _reject_commands(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _COMMANDS:
                raise ValueError("a route fact must not carry a command")
            _reject_commands(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_commands(item)
    elif isinstance(value, str) and value in _COMMANDS:
        raise ValueError("a route fact must not carry a command")


def route_context(*, planner: str, supplied: dict, holds: dict) -> dict:
    """One fact bundle. ``planner`` is an id in ``PLANNERS``."""
    if planner not in {row["id"] for row in PLANNERS}:
        raise ValueError(f"unknown planner {planner}")
    _reject_commands(supplied)
    _reject_commands(holds)
    return {
        "role": "fact",
        "planner": planner,
        "supplied": dict(supplied),
        "holds": dict(holds),
        "planners": [
            {"id": row["id"], "live": row["live"], "motion": row["motion"],
             "give": list(row["give"]), "note": row["note"]}
            for row in PLANNERS
        ],
    }
