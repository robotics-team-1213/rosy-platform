"""D-452: discovery hints never acquire enrollment or execution authority."""
import json
import pytest
from fastapi.testclient import TestClient

from core_common.protocol.network_peers import PeerObservation
from core_common.protocol.schemas import DiscoveryScanPayload
from fleet.server.peer_catalogue import PeerCatalogueStore
from fleet.server.peer_directory import load_approved_peer_directory
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.discovery import DiscoveryStore
from fleet.swarm.robots import RobotEndpoint
from fakes import FakeRobot


def observation(host='robot-a.local', address='192.168.1.10', role='robot'):
    return PeerObservation(name=host.removesuffix('.local'), role=role,
                           transport='https', service_type='_rosy._tcp' if role == 'robot' else '_rosy-fleet._tcp',
                           hostname=host, address=address, port=8443)


def test_ttl_conflict_and_approval_do_not_establish_readiness():
    clock = [0.0]
    store = PeerCatalogueStore(clock=lambda: clock[0])
    assert store.snapshot().scanner_state == 'never_seen'
    store.replace_scan([observation()])
    result = store.snapshot(approved={('robot', 'robot-a.local'): 'robot-1'})
    assert result.peers[0].approval == 'approved'
    assert result.peers[0].readiness == 'unknown'
    store.replace_scan([observation(), observation(address='192.168.1.11')])
    assert all(row.freshness == 'conflict' for row in store.snapshot().peers)
    clock[0] = 46
    assert store.snapshot().scanner_state == 'expired'
    assert all(row.freshness == 'expired' for row in store.snapshot().peers)


def test_scanner_cannot_publish_application_presence_or_exceed_combined_budget():
    client = PeerObservation(name='Pilot', role='pilot', transport='session')
    with pytest.raises(ValueError):
        PeerCatalogueStore().replace_scan([client])
    with pytest.raises(ValueError):
        DiscoveryScanPayload(devices=[{}] * 64, services=[observation()])


def test_viewer_catalogue_is_separate_from_robot_discovery_and_scanner_authority():
    console = FleetConsole([RobotEndpoint('robot-1', 'http://robot-a.local:8080', 'rest-secret')],
                           [FakeRobot('robot-1')])
    client = TestClient(create_app(console, console_token='viewer',
                                   discovery=DiscoveryStore(), discovery_token='scanner'))
    body = {'devices': [], 'services': [observation(host='site.local', role='fleet').model_dump()]}
    assert client.post('/api/fleet/discovery/scan', json=body,
                       headers={'Authorization': 'Bearer viewer'}).status_code == 401
    assert client.post('/api/fleet/discovery/scan', json=body,
                       headers={'Authorization': 'Bearer scanner'}).status_code == 200
    assert client.get('/api/fleet/peers').status_code == 401
    assert client.get('/api/fleet/peers', headers={'Authorization': 'Bearer scanner'}).status_code == 401
    response = client.get('/api/fleet/peers', headers={'Authorization': 'Bearer viewer'})
    assert response.status_code == 200
    assert response.json()['peers'][0]['peer_id'] == 'robot-1'
    assert response.json()['peers'][0]['readiness'] == 'unknown'
    hint = next(peer for peer in response.json()['peers'] if peer['role'] == 'fleet')
    assert hint['approval'] == 'unapproved' and hint['peer_id'] is None
    assert 'rest-secret' not in response.text
    assert client.get('/api/fleet/discovery', headers={'Authorization': 'Bearer viewer'}).json()['devices'] == []


def test_invalid_service_scan_does_not_replace_robot_scan():
    console = FleetConsole([], [])
    client = TestClient(create_app(console, console_token='viewer',
                                   discovery=DiscoveryStore(), discovery_token='scanner'))
    payload = {'devices': [], 'services': [{'name': 'Pilot', 'role': 'pilot', 'transport': 'session'}]}
    assert client.post('/api/fleet/discovery/scan', json=payload,
                       headers={'Authorization': 'Bearer scanner'}).status_code == 400
    assert client.get('/api/fleet/discovery', headers={'Authorization': 'Bearer viewer'}).json()['scanner_state'] == 'never_seen'


