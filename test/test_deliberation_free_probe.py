import importlib
import json

import pytest


def subjects():
    return (importlib.import_module('deploy.ai_pc.deliberation_free_codec'),
            importlib.import_module('deploy.ai_pc.deliberation_free_gateway'),
            importlib.import_module('deploy.ai_pc.deliberation_free_probe'))


def payload(codec):
    p = codec.PROBLEM
    return dict(schema_version=2, profile_revision=codec.PROFILE.profile_revision,
        subject_id=p.subject_id, case_id=p.case_id, generation=p.generation, input_hash=p.digest,
        verdict='abstain', alternatives=[dict(choice='human', probability=.5),
                                       dict(choice='reobserve', probability=.5)],
        evidence_ids=list(p.evidence_ids), missing_evidence=[], objections=[],
        next_step=None, success_check=None)


def response(codec):
    return dict(id='synthetic-response', model=codec.MODEL,
        choices=[dict(finish_reason='stop', message=dict(role='assistant', content=json.dumps(payload(codec))))],
        usage=dict(prompt_tokens=2000, completion_tokens=1024, total_tokens=3024,
                   completion_tokens_details=dict(reasoning_tokens=1000)))


def test_fixed_free_config_and_synthetic_v2_no_runtime_admission():
    codec, gate, probe = subjects()
    config = probe.config()
    assert config['model'] == config['small_model'] == 'opencode/mimo-v2.6-flash-free'
    assert config['enabled_providers'] == ['opencode']
    assert 'zai-coding-plan' not in json.dumps(config) and 'openrouter' not in json.dumps(config)
    assert config['permission'] == 'deny' and config['agent']['rosy']['steps'] == 1
    assert config['provider']['opencode']['models'][codec.MODEL]['limit']['output'] == 1024
    assert probe.FreeLauncher.cost_verified is False
    assert gate.UPSTREAM == 'https://opencode.ai/zen/v1/chat/completions'
    assert gate.claim.__module__ == 'deploy.ai_pc.deliberation_smoke_budget'
    from deploy.ai_pc.deliberation_smoke_budget import MARKER
    assert str(MARKER) == '/var/lib/rosy-deliberation/smoke/glm-first-review.spent'
    assert codec.trusted_body(codec.body())[0] == codec.PROBLEM
    checked = codec.checked_response(response(codec))
    assert checked['usage']['completion_tokens'] == 1024


@pytest.mark.parametrize('change', ['subject', 'case', 'schema', 'prior', 'url', 'instruction'])
def test_not_exact_synthetic_job_refused_before_upstream(change):
    codec, _, _ = subjects()
    body = json.loads(codec.body())
    if change == 'subject': body['problem']['subject_id'] = 'real-robot'
    elif change == 'case': body['problem']['case_id'] = 'other'
    elif change == 'schema': body['schema']['additionalProperties'] = True
    elif change == 'prior': body['prior'] = [{}]
    elif change == 'url': body['url'] = 'https://paid.invalid'
    else: body['instruction'] = 'execute tools'
    with pytest.raises(ValueError): codec.trusted_body(json.dumps(body))


@pytest.mark.parametrize('change', ['paid', 'tokens', 'reasoning', 'tool', 'scope', 'length'])
def test_wrong_or_unbounded_free_response_is_hold(change):
    codec, _, _ = subjects()
    data = response(codec)
    if change == 'paid': data['model'] = 'mimo-v2.6-flash'
    elif change == 'tokens': data['usage'].update(completion_tokens=1025, total_tokens=3025)
    elif change == 'reasoning': data['usage']['completion_tokens_details']['reasoning_tokens'] = 1025
    elif change == 'tool': data['choices'][0]['message']['tool_calls'] = [{}]
    elif change == 'length': data['choices'][0]['finish_reason'] = 'length'
    else:
        wrong = payload(codec); wrong['case_id'] = 'foreign'
        data['choices'][0]['message']['content'] = json.dumps(wrong)
    with pytest.raises(ValueError): codec.checked_response(data)


def test_free_upstream_fixed_headers_no_identity_spoof_no_redirect(monkeypatch):
    codec, gate, _ = subjects()
    seen = []
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            assert limit == 16385
            return json.dumps(response(codec)).encode()
    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            assert 0 < timeout <= 30
            return Reply()
    monkeypatch.setattr(gate.urllib.request, 'build_opener', lambda *args: Opener())
    gate.upstream({'model': codec.MODEL}, 'fake-unit-key', 1,
                  {'User-Agent': 'actual-sdk-fixture', 'Authorization': 'untrusted', 'Cookie': 'untrusted'})
    assert len(seen) == 1 and seen[0].full_url == gate.UPSTREAM
    headers = dict((k.lower(), v) for k, v in seen[0].header_items())
    assert headers['authorization'] == 'Bearer fake-unit-key'
    assert headers['user-agent'] == 'actual-sdk-fixture' and 'cookie' not in headers
