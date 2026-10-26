"""The SDK boundary receives explicit credentials, provider endpoint and namespaced bytes."""
from io import BytesIO
import sys
from types import SimpleNamespace

from storage_hub import StorageHub


def test_sdk_commit_uses_fixed_provider_and_explicit_connection(monkeypatch):
    stored = {}
    class Client:
        def __init__(self, *, endpoint=None, token=None):
            if endpoint != 'https://huggingface.co' or token != 'hf_private_fixture':
                raise PermissionError('provider refused implicit endpoint or credentials')
        def repo_info(self, **kwargs): return SimpleNamespace(private=True, sha='a' * 40)
        def create_commit(self, **kwargs):
            for operation in kwargs['operations']:
                stored[operation.path_in_repo] = operation.path_or_fileobj.read()
            return SimpleNamespace(oid='b' * 40)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(HfApi=Client, CommitOperationAdd=SimpleNamespace))
    assignment = dict(id='d' * 32, repo_id='team/data', repo_type='dataset')
    result = StorageHub().commit(assignment, {'data.json': BytesIO(b'{"frame":1}')}, 'hf_private_fixture')
    assert result == 'b' * 40
    assert stored == {'bundles/' + 'd' * 32 + '/data.json': b'{"frame":1}'}
