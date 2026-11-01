"""FleetConsole 의 대형(FOR-004) 표면 — 세션 열기·재편·재개·정지·리더 인계 (console.py 믹스인).

하는 일 하나: 열려 있는 대형 세션 하나(`_formation`, `_formation_leader`)를 다룬다. 팔로워 판정
(`_formation_members`), 상태, 시작·재편·재개·정지, 죽은 리더의 인계. 상태는 `FleetConsole.__init__` 이
소유하고 이 클래스는 `self` 로 읽고 쓴다. 메서드 이름·시그니처·동작은 console.py 에 있을 때와 같다
(2026-11-01 D-766 크기 래칫 때문에 옮김; 순수 이동).
"""

from __future__ import annotations

import logging

from core_common.succession import next_leader
from fleet.formation.geometry import DEFAULT_SPACING, Formation
from fleet.hub.hub import HubError
from fleet.server.console_view import _formation_stream_evidence
from fleet.swarm.session import FormationSession, FormationSpec, SessionError, SessionState

logger = logging.getLogger("fleet.console")


class FormationControl:
    """Mixin of `FleetConsole`: the one open formation session."""

    def _formation_members(self) -> set:
        """개별 미션을 받으면 안 되는 로봇 = 팔로워.

        **리더는 넣지 않는다.** 대형은 리더를 몰아서 움직이는 것이고(D-20: 오케스트레이션은
        Fleet, 폐루프 추종은 로봇), 리더가 목표를 못 받으면 대형은 무장만 된 채 아무 데도
        가지 못한다. 팔로워는 반대다 - 리더 pose 를 따라가는 중이라 목표를 따로 받으면
        로봇 안에서 두 임자가 같은 바퀴를 두고 다툰다.
        """
        session = self._formation
        if session is None or session.state in (SessionState.STOPPED, SessionState.IDLE):
            return set()
        return set(session.follower_ids)

    def formation_status(self) -> dict:
        """화면이 읽는 대형 상태. 세션이 없으면 `active: False` 하나다."""
        session = self._formation
        if session is None:
            return {"active": False, "state": "IDLE"}
        stats = session.relay.stats() if session.relay is not None else None
        stream_evidence = _formation_stream_evidence(
            stats, self._formation_leader, session.assignment,
        )
        return {
            "active": session.state in (SessionState.ARMING, SessionState.RUNNING,
                                        SessionState.HOLDING),
            "state": session.state.value,
            "leader": self._formation_leader,
            "formation": session.spec.formation.value,
            "spacing": session.spec.spacing,
            "assignment": {rid: {"distance": slot.distance, "lateral": slot.lateral}
                           for rid, slot in session.assignment.items()},
            # HOLDING 인데 이유가 비어 있으면 운영자는 왜 멈췄는지 알 길이 없다.
            "reason": list(session.reason) if session.reason else None,
            "pending_triggers": [list(t) for t in session.pending_triggers],
            "stream_evidence": stream_evidence,
            "anchor": None if (anchor := getattr(session.relay, "anchor", None)) is None else anchor.status(),
            "relay": None if stats is None else {
                "paused": stats.paused,
                "leader_rx_hz": round(stats.leader_rx_hz, 2),
                "leader_age_s": stats.leader_age_s,
                "leader_last_error": stats.leader_last_error,
                "follower_tx": {k: v for k, v in stats.follower_tx.items()},
                "follower_tx_hz": {k: round(v, 2) for k, v in stats.follower_tx_hz.items()},
                "follower_last_tx_age_s": dict(stats.follower_last_tx_age_s),
                "follower_connected": dict(stats.follower_connected),
                # 0 Hz 에 이유가 없으면 화면은 "그냥 멈춘 릴레이"만 보여 준다 — 팔로워
                # 소켓의 마지막 오류가 진단의 첫 줄이다(D-92 값 관례와 무관한 계약).
                "follower_last_error": dict(stats.follower_last_error),
            },
        }

    def _spec(self, formation: str, spacing, max_speed) -> FormationSpec:
        try:
            shape = Formation(formation)
        except ValueError as exc:
            raise HubError("UNKNOWN_FORMATION", f"{formation} is not a formation") from exc
        current = self._formation.spec if self._formation is not None else None
        if max_speed is None:
            max_speed = current.max_speed if current is not None else 0.15
        return FormationSpec(
            formation=shape,
            spacing=DEFAULT_SPACING if spacing is None else spacing,
            max_speed=max_speed,
        )

    async def formation_start(self, leader_id: str, formation: str = "COLUMN",
                              spacing=None, max_speed=None, members=None) -> dict:
        """리더와 선택된 팔로워로 대형을 연다(FOR-001 Robot Selection).

        이미 열려 있으면 거절한다. 조용히 갈아치우면 앞 세션의 팔로워가 무장된 채로
        남고, 그 로봇은 아무도 보내지 않는 참조를 기다리며 서 있게 된다.

        `members` 가 None 이면 등록된 나머지 전원이 팔로워다(기존 동작). 리스트면
        리더를 반드시 포함해야 하고, 그 안의 로봇만 대형에 들어가며 미선택 로봇은
        개별 미션을 계속 받는다.
        """
        if self._formation_members():
            raise HubError("FORMATION_ACTIVE", "a formation is already running; stop it first")
        if members is None:
            follower_ids = [rid for rid in self._order if rid != leader_id]
        else:
            member_ids = list(members)
            if len(set(member_ids)) != len(member_ids):
                raise HubError("MEMBER_DUPLICATED", "a formation lists a robot twice")
            if leader_id not in member_ids:
                raise HubError("LEADER_NOT_IN_MEMBERS",
                               f"leader {leader_id} must be among the selected members")
            unknown = [rid for rid in member_ids if rid not in self._clients]
            if unknown:
                raise HubError("UNKNOWN_ROBOT", f"unknown members: {', '.join(unknown)}")
            follower_ids = [rid for rid in member_ids if rid != leader_id]
        if not follower_ids:
            raise HubError("NO_FOLLOWERS", "a formation needs at least one follower")
        if self._goal_busy.intersection(follower_ids):
            raise HubError("COMMAND_REJECTED", "a follower has a goal pipeline in flight")
        leader = self._client(leader_id)
        followers = [self._clients[rid] for rid in follower_ids]
        kwargs = {"relay_factory": self._relay_factory} if self._relay_factory is not None else {}
        if not kwargs and self.formation_relay_factory is not None:
            kwargs["relay_factory"] = self.formation_relay_factory(lambda: session.spec.formation is Formation.TRAIL)
        member_order = [rid for rid in self._order if rid == leader_id or rid in follower_ids]
        session = FormationSession(leader, followers,
                                   self._spec(formation, spacing, max_speed),
                                   member_order=member_order, **kwargs)
        self._formation = session
        self._formation_leader = leader_id
        try:
            await session.start()
        except SessionError as exc:
            # 세션이 자기 안에서 이미 무장을 되돌렸다. 상태는 남겨 화면이 이유를 읽게 한다.
            raise HubError("ARMING_FAILED", str(exc)) from exc
        return self.formation_status()

    async def _handoff_dead_leader(self, robots: list) -> None:
        """리더 상태가 안 오면 대형을 풀고, 명단의 다음 생존자로 다시 연다.

        팔로워가 각자 다른 리더를 뽑지 않는다. `next_leader` 가 고른 한 명을
        관제가 `formation_start` 로 앉힌다. 살아있는 팔로워가 없으면 풀기만 한다.
        """
        if not self._formation_members():
            return
        leader_id = self._formation_leader
        session = self._formation
        if leader_id is None or session is None:
            return
        rows = {row["robot_id"]: row for row in robots}
        if rows.get(leader_id, {}).get("online"):
            return
        order = [rid for rid in self._order
                 if rid == leader_id or rid in session.assignment]
        dead = {rid for rid in order if not rows.get(rid, {}).get("online")}
        spec = session.spec
        chosen = next_leader(order, dead)
        living = [rid for rid in order if rid not in dead]
        await self.formation_stop()
        if chosen is None:
            return
        try:
            await self.formation_start(
                chosen, formation=spec.formation.value, spacing=spec.spacing,
                max_speed=spec.max_speed, members=living)
        except HubError:
            return

    async def formation_reform(self, formation: str, spacing=None, max_speed=None) -> dict:
        session = self._formation
        if session is None or session.state is SessionState.STOPPED:
            raise HubError("NO_FORMATION", "no formation to reform")
        try:
            await session.reform(self._spec(formation, spacing, max_speed))
        except SessionError as exc:
            raise HubError("REFORM_REFUSED", str(exc)) from exc
        return self.formation_status()

    async def formation_resume(self) -> dict:
        session = self._formation
        if session is None:
            raise HubError("NO_FORMATION", "no formation to resume")
        try:
            await session.resume()
        except SessionError as exc:
            raise HubError("RESUME_REFUSED", str(exc)) from exc
        return self.formation_status()

    async def formation_stop(self) -> dict:
        session = self._formation
        if session is None:
            return {"active": False, "state": "IDLE"}
        await session.stop()
        status = self.formation_status()
        self._formation_leader = None
        return status
