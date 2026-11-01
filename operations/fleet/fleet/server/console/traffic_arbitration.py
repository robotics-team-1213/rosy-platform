"""FleetConsole 의 교통 중재 — 경로 점유·양보·국소화 보류 (console.py 믹스인).

하는 일 하나: 로봇들이 같은 길을 두고 부딪히지 않게 **누가 지금 갈 수 있나**를 정하는 메서드 묶음이다.
계획 경로 읽기, 서 있는 로봇 비키기(`bays`), 대기 미션 풀기, 국소화 신뢰 판정, 군집 속도 조정, 취소.
상태(`_claims`, `_queued`, `_yielding`, `_seen`, `_trusted` …)는 `FleetConsole.__init__` 이 소유하고,
이 클래스는 그 상태를 `self` 로 읽고 쓴다. 메서드 이름·시그니처·동작은 console.py 에 있을 때와 같다
(2026-11-01 D-766 크기 래칫 때문에 옮김; 순수 이동). trip_guard 가 `cancel` 을 인스턴스 속성으로 감싸므로
메서드 해석 순서만 바뀌고 호출 지점은 그대로다.

FleetConsole 은 `goal`/`_goal`(전송 순서)을 소유하고, 이 믹스인의 `_route_of`·`_remember`·`_verdict` 등을 부른다.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional, Sequence

from fleet.hub.hub import HubError
from fleet.localization import trust
from fleet.server import bays, goal_admission, traffic
from fleet.server.observe import observe_states
from fleet.server.degraded_reroute import reroute_degraded
from fleet.swarm.session_arming import require_capability

logger = logging.getLogger("fleet.console")


class TrafficArbitration:
    """Mixin of `FleetConsole`: traffic arbitration, yielding and localization holds."""

    def _intended_route(self, mover: str, route: Sequence, x: float, y: float) -> list:
        """계획 경로. 아직 없으면 지금 자리에서 목표까지 직선으로 대신한다.

        경로는 목표를 받은 **뒤** 계획기가 내야 생긴다. 그 틈에 물으면 빈 목록이 오고,
        빈 목록은 "아무도 안 막는다"로 읽힌다 - 실측에서 폭 1 m 방의 둘째 미션이 그
        틈으로 나가 상대 0.19 m 앞까지 밀고 들어갔다. 관제가 막았다고 말한 통로였다.

        어디로 갈지는 몰라도 **어디서 어디로** 가는지는 안다. 직선은 실제 경로보다
        넓게 잡힐 수 있다. 폭이 넓다고 해서 경로 위의 로봇을 무시하지 않는다 (D-93).
        """
        if route:
            return traffic.thin(list(route))
        here = self._pose_of(mover)
        if here is None:
            return []
        span = math.dist(here, (x, y))
        steps = max(1, int(span / traffic.SAMPLE_STEP_M))
        return [(here[0] + (x - here[0]) * i / steps,
                 here[1] + (y - here[1]) * i / steps) for i in range(steps + 1)]

    def _standing_in_the_way(self, mover: str, route: Sequence, grid,
                             goal: tuple) -> list[str]:
        """이 경로 위에 **서서** 길을 막은 로봇들. 순서로는 풀리지 않는 쪽이다.

        거르는 조건은 하나다 - 달리는 로봇은 뺀다. 그쪽은 경로 대 경로 판정이 이미 봤고,
        곧 지나갈 것을 붙잡고 비켜서라 할 이유가 없다.

        **폭은 묻지 않는다 (D-93).** 한때 "넓으면 알아서 돌아 가니 빼자"는 조건이 있었다.
        실측이 그것을 부정했다 - 6 x 6 m 빈 방에서 마주 오는 두 대가 3 번 다 한가운데에서
        맞물려 섰다. 면제가 성립하는 폭은 없다.

        과잉 개입을 막는 것은 **경로 자체**다. 계획 경로는 이미 아는 장애물을 피해 나오므로,
        넓은 곳에 선 로봇 옆으로는 애초에 0.45 m 안을 지나지 않는다. 그런데도 지난다면
        돌아갈 자리가 없다는 뜻이고, 그때는 중재가 맞다.

        "길을 막았다"의 반경은 `_route_still_occupied` 가 "이제 비켰다"를 판단하는 반경과
        **같은 값**이어야 한다. 경로 대 경로의 `clearance_m`(0.7) 을 여기 쓰면, 0.45 만
        비켜선 로봇이 다시 "막고 있다"로 잡혀 벽감에서 또 밀려난다 - 로봇 하나가 맵
        바깥으로 밀려날 때까지 이 왕복이 이어진다.
        """
        if not route:
            return []
        out = []
        here = self._pose_of(mover)
        for robot_id in self._order:
            if (robot_id == mover or robot_id in self._claims
                    or self._verdict(robot_id) == trust.UNTRUSTED):
                continue
            pose = self._pose_of(robot_id)
            if pose is None:
                continue
            if here is not None and traffic.coincident(pose, here):
                # 출발점과 같은 보고는 길을 막은 로봇이 아니라 측위가 안 된 겹침이다 (D-116).
                continue
            nearest = bays.nearest_on_route(route, pose)
            if nearest is None or math.dist(nearest, pose) >= self._yield_keep_out_m:
                continue
            if grid is None and math.dist(pose, goal) >= self._goal_blocked_m:
                # 맵이 없으면 중재할 수 없다 - 비켜설 자리를 고를 근거가 없으므로, 여기서
                # 막으면 모든 미션이 이유 없이 대기열로 간다. 로봇 쪽 지역 코스트맵은
                # 살아 있으니 그쪽에 맡긴다.
                #
                # 예외는 **목표를 깔고 앉은 경우**다. 그 자리에 두 대가 설 수 없다는 것은
                # 맵을 몰라도 참이고, 보내 봐야 도착하지 못한다.
                continue
            out.append(robot_id)
        return out

    async def _make_room(self, mover: str, x: float, y: float, yaw: float,
                         route: Sequence, standing: Sequence[str], *,
                         task_id: str | None = None, attempt_id: str | None = None,
                         attempt_seq: int | None = None) -> dict:
        """길을 막고 선 로봇들을 비켜세우고, 미션은 자리가 날 때까지 세워 둔다.

        미션을 실패로 돌려주지 않는 이유가 있다. 비켜서기는 몇 초짜리 동작이고, 그 몇 초
        때문에 운영자가 같은 미션을 다시 내려야 한다면 관제가 일을 떠넘기는 것이다.
        비켜설 자리가 없을 때도 마찬가지로 세워 둔다 - 다만 이유를 `NO_YIELD_SPACE` 로
        적어, 사람이 손을 대야 풀린다는 것을 화면이 말하게 한다.
        """
        standing = list(standing)
        stop = self.goal_leases.stop_token(mover)
        grid = bays.Grid.from_payload(await self.map())
        self.goal_leases.check_stop(mover, stop)
        yielded, no_space = [], []
        for robot_id in standing:
            pose = self._pose_of(robot_id)
            # 거리장 계산은 맵이 크면 몇백 ms(40x40 m, 20 m 경로에서 0.38 s)라 이벤트 루프 밖에서 돈다.
            # 제 목표를 받고 교통 판정을 기다리는 로봇은 비켜세울 수 없다(_send_to_bay 거절) - 자리 없음으로 기다린다.
            bay = None if pose is None or self.trip_busy(robot_id) or robot_id in self._goal_busy else await asyncio.to_thread(
                bays.best_bay, grid, route, pose, keep_out_m=self._yield_keep_out_m)
            self.goal_leases.check_stop(mover, stop)
            if bay is None:
                no_space.append(robot_id)
                continue
            await self._send_to_bay(robot_id, bay, mover)
            self.goal_leases.check_stop(mover, stop)
            yielded.append(robot_id)

        stop = (stop[0], stop[1] + 1)
        cancel_receipt = await self.goal_leases.cancel(mover, self._client(mover))
        self.goal_leases.check_stop(mover, stop)
        if not self._cancel_confirmed(cancel_receipt):
            raise RuntimeError("navigation goal cancellation was not confirmed")
        self._goals.pop(mover, None)
        self._claims.pop(mover, None)
        reason = "NO_YIELD_SPACE" if no_space else "YIELDING"
        blocked_by = (no_space or yielded)[0]
        decision = goal_admission.standing_hold(blocked_by, standing, reason, route)
        self._queued[mover] = goal_admission.mission_of(
            decision, x, y, yaw, task_id=task_id, attempt_id=attempt_id,
            attempt_seq=attempt_seq)
        return {**goal_admission.response_of(decision),
                "yielding": yielded, "no_space": no_space}

    async def _send_to_bay(self, robot_id: str, bay: tuple, mover: str) -> None:
        if robot_id in self._goal_busy:
            raise HubError("COMMAND_REJECTED", f"{robot_id} has a goal pipeline in flight")
        self._goal_busy.add(robot_id)
        try:
            await self._bay_goal(robot_id, bay, mover)
        finally:
            self._goal_busy.discard(robot_id)

    async def _bay_goal(self, robot_id: str, bay: tuple, mover: str) -> None:
        """한 대를 비켜설 자리로. 제 미션이 있었다면 대기열에 넣어 돌아오게 한다."""
        client = self._client(robot_id)
        stop = self.goal_leases.stop_token(robot_id)
        mover_stop = self.goal_leases.stop_token(mover)
        caps = await require_capability(client, "navigation.goal_navigation")
        if self._clients.get(robot_id) is not client:
            raise RuntimeError("robot connection changed during capability check")
        if stop != self.goal_leases.stop_token(robot_id):
            raise HubError("COMMAND_REJECTED", f"{robot_id} stopped during yield admission")
        if robot_id in self._formation_members():
            raise HubError("FORMATION_ACTIVE", f"{robot_id} joined a formation while planning a yield")
        if busy := self.trip_refusal([robot_id]):
            raise busy
        self.goal_leases.check_stop(mover, mover_stop)
        try:
            result = await self.goal_leases.send(robot_id, client, caps, bay[0], bay[1], 0.0, None, "yield")
        except (Exception, asyncio.CancelledError):
            if mover_stop != self.goal_leases.stop_token(mover):
                try:
                    await self.goal_leases.cancel(robot_id, client)
                except Exception:
                    logger.exception("abandoned bay cancel for %s failed", robot_id)
            raise
        if mover_stop != self.goal_leases.stop_token(mover):
            await self.goal_leases.cancel(robot_id, client)
            self.goal_leases.check_stop(mover, mover_stop)
        if result["accepted"] is False:
            raise RuntimeError("navigation yield goal was rejected")
        own = self._goals.pop(robot_id, None)
        if own is not None and robot_id not in self._queued:
            # 비켜서는 것은 잠깐 물러나는 것이지 미션 취소가 아니다. 지나가는 대가 끝나면
            # 제 목표로 돌아간다 - 그러지 않으면 운영자가 보낸 곳에서 로봇이 사라진다.
            self._queued[robot_id] = {**own, "blocked_by": mover, "waiting_on": [mover],
                                      "reason": "YIELDED"}
        self._claims.pop(robot_id, None)
        self._yielding[robot_id] = {"bay": {"x": bay[0], "y": bay[1]}, "for": mover}

    async def _observe(self) -> None:
        """미션을 내리는 순간의 좌표 읽기 — 활동/대기 로봇의 읽기 선택은 `observe.py`."""
        await observe_states(self)

    def _remember(self, robots: Sequence[dict]) -> None:
        for row in robots:
            if row["robot_id"] not in self._clients:
                continue
            state = row.get("state") or {}
            if state:
                robot_id = row["robot_id"]
                self._seen[robot_id] = state
                if self._state_sink is not None:
                    try:
                        self._state_sink(robot_id, state)
                    except Exception:   # never let the sink skip the trust update below
                        logger.debug("state sink failed for %s", robot_id, exc_info=True)
                if state.get("localization") is not None:
                    self._loc_null_since[robot_id] = None
                elif robot_id in self._loc_null_since:
                    since = self._loc_null_since[robot_id]
                    if since is None:
                        self._loc_null_since[robot_id] = self._clock()
                    elif self._clock() - since >= trust.LAPSED_GRACE_S:
                        # Expire the stale position; missing localization remains untrusted.
                        del self._loc_null_since[robot_id]
                        self._trusted.pop(robot_id, None)
                trusted = trust.trusted_xy(state)
                if trusted is not None:
                    self._trusted[robot_id] = trusted

    def _lapsed(self, robot_id: str) -> bool:
        """A robot that reported localization and is null inside its grace (a CORE restart)."""
        return self._loc_null_since.get(robot_id) is not None

    async def trusted_map_pose(self, robot_id: str) -> Optional[tuple[float, float, Optional[float]]]:
        """Fresh ``(x, y, yaw or None)`` only when this snapshot is LOCALIZED in the map frame.

        A legacy snapshot, an odom pose, and a lapsed D-395 robot are not a
        lane-route pose (D-463). Remembering the row keeps a following goal
        on the same verdict as the pose just read.
        """
        state, _source = await self._gather_state(robot_id)
        self._remember([{"robot_id": robot_id, "state": state or {}}])
        if self._verdict(robot_id) != trust.TRUSTED:
            return None
        pose = (state or {}).get("pose") or {}
        try:
            x, y = float(pose["x"]), float(pose["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        try:
            yaw = float(pose["yaw"])
        except (KeyError, TypeError, ValueError):
            yaw = None
        return x, y, (yaw if yaw is not None and math.isfinite(yaw) else None)

    def _verdict(self, robot_id: str) -> str:
        """Trust only an explicit LOCALIZED map snapshot."""
        return trust.classify(self._seen.get(robot_id))

    def _untrusted_blocks(self, robot_id: str, route: Sequence) -> bool:
        return (self._verdict(robot_id) == trust.UNTRUSTED
                and trust.blocks(route, self._trusted.get(robot_id)))

    def _pose_of(self, robot_id: str) -> Optional[tuple]:
        if self._verdict(robot_id) == trust.UNTRUSTED:
            return self._trusted.get(robot_id)        # D-395 P2-2: skip the untrusted pose
        pose = (self._seen.get(robot_id) or {}).get("pose") or {}
        try:
            return float(pose["x"]), float(pose["y"])
        except (KeyError, TypeError, ValueError):
            # 좌표를 모르는 로봇은 길을 막았다고도 비켰다고도 말할 수 없다.
            return None

    async def _route_of(self, robot_id: str) -> list:
        """계획 경로. 읽지 못하면 빈 목록이다 — 모른다는 이유로 미션을 막지 않는다."""
        try:
            return traffic.route_points(await self._client(robot_id).navigation_path())
        except Exception:
            return []

    async def _manage_swarm_speed(self, robots: list) -> None:
        """ADR-1000: Down-sync swarm speed to the slowest degraded robot (FOR-004)."""
        session = self._formation
        if session is None or session.state != "RUNNING":
            return

        degraded_members = [
            row["robot_id"] for row in robots
            if row.get("state") and row["state"].get("capabilities_degraded")
            and row["robot_id"] in self._formation_members()
        ]

        if not degraded_members:
            return

        # If any member is degraded, reform the swarm with a lower speed limit
        # This is a naive implementation that halves the current speed
        current_speed = session.spec.max_speed
        degraded_speed = max(0.05, current_speed * 0.5)

        # We only want to reform once when degradation is detected
        if current_speed > degraded_speed + 0.01:
            try:
                await self.formation_reform(
                    formation=session.spec.formation, max_speed=degraded_speed)
            except Exception as exc:
                # 조용한 no-op 는 ADR-1000 을 죽인다 — 실패는 보이게, 재시도
                # 폭주는 current_speed 가득 가드가 이미 막는다.
                logger.warning("auto speed reform failed: %s", exc)

    async def _run_traffic(self, robots: list) -> None:
        """스냅샷마다 한 번: 끝난 로봇의 점유를 풀고, 풀린 자리의 대기 미션을 내려보낸다."""
        degraded = await reroute_degraded(self, robots)  # ADR-1000 MSN-004

        for row in robots:
            state = row.get("state") or {}
            if state.get("navigation") != "NAVIGATING" and row["robot_id"] not in self._held:
                self._claims.pop(row["robot_id"], None)
        for robot_id in sorted(self._yielding):
            # 비켜설 이유가 사라졌으면 표시도 지운다. 남겨 두면 그 로봇은 다음 미션을
            # 계속 대기열로 돌리고, 화면은 끝난 양보를 계속 진행 중으로 보여 준다.
            waiting_for = self._yielding[robot_id]["for"]
            if waiting_for not in self._claims and waiting_for not in self._queued:
                self._yielding.pop(robot_id, None)
        release_candidates = []
        for robot_id in sorted(self._queued):
            mission = self._queued[robot_id]
            if self._still_blocked(mission):
                if mission.get("reason") == "YIELDING":
                    self._check_yield_worked(mission)
                continue
            # 저하 로봇에게 즉석 목표를 다시 보내지 않는다. 작업 목표는 작업 대기열로 돌아가 재배정된다.
            if robot_id in degraded and mission.get("task_id") is None:
                continue
            release_candidates.append(robot_id)
        # 한 번에 여러 대가 풀리면 순서를 정한다 — 로터리 선착. 점유 클레임은 상한선으로
        # 남는다(달리는 로봇은 이 순서와 무관하게 이긴다. 여기서 고르는 것은 대기자
        # 사이의 순서다).
        for robot_id in self._release_order(release_candidates):
            # A roster removal may land between the awaits below (D-361 5).
            mission = self._queued.pop(robot_id, None)
            if mission is None or robot_id not in self._clients:
                continue
            if mission.get("task_id") is not None:
                if self._task_queue_release_callback is None:
                    self._queued[robot_id] = mission
                    continue
                try:
                    await self._task_queue_release_callback(dict(mission))
                except Exception:
                    self._queued[robot_id] = mission
                continue
            try:
                await self.goal(robot_id, mission["x"], mission["y"], mission["yaw"])
            except Exception:
                # 재하달이 실패하면 대기열에 되돌린다. 조용히 사라지면 운영자는 자기가
                # 내린 미션이 어디로 갔는지 알 수 없다.
                self._queued[robot_id] = mission

    def _release_order(self, candidates: Sequence[str]) -> list[str]:
        """대기 미션을 푸는 순서. 공유 충돌 지점까지 남은 경로 거리가 짧은 미션이 먼저
        나간다 — 도로의 선착 우권이다.

        점유 클레임은 이 순서 위에 있다. 달리는 로봇(클레임 있는 로봇)은 결코 여기서
        밀려나지 않고, 고르는 것은 대기자들 사이의 순서다. 거리를 모르면(경로나 좌표
        없음) 무한대로 밀려 robot_id 순으로 떨어진다 - 같은 상황이면 늘 같은 순서여야
        운영자가 화면을 읽을 수 있다.
        """
        def key(robot_id: str) -> tuple[float, str]:
            best = math.inf
            mine = self._queued[robot_id]
            mine_route = mine.get("route") or []
            mine_pose = self._pose_of(robot_id)
            for other in candidates:
                if other == robot_id:
                    continue
                pair = traffic.closest_points(mine_route, self._queued[other].get("route") or [])
                if pair is None:
                    continue
                d = traffic.remaining_distance(mine_route, mine_pose, pair[0])
                if d is not None and d < best:
                    best = d
            return (best, robot_id)

        return sorted(candidates, key=key)

    def _still_blocked(self, mission: dict) -> bool:
        """이 대기 미션이 아직 나가면 안 되는가. 묻기만 하고 아무것도 바꾸지 않는다.

        **비켜서기를 기다리는 미션은 기하로만 판단한다.** 남이 비켜 주기를 기다리는 A 와
        A 가 지나가기를 기다리는 B 는 서로를 블로커로 가리킨다 - "앞이 대기열에 있으면
        기다린다"를 양쪽에 걸면 둘 다 영원히 선다. A 는 "내 경로가 비었는가"만 보고,
        B 는 A 가 나간 뒤 A 의 점유가 풀리기를 기다린다. 그래서 고리가 끊긴다.
        """
        if mission.get("reason") in ("YIELDING", "NO_YIELD_SPACE"):
            return self._route_still_occupied(mission)
        if mission.get("reason") == "LOCALIZATION_UNTRUSTED":
            # No route: the mover itself was unlocalized; any route: a robot in its way is.
            return (self._verdict(mission["blocked_by"]) == trust.UNTRUSTED
                    if "route" not in mission
                    else self._untrusted_blocks(mission["blocked_by"], mission["route"]))
        blocker = mission["blocked_by"]
        # 앞이 아직 못 나갔으면 그 뒤도 못 나간다. 점유만 보면, 대기열에 들어간 순간
        # 점유가 없는 블로커를 "끝났다"고 읽고 뒤가 먼저 튀어 나간다.
        return blocker in self._claims or blocker in self._queued

    def _check_yield_worked(self, mission: dict) -> None:
        """비켜섰는데도 길이 안 열렸으면, 화면이 그렇게 말하게 한다.

        **이유를 바꾸는 것 말고는 아무것도 하지 않는다.** 로봇을 더 밀어내지 않는 이유는,
        한 번 비켜서고도 부족했다는 것이 곧 이 맵에 자리가 없다는 뜻이기 때문이다. 더
        멀리 보내면 벽에 붙을 때까지 같은 일이 반복된다.

        이 검사가 없으면 화면은 "물러나면 자동 출발합니다"를 영원히 띄운다 - 실측에서
        2x1 m 방의 두 대가 그 문장 아래서 한없이 서 있었다. 대기 자체는 맞다(물리가
        그렇다). 거짓말은 곧 풀린다고 말한 쪽이다.
        """
        if any((self._seen.get(rid) or {}).get("navigation") == "NAVIGATING"
               for rid in mission.get("waiting_on", [])):
            return          # 아직 비켜서는 중이다
        # 상태가 아직 안 올라온 첫 몇 틱을 "멈췄다"로 읽지 않는다.
        mission["settled_ticks"] = mission.get("settled_ticks", 0) + 1
        if mission["settled_ticks"] >= self._yield_grace_ticks:
            mission["reason"] = "NO_YIELD_SPACE"

    def _route_still_occupied(self, mission: dict) -> bool:
        """비켜서라고 한 로봇들이 아직 내 경로 위에 있는가."""
        route = mission.get("route") or []
        if not route:
            return False
        for robot_id in mission.get("waiting_on", []):
            if (self._seen.get(robot_id) or {}).get("navigation") == "NAVIGATING":
                return True          # 아직 비켜서는 중이다
            pose = self._pose_of(robot_id)
            if pose is None:
                continue
            nearest = bays.nearest_on_route(route, pose)
            if nearest is not None and math.dist(nearest, pose) < self._yield_keep_out_m:
                return True
        return False

    async def cancel(self, robot_id: str) -> dict:
        result = await self.goal_leases.cancel(robot_id, self._client(robot_id))
        self._goals.pop(robot_id, None)
        self._held.get(robot_id) or self._claims.pop(robot_id, None)  # D-361: held keeps its claim
        self._queued.pop(robot_id, None)
        self._yielding.pop(robot_id, None)
        return result

    async def hold_for_localization(self, mover: str) -> list[str]:
        """D-395 P2-7: before CORE moves an unlocalized `mover`, stop the Fleet-driven robots
        its keep-out reaches (`trust.blocks`, the whole track when it was never trusted).
        Each held goal waits as LOCALIZATION_UNTRUSTED behind the mover until it is trusted; a
        yield whose way to its bay crosses the keep-out is cancelled, and so is a formation
        with a robot in it (stopped whole: its session has no per-robot hold)."""
        held, last = [], self._trusted.get(mover)
        for robot_id in list(self._order):
            goal = self._goals.get(robot_id)
            here = self._pose_of(robot_id)
            route = ([here] if here is not None else []) + list(self._claims.get(robot_id) or [])
            if robot_id == mover or goal is None or not trust.blocks(route, last):
                continue
            if not self._cancel_confirmed(await self.goal_leases.cancel(robot_id, self._client(robot_id))):
                raise RuntimeError("navigation goal cancellation was not confirmed")
            self._goals.pop(robot_id, None)
            self._claims.pop(robot_id, None)
            self._queued[robot_id] = {**goal, "blocked_by": mover, "waiting_on": [mover],
                                      "reason": "LOCALIZATION_UNTRUSTED"}
            held.append(robot_id)
        for robot_id, yielding in list(self._yielding.items()):     # on the way to a bay
            here, bay = self._pose_of(robot_id), (yielding["bay"]["x"], yielding["bay"]["y"])
            if robot_id == mover or not trust.blocks(([here] if here else []) + [bay], last):
                continue
            if not self._cancel_confirmed(await self.goal_leases.cancel(robot_id, self._client(robot_id))):
                raise RuntimeError("navigation goal cancellation was not confirmed")
            self._yielding.pop(robot_id, None)
            held.append(robot_id)
        riders = self._formation_members() | ({self._formation_leader} - {None})
        if riders and (last is None or any(p is not None and trust.blocks([p], last)
                                           for p in map(self._pose_of, riders))):
            await self.formation_stop()
            held.append("formation")
        return held
