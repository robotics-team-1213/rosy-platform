"""FormationSession — 무장은 전부 아니면 전무, HOLD 는 릴레이를 멈추는 것(D-35 후보),
재개는 운영자만 한다."""

import asyncio

import pytest
from fakes import END, FakeRelay, FakeRobot, run, settle

from core_common.protocol.schemas import RobotMode, SwarmFollowParams
from fleet.formation.geometry import Formation, SlotOffset
from fleet.swarm.session import (
    ArmingFailed,
    FormationSession,
    FormationSpec,
    HoldPolicy,
    MapMismatch,
    SessionError,
    SessionState,
)
from fleet.swarm.transport import RobotApiError


def _robots(n=2, log=None, leader_pose=(0.0, 0.0, 0.0)):
    log = log if log is not None else []
    leader = FakeRobot("rosy_01", log=log, state={
        "robot_id": "rosy_01", "map_id": "m1",
        "pose": {"x": leader_pose[0], "y": leader_pose[1], "yaw": leader_pose[2]}})
    followers = [FakeRobot(f"rosy_{i:02d}", log=log) for i in range(2, 2 + n)]
    return leader, followers, log


async def _no_sleep(_s):
    await asyncio.sleep(0)


def _session(leader, followers, spec=None, log=None, **kw):
    spec = spec or FormationSpec(Formation.COLUMN, spacing=0.6)
    kw.setdefault("sleep", _no_sleep)
    return FormationSession(leader, followers, spec,
                            relay_factory=lambda ld, f, **_: FakeRelay(ld, f, log=log), **kw)


def _follows(robot):
    return [c[1] for c in robot.calls if c[0] == "follow"]