@pytest.mark.parametrize('url, hostname, address', [
    ('https://robot-a.example.test:8443', 'robot-a.example.test', None),
    ('http://100.82.51.8:8080', None, '100.82.51.8'),
])
def test_approved_other_network_profiles_remain_visible_without_lan_scan(url, hostname, address):
    console = FleetConsole([RobotEndpoint('robot-remote', url, 'private-token')], [FakeRobot('robot-remote')])
    client = TestClient(create_app(console, console_token='viewer'))
    response = client.get('/api/fleet/peers', headers={'Authorization': 'Bearer viewer'})
    assert response.status_code == 200
    peer = response.json()['peers'][0]
    assert peer['peer_id'] == 'robot-remote' and peer['approval'] == 'approved'
    assert peer['hostname'] == hostname and peer['address'] == address
    assert peer['freshness'] == 'unavailable' and peer['readiness'] == 'unknown'
    assert 'private-token' not in response.text


def test_robot_scan_uses_measured_transport_without_duplicate_service_row():
    console = FleetConsole([], [])
    client = TestClient(create_app(console, console_token='viewer', discovery=DiscoveryStore(), discovery_token='scanner'))
    robot = {'name': 'robot-a', 'hostname': 'robot-a.local', 'address': '192.168.1.10',
             'port': 8443, 'network': 'sta', 'transport': 'https'}
    assert client.post('/api/fleet/discovery/scan', json={'devices': [robot], 'services': []},
                       headers={'Authorization': 'Bearer scanner'}).status_code == 200
    peers = client.get('/api/fleet/peers', headers={'Authorization': 'Bearer viewer'}).json()['peers']
    assert len(peers) == 1 and peers[0]['transport'] == 'https'
    assert peers[0]['approval'] == 'unapproved' and peers[0]['readiness'] == 'unknown'
    robot['transport'] = 'ssh'
    assert client.post('/api/fleet/discovery/scan', json={'devices': [robot]},
                       headers={'Authorization': 'Bearer scanner'}).status_code == 400


def test_robot_services_are_rejected_before_original_scan_changes():
    console = FleetConsole([], [])
    client = TestClient(create_app(console, console_token='viewer', discovery=DiscoveryStore(), discovery_token='scanner'))
    assert client.post('/api/fleet/discovery/scan', json={'devices': [], 'services': [observation().model_dump()]},
                       headers={'Authorization': 'Bearer scanner'}).status_code == 400
    assert client.get('/api/fleet/discovery', headers={'Authorization': 'Bearer viewer'}).json()['scanner_state'] == 'never_seen'


def approved_directory_row(role='model-host'):
    profiles = {'model-host': ('ssh', '_rosy-model._tcp', 22),
                'fleet': ('https', '_rosy-fleet._tcp', 8443),
                'dock': ('http', '_rosy-dock._tcp', 80),
                'signal': ('http', '_rosy-signal._tcp', 80),
                'overhead-camera': ('https', '_rosy-overhead._tcp', 8095)}
    transport, kind, port = profiles[role]
    return dict(name=role, role=role, peer_id=role + '-approved', transport=transport,
                service_type=kind, hostname=role + '.example.test', port=port,
                provenance='approved-directory', approval='approved',
                freshness='unavailable', readiness='unknown')


def test_admin_directory_exposes_all_network_roles_without_scan_or_credentials(tmp_path):
    path = tmp_path / 'peers.json'
    values = [approved_directory_row(role) for role in
              ('model-host', 'fleet', 'dock', 'signal', 'overhead-camera')]
    path.write_text(json.dumps(values), encoding='utf-8')
    client = TestClient(create_app(FleetConsole([], []), console_token='viewer',
                                  approved_peer_directory_file=path))
    response = client.get('/api/fleet/peers', headers={'Authorization': 'Bearer viewer'})
    assert response.status_code == 200
    peers = response.json()['peers']
    assert len(peers) == 5 and all(peer['approval'] == 'approved' for peer in peers)
    assert all(peer['address'] is None and peer['readiness'] == 'unknown' for peer in peers)
    assert response.json()['scanner_state'] == 'never_seen'


@pytest.mark.parametrize('change', [
    {'token': 'must-not-leak'}, {'readiness': 'unreachable'}, {'freshness': 'fresh'},
    {'provenance': 'mdns'}, {'approval': 'unapproved', 'peer_id': None},
])
def test_directory_fails_closed_without_echoing_metadata_values(tmp_path, change):
    path = tmp_path / 'peers.json'
    path.write_text(json.dumps([{**approved_directory_row(), **change}]), encoding='utf-8')
    with pytest.raises(ValueError, match='^invalid approved peer directory metadata$'):
        load_approved_peer_directory(path)


