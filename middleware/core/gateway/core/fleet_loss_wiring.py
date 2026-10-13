"""SAF-003 wiring (D-419): FleetAgent link + Fleet nav goal -> FleetLossMonitor.

Kept out of services.py (size budget). The monitor itself is ROS-free in
core_features.safety.fleet_loss; ros_bridge ticks it on the 5 Hz power timer.
"""

from __future__ import annotations

import contextlib
import logging

from core_common.config import fleet_link_arm_state
from core_features.fleet_agent.agent import HEARTBEAT_PERIOD_S, fleet_link_configured
from core_features.safety.fleet_loss import (
    DEFAULT_TIMEOUT_S,
    FleetLossMonitor,
    fleet_loss_timeout_s,
    normalize_policy,
    validate_link_timing,
)

logger = logging.getLogger(__name__)


def build_fleet_loss(config: dict, *, events, fleet_agent, nav, safety,
                     localization) -> FleetLossMonitor:
    """Validate the config, normalise the stored policy, and bind the monitor."""
    # One predicate with the agent (agent.fleet_link_configured): a robot has a Fleet link
    # when its config carries an approved token and a site location. Read from config, not
    # from the agent: a later rejected hello or stop() is a lost link, not a robot without
    # Fleet (I1). Only PUT/DELETE /fleet/link change the config at runtime (D-555 5).
    configured = fleet_link_configured(config.get("fleet") or {})
    fallback = None
    # Fail fast only on a robot with a Fleet link; a robot without Fleet must boot
    # unaffected by Fleet-loss settings (D-419 scope) — one warning, defaults.
    try:
        timeout_s = fleet_loss_timeout_s(config.get("safety") or {})
        validate_link_timing(timeout_s, HEARTBEAT_PERIOD_S, fleet_agent.reply_timeout_s)
    except ValueError as exc:
        if configured:
            raise
        logger.warning("ignoring invalid SAF-003 timing on a robot without a Fleet link: %s", exc)
        timeout_s = DEFAULT_TIMEOUT_S
        fallback = f"SAF-003 timing: {exc}"
    policy, known = normalize_policy(safety.fleet_loss_policy)
    if not known:
        logger.warning("safety.fleet_loss_policy %r is unknown; SAF-003 uses STOP",
                       safety.fleet_loss_policy)
    safety.fleet_loss_policy = policy

    def return_home() -> None:
        # Same gate as the SAF-005 battery return: no home goal unless LOCALIZED (D-395).
        gate = localization.gate if localization is not None else contextlib.nullcontext()
        with gate:
            if localization is not None and not localization.autonomy_allowed():
                raise RuntimeError("robot localization is not LOCALIZED")
            nav.home(source="fleet_loss")

    monitor = FleetLossMonitor(
        events=events,
        # D-555: after a runtime relink the link counts once the hub welcomed it, or at the
        # latest after FLEET_LINK_ARM_GRACE_S (a link that never comes up is then lost, as at boot).
        link_configured=lambda: (fleet_link_configured(config.get("fleet") or {})
                                 and fleet_link_arm_state(getattr(fleet_agent, "armed", True),
                                                          getattr(fleet_agent, "relinked_at", None),
                                                          fleet_agent._clock()) != "pending"),
        link_connected=lambda: fleet_agent.connected,
        link_last_rx=lambda: fleet_agent.last_rx,
        # Link freshness is the heartbeat's own silence budget, not the policy timeout.
        freshness_s=fleet_agent.link_fresh_s,
        fleet_goal=nav.fleet_goal,
        policy=lambda: safety.fleet_loss_policy,
        stop_goal=lambda correlation_id: nav.cancel(
            source="fleet_loss", correlation_id=correlation_id),
        return_home=return_home,
        timeout_s=timeout_s,
    )
    #: D-555: PUT /fleet/link refuses to arm SAF-003 on these fallback defaults.
    monitor.config_fallback = fallback
    return monitor
