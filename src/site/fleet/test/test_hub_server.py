import asyncio
import pytest
from fastapi.testclient import TestClient
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

