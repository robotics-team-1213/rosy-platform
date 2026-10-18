"""Purpose-specific routes preserve legacy consumers and source authority."""
import copy
import json
from pathlib import Path

from core_common.protocol.measured_calibration import bundle_digest
from test_overhead_tracking_api import _client, _auth, _Clock, OPERATOR_TOKEN, VIEWER_TOKEN, SOURCE_TOKEN


def approval():
    raw = json.loads((Path(__file__).resolve().parents[3]
                      / 'test/fixtures/protocol/measured-calibration.v1.json').read_text())
    raw['evidence_kind'] = 'measured'
    raw['digest'] = bundle_digest(raw)
    return {'purpose': 'preview', 'kind': 'measured', 'bundle': raw,
            'expected_revision': None, 'limits': {'p95_m': .01, 'max_m': .02}}


def prepared(tmp_path, clock=None, vision=False):
    options = {'vision_lease_secret': 'v'*32, 'vision_sources': ('ceiling_north',)} if vision else None
    client = _client(tmp_path, clock=clock, app_options=options)
    # A configured current map; simulated numeric evidence is not field acceptance.
    service = getattr(client.app.state, 'measured_calibration', None)
    assert service is not None, 'measured preview service must be installed by create_app'
    service.map_revision = lambda map_id: 'site-map-5'
    return client


def test_new_approval_config_and_revoke_leave_legacy_contract_unchanged(tmp_path):
    with prepared(tmp_path) as client:
        legacy = client.get('/api/fleet/calibrations', headers=_auth(VIEWER_TOKEN)).json()
        response = client.post('/api/fleet/calibrations', json=approval(), headers=_auth(OPERATOR_TOKEN))
        assert response.status_code == 200, response.text
        row = response.json()
        assert row['use'] == 'preview-only' and row['approved_by'] == 'operator-1'
        assert client.get('/api/fleet/calibrations', headers=_auth(VIEWER_TOKEN)).json() == legacy
        default = client.get('/api/fleet/detections/config', headers=_auth(SOURCE_TOKEN)).json()
        assert 'measured_preview' not in default and default['calibration'] is None
        cfg = client.get('/api/fleet/detections/config?include_preview=true', headers=_auth(SOURCE_TOKEN)).json()
        assert cfg['measured_preview']['record']['calibration_revision'] == row['calibration_revision']
        stale = client.delete('/api/fleet/calibrations/ceiling_north?purpose=preview&expected_revision=old',
                               headers=_auth(OPERATOR_TOKEN))
        assert stale.status_code == 409
        result = client.delete('/api/fleet/calibrations/ceiling_north',
                               params={'purpose': 'preview', 'expected_revision': row['calibration_revision']},
                               headers=_auth(OPERATOR_TOKEN))
        assert result.status_code == 200 and result.json()['removed']


def test_preview_authority_limits_and_map_revision_are_checked(tmp_path):
    with prepared(tmp_path) as client:
        for token in (VIEWER_TOKEN, SOURCE_TOKEN):
            assert client.post('/api/fleet/calibrations', json=approval(), headers=_auth(token)).status_code in (401, 403)
        bad = copy.deepcopy(approval())
        bad['bundle']['evidence_kind'] = 'synthetic'
        bad['bundle']['digest'] = bundle_digest(bad['bundle'])
        assert client.post('/api/fleet/calibrations', json=bad, headers=_auth(OPERATOR_TOKEN)).status_code == 422
        client.app.state.measured_calibration.map_revision = lambda map_id: 'changed'
        assert client.post('/api/fleet/calibrations', json=approval(), headers=_auth(OPERATOR_TOKEN)).status_code == 409


def test_source_report_is_bound_to_current_revision_and_expires(tmp_path):
    clock = _Clock()
    with prepared(tmp_path, clock=clock) as client:
        row = client.post('/api/fleet/calibrations', json=approval(), headers=_auth(OPERATOR_TOKEN)).json()
        body = {'source_id': 'ceiling_north', 'calibration_revision': row['calibration_revision'],
                'session_id': 'receiver-one-link-one', 'state': 'applied', 'reason': 'ok', 'frame_seq': 2}
        assert client.post('/api/fleet/detections/preview-status', json=body,
                           headers=_auth(OPERATOR_TOKEN)).status_code == 401
        wrong = {**body, 'source_id': 'other'}
        assert client.post('/api/fleet/detections/preview-status', json=wrong,
                           headers=_auth(SOURCE_TOKEN)).status_code == 403
        assert client.post('/api/fleet/detections/preview-status', json={**body, 'jpeg': 'forbidden'},
                           headers=_auth(SOURCE_TOKEN)).status_code == 422
        assert client.post('/api/fleet/detections/preview-status', json=body,
                           headers=_auth(SOURCE_TOKEN)).status_code == 200
        url = '/api/fleet/calibrations?purpose=preview'
        listed = client.get(url, headers=_auth(VIEWER_TOKEN)).json()['calibrations'][0]
        assert listed['readback']['state'] == 'applied'
        clock.now += 5.01
        listed = client.get(url, headers=_auth(VIEWER_TOKEN)).json()['calibrations'][0]
        assert listed['readback']['state'] != 'applied'
        client.app.state.measured_calibration.map_revision = lambda map_id: 'changed'
        cfg = client.get('/api/fleet/detections/config?include_preview=true', headers=_auth(SOURCE_TOKEN)).json()
        assert cfg['measured_preview']['record'] is None
        assert cfg['measured_preview']['reason'] == 'map_changed'


def test_only_named_operator_can_sign_a_current_session_confirmation(tmp_path):
    from core_common.protocol.vision_preview import VisionLeaseSigner
    with prepared(tmp_path, vision=True) as client:
        row = client.post('/api/fleet/calibrations', json=approval(), headers=_auth(OPERATOR_TOKEN)).json()
        measured = {'calibration_revision': row['calibration_revision'], 'session_id': 'receiver:1',
                    'capture_signature': row['bundle']['capture']['signature'], 'confirm_conditions': True}
        body = {'source_id': 'ceiling_north', 'measured': measured}
        endpoint = '/api/fleet/vision/lease'
        assert client.post(endpoint, json=body, headers=_auth(VIEWER_TOKEN)).status_code == 403
        response = client.post(endpoint, json=body, headers=_auth(OPERATOR_TOKEN))
        assert response.status_code == 200, response.text
        claims = VisionLeaseSigner('v'*32).verify(response.json()['lease'], source_id='ceiling_north')
        assert claims['measured'] == measured
        body['measured']['confirm_conditions'] = False
        assert client.post(endpoint, json=body, headers=_auth(VIEWER_TOKEN)).status_code == 200
        body['measured']['calibration_revision'] = 'old'
        assert client.post(endpoint, json=body, headers=_auth(OPERATOR_TOKEN)).status_code == 409
