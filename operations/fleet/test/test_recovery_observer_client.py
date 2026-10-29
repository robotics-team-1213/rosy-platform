"""The independent observer submits facts once and never approves recovery."""
import copy
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from test_transfer_recovery_api import (
    failed_api, rig, geometry, policy, installation, request_recovery, headers, measured, _document,
)
from test_physical_transfer_observer_api import TOKEN
from test_physical_transfer_store import NOW


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[3] / 'tools/sim/recovery_observer.py'
    assert path.is_file(), 'independent recovery observation client is not implemented'
    spec = importlib.util.spec_from_file_location('recovery_observer', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ApiTransport:
    def __init__(self, case):
        self.case, self.calls, self.lose_reply = case, [], False

    def open(self, request, timeout):
        method = request.get_method()
        self.calls.append((method, request.full_url, request.data))
        response = self.case.client.request(method, request.full_url,
            headers=dict(request.header_items()), content=request.data)
        if method == 'POST' and self.lose_reply:
            raise TimeoutError('response lost after server processing')
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, 'request rejected', None, None)
        return io.BytesIO(response.content)


def ready(module, case, monkeypatch):
    request_recovery(case)
    client = module.Client('http://127.0.0.1:8765', TOKEN)
    client.opener = ApiTransport(case)
    context = client.context()
    state = case.app.state.arm_transfer_dispatcher.execution.snapshot(case.parent)
    samples = _document(measured(case.store, state, offset=1_200_000_000, sequence=20))
    case.clock[0] = NOW + 1_500_000_000
    monkeypatch.setattr(module, 'time_ns', lambda: case.clock[0])
    return client, context, samples


def test_actual_api_accepts_facts_without_creating_or_dispatching_a_child(module, failed_api, monkeypatch):
    case = failed_api
    client, context, samples = ready(module, case, monkeypatch)
    before = copy.deepcopy(samples)
    reply = client.submit(context, samples)
    assert len(reply['evidence_digest']) == 64 and samples == before
    view = case.client.get(case.url + '/recovery', headers=headers('harbor')).json()['recovery']
    assert view['status'] == 'READY_FOR_APPROVAL' and view['child_mission_id'] is None
    assert case.client.get(case.url, headers=headers('harbor')).json()['job']['status'] == 'HOLD'
    assert len(case.port.submitted) == 1
    posts = [call for call in client.opener.calls if call[0] == 'POST']
    assert len(posts) == 1 and posts[0][1].endswith('/observations')
    assert json.loads(posts[0][2])['observations'] == before


@pytest.mark.parametrize('change', ['action', 'attempt', 'producer', 'policy', 'owner', 'stale', 'future', 'order', 'spacing'])
def test_bad_bindings_or_source_times_are_refused_before_post(module, failed_api, monkeypatch, change):
    client, context, samples = ready(module, failed_api, monkeypatch)
    samples = copy.deepcopy(samples)
    if change in ('action', 'attempt'):
        samples[0][change + '_id'] = '00000000-0000-4000-8000-000000000099'
    elif change == 'producer':
        samples[0]['producer_id'] = 'another-producer'
    elif change == 'policy':
        samples[0]['policy_digest'] = '9' * 64
    elif change == 'owner':
        samples[0]['owners'][0]['owner_session_id'] = 'another-session'
    elif change in ('stale', 'future'):
        samples[0]['object_observed_at_ns'] = NOW if change == 'stale' else NOW + 9_000_000_000
    elif change == 'order':
        samples[1]['sequence'] = samples[0]['sequence']
    else:
        samples[1]['object_observed_at_ns'] = samples[0]['object_observed_at_ns']
    with pytest.raises(ValueError):
        client.submit(context, samples)
    assert not any(method == 'POST' for method, _, _ in client.opener.calls)


def test_replaced_context_is_not_used_to_relabel_old_observations(module, failed_api, monkeypatch):
    client, context, samples = ready(module, failed_api, monkeypatch)
    request_recovery(failed_api, key='replacement')
    with pytest.raises(ValueError, match='context'):
        client.submit(context, samples)
    assert not any(method == 'POST' for method, _, _ in client.opener.calls)


def test_lost_post_reply_is_unconfirmed_and_never_retried(module, failed_api, monkeypatch):
    client, context, samples = ready(module, failed_api, monkeypatch)
    client.opener.lose_reply = True
    with pytest.raises(module.SubmissionUnconfirmed):
        client.submit(context, samples)
    assert sum(method == 'POST' for method, _, _ in client.opener.calls) == 1
    view = failed_api.client.get(failed_api.url + '/recovery', headers=headers('harbor')).json()['recovery']
    assert view['status'] == 'READY_FOR_APPROVAL' and view['child_mission_id'] is None


@pytest.mark.parametrize('origin', ['http://example.invalid:80', 'https://user:password@example.invalid',
    'https://example.invalid/other', 'https://example.invalid?x=1', 'http://127.0.0.1',
    'https://example.invalid\\@other.invalid', 'https://example.invalid\n'])
def test_unsafe_destination_is_rejected_before_credentials_leave(module, origin):
    with pytest.raises(ValueError):
        module.Client(origin, TOKEN)


def test_wrong_token_cannot_read_context(module, failed_api):
    client = module.Client('http://127.0.0.1:8765', 'wrong-observer-token-' * 3)
    client.opener = ApiTransport(failed_api)
    with pytest.raises(HTTPError):
        client.context()
    assert len(client.opener.calls) == 1


def test_saved_context_is_exclusive_external_and_contains_no_token(module, failed_api, monkeypatch, tmp_path):
    client, _, _ = ready(module, failed_api, monkeypatch)
    output = tmp_path / 'context.json'
    client.save_context(output)
    assert TOKEN not in output.read_text()
    assert json.loads(output.read_bytes())['context']['purpose'] == 'RECOVERY_RESET'
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        client.save_context(output)
    assert output.read_bytes() == before
    root = tmp_path / 'checkout'
    root.mkdir(); (root / '.git').mkdir()
    with pytest.raises(ValueError, match='outside'):
        client.save_context(root / 'context.json')
