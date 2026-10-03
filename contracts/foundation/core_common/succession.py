"""Leader succession for one formation.

The same ordered roster and the same dead set name one leader. The site and
every follower run this function. They do not hold a ballot, so two robots
cannot appoint two leaders from the same facts.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence


def next_leader(order: Sequence[str], dead: Iterable[str] = ()) -> Optional[str]:
    """First living id in `order`, or None when a formation cannot continue.

    A formation needs a leader and at least one follower. One survivor is not
    a formation: the caller stops instead of following a dead reference.
    """
    gone = {robot_id for robot_id in dead if robot_id}
    living: list[str] = []
    seen: set[str] = set()
    for robot_id in order:
        if not robot_id or robot_id in gone or robot_id in seen:
            continue
        seen.add(robot_id)
        living.append(robot_id)
    if len(living) < 2:
        return None
    return living[0]
