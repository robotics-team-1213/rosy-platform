"""Deterministic wait-graph arithmetic shared by Fleet and Situation."""

from typing import Mapping, Optional, Sequence


def wait_cycle(waiting_for: Mapping[str, Sequence[str]]) -> Optional[tuple[str, ...]]:
    """A cycle in "robot waits for robot", or None. Linear in robots plus wait edges.

    Waiting on any holder counts, so a cycle may be reported where one holder would leave on
    its own; that escalates to the resolver (D-517 5), which is the safe side.
    """
    colour: dict[str, int] = {}
    for start in sorted(waiting_for):
        if colour.get(start):
            continue
        colour[start] = 1
        path = [start]
        stack = [iter(sorted(waiting_for.get(start, ())))]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                colour[path.pop()] = 2
                stack.pop()
            elif colour.get(nxt) == 1:
                return tuple(path[path.index(nxt):])
            elif not colour.get(nxt):
                colour[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(waiting_for.get(nxt, ()))))
    return None
