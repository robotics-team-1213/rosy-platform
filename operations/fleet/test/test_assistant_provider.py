"""Console broker is independently admitted and bound to the original request."""
import asyncio
import json

import pytest


def configuration():
    from fleet.server.assistant.provider import OperatorConfig
    return OperatorConfig(host='ai-host', ssh_port=2222, key_file='/run/rosy-deliberation/broker.key',
        known_hosts_file='/run/rosy-deliberation/known_hosts', source_commit='a'*40,
        semantic_evidence_sha256='b'*64, valid_until=4102444800., primary_admitted=True)


def question():
    from rosy.decision.conversation.operator import OperatorInput, OperatorScope
    return OperatorInput(scope=OperatorScope(principal_id='alice', conversation_id='conv-1'),
                         request_id='req-1', question='안녕', observed_at=1000., facts=[])


def test_console_provider_binds_scope_policy_and_result(monkeypatch):
    from fleet.server.assistant import provider
    cfg = configuration()
    seen = []

    async def exchange(config, command, packet, remaining):
        data = json.loads(packet)
        seen.append((command, data))
        return {k:data[k] for k in ('source_commit', 'profile', 'input_hash', 'semantic_evidence_sha256')} | {
            'answer':dict(kind='CHAT', response='안녕하세요.', evidence_refs=[]), 'cost_usd':0.}

    monkeypatch.setattr(provider, 'exchange', exchange)
    value = asyncio.run(provider.OperatorProvider(cfg)(question(), 30))
    assert value['kind'] == 'CHAT' and cfg.admitted()
    command, packet = seen[0]
    assert command == 'rosy-conversation-v1'
    assert packet['schema'] == 'rosy.operator-request/1'
    assert packet['question']['scope']['source'] == 'console'
    assert packet['policy']['authority'] == 'read_only'
    assert 'guild_id' not in packet['question']


def test_provider_rejects_foreign_result_and_legacy_admission(monkeypatch):
    from fleet.server.assistant import provider
    cfg = configuration()

    async def wrong(*_): return dict(source_commit='x', answer={})
    monkeypatch.setattr(provider, 'exchange', wrong)
    with pytest.raises(ValueError):
        asyncio.run(provider.OperatorProvider(cfg)(question(), 30))
    from fleet.server.channel.conversation.runtime import ConversationConfig
    with pytest.raises(ValueError):
        provider.OperatorConfig.model_validate(ConversationConfig.model_fields)
    assert not cfg.model_copy(update={'primary_admitted':False}).admitted()
    assert not cfg.model_copy(update={'valid_until':1.}).admitted()


def test_ai_broker_dispatch_selects_only_console_contract(monkeypatch):
    from deploy.ai_pc import operator_broker
    from rosy.decision.conversation.operator import OperatorProfile, operator_policy
    cfg = configuration()
    profile = OperatorProfile()
    packet = {'schema':'rosy.operator-request/1', 'source_commit':cfg.source_commit,
        'profile':profile.model_dump(), 'policy':operator_policy(cfg.source_commit),
        'semantic_evidence_sha256':cfg.semantic_evidence_sha256,
        'input_hash':question().digest, 'question':question().model_dump(), 'remaining':30}
    monkeypatch.setattr(operator_broker, 'execute', lambda *_:dict(kind='CHAT', response='안녕하세요.', evidence_refs=[]))
    output = asyncio.run(operator_broker.dispatch(packet, cfg.model_dump(), profile))
    assert output['input_hash'] == question().digest
    packet['question']['scope']['source'] = 'discord'
    with pytest.raises(ValueError):
        asyncio.run(operator_broker.dispatch(packet, cfg.model_dump(), profile))


def test_independent_operator_receipt_requires_every_bound_case():
    from deploy.ai_pc.operator_acceptance import CASES, validate_receipt
    from rosy.decision.conversation.operator import OperatorProfile
    from rosy.decision.conversation.codec import digest
    profile = OperatorProfile()
    cfg = dict(source_commit='a'*40, files={'source.py':'b'*64})
    receipt = dict(schema='rosy.operator-evaluation/1', evaluation_owner='model_pc', verdict='PASS',
        evaluated_at=__import__('time').time(), suite_sha256=digest(CASES),
        source_commit='a'*40, profile=profile.model_dump(), source_manifest_sha256=digest(cfg['files']),
        cases=[dict(name=name, passed=True) for name, _, _ in CASES])
    validate_receipt(receipt, cfg, profile)
    receipt['cases'] = receipt['cases'][:-1]
    with pytest.raises(ValueError): validate_receipt(receipt, cfg, profile)


def test_operator_inference_schema_never_requests_freeform_completion_prose(monkeypatch):
    from deploy.ai_pc import operator_broker
    from rosy.decision.conversation.operator import OperatorProfile
    monkeypatch.setattr(operator_broker, 'loaded', lambda _:None)
    seen = []
    def exchange(path, body, remaining):
        if path == '/api/ps': return {}
        seen.append(body)
        return {'model':OperatorProfile().model_id, 'done':True, 'done_reason':'stop',
                'eval_count':1, 'prompt_eval_count':1,
                'message':{'role':'assistant', 'content':json.dumps(dict(kind='CHAT', response='Classified', evidence_refs=[]))}}
    monkeypatch.setattr(operator_broker, 'exchange', exchange)
    assert operator_broker.execute(question(), OperatorProfile(), 30)['kind'] == 'CHAT'
    assert seen[0]['format']['properties']['response']['enum'] == ['Classified']
    assert question().question in seen[0]['messages'][1]['content']
