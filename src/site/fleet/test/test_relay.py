"""릴레이는 리더 프레임을 바꾸지 않고 팔로워에 전달한다(D-31). 합성하지 않고,
느린 팔로워에 밀리지 않고, 팔로워 하나가 죽어도 나머지는 계속 받는다."""

import asyncio
import json

import pytest
from fakes import END, FakeClock, FakeRobot, run, settle

from fleet.swarm.relay import Relay
from fleet.swarm.transport import RobotApiError


def frame(seq: int) -> str:
    return json.dumps({"type": "pose", "payload": {"robot_id": "rosy_01", "seq": seq,
                                                   "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}})


def _no_sleep():
    async def sleep(_s):
        await asyncio.sleep(0)
    return sleep


def test_frames_reach_every_follower_byte_for_byte():
    async def main():
        leader, f1, f2 = FakeRobot("rosy_01"), FakeRobot("rosy_02"), FakeRobot("rosy_03")
        relay = Relay(leader, [f1, f2], sleep=_no_sleep())
        await relay.start()
        await settle()
        leader.pose_frames.put_nowait(frame(1))
        leader.pose_frames.put_nowait(frame(2))
        await settle()
        assert f1.sinks[0].sent == [frame(1), frame(2)]
        assert f2.sinks[0].sent == [frame(1), frame(2)]
        await relay.stop()
    run(main())


def test_pause_stops_delivery_and_resume_restarts_it_without_replaying():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        leader.pose_frames.put_nowait(frame(1))
        await settle()
        relay.pause()
        leader.pose_frames.put_nowait(frame(2))
        leader.pose_frames.put_nowait(frame(3))
        await settle()
        assert f1.sinks[0].sent == [frame(1)]
        relay.resume()
        await settle()
        assert f1.sinks[0].sent == [frame(1)]          # 멈춘 동안의 프레임은 재생하지 않는다
        leader.pose_frames.put_nowait(frame(4))
        await settle()
        assert f1.sinks[0].sent == [frame(1), frame(4)]
        await relay.stop()
    run(main())


def test_a_slow_follower_gets_the_latest_frame_not_the_backlog():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        sink = f1.sinks[0]
        sink.gate = asyncio.Event()                     # send 가 여기서 막힌다
        leader.pose_frames.put_nowait(frame(1))        # 전송 중에 걸린다
        await settle()
        leader.pose_frames.put_nowait(frame(2))
        leader.pose_frames.put_nowait(frame(3))
        await settle()
        sink.gate.set()
        await settle()
        assert sink.sent == [frame(1), frame(3)]        # 2 는 3 에 덮였다
        await relay.stop()
    run(main())


def test_one_broken_follower_does_not_stop_the_others():
    async def main():
        leader, f1, f2 = FakeRobot("rosy_01"), FakeRobot("rosy_02"), FakeRobot("rosy_03")
        f1.next_sink_fail_on_send = True
        relay = Relay(leader, [f1, f2], sleep=_no_sleep())
        await relay.start()
        await settle()
        leader.pose_frames.put_nowait(frame(1))
        await settle()
        assert f2.sinks[0].sent == [frame(1)]
        # f1 은 첫 소켓이 깨져 재연결했고, 그다음 프레임은 새 소켓으로 받는다.
        leader.pose_frames.put_nowait(frame(2))
        await settle()
        assert len(f1.sinks) >= 2
        assert f1.sinks[-1].sent == [frame(2)]
        assert relay.is_connected("rosy_02")
        await relay.stop()
    run(main())


def test_a_lost_leader_is_reconnected_and_nothing_is_synthesized():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        leader.pose_frames.put_nowait(frame(1))
        leader.pose_frames.put_nowait(END)              # 리더 소켓 단절
        await settle()
        assert f1.sinks[0].sent == [frame(1)]           # 반복 전송 없음
        assert leader.pose_opens >= 2                   # 다시 열었다
        leader.pose_frames.put_nowait(frame(2))
        await settle()
        assert f1.sinks[0].sent == [frame(1), frame(2)]
        await relay.stop()
    run(main())


def test_a_follower_socket_that_will_not_open_is_retried():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        f1.sink_failures = 2
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle(40)
        assert len(f1.sinks) == 1
        assert relay.is_connected("rosy_02")
        await relay.stop()
    run(main())


def test_stats_count_frames_and_seq_gaps():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        for seq in (1, 2, 5, 6):                        # 3, 4 가 빠졌다
            leader.pose_frames.put_nowait(frame(seq))
        leader.pose_frames.put_nowait("not json")      # 계측만 건너뛰고 전달은 한다
        await settle()
        stats = relay.stats()
        assert stats.leader_frames == 5
        assert stats.leader_dropped == 2
        assert stats.follower_tx["rosy_02"] == 5
        assert f1.sinks[0].sent[-1] == "not json"
        await relay.stop()
    run(main())


def test_a_rejected_leader_socket_is_named_in_the_stats_and_still_retried():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        leader.pose_error = RobotApiError("rosy_01", 403, "WS_4403", "capability swarm.lead not declared")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle(40)
        assert relay.stats().leader_last_error is not None
        assert "WS_4403" in relay.stats().leader_last_error
        assert leader.pose_opens >= 2                   # 포기하지 않는다 — 정책은 호출자 것
        leader.pose_error = None
        leader.pose_frames.put_nowait(frame(1))
        await settle(40)
        assert f1.sinks[0].sent == [frame(1)]
        assert relay.stats().leader_last_error is None  # 프레임이 오면 지운다
        await relay.stop()
    run(main())


def test_a_leader_socket_that_fails_for_any_reason_is_named_too():
    """거부(RobotApiError)만 이름이 붙던 자리다. 리더가 죽으면 팔로워 전원이 굶는다 —
    연결 거부처럼 평범한 OSError 도 화면에 이유가 붙어야 한다."""
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        leader.pose_error = ConnectionRefusedError("cannot reach the leader pose socket")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle(40)
        assert "cannot reach the leader pose socket" in (relay.stats().leader_last_error or "")
        assert leader.pose_opens >= 2                   # 이름을 붙이고도 계속 다시 연다
        leader.pose_error = None
        leader.pose_frames.put_nowait(frame(1))
        await settle(40)
        assert relay.stats().leader_last_error is None  # 프레임이 오면 지운다
        await relay.stop()
    run(main())


def test_a_leader_stream_that_ends_without_a_frame_is_named_too():
    """전송계층은 연결 거부(OSError)를 삼키고 조용히 끝낸다. 그러면 예외도 프레임도
    없이 0 Hz 다 — 이유 없는 0 Hz 가 이 릴레이의 가장 나쁜 실패다."""
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        leader.pose_frames.put_nowait(END)              # 프레임 하나 없이 끝난다
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle(40)
        assert relay.stats().leader_last_error is not None
        assert "without frames" in relay.stats().leader_last_error
        leader.pose_frames.put_nowait(frame(1))
        await settle(40)
        assert relay.stats().leader_last_error is None  # 프레임이 오면 지운다
        assert f1.sinks[0].sent == [frame(1)]
        await relay.stop()
    run(main())


def test_a_leader_stream_that_delivered_frames_then_closed_is_not_an_error():
    """정상적인 소켓 종료는 사고가 아니다. 프레임이 왔다 갔으면 이유를 만들지 않는다."""
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        leader.pose_frames.put_nowait(frame(1))
        leader.pose_frames.put_nowait(END)
        await settle(40)
        assert relay.stats().leader_last_error is None
        await relay.stop()
    run(main())


def test_stop_closes_the_sinks():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        await relay.stop()
        assert f1.sinks[0].closed
        assert not relay.is_connected("rosy_02")
    run(main())


def test_streams_ready_is_false_until_the_first_leader_frame_arrives():
    """D-134 — 접속 시도가 아니라 첫 프레임 수신이 준비다. pose_stream()은 async
    generator라 첫 __anext__ 전까지 접속이 일어나지 않는다 — 시도 전에 세우면
    리더 down이어도 찰나 참이 돼 검증 안 된 리더에 무장한다."""
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        leader.pose_error = RobotApiError("rosy_01", 403, "WS_4403", "capability swarm.lead not declared")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await asyncio.sleep(0)          # 리더 태스크가 첫 접속 시도까지 돌게 한다
        assert relay.is_connected("rosy_02")      # 팔로워 sink는 열렸다
        assert not relay.streams_ready()          # 리더 실측 없음 — 구 코드는 여기서 참이었다
        await relay.stop()
    run(main())


def test_streams_ready_tracks_data_flow_and_stop_clears_it():
    """D-134 — 준비는 데이터 흐름이다. 프레임 1개에 참, stop 뒤에는 거짓으로 돌아간다."""
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        assert not relay.streams_ready()          # 소켓만 열리고 프레임은 없다
        leader.pose_frames.put_nowait(frame(1))
        await settle()
        assert relay.streams_ready()
        await relay.stop()
        assert not relay.streams_ready()          # lane과 리더 flag 둘 다 내린다
    run(main())


def test_a_rate_falls_to_zero_when_the_stream_stops():
    async def main():
        clock = FakeClock()
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], clock=clock, sleep=_no_sleep())
        await relay.start()
        await settle()
        for seq in range(1, 6):
            leader.pose_frames.put_nowait(frame(seq))
            clock.advance(0.1)
            await settle()
        assert relay.stats().leader_rx_hz > 5.0
        assert relay.stats().follower_tx_hz["rosy_02"] > 5.0
        assert relay.stats().follower_last_tx_age_s["rosy_02"] is not None
        assert relay.stats().follower_last_tx_age_s["rosy_02"] < 0.5
        clock.advance(600.0)
        assert relay.stats().leader_rx_hz == 0.0
        assert relay.stats().follower_tx_hz["rosy_02"] == 0.0
        assert relay.stats().leader_age_s >= 600.0
        assert relay.stats().follower_last_tx_age_s["rosy_02"] >= 600.0
        await relay.stop()
    run(main())


def test_a_follower_that_accepts_then_fails_backs_off_instead_of_storming():
    async def main():
        sleeps = []

        async def sleep(s):
            sleeps.append(s)
            await asyncio.sleep(0)

        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        f1.next_sink_fail_on_send = True          # 첫 소켓부터 send 에서 깨진다
        relay = Relay(leader, [f1], sleep=sleep, reconnect_max_s=2.0)
        await relay.start()
        await settle()
        for seq in range(1, 6):
            f1.next_sink_fail_on_send = True      # 다음 소켓도 send 에서 깨진다
            leader.pose_frames.put_nowait(frame(seq))
            await settle(10)
        follower_sleeps = [s for s in sleeps if s > 0]
        assert len(follower_sleeps) >= 3
        assert follower_sleeps[-1] > follower_sleeps[0]          # 커진다
        assert max(follower_sleeps) <= 2.0                       # 상한
        await relay.stop()
    run(main())


def test_a_refused_follower_socket_is_named_in_the_stats():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        f1.sink_error = RobotApiError("rosy_02", 403, "WS_403", "socket rejected during handshake")
        f1.sink_error_sticky = True                              # 토큰을 고칠 때까지 계속 거부
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle(40)
        assert "WS_403" in (relay.stats().follower_last_error["rosy_02"] or "")
        assert not relay.is_connected("rosy_02")
        f1.sink_error = None                                     # 토큰이 고쳐졌다
        await settle(40)
        assert relay.is_connected("rosy_02")                     # 재연결 성공
        # 소켓이 다시 열린 것만으로 이유는 지워진다 — 리더가 아직 조용해도. 첫 송신까지
        # 들고 있으면, 이미 고쳐진 팔로워가 화면에서는 계속 깨져 있다.
        assert relay.stats().follower_last_error["rosy_02"] is None
        leader.pose_frames.put_nowait(frame(1))
        await settle()
        assert f1.sinks[-1].sent == [frame(1)]
        await relay.stop()
    run(main())


def test_start_twice_does_not_double_the_lanes():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await relay.start()
        await settle()
        assert leader.pose_opens == 1 and len(f1.sinks) == 1
        await relay.stop()
    run(main())


def test_duplicate_or_self_following_robots_are_refused():
    leader, a, b = FakeRobot("rosy_01"), FakeRobot("rosy_02"), FakeRobot("rosy_02")
    with pytest.raises(ValueError):
        Relay(leader, [a, b])
    with pytest.raises(ValueError):
        Relay(leader, [a, FakeRobot("rosy_01")])


def test_seq_accounting_ignores_bools_and_accepts_integral_floats_and_resets_on_reconnect():
    async def main():
        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=_no_sleep())
        await relay.start()
        await settle()
        for raw in ('{"payload": {"seq": 1}}', '{"payload": {"seq": true}}', '{"payload": {"seq": 2.0}}',
                    '{"payload": {"seq": 3}}'):
            leader.pose_frames.put_nowait(raw)
        await settle()
        assert relay.stats().leader_dropped == 0
        leader.pose_frames.put_nowait(END)                       # 소켓 단절
        await settle()
        leader.pose_frames.put_nowait('{"payload": {"seq": 50}}')  # 재연결 뒤 seq 가 점프해도
        await settle()
        assert relay.stats().leader_dropped == 0                 # 단절은 드롭이 아니다
        await relay.stop()
    run(main())


