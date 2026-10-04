"""The robot-state safety_policy block (D-400, API v1.71). ROS-free."""
from __future__ import annotations

from typing import Any, Optional


def safety_policy_block(configured_mode: str, adapter: Any, params: Optional[Any],
                        shadow: Optional[Any], record_errors: int = 0) -> dict:
    return {"mode": configured_mode, "mode_effective": adapter.config.mode,
            "mode_error": adapter.mode_error,
            "revision": params.revision if params is not None else "",
            "sources": dict(params.sources) if params is not None else {},
            "shadow": ({**shadow.snapshot(), "record_errors": record_errors}
                       if shadow is not None else None)}
