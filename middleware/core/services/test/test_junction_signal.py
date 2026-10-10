"""D-620: Fleet reply wins before entry; only silence permits the three-second fallback."""
import pytest

from test_line_junction import Rig


def waiting():
    rig = Rig(junction_signal_enabled=True)
    rig.step(junction=True)
    return rig, rig.m.junction_signal_request()


def answer(rig, request, lamp, may_enter=False):
    return rig.m.junction_signal_answer(dict(request_id=request, lamp=lamp,
                                           may_enter=may_enter, reason="test"))


def test_silence_waits_three_seconds_then_arms_one_right_turn():
    rig, request = waiting()
    for _ in range(59):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        assert status.junction.state == "waiting"
        assert rig.m.junction_signal_request() == request
    _, status = rig.step(junction=True)
    assert status.junction.pending_action == "right"
    assert status.junction.turn_deg == -90
    assert status.junction.signal_state in ("fallback", "entered")
    seq = status.junction.seq
    for _ in range(3):
        rig.step(junction=True)
        assert rig.m.status().junction.seq == seq


@pytest.mark.parametrize("lamp,may_enter", [("red", False), ("unknown", False), ("green", False)])
def test_a_reply_never_becomes_silence_even_after_three_seconds(lamp, may_enter):
    rig, request = waiting()
    assert answer(rig, request, lamp, may_enter)
    for _ in range(100):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        assert status.junction.state == "waiting"
    assert status.junction.signal_state in (lamp, "unknown")


def test_red_then_green_enters_through_existing_bounded_turn_gate():
    rig, request = waiting()
    answer(rig, request, "red")
    rig.step(junction=True)
    answer(rig, request, "green", True)
    _, status = rig.step(junction=True)
    assert status.junction.pending_action == "right"
    assert status.junction.turn_deg == -90
    assert status.junction.signal_state in ("green", "entered")


def test_wrong_episode_and_malformed_answers_cannot_open_the_gate():
    rig, request = waiting()
    assert not answer(rig, "0" * 32, "green", True)
    assert not answer(rig, request, "green", "true")
    assert rig.m.status().junction.state == "waiting"
    for _ in range(70):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
    assert status.junction.signal_state == 'unknown'


def test_rejected_pairing_never_turns_into_silence_permission():
    rig, _request = waiting()
    rig.m.junction_signal_link_refused = lambda: True
    for _ in range(70):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
    assert status.junction.signal_state == 'unknown'


def test_late_red_before_rotation_cancels_fallback():
    rig, request = waiting()
    for _ in range(59):
        rig.step(junction=True)
    rig.now += .4
    rig.step(junction=True, pose=False)
    assert rig.m.status().junction.signal_state == "fallback"
    answer(rig, request, "red")
    decision, status = rig.step(junction=True)
    assert decision.linear == decision.angular == 0
    assert status.junction.state == "waiting"
    assert status.junction.signal_state == "red"


def test_red_still_cancels_a_rotation_zeroed_by_authority():
    rig = Rig(junction_signal_enabled=True, authority_required=True)
    rig.m._wall = lambda: rig.now
    rig.step(junction=True)
    request = rig.m.junction_signal_request()
    assert answer(rig, request, 'green', True)
    for _ in range(20):
        decision, _ = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        if rig.m._junction.get('sub') == 'rotating':
            break
    assert rig.m._junction['sub'] == 'rotating'
    assert answer(rig, request, 'red')
    rig.m.set_authority('A1', 'L1', rig.now, 1., 2.)
    for _ in range(10):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        assert status.junction.state == 'waiting'


