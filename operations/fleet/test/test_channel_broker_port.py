import asyncio
import sys
from types import SimpleNamespace

import pytest

from fleet.server.channel.broker_transport import exchange
from fleet.server.channel.conversation.runtime import ConversationConfig
from fleet.server.channel.model_runtime import BrokerConfig
from rosy.decision.conversation.codec import Profile, source_policy


def config(kind, **extra):
    data = dict(host='example', key_file='/run/rosy-deliberation/broker.key',
                known_hosts_file='/run/rosy-deliberation/known_hosts',
                source_commit='a'*40, valid_until=9999999999., primary_admitted=True)
    if kind is BrokerConfig:
        data.update(profile_revision='d720-test', reviewer_admitted=False)
    else:
        profile = Profile(revision='d728-test')
        data.update(profile=profile, policy=source_policy(data['source_commit'], profile),
                    semantic_evidence_sha256='b'*64)
    return kind(**data, **extra)


@pytest.mark.parametrize('kind', [BrokerConfig, ConversationConfig])
def test_fixed_openssh_port_preserves_legacy_default(kind):
    assert config(kind).ssh_port == 22
    assert config(kind, ssh_port=2222).ssh_port == 2222


@pytest.mark.parametrize('kind', [BrokerConfig, ConversationConfig])
@pytest.mark.parametrize('port', [True, 0, 443, 65536, '2222'])
def test_arbitrary_broker_ports_are_not_admitted(kind, port):
    with pytest.raises(ValueError):
        config(kind, ssh_port=port)


def test_ssh_uses_the_configured_openssh_listener(monkeypatch):
    original = asyncio.create_subprocess_exec
    seen = []

    async def spawn(*argv, **kwargs):
        seen.append(argv)
        return await original(sys.executable, '-c', "print('{}')", **kwargs)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    cfg = SimpleNamespace(host='example', key_file='/run/rosy-deliberation/broker.key',
                          known_hosts_file='/run/rosy-deliberation/known_hosts', ssh_port=2222)
    assert asyncio.run(exchange(cfg, 'rosy-conversation-v1', b'{}', 3)) == {}
    assert seen[0][seen[0].index('-p')+1] == '2222'
    assert 'StrictHostKeyChecking=yes' in seen[0]
    assert seen[0][-2:] == ('rosy-model-ingress@example', 'rosy-conversation-v1')


@pytest.mark.parametrize('port', [True, 443, '2222'])
def test_transport_refuses_an_unvalidated_port_before_spawn(port):
    with pytest.raises(ValueError, match='FIXED_BROKER_PORT_REQUIRED'):
        asyncio.run(exchange(SimpleNamespace(ssh_port=port), 'rosy-conversation-v1', b'{}', 3))