def test_a_follower_failure_without_a_code_is_named_in_the_stats_too():
    """RobotApiError 만 이름이 붙던 자리다. 이름 없는 0 Hz 가 릴레이의 가장 나쁜 실패다."""
    async def main():
        gate = asyncio.Event()

        async def sleep(_s):
            # backoff 에서 멈춰 세운다. 소켓이 다시 열리는 순간 이유가 지워지므로,
            # 이유를 보려면 재연결 직전에서 잡아야 한다.
            await gate.wait()

        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        f1.sink_failures = 1                                      # 평범한 ConnectionError
        relay = Relay(leader, [f1], sleep=sleep)
        await relay.start()
        await settle(40)
        assert "cannot open reference socket" in (relay.stats().follower_last_error["rosy_02"] or "")
        assert not relay.is_connected("rosy_02")
        gate.set()
        await settle(40)
        assert relay.is_connected("rosy_02")
        assert relay.stats().follower_last_error["rosy_02"] is None   # 다시 열리면 지운다
        gate.clear()
        f1.sinks[-1].fail_on_send = True                          # 이번엔 송신이 깨진다
        leader.pose_frames.put_nowait(frame(1))
        await settle(40)
        assert "sink broke" in (relay.stats().follower_last_error["rosy_02"] or "")
        await relay.stop()
    run(main())


