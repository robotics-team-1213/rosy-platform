"""Locked swarm state projection; the manager retains all mutation ownership."""
from core_common.protocol.schemas import SwarmFollowParams, SwarmRole, SwarmStatus


class SwarmStatusView:
    def status(self) -> SwarmStatus:
        with self._lock:
            if self._params is None:
                if self._elected:
                    return SwarmStatus(role=SwarmRole.LEADER, active=False)
                return SwarmStatus()
            return SwarmStatus(
                role=SwarmRole.FOLLOWER,
                formation=self._formation_label(self._params),
                active=True,
            )

    def state_payload(self) -> dict:
        """GET /api/v1/swarm/state (SWM-002). 스냅샷의 swarm 필드보다 자세하다."""
        with self._lock:
            status = self.status()
            return {
                "role": status.role.value,
                "formation": status.formation,
                "active": status.active,
                "holding": self._holding,
                "target_robot_id": self._params.target_robot_id if self._params else None,
                "source": self._params.source.value if self._params else None,
                "max_speed": self._params.max_speed if self._params else None,
                "map_mismatch": self._map_mismatch,
                "mode": self._params.mode if self._params else None,
                "trail": None if self._trail is None else {
                    "leader_s": round(self._trail.leader_s, 3),
                    "progress": round(self._trail.progress, 3),
                    "hold_reason": self._trail_hold,
                    "anchor": "fleet" if self._trail_kind == "fleet" else None},
                "stream_age_s": (
                    None if self._last_sample_at is None
                    else round(self._clock() - self._last_sample_at, 3)
                ),
            }

    @staticmethod
    def _formation_label(params: SwarmFollowParams) -> str:
        return f"follow:{params.target_robot_id}@{params.distance:.2f}/{params.lateral:.2f}"