def test_start_opens_the_streams_and_then_arms_every_follower_with_its_slot():
    """D-132 — 무장은 스트림이 연 뒤에 한다. follow 의 1 s 시계를 릴레이와 경주시키지 않는다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        assert s.state is SessionState.RUNNING
        params = {f.robot_id: _follows(f)[0] for f in followers}
        assert all(isinstance(p, SwarmFollowParams) for p in params.values())
        assert {p.target_robot_id for p in params.values()} == {"rosy_01"}
        assert sorted(p.distance for p in params.values()) == [0.6, 1.2]
        assert all(p.max_speed == 0.15 and p.stream_timeout_ms == 1000 for p in params.values())
        kinds = [entry[1] for entry in log if entry[0] == "relay" or entry[1] == "follow"]
        assert kinds.index("start") < min(i for i, k in enumerate(kinds) if k == "follow")
        await s.stop()
    run(main())


def test_the_nearest_follower_takes_the_nearest_slot():
    async def main():
        leader, followers, log = _robots(2)
        # V, spacing 0.6: 슬롯은 리더 뒤 0.6, 좌 +0.6 / 우 −0.6. rosy_02 는 왼쪽에 있다.
        followers[0]._state["pose"] = {"x": -0.6, "y": 0.6, "yaw": 0.0}
        followers[1]._state["pose"] = {"x": -0.6, "y": -0.6, "yaw": 0.0}
        s = _session(leader, followers, spec=FormationSpec(Formation.V, spacing=0.6), log=log)
        await s.start()
        assert s.assignment["rosy_02"] == SlotOffset(0.6, 0.6)
        assert s.assignment["rosy_03"] == SlotOffset(0.6, -0.6)
        await s.stop()
    run(main())


def test_one_refused_follow_cancels_the_ones_already_armed_and_stops_the_streams():
    async def main():
        leader, followers, log = _robots(2)
        followers[1].follow_error = RobotApiError("rosy_03", 409, "DOCKING_ACTIVE", "busy")
        s = _session(leader, followers, log=log)
        with pytest.raises(ArmingFailed) as exc:
            await s.start()
        assert exc.value.robot_id == "rosy_03" and exc.value.code == "DOCKING_ACTIVE"
        assert ("swarm_cancel",) in followers[0].calls
        # D-132 — 스트림은 무장보다 먼저 열렸다. 거절이면 끝까지 책임진다.
        assert ("relay", "start") in log and ("relay", "stop") in log
        assert s.state is SessionState.STOPPED
    run(main())


def test_a_map_mismatch_is_refused_before_any_follow():
    async def main():
        leader, followers, log = _robots(2)
        followers[1]._state["map_id"] = "other"
        s = _session(leader, followers, log=log)
        with pytest.raises(MapMismatch):
            await s.start()
        assert not any(_follows(f) for f in followers)
    run(main())


def test_a_robot_without_a_map_id_does_not_block_the_start():
    async def main():
        leader, followers, log = _robots(2)
        followers[1]._state["map_id"] = None
        s = _session(leader, followers, log=log)
        await s.start()
        assert s.state is SessionState.RUNNING
        await s.stop()
    run(main())


@pytest.mark.parametrize("event_type", ["nav.stuck", "nav.failed", "nav.blocked",
                                        "swarm.aborted", "safety.estop"])
def test_each_for_004_trigger_pauses_the_relay_and_cancels_the_leader(event_type):
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": event_type, "robot_id": "rosy_02", "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        assert s.reason == (event_type, "rosy_02")
        assert s.relay.paused
        assert ("navigation_cancel",) in leader.calls
        assert log.index(("relay", "pause")) < log.index(("rosy_01", "navigation_cancel"))
        await s.stop()
    run(main())


def test_a_trigger_on_the_leader_counts_too():
    async def main():
        leader, followers, log = _robots(1)
        s = _session(leader, followers, log=log)
        await s.start()
        leader.event_frames.put_nowait({"type": "nav.failed", "robot_id": "rosy_01", "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        await s.stop()
    run(main())


def test_swarm_hold_is_not_a_trigger_and_holding_keeps_further_triggers_for_the_operator():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "swarm.hold", "robot_id": "rosy_02",
                                              "data": {"reason": "map_mismatch"}})
        await settle()
        assert s.state is SessionState.RUNNING
        followers[0].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_02", "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        cancels = leader.calls.count(("navigation_cancel",))
        followers[1].event_frames.put_nowait({"type": "swarm.hold", "robot_id": "rosy_03",
                                              "data": {"reason": "reference stream lost"}})
        followers[1].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_03", "data": {}})
        await settle()
        assert leader.calls.count(("navigation_cancel",)) == cancels   # 두 번 세우지 않는다
        assert s.pending_triggers == [("nav.stuck", "rosy_03")]        # 버리지도 않는다
        await s.stop()
    run(main())


def test_resume_is_the_only_way_back_to_running():
    async def main():
        leader, followers, log = _robots(1)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02", "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        await settle(50)
        assert s.state is SessionState.HOLDING            # 시간이 지나도 스스로 돌아오지 않는다
        await s.resume()
        assert s.state is SessionState.RUNNING and not s.relay.paused and s.reason is None
        await s.resume()                                   # RUNNING 에서 resume 은 무해하다
        assert s.state is SessionState.RUNNING
        await s.stop()
    run(main())


def test_the_abort_policy_cancels_every_follower_and_ends_the_session():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log, policy=HoldPolicy.ABORT)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_02", "data": {}})
        await settle()
        assert s.state is SessionState.STOPPED
        assert all(("swarm_cancel",) in f.calls for f in followers)
        assert ("navigation_cancel",) in leader.calls
        assert s.relay.stopped
        await s.stop()
    run(main())


def test_reform_pauses_rearms_with_the_new_offsets_and_resumes():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        mark = len(log)
        await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        tail = log[mark:]
        # 릴레이에 처음 일어나는 일이 pause 이고, 그것이 첫 follow 앞이다. "로그의 맨
        # 첫 줄이 pause" 는 더 이상 참이 아니다 — 사전 점검(state 읽기)이 먼저 오고,
        # 그래야 거절되는 reform 이 릴레이를 만지지 않는다.
        relay_kinds = [e[1] for e in tail if e[0] == "relay"]
        assert relay_kinds[0] == "pause"
        first_pause = next(i for i, e in enumerate(tail) if e == ("relay", "pause"))
        first_follow = next(i for i, e in enumerate(tail) if e[1] == "follow")
        assert first_pause < first_follow
        assert tail[-1] == ("relay", "resume")
        second = {f.robot_id: _follows(f)[1] for f in followers}
        assert sorted(p.lateral for p in second.values()) == [-0.6, 0.6]
        assert all(p.distance == 0.0 for p in second.values())
        assert s.state is SessionState.RUNNING
        await s.stop()
    run(main())


def test_a_failed_reform_ends_the_session_because_half_a_formation_cannot_be_resumed():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[1].follow_error = RobotApiError("rosy_03", 409, "EMERGENCY_ACTIVE", "estop")
        with pytest.raises(ArmingFailed):
            await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        # 재무장된 팔로워는 이미 풀렸고 나머지는 옛 오프셋을 쥐고 있다. 그 상태로 스트림을
        # 다시 켜면 대형이 둘로 갈린다 — HOLD 가 아니라 종료가 정직하다.
        assert s.state is SessionState.STOPPED
        assert s.reason[0].startswith("reform_failed")
        assert all(("swarm_cancel",) in f.calls for f in followers)
        assert ("navigation_cancel",) in leader.calls
        assert s.relay.stopped
        await s.stop()
    run(main())


def test_stop_cancels_every_follower_and_stops_the_relay():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        await s.stop()
        assert s.state is SessionState.STOPPED
        assert all(("swarm_cancel",) in f.calls for f in followers)
        assert ("navigation_cancel",) not in leader.calls     # 리더 항법은 운영자의 것
        assert s.relay.stopped
    run(main())


def test_an_events_socket_that_drops_is_reopened_and_a_follower_found_inactive_is_an_abort():
    async def main():
        leader, followers, log = _robots(1)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0]._swarm_state = {"active": False, "holding": False}
        followers[0].event_frames.put_nowait(END)          # 이벤트 소켓 단절
        await settle(40)
        assert followers[0].event_opens >= 2
        assert s.state is SessionState.HOLDING
        assert s.reason == ("swarm.aborted", "rosy_02")
        await s.stop()
    run(main())


def test_a_quietly_closed_events_socket_is_reopened_with_backoff_not_a_tight_loop():
    async def main():
        sleeps = []

        async def sleep(s):
            sleeps.append(s)
            await asyncio.sleep(0)

        leader, followers, log = _robots(1)
        s = FormationSession(leader, followers, FormationSpec(Formation.COLUMN, spacing=0.6),
                             relay_factory=lambda ld, f, **_: FakeRelay(ld, f, log=log), sleep=sleep)
        await s.start()
        for _ in range(4):
            followers[0].event_frames.put_nowait(END)     # 소켓이 조용히 닫힌다, 반복해서
            await settle(10)
        follower_sleeps = [x for x in sleeps if x > 0]
        assert len(follower_sleeps) >= 3                 # 매번 기다린다
        assert follower_sleeps[1] > follower_sleeps[0]   # 커진다
        assert max(follower_sleeps) <= 2.0
        await s.stop()
    run(main())


# --- 무장 중에 걸린 트리거, 끝난 세션의 감시, 되돌려지지 않은 무장 -------------------


def test_a_hold_trigger_that_lands_while_rearming_is_not_erased_by_the_reform():
    """무장은 await 여러 개짜리 구간이다. 그 사이에 걸린 HOLD 를 재개가 지우면 안 된다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        gate = asyncio.Event()
        followers[0].follow_gate = gate                  # 재무장이 여기서 멈춘다
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        followers[1].event_frames.put_nowait({"type": "safety.estop", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING           # 무장 중에 걸렸다
        gate.set()
        await task                                       # reform 은 정상 반환한다
        assert s.state is SessionState.HOLDING           # 그러나 재개하지는 않는다
        assert s.relay.paused
        assert s.reason == ("safety.estop", "rosy_03")
        assert all(len(_follows(f)) == 2 for f in followers)   # 새 오프셋 무장은 살린다
        assert all(_follows(f)[1].distance == 0.0 for f in followers)
        assert leader.calls.count(("navigation_cancel",)) == 1
        await s.stop()
    run(main())


def test_an_abort_that_lands_while_rearming_disarms_the_robots_the_reform_just_armed():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log, policy=HoldPolicy.ABORT)
        await s.start()
        gate = asyncio.Event()
        followers[0].follow_gate = gate
        before = {f.robot_id: f.calls.count(("swarm_cancel",)) for f in followers}
        watchers = list(s._watchers)          # abort 는 목록을 비운다 — 그 전에 잡아 둔다
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        followers[1].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.STOPPED
        gate.set()
        with pytest.raises(SessionError):
            await task                                   # 재개하지 않고 끝난다
        assert s.state is SessionState.STOPPED
        assert s.relay.stopped
        # 죽은 릴레이를 보고 있는 팔로워를 남기지 않는다 — 재무장분까지 다시 푼다.
        for f in followers:
            assert f.calls.count(("swarm_cancel",)) - before[f.robot_id] >= 2
        last_follow = max(i for i, c in enumerate(followers[0].calls) if c[0] == "follow")
        assert ("swarm_cancel",) in followers[0].calls[last_follow:]
        await settle()
        assert watchers and all(t.done() for t in watchers)
    run(main())


def test_an_aborted_session_lets_go_of_its_event_sockets():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log, policy=HoldPolicy.ABORT)
        await s.start()
        watchers = list(s._watchers)          # abort 는 목록을 비운다 — 그 전에 잡아 둔다
        followers[0].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.STOPPED
        assert watchers and all(t.done() for t in watchers)
        opens = {f.robot_id: f.event_opens for f in followers}
        followers[1].event_frames.put_nowait(END)        # 끝난 세션은 소켓을 다시 열지 않는다
        await settle(40)
        assert {f.robot_id: f.event_opens for f in followers} == opens
        await s.stop()
    run(main())


