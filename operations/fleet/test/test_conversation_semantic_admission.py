"""A protected manifest hash does not establish successful semantic evaluation."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from deploy.ai_pc import deliberation_conversation_broker as broker
from rosy.decision.conversation.codec import Profile, source_policy


def host_configuration(monkeypatch, raw):
    import pwd
    profile = Profile(revision='d728-test')
    cfg = {'source_commit': 'a'*40, 'profile': profile.model_dump(),
           'policy': source_policy('a'*40, profile), 'valid_until': 9999999999.,
           'semantic_evidence_sha256': hashlib.sha256(raw).hexdigest(),
           'files': {'proof.json': hashlib.sha256(raw).hexdigest()}}
    monkeypatch.setattr(pwd, 'getpwnam', lambda _: SimpleNamespace(pw_uid=997))
    monkeypatch.setattr(broker.os, 'getuid', lambda: 997)
    monkeypatch.setattr(broker, 'protected', lambda p: json.dumps(cfg).encode()
                        if p == broker.CONFIG else raw)
    return cfg, profile


@pytest.mark.parametrize('raw', [b'proof', b'{}', b'{"verdict":"PASS"}',
                                b'{"verdict":"PASS","cases":[]}'])
def test_manifest_hash_alone_never_admits_conversation(monkeypatch, raw):
    host_configuration(monkeypatch, raw)
    with pytest.raises(ValueError):
        broker.configuration()