def test_a_hung_send_times_out_names_itself_and_the_lane_recovers():
    """수신 측이 읽지 않는 WS 는 send 를 영원히 붙잡는다 — connected=true · tx=0 인
    유령 레인이 된다. 타임아웃이 이름을 붙이고 소켓을 끊어 다시 연다(D-131 실측 결함 a)."""
    async def main():
        backoff_gate = asyncio.Event()

        async def sleep(_s):
            # 재연결 직전에서 얼린다 — 다시 열리면 이유는 지워지기 때문이다(설계).
            await backoff_gate.wait()

        leader, f1 = FakeRobot("rosy_01"), FakeRobot("rosy_02")
        relay = Relay(leader, [f1], sleep=sleep, send_timeout_s=0.05)
        await relay.start()
        await settle()
        f1.sinks[0].gate = asyncio.Event()      # 이 소켓의 send 는 영원히 리턴하지 않는다
        for seq in range(1, 4):
            leader.pose_frames.put_nowait(frame(seq))
            await asyncio.sleep(0.08)            # 타임아웃(0.05s)보다 길게 — 실제 시간이 흘러야 한다
        stats = relay.stats()
        assert "timed out" in (stats.follower_last_error["rosy_02"] or "")
        assert stats.follower_tx["rosy_02"] == 0      # 걸린 소켓으로는 한 프레임도 못 보냈다
        assert not relay.is_connected("rosy_02")      # 걸린 소켓은 끊겼다
        backoff_gate.set()                       # 놓아 주면 다시 열리고 이유는 지워진다
        await settle()
        f1.sinks[-1].gate = None                      # 두 번째 소켓은 읽힌다
        leader.pose_frames.put_nowait(frame(9))
        await settle()
        assert frame(9) in f1.sinks[-1].sent          # 다시 열린 소켓으로 흐른다
        assert relay.is_connected("rosy_02")
        assert relay.stats().follower_last_error["rosy_02"] is None   # 다시 열리면 지운다
        await relay.stop()
    run(main())
