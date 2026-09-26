import pytest
from core_common.protocol.schemas import HelloPayload, Envelope, EnvelopeType
from fleet.hub.hub import SiteHub
from fleet.swarm.robots import RobotEndpoint

def _ep(robot_id: str = "rosy_01") -> RobotEndpoint:
    suffix = robot_id.rsplit("_", 1)[-1]
    return RobotEndpoint(
        robot_id, "http://127.0.0.1:8080", f"rest-{suffix}",
        fleet_pairing_token=f"pair-{suffix}",
    )

def _hello(robot_id="rosy_01", token=None, uid="uuid-1", name="rosy-pinky-a1b2", serial="sn-1"):
    suffix = robot_id.rsplit("_", 1)[-1]
    token = token or f"pair-{suffix}"
    payload = HelloPayload(
        robot_id=robot_id, 
        pairing_token=token, 
        device_uid=uid, 
        device_name=name,
        hardware_serial=serial
    ).model_dump()
    return Envelope(type=EnvelopeType.HELLO, payload=payload)

def test_two_pinky_devices_register_as_two_robots():
    hub = SiteHub([_ep("rosy_01"), _ep("rosy_02")])
    
    reply1 = hub.handle(_hello(robot_id="rosy_01", token="pair-01", uid="uuid-1", name="rosy-pinky-aaaa", serial="sn-1"))
    assert reply1.type is EnvelopeType.WELCOME
    
    reply2 = hub.handle(_hello(robot_id="rosy_02", token="pair-02", uid="uuid-2", name="rosy-pinky-bbbb", serial="sn-2"))
    assert reply2.type is EnvelopeType.WELCOME
    
    assert set(hub.registry.online_ids()) == {"rosy_01", "rosy_02"}

def test_reject_duplicate_uuid():
    hub = SiteHub([_ep("rosy_01"), _ep("rosy_02")])
    hub.handle(_hello(robot_id="rosy_01", uid="uuid-1"))
    reply = hub.handle(_hello(robot_id="rosy_02", uid="uuid-1"))
    assert reply.type is EnvelopeType.ERROR
    assert reply.payload["code"] == "DUPLICATE_IDENTITY"

def test_reject_hardware_serial_drift():
    hub = SiteHub([_ep("rosy_01")])
    hub.handle(_hello(robot_id="rosy_01", serial="sn-1"))
    reply = hub.handle(_hello(robot_id="rosy_01", serial="sn-2"))
    assert reply.type is EnvelopeType.ERROR
    assert reply.payload["code"] == "IDENTITY_DRIFT"

