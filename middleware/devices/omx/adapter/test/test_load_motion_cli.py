"""End-to-end local-file contracts, exercised only on the remote test host."""
import json

import pytest

from load_motion_fixtures import characteristics, health, request
from omx_adapter.motion_characteristics import characteristics_digest, save_characteristics
from omx_adapter.load_motion_cli import main


def inputs(tmp_path):
    p = characteristics()
    r = request(p)
    profile, req = tmp_path / 'profile.json', tmp_path / 'request.json'
    save_characteristics(profile, p)
    req.write_text(json.dumps(r))
    return p, r, profile, req


def test_save_and_assess_persist_machine_readable_non_authority(tmp_path, capsys):
    p, _, profile, req = inputs(tmp_path)
    saved, out = tmp_path / 'saved.json', tmp_path / 'assessment.json'
    assert main(['save', str(profile), str(saved)]) == 0
    assert json.loads(saved.read_text()) == p
    capsys.readouterr()
    assert main(['assess', str(saved), str(req), '--accepted-sha256', characteristics_digest(p),
                 '--output', str(out)]) == 0
    row = json.loads(out.read_text())
    assert row == json.loads(capsys.readouterr().out)
    assert row['selected_candidate_id'] == 'direct'
    assert row['motion_admitted'] is False


def test_assessment_does_not_overwrite_any_input(tmp_path, capsys):
    p, _, profile, req = inputs(tmp_path)
    original = req.read_bytes()
    assert main(['assess', str(profile), str(req), '--accepted-sha256', characteristics_digest(p),
                 '--output', str(req)]) == 2
    assert req.read_bytes() == original
    assert json.loads(capsys.readouterr().out)['motion_admitted'] is False


def test_no_matching_domain_is_a_reported_refusal(tmp_path, capsys):
    p, r, profile, req = inputs(tmp_path)
    r['payload_mass_kg'] = [1., 2.]
    req.write_text(json.dumps(r))
    assert main(['assess', str(profile), str(req), '--accepted-sha256', characteristics_digest(p)]) == 3
    assert json.loads(capsys.readouterr().out)['selected_candidate_id'] is None


def test_watch_consumes_existing_snapshot_and_writes_recovery_recommendation(tmp_path, capsys, monkeypatch):
    from core_common.motor_health import write_motor_health_snapshot
    p, _, profile, req = inputs(tmp_path)
    path, out = tmp_path / 'health.json', tmp_path / 'watch.json'
    h = health(p, fault=True)
    row = {'schema_version': 'rosy.motor-health.v1', 'owner_id': h.owner_id, 'session_id': h.session_id,
           'status': 'fault', 'observed_at': 100., 'terminal_at': 100., 'expected_motor_count': 2,
           'motors': [{**m.model_dump(exclude={'sample_age_s'}), 'observed_at': 100.} for m in h.motors],
           'stop_reasons': ['hardware error']}
    write_motor_health_snapshot(path, row)
    monkeypatch.setattr('omx_adapter.load_motion_cli.time.time', lambda: 100.)
    args = ['watch', str(profile), str(req), '--accepted-sha256', characteristics_digest(p),
            '--health', str(path), '--candidate-id', 'direct', '--command-id', 'fixture-command',
            '--session-id', h.session_id, '--started-at', '100', '--samples', '1', '--interval-s', '.05',
            '--output', str(out)]
    assert main(args) == 3
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(out.read_text())
    assert report['status'] == 'hold_for_owner_review'
    assert report['automatic_recovery_enabled'] is False
    assert path.read_bytes() == path.read_bytes()  # Input is not an output destination.


def test_watch_missing_source_is_a_persisted_hold_not_a_healthy_sample(tmp_path, capsys, monkeypatch):
    p, _, profile, req = inputs(tmp_path)
    monkeypatch.setattr('omx_adapter.load_motion_cli.time.time', lambda: 100.)
    assert main(['watch', str(profile), str(req), '--accepted-sha256', characteristics_digest(p),
                 '--health', str(tmp_path / 'missing.json'), '--candidate-id', 'direct',
                 '--command-id', 'fixture-command', '--session-id',
                 '00000000-0000-4000-8000-000000000001', '--started-at', '100',
                 '--samples', '1', '--interval-s', '.05']) == 3
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'hold_for_owner_review'
    assert report['captured_at'] is None
    assert report['errors_rad'] == {}