def test_red_still_cancels_a_rotation_zeroed_by_crosswalk():
    from core_features.line_follow.crosswalk_gate import Zone
    from test_line_junction import BODY

    rig = Rig(junction_signal_enabled=True, crosswalk_gate_enabled=True,
              obstacle_mode='path', **BODY)
    rig.step(junction=True)
    request = rig.m.junction_signal_request()
    zones = [Zone((rig.m._return_evidence.epoch, 'odom'), 0., 0., 0., .08, .3)]
    rig.m._crosswalk_zones = lambda: zones
    rig.m.observe_crosswalk_scan((), range_min=.15, received_at=rig.now)
    assert answer(rig, request, 'green', True)
    for _ in range(20):
        decision, _ = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        if rig.m._junction.get('sub') == 'rotating':
            break
    assert rig.m._junction['sub'] == 'rotating'
    assert rig.m._xwalk.zone is not None
    assert answer(rig, request, 'red')
    zones.clear()
    rig.m._xwalk.reset()
    for _ in range(10):
        decision, status = rig.step(junction=True)
        assert decision.linear == decision.angular == 0
        assert status.junction.state == 'waiting'


def test_fallback_still_needs_motion_basis():
    rig = Rig(proof=False, junction_signal_enabled=True)
    for _ in range(63):
        decision, status = rig.step(junction=True)
    assert decision.linear == decision.angular == 0
    assert status.junction.state == "aborted"
    assert status.junction.reason == "motion_unconfirmed"


def test_default_off_and_mode_off_do_not_request_or_apply_answers():
    rig = Rig()
    rig.step(junction=True)
    assert rig.m.junction_signal_request() is None
    rig, request = waiting()
    from core_features.line_follow.model import LineFollowMode
    rig.m.set_mode(LineFollowMode.OFF)
    assert rig.m.junction_signal_request() is None
    assert not answer(rig, request, "green", True)
    assert not rig.m.junction_signal_answer({})


def test_a_camera_gap_at_the_same_stopped_junction_does_not_erase_a_red_reply():
    rig, request = waiting()
    answer(rig, request, 'red')
    for _ in range(100):
        decision, status = rig.step(junction=False)
        assert decision.linear == decision.angular == 0
    assert rig.m.junction_signal_request() == request
    assert status.junction.pending_action is None


def test_completed_turn_is_not_run_again_on_repeated_sightings():
    rig, request = waiting()
    answer(rig, request, 'green', True)
    for _ in range(400):
        _, status = rig.step(junction=True, move=True)
        if status.junction.state == 'idle':
            break
    assert status.junction.state == 'idle'
    seq = status.junction.seq
    for _ in range(70):
        rig.step(junction=True)
        assert rig.m.status().junction.seq == seq
        assert rig.m.junction_signal_request() is None


def test_agent_sends_the_query_and_delivers_the_correlated_heartbeat_answer():
    import asyncio
    from types import SimpleNamespace
    from core_common.protocol.schemas import Envelope, EnvelopeType, StateSnapshot
    from core_features.fleet_agent.agent import FleetAgent

    async def check():
        request = 'a' * 32
        queue, received = asyncio.Queue(), asyncio.Event()
        sent, replies = [], []
        agent = FleetAgent(SimpleNamespace(snapshot=lambda: StateSnapshot(robot_id='robot')),
                           None, {}, SimpleNamespace(robot_id='robot'))
        agent.enabled = True
        agent._hb_reply = asyncio.Event()
        agent.junction_signal_request = lambda: request

        def receive(reply):
            replies.append(reply)
            received.set()
        agent.junction_signal_answer = receive

        class Socket:
            async def send(self, raw):
                env = Envelope.model_validate_json(raw)
                sent.append(env.payload)
                await queue.put(Envelope(type=EnvelopeType.HEARTBEAT, payload={'junction_signal': dict(
                    request_id=request, lamp='red', may_enter=False, reason='test')}).model_dump_json())

            async def recv(self):
                return await queue.get()

        ws = Socket()
        tasks = [asyncio.create_task(agent._reader_loop(ws)), asyncio.create_task(agent._heartbeat_loop(ws))]
        try:
            await asyncio.wait_for(received.wait(), 1.)
            assert sent[0]['junction_signal_request'] == request
            assert replies[0]['request_id'] == request and replies[0]['lamp'] == 'red'
        finally:
            agent.enabled = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(check())
