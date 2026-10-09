"""D-531: admit fresh CORE route context for one camera frame."""

import math

from core_common.protocol.route_context import RouteContext

from .sensing.perception.lane_keep_junction import JUNCTION_AHEAD_M


ROUTE_CONTEXT_STALE_S = 0.5
SOURCE_FUTURE_TOLERANCE_S = 0.1
BEND_LEAD_M = 0.25  # D-507 CORE bend lead; only the expected window uses it.


class RouteContextInput:
    def __init__(self):
        self._context = None

    def receive(self, raw: str) -> None:
        try:
            context = RouteContext.model_validate_json(raw)
        except ValueError:
            self._context = None
            return
        self._context = context if context.seq is not None else None

    def for_frame(self, stamp_s: float) -> RouteContext | None:
        context = self._context
        if context is None:
            return None
        if (type(stamp_s) not in (int, float) or not math.isfinite(stamp_s)
                or not -SOURCE_FUTURE_TOLERANCE_S <= stamp_s - context.stamp_s <= ROUTE_CONTEXT_STALE_S
                or stamp_s > context.valid_until_s):
            self._context = None
            return None
        return context


def bend_expected(context: RouteContext | None) -> bool:
    return bool(context is not None and context.kind == "bend"
                and (context.bend_phase in ("bending", "reacquiring")
                     or (context.ahead_m is not None
                         and context.ahead_m[0] <= JUNCTION_AHEAD_M + BEND_LEAD_M
                         and context.ahead_m[1] >= 0.0)))