def test_an_arming_failure_with_an_unknown_outcome_also_disarms_the_robot_that_did_not_answer():
    async def main():
        leader, followers, log = _robots(2)
        followers[1].follow_error = ConnectionError("socket died mid-call")
        s = _session(leader, followers, log=log)
        with pytest.raises(ArmingFailed) as exc:
            await s.start()
        assert exc.value.robot_id == "rosy_03" and exc.value.code == "TRANSPORT"
        # 타임아웃 뒤에 로봇이 follow 를 받아 놓았을 수 있다. 거절과 달리 결과를 모른다.
        assert ("swarm_cancel",) in followers[1].calls
        assert ("swarm_cancel",) in followers[0].calls
        assert s.state is SessionState.STOPPED
    run(main())


def test_a_follower_that_left_the_formation_while_holding_blocks_resume_until_a_reform():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        followers[1]._swarm_state = {"active": False, "holding": False}
        followers[1].event_frames.put_nowait(END)        # 이벤트 소켓 단절 → reconcile
        await settle(40)
        assert s.pending_triggers == [("swarm.aborted", "rosy_03")]
        with pytest.raises(SessionError):
            await s.resume()                             # 반쪽 대형으로 스트림을 켜지 않는다
        assert s.state is SessionState.HOLDING
        followers[1]._swarm_state = {"active": True, "holding": False}
        await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        assert s.state is SessionState.RUNNING           # 재무장이 그것을 처리했다
        assert s.pending_triggers == []
        assert not s.relay.paused
        await s.stop()
    run(main())


