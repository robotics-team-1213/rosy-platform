"""Robot-side swarm reference ingestion and trail sampling (SWM-007)."""
from __future__ import annotations

from typing import Optional

from core_common.protocol.schemas import SwarmFollowParams, SwarmReferenceSource
from core_features.swarm.poses import ReferencePose, follow_goal
from core_features.swarm.trail import Trail, TrailError

#: SWM-002 v1: moving goal 갱신 상한. 군집 속도(<=0.2 m/s)에서 충분하고,
#: 그 이상은 Nav2 플래너를 재시작시키기만 한다.
MAX_GOAL_RATE_HZ = 2.0
_MIN_GOAL_INTERVAL_S = 1.0 / MAX_GOAL_RATE_HZ


class SwarmReferenceStream:
    """Reference-stream operations on the manager-owned follow state."""

    def on_reference_pose(self, reference: ReferencePose) -> bool:
        """참조 pose 한 표본. 목표를 실제로 보냈으면 True."""
        with self._lock:
            params = self._params
            if params is None or reference.robot_id != params.target_robot_id:
                return False
            now = self._clock()
            # 표본은 도착했다 — 스트림은 살아 있다. 맵이 맞지 않는 것은
            # 단절이 아니므로 SWM-004 타임아웃을 걸어서는 안 된다.
            self._last_sample_at = now

            # 락을 나가면 이 값들은 더 이상 우리 것이 아니다. 다른 스레드가
            # e-stop·docking·재무장으로 어느 것이든 바꿀 수 있으므로, 이 표본에
            # 대한 판단은 전부 여기서 지역 변수에 담아 나간다.
            ours = self._map_id()
            session = self._session
            formation = self._formation_label(params)
            # D-581: a Fleet-anchored sample lives in our odom frame; its map_id names the
            # site camera map, not ours, so the robot map comparison does not apply to it.
            mismatched = bool(reference.anchor is None and reference.map_id and ours
                              and reference.map_id != ours)
            announce = False
            resumed = False
            spec = None
            join_error: Optional[TrailError] = None

            if mismatched:
                announce = self._map_mismatch != reference.map_id
                self._map_mismatch = reference.map_id
                self._pending = None
                # 프레임이 도착했으니 스트림은 살아 있다. 단절 HOLD 를 그대로
                # 두면 `holding: true` 와 갓 갱신된 `stream_age_s` 가 나란히
                # 보이고, 운영자는 무엇이 멈춘 것인지 알 수 없다. 이유는
                # 이제 map_mismatch 다.
                self._holding = False
            else:
                resumed = self._holding or self._map_mismatch is not None
                self._holding = False
                self._map_mismatch = None
                if params.mode == "trail":
                    join_error = self._feed_trail(reference, params)
                elif (self._last_goal_at is not None
                        and now - self._last_goal_at < _MIN_GOAL_INTERVAL_S):
                    # SWM-002: <=2 Hz. 버리지 않고 들고 있다가 tick 에서 낸다.
                    self._pending = reference
                    return False
                else:
                    self._last_goal_at = now
                    self._pending = None
                    spec = follow_goal(reference, params.distance, params.lateral)

        if mismatched:
            if not announce:
                # 이미 알렸다. 매 프레임 같은 말을 감사 로그에 쌓지 않는다.
                return False
            # 목표를 거둔다. 대형은 살려 둔다 — 리더가 우리 맵으로 돌아오면
            # 새 follow 명령 없이 이어간다. 토큰을 붙여, 그 사이에 운영자가
            # 다시 건 대형의 목표를 대신 거두지 않게 한다.
            self.nav.cancel(source="swarm", close_session=False, session=session)
            self._state.set_swarm(self.status())
            self._events.publish(
                "swarm.hold", severity="warning", source="swarm_manager",
                data={"reason": "map_mismatch", "formation": formation,
                      "reference_map_id": reference.map_id, "map_id": ours})
            return False

        if join_error is not None:
            self.cancel(source="swarm", reason=join_error.code.lower())
            return False
        if resumed:
            self._state.set_swarm(self.status())
        if spec is None:
            return False  # trail: no Nav2 goal, trail_tick steers
        # 락 밖에서 부른다. 취소와 뒤바뀌어도 토큰이 맞지 않으면 저쪽이 버린다.
        return self.nav.moving_goal(spec, source="swarm", session=session)

    def _sample_kind(self, reference: ReferencePose,
                     params: SwarmFollowParams) -> tuple[Optional[str], Optional[str]]:
        """(kind, hold reason). "map": the leader's own map pose. "fleet" (D-581): Fleet put the
        leader into OUR odom frame. Anything else is unusable, with the reason it holds."""
        if reference.anchor is None:
            # Only a pose the leader itself calls "map": "odom" is no place on our map, and a
            # leader that does not say (pre-D-559, or no pose yet) is not trusted for a trail.
            return ("map", None) if reference.frame == "map" else (None, "reference_frame_not_map")
        if (reference.anchor == "fleet" and reference.frame == "odom" and self._robot_id
                and reference.for_robot_id == self._robot_id
                and params.source is SwarmReferenceSource.FLEET):
            # Fleet says it has no anchor now: hold, but the stream (and the leader) is alive.
            return (None, "anchor_withheld") if reference.anchor_hold else ("fleet", None)
        return None, "reference_anchor_invalid"  # another robot's odom, or an unknown anchor

    def _own_pose(self, kind: Optional[str]):
        """Own pose for the trail kind; the last item is its age (s). None = not available."""
        return self._odom() if kind == "fleet" else self._pose()

    def _feed_trail(self, reference: ReferencePose,
                    params: SwarmFollowParams) -> Optional[TrailError]:
        """D-559: one leader sample into the trail. Locked. The error ends the follow."""
        kind, self._ref_bad = self._sample_kind(reference, params)
        if self._ref_bad == "anchor_withheld":
            # The jump bound restarts here: a leader that drove on during a long withhold is
            # not bridged by a straight line afterwards (trail_lost), a short one still is.
            self._trail_sample_at = self._clock()
        if kind is None:
            return None
        self._ref_kind = kind
        if self._trail_kind is not None and kind != self._trail_kind:
            self._trail_broken = "reference_frame_changed"  # latched until a new follow
            return None
        if self._trail is None:
            own = self._own_pose(kind)
            if own is None or (kind == "map" and own[3] != "map"):
                return None  # seeded by a later sample; trail_tick holds meanwhile
            try:
                self._trail = Trail(own[:2], (reference.x, reference.y))
            except TrailError as exc:
                return exc
            self._trail_kind = kind
        else:
            # A jump bounded by how far a robot of our ceiling could drive since the last
            # sample: at 10 Hz anything past 0.3 m is a relocalisation, not driving.
            now = self._clock()
            dt = 0.0 if self._trail_sample_at is None else now - self._trail_sample_at
            jump = 0.3 + self._safety.limits.max_linear * dt
            if not self._trail.add(reference.x, reference.y, reference.yaw, max_jump=jump):
                self._trail_broken = "trail_lost"  # a jump the trail cannot bridge
        self._trail_sample_at = self._clock()
        return None