@pytest.mark.parametrize('other', [
    {'hostname': 'another.example.test'}, {'peer_id': 'another-owner'},
])
def test_directory_rejects_duplicate_identity_or_endpoint_owner(tmp_path, other):
    row = approved_directory_row()
    path = tmp_path / 'peers.json'
    path.write_text(json.dumps([row, {**row, **other}]), encoding='utf-8')
    with pytest.raises(ValueError):
        load_approved_peer_directory(path)


def test_directory_rejects_duplicate_json_fields_and_byte_or_row_overflow(tmp_path):
    path = tmp_path / 'peers.json'
    for contents in ('[{"token":"secret","token":"other"}]', ' ' * (1024 * 1024 + 1),
                     json.dumps([approved_directory_row()] * 65)):
        path.write_text(contents, encoding='utf-8')
        with pytest.raises(ValueError):
            load_approved_peer_directory(path)


def test_approved_directory_name_binds_mdns_but_never_promotes_readiness(tmp_path):
    row = approved_directory_row('fleet')
    row['hostname'] = 'site.local'
    path = tmp_path / 'peers.json'
    path.write_text(json.dumps([row]), encoding='utf-8')
    client = TestClient(create_app(FleetConsole([], []), console_token='viewer',
        discovery=DiscoveryStore(), discovery_token='scanner', approved_peer_directory_file=path))
    client.post('/api/fleet/discovery/scan', json={'devices': [],
        'services': [observation(host='site.local', role='fleet').model_dump()]},
        headers={'Authorization': 'Bearer scanner'})
    peers = client.get('/api/fleet/peers', headers={'Authorization': 'Bearer viewer'}).json()['peers']
    assert len(peers) == 1 and peers[0]['peer_id'] == 'fleet-approved'
    assert peers[0]['freshness'] == 'fresh' and peers[0]['readiness'] == 'unknown'


def test_cli_wires_optional_directory_file_into_viewer_catalogue(tmp_path, monkeypatch):
    from fleet import cli
    from fleet.swarm.robots import write_robots
    directory = tmp_path / 'peers.json'
    directory.write_text(json.dumps([approved_directory_row()]), encoding='utf-8')
    robots = tmp_path / 'robots.yaml'
    write_robots(robots, [RobotEndpoint('robot-1', 'http://robot.local:8080', 'rest-secret')])
    captured = {}
    monkeypatch.setattr('uvicorn.run', lambda app, **kwargs: captured.update(app=app))
    args = cli.parse_args(['console', '--robots', str(robots), '--token', 'viewer',
                          '--approved-peer-directory-file', str(directory)])
    cli.run_console(args)
    client = TestClient(captured['app'])
    peers = client.get('/api/fleet/peers', headers={'Authorization': 'Bearer viewer'}).json()['peers']
    assert any(peer['peer_id'] == 'model-host-approved' for peer in peers)


def test_conflicting_enrollment_and_metadata_claims_never_choose_an_owner():
    from types import SimpleNamespace
    from fastapi import FastAPI
    from core_common.protocol.network_peers import PeerSummary
    from fleet.server.peer_routes import install_peer_routes
    store = PeerCatalogueStore()
    store.replace_scan([observation(host='pinky.local')])
    directory = PeerSummary(name='other owner', role='robot', transport='http',
        service_type='_rosy._tcp', hostname='pinky.local', port=8080, peer_id='robot-B',
        provenance='approved-directory', approval='approved', freshness='unavailable')
    app = FastAPI()
    console = FleetConsole([RobotEndpoint('robot-A', 'http://100.82.51.8:8080', 'rest-secret')],
                           [FakeRobot('robot-A')])
    install_peer_routes(app, catalogue=store, console=console,
        enrollment=SimpleNamespace(enrolled_names=lambda: {'pinky': 'robot-A'}),
        pairing=None, read_guard=[], directory_rows=(directory,))
    peers = TestClient(app).get('/api/fleet/peers').json()['peers']
    hint = next(peer for peer in peers if peer['provenance'] == 'mdns')
    assert hint['approval'] == 'unapproved' and hint['peer_id'] is None
    assert hint['freshness'] == 'conflict'
