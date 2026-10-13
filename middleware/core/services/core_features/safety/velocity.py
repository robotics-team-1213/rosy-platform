"""Finite velocity limits and same-curve checks; no authority or runtime state."""

import math


def finite_velocity(linear: float, angular: float) -> bool:
    return all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in (linear, angular))


def limit_velocity(linear: float, angular: float, max_l: float, max_a: float,
                   *, preserve_curvature: bool = False) -> tuple[float, float]:
    if not finite_velocity(linear, angular) or not finite_velocity(max_l, max_a) or min(max_l, max_a) < 0:
        return 0., 0.
    if preserve_curvature:
        scale = min(1., max_l / abs(linear) if linear else 1., max_a / abs(angular) if angular else 1.)
        return linear * scale, angular * scale
    return max(-max_l, min(max_l, linear)), max(-max_a, min(max_a, angular))


def same_curve(candidate: tuple[float, float], output: tuple[float, float]) -> bool:
    scale = None
    for wanted, actual in zip(candidate, output):
        if wanted == 0.:
            if actual != 0.:
                return False
        else:
            ratio = actual / wanted
            if not 0 <= ratio <= 1 or (scale is not None and not math.isclose(ratio, scale, rel_tol=1e-9)):
                return False
            scale = ratio
    return True
