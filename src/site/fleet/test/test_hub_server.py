import asyncio
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from core_common.protocol.schemas import HelloPayload, Envelope, EnvelopeType, WelcomePayload
from fleet.hub.hub import SiteHub
from fleet.swarm.robots import RobotEndpoint
from fleet.hub.server import create_hub_app

def _ep(robot_id: str = "rosy_01") -> RobotEndpoint:
    return RobotEndpoint(robot_id, "http://127.0.0.1:8080", "rest-01",
                         fleet_pairing_token="pair-01")

def test_hub_websocket_accepts_hello_and_heartbeat():
    hub = SiteHub([_ep("rosy_01")])
    app = create_hub_app(hub)
    client = TestClient(app)
    
    with client.websocket_connect("/ws/robots") as websocket:
        hello = HelloPayload(robot_id="rosy_01", pairing_token="pair-01")
        env = Envelope(type=EnvelopeType.HELLO, payload=hello.model_dump())
        websocket.send_json(env.model_dump())
        
        data = websocket.receive_json()
        assert data["type"] == "welcome"
        assert hub.registry.online_ids() == ["rosy_01"]
        
        from core_common.protocol.schemas import HeartbeatPayload, StateSnapshot
        hb = HeartbeatPayload(state_snapshot=StateSnapshot(robot_id="rosy_01", seq=1))
        env_hb = Envelope(type=EnvelopeType.HEARTBEAT, payload=hb.model_dump(mode="json"))
        websocket.send_json(env_hb.model_dump(mode="json"))
        
        data2 = websocket.receive_json()
        assert data2["type"] == "heartbeat"
        
def test_hub_websocket_rejects_bad_token():
    hub = SiteHub([_ep("rosy_01")])
    app = create_hub_app(hub)
    client = TestClient(app)
    
    with pytest.raises(Exception): # websocket disconnects
        with client.websocket_connect("/ws/robots") as websocket:
            hello = HelloPayload(robot_id="rosy_01", pairing_token="bad")
            env = Envelope(type=EnvelopeType.HELLO, payload=hello.model_dump())
            websocket.send_json(env.model_dump())
            
            data = websocket.receive_json()
            assert data["type"] == "error"
            websocket.receive_json()



def _hello_env(robot_id: str, token: str) -> dict:
    hello = HelloPayload(robot_id=robot_id, pairing_token=token)
    return Envelope(type=EnvelopeType.HELLO, payload=hello.model_dump()).model_dump()


def _event_env(robot_id: str, seq: int = 1) -> dict:
    from core_common.protocol.schemas import EventMessage
    event = EventMessage(seq=seq, robot_id=robot_id, type="nav.completed")
    return Envelope(type=EnvelopeType.EVENT,
                    payload=event.model_dump(mode="json")).model_dump(mode="json")


def _heartbeat_env(robot_id: str) -> dict:
    from core_common.protocol.schemas import HeartbeatPayload, StateSnapshot
    hb = HeartbeatPayload(state_snapshot=StateSnapshot(robot_id=robot_id, seq=1))
    return Envelope(type=EnvelopeType.HEARTBEAT,
                    payload=hb.model_dump(mode="json")).model_dump(mode="json")


def _two_robot_hub() -> SiteHub:
    return SiteHub([_ep("rosy_01"), RobotEndpoint("rosy_02", "http://127.0.0.1:8081", "rest-02",
                                                  fleet_pairing_token="pair-02")])


def test_socket_cannot_speak_for_another_paired_robot():
    # D-382 F6: pairing binds the socket, not a global set of robot ids.
    hub = _two_robot_hub()
    client = TestClient(create_hub_app(hub))
    with client.websocket_connect("/ws/robots") as ws1, \
            client.websocket_connect("/ws/robots") as ws2:
        ws1.send_json(_hello_env("rosy_01", "pair-01"))
        assert ws1.receive_json()["type"] == "welcome"
        ws2.send_json(_hello_env("rosy_02", "pair-02"))
        assert ws2.receive_json()["type"] == "welcome"

        ws2.send_json(_event_env("rosy_02"))
        assert ws2.receive_json()["payload"] == {"accepted": True}

        ws1.send_json(_event_env("rosy_02"))
        reply = ws1.receive_json()
        assert reply["type"] == "error" and reply["payload"]["code"] == "PAIRING_INVALID"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws1.receive_json()
        assert closed.value.code == 4401
        assert len(hub.registry.record("rosy_02").events) == 1
        # rosy_01 lost its socket; rosy_02's pairing is untouched.
        assert hub.registry.online_ids() == ["rosy_02"]


