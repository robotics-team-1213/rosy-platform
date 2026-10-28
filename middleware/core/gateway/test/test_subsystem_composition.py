"""D-628 existing subsystem construction keeps CoreServices identities and ordering."""

from types import SimpleNamespace


def test_subsystem_parsers_keep_the_legacy_services_exports():
    from core import services
    from core.drive import traffic
    from core.system import power

    for name in ("_battery_config", "_power_config", "SHUTDOWN_SENTINEL_NAME"):
        assert getattr(services, name) is getattr(power, name)
    for name in ("_traffic_policy_config", "_signal_observer_binding"):
        assert getattr(services, name) is getattr(traffic, name)


def test_service_build_keeps_subsystem_instances_and_listener_order(core_client, monkeypatch):
    from core import services
    from core.drive import line_follow, traffic
    from core.system import power

    order, built = [], {}

    def tracked(name, implementation):
        def build(*args, **kwargs):
            order.append(name)
            result = implementation(*args, **kwargs)
            built[name] = result
            return result
        return build

    monkeypatch.setattr(services, "build_line_follow", tracked("line", line_follow.build_line_follow))
    monkeypatch.setattr(services, "build_traffic", tracked("traffic", traffic.build_traffic))
    monkeypatch.setattr(services, "build_power_and_battery", tracked("power", power.build_power_and_battery))
    # Exercise real configured monitor construction without starting its external poller.
    monkeypatch.setattr(traffic.SignalObserverMonitor, "start", lambda self: order.append("observer_start"))
    _client, assembled = core_client(config_overrides={
        "traffic_policy": {
            "mode": "MONITOR_ONLY", "map_id": "map_260905_update_v2",
            "scene_revision": "road-scene-v1",
            "signal_observer": {"url": "http://127.0.0.1:9", "roi_map": {"red": "red"}},
        },
    })

    assert order == ["line", "traffic", "observer_start", "power"]
    assert assembled.line_follow is built["line"]
    assert assembled.traffic_policy is built["traffic"][0]
    assert assembled.signal_observer is built["traffic"][1]
    assert assembled.power is built["power"][0]
    assert assembled.battery is built["power"][1]
    assert [fn.__name__ for fn in assembled.modes.change_listeners[:5]] == [
        "_on_mode_change", "mirror_mode", "leave_docking", "drop_return_on_release", "end_on_mode"]
    assert [fn.__name__ for fn in assembled.safety.estop_listeners[:7]] == [
        "_clear_for_stop", "reflect_stop", "on_estop", "on_estop", "<lambda>", "stop_line_follow", "reset_traffic_policy"]


def test_line_follow_constructor_keeps_the_live_manual_angular_provider():
    from core.drive.line_follow import build_line_follow

    safety = SimpleNamespace(limits=SimpleNamespace(manual_angular=.3))
    manager = build_line_follow({}, events=SimpleNamespace(), safety=safety)
    assert manager._angular_ceiling() == .3
    safety.limits.manual_angular = .15
    assert manager._angular_ceiling() == .15


def test_service_build_shares_real_host_owner_across_api_and_status_publication(core_client, tmp_path, monkeypatch):
    from core.system.host_files import HostFileExchange

    path = tmp_path / "status-inputs.json"
    client, svc = core_client(config_overrides={"hardware_probe": {
        "result_path": str(tmp_path / "missing-hardware.json"), "status_inputs_path": str(path)}})
    owner = svc.host_files
    assert isinstance(owner, HostFileExchange)
    readers = []
    original = HostFileExchange.hardware

    def hardware(actual_owner, actual_svc):
        readers.append((actual_owner, actual_svc))
        return original(actual_owner, actual_svc)

    monkeypatch.setattr(HostFileExchange, "hardware", hardware)
    for _ in range(2):
        response = client.get("/api/v1/host/hardware")
        assert response.status_code == 200, response.text
    assert readers == [(owner, svc)] * 2
    owner.write_status_inputs(svc)
    assert path.is_file() and svc.host_files is owner