def test_a_second_trigger_while_holding_is_kept_and_only_a_reform_clears_it():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        cancels = leader.calls.count(("navigation_cancel",))
        followers[1].event_frames.put_nowait({"type": "safety.estop", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.pending_triggers == [("safety.estop", "rosy_03")]
        assert leader.calls.count(("navigation_cancel",)) == cancels
        assert s.reason == ("nav.blocked", "rosy_02")    # 첫 사유는 그대로다
        with pytest.raises(SessionError):
            await s.resume()
        await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        assert s.state is SessionState.RUNNING and s.pending_triggers == []
        await s.stop()
    run(main())


def test_a_relay_that_cannot_be_built_is_refused_before_any_robot_is_touched():
    async def main():
        leader, followers, _ = _robots(2)

        def broken(_leader, _followers, **_kw):
            raise ValueError("relay refused the robot set")

        s = FormationSession(leader, followers, FormationSpec(Formation.COLUMN, spacing=0.6),
                             relay_factory=broken, sleep=_no_sleep)
        with pytest.raises(SessionError):
            await s.start()
        assert s.state is SessionState.STOPPED
        assert not any(_follows(f) for f in followers)   # D-132 — 접촉 전 거절이다
        assert s.reason[0].startswith("relay_failed")
    run(main())


def test_a_relay_session_error_keeps_its_original_reason():
    """D-134 — 고정 문자열로 덮어쓰지 않는다. 원인이 지워지면 "접촉 전 거절"이
    왜 일어났는지 아무도 모른다."""
    async def main():
        leader, followers, _ = _robots(2)

        def broken(_leader, _followers, **_kw):
            raise SessionError("cannot build: boom-134")

        s = FormationSession(leader, followers, FormationSpec(Formation.COLUMN, spacing=0.6),
                             relay_factory=broken, sleep=_no_sleep)
        with pytest.raises(SessionError):
            await s.start()
        assert s.state is SessionState.STOPPED
        assert "boom-134" in s.reason[0]
        assert not any(_follows(f) for f in followers)
    run(main())


def test_stop_during_open_wait_aborts_immediately_without_touching_robots():
    """D-134 — 개방 대기 3 s 중 운영자 stop이면 즉시 탈출한다. 3 s를 다 쓰고
    _arm까지 갔다가 되돌아오지 않고, 운영자의 종료 사유를 덮어쓰지 않는다."""
    async def main():
        leader, followers, log = _robots(2)
        holder = {}

        def factory(ld, f, **_kw):
            relay = FakeRelay(ld, f, log=log, ready=False)
            holder["relay"] = relay
            return relay

        box = {}

        async def sleep(_s):
            box["n"] = box.get("n", 0) + 1
            if box["n"] == 2:
                await box["s"].stop()       # 대기 중에 운영자가 끝낸다
            else:
                await asyncio.sleep(0)

        s = FormationSession(leader, followers, FormationSpec(Formation.COLUMN, spacing=0.6),
                             relay_factory=factory, sleep=sleep)
        box["s"] = s
        with pytest.raises(SessionError):
            await s.start()
        assert s.state is SessionState.STOPPED
        assert s.reason == ("stopped", None)      # 구 코드는 relay_failed로 덮어쓴다
        assert box["n"] < 60                       # 3 s 상한을 다 쓰지 않았다
        assert not any(_follows(f) for f in followers)
        assert holder["relay"].stopped
    run(main())


def test_the_session_refuses_duplicate_or_self_following_robots():
    spec = FormationSpec(Formation.COLUMN, spacing=0.6)
    with pytest.raises(ValueError):
        FormationSession(FakeRobot("rosy_01"), [FakeRobot("rosy_02"), FakeRobot("rosy_02")], spec)
    with pytest.raises(ValueError):
        FormationSession(FakeRobot("rosy_01"), [FakeRobot("rosy_02"), FakeRobot("rosy_01")], spec)


def test_a_leader_found_in_estop_after_a_socket_drop_holds_the_formation():
    async def main():
        leader, followers, log = _robots(1)
        s = _session(leader, followers, log=log)
        await s.start()
        leader._state["mode"] = RobotMode.EMERGENCY.value   # 끊긴 동안 e-stop 이 눌렸다
        leader.event_frames.put_nowait(END)
        await settle(40)
        assert leader.event_opens >= 2
        assert s.state is SessionState.HOLDING
        assert s.reason == ("safety.estop", "rosy_01")
        assert s.relay.paused
        await s.stop()
    run(main())


# --- 재개 직전에 들어온 것, 되지 않는 릴레이 정지, e-stop 상태의 리더 ------------------


def test_a_trigger_that_lands_while_resume_is_checking_blocks_the_resume():
    """재개 전 확인도 await 여러 개짜리 구간이다. 그 사이에 온 사고를 재개가 지나칠 수 없다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        gate = asyncio.Event()
        followers[1].swarm_state_gate = gate              # 확인이 여기서 멈춘다
        task = asyncio.create_task(s.resume())
        await settle()
        followers[0].event_frames.put_nowait({"type": "safety.estop", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        gate.set()
        with pytest.raises(SessionError):
            await task
        assert s.relay.paused                             # 풀지 않았다
        assert s.state is SessionState.HOLDING
        assert s.pending_triggers == [("safety.estop", "rosy_02")]
        await s.stop()
    run(main())


def test_a_stop_that_lands_while_resume_is_checking_is_not_overridden():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        gate = asyncio.Event()
        followers[1].swarm_state_gate = gate
        task = asyncio.create_task(s.resume())
        await settle()
        await s.stop()                                    # 확인 중에 운영자가 끝냈다
        assert s.state is SessionState.STOPPED
        gate.set()
        try:
            await task
        except SessionError:
            pass
        assert s.state is SessionState.STOPPED            # 재개가 되살리지 않는다
        assert s.relay.stopped
    run(main())


def test_the_same_trigger_from_the_same_robot_is_only_kept_once():
    """끊긴 이벤트 소켓은 2 s 마다 다시 열린다. 같은 사고를 무한히 쌓으면 안 된다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        followers[0]._swarm_state = {"active": False, "holding": False}
        for _ in range(3):
            followers[0].event_frames.put_nowait(END)     # 소켓 단절 → reconcile
            await settle(40)
        assert followers[0].event_opens >= 4
        assert s.pending_triggers.count(("swarm.aborted", "rosy_02")) == 1
        assert s.pending_triggers == [("swarm.aborted", "rosy_02")]
        await s.stop()
    run(main())


def test_an_abort_lets_the_robots_go_even_when_the_relay_cannot_be_stopped():
    async def main():
        leader, followers, log = _robots(2)

        class BrokenStopRelay(FakeRelay):
            async def stop(self):
                self.log.append(("relay", "stop"))
                raise ConnectionError("relay socket already gone")

        s = FormationSession(leader, followers, FormationSpec(Formation.COLUMN, spacing=0.6),
                             policy=HoldPolicy.ABORT, sleep=_no_sleep,
                             relay_factory=lambda ld, f, **_: BrokenStopRelay(ld, f, log=log))
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        # 릴레이를 못 끄는 것은 로봇을 무장한 채 두는 이유가 되지 못한다.
        assert all(("swarm_cancel",) in f.calls for f in followers)
        assert ("navigation_cancel",) in leader.calls
        assert s.state is SessionState.STOPPED
        await s.stop()
    run(main())


def test_a_leader_in_estop_is_refused_before_any_follower_is_armed():
    async def main():
        leader, followers, log = _robots(2)
        leader._state["mode"] = RobotMode.EMERGENCY.value
        s = _session(leader, followers, log=log)
        with pytest.raises(ArmingFailed) as exc:
            await s.start()
        assert exc.value.robot_id == "rosy_01" and exc.value.code == "EMERGENCY_ACTIVE"
        assert not any(_follows(f) for f in followers)
        assert s.state is SessionState.STOPPED
    run(main())


def test_resume_refuses_while_the_leader_is_still_in_estop():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        leader._state["mode"] = RobotMode.EMERGENCY.value
        leader.event_frames.put_nowait({"type": "safety.estop", "robot_id": "rosy_01", "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        with pytest.raises(SessionError):
            await s.resume()                              # 리더가 아직 서 있다
        assert s.state is SessionState.HOLDING and s.relay.paused
        leader._state["mode"] = RobotMode.IDLE.value      # e-stop 이 풀렸다
        await s.resume()
        assert s.state is SessionState.RUNNING and not s.relay.paused
        await s.stop()
    run(main())


def test_a_relay_that_cannot_be_started_is_stopped_before_any_robot_is_touched():
    async def main():
        leader, followers, log = _robots(2)
        created = []

        class BrokenStartRelay(FakeRelay):
            async def start(self):
                raise ConnectionError("reference socket refused")

        def factory(ld, f, **_):
            relay = BrokenStartRelay(ld, f, log=log)
            created.append(relay)
            return relay

        s = FormationSession(leader, followers, FormationSpec(Formation.COLUMN, spacing=0.6),
                             relay_factory=factory, sleep=_no_sleep)
        with pytest.raises(SessionError):
            await s.start()
        assert s.state is SessionState.STOPPED
        assert not any(_follows(f) for f in followers)   # 무장 시도 자체가 없다
        assert created[0].stopped
        assert s.reason[0].startswith("relay_failed")
    run(main())


def test_a_reform_from_a_hold_carries_only_what_was_already_there():
    """HOLDING 중의 reform 은 시작 시점에 쌓여 있던 몫만 책임진다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        followers[1].event_frames.put_nowait({"type": "safety.estop", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.pending_triggers == [("safety.estop", "rosy_03")]
        gate = asyncio.Event()
        followers[0].follow_gate = gate
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        followers[1].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        gate.set()
        await task
        assert s.state is SessionState.HOLDING
        assert s.pending_triggers == [("nav.stuck", "rosy_03")]   # 새로 온 것만 남는다
        assert s.relay.paused
        await s.stop()
    run(main())


def test_a_reform_does_not_resume_toward_a_robot_that_left_while_it_was_re_arming():
    """`follow` 가 200 이라는 것과 그 로봇이 아직 따르고 있다는 것은 다르다.

    캐리 몫에 같은 `(사유, id)` 가 들어 있으면, 무장 중에 다시 이탈한 로봇의 이벤트는
    중복으로 지워지고 그 캐리 몫은 reform 이 잘라낸다. 그러면 떠난 로봇을 향해 대형이
    다시 달린다 — 재개 직전에 전원에게 직접 묻는 것이 그것을 막는다.
    """
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        followers[1].event_frames.put_nowait({"type": "swarm.aborted", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        assert s.pending_triggers == [("swarm.aborted", "rosy_03")]
        gate = asyncio.Event()
        followers[1].follow_gate = gate
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        # rosy_03 은 follow 를 받아들인다. 그러고도 대형에 없다 — 이벤트는 오지 않는다.
        followers[1]._swarm_state = {"active": False, "holding": False}
        gate.set()
        await task                                        # 예외 없이 돌아온다
        assert s.state is SessionState.HOLDING
        assert s.relay.paused                             # 스트림은 멈춘 채다
        assert s.pending_triggers == [("swarm.aborted", "rosy_03")]
        assert s.reason == ("swarm.aborted", "rosy_03")
        await s.stop()
    run(main())


def test_a_reform_stays_holding_when_a_follower_cannot_say_whether_it_is_still_following():
    """물어볼 수 없으면 따라온다고 볼 수 없다. 재개하지 않는 쪽이 안전하다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        followers[1].swarm_state_error = ConnectionError("robot went dark")
        await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        assert s.state is SessionState.HOLDING
        assert s.relay.paused
        assert s.pending_triggers == [("swarm.state_unavailable", "rosy_03")]
        await s.stop()
    run(main())


def test_a_repeat_of_a_carried_trigger_during_re_arming_is_a_new_event():
    """캐리 몫은 곧 잘려 나간다. 무장 중에 같은 사고가 다시 오면 중복이 아니다 —
    거기 묻어 사라지면 reform 이 이미 끝난 사고로 알고 재개한다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        followers[1].event_frames.put_nowait({"type": "swarm.aborted", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.pending_triggers == [("swarm.aborted", "rosy_03")]
        gate = asyncio.Event()
        followers[0].follow_gate = gate
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        followers[1].event_frames.put_nowait({"type": "swarm.aborted", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        gate.set()
        await task
        assert s.state is SessionState.HOLDING
        assert s.relay.paused
        assert s.pending_triggers == [("swarm.aborted", "rosy_03")]   # 다시 온 것만 남는다
        await s.stop()
    run(main())


def test_a_map_mismatch_hold_is_a_warning_even_while_the_relay_is_paused(caplog):
    """설계 §6.2. 릴레이가 멈춰 있으면 swarm.hold 는 대개 우리가 만든 것(정보)이지만,
    맵이 어긋난 것은 우리가 만든 것이 아니다 — 정보로 흘리면 아무도 맵을 고치러 가지 않는다."""
    async def main():
        leader, followers, log = _robots(1)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING and s.relay.paused
        caplog.clear()
        followers[0].event_frames.put_nowait({"type": "swarm.hold", "robot_id": "rosy_02",
                                              "data": {"reason": "map_mismatch"}})
        await settle()
        holds = [r for r in caplog.records if "swarm.hold" in r.getMessage()]
        assert [r.levelname for r in holds] == ["WARNING"]
        caplog.clear()
        followers[0].event_frames.put_nowait({"type": "swarm.hold", "robot_id": "rosy_02",
                                              "data": {"reason": "reference stream lost"}})
        await settle()
        holds = [r for r in caplog.records if "swarm.hold" in r.getMessage()]
        assert [r.levelname for r in holds] == ["INFO"]   # 이쪽은 우리가 만든 HOLD 다
        await s.stop()

    with caplog.at_level("INFO", logger="fleet.swarm.session"):
        run(main())


# --- 사전 점검 거절: 아무것도 만지지 않았으므로 아무것도 달라지지 않는다 ---------------


def _touched(log, mark):
    """`mark` 이후에 로봇이나 릴레이가 실제로 움직인 흔적. state 읽기는 움직임이 아니다."""
    return [e for e in log[mark:]
            if e[1] in ("pause", "resume", "stop", "follow", "swarm_cancel", "navigation_cancel")]


@pytest.mark.parametrize("spec", [
    FormationSpec(Formation.FOLLOW, spacing=0.6),   # 팔로워 2대에 FOLLOW 는 만들 수 없다
    FormationSpec(Formation.LINE, spacing=0.1),     # spacing 이 하한(0.4) 아래다
], ids=["follow_with_two", "spacing_below_floor"])
def test_a_reform_that_cannot_be_planned_leaves_a_running_formation_running(spec):
    """계획이 릴레이보다 먼저다. 거절되는 reform 이 멀쩡한 대형을 세우면 `resume()` 도
    듣지 않는다 — 상태가 HOLDING 이 아니라 RUNNING 이기 때문이다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        mark = len(log)
        with pytest.raises(SessionError):
            await s.reform(spec)
        assert s.state is SessionState.RUNNING
        assert not s.relay.paused
        assert _touched(log, mark) == []
        await s.stop()
    run(main())


def test_a_reform_that_cannot_be_planned_leaves_a_hold_holding():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        mark = len(log)
        with pytest.raises(SessionError):
            await s.reform(FormationSpec(Formation.FOLLOW, spacing=0.6))
        assert s.state is SessionState.HOLDING
        assert s.relay.paused                              # HOLD 가 멈춘 그대로다
        assert s.reason == ("nav.blocked", "rosy_02")
        assert _touched(log, mark) == []
        await s.stop()
    run(main())


def test_a_reform_refused_by_a_leader_in_estop_does_not_destroy_the_hold():
    """`resume()` 은 "reform 으로 다시 무장하라"고 말한다. 그 reform 이 사전 점검에서
    거절됐다고 대형을 끝내면, 운영자는 시키는 대로 하고 대형을 잃는다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        leader._state["mode"] = RobotMode.EMERGENCY.value
        mark = len(log)
        with pytest.raises(ArmingFailed) as exc:
            await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        assert exc.value.robot_id == "rosy_01" and exc.value.code == "EMERGENCY_ACTIVE"
        assert s.state is SessionState.HOLDING
        assert s.relay.paused and not s.relay.stopped
        assert _touched(log, mark) == []                   # 팔로워는 한 대도 만지지 않았다
        await s.stop()
    run(main())


def test_a_reform_with_a_map_mismatch_never_pauses_the_relay():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[1]._state["map_id"] = "other"            # 그 사이에 다른 맵으로 갈아탔다
        mark = len(log)
        with pytest.raises(MapMismatch):
            await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        assert s.state is SessionState.RUNNING
        assert not s.relay.paused
        assert _touched(log, mark) == []
        await s.stop()
    run(main())


def test_a_start_with_a_spec_that_cannot_be_built_is_a_session_error_not_a_value_error():
    """`slots()` 의 `FormationError` 는 `ValueError` 다. 그대로 새어 나가면 호출자의
    `except SessionError` 를 지나쳐 세션이 ARMING 에 남는다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, spec=FormationSpec(Formation.FOLLOW, spacing=0.6), log=log)
        with pytest.raises(SessionError):
            await s.start()
        assert s.state is SessionState.STOPPED             # 다른 start 실패와 같은 자리다
        assert not any(_follows(f) for f in followers)
        assert not any(e[1] == "start" for e in log)
    run(main())


# --- 전송 실패도 세션의 거절 언어로 -----------------------------------------------


def test_a_state_read_that_dies_on_the_wire_is_an_arming_failure_not_a_raw_httpx_error():
    async def main():
        leader, followers, log = _robots(2)
        followers[1].state_error = ConnectionError("connection reset by peer")
        s = _session(leader, followers, log=log)
        with pytest.raises(ArmingFailed) as exc:
            await s.start()
        assert exc.value.robot_id == "rosy_03" and exc.value.code == "TRANSPORT"
        assert not any(_follows(f) for f in followers)
        assert s.state is SessionState.STOPPED
    run(main())


def test_a_state_read_that_dies_during_a_reform_leaves_the_formation_running():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[1].state_error = ConnectionError("connection reset by peer")
        mark = len(log)
        with pytest.raises(ArmingFailed) as exc:
            await s.reform(FormationSpec(Formation.LINE, spacing=0.6))
        assert exc.value.code == "TRANSPORT"
        assert s.state is SessionState.RUNNING
        assert not s.relay.paused
        assert _touched(log, mark) == []
        followers[1].state_error = None
        await s.stop()
    run(main())


def test_a_state_read_that_dies_while_resuming_keeps_the_hold():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].event_frames.put_nowait({"type": "nav.blocked", "robot_id": "rosy_02",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING
        leader.state_error = ConnectionError("connection reset by peer")
        with pytest.raises(SessionError):
            await s.resume()
        assert s.state is SessionState.HOLDING
        assert s.relay.paused
        leader.state_error = None
        await s.resume()
        assert s.state is SessionState.RUNNING and not s.relay.paused
        await s.stop()
    run(main())


def test_a_reconcile_that_cannot_read_swarm_state_does_not_kill_the_watcher(caplog):
    """`_reconcile` 은 감시 루프 안이다. 여기서 날것의 예외가 올라가면 감시가 통째로
    죽고, 그 로봇의 사고는 그때부터 아무도 보지 않는다."""
    async def main():
        leader, followers, log = _robots(1)
        s = _session(leader, followers, log=log)
        await s.start()
        followers[0].swarm_state_error = ConnectionError("socket gone")
        opens = followers[0].event_opens
        followers[0].event_frames.put_nowait(END)          # 소켓 단절 → reconcile
        await settle(40)
        assert followers[0].event_opens > opens            # 감시는 계속 다시 연다
        assert s.state is SessionState.RUNNING             # 상태는 건드리지 않는다
        assert s.pending_triggers == []
        assert any("swarm/state unavailable" in r.getMessage() for r in caplog.records)
        await s.stop()
    with caplog.at_level("WARNING", logger="fleet.swarm.session"):
        run(main())


def test_stop_from_idle_has_nothing_to_cancel():
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.stop()
        assert s.state is SessionState.STOPPED
        assert not any(("swarm_cancel",) in f.calls for f in followers)
        assert not any(entry[1] == "swarm_cancel" for entry in log)
    run(main())


# --- 계획 중에 들어온 것들: reform 은 `_plan` 동안에도 열려 있는 창이다 -----------------


def test_a_hold_that_lands_while_a_reform_is_planning_keeps_the_new_offsets_but_does_not_resume():
    """`_plan` 도 await 여러 개짜리 구간이다. 무장 중에 걸린 HOLD 와 같은 대접을 받아야
    한다 — 새 배정은 살고, 재개는 운영자 몫으로 남는다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        gate = asyncio.Event()
        followers[0].state_gate = gate                   # 계획이 여기서 멈춘다
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        followers[1].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.HOLDING           # 계획 중에 걸렸다
        gate.set()
        await task                                       # reform 은 정상 반환한다
        assert s.state is SessionState.HOLDING
        assert s.reason == ("nav.stuck", "rosy_03")      # 사유는 트리거 쪽이다
        assert s.relay.paused                            # 재개하지 않는다
        assert all(len(_follows(f)) == 2 for f in followers)     # 새 오프셋 무장은 살린다
        assert all(_follows(f)[1].distance == 0.0 for f in followers)   # LINE
        await s.stop()
    run(main())


def test_an_abort_that_lands_while_a_reform_is_planning_never_pauses_the_relay_again():
    """계획이 끝나기 전에 세션이 끝났다. 죽은 릴레이를 다시 만질 이유가 없고, 이미
    풀린 팔로워를 한 번 더 풀 이유도 없다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log, policy=HoldPolicy.ABORT)
        await s.start()
        gate = asyncio.Event()
        followers[0].state_gate = gate
        mark = len(log)
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        followers[1].event_frames.put_nowait({"type": "nav.stuck", "robot_id": "rosy_03",
                                              "data": {}})
        await settle()
        assert s.state is SessionState.STOPPED
        gate.set()
        with pytest.raises(SessionError) as exc:
            await task
        assert "aborted during reform" in str(exc.value)
        assert "nav.stuck" in str(exc.value)
        assert not s.relay.paused                        # pause 는 계획 뒤에 온다
        assert ("relay", "pause") not in log[mark:]
        # 팔로워는 abort 가 한 번 풀었다. reform 이 그 위에 또 풀지 않는다.
        assert all(f.calls.count(("swarm_cancel",)) == 1 for f in followers)
    run(main())


def test_an_operator_stop_while_a_reform_is_planning_is_reported_as_a_stop():
    """운영자가 세운 것을 "aborted ... unknown" 으로 보고하면, 운영자는 자기가 방금
    누른 것을 사고로 읽고 없는 로그를 뒤진다."""
    async def main():
        leader, followers, log = _robots(2)
        s = _session(leader, followers, log=log)
        await s.start()
        gate = asyncio.Event()
        followers[0].state_gate = gate
        task = asyncio.create_task(s.reform(FormationSpec(Formation.LINE, spacing=0.6)))
        await settle()
        await s.stop()                                   # 계획 한가운데로 들어온 stop
        assert s.state is SessionState.STOPPED
        gate.set()
        with pytest.raises(SessionError) as exc:
            await task
        assert "stopped" in str(exc.value)
        assert "aborted" not in str(exc.value)
        assert not s.relay.paused                        # 릴레이는 멈춘 게 아니라 끝났다
        assert s.relay.stopped
        assert s.state is SessionState.STOPPED
    run(main())


def test_two_followers_that_die_together_are_both_logged_and_the_first_is_raised(caplog):
    """`gather` 는 둘 다 돌려주지만 올라가는 것은 하나다. 나머지를 조용히 버리면 두 대가
    함께 죽은 사고가 한 대의 사고로 보이고, 운영자는 한 대만 고치러 간다."""
    async def main():
        leader, followers, log = _robots(2)
        followers[0].state_error = ConnectionError("rosy_02 socket gone")
        followers[1].state_error = ConnectionError("rosy_03 socket gone")
        s = _session(leader, followers, log=log)
        with pytest.raises(ArmingFailed) as exc:
            await s.start()
        assert exc.value.robot_id == "rosy_02"           # 첫 번째가 올라간다
        assert s.state is SessionState.STOPPED
        messages = [r.getMessage() for r in caplog.records]
        assert any("rosy_03" in m and "state unavailable while planning" in m for m in messages)
        assert not any("rosy_02" in m for m in messages)  # 올라간 것은 다시 적지 않는다
    with caplog.at_level("WARNING", logger="fleet.swarm.session"):
        run(main())