def test_socket_cannot_send_heartbeat_for_another_robot():
    hub = _two_robot_hub()
    client = TestClient(create_hub_app(hub))
    with client.websocket_connect("/ws/robots") as ws1,             client.websocket_connect("/ws/robots") as ws2:
        ws1.send_json(_hello_env("rosy_01", "pair-01"))
        assert ws1.receive_json()["type"] == "welcome"
        ws2.send_json(_hello_env("rosy_02", "pair-02"))
        assert ws2.receive_json()["type"] == "welcome"
        ws1.send_json(_heartbeat_env("rosy_02"))
        reply = ws1.receive_json()
        assert reply["type"] == "error" and reply["payload"]["code"] == "PAIRING_INVALID"
        assert hub.registry.record("rosy_02").snapshot is None


def test_socket_cannot_rebind_to_a_second_robot():
    hub = _two_robot_hub()
    client = TestClient(create_hub_app(hub))
    with client.websocket_connect("/ws/robots") as ws:
        ws.send_json(_hello_env("rosy_01", "pair-01"))
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json(_hello_env("rosy_02", "pair-02"))
        reply = ws.receive_json()
        assert reply["type"] == "error" and reply["payload"]["code"] == "PAIRING_INVALID"


def test_disconnect_unpairs_the_robot():
    hub = SiteHub([_ep("rosy_01")])
    client = TestClient(create_hub_app(hub))
    with client.websocket_connect("/ws/robots") as ws:
        ws.send_json(_hello_env("rosy_01", "pair-01"))
        assert ws.receive_json()["type"] == "welcome"
    assert hub.registry.online_ids() == []
    # In-process callers without a session see the robot as unpaired too.
    reply = hub.handle(Envelope.model_validate(_event_env("rosy_01")))
    assert reply.type is EnvelopeType.ERROR


def test_old_socket_closing_after_reconnect_keeps_the_new_pairing():
    hub = SiteHub([_ep("rosy_01")])
    old, new = hub.open_session(), hub.open_session()
    hello = Envelope.model_validate(_hello_env("rosy_01", "pair-01"))
    assert hub.handle(hello, session=old).type is EnvelopeType.WELCOME
    assert hub.handle(hello, session=new).type is EnvelopeType.WELCOME
    hub.close_session(old)
    assert hub.registry.online_ids() == ["rosy_01"]
    event = Envelope.model_validate(_event_env("rosy_01"))
    assert hub.handle(event, session=new).payload == {"accepted": True}
    assert hub.handle(event, session=old).type is EnvelopeType.ERROR


def test_a_refused_event_keeps_the_robot_link(tmp_path):
    """D-407 re-run 2026-10-02: EVENT_NOT_AUDITABLE refuses that event only; the socket stays
    open and the next heartbeat is answered (the agent drains every reply)."""
    from core_common.protocol.schemas import EventMessage
    from fleet.server.core_event_store import CoreEventStore

    hub = SiteHub([_ep("rosy_01")], event_store=CoreEventStore(tmp_path / "events.db"))
    client = TestClient(create_hub_app(hub))
    with client.websocket_connect("/ws/robots") as ws:
        ws.send_json(_hello_env("rosy_01", "pair-01"))
        assert ws.receive_json()["type"] == "welcome"
        bad = EventMessage(seq=1, robot_id="rosy_01", type="nav.line_stuck_answered",
                           data={"stuck_id": "s", "token_id": "abc"})
        ws.send_json(Envelope(type=EnvelopeType.EVENT,
                              payload=bad.model_dump(mode="json")).model_dump(mode="json"))
        reply = ws.receive_json()
        assert reply["type"] == "error" and reply["payload"]["code"] == "EVENT_NOT_AUDITABLE"
        ws.send_json(_heartbeat_env("rosy_01"))
        assert ws.receive_json()["type"] == "heartbeat"
        assert hub.registry.online_ids() == ["rosy_01"]


def test_send_reply_never_sends_into_a_closed_socket():
    """Review L5: the hub's reply guard (D-407 re-run 'websocket.send after websocket.close')."""
    from starlette.websockets import WebSocketState
    from fleet.hub.server import send_reply

    reply = Envelope(type=EnvelopeType.HEARTBEAT, payload={})

    class Socket:
        def __init__(self, state, fail=None):
            self.client_state = state
            self.fail = fail
            self.sent = []

        async def send_json(self, data):
            if self.fail:
                raise self.fail
            self.sent.append(data)

    closed = Socket(WebSocketState.DISCONNECTED)
    assert asyncio.run(send_reply(closed, reply)) is False and closed.sent == []
    racing = Socket(WebSocketState.CONNECTED, RuntimeError(
        "Unexpected ASGI message 'websocket.send', after sending 'websocket.close'."))
    assert asyncio.run(send_reply(racing, reply)) is False
    gone = Socket(WebSocketState.CONNECTED, WebSocketDisconnect(1006))
    assert asyncio.run(send_reply(gone, reply)) is False
    live = Socket(WebSocketState.CONNECTED)
    assert asyncio.run(send_reply(live, reply)) is True and live.sent[0]["type"] == "heartbeat"
