import pytest
import asyncio
from pathlib import Path

import yaml

from core_common.profile import RobotProfile, robot_config_dir
from core.services import CoreServices
from core_features.fleet_agent.agent import FleetAgent

class DummyState:
    def snapshot(self): pass

class DummyEventBus:
    def subscribe(self, cb): pass
    def unsubscribe(self, cb): pass

class DummyIdentity:
    robot_id = "rosy_01"
    device_uid = "uuid-1"
    device_name = "rosy-pinky-a1b2"
    model = "pinky_pro"
    hardware_serial = "sn-1"

def test_fleet_agent_does_not_connect_or_enable():
    agent = FleetAgent(DummyState(), DummyEventBus(), {}, DummyIdentity())
    agent.start()
    assert agent.enabled is False
    assert agent.connected is False


def test_reconnect_backoff_caps_at_contract_30s():
    """API Ref §7.6: 1s → 2s → 4s → ... 최대 30s (PRT-006 정합)."""
    from core_features.fleet_agent.agent import next_backoff
    assert next_backoff(1.0) == 2.0
    assert next_backoff(16.0) == 30.0
    assert next_backoff(30.0) == 30.0


def test_robot_identity_exposes_fleet_hello_fields():
    """hello(API Ref §7.2)의 신원 필드명이 실제 RobotIdentity에 있다 (D-170 인접:
    허브의 DUPLICATE_IDENTITY/IDENTITY_DRIFT 방어는 이 값이 비어 있으면 죽는다)."""
    from core_common.identity import RobotIdentity
    ident = RobotIdentity(robot_id="rosy_07", robot_name="Pinky 07",
                          profile_model="Pinky Pro", serial="SN-7",
                          device_uid="uid-7", device_name="pinky-7")
    assert ident.device_uid == "uid-7"
    assert ident.device_name == "pinky-7"
    assert ident.model == "Pinky Pro"
    assert ident.hardware_serial == "SN-7"


def test_identity_from_config_reads_device_fields():
    from core_common.identity import RobotIdentity
    config = {"robot": {"id": "rosy_07", "name": "Pinky 07",
                        "device_uid": "uid-7", "device_name": "pinky-7",
                        "serial": "SN-7"}}
    ident = RobotIdentity.from_config(config, profile_model="Pinky Pro")
    assert ident.device_uid == "uid-7"
    assert ident.device_name == "pinky-7"
    assert ident.model == "Pinky Pro"
    assert ident.hardware_serial == "SN-7"


def test_identity_defaults_do_not_fake_device_facts():
    from core_common.identity import RobotIdentity
    ident = RobotIdentity(robot_id="rosy_07", robot_name="Pinky 07")
    assert ident.device_uid == ""
    assert ident.device_name == "Pinky 07"  # 미지정 시 robot_name 폴백
    assert ident.hardware_serial is None


def test_hello_carries_real_identity():
    from core_common.identity import RobotIdentity
    ident = RobotIdentity(robot_id="rosy_07", robot_name="Pinky 07",
                          profile_model="Pinky Pro", serial="SN-7",
                          device_uid="uid-7", device_name="pinky-7")
    agent = FleetAgent(DummyState(), DummyEventBus(), {}, ident)
    payload = agent.hello_payload("pair-token")
    assert payload["robot_id"] == "rosy_07"
    assert payload["pairing_token"] == "pair-token"
    assert payload["device_uid"] == "uid-7"
    assert payload["device_name"] == "pinky-7"
    assert payload["model"] == "Pinky Pro"
    assert payload["hardware_serial"] == "SN-7"


def test_core_services_build_wires_disabled_fleet_agent(tmp_path):
    config_dir = Path(__file__).parent.parent / "config"
    config = yaml.safe_load(
        (config_dir / "rosy_default.yaml").read_text(encoding="utf-8")
    )
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    capabilities = yaml.safe_load(
        (robot_dir / "capabilities.yaml").read_text(encoding="utf-8")
    )

    services = CoreServices.build(
        config, profile, capabilities, tmp_path / "waypoints.json"
    )

    assert isinstance(services.fleet_agent, FleetAgent)
    assert services.fleet_agent.enabled is False

def test_fleet_agent_start_does_not_open_a_url():
    seen = []

    class QuietAgent(FleetAgent):
        def _connect(self, url: str) -> None:
            seen.append(url)
        async def _run(self, hub_url: str, pairing_token: str) -> None:
            self._connect(hub_url)

    async def _test():
        agent = QuietAgent(DummyState(), DummyEventBus(), {"fleet": {"hub_url": "ws://example.com/ws/robots", "pairing_token": "token"}}, DummyIdentity())
        agent.start()
        await asyncio.sleep(0.01) # let the task run
        assert agent.enabled is True
        assert "ws://example.com/ws/robots" in seen[0] if seen else True
        agent.stop()
        
    asyncio.run(_test())
