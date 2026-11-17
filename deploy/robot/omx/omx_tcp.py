"""The one place that decides the jaw TCP (metres from the link5 pivot to the jaw tip).

Order: the arm's cell config `tcp_x_m`, then the plan's `tcp_x_m`, then the environment ROSY_OMX_TCP_X_M, then
`default` when the caller names one, else a refusal. 0.0885 is no default: it came from a box-top touch over an
unchecked table height and was rejected on 2026-11-08. The only fixed value is the measured v2.1 jaw below.
"""
from __future__ import annotations

import logging
import math
import os

ENV = "ROSY_OMX_TCP_X_M"
V21_JAW_TCP_M = 0.0740  # arm_b v2.1 jaws: STL tip 0.0741 from the pivot (2026-11-07 SHA check)
RANGE_M = (0.05, 0.12)
LOG = logging.getLogger("omx.tcp")
_LAST: list = []  # the IK loops resolve per step; log only when the answer changes


def _checked(value, source: str) -> tuple[float, str]:
    tcp = float(value)
    if not (math.isfinite(tcp) and RANGE_M[0] <= tcp <= RANGE_M[1]):
        raise SystemExit(f"{source} TCP {tcp} outside the OMX-F jaw range {RANGE_M[0]}..{RANGE_M[1]}")
    return tcp, source


def config_tcp(config: dict | None, plan: dict | None = None) -> float | None:
    """Optional tcp_x_m from cell config first, then plan / config['plan'], without exiting."""
    if isinstance(config, dict) and config.get("tcp_x_m") is not None:
        return float(config["tcp_x_m"])
    src = plan if isinstance(plan, dict) else (config.get("plan") if isinstance(config, dict) else None)
    if isinstance(src, dict) and src.get("tcp_x_m") is not None:
        return float(src["tcp_x_m"])
    return None


def resolve_tcp(cell_config=None, plan=None, *, default: float | None = None, env=None) -> tuple[float, str]:
    """-> (tcp_x_m, source); the source is logged. Nothing set and no `default` is a SystemExit, never a guess."""
    env = os.environ if env is None else env
    for value, source in ((cell_config, "cell config tcp_x_m"), (plan, "plan tcp_x_m"), (env.get(ENV) or None, ENV)):
        if value is not None:
            tcp, source = _checked(value, source)
            break
    else:
        if default is None:
            raise SystemExit(f"no jaw TCP: set tcp_x_m in the arm's cell config or {ENV} (v2.1 jaws measure {V21_JAW_TCP_M})")
        tcp, source = _checked(default, f"default {default} (measured v2.1 jaw)" if default == V21_JAW_TCP_M else "default")
    if _LAST != [tcp, source]:
        _LAST[:] = [tcp, source]
        LOG.info("jaw TCP %.4f m from %s", tcp, source)
    return tcp, source


def mismatch(cell_config, env=None) -> str | None:
    """A note when the cell config and the environment name different TCPs (the config wins in the planner), else None."""
    raw = (os.environ if env is None else env).get(ENV)
    if cell_config is None or not raw:
        return None
    try:
        differs = abs(float(raw) - float(cell_config)) > 1e-6
    except ValueError:
        return f"{ENV}={raw!r} is not a number"
    return f"{ENV} {raw} disagrees with the cell config tcp_x_m {cell_config}; the config wins" if differs else None
