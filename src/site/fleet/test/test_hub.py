"""SiteHub는 계약 envelope만 모은다. 바퀴 속도와 원본 영상은 거절한다 (D-59)."""

from fakes import FakeRobot, run

from core_common.protocol.schemas import (
    Envelope,
    EnvelopeType,
    EventMessage,
    HeartbeatPayload,
    HelloPayload,
    StateSnapshot,
)
from fleet.swarm.robots import RobotEndpoint
from fleet.hub.hub import SiteHub


def _ep(robot_id: str = "rosy_01") -> RobotEndpoint:
    return RobotEndpoint(robot_id, "http://127.0.0.1:8080", "pair-01")


def _hello(robot_id="rosy_01", token="pair-01") -> Envelope:
    payload = HelloPayload(robot_id=robot_id, pairing_token=token).model_dump()
    return Envelope(type=EnvelopeType.HELLO, payload=payload)


def test_hello_with_known_token_is_welcomed_and_listed_online():
    hub = SiteHub([_ep()])
    reply = hub.handle(_hello())
    assert reply.type is EnvelopeType.WELCOME
    assert reply.payload["robot_id"] == "rosy_01"
    assert hub.registry.online_ids() == ["rosy_01"]


def test_hello_with_wrong_token_is_pairing_invalid_and_stays_offline():
    hub = SiteHub([_ep()])
    reply = hub.handle(_hello(token="nope"))
    assert reply.type is EnvelopeType.ERROR
    assert reply.payload["code"] == "PAIRING_INVALID"
    assert hub.registry.online_ids() == []


def _hello_with_identity(robot_id="rosy_01", token="pair-01",
                         device_uid="", device_name="",
                         model="", hardware_serial="") -> Envelope:
    payload = HelloPayload(
        robot_id=robot_id, pairing_token=token, device_uid=device_uid,
        device_name=device_name, model=model,
        hardware_serial=hardware_serial).model_dump()
    return Envelope(type=EnvelopeType.HELLO, payload=payload)


def test_second_robot_with_same_device_uid_is_duplicate_identity():
    hub = SiteHub([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "pair-01"),
                   RobotEndpoint("rosy_02", "http://127.0.0.1:8081", "pair-02")])
    first = hub.handle(_hello_with_identity("rosy_01", "pair-01",
                                            device_uid="uid-shared"))
    assert first.type is EnvelopeType.WELCOME
    second = hub.handle(_hello_with_identity("rosy_02", "pair-02",
                                             device_uid="uid-shared"))
    assert second.type is EnvelopeType.ERROR
    assert second.payload["code"] == "DUPLICATE_IDENTITY"
    assert hub.registry.online_ids() == ["rosy_01"]


def test_changed_hardware_serial_for_same_robot_is_identity_drift():
    hub = SiteHub([_ep()])
    first = hub.handle(_hello_with_identity("rosy_01", "pair-01",
                                            hardware_serial="SN-1"))
    assert first.type is EnvelopeType.WELCOME
    drifted = hub.handle(_hello_with_identity("rosy_01", "pair-01",
                                              hardware_serial="SN-OTHER"))
    assert drifted.type is EnvelopeType.ERROR
    assert drifted.payload["code"] == "IDENTITY_DRIFT"


def test_heartbeat_before_hello_is_rejected():
    hub = SiteHub([_ep()])
    snap = StateSnapshot(robot_id="rosy_01")
    env = Envelope(
        type=EnvelopeType.HEARTBEAT,
        payload=HeartbeatPayload(state_snapshot=snap).model_dump(mode="json"),
    )
    reply = hub.handle(env)
    assert reply.type is EnvelopeType.ERROR
    assert reply.payload["code"] == "SESSION_NOT_PAIRED"


def test_heartbeat_updates_registry_snapshot():
    hub = SiteHub([_ep()])
    hub.handle(_hello())
    snap = StateSnapshot(robot_id="rosy_01", seq=4)
    env = Envelope(
        type=EnvelopeType.HEARTBEAT,
        payload=HeartbeatPayload(state_snapshot=snap).model_dump(mode="json"),
    )
    reply = hub.handle(env)
    assert reply.type is not EnvelopeType.ERROR
    stored = hub.registry.record("rosy_01").snapshot
    assert stored is not None
    assert stored.seq == 4


def test_events_are_kept_in_seq_order_and_gap_fill_reads_since_seq():
    hub = SiteHub([_ep()])
    hub.handle(_hello())
    for seq in (1, 2, 3):
        event = EventMessage(seq=seq, robot_id="rosy_01", type="nav.completed")
        hub.handle(Envelope(type=EnvelopeType.EVENT, payload=event.model_dump(mode="json")))
    filled = hub.registry.events_since("rosy_01", since_seq=1)
    assert [e.seq for e in filled] == [2, 3]


def test_event_robot_id_mismatch_after_hello_is_pairing_invalid():
    hub = SiteHub([_ep()])
    hub.handle(_hello())
    event = EventMessage(seq=1, robot_id="rosy_99", type="nav.completed")
    reply = hub.handle(Envelope(type=EnvelopeType.EVENT, payload=event.model_dump(mode="json")))
    assert reply.type is EnvelopeType.ERROR
    assert reply.payload["code"] == "PAIRING_INVALID"


def test_inbound_command_envelope_is_role_violation():
    hub = SiteHub([_ep()])
    hub.handle(_hello())
    reply = hub.handle(Envelope(type=EnvelopeType.COMMAND, payload={"twist": {"linear": 0.2}}))
    assert reply.type is EnvelopeType.ERROR
    assert reply.payload["code"] == "ROLE_VIOLATION"


def test_payload_with_cmd_vel_or_image_is_role_violation():
    hub = SiteHub([_ep()])
    hub.handle(_hello())
    for payload in ({"cmd_vel": {"linear": 0.1}}, {"image": "base64"}, {"Image": True}):
        reply = hub.handle(Envelope(type=EnvelopeType.EVENT, payload=payload))
        assert reply.payload["code"] == "ROLE_VIOLATION", payload


def test_peer_source_is_rejected_on_follow_scatter_params():
    """D-31: peer 소스는 계약에 있지만 허브는 거절한다."""
    from core_common.protocol.schemas import SwarmFollowParams, SwarmReferenceSource

    params = SwarmFollowParams(
        target_robot_id="rosy_01",
        source=SwarmReferenceSource.PEER,
    )
    hub = SiteHub([_ep()])
    try:
        hub.assert_scatterable(params)
    except Exception as exc:
        assert getattr(exc, "code", None) == "ROLE_VIOLATION" or "peer" in str(exc).lower()
    else:
        raise AssertionError("peer follow must not scatter")


def test_scatter_estop_calls_robot_rest_not_a_twist():
    async def main():
        robot = FakeRobot("rosy_01")
        hub = SiteHub([_ep()], clients={"rosy_01": robot})
        hub.handle(_hello())
        result = await hub.scatter_estop("rosy_01")
        assert result == {"estop": True}
        assert robot.calls == [("estop",)]
        assert not any("cmd_vel" in str(c) or "twist" in str(c).lower() for c in robot.calls)

    run(main())


def test_scatter_estop_unknown_robot_errors():
    async def main():
        hub = SiteHub([_ep()])
        try:
            await hub.scatter_estop("rosy_99")
        except Exception as exc:
            assert "rosy_99" in str(exc) or getattr(exc, "code", "") == "UNKNOWN_ROBOT"
        else:
            raise AssertionError("missing client must fail")

    run(main())
